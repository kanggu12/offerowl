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
  printed: what no document may print (a value a build left empty, "undefined"; marks left as typed, == and **; an editing
          note, TODO or "(확인 필요"), and the pack's own rules for the printed words (its "printed" object, docs/WRITING.md):
          a comma after a Korean connective ending, the contrastive 대신 and "instead of", how many "A가 아니라 B",
          와/과 between Latin words, machine verbs said as of a person, the same word twice in one sentence
  lines: the typesetting's highlights and paragraphs (src/layout.js <name>.highlights.json) on the page (src/check_lines.py):
         a highlight broken across two lines, its size, a name inside it, a paragraph ending on a word alone
  blind: in a blind edition (OFFEROWL_BLIND=1, the table src/blind.py reads) a company or a project counts as listed when the
         words its bars leave are there: a covered name is a bar in the text layer (square glyphs), never its words

  python3 src/check_documents.py <profile.json> <resume.pdf> [deck.pdf] [--style name] [--max-pages N] [--report out.json]

--report also writes each finding as JSON, {"defects": [{"code", its values..., "text"}], "polish": [...]}: a reader that words the checks in
its own language (the panel) reads the code and the values; a line with no code of its own ("") keeps only its text.
"""
import json  # the profile, the measurement result, the style pack
import os  # the table the panel stages for the line checks
import pathlib  # file paths
import re  # text search
import sys  # command-line arguments
import tempfile  # page images

import blind  # the blind edition's table: what its bars cover
import check_lines as CL  # the line checks, from the PDF's word boxes and the typesetting's sidecar
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
        "empty_value": "a value the build left empty is printed: '{word}'",
        "markup_left": "marks are printed as typed ({marks}): '{near}'",
        "editing_note": "an editing note is printed ({why}): '{near}'",
        "comma_ending": "a comma after a connective ending: '{near}'",
        "instead": "the contrastive '{word}': '{near}'",
        "not_a_but_b": "'{form}' {n} times (the rules allow {limit})",
        "latin_and": "a Korean 'and' between Latin words (write a slash): '{near}'",
        "colloquial": "a machine said to act like a person: '{near}'",
        "repeated_word": "'{word}' twice in one sentence: '{near}'",
        "deck_tool": "the deck's own check {tool}: {what}",
        "deck_tool_failed": "the deck's own check {tool} did not run: {what}",
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
        "empty_value": "빌드가 비운 값이 찍혔다: '{word}'",
        "markup_left": "표시 부호가 그대로 찍혔다({marks}): '{near}'",
        "editing_note": "편집 메모가 찍혔다({why}): '{near}'",
        "comma_ending": "접속어미 뒤 쉼표: '{near}'",
        "instead": "대조의 '{word}': '{near}'",
        "not_a_but_b": "'{form}' {n}회(규칙은 {limit}회까지)",
        "latin_and": "영문 낱말 사이 와/과(빗금으로 쓴다): '{near}'",
        "colloquial": "기계를 사람처럼 말한 구어: '{near}'",
        "repeated_word": "한 문장에 '{word}' 두 번: '{near}'",
        "deck_tool": "덱 자체 검사 {tool}: {what}",
        "deck_tool_failed": "덱 자체 검사 {tool}이 돌지 못했다: {what}",
    },
}
# polish items (warnings): they go away only by editing someone else's text, so they are shown apart from defects (failures)
WARN = ("one-word last line", "the last page is nearly empty", "마지막 쪽이 거의 비었다")


def t(key: str, **kw) -> str:
    """A message of this check in the person's language."""
    return llm.message(MSG, key, **kw)


Issue = CL.Issue  # one problem in words that carries its code, its values and whether it is a note to polish


def issue(key: str, polish: bool = False, **kw) -> Issue:
    """A problem worded in the person's language, with its code and values kept for the report."""
    out = Issue(t(key, **kw))  # the words, a str to every caller
    out.code, out.values, out.polish = key, kw, polish  # and what they say, for a reader that words them itself
    return out


def report_item(b: str) -> dict:
    """One defect as the report writes it: its code and values when it has them, and its words."""
    vals = {k: v for k, v in (getattr(b, "values", None) or {}).items() if isinstance(v, (str, int, float))}  # plain values only
    return {"code": getattr(b, "code", ""), **vals, "text": str(b)}


def deck_tool_item(tool: str, what: str, failed: bool = False) -> dict:
    """A deck source's own check as a build reports it (apps/api/tasks.py): a line it found, or that it could not run, worded
    in the person's language with its code and values kept, as every other finding is."""
    return report_item(issue("deck_tool_failed" if failed else "deck_tool", tool=tool, what=what))


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
        return [issue("no_pack", style=style)]
    pack = json.loads(f.read_text(encoding="utf-8"))
    out = [issue("banned", c=c) for c in pack.get("banned_chars", "") if c in text]
    for pat, why in pack.get("banned_patterns", []):
        m = re.search(pat, text)
        if m:
            out.append(f"{why}: '{m.group(0)[:30]}'")
    return out


def load_pack(style: str) -> dict:
    """The style pack the documents were written with (a shipped name or a workspace pack's path), {} when there is none."""
    f = pathlib.Path(style) if ("/" in style or "\\" in style or style.endswith(".json")) else ROOT / "src" / "style" / f"{style}.json"
    try:
        pack = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # missing or unreadable: style_issues says so
        return {}
    return pack if isinstance(pack, dict) else {}


def near(text: str, m: re.Match, before: int = 25, after: int = 15) -> str:
    """The words around a match, on one line, for the message."""
    return " ".join(text[max(0, m.start() - before):m.end() + after].split())


# What no printed document may hold, whatever the pack: a value a build left empty, marks left as they were typed, and
# notes meant for the person writing. A tool's name like Node.js is no file name: only document files are named here
EMPTY_KO = re.compile(r"(?<![A-Za-z])undefined(?![A-Za-z])|\[object Object\]")  # NaN is left out: a training run's NaN loss is a real thing to write
EMPTY_EN = re.compile(r"(?:^|[.:;]\s+)undefined\b|(?<![A-Za-z])undefined(?=\s*(?:[.,;:)]|$))|\[object Object\]", re.M)  # an English "undefined segment" is a word
MARKS = re.compile(r"==|\*\*")
NOTES = [(r"\(\s*확인\s*필요", "확인 필요"), (r"(?<![A-Za-z])(?:TODO|TBD|FIXME)(?![A-Za-z])", "TODO"), (r"<!--|-->", "<!-- -->"),
         (r"\b[\w.-]+\.(?:docx|pptx|xlsx|hwp|md)\b", "file name")]
# The pack's rules for printed words ("printed" in a pack; docs/WRITING.md). A comma after a Korean connective ending: the
# nouns that end alike (보고, 이해 ...) are left out, and the -어/-아 verbs are named one by one, as nouns end so too (엔지니어)
COMMA_ENDING = re.compile(r"(?:[가-힣]{1,6}(?:고|며|면서|는데|지만|으나|해|해서|하여|아서|어서|워서|와서|져서|도록)"
                          r"|(?<![가-힣])(?:만들어|맡아|겪어|풀어|옮겨|나눠|묶어|바꿔|세워|맞춰|채워|넘겨)|[가-힣]이라),\s")
COMMA_NOUNS = re.compile(r"(?:보고|최고|창고|참고|광고|재고|신고|경고|사고|원고|금고|공고|이해|피해|방해|올해|손해|오해|견해|화해|침해|재해|장해|분해"
                         r"|저해|가해|상해|공해|난해|무해|유해),\s$")
INSTEAD = {"ko": re.compile(r"(?<![가-힣])대신(?:에)?(?=[\s,.)]|$)"), "en": re.compile(r"\b[Ii]nstead of\b")}  # '사용자를 대신해' and 대신증권 are not it
CONTRAST = {"ko": (re.compile(r"[가-힣)]\s?아니라\s"), "A가 아니라 B"), "en": (re.compile(r"\brather than\b"), "rather than")}
LATIN_AND = re.compile(r"[A-Za-z0-9+]+\s*[와과]\s+[A-Za-z0-9]+")
JOSA = ("에서는", "으로는", "에서", "으로", "까지", "부터", "처럼", "보다", "에게", "에는", "와의", "과의", "이나", "에도", "으로도",
        "과", "와", "을", "를", "이", "가", "은", "는", "의", "에", "로", "도", "만")  # the particles a word is read without
EN_STOP = {"through", "across", "between", "without", "within", "before", "during", "around", "system", "systems", "service",
           "services", "platform", "engineering", "engineer"}  # words an English sentence repeats by nature


def stem(word: str) -> str:
    """A Korean word without its particle, so 플랫폼을 and 플랫폼의 count as one word."""
    for j in JOSA:
        if word.endswith(j) and len(word) - len(j) >= 2:
            return word[:-len(j)]
    return word


def sentences_of(paras: list) -> list:
    """The sentences of the paragraphs the typesetting set."""
    out = []
    for p in paras:
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s*", str(p).replace("==", "")) if s.strip()]
    return out


def printed_issues(text: str, pack: dict, lang: str, paras: list | None = None) -> list:
    """What no printed document may hold, and the pack's own rules for printed words. paras: the paragraphs the typesetting
    set (the sidecar), for the rule on a word twice in one sentence; None for a document with no sidecar (a deck)."""
    out = []
    for m in (EMPTY_EN if lang == "en" else EMPTY_KO).finditer(text):  # a build's empty value
        out.append(issue("empty_value", word=m.group(0).strip(" .:;")))
    for m in MARKS.finditer(text):  # marks left as typed
        out.append(issue("markup_left", marks=m.group(0), near=near(text, m)))
        break  # one says it: the rest are the same mistake
    rules = pack.get("printed") if isinstance(pack.get("printed"), dict) else {}  # the pack's own printed rules
    notes = NOTES + [tuple(x) for x in rules.get("editing_notes") or [] if isinstance(x, list) and len(x) == 2]  # with the person's own
    for pat, why in notes:
        try:
            found = list(re.finditer(pat, text))
        except re.error:  # a pattern of the person's that does not compile: the pack's check says so when it is kept
            continue
        out += [issue("editing_note", why=why, near=near(text, m)) for m in found[:3]]
    ko = lang != "en"
    if ko and rules.get("comma_after_endings"):  # 하고, 했으며, 맡아,
        out += [issue("comma_ending", near=near(text, m)) for m in COMMA_ENDING.finditer(text) if not COMMA_NOUNS.search(m.group(0))][:8]
    if rules.get("instead"):  # the contrastive 대신, instead of
        out += [issue("instead", word=m.group(0), near=near(text, m)) for m in INSTEAD["en" if not ko else "ko"].finditer(text)][:6]
    limit = rules.get("not_a_but_b")
    if isinstance(limit, int) and not isinstance(limit, bool):  # how many 'A가 아니라 B' (rather than) a document may hold
        pat, form = CONTRAST["ko" if ko else "en"]
        n = len(pat.findall(text))
        if n > limit:
            out.append(issue("not_a_but_b", form=form, n=n, limit=limit))
    if ko and rules.get("latin_and"):  # Kafka와 Redis: Kafka/Redis
        out += [issue("latin_and", near=near(text, m, 10, 10)) for m in LATIN_AND.finditer(text)][:6]
    for pat in rules.get("colloquial") or []:  # the person's list of machine verbs said as of a person
        try:
            out += [issue("colloquial", near=near(text, m)) for m in re.finditer(str(pat), text)][:6]
        except re.error:
            continue
    if rules.get("repeated_words") and paras is not None:  # one word twice in one sentence
        for s in sentences_of(paras):
            words = [stem(w) for w in re.findall(r"[가-힣]{3,}", s)] if ko else [w for w in re.findall(r"[A-Za-z]{6,}", s.lower()) if w not in EN_STOP]
            twice = sorted({w for w in words if words.count(w) > 1})
            if twice:
                out.append(issue("repeated_word", word=twice[0], near=s[:60]))
    return out


def line_rules(pack: dict, lang: str) -> dict:
    """What the line checks take from the pack: a highlight's size, the names never inside one, defects or notes."""
    resume_rules = pack.get("resume") if isinstance(pack.get("resume"), dict) else {}
    size = (resume_rules.get("highlight") or {}).get(lang) if isinstance(resume_rules.get("highlight"), dict) else None  # [low, high]
    rules = pack.get("printed") if isinstance(pack.get("printed"), dict) else {}
    table = []  # the never-shown words of the person's table, when the check was given it
    named = os.environ.get("OFFEROWL_HIGHLIGHT_TABLE", "").strip()  # the panel stages the table for this check
    if named:
        try:
            table = [w for w in json.loads((ROOT / named).read_text(encoding="utf-8")).get("leak") or [] if isinstance(w, str)]
        except (OSError, ValueError, AttributeError):  # unreadable: the pack's names still hold
            table = []
    names = CL.name_pattern(list(rules.get("highlight_names") or []), table)
    return {"hl_range": tuple(size) if isinstance(size, list) and len(size) == 2 else None, "names": names,
            "polish": rules.get("lines") != "fail"}  # notes to polish unless the pack makes them defects


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
                out += [issue("form_suffix", school=school, value=v, suffix=suffix) for (school, v), e in zip(vals, ends) if not e]
    return out


def check_resume(prof: dict, pdf: str, style: str, max_pages: int) -> list:
    """Resume checks. The list of problems"""
    text = P.text(pdf)
    if not text.strip():
        return [issue("no_text")]
    # the text to look in: a blind edition's bars (square glyphs) leave the words beside them, so they are taken out first
    bad, ft = [], flat(text.replace("■", "") if BT is not None else text)
    hangul = len(re.findall(r"[가-힣]", text))  # the edition's language, read from the page: a Korean edition is mostly Hangul
    edition = "ko" if hangul > 0.2 * max(1, len(re.findall(r"[A-Za-z가-힣]", text))) else "en"
    for r in prof.get("roles", []):  # every company and project must appear (nothing may be dropped silently)
        if r.get("org") and flat(shown(r["org"])) not in ft:  # a blind edition's covered name is its bar
            bad.append(issue("no_role", name=r["org"]))
        for p in r.get("projects", []):
            if p.get("resume") is False:  # a draft left it off the resume on purpose
                continue  # kept in the profile for the deck
            if p.get("lang") and p["lang"] != edition:  # written for the other language's edition
                continue
            title = p.get("title")  # a text, or one per language in a drafted profile
            names = [x for x in title.values() if isinstance(x, str)] if isinstance(title, dict) else [title or ""]  # every spelling it has
            if not any(flat(shown(x)) in ft for x in names):  # the edition prints one of them (a blind one, what its bars leave)
                bad.append(issue("no_project", name=names[0] if names else ""))
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
            bad.append(issue("korean_left", text=re.sub(r"\s+", " ", near).strip(), n=len(left)))
    pages = text.count("\f")
    if pages > max_pages:
        bad.append(issue("too_long", pages=pages, limit=max_pages))
    bad += CR.footer_clearance(pdf) + CR.number_unit_split(pdf)  # layout checks shared with the other paths
    if pages > 1 and last_fill(pdf) < LAST_FILL_MIN:  # a one-page resume may be short
        bad.append(issue("empty_last", fill=last_fill(pdf), floor=LAST_FILL_MIN))
    bad += form_issues(prof, edition)  # the lines of a table said alike
    pack = load_pack(style)  # the person's rules
    side = CL.sidecar(pdf)  # what the typesetting set, when it left it
    paras = None
    if side.is_file():
        try:
            paras = json.loads(side.read_text(encoding="utf-8")).get("paras") or []
        except ValueError:
            paras = None
    bad += printed_issues(text, pack, edition, paras)  # what no document prints, and the pack's printed rules
    bad += CL.check(pdf, edition, **line_rules(pack, edition))  # highlights and last lines, from the word boxes
    return bad + style_issues(text, style)


def check_deck(pdf: str, style: str) -> list:
    """Deck checks. The browser measurement (.probe.json) and the PDF"""
    probe = pathlib.Path(pdf).with_suffix(".probe.json")
    if not probe.exists():
        return [issue("no_probe", name=probe.name)]
    slides = json.loads(probe.read_text(encoding="utf-8"))["slides"]
    info = P.info(pdf)  # its page count and size
    bad = []
    pages = info["pages"]
    if pages != len(slides):
        bad.append(issue("slide_count", pages=pages, slides=len(slides)))
    if abs(info["width"] - 960) > 1 or abs(info["height"] - 540) > 1:  # 16:9 at the deck's own size, within rounding
        bad.append(issue("not_wide"))
    for s in slides:
        tag = t("slide", n=s["n"], title=s["title"][:20])
        for words in [str(i) for i in s["issues"]] + [f"[{i['kind']}] {i['msg']}" for i in s.get("svg", [])]:  # element outside the slide, overflow, footer intrusion; defects inside figures
            line = Issue(f"{tag}: {words}")  # as the command line prints it
            line.code, line.values = "slide", {"n": s["n"], "title": s["title"][:20], "what": words}  # the slide's number and the measurement's own words
            bad.append(line)
    cut = pathlib.Path(str(pdf)[:-len(".pdf")] + ".cut.json")  # text that did not fit its figure frame and was cut out (deck_slides.js)
    if cut.exists():
        bad += json.loads(cut.read_text(encoding="utf-8"))
    text = P.text(pdf)
    hangul = len(re.findall(r"[가-힣]", text))  # the deck's language, read from its pages
    lang = "ko" if hangul > 0.2 * max(1, len(re.findall(r"[A-Za-z가-힣]", text))) else "en"
    return bad + printed_issues(text, load_pack(style), lang) + style_issues(text, style)


def main() -> int:
    args = sys.argv[1:]
    style = args[args.index("--style") + 1] if "--style" in args else "default"
    max_pages = int(args[args.index("--max-pages") + 1]) if "--max-pages" in args else 3
    report = args[args.index("--report") + 1] if "--report" in args else None  # the defects as JSON too
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--style", "--max-pages", "--report"))]
    if len(pos) < 2:
        print(__doc__)
        return 1
    prof = json.loads(pathlib.Path(pos[0]).read_text(encoding="utf-8"))
    bad = check_resume(prof, pos[1], style, max_pages)
    if len(pos) > 2:
        bad += check_deck(pos[2], style)
    warn = [b for b in bad if getattr(b, "polish", False) or any(w in b for w in WARN)]
    bad = [b for b in bad if b not in warn]
    if report:  # the defects with their codes, for a reader that words them itself
        pathlib.Path(report).write_text(json.dumps({"defects": [report_item(b) for b in bad], "polish": [report_item(w) for w in warn]}, ensure_ascii=False), encoding="utf-8")
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
