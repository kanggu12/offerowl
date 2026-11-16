#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Visual baselines: the pages of the copy that last went out, kept as small pictures, and what a later build changed.

An edition's page pictures (the previews a build draws: r-1.png for the resume, d-1.png for the deck, c-1.png for the
cover letter) are kept in one small form when the edition is exported: shrunk to two thirds by a box filter, each colour
channel rounded to six levels (a fixed palette of 216 colours). A later build's pictures are put in the same form and
compared pixel by pixel. The drawing is deterministic for one PDF reader, so an unchanged page is the same picture in this
form, while a changed letter, a moved highlight or a line that broke elsewhere is not. The rows that differ are grouped
into bands, and one picture shows each changed band as before | now, so a change nobody asked for is seen before the
edition goes out again.

    python3 src/baseline.py compare <old.pdf> <new.pdf> [--picture out.png] [--json out.json] [--dpi 110]
        two PDFs page by page (the same check the panel runs on an edition): exit 0 when no page changed, 1 when one did
    python3 src/baseline.py keep <preview folder> <kept folder> [--record JSON]  the kept form of a build's pictures
    python3 src/baseline.py diff <preview folder> <kept folder> [--picture out.png] [--json out.json]
    python3 src/baseline.py show <job> [--lang ko|en] [--data DIR]               what the last build of an edition changed
    python3 src/baseline.py accept <job> [--lang ko|en] [--data DIR]             keep that build as the edition's baseline

`show` and `accept` are the command line's way to the panel's baseline (`offerowl baseline ...` runs this file): they go
through the same HTTP API in this process, as `offerowl api` does.
"""
import json  # the result as JSON, and the kept folder's record
import pathlib  # paths
import re  # the page number in a picture's name
import sys  # the command line
import tempfile  # pages drawn from two PDFs

ROOT = pathlib.Path(__file__).resolve().parent.parent  # the repository root, one level above src/
sys.path.insert(0, str(ROOT / "src"))  # llm.py and pdftools.py beside this file, however it was started
import llm  # noqa: E402  the message helper and the language setting

PREFIXES = {"r": "resume", "d": "deck", "c": "cover"}  # the previews' name prefixes (apps/api/tasks.py _previews) and the document each is
SHRINK = 1.5  # the kept pictures are two thirds of the previews: 73 dpi for a page drawn at 110, 53 for a slide drawn at 80
LEVELS = 6  # values each colour channel keeps: six levels make a fixed palette of 216 colours, the same for every picture
STEP = 255 / (LEVELS - 1)  # the distance between two levels (51)
GAP = 12  # rows that differ within this many rows of each other are one band: a line of text is about 14 rows at 73 dpi
MIN_PIXELS = 3  # a band with fewer changed pixels is no change one could see (unchanged pages differ in none at all)
PAD = 6  # rows above and below a band that the picture shows with it, so the line around the change can be read
MAX_ROWS = 260  # rows of one band in the picture: a page that changed from top to bottom shows its top part
MAX_PAGES = 12  # changed pages of one document drawn in the picture; the list in words names them all
MAX_BANDS = 6  # bands of one page drawn; the rest are on the page itself
RECORD = "baseline.json"  # the kept folder's record: when, why, from which reader, how many pages of each document
MSG = {  # what this tool says, in both languages with the same keys
    "en": {
        "resume": "Resume",
        "deck": "Portfolio deck",
        "cover": "Cover letter",
        "page": "{doc}, page {n}: before | now",
        "slide": "{doc}, slide {n}: before | now",
        "same": "{doc}: no page changed (pages: {after})",
        "changed": "{doc}: pages changed: {pages} (pages before: {before}, now: {after})",
        "picture": "the changed parts, before | now: {file}",
        "no_pages": "no pages could be drawn from {file}",
        "usage": "usage: python3 src/baseline.py compare <old.pdf> <new.pdf> [--picture out.png] [--json out.json]",
        "no_build": "{job} ({lang}) has no typeset edition yet: make its PDFs first",
        "no_baseline": "{job} ({lang}): no baseline yet. Exporting the edition keeps one, or accept this build as one",
        "since": "{job} ({lang}): compared with the baseline kept on {at}",
        "nothing": "  no page changed",
        "other_reader": "  the baseline was drawn by another PDF reader, so the pages cannot be compared: accept this build as the baseline",
        "accepted": "{job} ({lang}): this build is the baseline now ({at})",
    },
    "ko": {
        "resume": "이력서",
        "deck": "포트폴리오",
        "cover": "자기소개서",
        "page": "{doc} {n}쪽: 이전 | 지금",
        "slide": "{doc} {n}장: 이전 | 지금",
        "same": "{doc}: 바뀐 쪽 없음 (모두 {after}쪽)",
        "changed": "{doc}: 바뀐 쪽 {pages} (이전 {before}쪽, 지금 {after}쪽)",
        "picture": "바뀐 부분, 이전 | 지금: {file}",
        "no_pages": "{file}에서 쪽을 그리지 못했다",
        "usage": "쓰는 법: python3 src/baseline.py compare <이전.pdf> <지금.pdf> [--picture out.png] [--json out.json]",
        "no_build": "{job} ({lang}): 조판한 판이 아직 없다. 먼저 PDF를 만든다",
        "no_baseline": "{job} ({lang}): 기준선이 아직 없다. 판을 내보내면 남고, 이 빌드를 기준선으로 받을 수도 있다",
        "since": "{job} ({lang}): {at}에 남긴 기준선과 견줬다",
        "nothing": "  바뀐 쪽 없음",
        "other_reader": "  기준선을 다른 PDF 읽개가 그려 쪽을 견줄 수 없다. 이 빌드를 기준선으로 받는다",
        "accepted": "{job} ({lang}): 이 빌드가 이제 기준선이다 ({at})",
    },
}


def t(key: str, in_lang: str | None = None, **kw) -> str:
    """A message of this tool in the person's language, or in `in_lang` (the picture of an edition speaks the edition's
    language, whatever the panel's process was started in). A message's own {lang} stays a value among kw."""
    if in_lang in MSG:  # a language asked for by name
        text = MSG[in_lang].get(key) or MSG["en"][key]
        return text.format(**kw) if kw else text
    return llm.message(MSG, key, **kw)


def doc_word(doc: str, lang: str | None = None) -> str:
    """A document's name in the person's language, or in `lang`."""
    return t("resume", lang) if doc == "resume" else t("deck", lang) if doc == "deck" else t("cover", lang)


def palette() -> list:
    """The fixed palette of the kept form: every mix of six levels per channel, red slowest (index = r*36 + g*6 + b)."""
    levels = [round(i * STEP) for i in range(LEVELS)]  # 0, 51, 102, 153, 204, 255
    return [c for r in levels for g in levels for b in levels for c in (r, g, b)]  # 216 colours, three values each


def canon(src):
    """A page picture in the kept form: a P-mode image of two thirds the size whose palette is the fixed one. Two pictures of
    the same page give the same bytes in this form; a changed letter changes some of them. src: a path or an image."""
    from PIL import Image, ImageChops  # Pillow: the render container has it, and so do the desktop app and a PC with the pdf extra
    if isinstance(src, Image.Image):  # a picture already open
        im = src.convert("RGB")  # its colours as drawn
    else:  # a file: read whole and closed again, so a folder of them can be replaced on Windows
        with Image.open(src) as f:
            im = f.convert("RGB")
    w, h = im.size  # the preview's size
    small = im.resize((max(1, round(w / SHRINK)), max(1, round(h / SHRINK))), Image.BOX)  # a box filter: the same pixels give the same mean
    level = [min(LEVELS - 1, int(v / STEP + 0.5)) for v in range(256)]  # each value to its nearest level, once for all 256
    r, g, b = small.split()  # the three channels
    # the palette index r*36 + g*6 + b, worked out by Pillow's own arithmetic (at most 180 + 30 + 5, so nothing clips)
    index = ImageChops.add(ImageChops.add(r.point([36 * x for x in level]), g.point([6 * x for x in level])), b.point(level))
    out = Image.frombytes("P", small.size, index.tobytes())  # the kept form: the same bytes, read as palette indexes
    out.putpalette(palette())  # its colours, for the picture of the changes and for a person who opens the file
    return out


def pictures(folder: pathlib.Path, prefix: str) -> list:
    """The page pictures of one document in a folder (<prefix>-1.png ...), in page order (a name order would put 10 before 2)."""
    found = [p for p in pathlib.Path(folder).glob(f"{prefix}-*.png") if re.fullmatch(rf"{prefix}-\d+\.png", p.name)]  # only page pictures
    return sorted(found, key=lambda p: int(p.stem.split("-")[1]))  # by their number


def keep(previews: pathlib.Path, dest: pathlib.Path, record: dict | None = None, only=None) -> dict:
    """The kept form of every page picture in `previews`, written to `dest` under the same names (the folder's older pictures
    go first, so a page that is gone is never compared). only: the documents (r, d, c) the build made this time, when the
    folder may still hold an older letter's pages. Returns the record written beside them: `record` with the page counts of
    each document."""
    dest = pathlib.Path(dest)  # the kept folder
    dest.mkdir(parents=True, exist_ok=True)  # made on the first export
    for old in dest.glob("*.png"):  # the last baseline's pictures
        old.unlink()  # never mixed with this one's
    pages = {}  # pages per document
    for prefix in PREFIXES:  # resume, deck, letter
        found = pictures(previews, prefix) if only is None or prefix in only else []  # this document's pages, when it was made
        for p in found:  # each page
            canon(p).save(dest / p.name, optimize=True)  # small: about 40 KB a page, 20 KB a slide
        if found:  # a document this edition has
            pages[prefix] = len(found)
    rec = {**(record or {}), "pages": pages, "shrink": SHRINK, "levels": LEVELS}  # with the form it was kept in
    (dest / RECORD).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")  # read by compare()
    return rec


def as_gray(im):
    """A P-mode picture's palette indexes as an L-mode image, so Pillow's own image arithmetic can compare two of them."""
    from PIL import Image  # Pillow
    return Image.frombytes("L", im.size, im.tobytes())  # the same bytes, read as grey values: equal bytes, equal pixels


def bands(a, b) -> list:
    """The bands where two pictures in the kept form differ: [(top row, bottom row)], top first. Pictures of different sizes
    (a page size that changed) differ everywhere."""
    from PIL import ImageChops  # Pillow's arithmetic on images
    if a.size != b.size:  # nothing can be laid over the other
        return [(0, max(a.size[1], b.size[1]) - 1)]
    diff = ImageChops.difference(as_gray(a), as_gray(b)).point(lambda v: 255 if v else 0)  # every pixel whose colour changed
    w, h = diff.size  # the picture's size
    if diff.getbbox() is None:  # not one pixel changed: the usual case of an unchanged page
        return []
    rows = []  # (row, changed pixels) of each row that differs
    for y in range(h):  # row by row
        n = diff.crop((0, y, w, y + 1)).histogram()[255]  # the changed pixels of this row
        if n:
            rows.append((y, n))
    out, start, last, count = [], None, None, 0  # the bands, and the one being grown
    for y, n in rows:  # rows close together are one band
        if start is not None and y - last > GAP:  # far from the band before: it ends
            out.append((start, last, count))
            start = None
        if start is None:  # a new band
            start, count = y, 0
        last, count = y, count + n  # it grows
    if start is not None:  # the last band
        out.append((start, last, count))
    return [(y0, y1) for y0, y1, n in out if n >= MIN_PIXELS]  # a stray pixel or two is no change to show


def compare(previews: pathlib.Path, kept: pathlib.Path, only=None) -> dict:
    """What changed between the kept pictures and a build's previews, per document present in either: {doc: {"before": pages,
    "after": pages, "pages": [changed page numbers], "bands": {page: [[top, bottom], ...]}}}. A page added or taken away
    counts as changed. Documents whose pages are all the same have an empty "pages" list. only: the documents (r, d, c) the
    build made this time; the others count as gone, whatever older pictures the folder still holds."""
    from PIL import Image  # Pillow
    out = {}  # per document
    for prefix, doc in PREFIXES.items():  # resume, deck, letter
        new = pictures(previews, prefix) if only is None or prefix in only else []  # this build's pages, when it made the document
        old = pictures(kept, prefix)  # the kept ones
        if not new and not old:  # a document neither has
            continue
        changed, where = [], {}  # the changed pages, and their bands
        for i in range(max(len(new), len(old))):  # every page either has
            if i >= len(new) or i >= len(old):  # added or taken away
                changed.append(i + 1)
                continue
            with Image.open(old[i]) as was:  # the kept form, as it was written
                found = bands(was.convert("P") if was.mode != "P" else was, canon(new[i]))  # this build's page in the same form
            if found:  # something on it changed
                changed.append(i + 1)
                where[str(i + 1)] = [list(x) for x in found]  # JSON keys are strings
        out[doc] = {"before": len(old), "after": len(new), "pages": changed, "bands": where}
    return out


def changed(found: dict) -> bool:
    """Did any document of a comparison change?"""
    return any(v.get("pages") for v in (found or {}).values())


def font(size: int):
    """The face the picture's labels are written in: Pretendard, which has Hangul (Pillow's own face has none)."""
    from PIL import ImageFont  # Pillow's text
    f = ROOT / "fonts" / "Pretendard-SemiBold.ttf"  # shipped with Offerowl
    return ImageFont.truetype(str(f), size) if f.is_file() else ImageFont.load_default()  # a copy without the fonts still labels in Latin


def picture(previews: pathlib.Path, kept: pathlib.Path, found: dict, out: pathlib.Path, lang: str | None = None) -> bool:
    """One picture of every changed band, before | now, top to bottom, each under a label that names its document and page
    in the person's language, or in `lang` (the edition's). Written to `out`; False when nothing changed that can be drawn (only
    pages added or taken away)."""
    from PIL import Image, ImageDraw  # Pillow
    label_font = font(13)  # the labels' face
    strips = []  # one image per band
    for prefix, doc in PREFIXES.items():  # in the documents' order
        info = found.get(doc) or {}  # this document's changes
        new, old = pictures(previews, prefix), pictures(kept, prefix)  # its pages (only pages both have are drawn)
        for page in [p for p in info.get("pages") or [] if str(p) in (info.get("bands") or {})][:MAX_PAGES]:  # pages both have, changed
            with Image.open(old[page - 1]) as was:  # the kept page
                a = was.convert("RGB")  # its colours
            b = canon(new[page - 1]).convert("RGB")  # this build's page, in the same form
            w, h = max(a.width, b.width), max(a.height, b.height)  # the larger of the two, when the page size changed
            for y0, y1 in (info["bands"][str(page)])[:MAX_BANDS]:  # each band of the page
                top, bottom = max(0, y0 - PAD), min(h, y1 + PAD + 1)  # with a little of what is around it
                bottom = min(bottom, top + MAX_ROWS)  # a large change shows its top
                words = t("slide" if prefix == "d" else "page", lang, doc=doc_word(doc, lang), n=page)  # "이력서 2쪽: 이전 | 지금"
                s = Image.new("RGB", (w * 2 + 12, bottom - top + 22), "white")  # the strip: a label line, then the two halves
                s.paste(a.crop((0, top, a.width, min(bottom, a.height))), (0, 22))  # before, left
                s.paste(b.crop((0, top, b.width, min(bottom, b.height))), (w + 12, 22))  # now, right
                d = ImageDraw.Draw(s)  # a pen
                d.rectangle([w + 3, 22, w + 8, s.height], fill=(200, 200, 200))  # a thin rule between the halves
                d.text((4, 3), words, fill=(150, 30, 30), font=label_font)  # the label, in the bars' red
                strips.append(s)
    if not strips:  # nothing to draw
        return False
    width, height = max(s.width for s in strips), sum(s.height + 8 for s in strips)  # the sheet
    sheet = Image.new("RGB", (width, height), (232, 232, 232))  # grey between the strips
    y = 0  # where the next strip goes
    for s in strips:  # top to bottom
        sheet.paste(s, (0, y))
        y += s.height + 8
    out = pathlib.Path(out)  # where it goes
    out.parent.mkdir(parents=True, exist_ok=True)  # beside the edition's previews
    sheet.save(out, optimize=True)  # one file
    return True


def describe(found: dict) -> list:
    """The comparison in words, one line per document."""
    lines = []  # the lines
    for doc, info in found.items():  # each document compared
        if info.get("pages"):  # changed
            lines.append(t("changed", doc=doc_word(doc), pages=", ".join(map(str, info["pages"])), before=info["before"], after=info["after"]))
        else:  # the same
            lines.append(t("same", doc=doc_word(doc), after=info["after"]))
    return lines


def compare_pdfs(old: str, new: str, picture_out: str | None = None, dpi: int = 110) -> dict:
    """Two PDFs of one document compared page by page, as the panel compares an edition with its baseline: both drawn at the
    same resolution, put in the kept form and laid over each other. The picture of the changed bands goes to picture_out."""
    import pdftools  # the pages, drawn with poppler or PDFium
    with tempfile.TemporaryDirectory() as tmp:  # the pages live here only while they are compared
        a, b = pathlib.Path(tmp) / "old", pathlib.Path(tmp) / "new"  # one folder each, the pictures named as previews are
        a.mkdir()
        b.mkdir()
        for pdf, folder in ((old, a), (new, b)):  # each PDF
            if not pdftools.render_png(pdf, folder / "r", dpi=dpi):  # r-1.png ... as a resume's previews
                raise SystemExit(t("no_pages", file=pathlib.Path(pdf).name))
        kept = pathlib.Path(tmp) / "kept"  # the old PDF's pages in the kept form
        keep(a, kept)
        found = compare(b, kept)  # what the new one changed
        if picture_out and changed(found):  # the bands, before | now
            picture(b, kept, found, pathlib.Path(picture_out))
    return found


def option(args: list, name: str, default=None):
    """The value after --name on the command line, or the default."""
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def job_command(cmd: str, args: list) -> int:
    """`show` and `accept`: an edition's baseline through the panel's own API in this process (apps/api), as the panel's keys
    use it. The job is its id (the general edition is -general)."""
    sys.path.insert(0, str(ROOT))  # apps/ is a package under the root
    from apps.api.client import Client  # noqa: E402  the API in this process
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--lang", "--data"))]  # the job
    if not pos:  # the job is needed
        print(t("usage"), file=sys.stderr)
        return 2
    job, lang = pos[0], option(args, "--lang", "ko")  # which edition
    data = option(args, "--data")  # another data folder, as `offerowl api --data`
    c = Client(pathlib.Path(data) if data else None)  # the API
    if cmd == "accept":  # keep the last build as the baseline
        try:
            got = c.post("/api/v1/jobs/baseline", {"job": job, "lang": lang})  # the same route the panel's key calls
        except (RuntimeError, ValueError) as exc:  # refused: no such job, or no build
            print(t("no_build", job=job, lang=lang) if "not_built" in str(exc) else str(exc), file=sys.stderr)
            return 1
        print(t("accepted", job=job, lang=lang, at=(got.get("baseline") or {}).get("at", "")))
        return 0
    jobs = c.get("/api/v1/jobs").get("jobs") or []  # every job with its editions
    st = c.get("/api/v1/state")  # the general and named editions are in the state
    every = [*jobs, st.get("general") or {}, *(st.get("editions") or [])]  # where an edition may be
    b = next(((x.get("builds") or {}).get(lang) for x in every if x.get("id") == job), None)  # its build record
    if not b:  # never made
        print(t("no_build", job=job, lang=lang), file=sys.stderr)
        return 1
    ch = b.get("changes")  # what the build compared
    if not ch:  # no baseline was kept for it
        print(t("no_baseline", job=job, lang=lang))
        return 0
    print(t("since", job=job, lang=lang, at=ch.get("since", "")))
    if ch.get("reader_changed"):  # another reader drew the baseline
        print(t("other_reader"))
        return 1
    lines = [ln for ln in describe(ch.get("docs") or {}) if ln]  # one line per document
    print("\n".join("  " + ln for ln in lines) if changed(ch.get("docs")) else t("nothing"))
    return 1 if changed(ch.get("docs")) else 0  # 1 when a page changed, as `compare` does


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)  # the arguments
    cmd = args[0] if args else ""  # the command
    rest = args[1:]  # its arguments
    pos = [a for i, a in enumerate(rest) if not a.startswith("--") and (i == 0 or rest[i - 1] not in ("--picture", "--json", "--dpi", "--record", "--only", "--lang"))]  # files and folders
    if cmd in ("-h", "--help", "help"):  # the commands in plain words
        print(__doc__.strip())
        return 0
    if cmd in ("show", "accept"):  # the panel's baseline from the command line
        return job_command(cmd, rest)
    if cmd == "compare" and len(pos) == 2:  # two PDFs
        found = compare_pdfs(pos[0], pos[1], option(rest, "--picture"), int(option(rest, "--dpi", 110)))
    elif cmd == "keep" and len(pos) == 2:  # the panel's fallback when this PC has no Pillow: run in the render container
        only = set(option(rest, "--only").split(",")) if option(rest, "--only") else None  # the documents the build made
        print(json.dumps(keep(pathlib.Path(pos[0]), pathlib.Path(pos[1]), json.loads(option(rest, "--record", "{}") or "{}"), only), ensure_ascii=False))
        return 0
    elif cmd == "diff" and len(pos) == 2:  # the same, for the comparison
        only = set(option(rest, "--only").split(",")) if option(rest, "--only") else None  # the documents the build made
        found = compare(pathlib.Path(pos[0]), pathlib.Path(pos[1]), only)
        if option(rest, "--picture") and changed(found):  # the picture beside the edition, in its language
            picture(pathlib.Path(pos[0]), pathlib.Path(pos[1]), found, pathlib.Path(option(rest, "--picture")), option(rest, "--lang"))
    else:  # anything else
        print(t("usage"), file=sys.stderr)
        return 2
    if option(rest, "--json"):  # the result for a reader that words it itself
        pathlib.Path(option(rest, "--json")).write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    for line in describe(found):  # in words
        print(line)
    if option(rest, "--picture") and changed(found):  # where the picture went
        print(t("picture", file=option(rest, "--picture")))
    return 1 if changed(found) else 0  # 1 when a page changed


if __name__ == "__main__":
    sys.exit(main())
