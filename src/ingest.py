#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extracts fact candidates from a folder of source material.

Turns the files in a folder (md, txt, pdf, docx, pptx, images; scanned PDFs and images go through tesseract OCR) into
text and asks the LLM (src/llm.py) for fact candidates piece by piece. Every candidate comes with a verbatim quote, which
is checked against the real source text, and a candidate whose quote is not there is dropped (the first guard against
invented facts). A person confirms the remaining candidates before they move into the profile (docs/DOCUMENTS.md).
This script never edits the profile.

  offerowl ingest <folder or file> ...     # the candidates go to output/_ingest/candidates.json
  offerowl ingest --text <file>            # only the text conversion, no LLM (to check the conversion)

It runs on the host (the LLM CLI is on the host). Without an LLM (OFFEROWL_LLM=none) it stops after the text conversion.
"""
import html  # entities in docx and pptx
import json  # saving the candidates
import pathlib  # file paths
import re  # pulling text out of XML, tidying whitespace
import subprocess  # tesseract, and the typesetting image
import sys  # command-line arguments
import zipfile  # docx and pptx are zip files of XML

import factcheck as F  # the fact-checking rules, kept in one place
import llm  # the LLM connection
import pdftools  # the text and page pictures of a PDF, with poppler or PDFium

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
OUT = ROOT / "output" / "_ingest" / "candidates.json"  # where the candidates are saved (personal data, so it stays outside git)
CHUNK = 12000  # characters per piece. Too long and facts near the end are missed, too short and the number of calls grows
KINDS = ("role", "project", "education", "skill", "paper", "patent", "award", "certificate", "other")  # candidate kinds

# extraction instructions. Only one output format is asked for (adding a format made the remaining reads worse in extraction trials)
SYSTEM = (
    "You extract career facts from a person's documents for their resume. "
    "Return only JSON. Never invent anything: every fact must be supported by a quote copied character for character from the text."
)
PROMPT = """Text from the file "{name}" (part {part} of {parts}):

<<<
{text}
>>>

List every career fact in this text: jobs and roles, projects, education, skills, papers, patents, awards, certificates.
One item per fact. Keep the text's own language.

Return JSON: {{"facts": [{{"kind": one of {kinds}, "org": company or school or "", "period": dates as written or "",
"title": short name, "statement": one sentence of what was done or achieved, "quote": exact substring of the text that supports it (under 200 characters)}}]}}"""


IMAGES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")  # image files that are read with OCR
MAX_PART = 64_000_000  # bytes of one XML part of a .docx or .pptx once inflated: a 300-page document's is a few MB
MSG = {  # what this step says, in both languages with the same keys
    "en": {
        "quote_short": "the quote is too short",
        "quote_missing": "the quote is not in the source",
        "title_missing": "the title is not in the source",
        "org_missing": "the company is not in the source",
        "no_text": "no text (a format it cannot read, or a scan with no OCR on this PC)",
        "bad_answer": "the answer's form: {why}",
        "not_a_list": "the answer's facts are not a list",
        "no_llm": "The AI backend cannot be used ({why}). The last candidate file stays as it is. Text read from the files: {sizes}",
        "size": "{name} {n} characters",
        "done": "{files} files, {kept} candidates kept ({kinds}), {dropped} dropped for lack of evidence, {orgs} companies -> {out}",
        "stopped": "  The AI backend stopped part way ({why}), so this holds the candidates found until then. Run it again for the other files",
    },
    "ko": {
        "quote_short": "인용이 너무 짧다",
        "quote_missing": "인용이 원문에 없다",
        "title_missing": "제목이 원문에 없다",
        "org_missing": "회사가 원문에 없다",
        "no_text": "글 없음(형식 미지원이거나 OCR 로도 못 읽음)",
        "bad_answer": "응답 형식: {why}",
        "not_a_list": "응답의 facts 가 목록이 아니다",
        "no_llm": "LLM 을 쓸 수 없다({why}). 지난 후보 파일은 그대로 둔다. 글 변환만 확인: {sizes}",
        "size": "{name} {n}자",
        "done": "파일 {files}개, 후보 {kept}개 채택({kinds}), 근거 없어 버림 {dropped}개, 회사 {orgs}곳  -> {out}",
        "stopped": "  LLM 이 중간에 멈춰({why}) 그때까지 뽑은 후보만 담았다. 남은 파일은 다시 돌린다",
    },
}


def t(key: str, **kw) -> str:
    """A message of this step in the person's language."""
    return llm.message(MSG, key, **kw)


CONTAINER_TIMEOUT = 600  # seconds one file may take in the image (a long scan at 300 dpi), so a hung tool never holds a reading


def in_container(path: pathlib.Path, make_script) -> str:
    """Reads one file with the tools of the typesetting image (tesseract, pdftotext). The container sees only the repository,
    so the file is copied to a folder of its own under output/_ingest/ for a moment and removed afterwards: two readings at
    once (a material and a form's screenshot) never share it. Empty text when the tools hang past the time limit.
    make_script(file name) returns the shell line to run inside that folder"""
    import shutil  # temporary copy
    import tempfile  # a folder of this call's own
    base = ROOT / "output" / "_ingest"
    base.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="_ocr-", dir=base))  # unique, inside the repository the container mounts
    try:
        src = work / ("in" + path.suffix.lower())
        shutil.copy(path, src)
        rel = src.relative_to(ROOT)
        script = f"cd /work/{rel.parent} && " + make_script(src.name)
        inside = pathlib.Path("/.dockerenv").exists()  # already inside a container (tests): run directly, on the host go through render/run.sh
        try:
            r = subprocess.run((["bash", "-c", script.replace("/work/", str(ROOT) + "/")] if inside else [str(ROOT / "render" / "run.sh"), "bash", "-c", script]),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CONTAINER_TIMEOUT)
        except subprocess.TimeoutExpired:  # a hung tool: the file counts as one without text, and the reading goes on
            return ""
        return r.stdout
    finally:
        shutil.rmtree(work, ignore_errors=True)  # the copy goes, whatever happened


def win_ocr(picture) -> str:
    """One picture's lines read by the OCR engine Windows ships (apps/api/winocr.ps1): the Korean engine, else the English one.
    Empty when neither language's pack is on this PC."""
    script = ROOT / "apps" / "api" / "winocr.ps1"  # beside the API, in the repository and in the app alike
    for lang in ("ko", "en-US"):  # Korean reads Latin letters too; English when Korean has no pack here
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(picture), lang],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)  # never left waiting
        except (OSError, subprocess.TimeoutExpired):  # no PowerShell, or it hung
            return ""
        if r.returncode == 0 and r.stdout.strip():  # read
            return r.stdout
    return ""


def ocr(path: pathlib.Path, block: bool = False) -> str:
    """Reads a scanned PDF or an image with tesseract (Korean and English): the one on this PC when there is one, else the
    one in the typesetting image. A PDF is turned into a 300 dpi image per page and then read, an image is read directly.
    Pages are separated by two blank lines. Empty text when neither is here: the caller reports a file it could not read.
    block reads a screenshot of a form as one block of lines in order (tesseract's --psm 6), from a copy twice the size,
    since a screen's small letters read badly at their own size"""
    import tempfile  # a folder for this reading's copies, removed with it
    with tempfile.TemporaryDirectory(prefix="offerowl-ocr-") as scratch:  # the enlarged copy of a person's screenshot never stays behind
        return _ocr(path, block, pathlib.Path(scratch))


def _ocr(path: pathlib.Path, block: bool, scratch: pathlib.Path) -> str:
    """ocr(), with a folder for its copies."""
    import shutil  # is tesseract here?
    import tempfile  # the page pictures
    psm = ["--psm", "6"] if block else []  # a form's lines in order, never split into columns
    if block and path.suffix.lower() != ".pdf":  # a screenshot: twice the size, when Pillow is here
        try:
            from PIL import Image  # the enlarging
            big = scratch / ("big" + path.suffix.lower())  # a copy beside nothing of the person's, gone with the folder
            im = Image.open(path)
            im.resize((im.width * 2, im.height * 2), Image.LANCZOS).save(big)
            path = big
        except Exception:  # noqa: BLE001  no Pillow, or a picture it cannot open: read as it is
            pass
    if shutil.which("tesseract") and pdftools.reader():  # on this PC, with no container
        def read(picture) -> str:  # one picture's words
            try:
                r = subprocess.run(["tesseract", str(picture), "stdout", "-l", "kor+eng", *psm], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=CONTAINER_TIMEOUT)  # a hung tesseract never holds the reading
            except subprocess.TimeoutExpired:  # read as a picture without text
                return ""
            return r.stdout if r.returncode == 0 else ""
        if path.suffix.lower() != ".pdf":  # an image is read directly
            return read(path)
        with tempfile.TemporaryDirectory() as tmp:  # the page pictures go with it
            return "\n\n".join(read(p) for p in pdftools.render_png(path, pathlib.Path(tmp) / "pg", dpi=300))
    if sys.platform == "win32":  # Windows reads pictures itself (Windows.Media.Ocr), with no tesseract and no Docker
        if path.suffix.lower() != ".pdf":  # an image is read directly
            return win_ocr(path)
        if pdftools.reader():  # a scanned PDF: its pages as pictures first
            with tempfile.TemporaryDirectory() as tmp:
                return "\n\n".join(win_ocr(p) for p in pdftools.render_png(path, pathlib.Path(tmp) / "pg", dpi=300))
    if not (ROOT / "render" / "run.sh").is_file() or not shutil.which("docker"):  # the one-file app, or a PC without Docker: nothing can read a scan here
        return ""
    return in_container(path, lambda n: (f"pdftoppm -r 300 -png {n} pg && for f in $(ls pg-*.png | sort -V); do tesseract $f stdout -l kor+eng 2>/dev/null; printf '\\n\\n'; done"
                                         if n.endswith(".pdf") else f"tesseract {n} stdout -l kor+eng {' '.join(psm)} 2>/dev/null"))


def pdftotext(path: pathlib.Path) -> str:
    """The text layer of a PDF, with poppler or PDFium on this PC, else with the pdftotext of the typesetting image"""
    if pdftools.reader():  # no container needed
        return pdftools.text(path, layout=True)
    return in_container(path, lambda n: f"pdftotext -layout {n} -")


# shape of the answer (JSON Schema). Passed to backends that accept an output schema (codex). To satisfy strict mode every
# object sets additionalProperties false and lists every field as required
FACTS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["facts"],
    "properties": {"facts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "org", "period", "title", "statement", "quote"],
        "properties": {"kind": {"type": "string", "enum": list(KINDS)}, "org": {"type": "string"}, "period": {"type": "string"},
                       "title": {"type": "string"}, "statement": {"type": "string"}, "quote": {"type": "string"}}}}},
}


def to_text(path: pathlib.Path) -> str:
    """One file as text. An unknown format gives empty text. A PDF without a text layer (a scan) and images go through OCR"""
    suf = path.suffix.lower()  # extension
    if suf in IMAGES:  # image: OCR
        return ocr(path)
    if suf in (".md", ".txt", ".csv", ".json", ".yaml", ".yml"):  # already text
        return path.read_text(encoding="utf-8", errors="replace")
    if suf == ".pdf":  # PDF text layer. With almost no characters per page it is taken for a scan and read with OCR
        t = pdftotext(path)
        pages = max(1, t.count("\f"))
        return t if len(t.strip()) / pages >= 40 else ocr(path)
    if suf in (".docx", ".pptx"):  # pieces of text from the XML inside the zip
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist()  # body XML (docx) or slide XML (pptx, in slide order)
                           if n == "word/document.xml" or re.match(r"ppt/slides/slide\d+\.xml$", n))
            names.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)) if "slide" in n else 0)
            parts = []
            for n in names:
                if z.getinfo(n).file_size > MAX_PART:  # a part far larger than any document's (a zip bomb): left out, never inflated
                    continue  # zipfile checks the size it inflates against this one, so a part cannot claim less
                xml = z.read(n).decode("utf-8", errors="replace")
                xml = re.sub(r"</w:p>|</a:p>|<w:br/>|<a:br/>|<w:cr/>", "\n", xml)  # paragraph ends and line breaks
                xml = re.sub(r"<w:tab/>", "\t", xml)  # tabs (without them the dates in table cells ran together)
                parts.append(html.unescape(re.sub(r"<[^>]+>", "", xml)))  # strip the tags and turn entities such as &amp; into characters
            return "\n".join(parts)
    return ""


def files_in(args) -> list[pathlib.Path]:
    """The files to read from the folders and files given as arguments"""
    out = []
    for a in args:
        p = pathlib.Path(a)
        out += sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]  # a folder gives everything below it
    return [p for p in out if not p.name.startswith((".", "~$"))]  # skip hidden files and Office lock files


def chunks(text: str) -> list[tuple[int, str]]:
    """Splits the text into (start offset, piece). Cuts at a blank line when possible"""
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + CHUNK)  # maximum length
        if j < len(text):
            k = text.rfind("\n\n", i + CHUNK // 2, j)  # the last blank line in the second half of the piece
            j = k if k > 0 else j
        out.append((i, text[i:j]))
        i = j
    return out


def norm(s: str) -> str:
    """For quote matching: collapses whitespace to one space (hides differences in line breaks and PDF spacing)"""
    return re.sub(r"\s+", " ", s).strip()


def grounded(fact: dict, piece: str) -> str | None:
    """Whether the candidate rests on the source text: the reason when there is a problem, None otherwise"""
    q = norm(fact.get("quote") or "")
    if len(q) < 4:  # a quote under 4 characters is no evidence (a 7-character quote like 'IEEE' plus a two-character Korean word still passes)
        return t("quote_short")
    if q not in norm(piece):  # the quote is not in the source verbatim (only whitespace differences are allowed)
        return t("quote_missing")
    # Numbers (with units), number words, English words (tool names) and company or institution names in the statement, title
    # and period must occur in the source piece (src/factcheck.py). The period becomes the start and end of the career entry
    # as it is, so an invented period must not pass. Numbers are compared as (value, unit) tokens, not as substrings of the
    # piece, so '23%' does not pass because of '2023.05'. English words of the statement and title are checked too
    claims = " ".join(str(fact.get(k) or "") for k in ("statement", "title", "period"))
    bad = F.unsupported(claims, piece)
    if bad:
        return "; ".join(bad)
    flat = norm(piece).replace(" ", "")  # the source without spaces
    # for roles, education and certificates the title becomes a resume field as written, so it must be in the source (an
    # invented title such as 'CTO' would otherwise pass)
    if fact.get("kind") in ("role", "education", "certificate") and fact.get("title") and norm(fact["title"]).replace(" ", "") not in flat:
        return t("title_missing")
    if fact.get("org") and org_key(fact["org"]) and org_key(fact["org"]) not in org_key(piece):  # the company name must be in the source too
        return t("org_missing")
    return None


def org_key(org: str) -> str:
    """Key for grouping company names: drops the Korean company-form markers (parenthesized or spelled out, both meaning
    'Co., Ltd.'), parenthesized text and whitespace, so a name with and without the marker gets the same key"""
    s = re.sub(r"\(주\)|주식회사|\([^)]*\)", "", org or "")
    return re.sub(r"\s+", "", s).lower()


def dedupe(kept: list) -> list:
    """Merges candidates with the same kind, company and title (the title without whitespace and punctuation). When the same
    fact is in several files, as in a resume and a portfolio, the review screen would make people confirm the same thing
    several times. The candidate with the longest statement is kept and all sources are collected"""
    # the title loses whitespace and punctuation but keeps + # . so that C, C# and C++ stay apart. When the title is empty, the statement tells them apart
    word = lambda s: re.sub(r"[^\w+#.]+|_", "", (s or "").lower()).strip(".")  # the trailing period is dropped (the dot inside Node.js stays)
    key = lambda f: (f["kind"], f.get("org_key", ""), word(f.get("title")) or "문장:" + word(f.get("statement")))
    groups = {}
    for f in kept:
        groups.setdefault(key(f), []).append(f)
    out = []
    for fs in groups.values():
        best = max(fs, key=lambda f: len(f.get("statement") or ""))  # the one with the longest statement
        best = {**best, "sources": [f["source"] for f in fs]}  # every place the same fact came from
        out.append(best)
    return out


class Partial(Exception):
    """The LLM stopped midway. Carries the candidates extracted so far and the number of pieces that were asked"""

    def __init__(self, why, kept, dropped, asked):
        super().__init__(why)
        self.kept, self.dropped, self.asked = kept, dropped, asked


def extract(paths, backend=None, texts=None, stop=None):
    """Extracts candidates from the files and returns (kept, dropped). When the response for one piece is wrong, it moves on to
    the next piece and records the reason in dropped (one malformed response must not lose the earlier results). When there
    is no LLM at all, LLMUnavailable is raised unchanged. stop() true before a piece ends it with Partial("stopped"): the
    person asked, and what was read so far is kept"""
    kept, dropped, asked = [], [], 0  # asked: the number of pieces that got an answer
    texts = texts if texts is not None else {}
    for path in paths:
        text = texts.setdefault(str(path), to_text(path))  # convert once (OCR is slow)
        if not text.strip():  # a file without text
            dropped.append({"file": str(path), "why": t("no_text")})
            continue
        parts = chunks(text)
        for n, (start, piece) in enumerate(parts, 1):
            if stop and stop():  # the person stopped it: no more pieces are sent
                raise Partial("stopped", dedupe(kept), dropped, asked)
            prompt = PROMPT.format(name=path.name, part=n, parts=len(parts), text=piece, kinds="|".join(KINDS))
            try:
                data = llm.run("ingest", prompt, system=SYSTEM, want_json=True, required=("facts",), backend=backend, timeout=600,
                               schema=FACTS_SCHEMA)
            except llm.LLMUnavailable as e:  # the LLM stopped (limit, timeout, connection): leave with what was extracted so far
                raise Partial(str(e), dedupe(kept), dropped, asked)
            except ValueError as e:  # the format was wrong even after asking twice
                dropped.append({"file": str(path), "offset": start, "why": t("bad_answer", why=e)})
                continue
            asked += 1
            facts = data.get("facts") if isinstance(data, dict) else None
            if not isinstance(facts, list):
                dropped.append({"file": str(path), "offset": start, "why": t("not_a_list")})
                continue
            for f in facts:
                if not isinstance(f, dict):  # an element that is not an object, such as a bare line of text
                    continue
                f = {k: (v if isinstance(v, str) else ("" if v is None else str(v))) for k, v in f.items()}  # make every field a string
                f["source"] = {"file": str(path), "offset": start}  # source: the file and where the piece starts
                if f.get("kind") not in KINDS:  # unknown kinds become other
                    f["kind"] = "other"
                f["org_key"] = org_key(f.get("org", ""))  # group the same company
                why = grounded(f, piece)  # check against the source
                if why:
                    f["why"] = why
                (dropped if why else kept).append(f)  # without support the candidate is dropped
    return dedupe(kept), dropped


def main() -> int:
    if "--text" in sys.argv:  # conversion only
        print(to_text(pathlib.Path(sys.argv[sys.argv.index("--text") + 1])))
        return 0
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    paths = files_in(args)
    texts = {}  # the converted texts (so they are not converted again when there is no LLM)
    stopped = None
    try:
        kept, dropped = extract(paths, texts=texts)
    except Partial as e:  # the LLM stopped
        if not e.asked:  # not one piece got an answer: do not overwrite the previous candidate file with an empty one
            sizes = ", ".join(t("size", name=p.name, n=len(texts[str(p)]) if str(p) in texts else len(to_text(p))) for p in paths)
            print(t("no_llm", why=e, sizes=sizes))
            return 2
        stopped, kept, dropped = str(e), e.kept, e.dropped
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"kept": kept, "dropped": dropped}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    by = {}
    for f in kept:
        by[f["kind"]] = by.get(f["kind"], 0) + 1
    print(t("done", files=len(paths), kept=len(kept), kinds=", ".join(f"{k} {v}" for k, v in sorted(by.items())), dropped=sum(1 for d in dropped if "quote" in d),
            orgs=len({f["org_key"] for f in kept if f["org_key"]}), out=OUT.relative_to(ROOT)))
    if stopped:
        print(t("stopped", why=stopped[:120]))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
