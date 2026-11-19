#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks across the documents of one application: the Korean and the English edition say the same, and the resume and
its portfolio deck agree.

Two editions written apart drift: a fact fixed in one is missing from the other, a period changed in one is old in the
other. Their sentences cannot be compared, so what can be compared is: the structure and the facts that read the same in
both languages, taken from what each edition prints (the profile it was typeset from, read by the loader the resume and
the deck use, src/profile_loader.js, with the job's own choices), never from names written into this file.

  langs    the Korean and the English edition of one application:
           - as many companies, projects per company, schools, competencies, sections, entries per section and about-me
             parts, overview cards, selected projects and hierarchy rows; the same periods, company by company and project by
             project; no field one edition prints and the other leaves empty;
           - the same tools in the skills table, the same long numbers (patent and registration numbers) and the same dates in
             each section;
           - every Latin word of a Korean text (a tool, a product, a company) is in the English text of the same place, and
             no about-me part has fewer sentences in English; a project with fewer English sentences is a note to polish.
           The style pack's "parity" object adds the person's own words: aliases (DB: database) and a glossary of Korean words
           with the English that must stand for them (docs/DOCUMENTS.md "Checks across documents").
  edition  one edition's resume and its deck:
           - each project slide (kind "project" in the deck's measurement, or a slide of a company with no kind) carries the
             name of a project of the profile, and the period the resume prints for it is on the slide; the pack's
             whole_period names projects whose slide's whole period the resume must print;
           - the deck uses the resume's colours (the theme's name fill, accent, band, rule and the highlight) and shares a
             font family with it;
           - one thing has one word in both: each group of the pack's parity.terms (patterns that name one thing, the first
             the word to use) that the text of both PDFs names is named with the same members in both. A deck the person
             made is read for this too, though nothing else of it is measured;
           - a dated list the pack's parity.newest_first names runs newest first (within each kind of entry, when a table's
             first cells name kinds: first-author papers, then co-author ones).

    python3 src/check_parity.py langs <ko profile.json> <ko job.json> <en profile.json> <en job.json> [--style pack] [--notes] [--report out.json]
    python3 src/check_parity.py edition <profile.json> <job.json> <resume.pdf> [<deck.pdf>] [--style pack] [--report out.json]

--notes makes every finding of `langs` a note to polish: the panel says so in the edition written first, whose words are the
source, and holds the other one to them. --report writes the findings with their codes, as src/check_documents.py does.
"""
import json  # the loader's answer, the report
import os  # the theme file setting
import pathlib  # paths
import re  # words, periods, numbers
import shutil  # is node here
import subprocess  # the loader
import sys  # the command line
import zlib  # the font names inside a PDF's compressed streams

ROOT = pathlib.Path(__file__).resolve().parent.parent  # the repository root, one level above src/
sys.path.insert(0, str(ROOT / "src"))  # the modules beside this file, however it was started
import check_lines as CL  # noqa: E402  a finding that carries its code and values
import llm  # noqa: E402  the message helper and the language setting

HILITE = "FFF0A0"  # the resume's highlight colour (src/layout.js HILITE), which the deck's highlight shares
THEME_KEYS = ("nameFill", "acc2", "band", "rule")  # the theme colours a reader sees on both: the name panel, the accent, the bands, the rules
MSG = {  # what these checks say, in both languages with the same keys
    "en": {
        "parity_roles": "companies: {ko} in the Korean edition, {en} in the English one",
        "parity_items": "{where}: {ko} projects in the Korean edition, {en} in the English one",
        "parity_education": "schools: {ko} in the Korean edition, {en} in the English one",
        "parity_competencies": "core competencies: {ko} in the Korean edition, {en} in the English one",
        "parity_sections": "other sections: {ko} in the Korean edition, {en} in the English one",
        "parity_entries": "{where}: {ko} entries in the Korean edition, {en} in the English one",
        "parity_about": "about-me parts: {ko} in the Korean edition, {en} in the English one",
        "parity_overview": "the overview's {what}: {ko} in the Korean edition, {en} in the English one",
        "parity_period": "{where}: the Korean edition prints {ko}, the English one {en}",
        "parity_field": "{where}: the Korean edition prints '{ko}' where the English one prints '{en}'",
        "parity_words": "{where}: the English edition does not say {words}, which the Korean one does",
        "parity_sentences": "{where}: {ko} sentence(s) in Korean, {en} in English",
        "parity_skills": "skills only one edition lists: Korean {ko}; English {en}",
        "parity_numbers": "numbers only one edition prints (patents and the like): Korean {ko}; English {en}",
        "parity_dates": "{where}: dates {ko} in the Korean edition, {en} in the English one",
        "dates_order": "{where}: its dates do not run newest first ({dates})",
        "deck_unpaired": "slide {n} '{title}' names no project of the profile: give it the resume's name for that project, or list it in your rules' deck_only",
        "deck_period": "slide {n} '{title}': the resume prints {period}, the slide {deck}",
        "deck_whole_period": "slide {n} '{title}': the resume prints {period}, not the slide's whole period {deck}",
        "deck_theme": "the deck does not use the resume's colours: {missing}",
        "deck_font": "the deck's fonts ({deck}) share no family with the resume's ({resume})",
        "term_drift": "one thing, two words: the resume says '{resume}', the portfolio '{deck}'. Use '{first}' in both",
        "cards": "cards",
        "highlights": "selected projects",
        "layers": "hierarchy rows",
        "langs_ok": "Korean and English editions: no difference ({n} parts compared)",
        "edition_ok": "resume and deck: nothing apart ({n} project slides paired)",
        "found": "{n} finding(s)",
        "no_loader": "the profile loader could not read {file}: {why}",
        "usage": "usage: python3 src/check_parity.py langs <ko profile> <ko job> <en profile> <en job> | edition <profile> <job> <resume.pdf> [<deck.pdf>] [--style pack] [--report out.json]",
    },
    "ko": {
        "parity_roles": "회사: 국문판 {ko}곳, 영문판 {en}곳",
        "parity_items": "{where}: 국문판 과제 {ko}개, 영문판 {en}개",
        "parity_education": "학력: 국문판 {ko}행, 영문판 {en}행",
        "parity_competencies": "핵심역량: 국문판 {ko}개, 영문판 {en}개",
        "parity_sections": "기타 절: 국문판 {ko}개, 영문판 {en}개",
        "parity_entries": "{where}: 국문판 항목 {ko}개, 영문판 {en}개",
        "parity_about": "자기소개 단락: 국문판 {ko}개, 영문판 {en}개",
        "parity_overview": "개요의 {what}: 국문판 {ko}개, 영문판 {en}개",
        "parity_period": "{where}: 국문판은 {ko}, 영문판은 {en}",
        "parity_field": "{where}: 국문판은 '{ko}', 영문판은 '{en}'",
        "parity_words": "{where}: 국문판에 있는 말이 영문판에 없다: {words}",
        "parity_sentences": "{where}: 국문 {ko}문장, 영문 {en}문장",
        "parity_skills": "한 판에만 있는 보유기술: 국문 {ko}; 영문 {en}",
        "parity_numbers": "한 판에만 찍힌 번호(특허 등): 국문 {ko}; 영문 {en}",
        "parity_dates": "{where}: 국문판 날짜 {ko}, 영문판 {en}",
        "dates_order": "{where}: 날짜가 최근 순이 아니다({dates})",
        "deck_unpaired": "{n}장 '{title}': 프로필의 어느 과제 이름과도 맞지 않는다. 이력서의 과제 이름으로 쓰거나 규칙의 deck_only에 적는다",
        "deck_period": "{n}장 '{title}': 이력서는 {period}, 장은 {deck}",
        "deck_whole_period": "{n}장 '{title}': 이력서가 장의 기간 전체 {deck} 대신 {period}만 적었다",
        "deck_theme": "덱이 이력서의 색을 쓰지 않는다: {missing}",
        "deck_font": "덱의 글꼴({deck})이 이력서 글꼴({resume})과 한 갈래도 겹치지 않는다",
        "term_drift": "같은 것을 이력서는 '{resume}', 포트폴리오는 '{deck}'라고 쓴다. 둘 다 '{first}' 하나로 맞춘다",
        "cards": "카드",
        "highlights": "대표 프로젝트",
        "layers": "계층도 행",
        "langs_ok": "국영문판: 갈림 없음 ({n}곳 대조)",
        "edition_ok": "이력서와 덱: 어긋남 없음 (과제 장 {n}개 짝지음)",
        "found": "{n}건",
        "no_loader": "프로필 로더가 {file} 파일을 읽지 못했다: {why}",
        "usage": "쓰는 법: python3 src/check_parity.py langs <국문 프로필> <국문 job> <영문 프로필> <영문 job> | edition <프로필> <job> <resume.pdf> [<deck.pdf>] [--style pack] [--report out.json]",
    },
}


def t(key: str, **kw) -> str:
    """A message of these checks in the person's language."""
    return llm.message(MSG, key, **kw)


def issue(key: str, polish: bool = False, **kw) -> CL.Issue:
    """A finding worded in the person's language, with its code and values kept for the report."""
    out = CL.Issue(t(key, **kw))  # the words, a str to every caller
    out.code, out.values, out.polish = key, kw, polish  # and what they say
    return out


# ---------------------------------------------------------------- what an edition prints


class LoaderError(RuntimeError):
    """The profile loader stopped: an edition that cannot be typeset either."""


def load(profile, job) -> tuple:
    """(what an edition is typeset from, its job settings): src/profile_loader.js on the profile in the job's language, so
    the names, periods and lists are exactly the ones the resume and the deck print."""
    cfg = json.loads(pathlib.Path(job).read_text(encoding="utf-8")) if job and pathlib.Path(job).is_file() else {}  # the edition's settings
    lang = cfg.get("lang") if cfg.get("lang") in ("ko", "en") else "ko"  # its language
    node = shutil.which("node") or "node"  # the container and a PC that typesets both have it
    r = subprocess.run([node, "src/profile_loader.js", str(profile), lang, *([str(job)] if job else [])], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")  # the loader, as the typesetting runs it
    if r.returncode != 0:  # the loader stopped (an English text missing, an unknown section)
        raise LoaderError(((r.stderr or "").strip().splitlines() or [""])[-1][:200])
    return json.loads(r.stdout), cfg


def text_of(v) -> str:
    """Every text inside a value (a string, a list of strings, a row of cells, a {t} cell), joined with spaces, without the
    highlight marks."""
    if isinstance(v, str):
        return v.replace("==", "")
    if isinstance(v, dict):  # a styled cell {t, bold, accent}, or a card
        return " ".join(text_of(x) for k, x in v.items() if k not in ("logo", "logoId", "file", "color", "align", "widths"))
    if isinstance(v, (list, tuple)):  # a list or a row
        return " ".join(text_of(x) for x in v)
    return "" if v is None else str(v)


def entries(s: dict) -> list:
    """The entries a section prints, each as its text: its items, dated lines, table rows and a ledger body's bullets and rows."""
    out = [text_of(x) for x in s.get("items") or []] + [text_of(x) for x in s.get("lines") or []] + [text_of(x) for x in s.get("rows") or []]
    for b in s.get("blocks") or []:  # a ledger body
        if b.get("item"):  # a bullet
            out.append(text_of(b["item"]))
        elif b.get("table"):  # a table's rows
            out += [text_of(r) for r in b["table"].get("rows") or []]
    return out


def lists_of(s: dict) -> list:
    """(name, entries) of each list a section prints: one per group under its caption, else the section itself."""
    if s.get("groups"):  # captions with their own lists
        return [(f"{s.get('title') or ''} / {g.get('title') or ''}", entries(g)) for g in s["groups"]]
    return [(str(s.get("title") or ""), entries(s))]


def printed(view: dict, cfg: dict) -> dict:
    """What the resume prints of the loader's view, with the job's choices that resume_form.js applies on top of it: a
    project marked resume: false stays out, the job's projectOrder comes first, competencyDrop leaves names out, and a
    section marked resume: false is left out."""
    order = list(cfg.get("projectOrder") or [])  # the job's project order
    rank = lambda p, i: ((order.index(p.get("id")) if p.get("id") in order else 10 ** 9), i)  # noqa: E731  ordered first, then as written
    roles = []  # the companies, newest first as the loader sorts them
    for r in view.get("roles") or []:
        shown = [p for p in r.get("projects") or [] if p.get("resume") is not False]  # the projects the resume prints
        shown = [p for _, p in sorted(((rank(p, i), p) for i, p in enumerate(shown)), key=lambda x: x[0])]  # in the job's order
        roles.append({**r, "items": shown})
    drop = set(cfg.get("competencyDrop") or [])  # names the job leaves out
    comps = [c for c in view.get("competencies") or [] if c.get("name") not in drop]
    sections = [s for s in view.get("sections") or [] if s.get("resume") is not False and entries_any(s)]  # the sections with a body
    summary = view.get("summary") or {}  # the overview's parts
    return {"roles": roles, "education": view.get("education") or [], "service": view.get("service"), "competencies": comps,
            "skills": view.get("skills") or [], "sections": sections, "about": view.get("about") or [], "summary": summary,
            }


def dated_runs(s: dict) -> list:
    """(name, [dates of each kind of entry]) of each list a section prints: each entry's first date, in order. A table whose
    first cells repeat (a kind: first author, co-author) is split by them, as its rows run newest first within each kind."""
    out = []  # the lists
    for g in (s.get("groups") or [s]):  # captions with lists of their own, else the section
        name = f"{s.get('title') or ''} / {g.get('title') or ''}" if s.get("groups") else str(s.get("title") or "")
        rows = [r for r in g.get("rows") or [] if isinstance(r, (list, tuple)) and r]  # a table's rows
        rows += [r for b in g.get("blocks") or [] if b.get("table") for r in b["table"].get("rows") or [] if r]  # and a ledger body's
        kind = [text_of(r[0]).strip() for r in rows]  # each row's first cell
        repeats = len(set(kind)) < len(kind)  # a kind shared by rows
        runs = {}  # dates per kind, in order
        for k, r in zip(kind, rows):
            ds = dates(text_of(r))
            if ds:
                runs.setdefault(k if repeats else "", []).append(ds[0])
        other = [text_of(x) for x in (g.get("items") or []) + (g.get("lines") or [])] + [text_of(b.get("item")) for b in g.get("blocks") or [] if b.get("item")]  # items and dated lines
        line_dates = [ds[0] for ds in (dates(e) for e in other) if ds]
        out.append((name, [*runs.values(), *([line_dates] if line_dates else [])]))
    return out


def entries_any(s: dict) -> bool:
    """Does a section print anything (an empty one gets no heading)?"""
    return any(e for _, es in lists_of(s) for e in es) or bool(s.get("note"))


# ---------------------------------------------------------------- comparing two editions


def norm_period(p) -> str:
    """A period in one form for comparing two editions: the range mark and the word for an open end alike."""
    s = str(p or "").replace("재직 중", "now").replace("재학 중", "now").replace("Present", "now")  # the open end, in either language
    s = re.sub(r"\s*[~–—-]\s*", " ~ ", s)  # Korean '~', English '-'
    return " ".join(s.split())


def dates(text: str) -> list:
    """The year-months a text holds, in order, as YYYY.MM."""
    return [f"{y}.{int(m):02d}" for y, m in re.findall(r"((?:19|20)\d{2})[.\-/](\d{1,2})(?!\d)", str(text or ""))]


def latin_tokens(text: str) -> set:
    """The Latin words of a Korean text (tools, products, companies), as one edition prints them: a capitalised word keeps the
    capitalised words after it, a slash splits, and marks around a word go."""
    toks = set()  # the words
    for w in re.findall(r"[A-Za-z][A-Za-z0-9+.&:'-]*(?:\s+[A-Z][A-Za-z0-9+.-]*)*", str(text or "").replace("==", "")):
        for part in w.split("/"):  # Kafka/Redis is two
            part = part.strip(".:'-")
            if len(part) >= 2:  # a single letter says nothing
                toks.add(part)
    return toks


def covered(tok: str, en: str, aliases: dict) -> bool:
    """Does an English text say a Latin word of the Korean one: as it is, by one of the pack's aliases, or a phrase word by
    word (the two languages order a name's words alike, but not always together)."""
    low = str(en or "").replace("==", "").lower()  # the English, without marks
    if tok.lower() in low or tok.lower() in low.replace(" & ", "&"):  # as written
        return True
    if any(a.lower() in low for a in aliases.get(tok) or []):  # said another way
        return True
    bare = lambda x: " ".join(re.sub(r"[^0-9a-z+#]+", " ", x.lower()).split())  # noqa: E731  words alone: 'OSS: Open SW' reads as 'OSS, Open SW'
    if bare(tok) and f" {bare(tok)} " in f" {bare(low)} ":  # the same words with other marks between them
        return True
    words = bare(tok).split()  # a phrase, word by word: the two languages may order its words otherwise
    return len(words) > 1 and all(w in low for w in words)


def glossary_miss(ko: str, en: str, glossary: list) -> list:
    """The Korean words of the pack's glossary that a Korean text holds and whose English its English text lacks."""
    out = []  # the words missed
    for row in glossary:
        try:
            if re.search(row[0], ko or "") and not re.search(row[1], str(en or "").replace("==", ""), re.I):
                out.append(row[0].split("|")[0])  # the first spelling names it
        except re.error:  # a pattern the panel refused would never get here
            continue
    return out


def ko_sentences(text: str) -> int:
    """Sentences of a Korean text: each ends in 다. (and 요.), as the resume's sentences do."""
    return len([x for x in re.split(r"(?<=[다요]\.)\s+|(?<=[다요]\.)$", str(text or "").strip()) if x.strip()])


def en_sentences(text: str) -> int:
    """Sentences of an English text: a full stop after a word, then a capital (an abbreviation such as e.g. does not end one)."""
    return len([x for x in re.split(r"(?<=[a-z0-9)\]%])\.\s+(?=[A-Z])|\.$", str(text or "").strip()) if x.strip()])


def long_numbers(text: str) -> set:
    """Registration and patent numbers: runs of seven digits or more (a hyphen or a comma inside counts as part of one), as
    their first nine digits, since one language writes a kind code and the other zeros after them (KR102...B1, KR102...0000)."""
    out = set()
    for m in re.findall(r"\d[\d,\-]{5,}\d", str(text or "")):  # a number with its separators
        digits = re.sub(r"\D", "", m)  # the digits alone
        if len(digits) >= 7 and not re.fullmatch(r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])\d{0,2}", digits):  # a date written without marks is no number
            out.add(digits[:9])
    return out


def about_parts(about) -> list:
    """The about-me parts as (title, text): a stage band's title and paragraphs, or a quote box."""
    out = []
    for item in about or []:
        if isinstance(item, dict):  # { quote, text }
            out.append((str(item.get("quote") or ""), text_of(item.get("text"))))
        elif isinstance(item, (list, tuple)) and item:  # [title, paragraph or paragraphs]
            out.append((str(item[0] or ""), text_of(item[1:] if len(item) > 1 else "")))
    return out


def langs(ko_view: dict, ko_cfg: dict, en_view: dict, en_cfg: dict, pack: dict, notes: bool = False) -> tuple:
    """The differences between the Korean and the English edition of one application: ([findings], parts compared). With
    notes, each is a note to polish."""
    rules = pack.get("parity") if isinstance(pack.get("parity"), dict) else {}  # the person's own words
    aliases = rules.get("aliases") if isinstance(rules.get("aliases"), dict) else {}  # DB: [database]
    glossary = [r for r in rules.get("glossary") or [] if isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) for x in r)]  # [Korean, English]
    a, b = printed(ko_view, ko_cfg), printed(en_view, en_cfg)  # what each prints
    out, n = [], 0  # the findings, and how many parts were compared

    def words(where, ko_text, en_text):  # the Latin words and the glossary's
        miss = sorted(x for x in latin_tokens(ko_text) if not covered(x, en_text, aliases)) + glossary_miss(ko_text, en_text, glossary)
        if miss:
            out.append(issue("parity_words", polish=notes, where=where, words=", ".join(f"'{x}'" for x in miss[:6])))

    def field(where, ko_val, en_val, name=""):  # printed in one edition and empty in the other; the field's key kept for a tool
        if bool(str(ko_val or "").strip()) != bool(str(en_val or "").strip()):
            out.append(issue("parity_field", polish=notes, where=where, ko=str(ko_val or "")[:40], en=str(en_val or "")[:40], field=name))

    # companies, their projects, and their periods
    if len(a["roles"]) != len(b["roles"]):
        out.append(issue("parity_roles", polish=notes, ko=len(a["roles"]), en=len(b["roles"])))
    for ra, rb in zip(a["roles"], b["roles"]):  # newest first in both
        n += 1
        where = f"{ra.get('org') or ''} ({rb.get('org') or ''})"  # both names, so the person finds both
        if norm_period(ra.get("period")) != norm_period(rb.get("period")):
            out.append(issue("parity_period", polish=notes, where=where, ko=ra.get("period") or "", en=rb.get("period") or ""))
        for f in ("dept", "place", "title", "note", "badge", "desc"):  # what the career table and the band print
            field(where, ra.get(f), rb.get(f), f)
        words(where, " ".join(str(ra.get(f) or "") for f in ("dept", "desc", "sub")), " ".join(str(rb.get(f) or "") for f in ("dept", "desc", "sub")))
        if len(ra["items"]) != len(rb["items"]):
            out.append(issue("parity_items", polish=notes, where=where, ko=len(ra["items"]), en=len(rb["items"])))
        for j, (pa, pb) in enumerate(zip(ra["items"], rb["items"]), 1):  # project by project, in print order
            n += 1
            at = f"{ra.get('org') or ''} {j}: {str(pa.get('title') or '')[:30]}"  # the company, the project's place and its Korean name
            if norm_period(pa.get("period")) != norm_period(pb.get("period")):
                out.append(issue("parity_period", polish=notes, where=at, ko=pa.get("period") or "", en=pb.get("period") or ""))
            words(at, f"{pa.get('title') or ''} {pa.get('summary') or ''}", f"{pb.get('title') or ''} {pb.get('summary') or ''}")
            sk, se = ko_sentences(pa.get("summary")), en_sentences(pb.get("summary"))  # a sentence left out of the translation
            if se < sk:  # a note: a long Korean sentence may be two English ones, but rarely the other way round
                out.append(issue("parity_sentences", polish=True, where=at, ko=sk, en=se))
    # schools and service
    if len(a["education"]) != len(b["education"]):
        out.append(issue("parity_education", polish=notes, ko=len(a["education"]), en=len(b["education"])))
    for ea, eb in zip(a["education"], b["education"]):
        n += 1
        where = f"{ea.get('school') or ''} ({eb.get('school') or ''})"
        if norm_period(ea.get("period")) != norm_period(eb.get("period")):
            out.append(issue("parity_period", polish=notes, where=where, ko=ea.get("period") or "", en=eb.get("period") or ""))
        for f in ("sub", "major", "majorSub", "degree", "note"):  # the table's cells, a grey line each
            field(where, ea.get(f), eb.get(f), f)
        words(where, text_of([ea.get(f) for f in ("sub", "major", "majorSub", "degree", "note")]), text_of([eb.get(f) for f in ("sub", "major", "majorSub", "degree", "note")]))
    sa, sb = a.get("service") or {}, b.get("service") or {}  # military service, when there is one
    if sa or sb:
        n += 1
        where = f"{sa.get('label') or '-'} ({sb.get('label') or '-'})"  # the service as each edition names it
        field(where, sa.get("label"), sb.get("label"), "label")
        if norm_period(f"{sa.get('start') or ''} ~ {sa.get('end') or ''}") != norm_period(f"{sb.get('start') or ''} ~ {sb.get('end') or ''}"):
            out.append(issue("parity_period", polish=notes, where=where, ko=f"{sa.get('start') or ''} ~ {sa.get('end') or ''}", en=f"{sb.get('start') or ''} - {sb.get('end') or ''}"))
    # competencies, skills, the overview
    if len(a["competencies"]) != len(b["competencies"]):
        out.append(issue("parity_competencies", polish=notes, ko=len(a["competencies"]), en=len(b["competencies"])))
    for ca, cb in zip(a["competencies"], b["competencies"]):
        n += 1
        words(str(ca.get("name") or ""), f"{ca.get('name') or ''} {ca.get('text') or ''}", f"{cb.get('name') or ''} {cb.get('text') or ''}")
    tools = lambda rows: {str(x).strip() for s in rows for x in (s.get("items") or []) if str(x).strip()}  # noqa: E731  the tool names of a skills table
    only_ko, only_en = sorted(tools(a["skills"]) - tools(b["skills"])), sorted(tools(b["skills"]) - tools(a["skills"]))
    n += 1
    if only_ko or only_en:
        out.append(issue("parity_skills", polish=notes, ko=", ".join(only_ko[:8]) or "-", en=", ".join(only_en[:8]) or "-"))
    for what in ("cards", "highlights", "layers"):  # the overview's parts
        ka, kb = len(a["summary"].get(what) or []), len(b["summary"].get(what) or [])
        if ka != kb:
            out.append(issue("parity_overview", polish=notes, part=what, what=t("cards" if what == "cards" else "highlights" if what == "highlights" else "layers"), ko=ka, en=kb))  # the part's code for the panel's own words, and its words here
    # the other sections, list by list
    if len(a["sections"]) != len(b["sections"]):
        out.append(issue("parity_sections", polish=notes, ko=len(a["sections"]), en=len(b["sections"])))
    for xa, xb in zip(a["sections"], b["sections"]):
        for (name, la), (name_en, lb) in zip(lists_of(xa), lists_of(xb)):  # a list and its twin
            n += 1
            where = f"{name} ({name_en})"  # both names
            da, db = [d for e in la for d in dates(e)], [d for e in lb for d in dates(e)]  # the dates the list prints, in order
            if da != db:  # a dated entry (a certificate, an award, a talk) one edition lacks or dates otherwise
                out.append(issue("parity_dates", polish=notes, where=where, ko=", ".join(da) or "-", en=", ".join(db) or "-"))
            if len(la) != len(lb):  # with the dated entries alike, an undated line one language adds (a native language) is a note
                out.append(issue("parity_entries", polish=notes or da == db, where=where, ko=len(la), en=len(lb)))
            words(where, " ".join(la), " ".join(lb))
    na = set().union(*[long_numbers(" ".join(e for _, es in lists_of(s) for e in es)) for s in a["sections"]] or [set()])  # patent numbers and the like
    nb = set().union(*[long_numbers(" ".join(e for _, es in lists_of(s) for e in es)) for s in b["sections"]] or [set()])
    if na != nb:
        out.append(issue("parity_numbers", polish=notes, ko=", ".join(sorted(na - nb)) or "-", en=", ".join(sorted(nb - na)) or "-"))
    # about me
    pa_, pb_ = about_parts(a["about"]), about_parts(b["about"])
    if len(pa_) != len(pb_):
        out.append(issue("parity_about", polish=notes, ko=len(pa_), en=len(pb_)))
    for i, ((ta, xa), (tb, xb)) in enumerate(zip(pa_, pb_), 1):
        n += 1
        where = f"{ta[:30] or i} ({tb[:30] or i})"
        sk, se = ko_sentences(xa), en_sentences(xb)
        if se < sk:  # a sentence left out of the English about-me
            out.append(issue("parity_sentences", polish=notes, where=where, ko=sk, en=se))
        words(where, f"{ta} {xa}", f"{tb} {xb}")
    return out, n


# ---------------------------------------------------------------- one edition: the resume and its deck


def flat(s) -> str:
    """For matching a name: no spaces, no marks, lower case (a slide's title runs into its tagline without a space)."""
    return re.sub(r"[\s\u00a0\u2060]+|==", "", str(s or "")).lower()


def slide_title(s: str) -> str:
    """A slide's title as the measurement reads it, without a spread's page mark (1/2)."""
    return re.sub(r"\(\d+/\d+\)", "", flat(s))


def names_it(title: str, name: str) -> bool:
    """Does a slide's title (flat) name a project (flat)? The title starts with the name (a tagline may run on after it), or
    the title is a cut-off start of the name: a deck's measurement may keep only the first 40 letters of a title."""
    return bool(name) and (title.startswith(name) or (len(title) >= 16 and name.startswith(title)))


def project_slides(probe: dict) -> list:
    """The deck's project slides: kind "project", or a slide of a company with no kind (a deck source that does not mark
    its slides)."""
    return [s for s in probe.get("slides") or [] if s.get("kind") == "project" or (not s.get("kind") and s.get("company"))]


def every_title(raw: dict) -> list:
    """Every name a project has anywhere in the profile, in every language: the deck may show a project the resume leaves
    out (resume: false, a chapter of research), under its own name."""
    out = []  # flat names

    def names(v):  # a title, or one per language
        return [x for x in (v.values() if isinstance(v, dict) else [v]) if isinstance(x, str) and x.strip()]
    for r in raw.get("roles") or []:  # companies
        for p in r.get("projects") or []:
            out += [flat(x) for k in ("title", "short") for x in names(p.get(k))]
    for c in raw.get("chapters") or []:  # chapters that are not companies
        for p in c.get("projects") or []:
            out += [flat(x) for k in ("title", "short") for x in names(p.get(k))]
    return [x for x in out if x]


def pdf_fonts(path) -> set:
    """The font families a PDF embeds (Pretendard for Pretendard-Bold and ABCDEF+Pretendard-Regular): read from the PDF's
    objects and from its compressed streams, where a writer may keep its font dictionaries."""
    data = pathlib.Path(path).read_bytes()  # the file
    names = set(re.findall(rb"/BaseFont\s*/([^\s/<>\[\]()]+)", data))  # in plain objects
    for m in re.finditer(rb"stream\r?\n", data):  # in object streams
        end = data.find(b"endstream", m.end())
        if end < 0:
            continue
        try:
            names |= set(re.findall(rb"/BaseFont\s*/([^\s/<>\[\]()]+)", zlib.decompress(data[m.end():end])))
        except zlib.error:  # not a deflated stream: a picture, a font program
            continue
    fam = {re.split(r"[-,]", n.decode("latin-1").split("+")[-1])[0] for n in names}  # the family: after the subset tag, before the style
    return {f for f in fam if f and f.lower() not in ("symbol", "zapfdingbats")}


def theme_colours(name: str) -> dict:
    """A theme's colours as the documents use them: src/themes.json, and the person's OFFEROWL_THEME_FILE over it."""
    themes = json.loads((ROOT / "src" / "themes.json").read_text(encoding="utf-8"))  # the shipped sets
    extra = os.environ.get("OFFEROWL_THEME_FILE") or ""  # a person's own sets
    if extra and pathlib.Path(extra).is_file():
        themes.update(json.loads(pathlib.Path(extra).read_text(encoding="utf-8")))
    got = themes.get(name) or themes.get("navy") or {}  # the edition's set
    return {k: str(v).lstrip("#").upper() for k, v in got.items() if not str(k).startswith("_")}


INVISIBLE = dict.fromkeys(map(ord, "\u2060\u200b\ufeff\u00ad"), None)  # joiners and a soft hyphen: no part of a word as it reads (as src/check_blind.py takes them)


def pdf_lines(pdf) -> list:
    """A PDF's lines, each a list of its words, in reading order, read alike by both PDF readers from the words' boxes
    (src/check_lines.py): poppler's plain text drops the hyphen of a word the line broke after it (blue- on one line and
    green on the next reads bluegreen), and its word boxes keep it."""
    lines = {}  # line number -> its words, in the order they are read
    for _, line, word, *_ in CL.words_of(str(pdf)):  # (page, line, text, box)
        lines.setdefault(line, []).append(word)
    return list(lines.values())


def term_text(lines: list) -> str:
    """A document's words in one line, as the pack's terms are looked for in them: one space between two words, a line end
    among them (a term the line broke inside reads as it does on one line), except after a word that ends in a hyphen or a
    slash, which the line broke inside (blue-green on two lines is one word, as printed). The joiners and soft hyphens the
    typesetting puts in go, and a no-break space and a no-break hyphen read as the plain ones."""
    out = []  # the words so far
    for line in lines:  # each line of the document, in reading order
        fresh = True  # the next word starts this line
        for w in line:
            w = str(w).translate(INVISIBLE).replace("\u00a0", " ").replace("\u2011", "-")  # the typesetting's ties, as their plain marks
            if not w.strip():  # a box with no letter in it
                continue
            if fresh and out and len(out[-1]) > 1 and out[-1][-1] in "-/":  # the line before ended inside this word (a dash alone ends no word)
                out[-1] += w
            else:
                out.append(w)
            fresh = False
    return " ".join(" ".join(out).split())  # one space between words, however the boxes held them


def term_groups(rules: dict) -> list:
    """The pack's terms that can be looked for: (the patterns as written, the same compiled without regard to case) for each
    group of two or more patterns that name one thing, the first the word to use. A group of another shape, or with a
    pattern that does not compile, is left out: the panel refuses such a pack before it is kept (pack_problem), and a pack
    given by hand never stops the other checks."""
    groups = rules.get("terms") if isinstance(rules.get("terms"), list) else []  # a list of groups, or none
    out = []  # the groups to look for
    for g in groups:
        if not (isinstance(g, list) and len(g) >= 2 and all(isinstance(x, str) and x.strip() for x in g)):  # two patterns at least, none blank
            continue
        try:
            out.append((g, [re.compile(x, re.I) for x in g]))  # 'Runbook' at the head of a line and 'runbook' inside one are one word
        except re.error:  # a broken pattern leaves its group out
            continue
    return out


def term_uses(text: str, members: list) -> list:
    """(member, the words) of each place a text names a group's thing, in reading order. Where members match over the same
    letters ('staged rollout plan' holds both 'staged rollout' and 'rollout plan'), the match that starts first, then the
    longer, takes them: one place is one word. An empty match is none."""
    found = sorted((m.start(), m.start() - m.end(), i, m.group(0)) for i, rx in enumerate(members)
                   for m in rx.finditer(text) if m.end() > m.start())  # every match of every member: by where it starts, the longest first
    out, end = [], 0  # the places taken, and where the last of them ends
    for start, minus_len, i, words in found:
        if start >= end:  # past the place before it: a place of its own
            out.append((i, words))
            end = start - minus_len  # where this one ends
    return out


def as_written(pattern: str) -> str:
    """A pattern as the word it stands for, for the person to read: a backslash before a mark is left out (C\\+\\+ reads C++)."""
    return re.sub(r"\\(.)", r"\1", pattern)


def term_drift(resume_text: str, deck_text: str, groups: list) -> list:
    """The pack's terms against the words of the resume and of the deck, each in one line (term_text): a term_drift finding
    for each group that both name, but not with the same members (the resume's '멱등 키' where the deck says 'idempotency
    key'). A group that one of them alone names says nothing: the other may have no place for it."""
    forms = lambda uses: ", ".join(list(dict.fromkeys(w for _, w in uses))[:4])  # noqa: E731  the words as printed, each once, in reading order
    out = []  # the findings
    for written, members in groups:  # the patterns as the person wrote them, and compiled
        ua, ub = term_uses(resume_text, members), term_uses(deck_text, members)  # where each document names the thing, and with which member
        if ua and ub and {i for i, _ in ua} != {i for i, _ in ub}:  # both name it, one with a word the other does not use
            out.append(issue("term_drift", first=as_written(written[0]), resume=forms(ua), deck=forms(ub)))
    return out


def edition(view: dict, cfg: dict, raw: dict, resume_pdf, deck_pdf, pack: dict) -> tuple:
    """One edition's resume against its deck, and its dated lists: ([findings], project slides paired)."""
    rules = pack.get("parity") if isinstance(pack.get("parity"), dict) else {}  # the person's own words
    deck_only = {flat(x) for x in rules.get("deck_only") or [] if isinstance(x, str)}  # slides that stand for no single project
    whole = [str(x).lower() for x in rules.get("whole_period") or [] if isinstance(x, str) and x.strip()]  # projects whose whole period the resume prints
    p = printed(view, cfg)  # what the resume prints
    out, paired = [], 0  # the findings, and the slides paired
    held = [str(x) for x in rules.get("newest_first") or [] if isinstance(x, str) and x.strip()]  # the lists the person keeps newest first
    for s in p["sections"]:  # each of them runs newest first, kind by kind
        for name, runs in dated_runs(s):
            if not any(w in name for w in held):  # a list grouped by kind, or ordered by weight, is the person's own order
                continue
            for ds in runs:  # each kind of entry: a table's first-author papers, then its co-author ones
                if len(ds) > 1 and ds != sorted(ds, reverse=True):
                    out.append(issue("dates_order", where=name, dates=", ".join(ds)))
    if not deck_pdf or not pathlib.Path(deck_pdf).is_file():  # no deck in this edition
        return out, paired
    terms = term_groups(rules)  # the person's groups of words for one thing
    if terms and resume_pdf and pathlib.Path(resume_pdf).is_file():  # one thing, one word: any deck, a portfolio the person made too
        out += term_drift(term_text(pdf_lines(resume_pdf)), term_text(pdf_lines(deck_pdf)), terms)  # every word of both, in one line each
    probe_f = pathlib.Path(str(deck_pdf)[:-4] + ".probe.json")  # the deck's measurement, beside it
    probe = json.loads(probe_f.read_text(encoding="utf-8")) if probe_f.is_file() else {}
    if not probe_f.is_file() or probe.get("own"):  # a portfolio the person made (or one no measurement came with): theirs as it is
        return out, paired
    import pdftools  # the deck's pages as text
    pages = pdftools.text(deck_pdf).split("\f")  # one text per slide
    items = [(flat(x.get("title")), x) for r in p["roles"] for x in r["items"] if flat(x.get("title"))]  # the resume's projects
    known = every_title(raw)  # every name a project has in the profile
    for s in project_slides(probe):  # each project slide
        title = slide_title(s.get("title"))  # its name as the slide prints it, its tagline after it
        n = int(s.get("n") or 0)  # its number
        hit = max((x for x in items if names_it(title, x[0])), key=lambda x: len(x[0]), default=None)  # the resume's project it names, the longest name first
        if hit is None:  # not a project the resume prints
            if not any(names_it(title, k) for k in known) and not any(names_it(title, k) for k in deck_only):  # nor any the profile has, nor one kept apart
                out.append(issue("deck_unpaired", n=n, title=str(s.get("title") or "")[:30]))
            continue
        paired += 1
        item = hit[1]  # the project
        on_slide = dates(pages[n - 1] if 0 < n <= len(pages) else "")  # the dates the slide prints
        mine = dates(item.get("period"))  # the dates the resume prints for it
        if not on_slide or not mine:  # a slide or a project that prints no date: nothing to compare
            continue
        label = str(item.get("title") or "")[:30]
        if any(w in label.lower() or w in str(item.get("title") or "").lower() for w in whole):  # the whole period, or nothing
            if set(mine) != set(on_slide):
                out.append(issue("deck_whole_period", n=n, title=label, period=item.get("period") or "", deck=", ".join(dict.fromkeys(on_slide))))
        elif not set(mine) <= set(on_slide):  # the resume's period is one the slide shows
            out.append(issue("deck_period", n=n, title=label, period=item.get("period") or "", deck=", ".join(dict.fromkeys(on_slide))))
    page = pathlib.Path(str(deck_pdf)[:-4] + ".html")  # the page the deck was printed from (a deck drawn or written from a source)
    if page.is_file():  # a deck the person brought in as a PDF has none: its colours are its own
        html = page.read_text(encoding="utf-8", errors="replace").upper()  # every colour it names
        colours = theme_colours(cfg.get("theme") or "navy")  # the resume's set
        want = {k: colours[k] for k in THEME_KEYS if colours.get(k)} | {"highlight": HILITE}  # what a reader sees on both
        missing = [f"{k} #{v}" for k, v in want.items() if v not in html]
        if missing:
            out.append(issue("deck_theme", missing=", ".join(missing)))
    if resume_pdf and pathlib.Path(resume_pdf).is_file():  # the fonts both embed
        fa, fb = pdf_fonts(resume_pdf), pdf_fonts(deck_pdf)
        if fa and fb and not fa & fb:
            out.append(issue("deck_font", resume=", ".join(sorted(fa)), deck=", ".join(sorted(fb))))
    return out, paired


# ---------------------------------------------------------------- the command line


def pack_problem(pack: dict) -> str:
    """Why a style pack's "parity" object cannot be used ("" when it can, or when there is none): aliases, glossary, deck_only,
    whole_period, newest_first and terms of their shapes, every glossary and terms pattern compiling. The panel refuses such a
    pack before it is kept (apps/api/app.py add_style), so a broken pattern never stops a build."""
    rules = pack.get("parity", {}) if isinstance(pack, dict) else None  # the object, when the pack has one
    if not isinstance(rules, dict):  # an object or nothing
        return "parity"
    words = lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)  # noqa: E731  a list of words
    aliases = rules.get("aliases", {})  # a Latin word and the English that may stand for it
    if not isinstance(aliases, dict) or not all(isinstance(k, str) and words(v) for k, v in aliases.items()):
        return "parity.aliases"
    if not words(rules.get("deck_only", [])) or not words(rules.get("whole_period", [])):  # names and words
        return "parity.names"
    if not words(rules.get("newest_first", [])):  # names of the lists held to date order
        return "parity.newest_first"
    for row in rules.get("glossary", []) if isinstance(rules.get("glossary", []), list) else [None]:  # [Korean, English] pairs of patterns
        if not (isinstance(row, list) and len(row) == 2 and all(isinstance(x, str) and x for x in row)):
            return "parity.glossary"
        try:
            re.compile(row[0])  # both must compile, or every comparison would stop on them
            re.compile(row[1])
        except re.error:
            return "parity.glossary"
    for group in rules.get("terms", []) if isinstance(rules.get("terms", []), list) else [None]:  # groups of patterns, each for one thing
        if not (isinstance(group, list) and len(group) >= 2 and all(isinstance(x, str) and x.strip() for x in group)):  # two words at least, none blank
            return "parity.terms"
        try:
            for x in group:
                re.compile(x, re.I)  # each must compile, as the check looks for it, or its group could never be looked for
        except re.error:
            return "parity.terms"
    return ""


def load_pack(style: str) -> dict:
    """The style pack the documents were written with: a shipped name, or the path of a workspace pack ({} when none)."""
    f = pathlib.Path(style) if ("/" in style or "\\" in style or style.endswith(".json")) else ROOT / "src" / "style" / f"{style}.json"
    try:
        pack = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # missing or unreadable: the document check says so
        return {}
    return pack if isinstance(pack, dict) else {}


def report_item(b) -> dict:
    """One finding as the report writes it: its code and values, and its words."""
    vals = {k: v for k, v in (getattr(b, "values", None) or {}).items() if isinstance(v, (str, int, float))}  # plain values only
    return {"code": getattr(b, "code", ""), **vals, "text": str(b)}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)  # the arguments
    opt = lambda name: args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None  # noqa: E731  an option's value
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--style", "--report"))]  # the command and its files
    pack = load_pack(opt("--style") or "default")  # the person's rules
    try:
        if len(pos) == 5 and pos[0] == "langs":  # two editions
            (va, ca), (vb, cb) = load(pos[1], pos[2]), load(pos[3], pos[4])  # what each prints
            found, n = langs(va, ca, vb, cb, pack, notes="--notes" in args)
            print(t("langs_ok", n=n) if not found else t("found", n=len(found)))
        elif len(pos) in (4, 5) and pos[0] == "edition":  # one edition's resume and deck
            view, cfg = load(pos[1], pos[2])
            raw = json.loads(pathlib.Path(pos[1]).read_text(encoding="utf-8"))  # the profile as written, for every name a project has
            found, n = edition(view, cfg, raw, pos[3], pos[4] if len(pos) == 5 else None, pack)
            print(t("edition_ok", n=n) if not found else t("found", n=len(found)))
        else:  # anything else
            print(t("usage"), file=sys.stderr)
            return 2
    except LoaderError as exc:  # an edition that cannot be read cannot be compared: said, and left to its own build's error
        print(t("no_loader", file=pathlib.Path(pos[1]).name, why=str(exc)), file=sys.stderr)
        return 3
    for b in found:  # in words
        print("  - " + b)
    if opt("--report"):  # with their codes, for the panel
        pathlib.Path(opt("--report")).write_text(json.dumps({"defects": [report_item(b) for b in found if not b.polish],
                                                             "polish": [report_item(b) for b in found if b.polish]}, ensure_ascii=False), encoding="utf-8")
    return 1 if any(not b.polish for b in found) else 0  # a defect fails; a note does not


def utf8_stdio() -> None:
    """Print UTF-8 whatever the console's code page: the findings name Korean words, and a Windows pipe or console in cp1252
    stopped the check at the first Hangul letter, before it wrote its report (the panel then took the check as not run)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # a text stream of this Python, not a test's replacement
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    utf8_stdio()  # before anything is printed
    sys.exit(main())
