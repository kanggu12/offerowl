#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two layout checks that only show on the printed page, shared by the resume and the cover letter (src/check_documents.py, src/cover.py).

Text checks cannot see a body line that runs into the page number, or a number left at a line end with its unit on the next
line. Both are measured here from the positions of the lines in the finished PDF.
"""
import re  # the lines of the PDF's layout, and numbers and units

import llm  # the message helper and the language setting
import pdftools as P  # the boxes of the lines, with poppler or PDFium

MSG = {  # what these checks say, in both languages with the same keys
    "en": {"footer": "page {page}: the body touches the page number ({gap:.1f} pt clear, at least {floor} pt)",
           "split": "page {page}: a number is split from its unit: ...{end} / {start}..."},
    "ko": {"footer": "{page}p 본문이 쪽번호에 닿음 (여유 {gap:.1f}pt, 최소 {floor}pt)",
           "split": "{page}p 수와 단위가 갈림: …{end} / {start}…"},
}


def t(key: str, **kw) -> str:
    """A message of these checks in the person's language."""
    return llm.message(MSG, key, **kw)


def footer_clearance(pdf, floor=5.0):
    """Checks that the body keeps clear of the page number.

    When the bottom margin of the docx is smaller than the footer position, the body runs into the page-number area. The
    layout looks normal and the other checks pass, and only the render shows the two overlapping. A bottom margin of 170
    twips makes them touch.
    """
    xml = P.bbox_layout(pdf)  # the lines and their boxes
    out = []
    for i, body in enumerate(re.findall(r"<page[^>]*>(.*?)</page>", xml, re.S), 1):
        ls = sorted((float(m.group(2)), float(m.group(4)), float(m.group(3)) - float(m.group(1)))
                    for m in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"', body))
        if len(ls) < 2:
            continue
        # The footer can have two text groups even in one line (the name on the left, the page number on the right). Groups at
        # the same height count together as the footer and are measured against the line above. Otherwise the footer pieces
        # would be reported as overlapping each other.
        # The fonts differ, so the top lines of the two groups are off by about 2 pt; within 4 pt counts as the same line.
        # Only narrow groups (under 150 pt) count as footer. A body line that came down and overlaps is wide, so it is not in
        # here and gets caught
        foot_rows = [l for l in ls if l[0] >= ls[-1][0] - 4.0 and l[2] < 150]
        if not foot_rows:
            foot_rows = [ls[-1]]
        above = [l for l in ls if l not in foot_rows]
        if not above:
            continue
        gap = min(l[0] for l in foot_rows) - max(l[1] for l in above)
        if gap < floor:
            out.append(t("footer", page=i, gap=gap, floor=floor))
    return out


def number_unit_split(pdf):
    """Checks whether a number and its unit were split by a line break.

    When a line ends with a number and the next line starts with its unit, that is wrong in Korean typesetting. It cannot
    be seen in the text, only by coordinates.
    """
    xml = P.bbox_layout(pdf)  # the lines and their boxes
    # `\b` does not work after a Korean letter: the unit and the syllable after it are both word characters, so no boundary
    # is found and a real split would be missed. A line start counts as a unit when it is not followed by a Korean letter or
    # when it is followed by a particle. Words that merely start with a unit character are not in the particle list, so they
    # are not caught
    UNITS = "시간|회|건|대|장|개|명|쪽|종|배|초|분|주|월|년|행|번|권|편"
    JOSA = "을|를|이|가|은|는|과|와|씩|째|당|짜리|밖에|만큼|뿐"
    unit = rf"^(?:{UNITS})(?:(?![가-힣])|(?={JOSA}))"
    out = []
    for i, body in enumerate(re.findall(r"<page[^>]*>(.*?)</page>", xml, re.S), 1):
        # when one y has several fragments they must be read in order of x. Sorting by (y, text) would put a company name and
        # its description in alphabetical order, which breaks the comparison of neighbouring lines
        lines = []
        for m in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)"[^>]*>(.*?)</line>', body, re.S):
            lines.append((float(m.group(2)), float(m.group(1)),
                          " ".join(re.sub(r"<[^>]+>", " ", m.group(3)).split())))
        lines.sort()
        lines = [(y, t) for y, _, t in lines]
        for a, b in zip(lines, lines[1:]):
            if re.search(r"[\d,]+\s*[만억천백십]*여?$", a[1]) and re.match(unit, b[1]):
                out.append(t("split", page=i, end=a[1][-24:], start=b[1][:20]))
    return out
