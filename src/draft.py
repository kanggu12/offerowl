#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI drafts: every resume part, posting fit, translation and portfolio figures.

  offerowl draft write <profile.json> [--job posting.md] [--style pack] [--langs ko,en] [--parts ...]
        every part the resume prints (headline, introduction, cards, selected projects, competencies, items, about,
        motivation) in Korean and English, each sentence with its evidence ids, saved as <profile>.draft.json (src/write_resume.py)
  offerowl draft check <profile.draft.json> [--style pack]
        hold every drafted sentence against its evidence again (facts, claim strength, style, text without evidence)

The other tasks (jd, translate, figures) are described below.

The LLM suggestion steps: posting analysis, translation and portfolio figure suggestions.

They serve the builders only (anyone's profile).
- The input profile is never overwritten. A task writes a new profile with the suggestions applied (<name>.<task>.json)
  and a record of the suggestions (output/_draft/<name>.<task>.json)
- Every suggestion is filtered with the rules of src/factcheck.py: numbers (with units) and number words that the
  evidence lacks, English words (tool and product names), company and institution names, banned characters and patterns
  of the style pack, length and yellow highlights. A suggestion that is caught is dropped and the reason goes into the
  record (so no invented fact gets in)
- The evidence is the profile text plus those quotes of the extracted candidates that occur verbatim in the source.
  Candidates removed in the review screen are not used
- Each task is asked separately (several output formats in one prompt made the remaining reads worse in extraction trials)
- When the LLM stops midway (limit, timeout), the suggestions and the record so far are kept

  offerowl draft jd <profile.json> <JD.txt>              skill categories to put first, competencies to send back, project order
  offerowl draft translate <profile.json>                English profile (<name>.en.json)
  offerowl draft figures <profile.json> [--cands ...]    portfolio figure data for each project
The LLM is chosen with OFFEROWL_LLM (claude-code, codex, openai-compat, none), see src/llm.py. It runs on the host.
"""
import copy  # copies of the profile
import json  # reading and writing files
import pathlib  # file paths
import re  # pattern rules
import sys  # command-line arguments

import factcheck as F  # the fact-checking rules, kept in one place
import llm  # the LLM connection

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
OUT = ROOT / "output" / "_draft"  # record of the suggestions
REVIEW = ROOT / "output" / "_profile" / "review.json"  # accepted and rejected state of the review screen (src/ui/server.py)


class Stopped(Exception):
    """The LLM stopped midway. Carries the results so far"""

    def __init__(self, why, result, log):
        super().__init__(why)
        self.result, self.log = result, log


# Rules

MSG = {  # what this step says, in both languages with the same keys
    "en": {
        "no_pack": "the style pack is missing: src/style/{name}.json",
        "banned": "banned character '{c}'",
        "empty": "empty, or not text",
        "too_long": "length {n} > {limit}",
        "bad_answer": "the answer's form: {why}",
        "unknown_names": "names that do not exist: {names}",
        "all_back": "it moved every competency back",
        "lost_number": "a number was lost",
        "new_number": "a new number",
        "new_number_word": "new counted words: {words}",
        "lost_latin": "lost English words: {words}",
        "new_name": "new proper names: {words}",
        "highlight_count": "the number of highlights differs",
        "stopped_short": "the AI backend stopped",
        "no_translation": "no translation, or not text",
        "empty_translation": "an empty translation",
        "unknown_figure": "an unknown kind of figure",
        "rows_count": "two to eight rows",
        "compare_row": "a compare row is [name, before, after], with values of 0 or more",
        "value_missing": "values not in the evidence: {values}",
        "empty_name": "a row with no name",
        "no_llm": "The AI backend could not be called ({why}). Check OFFEROWL_LLM (python3 src/llm.py --list)",
        "done": "{task}: {kept} of {n} proposals kept, {dropped} stopped by the rules{failed} -> {out}  (log {log})",
        "done_failed": ", {n} answers in the wrong form",
        "stopped": "  The AI backend stopped part way ({why}). This holds the proposals made until then",
    },
    "ko": {
        "no_pack": "문체 묶음이 없다: src/style/{name}.json",
        "banned": "금지 글자 '{c}'",
        "empty": "빈 글이거나 글이 아니다",
        "too_long": "길이 {n} > {limit}",
        "bad_answer": "응답 형식: {why}",
        "unknown_names": "없는 이름: {names}",
        "all_back": "모든 역량을 뒤로 보내 버림",
        "lost_number": "빠진 숫자",
        "new_number": "새 숫자",
        "new_number_word": "새 숫자 낱말: {words}",
        "lost_latin": "빠진 영문 낱말: {words}",
        "new_name": "새 고유명사: {words}",
        "highlight_count": "강조 개수가 다르다",
        "stopped_short": "LLM 이 멈췄다",
        "no_translation": "번역 없음이거나 글이 아니다",
        "empty_translation": "빈 번역",
        "unknown_figure": "모르는 그림 종류",
        "rows_count": "항목은 둘에서 여덟",
        "compare_row": "비교 행은 [이름, 전, 후], 값은 0 이상의 수",
        "value_missing": "근거에 없는 값: {values}",
        "empty_name": "이름이 빈 항목",
        "no_llm": "LLM 을 부르지 못했다({why}). OFFEROWL_LLM 을 확인한다(python3 src/llm.py --list)",
        "done": "{task}: 제안 {n}개 가운데 {kept}개 받음, {dropped}개 규칙에 걸려 버림{failed} -> {out}  (기록 {log})",
        "done_failed": ", 형식 실패 {n}건",
        "stopped": "  LLM 이 중간에 멈췄다({why}). 그때까지의 제안만 담았다",
    },
}


def t(key: str, **kw) -> str:
    """A message of this step in the person's language."""
    return llm.message(MSG, key, **kw)


def style_pack(name: str = "default") -> dict:
    """A style pack by name (src/style/<name>.json) or by path (a workspace's own, which the panel passes). An unknown one
    stops the run (so a typo cannot silently switch the banned-character check off)"""
    f = pathlib.Path(name) if ("/" in name or "\\" in name or name.endswith(".json")) else ROOT / "src" / "style" / f"{name}.json"  # a path, or a shipped name
    if not f.exists():
        raise SystemExit(t("no_pack", name=name))
    return json.loads(f.read_text(encoding="utf-8"))


def style_issues(text: str, style: dict) -> list:
    """Banned characters and banned patterns of the style pack"""
    bad = [t("banned", c=c) for c in style.get("banned_chars", "") if c in text]
    for pat, why in style.get("banned_patterns", []):
        if re.search(pat, text):
            bad.append(why)
    return bad


def check_text(text, evidence: str, *, style: dict, max_len: int, highlight: tuple = (0, 1), lang: str = "ko") -> list:
    """The problems of one suggested text (empty means it passes)"""
    if not isinstance(text, str) or not text.strip():
        return [t("empty")]
    bad = [t("too_long", n=len(text), limit=max_len)] if len(text) > max_len else []
    bad += F.unsupported(text.replace("==", ""), evidence)
    bad += F.highlight_ok(text, lang, highlight)
    return bad + style_issues(text, style)


# Evidence

def load_cands(path: str | None) -> list:
    """The extracted candidates (the kept ones from src/ingest.py). Candidates rejected in the review screen are left out. An empty list when there is no file"""
    if not path:
        return []
    kept = json.loads(pathlib.Path(path).read_text(encoding="utf-8")).get("kept", [])
    if REVIEW.exists():
        import review  # the candidate id rule (the same hash as the review screen)
        st = json.loads(REVIEW.read_text(encoding="utf-8"))
        kept = [c for c in kept if st.get(review.cid(c)) != "rejected"]
    return kept


def org_key(org: str) -> str:
    """Company name key (the same rule as review.org_key)"""
    s = re.sub(r"\(주\)|주식회사|\([^)]*\)", "", org or "")
    return re.sub(r"\s+", "", s).lower()


def as_list(v) -> list:
    """None or a single value as a list"""
    return [] if v is None else (v if isinstance(v, list) else [v])


def project_evidence(role: dict, proj: dict, cands: list) -> str:
    """The evidence text of one project: its title, period, summary, bullets and notes, plus the quotes of candidates from the same company (only those that occur verbatim in the source)"""
    parts = [proj.get("title", ""), proj.get("period", ""), proj.get("summary", ""), " ".join(map(str, as_list(proj.get("points")))),
             proj.get("notes", ""), role.get("org", ""), role.get("title", "")]
    k = org_key(role.get("org", ""))
    parts += [c.get("quote", "") for c in cands if org_key(c.get("org", "")) == k]
    return "\n".join(str(p) for p in parts if p)


def profile_evidence(prof: dict, cands: list) -> str:
    """The evidence text of the whole profile (for the headline and the introduction)"""
    parts = []
    for r in as_list(prof.get("roles")):
        parts.append(f"{r.get('org', '')} {r.get('title', '')} {r.get('start', '')} {r.get('end') or ''}")
        for p in as_list(r.get("projects")):
            parts.append(project_evidence(r, p, []))
    parts += [f"{s.get('category', '')}: {', '.join(map(str, as_list(s.get('items'))))}" for s in as_list(prof.get("skills")) if isinstance(s, dict)]
    parts += [c.get("quote", "") for c in cands]
    return "\n".join(parts)


def pick(v, lang="ko"):
    """The value of that language when it has the {ko, en} shape (ko when missing), otherwise the value itself"""
    return (v.get(lang) or v.get("ko")) if isinstance(v, dict) and ("ko" in v or "en" in v) else v


# Tasks

def obj_schema(**props) -> dict:
    """A strict-mode JSON Schema (every field required, additionalProperties false). Only backends that accept an output schema (codex) get it"""
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


STR, STRS = {"type": "string"}, {"type": "array", "items": {"type": "string"}}

SYSTEM = ("You help write a resume from facts the person gave. Use only facts in the evidence. Never add numbers, tools, products, "
          "clients or results that are not in the evidence. Return only JSON.")


def ask(task, prompt, required, schema, result, log):
    """One LLM call. None when the format stays wrong in the end (logged in the record). When the LLM stops, raises Stopped carrying the results so far"""
    try:
        return llm.run(task, prompt, system=SYSTEM, want_json=True, required=required, schema=schema)
    except llm.LLMUnavailable as e:
        raise Stopped(str(e), result, log)
    except ValueError as e:
        log.append({"where": task, "kept": False, "why": [t("bad_answer", why=e)]})
        return None


def task_write(prof: dict, cands: list, style: dict, lang: str = "ko") -> tuple:
    """Every resume part from the evidence, through src/write_resume.py. Returns (new profile, the record's texts). The command line reaches write_resume.main() directly."""
    import write_resume as W  # imported here: write_resume imports cover.py, which imports this module
    try:
        new, rec = W.draft(prof, style=W.load_style(style.get("_name") if isinstance(style, dict) else None))  # the named pack, else the default
    except W.Stopped as e:  # the model never answered: the caller gets this module's Stopped, like from every other task
        raise Stopped(str(e), copy.deepcopy(prof), [])
    return new, rec["texts"]  # the new profile and every drafted text with its checks


def task_jd(prof: dict, jd: str) -> tuple:
    """Skill categories to put first for a job posting (skillsFocus), competencies to send back (competencyWeak) and the project order (projectOrder). Only names that exist in the profile are accepted. Returns (config suggestion, record)"""
    cats = [s.get("category") for s in as_list(prof.get("skills")) if isinstance(s, dict) and s.get("category")]
    comps = [c[0] for c in as_list(pick(prof.get("competencies"))) if isinstance(c, (list, tuple)) and c]
    projs = [p["id"] for r in as_list(prof.get("roles")) for p in as_list(r.get("projects")) if p.get("id")]
    plist = "\n".join(f"- {p['id']}: {p.get('title', '')}" for r in as_list(prof.get("roles")) for p in as_list(r.get("projects")) if p.get("id"))
    prompt = (f"Job description:\n<<<\n{jd[:8000]}\n>>>\n\nSkill categories: {json.dumps(cats, ensure_ascii=False)}\n"
              f"Competencies: {json.dumps(comps, ensure_ascii=False)}\nProjects:\n{plist}\n\n"
              "Pick what this job needs. skillsFocus: categories the job asks for, most important first. competencyWeak: competencies the "
              "job does not ask for. projectOrder: project ids, most relevant first. Use only the names and ids listed above.\n"
              'Return JSON: {"skillsFocus": [...], "competencyWeak": [...], "projectOrder": [...]}')
    log, cfg = [], {}
    out = ask("draft-jd", prompt, ("skillsFocus", "competencyWeak", "projectOrder"),
              obj_schema(skillsFocus=STRS, competencyWeak=STRS, projectOrder=STRS), cfg, log)
    if out is None:
        return cfg, log
    for key, allowed in (("skillsFocus", cats), ("competencyWeak", comps), ("projectOrder", projs)):
        got = [x for x in as_list(out.get(key)) if isinstance(x, str)]
        unknown = [x for x in got if x not in allowed]
        good = list(dict.fromkeys(x for x in got if x in allowed))  # without duplicates, order kept
        # an empty list (no competency to send back) is not a rejection. A suggestion counts as caught only when unknown names are mixed in
        log.append({"where": key, "proposal": got, "kept": good if good else not unknown, "why": [t("unknown_names", names=", ".join(unknown))] if unknown else []})
        if good:
            cfg[key] = good
    if comps and set(cfg.get("competencyWeak", [])) == set(comps):  # if every competency is sent back, no layer is left
        log.append({"where": "competencyWeak", "kept": False, "why": [t("all_back")]})
        cfg.pop("competencyWeak")
    return cfg, log


HANGUL = re.compile(r"[가-힣]")  # a text that still needs translating


def md_units(md: str) -> list:
    """The parts of a Markdown body that hold Korean, as ((line, cell), text): each cell of a table row, each bullet, heading
    and plain line (cell -1 for a whole line). Notes in <!-- --> are not parts: they are not printed."""
    out = []  # in reading order
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), str(md or ""), flags=re.S)  # notes blanked, so the line numbers stay
    for li, ln in enumerate(text.split("\n")):  # line by line
        if ln.strip().startswith("|"):  # a table row
            cells = ln.strip().strip("|").split("|")  # its cells
            if all(re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in cells):  # the separator row
                continue  # nothing to say
            out += [((li, ci), c.strip()) for ci, c in enumerate(cells) if HANGUL.search(c)]  # the cells in Korean
        elif HANGUL.search(ln):  # a bullet, a heading or a line of text
            out.append(((li, -1), re.sub(r"^\s*(?:[-*]|#{1,6})\s+", "", ln).strip()))  # its words, without the mark
    return out


def md_apply(md: str, repl: dict) -> str:
    """The Markdown body with translated parts put back ({(line, cell): English}), and the notes in <!-- --> left out."""
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), str(md or ""), flags=re.S)  # the same line numbers as md_units
    lines = text.split("\n")  # line by line
    for li, ln in enumerate(lines):  # each line
        if ln.strip().startswith("|"):  # a table row
            lead = ln[:len(ln) - len(ln.lstrip())]  # its indent
            cells = ln.strip().strip("|").split("|")  # its cells
            cells = [f" {repl[(li, ci)]} " if (li, ci) in repl else c for ci, c in enumerate(cells)]  # translated where there is a translation
            lines[li] = lead + "|" + "|".join(cells) + "|"  # the row again
        elif (li, -1) in repl:  # a whole line
            mark = re.match(r"^\s*(?:[-*]|#{1,6})\s+", ln)  # its bullet or heading mark
            lines[li] = (mark.group(0) if mark else "") + repl[(li, -1)]  # the mark kept
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"  # the blank lines a note left are closed up


def _strings(prof: dict, skip_drafted: bool = False) -> list:
    """The text fields to translate: (path, Korean text, is it a name field). Name fields (company, school, place, department,
    job title, project title) may be transliterated, while sentence fields accept no new proper nouns. A per-language shape
    ({ko, en}) translates the ko text into the en path, and the introduction goes to intro.en (the Korean one stays).
    A per-language field whose en side the person already wrote is left alone. With skip_drafted, the parts a resume draft
    writes in both languages are left out: the headline, the introduction, the cards and selected projects, the
    competencies, about me, the motivation and the projects. Only what the draft does not hold is asked for."""
    out = []

    def add(path, text, name=False):
        if isinstance(text, str) and text.strip() and HANGUL.search(text):  # only what is still in Korean
            out.append((path, text, name))

    def written(v):  # a per-language field whose English side exists
        return isinstance(v, dict) and bool(v.get("en"))

    P = prof.get("person") or {}
    add(("person", "tagline"), P.get("tagline"), True)
    for k in ("location", "info"):  # where the person lives, and the personal line some Korean resumes print (birth year, place)
        v = P.get(k)  # a text, or one per language
        if isinstance(v, dict):  # per language: an "en" the person wrote, even an empty one, is theirs (empty prints no row)
            if "en" not in v:  # no English side at all
                add(("person", k, "en"), v.get("ko"), True)  # its Korean side, into the English one
        else:  # one text for both editions
            add(("person", k), v, True)  # place names may be romanized
    S = prof.get("summary") or {}
    intro = S.get("intro")
    if not skip_drafted:  # the draft writes the top of the resume in both languages
        add(("summary", "headline"), S.get("headline"))
        if not written(intro):  # the person's own English stays
            add(("summary", "intro", "en"), intro.get("ko") if isinstance(intro, dict) else intro)
    for ri, r in enumerate(as_list(prof.get("roles"))):
        for k in ("org", "title", "dept", "place"):
            add(("roles", ri, k), r.get(k), True)
        career = r.get("career") if isinstance(r.get("career"), dict) else {}  # a ledger's career block
        if not r.get("org") and not (career.get("en") or {}).get("name"):  # a ledger role with no English name
            add(("roles", ri, "heading"), r.get("heading"), True)  # its heading is what the resume prints
        if skip_drafted:  # the draft writes each printed project's title and sentences
            continue
        for pi, p in enumerate(as_list(r.get("projects"))):
            add(("roles", ri, "projects", pi, "title"), p.get("title"), True)
            add(("roles", ri, "projects", pi, "summary"), p.get("summary"))
            for qi, q in enumerate(as_list(p.get("points"))):
                add(("roles", ri, "projects", pi, "points", qi), q)
            fig = p.get("figure")
            if isinstance(fig, dict):  # figure text (caption, steps, rows)
                add(("roles", ri, "projects", pi, "figure", "caption"), fig.get("caption"), True)  # a figure caption has the shape of a title (capitalised words are common)
                key = "steps" if isinstance(fig.get("steps"), list) else "rows"
                for si, st in enumerate(as_list(fig.get(key))):
                    for j, v in enumerate(st if isinstance(st, list) else []):
                        add(("roles", ri, "projects", pi, "figure", key, si, j), v, j == 0)
    for ei, e in enumerate(as_list(prof.get("education"))):
        for k in ("school", "major", "degree"):
            add(("education", ei, k), e.get(k), True)
    for si, s in enumerate(as_list(prof.get("sections"))):
        add(("sections", si, "title"), s.get("title"), True)
        for ii, it in enumerate(as_list(s.get("items"))):
            add(("sections", si, "items", ii), it, True)  # names such as certificates, awards and papers, which are translated as names
        if isinstance(s.get("body_md"), str) and not s.get("items"):  # the ledger form: a Markdown body, often a table
            for (li, ci), text in md_units(s["body_md"]):  # each cell and line in Korean
                add(("sections", si, "body_md", li, ci), text, True)  # names and short phrases, as the items above
    for si, s in enumerate(as_list(prof.get("skills"))):  # skill groups: their names, and items written in Korean
        if isinstance(s, dict):
            add(("skills", si, "category"), s.get("category"), True)
            for ii, it in enumerate(as_list(s.get("items"))):
                add(("skills", si, "items", ii), it, True)
    for key in ("competencies", "about", "motivation"):  # fields that can have a per-language shape
        v = prof.get(key)
        if skip_drafted or written(v):  # the draft writes them, or the person did
            continue
        src, dst = (v.get("ko"), (key, "en")) if isinstance(v, dict) else (v, (key,))
        if key == "motivation":
            if isinstance(src, list):
                for bi, b in enumerate(src):
                    add(dst + (bi,), b)
            else:
                add(dst, src)
            continue
        for ci, c in enumerate(as_list(src)):
            if not isinstance(c, (list, tuple)):
                continue
            if c:
                add(dst + (ci, 0), c[0], True)
            if len(c) > 1:
                if isinstance(c[1], str):
                    add(dst + (ci, 1), c[1])
                else:
                    for bi, b in enumerate(as_list(c[1])):
                        add(dst + (ci, 1, bi), b)
    for key in ("cards", "highlights", "layers"):
        v = S.get(key)
        if written(v) or (skip_drafted and key != "layers"):  # the person's own English, or the draft's part
            continue
        src, dst = (v.get("ko"), ("summary", key, "en")) if isinstance(v, dict) else (v, ("summary", key))
        for ci, c in enumerate(as_list(src)):
            if key == "highlights" and isinstance(c, dict):
                add(dst + (ci, "title"), c.get("title"), True)
                add(dst + (ci, "where"), c.get("where"), True)
                for ri, row in enumerate(as_list(c.get("rows"))):
                    for j, val in enumerate(row if isinstance(row, list) else []):
                        add(dst + (ci, "rows", ri, j), val, j == 0)
            elif isinstance(c, (list, tuple)):
                for j, val in enumerate(c):
                    add(dst + (ci, j), val, j == 0)
    return out


def _set(prof, path, value):
    """Sets the value at the path. When the en side of a per-language shape does not exist yet, it is created as a copy of ko.
    When the introduction is a single text, it is turned into {ko: text} first and then en is added"""
    if path[:3] == ("summary", "intro", "en") and not isinstance((prof.get("summary") or {}).get("intro"), dict):
        prof.setdefault("summary", {})["intro"] = {"ko": prof["summary"].get("intro")}
    obj = prof
    for i, k in enumerate(path[:-1]):
        if k == "en" and isinstance(obj, dict) and "en" not in obj:
            obj["en"] = copy.deepcopy(obj.get("ko"))
        obj = obj[k]
    obj[path[-1]] = value


def _english_issues(ko: str, en: str, name: bool, allowed: set, style: dict) -> list:
    """The problems of one translation: numbers, number words, kept English words of the source, highlight count, banned characters. A sentence field accepts no new proper nouns (capitalised words that do not start a sentence)"""
    why = []
    kn, en_n = {v for v, _ in F.number_tokens(ko)}, {v for v, _ in F.number_tokens(en)}
    if kn - en_n:
        why.append(t("lost_number"))
    if en_n - kn:
        why.append(t("new_number"))
    if F.number_words(en) and not re.search(r"배|절반|반|수십|수백|수천|수만|여러", ko):
        why.append(t("new_number_word", words=", ".join(sorted(F.number_words(en)))))
    lost = sorted(w for w in F.latin_tokens(ko) if w not in en.lower())
    if lost:
        why.append(t("lost_latin", words=", ".join(lost[:5])))
    if not name:
        caps = set()
        for sent in re.split(r"(?<=[.!?:;])\s+", en):
            words = re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]*", sent)
            caps |= {w.lower().strip(".") for w in words[1:] if w[0].isupper()}
        joined = {w.replace(" ", "") for w in allowed}
        new = sorted(w for w in caps if not F.plural_ok(w, allowed) and w not in joined and w not in F.COMMON_EN and w not in {"i", "a"})
        if new:
            why.append(t("new_name", words=", ".join(new[:5])))
    if ko.count("==") != en.count("=="):
        why.append(t("highlight_count"))
    return why + style_issues(en, style)


def task_translate(prof: dict, style: dict, skip_drafted: bool = False) -> tuple:
    """Korean profile to English. Fields that do not pass stay in Korean and are recorded. Returns (new profile, record).
    skip_drafted asks only for what a resume draft does not write (see _strings)"""
    new, log = copy.deepcopy(prof), []
    items = _strings(prof, skip_drafted)
    done = []  # (path, Korean, name field, English)
    for i in range(0, len(items), 25):  # 25 fields per call
        chunk = items[i:i + 25]
        src = {str(j): t for j, (_, t, _) in enumerate(chunk)}
        prompt = ("Translate each Korean resume field to natural, concise English for a resume. Keep numbers, product and tool names, "
                  "and URLs exactly. Keep ==marks== around the same phrase, and never add ==marks== to a field that has none. "
                  "Company and school names: romanize if they have no English name.\n"
                  f"Fields (JSON object id -> Korean):\n{json.dumps(src, ensure_ascii=False)}\n"
                  'Return JSON: {"t": {"<id>": "<English>", ...}} with every id.')
        try:
            out = ask("draft-translate", prompt, ("t",), None, new, log)
        except Stopped:  # when stopped, apply the fields translated so far and leave with them
            _apply_translations(new, log, prof, done, style)
            raise Stopped(t("stopped_short"), new, log)
        got = out.get("t") if isinstance(out, dict) and isinstance(out.get("t"), dict) else {}
        for j, (path, ko, name) in enumerate(chunk):
            en = got.get(str(j))
            done.append((path, ko, name, en if isinstance(en, str) else None))
    _apply_translations(new, log, prof, done, style)
    return new, log


def _apply_translations(new, log, prof, done, style):
    """Checks the translations and puts in only the fields that pass. A proper noun in a sentence field is accepted only when it
    is in the translation of a name field (company, school, ...), in an English word of the source or in an English name"""
    allowed = F.latin_tokens(json.dumps(prof, ensure_ascii=False))
    bodies = {}  # section index -> {(line, cell): English}
    for path, ko, name, en in done:
        if name and en:  # words of the name-field translation and the spaced name joined together (Beta Commerce gives betacommerce)
            words = re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]*", en)
            allowed |= {w.lower() for w in words} | {"".join(words).lower()}
    allowed |= {w.lower() for w in re.findall(r"[A-Za-z]+", str((prof.get("person") or {}).get("name_en", "")))}
    for path, ko, name, en in done:
        if en is None:
            log.append({"where": ".".join(map(str, path)), "before": ko, "proposal": None, "kept": False, "why": [t("no_translation")]})
            continue
        en = en.strip()
        if "==" not in ko and "==" in en:  # an emphasis mark that the source lacks is only formatting, so it is removed and the translation is accepted
            en = en.replace("==", "")
        why = [t("empty_translation")] if not en else _english_issues(ko, en, name, allowed, style)
        log.append({"where": ".".join(map(str, path)), "before": ko, "proposal": en, "kept": not why, "why": why})
        if not why and path[2:3] == ("body_md",) and path[0] == "sections":  # one cell or line of a Markdown body
            bodies.setdefault(path[1], {})[(path[3], path[4])] = en.replace("|", "/")  # a bar would split the table cell
        elif not why:
            _set(new, path, en)
    for si, repl in bodies.items():  # each Markdown body with translated parts
        new["sections"][si]["body_md"] = md_apply(prof["sections"][si]["body_md"], repl)  # rebuilt around them, notes left out
    done.clear()


FIG_PROMPT = ("Evidence about one project:\n<<<\n{ev}\n>>>\n\n"
              "Propose one figure for a portfolio slide about this project, using only facts in the evidence. Choose the type that fits:\n"
              '- flow: a process in 3 to 6 steps -> {{"type": "flow", "caption": "...", "steps": [["step name", "short description"], ...]}}\n'
              '- compare: before and after numbers that appear in the evidence -> {{"type": "compare", "unit": "...", "caption": "...", '
              '"rows": [["metric", before, after], ...]}}\n'
              '- layers: a system in 2 to 5 layers, top to bottom -> {{"type": "layers", "caption": "...", "rows": [["layer", "what it holds"], ...]}}\n'
              "Write the text in Korean. If the evidence has no before/after numbers, do not use compare.\n"
              'Return JSON: {{"figure": {{...}}}}')


def check_figure(f, ev: str, style: dict | None = None) -> list:
    """Checks figure data: the same shape rules as checkFigure in deck_slides.js, plus a check of every text and value against the evidence"""
    if not isinstance(f, dict) or f.get("type") not in ("flow", "compare", "layers"):
        return [t("unknown_figure")]
    rows = f.get("steps") if f["type"] == "flow" else f.get("rows")
    if not isinstance(rows, list) or not 2 <= len(rows) <= 8:
        return [t("rows_count")]
    bad, texts = [], [str(f.get("caption") or ""), str(f.get("unit") or "")]
    ev_vals = {v for v, _ in F.number_tokens(ev)}
    for r in rows:
        if f["type"] == "compare":
            if not (isinstance(r, list) and len(r) == 3 and r[0] and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in r[1:])):
                bad.append(t("compare_row"))
                continue
            missing = [v for v in r[1:] if float(v) not in ev_vals]
            if missing:
                bad.append(t("value_missing", values=missing))
            texts.append(str(r[0]))
        elif not (isinstance(r, list) and r and isinstance(r[0], str) and r[0].strip()):
            bad.append(t("empty_name"))
        else:
            texts += [str(x) for x in r if isinstance(x, str)]
    text = " ".join(texts)
    bad += F.unsupported(text, ev)
    return bad + (style_issues(text, style) if style else [])


def task_figures(prof: dict, cands: list, style: dict | None = None) -> tuple:
    """Figure data suggested for every project that has no figure. Returns (new profile, record)"""
    new, log = copy.deepcopy(prof), []
    for ri, r in enumerate(as_list(new.get("roles"))):
        for pi, p in enumerate(as_list(r.get("projects"))):
            if p.get("figure"):
                continue
            ev = project_evidence(r, p, cands)
            out = ask("draft-figure", FIG_PROMPT.format(ev=ev), ("figure",), None, new, log)
            if out is None:
                continue
            fig = out.get("figure")
            why = check_figure(fig, ev, style)
            log.append({"where": f"roles[{ri}].projects[{pi}]", "title": p.get("title"), "proposal": fig, "kept": not why, "why": why})
            if not why:
                p["figure"] = fig
    return new, log


def main() -> int:
    a = sys.argv[1:]
    if a and a[0] in ("write", "check"):  # the drafting step of every resume part and its check (src/write_resume.py)
        import write_resume  # imported here: it imports cover.py, which imports this module
        return write_resume.main(a)  # its own parser reads the options
    if len(a) < 2 or a[0] not in ("write", "jd", "translate", "figures") or (a[0] == "jd" and (len(a) < 3 or a[2].startswith("--"))):
        print(__doc__)
        return 1
    task, src = a[0], pathlib.Path(a[1])
    prof = json.loads(src.read_text(encoding="utf-8"))
    cands = load_cands(a[a.index("--cands") + 1] if "--cands" in a else None)
    style = style_pack(a[a.index("--style") + 1] if "--style" in a else "default")
    stopped = None
    try:
        if task == "write":
            result, log = task_write(prof, cands, style)
        elif task == "jd":
            result, log = task_jd(prof, pathlib.Path(a[2]).read_text(encoding="utf-8"))
        elif task == "translate":
            result, log = task_translate(prof, style)
        else:
            result, log = task_figures(prof, cands, style)
    except Stopped as e:  # the LLM stopped midway: the results so far are kept
        stopped, result, log = str(e), e.result, e.log
        if not log:
            print(t("no_llm", why=stopped))
            return 2
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{src.stem}.{task}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    suffix = {"write": "draft", "jd": "jd", "translate": "en", "figures": "figs"}[task]
    dst = src.with_name(f"{src.stem}.{suffix}.json")  # a new file next to the input (the input is never overwritten)
    dst.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    proposals = [x for x in log if "proposal" in x]
    kept = sum(1 for x in proposals if x.get("kept"))
    failed = t("done_failed", n=len(log) - len(proposals)) if len(log) > len(proposals) else ""  # answers in the wrong form, when there were any
    print(t("done", task=task, n=len(proposals), kept=kept, dropped=len(proposals) - kept, failed=failed, out=dst, log=OUT / (src.stem + "." + task + ".json")))
    for x in [x for x in log if not x.get("kept")][:8]:
        print(f"  - {x['where']}: {'; '.join(x.get('why', []))}")
    if stopped:
        print(t("stopped", why=stopped[:120]))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
