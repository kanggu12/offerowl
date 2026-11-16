#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A blind edition's own checks, beside the export's check that nothing covered shows (apps/api/task_export.py):

  layout  the bars move nothing. A blind edition is typeset as its ordinary twin is, so every word the bars leave stands
          where it stands in the twin, on as many pages. A bar of the wrong width, or one that broke over two lines, moves
          the words after it, and the text checks see nothing of it (a resume once passed every check with a bar split
          between the end of one line and the start of the next).
  masks   every mask pattern of the table matches something in the ordinary twin's own words (its Word paragraphs, the
          deck's page, else its PDF). A pattern is tied to the words it was written for: once they are rewritten it matches
          nothing, and the words it was meant to cover go out uncovered. The table's mask_keep names patterns kept on
          purpose (a name the documents do not print yet), which are not named here.

    python3 src/check_blind.py layout <ordinary.pdf> <blind.pdf> [<ordinary deck.pdf> <blind deck.pdf>]
                               [--table table.json --files <file>...] [--report out.json]
    python3 src/check_blind.py masks <table.json> <file>... [--report out.json]    the twin's .docx, .html or .pdf

layout with --table and --files also tries the table's patterns on the twin's files and writes the ones that matched to the
report ("matched"): the panel joins them with what its other blind editions matched before it names a pattern as dead.

The words are pdftotext's word boxes (src/pdftools.py: poppler or PDFium). The band across the top of the first page and
the footer (where the blind label is) are left out of the layout check. --report writes the findings with their codes, as
src/check_documents.py --report does: {"defects": [...], "polish": [...]}.
"""
import html  # the words inside the XML, and a page's text
import json  # the table and the report
import pathlib  # paths
import re  # the patterns, the XML
import sys  # the command line
import zipfile  # a Word file is a zip

ROOT = pathlib.Path(__file__).resolve().parent.parent  # the repository root, one level above src/
sys.path.insert(0, str(ROOT / "src"))  # the modules beside this file, however it was started
import blind  # noqa: E402  the table: how blind.js reads a pattern
import check_lines as CL  # noqa: E402  a finding that carries its code and values
import llm  # noqa: E402  the message helper and the language setting

TOP, BOTTOM = 18.0, 28.0  # points at the top (the band across page 1) and the bottom (the footer and its label) left out
DX, DY = 1.5, 1.2  # how far a word may stand from its twin's place: a justified line moved 1.4 pt with the bars' rounding, and the band's
# paragraph lowers page 1 by 1 pt; a line that broke elsewhere moves its words by 10 pt and more
NEAR = 40.0  # points within which a word looks for its twin: farther than that it was pushed out of its place
END = "(?=\\s*$)"  # the end of a text node: the words a pattern is tried on here run past the node a bar is put on
MSG = {  # what these checks say, in both languages with the same keys
    "en": {
        "blind_pages": "the blind edition has {after} pages where the ordinary one has {before}: its bars moved the text",
        "blind_moved": "the bars moved {n} word(s) from their place in the ordinary edition, first '{word}' on page {page} ({dx} pt across, {dy} pt down)",
        "blind_pushed": "the bars pushed {n} word(s) out of their place in the ordinary edition, first '{word}' on page {page}",
        "blind_unmatched": "{n} mask pattern(s) of the blind table match nothing in any blind edition's words, so what they were written to cover may go out: {patterns}",
        "blind_unchecked": "the blind edition's bars were not checked: its ordinary twin could not be typeset",
        "layout_ok": "blind layout: {n} words where the ordinary edition has them",
        "layout_bad": "blind layout: {n} finding(s)",
        "masks_ok": "blind masks: all {n} patterns match",
        "unmatched_here": "  patterns these files' words do not take (another edition's words may): {patterns}",
        "usage": "usage: python3 src/check_blind.py layout <ordinary.pdf> <blind.pdf> | masks <table.json> <file>... [--report out.json]",
    },
    "ko": {
        "blind_pages": "블라인드판이 {after}쪽이고 원본판은 {before}쪽이다. 막대가 글을 밀었다",
        "blind_moved": "막대가 원본판 자리에서 낱말 {n}개를 옮겼다. 처음은 {page}쪽 '{word}'(가로 {dx}pt, 세로 {dy}pt)",
        "blind_pushed": "막대가 원본판 자리 밖으로 낱말 {n}개를 밀었다. 처음은 {page}쪽 '{word}'",
        "blind_unmatched": "블라인드 표의 가림 패턴 {n}개가 어느 블라인드판의 글에도 걸리지 않아, 가리려던 글이 그대로 나갈 수 있다: {patterns}",
        "blind_unchecked": "블라인드판의 막대를 검사하지 못했다: 가리지 않은 짝 판을 조판하지 못했다",
        "layout_ok": "블라인드 조판: 낱말 {n}개가 원본판 자리에 있다",
        "layout_bad": "블라인드 조판: {n}건",
        "masks_ok": "블라인드 가림: 패턴 {n}개가 모두 걸린다",
        "unmatched_here": "  이 파일들의 글에 걸리지 않는 패턴(다른 판의 글에는 걸릴 수 있다): {patterns}",
        "usage": "쓰는 법: python3 src/check_blind.py layout <원본판.pdf> <블라인드판.pdf> | masks <표.json> <파일>... [--report out.json]",
    },
}
WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')  # one word box of the XML
INVISIBLE = dict.fromkeys(map(ord, "\u2060\u200b\ufeff\u00ad"), None)  # joiners and a soft hyphen: no part of a word as it reads


def t(key: str, **kw) -> str:
    """A message of these checks in the person's language."""
    return llm.message(MSG, key, **kw)


def issue(key: str, polish: bool = False, **kw) -> CL.Issue:
    """A finding worded in the person's language, with its code and values kept for the report."""
    out = CL.Issue(t(key, **kw))  # the words, a str to every caller
    out.code, out.values, out.polish = key, kw, polish  # and what they say
    return out


def page_words(pdf) -> list:
    """Each page's words as [(text, x, y)] in points from the top left, without the band at the top and the footer: what a
    bar could move."""
    import pdftools  # poppler or PDFium
    xml = pdftools.bbox_layout(pdf)  # every word with its box
    out = []  # one list per page
    for chunk in xml.split("<page ")[1:]:  # page by page
        m = re.search(r'height="([\d.]+)"', chunk)  # the page's height, for the footer
        h = float(m.group(1)) if m else 842.0  # A4 when it is not said
        ws = [(html.unescape(w.group(5)).translate(INVISIBLE).strip(), float(w.group(1)), float(w.group(2))) for w in WORD.finditer(chunk)]  # text, left, top
        out.append([w for w in ws if w[0] and TOP < w[2] < h - BOTTOM])  # inside the body
    return out


def layout(ordinary, blind_pdf) -> list:
    """The words of a blind edition that do not stand where its ordinary twin has them. A word is paired with the nearest
    word of the same text on the same page (pairs are made closest first, so a figure's repeated labels pair with their own),
    and a covered word has no pair: it is a bar now. More unpaired words than the bars took away were pushed out of place."""
    a, b = page_words(ordinary), page_words(blind_pdf)  # both editions' words
    if len(a) != len(b):  # a page more or less: every word after the change moved
        return [issue("blind_pages", before=len(a), after=len(b))]
    moved, pushed, first_moved, first_pushed = 0, 0, None, None  # the counts, and the first of each to name
    for page, (wa, wb) in enumerate(zip(a, b), 1):  # page by page
        ga, gb = {}, {}  # the places of each word, per edition
        for text, x, y in wa:
            ga.setdefault(text, []).append((x, y))
        for text, x, y in wb:
            gb.setdefault(text, []).append((x, y))
        for text, pa in ga.items():  # each word of the ordinary edition
            pb = gb.get(text, [])  # the same word in the blind one
            pairs = sorted(((xa - xb) ** 2 + (ya - yb) ** 2, i, j) for i, (xa, ya) in enumerate(pa) for j, (xb, yb) in enumerate(pb))  # closest first
            used_a, used_b = set(), set()  # the words already paired
            for d2, i, j in pairs:
                if d2 > NEAR * NEAR:  # too far to be the same word
                    break
                if i in used_a or j in used_b:  # one of them has its pair
                    continue
                used_a.add(i)
                used_b.add(j)
                (xa, ya), (xb, yb) = pa[i], pb[j]
                if abs(xb - xa) > DX or abs(yb - ya) > DY:  # paired, but not in its place
                    moved += 1
                    first_moved = first_moved or (page, text, round(xb - xa, 1), round(yb - ya, 1))
            lost = (len(pa) - len(used_a)) - max(0, len(pa) - len(pb))  # unpaired beyond what the bars took away
            if lost > 0:  # pushed beyond the radius
                pushed += lost
                first_pushed = first_pushed or (page, text)
    out = []  # the findings
    if moved:
        page, word, dx, dy = first_moved
        out.append(issue("blind_moved", n=moved, page=page, word=word[:30], dx=dx, dy=dy))
    if pushed:
        page, word = first_pushed
        out.append(issue("blind_pushed", n=pushed, page=page, word=word[:30]))
    return out


def compared(ordinary) -> int:
    """How many words of the ordinary edition the layout check looks at (for the line it prints)."""
    return sum(len(p) for p in page_words(ordinary))


def docx_texts(path) -> list:
    """The texts a blind edition's bars are put on in a Word file: every run (save.js covers run by run), and every paragraph
    with its runs joined, of the body, the headers and the footers."""
    out = []  # the texts
    with zipfile.ZipFile(path) as z:  # the Word file
        parts = [n for n in z.namelist() if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", n)]  # the body, headers and footers
        for name in parts:
            xml = z.read(name).decode("utf-8", "replace")  # its XML
            for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):  # each paragraph
                runs = [html.unescape(r) for r in re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", para)]  # its runs' text
                out += [r for r in runs if r.strip()]  # each run
                joined = "".join(runs)  # the paragraph as it reads
                if joined.strip():
                    out.append(joined)
    return out


def html_texts(path) -> list:
    """The texts of a deck's page: every text node (deck.js covers node by node), and the page's words on one line."""
    page = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")  # the page
    page = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", page, flags=re.S | re.I)  # no code, no styles
    page = re.sub(r"<pre id=\"probe-out\">.*?</pre>", " ", page, flags=re.S)  # nor the measurement
    nodes = [html.unescape(x) for x in re.split(r"<[^>]+>", page)]  # the text between the tags
    nodes = [x for x in nodes if x.strip()]  # with words
    return nodes + [" ".join(" ".join(nodes).split())]  # each node, and the whole


def file_texts(path) -> list:
    """The texts of one of the ordinary twin's files, by its kind."""
    p = pathlib.Path(path)  # the file
    if p.suffix.lower() == ".docx":  # the resume's Word file
        return docx_texts(p)
    if p.suffix.lower() in (".html", ".htm"):  # the deck's page
        return html_texts(p)
    import pdftools  # a PDF: its text layer, a page at a time, then whole
    text = pdftools.text(p).translate(INVISIBLE)
    return [x for x in text.split("\f") if x.strip()] + [" ".join(text.split())]


def unmatched(table: dict, texts: list) -> list:
    """The mask patterns that match no text (each read as blind.js reads it: its plain spaces taking a no-break space too,
    with ASCII classes), leaving out the table's mask_keep. A pattern that ends at a text node's end is also tried without that
    end, since a paragraph runs on past a run."""
    keep = set(table.get("mask_keep") or [])  # kept on purpose
    out = []  # the patterns that match nothing
    for p in table.get("mask") or []:  # each pattern, in the table's order
        if p in keep:  # the person keeps it for words not printed yet
            continue
        tries = [p] + ([p.replace(END, "")] if END in p else [])  # as written, then without the node's end
        try:
            rxs = [re.compile(blind.nbsp(x), re.ASCII) for x in tries]
        except re.error:  # a table the panel refused would never get here; a hand-made one is said as unmatched
            out.append(p)
            continue
        if not any(m.group(0) for rx in rxs for s in texts for m in rx.finditer(s)):  # no match that holds a character
            out.append(p)
    return out


def masks(table: dict, files: list) -> list:
    """The finding for a table's patterns that match nothing in the ordinary twin's files: a note to polish, as a pattern may
    be meant for another edition."""
    texts = [s for f in files if pathlib.Path(f).is_file() for s in file_texts(f)]  # every text the bars could be put on
    if not texts:  # nothing to try them on: nothing to say
        return []
    note = dead_note(unmatched(table, texts))  # the patterns that match nothing
    return [note] if note else []


def dead_note(dead: list):
    """The note that names patterns matching nothing (None for none): the first few, as written."""
    if not dead:
        return None
    shown = ", ".join(dead[:5]) + (" …" if len(dead) > 5 else "")  # the first few, as written
    return issue("blind_unmatched", polish=True, n=len(dead), patterns=shown[:240])


def unchecked():
    """The defect of a blind edition whose ordinary twin could not be typeset: its bars were not checked, which is never
    taken for passed."""
    return issue("blind_unchecked")


def report_item(b) -> dict:
    """One finding as the report writes it: its code and values, and its words."""
    vals = {k: v for k, v in (getattr(b, "values", None) or {}).items() if isinstance(v, (str, int, float))}  # plain values only
    return {"code": getattr(b, "code", ""), **vals, "text": str(b)}


def write_report(path, found: list, extra: dict | None = None) -> None:
    """The findings as JSON: defects, notes to polish, and what else the run found (the patterns that matched)."""
    pathlib.Path(path).write_text(json.dumps({"defects": [report_item(b) for b in found if not b.polish],
                                              "polish": [report_item(b) for b in found if b.polish], **(extra or {})}, ensure_ascii=False), encoding="utf-8")


def matched(table: dict, files: list) -> list:
    """The mask patterns that match something in these files (the twin's words), in the table's order."""
    texts = [s for f in files if pathlib.Path(f).is_file() for s in file_texts(f)]  # every text the bars could be put on
    dead = set(unmatched({**table, "mask_keep": []}, texts)) if texts else set(table.get("mask") or [])  # what matched nothing
    return [p for p in table.get("mask") or [] if p not in dead]


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)  # the arguments
    opt = lambda name: args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None  # noqa: E731  an option's value
    report = opt("--report")  # the JSON too
    files = args[args.index("--files") + 1:] if "--files" in args else []  # the twin's own files: the last option, to the end
    files = files[:next((i for i, a in enumerate(files) if a.startswith("--")), len(files))]  # up to another option
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and a not in files and (i == 0 or args[i - 1] not in ("--report", "--table"))]  # the command and its PDFs
    extra = {}  # what the report carries beside the findings
    if len(pos) in (3, 5) and pos[0] == "layout":  # a resume, and a deck, each with its twin
        found = layout(pos[1], pos[2]) + (layout(pos[3], pos[4]) if len(pos) == 5 else [])
        print(t("layout_bad", n=len(found)) if found else t("layout_ok", n=compared(pos[1]) + (compared(pos[3]) if len(pos) == 5 else 0)))
        if opt("--table"):  # the patterns the twin's words take
            table = blind.merged(json.loads((ROOT / opt("--table")).read_text(encoding="utf-8")) if not pathlib.Path(opt("--table")).is_absolute()
                                 else json.loads(pathlib.Path(opt("--table")).read_text(encoding="utf-8")))  # over the shipped one, as the build read it
            extra["matched"] = matched(table, files)
            here = [p for p in table.get("mask") or [] if p not in extra["matched"] and p not in set(table.get("mask_keep") or [])]  # this run's own
            if here:  # said for a person at the command line; the panel joins every blind edition's matches before it names one
                print(t("unmatched_here", patterns=", ".join(here[:8]) + (" …" if len(here) > 8 else "")))
    elif len(pos) >= 3 and pos[0] == "masks":  # a table and the twin's files
        table = blind.merged(json.loads(pathlib.Path(pos[1]).read_text(encoding="utf-8")))  # over the shipped one, as a build reads it
        found = masks(table, pos[2:])
        if not found:
            print(t("masks_ok", n=len([p for p in table.get("mask") or [] if p not in set(table.get("mask_keep") or [])])))
    else:  # anything else
        print(t("usage"), file=sys.stderr)
        return 2
    for b in found:  # in words
        print("  - " + b)
    if report:  # with their codes
        write_report(report, found, extra)
    return 1 if any(not b.polish for b in found) else 0  # a defect fails; a note does not


if __name__ == "__main__":
    sys.exit(main())
