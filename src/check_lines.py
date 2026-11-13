#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Line checks of a typeset resume, read from the PDF's word boxes: what only a look at the page used to find.

  1. a highlight (==phrase==) that broke across two lines: its yellow is cut in two
  2. a highlight's size (Korean: letters without spaces; English: words) outside the style pack's range, and a name that
     never goes inside a highlight (a client's, an institution's: the pack's printed.highlight_names, and the never-shown
     words of the person's blind table when the check is given one)
  3. a paragraph the typesetting set (the introduction, a card's cells, a competency, an item, about me, the motivation)
     whose last line holds one word alone, or two very short ones

Its input is <name>.highlights.json, which src/layout.js writes beside the document ({"highlights", "paras"}), and the
PDF's word boxes (pdftools.bbox_layout: poppler or PDFium). A phrase is found in the words joined without spaces, so a
particle glued to a highlight ("==설계==하고" prints as one word "설계하고") and a word cut at a line's hyphen still match.
A highlight or a paragraph that cannot be found is said too: a check that measured nothing must not pass in silence.

  python3 src/check_lines.py <resume.pdf> [--lang en]       the problems, one per line; exit 1 when there are any
"""
import json  # the sidecar
import pathlib  # paths
import re  # words and names
import sys  # the command line
import xml.etree.ElementTree as ET  # the word boxes

import llm  # the message helper and the language setting

NS = {"h": "http://www.w3.org/1999/xhtml"}  # the namespace of pdftotext's -bbox-layout XML
HL_RANGE = {"ko": (6, 24), "en": (2, 9)}  # a highlight's size when the pack sets none: write_resume.py RESUME_DEFAULTS["highlight"]
SHORT_TAIL = {"ko": 5, "en": 10}  # two words on a paragraph's last line still read as one alone when they hold this many letters or fewer
MSG = {  # what this check says, in both languages with the same keys
    "en": {
        "hl_broken": "a highlight breaks across two lines: '{text}'",
        "hl_size": "a highlight of {size} {unit} (the rules say {lo} to {hi}): '{text}'",
        "hl_name": "a name inside a highlight ({names}): '{text}'",
        "hl_missing": "a highlight was not found on the page: '{text}'",
        "last_word": "a paragraph ends on '{tail}' alone: '…{end}'",
        "para_missing": "a paragraph was not found on the page, so its last line was not measured: '{text}…'",
        "no_words": "no words could be read from the PDF, so its lines were not measured",
        "letters": "letters", "words": "words",
    },
    "ko": {
        "hl_broken": "강조가 두 줄로 꺾였습니다: '{text}'",
        "hl_size": "강조가 {size}{unit}입니다(규칙은 {lo}~{hi}): '{text}'",
        "hl_name": "강조 안에 이름이 있습니다({names}): '{text}'",
        "hl_missing": "강조를 쪽에서 찾지 못했습니다: '{text}'",
        "last_word": "문단 끝줄에 '{tail}'만 남았습니다: '…{end}'",
        "para_missing": "문단을 쪽에서 찾지 못해 끝줄을 재지 못했습니다: '{text}…'",
        "no_words": "PDF에서 낱말을 읽지 못해 줄을 재지 못했습니다",
        "letters": "자", "words": "낱말",
    },
}


class Issue(str):
    """One problem in words, as every caller reads it, carrying its code and its values for a reader that words it itself
    (src/check_documents.py --report, the panel) and whether it is a note to polish rather than a defect."""
    code = ""  # the message's key; "" for a line worded elsewhere
    values: dict = {}  # what the words were made from
    polish = False  # a note to polish: shown, never a reason to keep the documents home


def t(key: str, **kw) -> str:
    """A message of this check in the person's language."""
    return llm.message(MSG, key, **kw)


def issue(key: str, polish: bool = False, **kw) -> Issue:
    """A problem worded in the person's language, with its code and values kept."""
    out = Issue(t(key, **kw))  # the words, a str to every caller
    out.code, out.values, out.polish = key, kw, polish  # and what they say
    return out


def norm(s: str) -> str:
    """Text in one form before it is compared: the typesetting ties Latin words with no-break spaces (U+00A0) and
    no-break hyphens (U+2011), which a PDF's text layer gives back as plain spaces and hyphens."""
    return re.sub(r"\s+", " ", str(s).replace(" ", " ").replace("‑", "-")).strip()


def words_from_xml(xml: str) -> list:
    """The PDF's words in reading order from pdftotext's -bbox-layout XML: (page, line number, text, x0, y0, x1, y1)."""
    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", xml))  # its DOCTYPE names an outside DTD ElementTree cannot read
    out, line_no = [], 0  # the words; a line number over the whole document, so lines of two pages stay apart
    for pi, page in enumerate(root.findall(".//h:page", NS)):  # each page
        for line in page.findall(".//h:line", NS):  # each line on it
            line_no += 1
            for w in line.findall("h:word", NS):  # each word
                if w.text and w.text.strip():  # a box of spaces is no word
                    out.append((pi, line_no, norm(w.text), float(w.get("xMin")), float(w.get("yMin")), float(w.get("xMax")), float(w.get("yMax"))))
    return out


def words_of(pdf: str) -> list:
    """The PDF's words with their boxes (poppler or PDFium, through src/pdftools.py)."""
    import pdftools as P  # the reader this PC has
    return words_from_xml(P.bbox_layout(pdf))


def stream(words: list) -> tuple[str, list]:
    """The words joined without spaces, and for every letter the number of the word it is in: a text layer that splits a
    Latin word from the particle after it ("PM 과") or cuts a word at a line's hyphen reads the same once spaces are out."""
    owner = []  # letter -> word
    for i, w in enumerate(words):
        owner.extend([i] * len(w[2]))
    return "".join(w[2] for w in words), owner


def locate(text: str, owner: list, phrase: str, start: int = 0, taken=()) -> tuple | None:
    """A phrase found from letter `start`, spaces left out: (its first letter, its first word, its last word, the letter
    after it), or None. A start in `taken` was measured already (the same phrase twice is measured at each place once)."""
    key = re.sub(r"\s+", "", norm(phrase))  # in the joined text's form
    if not key:
        return None
    i = text.find(key, start)
    while i >= 0 and i in taken:  # measured already: its next place
        i = text.find(key, i + 1)
    if i < 0:
        return None
    return i, owner[i], owner[i + len(key) - 1], i + len(key)


def seek(text: str, owner: list, phrase: str, cur: int, taken) -> tuple:
    """A phrase found in the document's order: after the last one first (the same words in an earlier card or table are not
    it), else from the top (a table's cells read in another order). (what was found, the place to go on from)."""
    hit = locate(text, owner, phrase, cur, taken)
    if hit:
        return hit, hit[3]
    return locate(text, owner, phrase, 0, taken), cur  # from the top: the place does not move back


def place(text: str, owner: list, toks: list, cur: int, taken) -> tuple:
    """A paragraph's first three and last three words, the last within the paragraph's reach of the first (another
    paragraph that starts with the same words is not it); a page's foot and the next page's head may stand between
    them. (head, tail), or (None, None)."""
    head_key, tail_key = " ".join(toks[:3]), " ".join(toks[-3:])  # the two ends
    reach = int(len("".join(toks)) * 1.3) + 120  # the paragraph's letters, with room for a footer and a header
    for start in (cur, 0):  # after the last paragraph first, else from the top
        pos = start
        while True:
            h = locate(text, owner, head_key, pos, taken)
            if not h:
                break
            tl = locate(text, owner, tail_key, h[0], ())
            if tl and tl[3] - h[0] <= reach:  # close enough to be the same paragraph
                return h, tl
            pos = h[0] + 1  # another paragraph with the same start: the next one
    return None, None


def lines_of(words: list) -> dict:
    """Each line as the text layer set it: its number -> [page, left edge, top, bottom, first word, last word]."""
    out = {}  # line number -> its record
    for k, w in enumerate(words):  # the words in reading order
        if w[1] not in out:  # the line's first word
            out[w[1]] = [w[0], w[3], w[4], w[6], k, k]
        else:  # a later word of it
            r = out[w[1]]
            r[2], r[3], r[5] = min(r[2], w[4]), max(r[3], w[6]), k  # its box grows, its last word moves on
    return out


def follow(words: list, lines: dict, start: int, letters: int) -> list:
    """The words of a paragraph whose first line is `start`, read down its own column: the nearest line below on the same
    page whose left edge stands within three points of the first line's, until `letters` letters are read. A text layer
    reads cells that stand side by side row by row (three cards whose labels share rows: every card's first line, then
    every card's second line), so a cell's paragraph is not in one piece of the reading order."""
    page, left, _, bottom, a, b = lines[start]  # the first line
    got = list(range(a, b + 1))  # its words
    have = sum(len(words[k][2]) for k in got)  # the letters read so far
    height = bottom - lines[start][2]  # a line's height, for how far the next one may be
    while have < letters:  # more of the paragraph to read
        below = [(r[2], n) for n, r in lines.items()  # the lines that may continue it
                 if r[0] == page and abs(r[1] - left) <= 3 and r[2] >= bottom - 1 and r[2] - bottom <= 1.2 * height]
        if not below:  # the column ends
            break
        _, n = min(below)  # the nearest one
        r = lines[n]
        got += list(range(r[4], r[5] + 1))  # its words
        have += sum(len(words[k][2]) for k in range(r[4], r[5] + 1))
        bottom = r[3]  # the next one is looked for under it
    return got


def place_in_column(text: str, owner: list, words: list, lines: dict, toks: list, taken) -> tuple:
    """place() for a paragraph the reading order splits (a table cell's, a card's): its first three words found, the
    rest read down its column with follow(). (head, tail) in place()'s form, or (None, None)."""
    key = re.sub(r"\s+", "", norm(" ".join(toks)))  # the paragraph's letters
    h = locate(text, owner, " ".join(toks[:3]), 0, taken)  # where it starts
    while h:
        got = follow(words, lines, words[h[1]][1], len(key) + sum(len(words[k][2]) for k in range(lines[words[h[1]][1]][4], h[1])))
        got = [k for k in got if k >= h[1] or words[k][1] != words[h[1]][1]]  # from its first word on (a line may hold a label first)
        joined, last, read = "", None, 0  # the letters read down the column, and the word where the paragraph ends
        for k in got:
            joined += words[k][2]
            read += len(words[k][2])
            if last is None and read >= len(key):  # the paragraph's last letter is in this word
                last = k
        if last is not None and joined.startswith(key):  # the column reads as the paragraph
            return h, (h[0], h[1], last, h[3])  # the cursor stays after its head: what follows in the reading order is not past it
        h = locate(text, owner, " ".join(toks[:3]), h[0] + 1, taken)  # another paragraph with the same start
    return None, None


def split_rows(ws: list) -> list:
    """Words as the lines they stand on: on one page, a centre more than six tenths of a letter's height away starts a
    new line (a superscript or a smaller face stays on its line)."""
    rows = []
    for w in ws:
        c, h = (w[4] + w[6]) / 2, w[6] - w[4]  # its centre and height
        if rows and rows[-1][0] == w[0] and abs(c - rows[-1][1]) <= 0.6 * h:
            rows[-1][2].append(w[2])
        else:
            rows.append([w[0], c, [w[2]]])
    return [" ".join(r[2]) for r in rows]


def name_pattern(names: list, table_words: list) -> re.Pattern | None:
    """One pattern for the names a highlight may not hold: the pack's names as written, the table's words as the patterns
    they are; each only where no Latin letter or digit stands next to it (HACKATHON holds no HAC, 64KB no KB)."""
    parts = [re.escape(n) for n in names if isinstance(n, str) and n.strip()] + [w for w in table_words if isinstance(w, str) and w.strip()]
    good = []
    for p in parts:  # a table's pattern that does not compile is left out here (the blind check says so)
        try:
            re.compile(p)
            good.append(p)
        except re.error:
            continue
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(good) + r")(?![A-Za-z0-9])") if good else None


def analyze(words: list, data: dict, lang: str = "ko", hl_range: tuple | None = None, names: re.Pattern | None = None,
            polish: bool = True) -> tuple[list, dict]:
    """The line problems of one document. data: the sidecar's {"highlights", "paras"}. polish: each problem is a note to
    polish (the default) rather than a defect. Returns (the problems, what was measured: highlights, found, paragraphs,
    measured), so a caller can see when a check measured nothing."""
    en = lang == "en"
    lo, hi = hl_range or HL_RANGE["en" if en else "ko"]  # a highlight's size
    text, owner = stream(words)
    bad = []
    # 1 and 2: the highlights, in the order the typesetting drew them
    hs = [norm(h) for h in data.get("highlights") or [] if norm(h)]
    found, cur, taken = 0, 0, set()
    for h in hs:
        hit, cur = seek(text, owner, h, cur, taken)
        if not hit:  # not measured: said, never passed over
            bad.append(issue("hl_missing", polish, text=h[:60]))
            continue
        found += 1
        at, s, e, _ = hit
        taken.add(at)
        rows = split_rows(words[s:e + 1])  # the lines its words stand on
        if len(rows) > 1:  # its yellow breaks in two
            bad.append(issue("hl_broken", polish, text=h[:60], rows=" / ".join(rows)[:120]))
        size = len(h.split()) if en else len(h.replace(" ", ""))  # words, or letters without spaces
        if not lo <= size <= hi:
            bad.append(issue("hl_size", polish, text=h[:60], size=size, lo=lo, hi=hi, unit=t("words" if en else "letters")))
        hit_names = sorted({m.group(0) for m in names.finditer(h)}) if names else []
        if hit_names:  # a client's or an institution's name in the yellow
            bad.append(issue("hl_name", polish, text=h[:60], names=", ".join(hit_names)))
    # 3: a paragraph's last line. A cell with its own line breaks (a table's company cell) and a text under four words are left out
    paras = [norm(p) for p in data.get("paras") or [] if "\n" not in p and len(norm(p).split()) >= 4]
    measured, lost, cur, taken = 0, [], 0, set()
    lines = lines_of(words)  # the lines with their boxes, for a paragraph the reading order splits
    for p in paras:
        toks = p.split()
        head, tail = place(text, owner, toks, cur, taken)
        if not head:  # not in one piece of the reading order: read down its column (a table cell, a card)
            head, tail = place_in_column(text, owner, words, lines, toks, taken)
        if not head:
            lost.append(p)
            continue
        if head[0] >= cur:  # found going forward: the next one is looked for after it
            cur = tail[3]
        taken.add(head[0])
        measured += 1
        first, last = words[head[1]], words[tail[2]]  # its first and last words
        if first[1] == last[1]:  # one line: no last line of its own
            continue
        mine = [w for k, w in enumerate(words) if w[1] == last[1] and k <= tail[2]]  # its words on its last line
        tail_text = " ".join(w[2] for w in mine)
        if len(mine) == 1 or (len(mine) == 2 and len(tail_text.replace(" ", "")) <= SHORT_TAIL["en" if en else "ko"]):
            bad.append(issue("last_word", polish, tail=tail_text, end=" ".join(toks[-6:])[:50]))
    for p in lost:  # not measured: said
        bad.append(issue("para_missing", polish, text=p[:40]))
    return bad, {"highlights": len(hs), "found": found, "paragraphs": len(paras), "measured": measured}


def sidecar(pdf: str) -> pathlib.Path:
    """Where the typesetting left what it set for a PDF: <name>.highlights.json beside it."""
    return pathlib.Path(re.sub(r"\.pdf$", ".highlights.json", str(pdf)))


def check(pdf: str, lang: str = "ko", hl_range: tuple | None = None, names: re.Pattern | None = None, polish: bool = True) -> list:
    """The line problems of a typeset resume, [] when the typesetting left no sidecar (a resume the person made, an older
    engine): nothing to measure against, and nothing said."""
    side = sidecar(pdf)
    if not side.is_file():
        return []
    try:
        data = json.loads(side.read_text(encoding="utf-8"))  # {"highlights", "paras"}
    except ValueError:
        return []
    if not (data.get("highlights") or data.get("paras")):  # nothing set: nothing to measure
        return []
    words = words_of(pdf)
    if not words:  # a text layer with nothing in it: said, never passed
        return [issue("no_words", polish)]
    return analyze(words, data, lang, hl_range, names, polish)[0]


def main(argv: list) -> int:
    pdf = next((a for a in argv if not a.startswith("--") and a != "en"), "")
    if not pdf:
        print(__doc__)
        return 1
    bad = check(pdf, "en" if "--lang" in argv and "en" in argv else "ko", polish=False)
    for b in bad:
        print("  - " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
