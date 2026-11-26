#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""An edition held to the person's facts and to the shape the person keeps (the style pack's "ledger" and "structure"
objects, docs/WRITING.md). An edition brought in, or one edited by hand, may print a period, a number or a title the facts
never had; an edition rewritten for one posting may lose an item, a section, a figure or a required line on the way. These
checks read what the edition prints against what the person's profile (the ledger) holds and against the lists the pack keeps.

  ledger.periods    every period printed (2022.03 ~ 2024.02) is one the ledger holds, as written
  ledger.ids        identifiers (a patent's number) printed only as the ledger writes them; with "all", every one it holds
  ledger.lists      the entries of these sections or groups (papers, patents) are the ledger's own, by their title
  ledger.required   words every edition prints (spaces aside), one list or one per language; an entry may list alternatives
  ledger.core       projects no edition leaves out
  ledger.min_items  at least this many items under a company (by its name), in a general edition
  structure.sections   the section titles in this order (an entry may list alternatives), none missing
  structure.figures    the figures the form places (timeline, stack) are placed
  structure.about_max  about me in at most this many parts
  structure.title_lead "latin": a job title's lead (before its first comma) has no Hangul; "same": every lead in one script
  structure.title_ranks a job title says its rank once (Lead and 리드 together, or Lead twice, is the same rank twice)
  structure.not_skills patterns of what is experience, not a stack, which the skills table never holds

What the typesetting set is read from the sidecar src/layout.js writes beside the document (<name>.highlights.json, its
"parts"); the ledger is a profile, or {"profiles": [...]} with the languages the build staged.
"""
import json  # the ledger and the sidecar
import re  # words, periods and patterns

import check_lines as CL  # the Issue every check gives
import llm  # the message helper and the language setting

MSG = {  # what these checks say, in both languages with the same keys
    "en": {
        "ledger_period": "a period the profile does not have: {period}",
        "ledger_id": "an identifier the profile does not have: {id} ({why})",
        "ledger_id_missing": "an identifier of the profile is not printed: {id} ({why})",
        "ledger_entry": "an entry of '{list}' that the profile does not have: '{entry}'",
        "required_missing": "words every edition prints are missing: '{words}'",
        "core_missing": "a project no edition leaves out is missing: {name}",
        "items_fewer": "{org} has {n} item(s), fewer than {min}",
        "section_missing": "a section is missing: {title}",
        "section_order": "the sections are not in the order the rules keep: {order}",
        "figure_missing": "a figure the rules keep is not placed: {figure}",
        "about_parts": "about me has {n} parts, more than {limit}: {parts}",
        "title_lead": "a job title does not lead in Latin letters as the others do: '{title}'",
        "title_mixed": "the job titles lead in two scripts: {titles}",
        "title_rank": "a job title says its rank twice: '{title}'",
        "not_skill": "the skills table holds what is experience, not a stack: '{what}'",
    },
    "ko": {
        "ledger_period": "프로필에 없는 기간: {period}",
        "ledger_id": "프로필에 없는 번호: {id} ({why})",
        "ledger_id_missing": "프로필의 번호가 찍히지 않았다: {id} ({why})",
        "ledger_entry": "'{list}'에 프로필에 없는 항목: '{entry}'",
        "required_missing": "판마다 찍는 말이 없다: '{words}'",
        "core_missing": "어느 판에서도 빼지 않는 과제가 없다: {name}",
        "items_fewer": "{org} 항목이 {n}개로 {min}개보다 적다",
        "section_missing": "절이 빠졌다: {title}",
        "section_order": "절 순서가 규칙과 다르다: {order}",
        "figure_missing": "규칙이 두는 그림이 없다: {figure}",
        "about_parts": "자기소개가 {n}개로 {limit}개를 넘는다: {parts}",
        "title_lead": "직함 앞머리가 다른 직함처럼 영문이 아니다: '{title}'",
        "title_mixed": "직함 앞머리가 두 가지 글자로 쓰였다: {titles}",
        "title_rank": "직함에 같은 급이 두 번 있다: '{title}'",
        "not_skill": "보유기술에 기술 스택이 아닌 경험이 있다: '{what}'",
    },
}
# the rank words of a job title, and the English words a Korean rank translates to. A title says a rank twice when the same
# rank stands twice, or a Korean rank stands with its English word ("Project Lead, 플랫폼 운영 리드"): the second only restates
# the first. A gloss in parentheses translates the rank before it and claims nothing more ("팀장(Platform Lead)"), and two
# different ranks are two positions the person held ("Team Lead, Release Owner"): neither is the rank said twice
RANKS = {"en": ("Lead", "Head", "Owner", "Manager", "Chief", "Director"), "ko": ("리드", "팀장", "총괄", "책임자", "오너", "매니저")}
SAME_RANK = {"리드": ("Lead",), "팀장": ("Lead", "Head"), "총괄": ("Head", "Chief", "Director"), "책임자": ("Head", "Owner"),
             "오너": ("Owner",), "매니저": ("Manager",)}
SIDE = r"(\d ?\d ?(?:\d ?\d ?)?)\. ?(\d ?\d?)"  # one side of a period: 2024.05 or 24.05, digits a wide letter spacing may split
PERIOD = re.compile(SIDE + r"(?:\. ?\d ?\d?)?[ \t\u00a0]*[~\-–—][ \t\u00a0]*" + SIDE + r"(?!\d)")  # a closed period as printed, on one line (an open one, "2023.03 ~", names no end, and the next line's start is not it)


def t(key: str, **kw) -> str:
    """A message of these checks in the person's language."""
    return llm.message(MSG, key, **kw)


def issue(key: str, polish: bool = False, **kw) -> CL.Issue:
    """A problem worded in the person's language, with its code and values kept for the report."""
    out = CL.Issue(t(key, **kw))  # the words, a str to every caller
    out.code, out.values, out.polish = key, kw, polish  # and what they say
    return out


def strings(v) -> list:
    """Every text in a JSON value, in order (a profile's fields, its sections' markdown, its language halves)."""
    if isinstance(v, str):  # a text
        return [v]
    if isinstance(v, dict):  # an object: its values in order
        return [s for x in v.values() for s in strings(x)]
    if isinstance(v, list):  # a list: its items in order
        return [s for x in v for s in strings(x)]
    return []  # a number, a flag or null holds no words


def ledger_text(ledger) -> str:
    """The ledger's words, one text per line."""
    return "\n".join(strings(ledger))


def squash(s: str) -> str:
    """For comparison: no space, no emphasis marks, no word joiner, lower case."""
    return re.sub(r"\s+|\*\*|==|\u2060", "", str(s or "")).lower()


def side(y: str, m: str) -> str:
    """One side of a period as YY.MM, whichever way it was written (2024.5, 24.05)."""
    y, m = re.sub(r"\s", "", y), re.sub(r"\s", "", m)  # a wide letter spacing's spaces out
    return f"{y[-2:]}.{m.zfill(2)}"  # the year's last two digits, the month in two


def periods_in(text: str) -> list:
    """The closed periods a text writes, each as (YY.MM, YY.MM), with the words as written."""
    return [((side(m.group(1), m.group(2)), side(m.group(3), m.group(4))), " ".join(m.group(0).split())) for m in PERIOD.finditer(text or "")]


def ledger_periods(ledger) -> set:
    """Every period the ledger holds: those its texts write, and every start and end it keeps as fields."""
    out = {p for p, _ in periods_in(ledger_text(ledger))}  # written out
    def walk(v):  # every object of the ledger
        if isinstance(v, dict):
            a, b = v.get("start"), v.get("end")  # a role's, a school's, a service's, a career half's
            if isinstance(a, str) and isinstance(b, str):  # a closed period kept as two fields (an open one names no end)
                ma, mb = re.match(r"\s*(\d{2,4})[.\-/](\d{1,2})", a), re.match(r"\s*(\d{2,4})[.\-/](\d{1,2})", b)  # year and month of each
                if ma and mb:
                    out.add((side(*ma.groups()), side(*mb.groups())))
            for x in v.values():  # and the objects inside it
                walk(x)
        elif isinstance(v, list):  # a list's items
            for x in v:
                walk(x)
    walk(ledger)  # from the top
    return out


def period_issues(text: str, ledger) -> list:
    """Each printed period the ledger does not hold (said once)."""
    have, seen, out = ledger_periods(ledger), set(), []  # what the facts hold, what was said, the findings
    for p, words in periods_in(text):  # each period printed
        if p not in have and p not in seen:  # one the facts lack, said once
            seen.add(p)
            out.append(issue("ledger_period", period=words))
    return out


def id_issues(text: str, ledger: str, rules: list) -> list:
    """Identifiers held to the ledger: each rule {printed, ledger, why, all} finds them as printed and as the ledger writes
    them (the first group of each pattern is the part both share, else the whole match)."""
    out = []  # the findings
    for r in rules or []:  # each kind of identifier
        if not isinstance(r, dict) or not isinstance(r.get("printed"), str):  # the validator refuses these; an older file may hold one
            continue
        try:
            pr, lr = re.compile(r["printed"]), re.compile(r.get("ledger") or r["printed"])  # as printed, and as the ledger writes it
        except re.error:  # a pattern that does not compile reads nothing
            continue
        key = lambda m: m.group(1) if m.re.groups else m.group(0)  # noqa: E731  what a match stands for
        printed = {key(m): m.group(0) for m in pr.finditer(text)}  # the ones printed
        held = {key(m): m.group(0) for m in lr.finditer(ledger)}  # the ones the facts hold
        why = str(r.get("why") or "")  # the person's reason, for the finding
        out += [issue("ledger_id", id=v, why=why) for k, v in printed.items() if k not in held]  # printed, and not a fact
        if r.get("all"):  # every one the ledger holds is printed too
            out += [issue("ledger_id_missing", id=v, why=why) for k, v in held.items() if k not in printed]
    return out


def _texts(v, lang: str) -> list:
    """A field's text in this edition's language (a text, or one per language)."""
    if isinstance(v, dict):  # one per language, or a styled table cell {t, bold}
        return [v.get(lang) or v.get("ko") or v.get("en") or ""] if ("ko" in v or "en" in v) else [str(v.get("t") or "")]
    return [str(v)] if isinstance(v, (str, int, float)) else []  # a plain value


def entries(block: dict, lang: str) -> list:
    """The entries of a section or group: an item, a dated line's main text, a table row's cell with the most letters."""
    out = [x for it in block.get("items") or [] for x in _texts(it, lang)]  # its bullets
    out += [_texts(ln[0], lang)[0] for ln in block.get("lines") or [] if isinstance(ln, list) and ln and _texts(ln[0], lang)]  # its dated lines' main text
    rows = list(block.get("rows") or []) + [r for b in block.get("blocks") or [] if isinstance(b, dict) and isinstance(b.get("table"), dict) for r in b["table"].get("rows") or []]  # its table's rows, and a ledger body's
    for row in rows:  # each row
        cells = [x for c in row for x in _texts(c, lang)] if isinstance(row, list) else []  # its cells' words
        if cells:  # the title is the cell with the most letters (a number, a date or a mark has few)
            out.append(max(cells, key=lambda c: len(re.sub(r"[\d\W_]", "", c))))
    return [x for x in out if len(squash(x)) >= 8]  # a short cell names nothing


def list_issues(prof: dict, ledger: str, names: list, lang: str) -> list:
    """The entries of the sections or groups the pack names whose title the ledger does not hold. A title is found by its
    first 40 letters (spaces aside, any case), so a line break or a capital letter more is the same title."""
    want = [squash(n) for n in names or [] if isinstance(n, str) and n.strip()]  # the lists the pack names
    if not want:  # none: nothing to read
        return []
    have = squash(ledger)  # the facts' words, in the same form
    out = []  # the findings
    def visit(block: dict):  # a section, or a group inside one
        title = "".join(_texts(block.get("title"), lang))  # its title in this language
        if any(squash(title).startswith(w) for w in want):  # a list the ledger keeps
            for e in entries(block, lang):  # each entry it prints
                if squash(e)[:40] not in have:  # its title is not the facts' own
                    out.append(issue("ledger_entry", list=title.strip(), entry=" ".join(e.split())[:70]))
        for g in block.get("groups") or []:  # a group under a section
            if isinstance(g, dict):
                visit(g)
    for s in prof.get("sections") or []:  # the edition's own lists
        if isinstance(s, dict) and (not s.get("lang") or s.get("lang") == lang):  # one written for the other language does not print
            visit(s)
    return out


def terms_of(v, lang: str) -> list:
    """A list for both languages, or the language's own list."""
    v = v.get(lang) if isinstance(v, dict) else v  # one per language: this one's
    return [x for x in v or [] if isinstance(x, (str, list))]  # texts, and lists of alternatives


def required_issues(text: str, rules, lang: str, shown=lambda s: s) -> list:
    """The words every edition prints, spaces aside and any case; an entry that is a list passes with any of its words.
    shown(): what a blind edition prints of a word (its bars stand for the rest)."""
    flat = squash(text)  # the printed words in the form compared
    out = []  # the findings
    for e in terms_of(rules, lang):  # each entry
        alts = [e] if isinstance(e, str) else [x for x in e if isinstance(x, str)]  # its words, or its alternatives
        if alts and not any(squash(shown(a)) in flat for a in alts):  # none printed
            out.append(issue("required_missing", words=alts[0]))
    return out


def core_issues(text: str, names: list, shown=lambda s: s) -> list:
    """The projects no edition leaves out, found in the printed words (spaces aside, any case)."""
    flat = squash(text)  # the printed words in the form compared
    return [issue("core_missing", name=n) for n in names or [] if isinstance(n, str) and n.strip() and squash(shown(n)) not in flat]


def role_names(r: dict) -> set:
    """Every name a role goes by: its org in either language, a ledger career half's, its heading and its key."""
    out = set()  # its names
    for v in (r.get("org"), r.get("heading"), r.get("key"), r.get("short")):  # a text, or one per language
        out |= {x.strip() for x in strings(v) if x.strip()}
    c = r.get("career") if isinstance(r.get("career"), dict) else {}  # a ledger's career block
    for half in ("ko", "en"):  # both of its halves
        h = c.get(half) if isinstance(c.get(half), dict) else {}
        out |= {str(h.get(k)).strip() for k in ("name", "short") if h.get(k)}
    return out


def min_items_issues(prof: dict, mins: dict, lang: str) -> list:
    """A company with fewer printed items than the pack keeps for it (a project marked resume: false, or written for the other
    language, is not printed)."""
    out = []  # the findings
    for r in prof.get("roles") or []:  # each company
        if not isinstance(r, dict):
            continue
        names = role_names(r)  # every name it goes by
        n_min = next((v for k, v in (mins or {}).items() if k in names and isinstance(v, int) and not isinstance(v, bool)), None)  # the pack's minimum for it
        if n_min is None:  # none kept for this company
            continue
        n = len([p for p in r.get("projects") or [] if isinstance(p, dict) and p.get("resume") is not False and (not p.get("lang") or p.get("lang") == lang)])  # the items it prints
        if n < n_min:  # fewer than kept
            org = "".join(_texts(r.get("org"), lang)) or next(iter(sorted(names)), "")  # its name, for the finding
            out.append(issue("items_fewer", org=org, n=n, min=n_min))
    return out


def section_issues(printed: list, order, lang: str, omitted=()) -> list:
    """The section titles the pack keeps, in its order: each one printed, and the printed ones in that order. A section the
    edition leaves out on purpose (omitted: its title, as the typesetting names it; the about-me switched off) is not missing."""
    want = [e for e in terms_of(order, lang)  # the order the pack keeps for this language, but what the edition left out
            if not ({e} if isinstance(e, str) else set(e)) & set(omitted)]
    if not want:  # none: nothing to read
        return []
    alts = [[e] if isinstance(e, str) else [x for x in e if isinstance(x, str)] for e in want]  # each entry's titles
    at = []  # (where it was printed, its title as the pack names it)
    out = []  # the findings
    for names in alts:  # each section kept
        pos = next((i for i, s in enumerate(printed) if s.strip() in names), None)  # where it printed
        if pos is None:  # it did not
            out.append(issue("section_missing", title=names[0] if names else ""))
        else:
            at.append((pos, printed[pos].strip()))
    if [p for p, _ in at] != sorted(p for p, _ in at):  # printed in another order
        out.append(issue("section_order", order=", ".join(s for _, s in sorted(at))))
    return out


def figure_issues(figures: list, want: list) -> list:
    """Each figure the pack keeps (timeline, stack) placed by the form: a figure's file is named <edition>_<kind>[_en].png."""
    names = [str(f.get("name") or "") for f in figures or [] if isinstance(f, dict)]  # the files the form placed
    return [issue("figure_missing", figure=k) for k in want or [] if isinstance(k, str) and not any(re.search(rf"_{re.escape(k)}(?:_en)?\.png$", n) for n in names)]


def about_issues(about: list, limit) -> list:
    """About me in at most this many parts (its stage bands and its boxed statements)."""
    if not isinstance(limit, int) or isinstance(limit, bool) or len(about or []) <= limit:  # no limit set, or within it
        return []
    return [issue("about_parts", n=len(about), limit=limit, parts=", ".join(about)[:120])]


def title_issues(titles: list, lead, ranks: bool) -> list:
    """The job titles of the company bands in one form: their leads (before the first comma) in Latin letters, or in one
    script; and no rank said twice in a title."""
    out = []  # the findings
    leads = [(x, x.split(",")[0]) for x in titles or [] if isinstance(x, str) and x.strip()]  # each title and its lead
    hangul = lambda s: bool(re.search(r"[가-힣]", s))  # noqa: E731  written in Hangul
    if lead == "latin":  # every lead in Latin letters; a Korean rank after the comma is fine
        out += [issue("title_lead", title=x) for x, head in leads if hangul(head)]
    elif lead == "same" and len({hangul(head) for _, head in leads}) > 1:  # the leads in two scripts
        out.append(issue("title_mixed", titles=" / ".join(x for x, _ in leads)[:120]))
    if ranks:  # a rank said twice
        for x, _ in leads:
            bare = re.sub(r"\([^)]*\)", " ", x)  # a gloss in parentheses left out: it translates, it claims no second rank
            en = [w for w in RANKS["en"] for _ in re.findall(rf"\b{w}\b", bare)]  # its English ranks, as words (Leader is no Lead), each time it stands
            ko = [w for w in RANKS["ko"] for _ in range(bare.count(w))]  # its Korean ranks, each time
            twice = len(en) > len(set(en)) or len(ko) > len(set(ko))  # the same rank twice
            restated = any(w in SAME_RANK.get(k, ()) for k in ko for w in en)  # a Korean rank with its English word
            if twice or restated:
                out.append(issue("title_rank", title=x))
    return out


def skills_issues(prof: dict, patterns: list, lang: str) -> list:
    """What the skills table holds that is experience, not a stack: a category or a skill a pattern of the pack matches."""
    out = []  # the findings
    for s in prof.get("skills") or []:  # each row of the table
        if not isinstance(s, dict) or (s.get("lang") and s.get("lang") != lang):  # a row of the other edition does not print
            continue
        words = _texts(s.get("category"), lang) + [x for it in s.get("items") or [] for x in _texts(it, lang)]  # its category and skills
        for w in words:  # each one
            for p in patterns or []:  # against each pattern
                try:
                    if isinstance(p, str) and re.search(p, w):  # experience, not a stack
                        out.append(issue("not_skill", what=w))
                        break  # said once
                except re.error:  # the validator refuses one; an older file may hold it
                    continue
    return out


def check(text: str, prof: dict, parts: dict, pack: dict, lang: str, ledger=None, shown=lambda s: s, general: bool = True) -> list:
    """The ledger and structure problems of one typeset resume. text: its printed words; prof: the edition's profile;
    parts: the sidecar's "parts" ({} when the typesetting left none); ledger: the profile it is held to, None when the check
    was given none (the ledger rules are not read then); shown: what a blind edition prints of a word."""
    led = pack.get("ledger") if isinstance(pack.get("ledger"), dict) else {}  # the rules against the facts
    st = pack.get("structure") if isinstance(pack.get("structure"), dict) else {}  # the shape kept
    out = []  # the findings
    if ledger is not None:  # against the facts
        words = ledger_text(ledger)  # their words
        if led.get("periods"):  # every period printed is theirs
            out += period_issues(text, ledger)
        out += id_issues(text, words, led.get("ids") or [])
        out += list_issues(prof, words, led.get("lists") or [], lang)
    out += required_issues(text, led.get("required"), lang, shown)
    out += core_issues(text, led.get("core") or [], shown)
    if general:  # a general edition keeps its items; an application drops some for its posting on purpose
        out += min_items_issues(prof, led.get("min_items") or {}, lang)
    if parts:  # what the typesetting set: a document it did not set (a file the person made) is not read here
        out += section_issues(parts.get("sections") or [], st.get("sections"), lang, parts.get("omitted") or [])
        out += figure_issues(parts.get("figures") or [], st.get("figures") or [])
        out += about_issues(parts.get("about") or [], st.get("about_max"))
        out += title_issues(parts.get("titles") or [], st.get("title_lead"), bool(st.get("title_ranks")))
    out += skills_issues(prof, st.get("not_skills") or [], lang)
    return out


def problems(pack: dict) -> list:
    """What makes the ledger and structure objects unusable, as short lines (the style pack's validator refuses the pack
    on any): shapes the checks cannot read, a pattern that does not compile."""
    bad = []  # what is wrong, as short lines
    led, st = pack.get("ledger", {}), pack.get("structure", {})  # none: nothing to refuse
    if not isinstance(led, dict) or not isinstance(st, dict):  # the objects themselves in another shape
        return ["ledger"]
    words = lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)  # noqa: E731  a list of texts
    terms = lambda v: isinstance(v, list) and all(isinstance(x, str) or words(x) for x in v)  # noqa: E731  texts or alternatives
    each = lambda v, ok: ok(v) or (isinstance(v, dict) and not set(v) - {"ko", "en"} and all(ok(x) for x in v.values()))  # noqa: E731
    if "periods" in led and not isinstance(led["periods"], bool):
        bad.append("ledger.periods")
    for r in led.get("ids", []) if isinstance(led.get("ids", []), list) else [None]:
        if not (isinstance(r, dict) and isinstance(r.get("printed"), str) and isinstance(r.get("ledger", ""), str) and isinstance(r.get("why", ""), str)
                and isinstance(r.get("all", False), bool)):
            bad.append("ledger.ids")
            continue
        for p in (r["printed"], r.get("ledger") or r["printed"]):
            try:
                re.compile(p)
            except re.error:
                bad.append("ledger.ids: a pattern does not compile")
    if not words(led.get("lists", [])):
        bad.append("ledger.lists")
    if not each(led.get("required", []), terms):
        bad.append("ledger.required")
    if not words(led.get("core", [])):
        bad.append("ledger.core")
    mins = led.get("min_items", {})
    if not (isinstance(mins, dict) and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in mins.values())):
        bad.append("ledger.min_items")
    if not each(st.get("sections", []), terms):
        bad.append("structure.sections")
    if not words(st.get("figures", [])):
        bad.append("structure.figures")
    am = st.get("about_max")
    if am is not None and not (isinstance(am, int) and not isinstance(am, bool) and am >= 0):
        bad.append("structure.about_max")
    if st.get("title_lead") not in (None, "latin", "same"):
        bad.append("structure.title_lead")
    if "title_ranks" in st and not isinstance(st["title_ranks"], bool):
        bad.append("structure.title_ranks")
    if not words(st.get("not_skills", [])):
        bad.append("structure.not_skills")
    for p in st.get("not_skills", []) if words(st.get("not_skills", [])) else []:
        try:
            re.compile(p)
        except re.error:
            bad.append("structure.not_skills: a pattern does not compile")
    return bad


def read_ledger(path: str):
    """The ledger file the build staged, or None when it cannot be read (the ledger rules are not read then)."""
    try:
        with open(path, encoding="utf-8") as f:  # the staged copy
            return json.load(f)
    except (OSError, ValueError):  # missing or broken: the ledger rules wait for another build
        return None
