#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for a finished resume and portfolio deck, for anyone's.

Rules tied to one person's career (interview weak words, customer names, a blind table, company counts) do not belong
here, so only checks that fit everyone are kept.
  resume: every company and project of the profile is listed, page limit, body text clear of the page number, numbers
          and units not split across lines, fill of the last page
  deck: page count = slide count, 16:9 page size, defects the browser measured (element outside the slide, text
        overflowing its box, footer intrusion, overlapping text and box overflow inside figures)
  style: banned characters and patterns of the style pack set in the config (src/style/<name>.json). The default pack is empty
  blind: in a blind edition (OFFEROWL_BLIND=1, the table src/blind.py reads) a company or a project counts as listed when the
         words its bars leave are there: a covered name is a bar in the text layer (square glyphs), never its words

  python3 src/check_documents.py <profile.json> <resume.pdf> [deck.pdf] [--style name] [--max-pages N]
"""
import json  # the profile, the measurement result, the style pack
import pathlib  # file paths
import re  # text search
import sys  # command-line arguments
import tempfile  # page images

import blind  # the blind edition's table: what its bars cover
import check_render as CR  # footer clearance, numbers split from their units (layout checks shared with the other paths)
import llm  # the message helper and the language setting
import pdftools as P  # the PDF's text, size and page pictures, with poppler or PDFium

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
BT = blind.load() if blind.on() else None  # the table of the blind edition being checked, None for an ordinary one
LAST_FILL_MIN = 0.15  # minimum share of the body area that text should fill on the last page; below it a few lines spilled onto an almost empty page
MSG = {  # what this check prints, in both languages with the same keys
    "en": {
        "polish": "  to polish: {item}",
        "failed": "Document check: {bad} defect(s){polish}  FAIL",
        "failed_polish": ", {n} to polish",
        "passed": "Document check: resume{deck} passed{polish} (style pack {style})",
        "passed_deck": " and deck",
        "passed_polish": " ({n} to polish)",
        "no_pack": "the style pack is missing: src/style/{style}.json",
        "banned": "banned character '{c}'",
        "no_text": "the resume's text could not be read",
        "no_role": "company missing: {name}",
        "no_project": "project missing: {name}",
        "korean_left": "Korean text in the English edition: '{text}' ({n} place(s)). Translate it, or write its English in the profile",
        "too_long": "{pages} pages, more than the limit of {limit}",
        "empty_last": "the last page is nearly empty (filled {fill:.0%}, at least {floor:.0%}). Shorten the pages before it or add to it",
        "no_probe": "the measurement {name} is missing",
        "slide_count": "the PDF has {pages} pages and the deck {slides} slides",
        "not_wide": "the page size is not 16:9",
        "slide": "slide {n} '{title}'",
        "form_suffix": "the education table says '{value}' ({school}) where its other lines end in '{suffix}': write it as they do",
    },
    "ko": {
        "polish": "  다듬을 거리: {item}",
        "failed": "문서 검사: 결함 {bad}건{polish}  실패",
        "failed_polish": ", 다듬을 거리 {n}건",
        "passed": "문서 검사: 이력서{deck} 통과{polish} (문체 묶음 {style})",
        "passed_deck": "와 덱",
        "passed_polish": "(다듬을 거리 {n}건)",
        "no_pack": "문체 묶음이 없다: src/style/{style}.json",
        "banned": "금지 글자 '{c}'",
        "no_text": "이력서 글자를 못 읽었다",
        "no_role": "회사가 빠졌다: {name}",
        "no_project": "과제가 빠졌다: {name}",
        "korean_left": "영문판에 한글이 남았다: '{text}' ({n}곳). 번역하거나 프로필에 영문을 적는다",
        "too_long": "쪽 수 {pages} > 상한 {limit}",
        "empty_last": "마지막 쪽이 거의 비었다(채움 {fill:.0%}, 하한 {floor:.0%}). 앞 쪽에서 줄이거나 내용을 더한다",
        "no_probe": "측정 결과 {name} 이 없다",
        "slide_count": "PDF {pages}쪽, 장 {slides}개",
        "not_wide": "쪽 크기가 16:9 가 아니다",
        "slide": "{n}장 '{title}'",
        "form_suffix": "학력 표에서 '{value}'({school})만 '{suffix}'로 끝나지 않는다. 다른 줄처럼 쓴다",
    },
}
# polish items (warnings): they go away only by editing someone else's text, so they are shown apart from defects (failures)
WARN = ("one-word last line", "the last page is nearly empty", "마지막 쪽이 거의 비었다")


def t(key: str, **kw) -> str:
    """A message of this check in the person's language."""
    return llm.message(MSG, key, **kw)


def flat(s: str) -> str:
    """For comparison: removes whitespace and emphasis marks"""
    return re.sub(r"\s+|==", "", s or "")


def shown(name: str) -> str:
    """What a blind edition prints of a name: the characters its table leaves uncovered (the bars stand for the rest). The name
    itself in an ordinary edition"""
    if BT is None:  # nothing is covered
        return name
    return "".join(c for c, f in zip(name, blind.flags(name, BT)) if not f)  # the uncovered characters


def last_fill(pdf: str) -> float:
    """Share of the page height between the top margin and the last line of ink on the last page (the footer line is left out)"""
    from PIL import Image  # available both in the container and on the host
    with tempfile.TemporaryDirectory() as tmp:
        n = P.info(pdf)["pages"]  # the last page
        picture = P.render_png(pdf, pathlib.Path(tmp) / "p", dpi=30, gray=True, first=n, last=n)[0]  # small and grey: only where the ink stops matters
        im = Image.open(picture).convert("L")  # one grey value per pixel (with several channels the comparison below broke)
        w, h = im.size
        px = im.load()
        rows = [y for y in range(h) if any(px[x, y] < 200 for x in range(0, w, 2))]  # rows that have ink
        body = [y for y in rows if y < h * 0.94]  # leave out the footer (the bottom 6% of the page)
        return (max(body) / h) if body else 0.0


def style_issues(text: str, style: str) -> list:
    """Banned characters and banned patterns of the style pack (a shipped name, or the path of a workspace's own pack)"""
    f = pathlib.Path(style) if ("/" in style or "\\" in style or style.endswith(".json")) else ROOT / "src" / "style" / f"{style}.json"
    if not f.exists():
        return [t("no_pack", style=style)]
    pack = json.loads(f.read_text(encoding="utf-8"))
    out = [t("banned", c=c) for c in pack.get("banned_chars", "") if c in text]
    for pat, why in pack.get("banned_patterns", []):
        m = re.search(pat, text)
        if m:
            out.append(f"{why}: '{m.group(0)[:30]}'")
    return out


def _texts(v) -> list:
    """Every text of a value that is a text or one per language."""
    return [x for x in v.values() if isinstance(x, str)] if isinstance(v, dict) else [v] if isinstance(v, str) else []


FORM_SUFFIXES = ("전공", "대학원")  # words a field of the education table ends in, line after line


def form_issues(prof: dict, edition: str) -> list:
    """The education table's lines say alike things alike: when two or more lines' majors end in 전공 (or their parts of a
    school in 대학원), a line whose does not is named: a table once printed one major bare under others that ended in 전공.
    Korean editions only (the English fields name a major plainly); a high school's line has no major to compare."""
    if edition != "ko":
        return []
    ko = lambda v: (v.get("ko") if isinstance(v, dict) else v) or ""  # noqa: E731  the Korean text of a field
    rows = [e for e in prof.get("education") or [] if isinstance(e, dict) and "고등학교" not in ko(e.get("school"))]  # the degrees
    out = []
    for field in ("major", "sub"):  # the major, and the school's part (the graduate school)
        vals = [(ko(e.get("school")).strip(), str(ko(e.get(field))).strip()) for e in rows]
        vals = [(school, v) for school, v in vals if v]  # an empty field says nothing
        for suffix in FORM_SUFFIXES:
            ends = [v.endswith(suffix) for _, v in vals]
            if sum(ends) >= 2 and not all(ends):  # the others say it one way and a line another
                out += [t("form_suffix", school=school, value=v, suffix=suffix) for (school, v), e in zip(vals, ends) if not e]
    return out


def check_resume(prof: dict, pdf: str, style: str, max_pages: int) -> list:
    """Resume checks. The list of problems"""
    text = P.text(pdf)
    if not text.strip():
        return [t("no_text")]
    # the text to look in: a blind edition's bars (square glyphs) leave the words beside them, so they are taken out first
    bad, ft = [], flat(text.replace("■", "") if BT is not None else text)
    hangul = len(re.findall(r"[가-힣]", text))  # the edition's language, read from the page: a Korean edition is mostly Hangul
    edition = "ko" if hangul > 0.2 * max(1, len(re.findall(r"[A-Za-z가-힣]", text))) else "en"
    for r in prof.get("roles", []):  # every company and project must appear (nothing may be dropped silently)
        if r.get("org") and flat(shown(r["org"])) not in ft:  # a blind edition's covered name is its bar
            bad.append(t("no_role", name=r["org"]))
        for p in r.get("projects", []):
            if p.get("resume") is False:  # a draft left it off the resume on purpose
                continue  # kept in the profile for the deck
            if p.get("lang") and p["lang"] != edition:  # written for the other language's edition
                continue
            title = p.get("title")  # a text, or one per language in a drafted profile
            names = [x for x in title.values() if isinstance(x, str)] if isinstance(title, dict) else [title or ""]  # every spelling it has
            if not any(flat(shown(x)) in ft for x in names):  # the edition prints one of them (a blind one, what its bars leave)
                bad.append(t("no_project", name=names[0] if names else ""))
    if edition == "en":  # an English edition prints no Korean but the person's own name
        own = {re.sub(r"\s+", "", w) for v in _texts((prof.get("person") or {}).get("name")) for w in re.findall(r"[가-힣][가-힣\s]*", v)}  # the name in Hangul, syllables joined
        left = [w for w in re.findall(r"[가-힣](?:[가-힣 \t]*[가-힣])?", text) if re.sub(r"\s+", "", w) not in own]  # every other run of Hangul, within a line
        if left:  # what the translation missed, or a field written in Korean only
            line = next((x for x in text.splitlines() if left[0] in x), left[0])  # the line it is on, so the person can find it
            at = line.find(left[0])  # where the Korean starts in it
            start, end = max(0, at - 15), at + len(left[0]) + 15  # the words around it, however long the line
            if start > 0 and 0 <= line.find(" ", start) < at:  # cut inside a word before it: begin at the next whole word
                start = line.find(" ", start) + 1
            if end < len(line) and line.rfind(" ", at + len(left[0]), end) > 0:  # cut inside a word after it: end at the last whole word
                end = line.rfind(" ", at + len(left[0]), end)
            near = line[start:end]  # whole words only
            bad.append(t("korean_left", text=re.sub(r"\s+", " ", near).strip(), n=len(left)))
    pages = text.count("\f")
    if pages > max_pages:
        bad.append(t("too_long", pages=pages, limit=max_pages))
    bad += CR.footer_clearance(pdf) + CR.number_unit_split(pdf)  # layout checks shared with the other paths
    if pages > 1 and last_fill(pdf) < LAST_FILL_MIN:  # a one-page resume may be short
        bad.append(t("empty_last", fill=last_fill(pdf), floor=LAST_FILL_MIN))
    bad += form_issues(prof, edition)  # the lines of a table said alike
    return bad + style_issues(text, style)


def check_deck(pdf: str, style: str) -> list:
    """Deck checks. The browser measurement (.probe.json) and the PDF"""
    probe = pathlib.Path(pdf).with_suffix(".probe.json")
    if not probe.exists():
        return [t("no_probe", name=probe.name)]
    slides = json.loads(probe.read_text(encoding="utf-8"))["slides"]
    info = P.info(pdf)  # its page count and size
    bad = []
    pages = info["pages"]
    if pages != len(slides):
        bad.append(t("slide_count", pages=pages, slides=len(slides)))
    if abs(info["width"] - 960) > 1 or abs(info["height"] - 540) > 1:  # 16:9 at the deck's own size, within rounding
        bad.append(t("not_wide"))
    for s in slides:
        tag = t("slide", n=s["n"], title=s["title"][:20])
        bad += [f"{tag}: {i}" for i in s["issues"]]  # element outside the slide, overflow, footer intrusion
        bad += [f"{tag}: [{i['kind']}] {i['msg']}" for i in s.get("svg", [])]  # defects inside figures
    cut = pathlib.Path(str(pdf)[:-len(".pdf")] + ".cut.json")  # text that did not fit its figure frame and was cut out (deck_slides.js)
    if cut.exists():
        bad += json.loads(cut.read_text(encoding="utf-8"))
    text = P.text(pdf)
    return bad + style_issues(text, style)


def main() -> int:
    args = sys.argv[1:]
    style = args[args.index("--style") + 1] if "--style" in args else "default"
    max_pages = int(args[args.index("--max-pages") + 1]) if "--max-pages" in args else 3
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--style", "--max-pages"))]
    if len(pos) < 2:
        print(__doc__)
        return 1
    prof = json.loads(pathlib.Path(pos[0]).read_text(encoding="utf-8"))
    bad = check_resume(prof, pos[1], style, max_pages)
    if len(pos) > 2:
        bad += check_deck(pos[2], style)
    warn = [b for b in bad if any(w in b for w in WARN)]
    bad = [b for b in bad if b not in warn]
    for w in warn:
        print(t("polish", item=w))
    if bad:
        print(t("failed", bad=len(bad), polish=t("failed_polish", n=len(warn)) if warn else ""))
        for b in bad:
            print("  - " + b)
        return 1
    print(t("passed", deck=t("passed_deck") if len(pos) > 2 else "", polish=t("passed_polish", n=len(warn)) if warn else "", style=style))
    return 0


if __name__ == "__main__":
    sys.exit(main())
