#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resume drafting: every part that the resume prints, written from the evidence in Korean and English (docs/WRITING.md).

The resume (src/resume_form.js) prints a headline, an introduction, overview cards, selected-project cards, core
competencies with their evidence projects, the work-history items, a company line per role, an "about me" and a motivation.
A profile in the ledger form holds the facts but none of those sentences. This step writes them:

  1. items        the work-history items of each role (one item is one project), in the order scope, decision, result,
                  with one highlighted phrase, and one company line per role
  2. summary      the headline, the introduction, four overview cards and the selected-project cards
  3. competencies four to six competencies, each with the projects it rests on
  4. about        the "about me" sections and the motivation
  5. repair       one more call for every text the checks rejected; what still fails is dropped and recorded

Every sentence cites evidence ids (cover.py's units: `nara-2#3` is the third block of a project). Each language's text is
held against the text of the ids it cites: numbers, names and tools (factcheck.py and cover.py's name rules), claim strength
(factcheck.claim_issues) and the style pack (banned characters, patterns and words, coined terms, lengths, highlights).
The new profile carries every sentence with its ids under "evidence", so `check` can prove it later and the panel can show
the evidence of any sentence. The ids always refer to the ledger as it was before drafting (ledger_view()).

  python3 src/write_resume.py write <profile.json> [--job posting.md] [--style pack] [--langs ko,en] [--parts items,summary,...]
        [--items N] [--backend name] [-o out.json] [--raw answers.json] [--replay answers.json]
  python3 src/write_resume.py check <profile.json> [--style pack] [--json out.json]

`src/draft.py write` and `src/draft.py check` run the same code. The input profile is never overwritten.
"""
from __future__ import annotations  # `str | None` hints on older Python versions

import argparse  # command line
import copy  # the new profile is a copy of the old one
import datetime  # the date in the record
import hashlib  # fingerprints of the inputs
import json  # every file is JSON
import math  # rounding up the item bounds
import os  # the language of messages
import pathlib  # paths
import re  # the text rules
import sys  # exit codes

import cover as C  # evidence units, word matching, the posting reader, the name and number rules, the style loader
import factcheck as F  # numbers, Latin words, organisations, claim strength
import llm  # the one door to a model

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
PROMPTS = ROOT / "src" / "prompts"  # prompt templates (write_*.md)
SCHEMA_RECORD = "offerowl-write/0.1"  # the draft record and the _draft stamp of a new profile
LANGS = ("ko", "en")  # the two languages of every part
PARTS = ("items", "summary", "competencies", "about", "deck")  # the drafting stages, in order
SYSTEM = ("You write resume text from facts the person gave. Use only the facts in the evidence you cite. Never add numbers, tools, "  # evidence only, and never a larger part than the evidence gives
          "products, clients, places or results that the evidence does not state, and never make the person's part larger than "
          "the evidence makes it. Return only JSON.")  # the system text of every call

# messages (Korean and English)

MSG = {  # one table per language with the same keys; t() falls back to English
    "en": {
        "done": "write: {parts} drafted in {langs}; {kept} texts kept, {dropped} dropped, {calls} model calls -> {out}  (record {rec})",
        "stopped": "No model answered ({why}). Nothing was drafted; the profile is unchanged.",
        "stopped_mid": "The model stopped part way ({why}). The parts drafted so far were kept.",
        "drop": "  dropped {at} [{lang}]: {why}",
        "check_head": "resume check: {n} sentences in {fields} fields",
        "check_line": "  [{mark}] {name}: {detail}",
        "check_pass": "resume check: PASS ({sent} sentences, 0 fact flags, {claims} claim flags, {polish} to polish)",
        "check_fail": "resume check: FAIL ({facts} fact flags, {style} style flags, {claims} claim flags, {unlinked} texts without evidence)",
        "c_facts": "fact check", "c_claims": "claim strength", "c_style": "style pack", "c_linked": "evidence ids", "c_polish": "polish",
        "c_parts": "parts present",
        "i_empty": "empty text", "i_unknown_id": "unknown or uncitable evidence id {id}", "i_no_ev": "no evidence id",
        "i_frame_where": "a framing sentence may stand only in the motivation", "i_number": "number not allowed: {detail}",
        "i_number_word": "counted amount not allowed: {detail}", "i_name": "name or tool not in the cited evidence: {detail}",
        "i_org": "organisation not in the cited evidence: {detail}", "i_name_src": "declared source for {detail} is not in the cited evidence",
        "i_claim": "{detail}", "i_banned_char": "banned character {detail}", "i_banned_pattern": "banned wording: {detail}",
        "i_banned_word": "banned word: {detail}", "i_coined": "coined term {detail}", "i_too_long": "too long ({detail})",
        "i_highlight": "highlight: {detail}", "i_ending": "Korean sentence ends like prose ({detail})",
        "i_routine": "the highlight reads as a routine duty ({detail})", "i_title_end": "the title does not end with a work noun ({detail})",
        "i_unlinked": "text without evidence: {detail}", "i_edited": "the text changed after drafting; draft it again or link its evidence",
    },
    "ko": {
        "done": "초안: {parts} 를 {langs} 로 씀; 글 {kept}개 남김, {dropped}개 버림, 모델 호출 {calls}번 -> {out}  (기록 {rec})",
        "stopped": "모델이 답하지 않았다({why}). 아무것도 쓰지 않았고 프로필은 그대로다.",
        "stopped_mid": "모델이 중간에 멈췄다({why}). 그때까지 쓴 부분은 남겼다.",
        "drop": "  버림 {at} [{lang}]: {why}",
        "check_head": "이력서 검사: 칸 {fields}개, 문장 {n}개",
        "check_line": "  [{mark}] {name}: {detail}",
        "check_pass": "이력서 검사: 통과(문장 {sent}개, 사실 문제 0, 주장 세기 {claims}, 다듬을 것 {polish})",
        "check_fail": "이력서 검사: 실패(사실 문제 {facts}, 문체 {style}, 주장 세기 {claims}, 근거 없는 글 {unlinked})",
        "c_facts": "사실 대조", "c_claims": "주장 세기", "c_style": "문체 묶음", "c_linked": "근거 번호", "c_polish": "다듬을 것",
        "c_parts": "있는 부분",
        "i_empty": "빈 글", "i_unknown_id": "없거나 인용할 수 없는 근거 번호 {id}", "i_no_ev": "근거 번호가 없다",
        "i_frame_where": "틀을 잡는 문장은 지원 동기에만 둔다", "i_number": "쓸 수 없는 숫자: {detail}",
        "i_number_word": "쓸 수 없는 수량 표현: {detail}", "i_name": "달아 둔 근거에 없는 이름이나 도구: {detail}",
        "i_org": "달아 둔 근거에 없는 회사·기관 이름: {detail}", "i_name_src": "{detail} 의 원문이 달아 둔 근거에 없다",
        "i_claim": "{detail}", "i_banned_char": "금지 글자 {detail}", "i_banned_pattern": "금지 꼴: {detail}",
        "i_banned_word": "금지 낱말: {detail}", "i_coined": "지어낸 용어 {detail}", "i_too_long": "길다({detail})",
        "i_highlight": "노란 강조: {detail}", "i_ending": "문장이 서술형으로 끝난다({detail})",
        "i_routine": "강조가 당연한 업무로 읽힌다({detail})", "i_title_end": "제목이 일 명사로 끝나지 않는다({detail})",
        "i_unlinked": "근거 없는 글: {detail}", "i_edited": "초안 뒤에 글이 바뀌었다. 다시 쓰거나 근거를 다시 단다",
    },
}


def ui_lang() -> str:
    """Language of the messages: OFFEROWL_LANG, else the locale, else English."""
    v = (os.environ.get("OFFEROWL_LANG") or os.environ.get("LANG") or "en").lower()  # the panel sets OFFEROWL_LANG
    return "ko" if v.startswith("ko") else "en"  # only two languages exist


def t(key: str, **kw) -> str:
    """One message in the user's language, English when a Korean entry is missing."""
    table = MSG[ui_lang()]  # the chosen language
    return (table.get(key) or MSG["en"][key]).format(**kw)  # fall back to English, then fill the placeholders


def issue(code: str, **kw) -> dict:
    """One problem of a text: a stable code for programs and the detail for people."""
    return {"code": code, **kw}  # kw holds detail, id, ...


def issue_text(i: dict) -> str:
    """The message of one issue in the user's language."""
    return t("i_" + i["code"], **{k: v for k, v in i.items() if k != "code"})  # the issue's fields fill the placeholders


# Issue codes by level. Fact and style issues drop a text, claim issues drop it after the repair round, polish is only reported.
FACT_CODES = {"empty", "unknown_id", "no_ev", "frame_where", "number", "number_word", "name", "org", "name_src"}  # a fact the evidence lacks: the text is dropped
STYLE_CODES = {"banned_char", "banned_pattern", "banned_word", "coined", "too_long", "highlight"}  # a wording the pack forbids: the text is dropped
CLAIM_CODES = {"claim"}  # stronger than the evidence
POLISH_CODES = {"ending", "routine", "title_end"}  # worth a look, never a reason to drop

# the style pack

RESUME_DEFAULTS = {  # every option has a default, so a style pack may leave the resume object out
    "numbers": "evidence",  # evidence: a number only when the cited evidence states it; forbid: no numbers in the prose at all
    "items": 20,  # work-history items over the whole resume, shared out by tenure
    "work_words": {"en": 1200},  # the space of all work-history items in English words, shared out by tenure
    "title_chars": {"ko": 34}, "title_words": {"en": 12},  # item titles
    "item_chars": {"ko": 300}, "item_words": {"en": 75},  # one item's sentences together
    "highlight": {"ko": [6, 24], "en": [2, 9]},  # the length of one highlighted phrase
    "headline_chars": {"ko": 48}, "headline_words": {"en": 16},  # the headline
    "intro_chars": {"ko": 170}, "intro_words": {"en": 48},  # the introduction
    "card_chars": {"ko": 70}, "card_words": {"en": 20},  # one overview card
    "stat_chars": {"ko": 9}, "stat_words": {"en": 3},  # a proof tile's value on the deck's cover: one line of a quarter of the name panel
    "stat_en_chars": 16,  # and in English its letters too: three long words would still run past the tile
    "stat_note_chars": {"ko": 30}, "stat_note_words": {"en": 9},  # the note under it: three short lines
    "focus_chars": {"ko": 42}, "focus_words": {"en": 12},  # a focus column's line on the cover
    "focus_head_chars": {"ko": 14}, "focus_head_words": {"en": 3},  # a focus column's title, one line of a quarter of the slide
    "phase_chars": {"ko": 8}, "phase_words": {"en": 3},  # the kind of work over a station of the career path
    "path_chars": {"ko": 26}, "path_words": {"en": 8},  # a line under a station: two short lines of a fifth of the slide at most
    "path_key_chars": {"ko": 22}, "path_key_words": {"en": 6},  # what a role is known by: the same width, on one line
    "path_key_en_chars": 38,  # and in English its letters too, since one long word would run on to a second line
    "row_chars": {"ko": 60}, "row_words": {"en": 18},  # one row of a selected-project card
    "competencies": [4, 6],  # how many competencies (four to six, each with evidence)
    "competency_chars": {"ko": 190}, "competency_words": {"en": 52},  # one competency
    "about_items": 3, "about_quote": False,  # sections of the about me, and the optional quote box
    "about_chars": {"ko": 420}, "about_words": {"en": 110},  # one section of the about me
    "motivation_chars": {"ko": 320}, "motivation_words": {"en": 85},  # the motivation
    "highlights": 3,  # selected-project cards
    "ko_ending": "nominal",  # Korean items, cards and competencies end in a noun or a nominal form (the usual resume style); "plain" allows ~했다
    "banned_words": {"en": [], "ko": []},  # words a resume may not use (hype, dressed-up words)
    "coined": {"en": {}, "ko": {}},  # coined term to the term the industry uses
    "routine": {"en": [], "ko": []},  # words that make a highlighted result read as a routine duty (reported as polish)
    "title_end": {"en": [], "ko": []},  # when given, an item title should end with one of these work nouns (reported as polish)
    "rules": {"en": [], "ko": []},  # extra rules in words, carried by every prompt
    "avoid_lead": [],  # role keys the headline and the introduction should not lead with
}
LABELS = {  # the labels the renderer prints, per language
    "cards": {"ko": {"target": "지향 직무", "focus": "주력 분야", "strengths": "강점", "industries": "산업 도메인"},
              "en": {"target": "TARGET ROLE", "focus": "FOCUS", "strengths": "STRENGTHS", "industries": "INDUSTRIES"}},
    "rows": {"ko": {"challenge": "문제", "action": "한 일", "result": "결과"},
             "en": {"challenge": "CHALLENGE", "action": "ACTION", "result": "RESULT"}},
}
CARD_KEYS = ("target", "focus", "strengths", "industries")  # the overview cards, in print order
ROW_KEYS = ("challenge", "action", "result")  # the rows of a selected-project card
PART_RANK = {"scope": 0, "decision": 1, "result": 2}  # the order of an item's sentences


def pack_file(spec: str | None, hints=()) -> pathlib.Path | None:
    """The file of a style pack, found the way cover.load_style finds it."""
    if spec and ("/" in spec or spec.endswith(".json")):  # a path: as given, then from the repository root
        cands = [pathlib.Path(spec), ROOT / spec]  # a path given relative to the repository works from any folder
    else:  # a name: the packs in src/style, then the workspace's own
        cands = [ROOT / "src" / "style" / f"{spec or 'default'}.json"] + [pathlib.Path(h) / "style" / f"{spec}.json" for h in hints]  # the shipped packs first, then a workspace's own style/ folder
    return next((p for p in cands if p.is_file()), None)  # the first that exists


def load_style(spec: str | None = None, hints=()) -> dict:
    """The style pack (cover.py's loader: banned characters and patterns, the cover options) with the resume options merged in."""
    st = C.load_style(spec, hints)  # stops with a message when the pack is missing, so a typo never switches the rules off
    f = pack_file(spec, hints)  # the same file, read again for its resume object
    raw = json.loads(f.read_text(encoding="utf-8")) if f else {}  # the pack as written
    res = copy.deepcopy(RESUME_DEFAULTS)  # the defaults, overridden by the pack
    for k, v in (raw.get("resume") or {}).items():  # nested options merge, plain ones replace
        res[k] = {**res[k], **v} if isinstance(v, dict) and isinstance(res.get(k), dict) else v  # dict options merge key by key, others are replaced whole
    if res["numbers"] not in ("forbid", "evidence"):  # an unknown policy would silently allow numbers
        raise SystemExit("style resume.numbers must be forbid or evidence")  # fail early rather than let numbers through
    st["resume"] = res  # the merged options
    return st


def per_lang(opt, lang: str, fallback):
    """An option given per language ({"ko": 30}) or for both (30)."""
    if isinstance(opt, dict):  # a table per language
        return opt.get(lang, fallback)
    return opt if opt is not None else fallback  # one value for both languages


# evidence

CITABLE_KINDS = {"project", "context", "role", "skills", "section", "education"}  # ledger units a drafted sentence may cite
# Summary rows that the draft never rewrites stay citable: the hierarchy rows name clients and places
CITABLE_LOOSE = re.compile(r"^summary#l\d+$")  # summary#l1, l2, ...: the hierarchy rows
def pick(v, lang: str):
    """The language side of a {ko, en} value (the other side when it is missing), else the value itself."""
    if isinstance(v, dict) and ("ko" in v or "en" in v) and set(v) <= {"ko", "en"}:  # a language pair
        return v.get(lang) if v.get(lang) is not None else (v.get("ko") or v.get("en"))
    return v  # any other value


def ledger_view(profile: dict) -> dict:
    """The profile as the ledger had it before drafting: drafted titles and summaries go back to what they replaced. Evidence
    ids are block numbers, and a drafted summary would become block 1 of its project and shift every other block."""
    out = copy.deepcopy(profile)  # never change the caller's profile
    for r in C.as_list(out.get("roles")):  # every project of every role
        for p in C.as_list(r.get("projects")):  # a drafted project keeps its ledger fields under 'ledger'
            if isinstance(p, dict) and isinstance(p.get("ledger"), dict):  # a drafted project keeps what it replaced here
                old = p["ledger"]  # what the draft replaced
                if "title" in old:  # the ledger's own title
                    p["title"] = old["title"]  # the ledger's own title, which the units' heads use
                if old.get("summary") is None:  # the ledger had no summary
                    p.pop("summary", None)  # a drafted summary would become block 1 and shift every id
                else:  # the summary the person wrote
                    p["summary"] = old["summary"]  # a summary the person wrote stays the evidence it was
    return out


class Ctx:
    """What every drafted text is checked against: the units in both languages, the word index, the vocabularies, the
    glossary, the posting's names and the style."""

    def __init__(self, profile: dict, style: dict, posting: dict | None = None):  # posting is None for a general resume
        base = ledger_view(profile)  # ids refer to the ledger before drafting
        self.profile = base  # the ledger view, for the roles of projects
        self.U = {l: C.units_of(base, l) for l in LANGS}  # the same ids in both languages; summary rows differ by language
        self.lex = C.Lex(self.U["ko"])  # word matching, to narrow a whole project to the blocks that speak to a sentence
        self.vocab = C.tool_vocab(self.U["ko"])  # tool names of the profile: a text may not use one its evidence lacks
        self.where = C.name_locations(self.U["ko"])  # where each name lives, for the hint under a rejected name
        self.glossary = F.glossary_of(base)  # names across languages (factcheck.py)
        self.style = style  # the style pack with the resume options
        self.posting = posting or {}  # company, role, overview, lines
        P = base.get("person") or {}  # the person's own names may stand anywhere
        self.allow = set(F.latin_tokens(" ".join(str(P.get(k) or "") for k in ("name", "name_en"))))  # the person's own names never need evidence
        for table in (style.get("resume", {}).get("coined") or {}).values():  # the terms a pack prescribes (Root Cause for 근본원인) are words, not facts
            self.allow |= set(F.latin_tokens(" ".join(str(v) for v in (table or {}).values())))  # the person's own names never need evidence
        ident = " ".join([self.posting.get("company", ""), self.posting.get("role", "")])  # the posting's company and role
        self.posting_allow = set(F.latin_tokens(ident)) | ({C.flat(self.posting["company"])} if self.posting.get("company") else set())  # the posting's company and role words, and the company as one Korean word
        ov = self.posting.get("overview", "")  # the posting's own text about the company, allowed in the motivation only
        self.overview = {p.lower() for p, ini in C.name_parts(ov) if C.name_like(p, ini)} | set(F.latin_tokens(ov))  # name-like words and Latin words of the posting's own text
        role = self.posting.get("role", "")  # the job the person seeks: the target card and the motivation may name it
        initials = "".join(w[0] for w in re.findall(r"[A-Z][a-z]+", role)).lower()  # Site Reliability Engineer gives sre
        self.target = set(F.latin_tokens(role)) | ({initials} if len(initials) >= 2 else set()) | set(F.latin_tokens(" ".join(self.posting.get("lines", []))))  # the role, its initials and the words of the posting's lines

    def citable(self, uid: str) -> bool:
        """May a drafted text cite this id? Ledger units yes. Summary, competency and statement units are what the draft
        writes, so they may not be cited (they would cite themselves), except the hierarchy rows, which it never rewrites."""
        U = self.U["ko"]  # ids are the same in both languages
        if uid in U["proj"]:  # a whole project
            return True
        u = U["index"].get(uid)  # one unit
        return bool(u) and (u["kind"] in CITABLE_KINDS or bool(CITABLE_LOOSE.match(uid)))

    def text(self, ids, lang: str) -> str:
        """The evidence text of some ids in a language, with the words that name each unit's company and role."""
        return C.evidence_for(self.U[lang], ids)

    def blocks(self, ids, sentence: str) -> list:
        """The blocks a claim is held against: a block id gives its block; a project id gives the three blocks that share
        the most terms with the sentence (all of them when none does)."""
        U, out = self.U["ko"], []  # the units; block texts are the same in both languages
        q = self.lex.query(sentence)  # the sentence's terms with their twins in the other language
        for i in ids:  # each cited id
            if i in U["index"]:  # one unit
                out.append(U["index"][i]["text"])  # the block's own text
            elif i in U["proj"]:  # a whole project
                scored = sorted(((self.lex.score(q, b), b) for b in U["proj"][i]), reverse=True)  # best block first
                best = [b for s, b in scored[:3] if s > 0] or U["proj"][i]  # every block when none shares a term
                out += [U["index"][b]["text"] for b in best]  # the blocks that speak to the sentence
        return out


UNITS = {"gbps", "mbps", "kbps", "tbps", "gb", "mb", "kb", "tb", "pb", "eb", "gib", "mib", "tib", "mw", "kw", "w", "ghz", "mhz", "ms",  # units of a figure: 10Gbps and 5TB are numbers
         "ns", "us", "s", "nm", "bit", "bits", "bps", "fps", "x", "k", "m", "b", "g", "t", "p", "h", "hr", "hrs", "d", "yr", "yrs", "mo",
         "mos", "min", "mins", "sec", "secs", "tps", "qps", "rps", "ops", "gpu", "gpus", "node", "nodes", "core", "cores", "st", "nd",
         "rd", "th"}  # letters after digits that make a figure (10Gbps, 5TB), not a name


def mask_identifiers(text: str) -> str:
    """Product names that start with digits (1Password, 3scale) are names, not numbers; figures with units (10Gbps, 5TB) stay numbers."""
    def sub(m):  # one token that starts with digits and goes on with letters
        return "#" * len(m.group(0)) if m.group(2).lower() not in UNITS else m.group(0)  # a name is blanked, a figure kept
    return re.sub(r"(?<![\w.])(\d+)([A-Za-z][A-Za-z0-9]*)\b", sub, text or "")


def declared_names(text: str, names: dict, E: str, ctx: Ctx) -> tuple[list, list]:
    """Spellings the evidence holds in another form: the text's own declarations (the source must stand in the cited
    evidence) and the glossary pairs with one side in the text and the other in the evidence. Returns (accepted, issues)."""
    ok, bad = [], []  # accepted spellings, problems
    low, fE = text.lower(), C.flat(E)  # the text without case; the evidence without spaces or case
    for written, src in (names or {}).items():  # the model's declarations
        if written and written.lower() in low:  # a declaration for a word the text does not use is ignored
            if src and C.flat(src) in fE:  # the source really stands in the cited evidence
                ok.append(written)  # this spelling is backed
            else:  # a made-up source cannot launder a name
                bad.append(issue("name_src", detail=written))  # the declared source is not in the cited evidence
    ok += F.glossary_accept(text, E, ctx.glossary)  # a spelling whose twin in the other language stands in the evidence
    return ok, bad


# the checks of one text

def length_of(text: str, lang: str) -> int:
    """Words in English, characters without spaces in Korean: the units of every limit."""
    plain = text.replace("==", "")  # marks are not text
    return len(plain.split()) if lang == "en" else len(re.sub(r"\s", "", plain))


def style_issues(text: str, lang: str, kind: str, style: dict) -> list:
    """Banned characters, patterns and words, coined terms, and the Korean ending of item-like texts."""
    R = style["resume"]  # the resume options
    plain = text.replace("==", "")  # marks are not text
    bad = [issue("banned_char", detail=repr(c)) for c in style.get("banned_chars", "") if c in plain]  # one per banned character
    for pat, why in style.get("banned_patterns", []):  # a pattern comes with its reason
        if re.search(pat, plain):  # a banned wording
            bad.append(issue("banned_pattern", detail=why))  # the pack's reason is the message
    for w in list(per_lang(R["banned_words"], lang, [])) + list(style.get("cover", {}).get("banned_words", [])):  # the resume's and the letter's banned words
        hit = re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", plain, re.I) if re.match(r"[A-Za-z]", w) else (w in plain)  # Latin words as whole words
        if hit:  # a banned word
            bad.append(issue("banned_word", detail=w))  # the word itself is the detail
    for wrong, right in (per_lang(R["coined"], lang, {}) or {}).items():  # coined terms and the terms to use instead
        if wrong and wrong in plain:  # a coined term stands in the text
            bad.append(issue("coined", detail=f"{wrong} -> {right}"))  # the right term goes into the message
    if lang == "ko" and R["ko_ending"] == "nominal" and kind in ("item", "competency", "desc", "card", "target", "row") and re.search(r"(?:다|요)\.?$", plain.strip()):  # item-like texts only; the about me and the motivation are prose
        bad.append(issue("ending", detail=plain.strip()[-6:]))  # resume bullet style ends in a noun (~구축, ~설계, ~함)
    return bad


def text_issues(text: str, lang: str, ids: list, names: dict, ctx: Ctx, *, kind: str, frame: bool = False,
                limit: int | None = None, marks: tuple = (0, 0)) -> list:
    """Everything wrong with one text in one language. `kind` names the part (item, title, short, desc, headline, intro,
    card, row, competency, about, motivation); it decides the framing rule and whether claims are checked."""
    if not str(text or "").strip():  # nothing to check
        return [issue("empty")]
    bad = [issue("unknown_id", id=i) for i in ids if not ctx.citable(i)]  # ids that do not exist or may not be cited
    good = [i for i in ids if ctx.citable(i)]  # the evidence the text rests on
    if frame:  # a sentence about the company, from the posting
        if kind != "motivation":  # only the motivation may speak of the company without evidence
            bad.append(issue("frame_where"))  # a framing sentence anywhere else
    elif not good:  # a claim without evidence
        bad.append(issue("no_ev"))  # every claim needs an id
    E = ctx.text(good, lang)  # the cited text in the text's language
    E_both = E + "\n" + ctx.text(good, "en" if lang == "ko" else "ko")  # a bilingual row holds a name in both spellings
    accepted, name_bad = declared_names(text, names, E_both, ctx)  # spellings the evidence holds in another form
    bad += name_bad  # made-up sources are problems too
    plain = text.replace("==", "")  # marks are not text
    bad += C.number_issues(mask_identifiers(plain), E, ctx.style["resume"]["numbers"])  # numbers and counted words
    allow = set(ctx.allow) | (ctx.posting_allow | ctx.overview | ctx.target if kind == "motivation" else set())  # the posting's names only where the text speaks of the company
    if kind == "target":  # the target card says which job the person seeks, in the posting's words
        allow |= ctx.posting_allow | ctx.target  # the role's words and initials
    E_ext = "\n".join(accepted) if frame else E + "\n" + "\n".join(accepted)  # a framing text has only the accepted spellings
    bad += C.name_issues(plain, E_ext, allow, ctx.vocab, ctx.where, lang)  # names, tools and organisations
    if not frame and kind not in ("title", "short"):  # the claim strength of a sentence (a title claims nothing)
        for c in F.claim_issues(plain, ctx.blocks(good, plain)):  # each claim class of the sentence against the cited blocks
            bad.append(issue("claim", detail=F.claim_text(c, ui_lang()), claim=c["claim"], hedge=c["hedge"], quote=c["quote"]))  # the message, the class, the qualifier and the quoted evidence
    bad += style_issues(text, lang, kind, ctx.style)  # wording
    if limit and length_of(text, lang) > limit:  # longer than the part allows
        bad.append(issue("too_long", detail=f"{length_of(text, lang)} > {limit}"))  # the part's own limit
    room = {"stat": ctx.style["resume"].get("stat_en_chars", 16), "pathkey": ctx.style["resume"].get("path_key_en_chars", 38)}.get(kind)  # the letters a narrow place holds in English
    if room and lang == "en" and len(plain) > room:  # few words can still run past it
        bad.append(issue("too_long", detail=f"{len(plain)} letters > {room}"))  # shortened in the repair round, or left out
    found = re.findall(r"==(.+?)==", text)  # highlighted phrases
    if not marks[0] <= len(found) <= marks[1] or text.count("==") % 2:  # too many, too few, or one left open
        bad.append(issue("highlight", detail=f"{len(found)} (allowed {marks[0]} to {marks[1]})"))  # the part decides how many highlights it takes
    lo, hi = per_lang(ctx.style["resume"]["highlight"], lang, [2, 30])  # the size of one phrase
    for m in found:  # each phrase on its own
        size = len(m.split()) if lang == "en" else len(m.strip())  # words in English, characters with their spaces in Korean
        if not lo <= size <= hi:  # a phrase too short or too long
            bad.append(issue("highlight", detail=f"'{m}' is {size} (allowed {lo} to {hi})"))  # the phrase and its size
        for w in per_lang(ctx.style["resume"]["routine"], lang, []):  # a highlighted routine duty
            if w and w.lower() in m.lower():  # a routine duty inside the highlight
                bad.append(issue("routine", detail=w))  # reported as polish
    return bad


def hard(issues: list) -> list:
    """The issues that drop a text: facts and style (claims are counted apart)."""
    return [i for i in issues if i["code"] in FACT_CODES | STYLE_CODES]


def sentence_form(text: str, lang: str, style: dict) -> str:
    """A sentence as it is printed: Korean resume bullets end without a full stop, other sentences with one."""
    s = text.strip()  # the sentence as written
    if lang == "ko" and style["resume"]["ko_ending"] == "nominal":  # the terse noun-ending style: "... 재구성. ... 정상화"
        return s.rstrip(".")  # the joint adds the stop between sentences
    return s if s.endswith((".", "!", "?")) else s + "."  # prose ends with a stop


def joined(sentences: list, lang: str, style: dict) -> str:
    """Sentences joined into one printed text."""
    forms = [sentence_form(s, lang, style) for s in sentences if s.strip()]  # each as printed
    nominal = lang == "ko" and style["resume"]["ko_ending"] == "nominal"  # bullets join with a stop and no stop at the end
    return ". ".join(forms) if nominal else " ".join(forms)


# the profile's shape

def ym(s) -> float:
    """A year-month as a fractional year (2024.05 gives 2024.33); 0 when unreadable. Two-digit years read as 20YY."""
    m = re.search(r"((?:19|20)\d{2}|\d{2})[.\-/](\d{1,2})", str(s or ""))  # the first year-month of the text
    if not m:  # maybe a bare year
        y = re.search(r"(?:19|20)\d{2}", str(s or ""))  # a bare year counts from January
        return float(y.group(0)) if y else 0.0
    y = int(m.group(1)) + (2000 if len(m.group(1)) == 2 else 0)  # 24 reads as 2024
    return y + (min(max(int(m.group(2)), 1), 12) - 1) / 12  # the month as a fraction of the year


def months_of(r: dict) -> int:
    """A role's tenure in months (the first and the last month count), 1 when unknown."""
    c = r.get("career") or {}  # the ledger form
    a, b = ym(r.get("start") or c.get("start")), ym(r.get("end") or c.get("end") or "")  # start and end
    if not a:  # no start: unknown tenure
        return 1
    if not b:  # ongoing or unknown end: up to this month
        today = datetime.date.today()  # this month
        b = today.year + (today.month - 1) / 12  # as a fractional year
    return max(1, round((b - a) * 12) + 1)


def role_key(r: dict, ri: int) -> str:
    """The key cover.units_of gives a role: its unit ids start with it."""
    return C.clean_text(r.get("key") or r.get("org") or f"role{ri}").replace(" ", "_")


def role_name(r: dict, lang: str) -> str:
    """A role's short name in a language (for the selected-project cards)."""
    c = (r.get("career") or {}).get(lang) or {}  # the ledger's language half
    return C.clean_text(c.get("short") or c.get("name") or pick(r.get("short"), lang) or pick(r.get("org"), lang) or r.get("heading") or r.get("key"))


def project_id(p: dict, rk: str, pi: int) -> str:
    """A project's id, the way cover.units_of numbers a project without one."""
    return str(p.get("id") or f"{rk}-{pi}")


def roles_of(profile: dict) -> list:
    """The roles that have projects: [{key, role, months, projects: [(index, id, project)]}], in the profile's order."""
    out = []  # roles in the profile's order
    for ri, r in enumerate(C.as_list(profile.get("roles")), 1):  # numbered from 1, as cover.units_of numbers them
        rk = role_key(r, ri)  # the role's key
        ps = [(pi, project_id(p, rk, pi), p) for pi, p in enumerate(C.as_list(r.get("projects")), 1) if isinstance(p, dict)]  # each project with its position and id
        if ps:  # a role without projects has nothing to draft
            out.append({"key": rk, "role": r, "months": months_of(r), "projects": ps})  # tenure decides the role's share of the items
    return out


def shares(roles: list, total: int, words: int = 1200) -> dict:
    """How much each role may take: space in proportion to tenure (space follows time, measured in words,
    not items), at least one item, at most the role's projects. Returns {key: (low, high, words)}."""
    months = sum(x["months"] for x in roles) or 1  # all tenure
    out = {}  # role key to (low, high, words)
    for x in roles:  # each role
        share = x["months"] / months  # its tenure share
        base = total * share  # its share of the items
        n = len(x["projects"])  # its projects
        lo = max(1, min(n, int(base * 0.7)))  # at least one
        hi = max(lo, min(n, math.ceil(base * 1.3)))  # room for a role the job cares about, none for a short role
        out[x["key"]] = (lo, hi, max(40, round(words * share)))  # the bounds and the words of this role
    return out


def posting_of(text: str | None) -> dict | None:
    """The posting as company, role, overview and lines (cover.py's reader), or None without one."""
    if not text:  # a general resume
        return None
    p = C.parse_posting(text)  # sections, bullets, company
    return {"company": p.get("company", ""), "role": p.get("title", ""), "overview": p.get("overview", ""),
            "lines": [f"[{it['kind']}] {it['text']}" for it in p.get("items", [])], "sha": hashlib.sha256(text.encode()).hexdigest()[:16]}  # lines carry their kind for the prompt; the fingerprint goes into the stamp


# prompts

def prompt_text(name: str, **kw) -> str:
    """A template from src/prompts with its {{key}} placeholders filled."""
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")  # the template
    for k, v in kw.items():  # every placeholder given
        text = text.replace("{{" + k + "}}", str(v))  # the braces of the JSON examples stay untouched
    return text.strip()


def target_text(posting: dict | None, overview: bool = False) -> str:
    """What the resume is for, as the prompts say it. With `overview`, also what the posting says about the company and the
    team: the motivation and the target card connect the person's record with it."""
    if not posting:  # no posting: a general resume
        return "The resume is a general one for the person's own field: choose and phrase by the strength of the work."
    lines = "\n".join("- " + ln for ln in posting["lines"][:40])  # the posting's lines, capped
    about = (f"\nWhat the posting says about the company and the team (facts about the company, not about the person):\n{posting['overview']}"  # the motivation's only source on the company
             if overview and posting.get("overview") else "")  # the motivation's only source on the company
    return (f"The resume is for this job: {posting.get('role') or '(role not stated)'}" + (f" at {posting['company']}" if posting.get("company") else "")
            + f". What the job asks for:\n{lines}{about}\nWrite for this job: choose and phrase what the job asks for, and claim nothing the evidence lacks.")  # the job is the target, but never a reason to claim more


def rules_text(style: dict) -> str:
    """The shared sentence rules with the number rule and the pack's own rules and words."""
    R = style["resume"]  # the resume options
    numbers = ("- Write no numbers in the prose: no digits, no counted amounts (two, three, dozens), no years, no percentages. "  # the strict rule of a pack that forbids numbers
               "Say several, many, every or each instead." if R["numbers"] == "forbid" else  # say how to write around a number
               "- Use a number only when the cited evidence states the same number.")  # the pack decides
    extra = []  # the pack's own rules and banned words, in words
    for lang in LANGS:  # rules may differ per language
        extra += [f"- ({lang}) {r}" for r in per_lang(R["rules"], lang, [])]  # rules in words
        words = per_lang(R["banned_words"], lang, [])  # banned words
        if words:  # the pack bans some words
            extra.append(f"- ({lang}) Never use: " + ", ".join(words) + ".")  # told before the checker enforces them
        coined = per_lang(R["coined"], lang, {}) or {}  # coined terms and the right ones
        if coined:  # the pack maps coined terms to the usual ones
            extra.append(f"- ({lang}) Use the usual term: " + "; ".join(f"{right} (not {wrong})" for wrong, right in coined.items()) + ".")  # the right term first
    chars = style.get("banned_chars", "")  # banned characters of the pack
    if chars:  # the pack bans some characters
        extra.append("- Never use these characters: " + " ".join(chars) + ".")  # spaced so each one can be read
    return prompt_text("write_rules", numbers_rule=numbers, style="\n".join(extra))


def ko_style(style: dict) -> str:
    """The Korean sentence style the pack asks for, in words."""
    if style["resume"]["ko_ending"] == "nominal":  # the usual Korean resume style
        return "resume bullet style: end each sentence with a noun or a nominal form (~구축, ~설계, ~함), never with ~했다 or ~습니다."
    return "plain past tense (~했다)."


def unit_line(U: dict, uid: str) -> str:
    """One evidence line of a prompt."""
    return f"[{uid}] {U['index'][uid]['text']}"


def role_listing(ctx: Ctx, roles: list) -> str:
    """The evidence of some roles: each role's head and context blocks, then each project's head and blocks."""
    U, out = ctx.U["ko"], []  # the ledger text is the same in both languages
    for x in roles:  # role by role
        rk = x["key"]  # the prefix of its ids
        head = f"role:{rk}"  # the role's own unit
        if head in U["index"]:  # the role's own unit, when the profile has a head for it
            out.append(f"\n## {rk}\n[{head}] {U['index'][head]['text']}")  # the head names the organisation and the role
        out += [unit_line(U, u["id"]) for u in U["units"] if u["kind"] == "context" and u["id"].startswith(rk + "#c")]  # its context blocks
        for _, pid, _p in x["projects"]:  # each project with its blocks
            out.append(f"\n{pid}: {U['heads'].get(pid, pid)}")  # the project head: role, title and period
            out += ["  " + unit_line(U, b) for b in U["proj"].get(pid, [])]  # one line per block, with its id
    return "\n".join(out).strip()


def hierarchy_rows(ctx: Ctx) -> str:
    """The hierarchy rows of the profile (summary#l1 ...): they often name a project's client or place that the ledger
    text leaves out, so the items prompt lists them after the roles."""
    rows = [unit_line(ctx.U["ko"], u["id"]) for u in ctx.U["ko"]["units"] if CITABLE_LOOSE.match(u["id"])]  # Korean rows: the same language as the ledger
    return ("\n\n## hierarchy rows\n" + "\n".join(rows)) if rows else ""  # nothing when the profile has none


def loose_listing(ctx: Ctx, lang: str = "en") -> str:
    """Skills rows, sections, education and the hierarchy rows: evidence for the summary parts."""
    U = ctx.U[lang]  # the hierarchy rows read in English when the profile has them in English
    keep = [u for u in U["units"] if u["kind"] in ("skills", "section", "education") or CITABLE_LOOSE.match(u["id"])]  # the parts that name tools, credentials and schools
    return "\n".join(unit_line(U, u["id"]) for u in keep)


def items_listing(view: list) -> str:
    """The drafted items as the later prompts see them."""
    out = []  # one block of lines per item
    for it in view:  # each surviving item
        out.append(f"{it['project']} | {it['title'].get('en', '')} / {it['title'].get('ko', '')}")  # the project id and its title in both languages
        for s in it["sentences"]:  # its sentences with the ids they cite
            out.append(f"   - [{', '.join(s['ev'])}] {s.get('en', '')} / {s.get('ko', '')}")  # each sentence with the ids it cites
    return "\n".join(out)


def cited_listing(ctx: Ctx, view: list, extra=()) -> str:
    """The blocks the items cite (and some extra ids), each project's head once."""
    U = ctx.U["ko"]  # block texts
    ids = list(dict.fromkeys([e for it in view for s in it["sentences"] for e in s["ev"]] + list(extra)))  # in order, once
    out, heads = [], set()  # lines; project heads already printed
    for uid in ids:  # in the order the items cite them
        if uid in U["index"]:  # a unit
            u = U["index"][uid]  # the unit behind the id
            if u["pid"] and u["pid"] not in heads:  # the project's head first, once
                heads.add(u["pid"])  # printed once
                out.append(f"{u['pid']}: {U['heads'].get(u['pid'], '')}")  # the project's head
            out.append(("  " if u["pid"] else "") + unit_line(U, uid))  # blocks of a project are indented under its head
        elif uid in U["proj"]:  # a whole project: its blocks
            out.append(f"{uid}: {U['heads'].get(uid, '')}")  # the head of a whole project
            out += ["  " + unit_line(U, b) for b in U["proj"][uid]]  # all of its blocks
    return "\n".join(out)


def evidence_block(ctx: Ctx, ids) -> str:
    """The evidence lines of some ids, for the repair request."""
    U, out = ctx.U["ko"], []  # units and the lines of the request
    for uid in dict.fromkeys(ids):  # once each
        if uid in U["proj"]:  # a project lists its blocks
            out.append(f"{uid}: {U['heads'].get(uid, '')}")  # the project's head
            out += ["  " + unit_line(U, b) for b in U["proj"][uid]]  # all of its blocks
        elif uid in U["index"]:  # one unit
            out.append(unit_line(U, uid))  # the unit's line
    return "\n".join(out)


# the model

class Stopped(Exception):
    """The model stopped; the message says why."""


def model_ask(backend: str | None, raw: list | None):
    """The real model through llm.run(). Every answer is appended to `raw` for audit and replay."""

    def ask(task: str, prompt: str, required: tuple):  # the same signature as a test stand-in
        try:
            out = llm.run(task, prompt, system=SYSTEM, want_json=True, required=required, backend=backend, timeout=900)  # long answers take time
        except llm.LLMUnavailable as e:  # no backend, or it stopped
            raise Stopped(str(e))  # the caller keeps what was written before
        except ValueError:  # it answered, but never in the right shape
            out = None  # an unusable answer counts as none
        if raw is not None:  # kept as the model wrote it, before any check
            raw.append({"task": task, "answer": out})  # the answer as the model wrote it
        return out
    return ask


def replay_ask(answers: list):
    """Serve stored answers in order, by task: re-checking a draft after a rule change costs no call."""
    queue = list(answers)  # what is left to serve

    def ask(task: str, prompt: str, required: tuple):  # the same signature as model_ask's
        for i, a in enumerate(queue):  # the next stored answer of this task
            if a.get("task") == task:  # the first stored answer of this task
                queue.pop(i)  # used once
                return a.get("answer")
        raise Stopped(f"no stored answer for {task}")  # the replay ran out
    return ask


# the texts of one run

def bilingual(obj, langs) -> dict:
    """{ko, en} texts of a model object, with runs of white space collapsed; a missing language is empty."""
    obj = obj if isinstance(obj, dict) else {}  # anything else has no text
    return {l: " ".join(str(obj.get(l) or "").split()) for l in langs}


def names_of(obj) -> dict:
    """The name declarations of a model object."""
    n = obj.get("names") if isinstance(obj, dict) else None  # {spelling: source}
    return {str(k): str(v) for k, v in n.items()} if isinstance(n, dict) else {}


def english_words(obj) -> set:
    """Every lowercase English word of a model answer: the words the model itself uses as ordinary words."""
    out = set()  # lowercase words

    def walk(v, key=""):  # every string under an "en" key, at any depth
        if isinstance(v, dict):  # an object: its values, with their keys
            for k, x in v.items():  # each value with its key
                walk(x, k)  # walked with its key
        elif isinstance(v, list):  # a list: its items, under the same key
            for x in v:  # each item
                walk(x, key)  # under the same key
        elif isinstance(v, str) and key == "en":  # English text
            out.update(re.findall(r"(?<![A-Za-z])[a-z][a-z-]{2,}(?![A-Za-z])", v))  # words written in lowercase somewhere
    walk(obj)  # the whole answer
    return out


def sentence_case(text: str, ordinary: set) -> str:
    """An English title in sentence case: a capitalised word after the first goes to lowercase when the run also writes it
    as an ordinary lowercase word ("Unified Observability Rebuild" becomes "Unified Observability rebuild" when 'rebuild'
    is written in lowercase elsewhere in the run and 'observability' never is). Names, acronyms and mixed-case words keep their capitals, so an invented name is still
    caught by the name rule."""
    words = text.split(" ")  # spaces only, so punctuation stays with its word
    for i, w in enumerate(words[1:], 1):  # the first word keeps its capital
        core = w.strip("()[],.:;")  # the word without punctuation around it
        if len(core) > 1 and core[0].isupper() and core[1:].islower() and core.lower() in ordinary:  # Capitalised, and ordinary elsewhere
            words[i] = w.replace(core, core.lower(), 1)  # the ordinary word in lowercase
    return " ".join(words)


def ids_of(obj) -> list:
    """The evidence ids of a model object, once each."""
    if not isinstance(obj, dict):  # a model object without ids
        return []
    return list(dict.fromkeys(str(e).strip() for e in C.as_list(obj.get("ev")) if str(e).strip()))


class Draft:
    """The state of one run: every text in every language, its checks, what was dropped and the calls made."""

    def __init__(self, ctx: Ctx, langs):  # one per run
        self.ctx, self.langs = ctx, tuple(langs)  # the checking context and the languages
        self.texts = []  # every text: {at, kind, lang, text, ev, names, frame, limit, marks, issues, round}
        self.dropped = []  # texts that failed for good
        self.calls = 0  # model calls made

    def add(self, at: str, kind: str, obj: dict, *, limit_key: str | None = None, marks=(0, 0), frame=False, ev=None) -> dict:
        """Register one text in every language and check it. Returns {lang: entry}."""
        R = self.ctx.style["resume"]  # the length limits
        texts, ids, nm = bilingual(obj, self.langs), (ids_of(obj) if ev is None else list(ev)), names_of(obj)  # text, ids, names
        out = {}  # language to entry
        for lang in self.langs:  # each language is checked against the evidence in its own way
            limit = per_lang(R.get(f"{limit_key}_{'words' if lang == 'en' else 'chars'}"), lang, None) if limit_key else None  # the part's limit
            e = {"at": at, "kind": kind, "lang": lang, "text": texts[lang], "ev": list(ids), "names": nm, "frame": frame,  # everything the checks and the record need
                 "limit": limit, "marks": tuple(marks), "round": "draft"}
            e["issues"] = text_issues(e["text"], lang, e["ev"], nm, self.ctx, kind=kind, frame=frame, limit=limit, marks=e["marks"])  # checked as soon as it is written
            self.texts.append(e)  # the record keeps every text
            out[lang] = e  # the caller gets both languages
        return out

    def failing(self) -> list:
        """Texts with fact, style or claim issues that are still in the draft."""
        return [e for e in self.texts if not e.get("gone") and (hard(e["issues"]) or any(i["code"] in CLAIM_CODES for i in e["issues"]))]

    def repair(self, ask) -> None:
        """One call for every failing text; the answers face the same checks."""
        todo = self.failing()  # what needs another try
        if not todo:  # a clean draft needs no call
            return  # nothing to send
        rows, ids = [], []  # request lines; the evidence they may cite
        for e in todo:  # each failing text gets a short id made from its place and words, so a stored answer still fits after a rule change
            e["rid"] = "r" + hashlib.sha1(f"{e['at']}|{e['lang']}|{e['text']}".encode()).hexdigest()[:8]  # the id the request and the answer share
            why = "; ".join(issue_text(i) for i in e["issues"] if i["code"] not in POLISH_CODES)  # the reasons in plain words
            what = KIND_WORDS.get(e["kind"], e["kind"]) + (f" (exactly {e['marks'][1]} ==highlight==)" if e["marks"][0] else  # what the part is
                                                           " (at most one ==highlight==)" if e["marks"][1] else " (no highlight)")
            if e["limit"]:  # the part's length limit, so a rewording does not outgrow it
                what += f" (at most {e['limit']} {'words' if e['lang'] == 'en' else 'characters without spaces'})"  # a rewording must stay within it
            rows.append(f"{e['rid']} | {e['lang']} | {what} | {e['text'] or '(empty)'} | {why} | {', '.join(e['ev']) or '(none)'}")  # id, language, part, text, reasons, ids
            ids += e["ev"]  # the evidence block lists these
        prompt = prompt_text("write_repair", rules=rules_text(self.ctx.style), items="\n".join(rows), evidence=evidence_block(self.ctx, ids))  # the shared rules, the texts and their evidence
        self.calls += 1  # the repair is a model call too
        got = ask("write-repair", prompt, ("parts",))  # {"parts": [{id, text, ev, names}]}
        back = {str(p.get("id")): p for p in C.as_list((got or {}).get("parts")) if isinstance(p, dict)}  # the answers by id
        for e in todo:  # each rewritten text is checked again
            p = back.get(e["rid"])  # its answer
            if not p:  # the model left it out
                continue  # the text stays as it was and fails again
            e["first"] = {"text": e["text"], "issues": e["issues"]}  # what the first round wrote and why it failed, for the record
            e["text"] = " ".join(str(p.get("text") or "").split())  # the new text
            e["ev"] = ids_of(p) or e["ev"]  # new ids, or the old ones
            e["names"] = {**e["names"], **names_of(p)}  # declarations add up
            e["round"] = "repair"  # where it came from, for the record
            e["issues"] = text_issues(e["text"], e["lang"], e["ev"], e["names"], self.ctx, kind=e["kind"], frame=e["frame"],  # the same checks as the first draft
                                      limit=e["limit"], marks=e["marks"])  # the same limits

    def settle(self) -> None:
        """Drop every text that still fails (claims included) and record why."""
        for e in self.failing():  # after the repair round
            e["gone"] = True  # it is not printed
            self.dropped.append({"at": e["at"], "lang": e["lang"], "text": e["text"], "issues": e["issues"], "round": e["round"]})  # the record says what was lost and why

    def ok(self, es: dict) -> bool:
        """Does a text survive in every language? Both editions then say the same thing."""
        return bool(es) and all(not es[l].get("gone") and bool(es[l]["text"]) for l in self.langs)

    def pair(self, es: dict) -> dict | None:
        """{ko, en} of a text that survives in every language, else None."""
        return {l: es[l]["text"] for l in self.langs} if self.ok(es) else None


KIND_WORDS = {"item": "a sentence of a work-history item", "title": "a project title", "short": "a short name or a section title",  # what each kind is, for the repair request
              "desc": "the company line of a role", "headline": "the headline", "intro": "the introduction",
              "card": "an overview card", "row": "a row of a selected-project card", "competency": "a core competency",
              "about": "a sentence of the about me", "motivation": "a sentence of the motivation",
              "deck": "a line of the portfolio deck's opening slides", "stat": "a proof tile's value on the deck's cover", "pathkey": "what a role is known by, on one line of the deck's cover"}  # what each kind is, for the repair request


# the stages

def stage_items(dr: Draft, ask, roles: list, total: int, posting: dict | None) -> tuple[list, dict]:
    """Work-history items and company lines, one call per group of roles. Returns (items, company lines by role key)."""
    ctx, R, U = dr.ctx, dr.ctx.style["resume"], dr.ctx.U["ko"]  # context, options, units
    bounds = shares(roles, total, per_lang(R.get("work_words"), "en", 1200))  # how many items and words each role may take
    groups, cur, size = [], [], 0  # roles grouped so that each prompt stays below a size
    for x in roles:  # in the profile's order
        n = sum(len(U["index"][b]["text"]) for _, pid, _ in x["projects"] for b in U["proj"].get(pid, []))  # the role's evidence text
        if cur and size + n > 45000:  # past the size: a new group
            groups.append(cur)  # the group is full
            cur, size = [], 0  # the next group starts empty
        cur.append(x)  # this role joins the open group
        size += n  # its evidence counts against the size
    if cur:  # the last group
        groups.append(cur)  # a group is only closed by size, so close the last one here
    items, descs = [], {}  # drafted items; company lines
    for g in groups:  # one call per group
        listing = "\n".join(f"{x['key']} | {U['index'].get('role:' + x['key'], {}).get('text', x['key'])} | {x['months']} | "  # one line per role of the group
                            f"{bounds[x['key']][0]} to {bounds[x['key']][1]} items, about {bounds[x['key']][2]} English words in all" for x in g)  # key, head, tenure, the items to choose and their space
        listing += "\nSpace follows tenure: keep each role near its words (fewer, fuller items or more, shorter ones); the job decides which projects."  # the rule the counts come from
        prompt = prompt_text("write_items", target=target_text(posting), rules=rules_text(ctx.style), roles=listing,  # the items template with every placeholder
                             evidence=role_listing(ctx, g) + hierarchy_rows(ctx), title_ko=per_lang(R["title_chars"], "ko", 34),  # every block of the group's roles
                             title_en=per_lang(R["title_words"], "en", 12), ko_style=ko_style(ctx.style),  # the Korean bullet style of the pack
                             hl_ko="{}-{}".format(*per_lang(R["highlight"], "ko", [6, 24])), hl_en="{}-{}".format(*per_lang(R["highlight"], "en", [2, 9])),  # the pack's highlight sizes
                             item_ko=per_lang(R["item_chars"], "ko", 300), item_en=per_lang(R["item_words"], "en", 75))  # the pack's item lengths
        dr.calls += 1  # one call for the group
        got = ask("write-items", prompt, ("roles",))  # {"roles": [{key, desc, items}]}
        ordinary = english_words(got) | set(re.findall(r"(?<![A-Za-z])[a-z][a-z-]{2,}(?![A-Za-z])", target_text(posting)))  # words the answer and the posting use as ordinary words
        keys = {x["key"]: x for x in g}  # the roles of this group
        for r in C.as_list((got or {}).get("roles")):  # the model's roles
            if not isinstance(r, dict) or str(r.get("key")) not in keys:  # unknown roles are ignored
                continue  # skip it
            x = keys[str(r["key"])]  # the role
            pids = {pid for _, pid, _ in x["projects"]}  # its projects
            if isinstance(r.get("desc"), dict) and any(r["desc"].get(l) for l in dr.langs):  # the company line, when written
                descs[x["key"]] = dr.add(f"role.{x['key']}.desc", "desc", r["desc"])  # checked like any sentence
            taken = 0  # items kept for this role
            for it in C.as_list(r.get("items")):  # most important first
                pid = str((it or {}).get("project")) if isinstance(it, dict) else ""  # the item's project id
                if pid not in pids or any(i["project"] == pid for i in items):  # another role's project, an unknown id or a repeat
                    continue  # skip it
                if taken >= bounds[x["key"]][1]:  # over the role's share
                    break  # the rest of the role's items are left out
                taken += 1  # one more item for this role
                own = [i for i in pids]  # ids of this role's projects, for the one-project rule below
                around = [pid] + [u["id"] for u in U["units"] if u["kind"] == "context" and u["id"].startswith(x["key"] + "#c")] \
                    + [u["id"] for u in U["units"] if CITABLE_LOOSE.match(u["id"])]  # a title rests on its project, its role's context and the hierarchy rows (where the client is often named)
                title = {**bilingual(it.get("title"), dr.langs), "names": names_of(it.get("title"))}  # the title in both languages
                short = {**bilingual(it.get("short"), dr.langs), "names": names_of(it.get("short"))}  # the short name
                for t_ in (title, short):  # English names of things in sentence case
                    if t_.get("en"):  # an English name of a thing
                        t_["en"] = sentence_case(t_["en"], ordinary)  # in sentence case
                entry = {"role": x["key"], "project": pid, "rank": taken, "sentences": [],  # the item: its project, rank, title, short name and sentences
                         "title": dr.add(f"project.{pid}.title", "title", title, limit_key="title", ev=around),  # checked against what it rests on
                         "short": dr.add(f"project.{pid}.short", "short", short, ev=around)}
                sents = [s for s in C.as_list(it.get("sentences")) if isinstance(s, dict)]  # the sentences
                sents.sort(key=lambda s: PART_RANK.get(str(s.get("part")), 1))  # scope, decision, result (a stable sort keeps the model's order within a part)
                for k, s in enumerate(sents[:4]):  # at most four sentences
                    ev = [i for i in ids_of(s) if C.project_of(U, i) == pid or (C.project_of(U, i) not in own and not U["index"].get(i, {}).get("pid"))]  # one item, one project: blocks of another project are dropped
                    entry["sentences"].append({"part": str(s.get("part") or "decision"),  # each sentence keeps its part (scope, decision, result)
                                               "entries": dr.add(f"project.{pid}.summary", "item", s, marks=(0, 1), ev=ev)})
                items.append(entry)  # kept for the later stages and the assembly
    return items, descs


def item_view(dr: Draft, items: list) -> list:
    """The surviving items as the later prompts see them: title and sentences in each language with their ids."""
    out = []  # one entry per item
    for it in items:  # each item
        sents = [{"ev": s["entries"][dr.langs[0]]["ev"], **{l: s["entries"][l]["text"] for l in dr.langs}}  # the ids and the text in each language
                 for s in it["sentences"] if dr.ok(s["entries"])]  # sentences that survive in every language
        if sents:  # an item without a sentence says nothing
            out.append({"project": it["project"], "title": {l: it["title"][l]["text"] for l in dr.langs}, "sentences": sents})  # the project, its title and its surviving sentences
    return out


def stage_summary(dr: Draft, ask, items: list, posting: dict | None) -> dict:
    """Headline, introduction, cards and selected-project cards: one call."""
    ctx, R = dr.ctx, dr.ctx.style["resume"]  # context and options
    view = item_view(dr, items)  # what the items say so far
    avoid = list(C.as_list(R.get("avoid_lead")))  # roles not to lead with
    lead_rule = ("- Do not lead the headline or the introduction with these roles: " + ", ".join(avoid) + ".") if avoid else ""  # a pack may keep a role off the top of the resume
    roles = [u["id"] for u in ctx.U["ko"]["units"] if u["kind"] == "role"]  # every role's head, for the introduction and the industries
    prompt = prompt_text("write_summary", target=target_text(posting, overview=True), rules=rules_text(ctx.style), items=items_listing(view),  # the summary template
                         evidence=cited_listing(ctx, view, roles) + "\n" + loose_listing(ctx),  # the items' blocks, every role's head and the loose rows
                         n_highlights=R["highlights"], headline_ko=per_lang(R["headline_chars"], "ko", 48),  # the pack's numbers and lengths
                         headline_en=per_lang(R["headline_words"], "en", 16), intro_ko=per_lang(R["intro_chars"], "ko", 170),  # headline and introduction limits
                         intro_en=per_lang(R["intro_words"], "en", 48), card_ko=per_lang(R["card_chars"], "ko", 70),  # card limits
                         card_en=per_lang(R["card_words"], "en", 20), row_ko=per_lang(R["row_chars"], "ko", 60),  # row limits
                         row_en=per_lang(R["row_words"], "en", 18), lead_rule=lead_rule)  # the lead rule, empty when the pack has none
    dr.calls += 1  # one call
    got = ask("write-summary", prompt, ("headline", "intro", "cards", "highlights")) or {}  # the parts
    out = {"cards": {}, "highlights": []}  # cards by key, selected projects in order
    if isinstance(got.get("headline"), dict):  # the headline
        out["headline"] = dr.add("summary.headline", "headline", got["headline"], limit_key="headline")  # no highlight in the headline
    if isinstance(got.get("intro"), dict):  # the introduction, with one highlight
        out["intro"] = dr.add("summary.intro", "intro", got["intro"], limit_key="intro", marks=(1, 1))  # exactly one highlight in the introduction
    cards = {str(c.get("key")): c for c in C.as_list(got.get("cards")) if isinstance(c, dict)}  # the cards by key
    out["cards"] = {k: dr.add(f"summary.cards.{k}", "target" if k == "target" else "card", cards[k], limit_key="card") for k in CARD_KEYS if k in cards}  # the target card may use the posting's words
    known = set(ctx.U["ko"]["proj"])  # any project of the profile may become a card; its evidence is checked like any text
    ordinary = english_words(got) | english_words({"en": " ".join(s.get("en", "") for it in view for s in it["sentences"])})  # ordinary words of this answer and of the items
    role_of = {pid: x["key"] for x in roles_of(ledger_view(ctx.profile)) for _, pid, _ in x["projects"]}  # each project's role key
    around = {pid: [pid] + [u["id"] for u in ctx.U["ko"]["units"] if (u["kind"] == "context" and u["id"].startswith(role_of[pid] + "#c"))  # a card title rests like an item title
                            or CITABLE_LOOSE.match(u["id"])] for pid in known}  # a card title rests like an item title
    for h in C.as_list(got.get("highlights")):  # each selected-project card
        pid = str(h.get("project")) if isinstance(h, dict) else ""  # the card's project id
        if pid not in known or any(x["project"] == pid for x in out["highlights"]) or len(out["highlights"]) >= R["highlights"]:  # only drafted items, each once, at most the pack's number
            continue  # unknown, repeated, or one too many
        i = len(out["highlights"])  # its position, which keys its texts
        rows = {str(r.get("key")): r for r in C.as_list(h.get("rows")) if isinstance(r, dict)}  # its rows by key
        ht = {**bilingual(h.get("title"), dr.langs), "names": names_of(h.get("title"))}  # the card's title
        if ht.get("en"):  # sentence case, as the item titles
            ht["en"] = sentence_case(ht["en"], ordinary)  # in sentence case
        out["highlights"].append({"project": pid,  # the card's project, title and rows
                                  "title": dr.add(f"summary.highlights.{i}.title", "title", ht, limit_key="title", ev=around.get(pid, [pid])),  # a short title that rests like an item title
                                  "rows": {k: dr.add(f"summary.highlights.{i}.{k}", "row", rows[k], limit_key="row",
                                                     marks=(1, 1) if k == "result" else (0, 0)) for k in ROW_KEYS if k in rows}})  # the result row carries the highlight
    return out


def stage_competencies(dr: Draft, ask, items: list, posting: dict | None) -> list:
    """Core competencies: one call."""
    ctx, R = dr.ctx, dr.ctx.style["resume"]  # context and options
    view = item_view(dr, items)  # what the items say so far
    lo, hi = R["competencies"]  # how many
    prompt = prompt_text("write_competencies", target=target_text(posting), rules=rules_text(ctx.style), items=items_listing(view),  # the competencies template
                         evidence=cited_listing(ctx, view) + "\n" + loose_listing(ctx), min=lo, max=hi, ko_style=ko_style(ctx.style),  # the items' blocks and the loose rows
                         comp_ko=per_lang(R["competency_chars"], "ko", 190), comp_en=per_lang(R["competency_words"], "en", 52))  # the pack's lengths
    dr.calls += 1  # one call
    got = ask("write-competencies", prompt, ("competencies",)) or {}  # {"competencies": [...]}
    out = []  # one entry per competency
    ordinary = english_words(got)  # the answer's ordinary words
    for i, c in enumerate([c for c in C.as_list(got.get("competencies")) if isinstance(c, dict)][:hi]):  # at most the pack's number
        nm = bilingual(c.get("name"), dr.langs)  # the competency's name
        if nm.get("en"):  # sentence case, as the titles
            nm["en"] = sentence_case(nm["en"], ordinary)  # in sentence case
        out.append({"name": dr.add(f"competencies.{i}.name", "short", nm, ev=ids_of(c)),  # its name rests on the same ids as its text
                    "text": dr.add(f"competencies.{i}.text", "competency", c, limit_key="competency")})
    return out


def stage_about(dr: Draft, ask, items: list, posting: dict | None) -> dict:
    """About me and motivation: one call."""
    ctx, R = dr.ctx, dr.ctx.style["resume"]  # context and options
    view = item_view(dr, items)  # what the items say so far
    quote_rule = ('- "quote": one boxed statement of how the person works, two or three sentences in each language, with "title" (two or three words) and "ev".'  # the box is optional
                  if R.get("about_quote") else '- Leave "quote" out.')  # the quote box only when the pack asks for it
    prompt = prompt_text("write_about", target=target_text(posting, overview=True), rules=rules_text(ctx.style), items=items_listing(view),  # the about me template
                         evidence=cited_listing(ctx, view) + "\n" + loose_listing(ctx), n_about=R["about_items"], quote_rule=quote_rule,  # the items' blocks and the loose rows
                         about_ko=per_lang(R["about_chars"], "ko", 420), about_en=per_lang(R["about_words"], "en", 110),  # section limits
                         mot_ko=per_lang(R["motivation_chars"], "ko", 320), mot_en=per_lang(R["motivation_words"], "en", 85))  # motivation limits
    dr.calls += 1  # one call
    got = ask("write-about", prompt, ("about", "motivation")) or {}  # {"about": [...], "quote": {...}, "motivation": [...]}
    about = []  # the sections in order
    for a in [a for a in C.as_list(got.get("about")) if isinstance(a, dict)][:R["about_items"]]:  # at most the pack's number of sections
        i = len(about)  # its position, which keys its texts
        sents = [s for s in C.as_list(a.get("sentences")) if isinstance(s, dict)][:5]  # its sentences
        about.append({"title": dr.add(f"about.{i}.title", "short", {**bilingual(a.get("title"), dr.langs)},  # the section's title and its sentences
                                      ev=list(dict.fromkeys(e for s in sents for e in ids_of(s)))),  # the title rests on what its sentences cite
                      "sentences": [dr.add(f"about.{i}.text", "about", s) for s in sents]})
    quote = None  # the quote box
    q = got.get("quote")  # the boxed statement, when the model wrote one
    if R.get("about_quote") and isinstance(q, dict) and any(q.get(l) for l in dr.langs):  # only when asked for and written
        quote = {"title": dr.add("about.quote.title", "short", {**bilingual(q.get("title"), dr.langs)}, ev=ids_of(q)),  # a title and a text, each checked
                 "text": dr.add("about.quote.text", "about", q)}
    mot = [dr.add("motivation", "motivation", s, frame=bool(s.get("frame")) and not ids_of(s))  # a sentence about the company cites nothing
           for s in [s for s in C.as_list(got.get("motivation")) if isinstance(s, dict)][:4]]  # at most four sentences
    return {"about": about, "quote": quote, "motivation": mot}


def stage_deck(dr: Draft, ask, items: list, posting: dict | None) -> dict:
    """The words of the deck's opening slides: proof tiles and focus columns on the cover, a line over the contents and one over
    the career at a glance. One call: a form of its own, so the other stages' prompts stay as they are."""
    ctx, R = dr.ctx, dr.ctx.style["resume"]  # context and options
    view = item_view(dr, items)  # what the items say so far
    roles = [u["id"] for u in ctx.U["ko"]["units"] if u["kind"] == "role"]  # every role's head, for the contents and the glance
    printed = {it["role"] for it in items}  # the roles with a project on the resume: a career path has a station for these
    prompt = prompt_text("write_deck", target=target_text(posting), rules=rules_text(ctx.style), items=items_listing(view),  # the deck template
                         evidence=cited_listing(ctx, view, roles) + "\n" + loose_listing(ctx), ko_style=ko_style(ctx.style),  # the items' blocks, the role heads and the loose rows
                         stat_ko=per_lang(R["stat_chars"], "ko", 9), stat_en=per_lang(R["stat_words"], "en", 3), stat_en_chars=R["stat_en_chars"],  # a tile's value
                         note_ko=per_lang(R["stat_note_chars"], "ko", 30), note_en=per_lang(R["stat_note_words"], "en", 9),  # the note under it
                         focus_ko=per_lang(R["focus_chars"], "ko", 42), focus_en=per_lang(R["focus_words"], "en", 12),  # a column's line
                         phase_ko=per_lang(R["phase_chars"], "ko", 8), phase_en=per_lang(R["phase_words"], "en", 3),  # a station's kind of work
                         path_ko=per_lang(R["path_chars"], "ko", 26), path_en=per_lang(R["path_words"], "en", 8),  # a station's line
                         key_ko=per_lang(R["path_key_chars"], "ko", 22), key_en=per_lang(R["path_key_words"], "en", 6), key_en_chars=R["path_key_en_chars"],  # and what it is known by
                         focus_head_ko=per_lang(R["focus_head_chars"], "ko", 14), focus_head_en=per_lang(R["focus_head_words"], "en", 3),  # a column's title
                         roles=", ".join(u.split(":", 1)[1] for u in roles if ":" in u and u.split(":", 1)[1] in printed),  # the roles a station can be for
                         card_ko=per_lang(R["card_chars"], "ko", 70), card_en=per_lang(R["card_words"], "en", 20))  # the lines over the overview slides
    dr.calls += 1  # one call
    got = ask("write-deck", prompt, ("stats", "focus")) or {}  # {"stats": [...], "focus": [...], "contents": {...}, "glance": {...}}
    out = {"stats": [], "focus": [], "contents": None, "glance": None, "journey": []}  # what survives
    for key, head in (("stats", "value"), ("focus", "title")):  # the tiles and the columns
        for c in [c for c in C.as_list(got.get(key)) if isinstance(c, dict)][:4]:  # four at most
            i = len(out[key])  # its position, which keys its texts
            head_es = dr.add(f"summary.{key}.{i}.{head}", "stat" if key == "stats" else "short", {**bilingual(c.get(head), dr.langs), "names": names_of(c.get(head))},  # its head rests on its line's ids
                             limit_key="stat" if key == "stats" else "focus_head", ev=ids_of(c))  # a tile's value is short, a column's title takes one line
            out[key].append({"head": head_es, "text": dr.add(f"summary.{key}.{i}.text", "deck", c, limit_key="stat_note" if key == "stats" else "focus")})  # its line
    for key in ("contents", "glance"):  # the two lines over the overview slides
        if isinstance(got.get(key), dict):  # written
            out[key] = dr.add(f"summary.{key}", "deck", got[key], limit_key="card")  # as long as a card
    known = {u.split(":", 1)[1] for u in roles if ":" in u} & printed  # the roles of the profile that print something
    theirs = {x["key"]: {pid for _, pid, _ in x["projects"]} for x in roles_of(ctx.profile)}  # the projects of each role
    for c in [c for c in C.as_list(got.get("journey")) if isinstance(c, dict)]:  # one station per role
        rk = str(c.get("role") or "").strip()  # whose
        if rk not in known or any(x["role"] == rk for x in out["journey"]):  # a made-up role, or a second answer for one
            continue  # left out
        if not any(e == f"role:{rk}" or e.split("#")[0] == rk or e.split("#")[0] in theirs.get(rk, ()) for e in ids_of(c)):  # the facts check reads the cited blocks: another role's would pass for this one
            continue  # a station rests on its own role
        parts = {k: {**bilingual(c.get(k), dr.langs), "names": names_of(c.get(k)), "ev": ids_of(c)} for k in ("phase", "key")}  # the two pairs rest on the station's ids
        out["journey"].append({"role": rk, "phase": dr.add(f"role.{rk}.journey.phase", "short", parts["phase"], limit_key="phase"),  # the kind of work
                               "line": dr.add(f"role.{rk}.journey.line", "deck", c, limit_key="path"),  # what it was
                               "key": dr.add(f"role.{rk}.journey.key", "pathkey", parts["key"], limit_key="path_key")})  # what it is known by
    return out


# assembly

def one_mark(text: str) -> str:
    """Keep the first highlight of a text and drop the marks of any later one (an item has exactly one)."""
    seen = [0]  # highlights met so far

    def sub(m):  # one highlight met
        seen[0] += 1  # count it
        return m.group(0) if seen[0] == 1 else m.group(1)  # later phrases keep their words, not their marks
    return re.sub(r"==(.+?)==", sub, text)


def assemble(profile: dict, dr: Draft, res: dict, overwrite: bool, space: dict | None = None) -> dict:
    """The new profile: the drafted parts as language pairs, the projects the draft did not choose kept off the resume,
    and every surviving sentence with its ids under "evidence"."""
    new = copy.deepcopy(profile)  # never change the input
    L, st = dr.langs, dr.ctx.style  # languages and the style pack
    if not isinstance(new.get("summary"), dict):  # the summary block may be missing
        new["summary"] = {}  # an empty summary block to fill
    S = new["summary"]  # where the top of the resume goes
    links = []  # every surviving sentence: where it stands, its language, its text as printed, its ids and names

    def put(obj, key, value):  # fill a field; what the person wrote stays unless the run tailors to a posting
        if value and (overwrite or not obj.get(key)):  # a value, and a field that is empty or may be replaced
            obj[key] = value  # write it

    def link(at, es, form=False, part=None):  # record the evidence of a text that survives in every language
        if dr.ok(es):  # only texts that survive in every language are linked
            for l in L:  # one link per language
                txt = es[l]["text"].replace("==", "")  # the text without marks, as the check finds it again
                links.append({"at": at, "lang": l, "text": sentence_form(txt, l, st) if form else txt, "ev": es[l]["ev"],  # where, language, text, ids and names
                              "names": es[l]["names"], **({"frame": True} if es[l]["frame"] else {}), **({"part": part} if part else {})})  # an item's sentence says what it is: the deck's cards read it

    if "items" in res:  # work-history items and company lines
        items, descs = res["items"]  # the items and the company lines
        chosen = {}  # project id to its new fields
        used, trimmed = {}, []  # English words each role has used; items left out for space
        for it in items:  # each drafted item
            sents = [s["entries"] for s in it["sentences"] if dr.ok(s["entries"])]  # sentences that survive in every language
            if not sents or not dr.ok(it["title"]):  # nothing to print, or no title
                continue  # skip it
            words = sum(len(s["en"]["text"].split()) for s in sents) if "en" in L else sum(len(s[L[0]]["text"]) for s in sents) // 2  # the item's space
            lo, _hi, budget = (space or {}).get(it["role"], (1, 99, 10 ** 6))  # the role's bounds and words
            kept = sum(1 for c in chosen.values() if c.get("role") == it["role"])  # items of this role so far
            if kept >= lo and used.get(it["role"], 0) + words > budget * 1.15:  # past the role's space: tenure decides how much a role may take
                trimmed.append(it["project"])  # recorded, and the project stays off the resume
                continue  # skip it
            used[it["role"]] = used.get(it["role"], 0) + words  # the role's space grows
            chosen[it["project"]] = {"role": it["role"], "title": dr.pair(it["title"]), "short": dr.pair(it["short"]),  # the new fields of the project
                                     "summary": {l: one_mark(joined([s[l]["text"] for s in sents], l, st)) for l in L}}
            link(f"project.{it['project']}.title", it["title"])  # the title's evidence
            for s in it["sentences"]:  # each sentence
                if dr.ok(s["entries"]):  # that survives
                    link(f"project.{it['project']}.summary", s["entries"], form=True, part=s["part"])  # linked as printed
        res["_trimmed"] = trimmed  # the record says which items gave way
        for ri, r in enumerate(C.as_list(new.get("roles")), 1):  # write into the roles and projects
            rk = role_key(r, ri)  # the role's key
            if rk in descs and dr.ok(descs[rk]):  # the company line
                put(r, "desc", dr.pair(descs[rk]))  # the company line in both languages
                link(f"role.{rk}.desc", descs[rk])  # its evidence
            ps = [p for p in C.as_list(r.get("projects")) if isinstance(p, dict)]  # the role's projects
            ids = {id(p): project_id(p, rk, pi) for pi, p in enumerate(ps, 1)}  # each project's id, computed before any reordering
            for p in ps:  # every project of the role
                pid = ids[id(p)]  # its id
                if pid in chosen:  # a drafted item
                    c = chosen[pid]  # the new fields
                    if "ledger" not in p:  # what the draft replaces is kept, so the evidence ids keep their meaning
                        p["ledger"] = {"title": p.get("title"), "summary": p.get("summary")}  # the ledger's own title and summary
                    p["title"], p["summary"] = c["title"], c["summary"]  # the drafted title and sentences
                    if c["short"]:  # the short name competencies print as their evidence
                        p["short"] = c["short"]  # a short name for the competencies' evidence
                    p.pop("resume", None)  # on the resume
                elif overwrite or not p.get("summary"):  # a project the draft did not choose stays in the profile, off the resume
                    p["resume"] = False  # kept in the profile for the deck and later drafts
            if any(ids[id(p)] in chosen for p in ps):  # chosen items newest first, the others after them
                ps.sort(key=lambda p: (ids[id(p)] not in chosen, -ym(p.get("period"))))  # drafted first, newest first
                r["projects"] = ps  # the new order
    if "summary" in res:  # the top of the resume
        sm = res["summary"]  # the stage's texts
        for key in ("headline", "intro"):  # one text each
            if sm.get(key) and dr.ok(sm[key]):  # survived in every language
                put(S, key, dr.pair(sm[key]))  # the pair goes into the summary
                link(f"summary.{key}", sm[key])  # and its evidence
        cards = [(k, sm["cards"][k]) for k in CARD_KEYS if k in sm["cards"] and dr.ok(sm["cards"][k])]  # surviving cards in print order
        if len(cards) % 2:  # the renderer prints two per row
            cards = cards[:-1]  # the last card goes
        if cards:  # at least two survived
            put(S, "cards", {l: [[LABELS["cards"][l][k], es[l]["text"]] for k, es in cards] for l in L})  # label and text, per language
            for k, es in cards:  # each card's evidence
                link(f"summary.cards.{k}", es)  # keyed by the card
        hl = [h for h in sm["highlights"] if dr.ok(h["title"]) and all(k in h["rows"] and dr.ok(h["rows"][k]) for k in ROW_KEYS)]  # complete cards only
        if hl:  # at least one complete card
            role_of = {pid: x for x in roles_of(profile) for _, pid, _ in x["projects"]}  # project to its role

            def where(pid, l):  # "Nara Cloud  2024 ~ 2025": the role's short name and the project's years
                x = role_of.get(pid)  # the project's role
                if not x:  # a project outside the profile has no place line
                    return ""
                p = next((p for _, q, p in x["projects"] if q == pid), {})  # the project
                years = sorted({int(ym(s)) for s in re.split(r"\s*[~–]\s*|\s+-\s+", str(p.get("period") or "")) if ym(s)})  # the years it spans
                span = "" if not years else str(years[0]) if years[0] == years[-1] else f"{years[0]}{' - ' if l == 'en' else ' ~ '}{years[-1]}"  # one year, or the first and last year
                return role_name(x["role"], l) + ("  " + span if span else "")
            put(S, "highlights", {l: [{"title": h["title"][l]["text"], "where": where(h["project"], l),  # title, place line and rows per language
                                       "rows": [[LABELS["rows"][l][k], h["rows"][k][l]["text"]] for k in ROW_KEYS]} for h in hl] for l in L})
            for i, h in enumerate(hl):  # positions after the incomplete cards are gone
                link(f"summary.highlights.{i}.title", h["title"])  # the card's title
                for k in ROW_KEYS:  # each row
                    link(f"summary.highlights.{i}.{k}", h["rows"][k])  # keyed by position and row
    if "competencies" in res:  # core competencies with the projects they rest on
        U = dr.ctx.U["ko"]  # units, for the project of each cited block
        comps = []  # (competency, its projects)
        for c in res["competencies"]:  # each drafted competency
            if dr.ok(c["name"]) and dr.ok(c["text"]):  # both its name and its text survived
                printed = {project_id(p, role_key(r, ri), pi) for ri, r in enumerate(C.as_list(new.get("roles")), 1)  # the items the resume prints, with their ids after reordering
                           for pi, p in enumerate(C.as_list(r.get("projects")), 1) if isinstance(p, dict) and p.get("resume") is not False and p.get("summary")}  # items the resume prints
                pids = list(dict.fromkeys(C.project_of(U, e) for e in c["text"][L[0]]["ev"] if C.project_of(U, e) in printed))[:3]  # the printed projects it cites: another would print its ledger title
                comps.append((c, pids))  # kept with the projects it names
        if comps:  # at least one survived
            put(new, "competencies", {l: [{"name": c["name"][l]["text"], "text": c["text"][l]["text"], "evidence": pids} for c, pids in comps] for l in L})  # the renderer prints the projects in parentheses
            for i, (c, _) in enumerate(comps):  # each competency's evidence
                link(f"competencies.{i}.name", c["name"])  # its name
                link(f"competencies.{i}.text", c["text"])  # its text
    if "about" in res:  # about me and motivation
        ab = res["about"]  # the stage's texts
        about = {l: [] for l in L}  # the sections in each language
        if ab.get("quote") and dr.ok(ab["quote"]["title"]) and dr.ok(ab["quote"]["text"]):  # the quote box first
            for l in L:  # both languages
                about[l].append({"quote": ab["quote"]["title"][l]["text"], "text": ab["quote"]["text"][l]["text"]})  # the box goes first
            link("about.quote.title", ab["quote"]["title"])  # its title's evidence
            link("about.quote.text", ab["quote"]["text"], form=False)  # its text's evidence
        n = 0  # position among the surviving sections
        for a in ab["about"]:  # each section
            sents = [es for es in a["sentences"] if dr.ok(es)]  # sentences that survive in every language
            if dr.ok(a["title"]) and sents:  # a section needs its title and a sentence
                for l in L:  # both languages
                    about[l].append([a["title"][l]["text"], " ".join(sentence_form(es[l]["text"], l, {"resume": {"ko_ending": "plain"}}) for es in sents)])  # the sentences as one paragraph
                link(f"about.{n}.title", a["title"])  # the title's evidence
                for es in sents:  # each sentence
                    link(f"about.{n}.text", es)  # linked to the section
                n += 1  # the next section's position
        if any(about.values()):  # at least one section survived
            put(new, "about", about)  # both languages
        sents = [es for es in ab["motivation"] if dr.ok(es)]  # surviving motivation sentences
        if sents:  # at least one sentence
            put(new, "motivation", {l: " ".join(sentence_form(es[l]["text"], l, {"resume": {"ko_ending": "plain"}}) for es in sents) for l in L})  # one paragraph per language
            for es in sents:  # each sentence
                link("motivation", es)  # linked to the motivation
    if "deck" in res:  # the deck's opening slides
        dk = res["deck"]  # the stage's texts
        for key in ("stats", "focus"):  # tiles and columns: [head, line] per language
            rows = [c for c in dk[key] if dr.ok(c["head"]) and dr.ok(c["text"])]  # both parts survived
            if len(rows) >= 3:  # the cover lays out three or four; fewer read as a gap
                put(S, key, {l: [[c["head"][l]["text"], c["text"][l]["text"]] for c in rows] for l in L})  # both languages
                for i, c in enumerate(rows):  # each one's evidence
                    link(f"summary.{key}.{i}.{'value' if key == 'stats' else 'title'}", c["head"])  # its head
                    link(f"summary.{key}.{i}.text", c["text"])  # its line
        for key in ("contents", "glance"):  # one line each
            if dk.get(key) and dr.ok(dk[key]):  # survived in every language
                put(S, key, dr.pair(dk[key]))  # both languages
                link(f"summary.{key}", dk[key])  # its evidence
        stations = {c["role"]: c for c in dk.get("journey") or [] if dr.ok(c["phase"]) and dr.ok(c["line"]) and dr.ok(c["key"])}  # the whole stations
        if len(stations) >= 2:  # one station is no path: the cover keeps its timeline
            for ri, r in enumerate(C.as_list(new.get("roles")), 1):  # write into the roles
                c = stations.get(role_key(r, ri))  # this role's
                if c:  # it has one
                    put(r, "journey", {k: dr.pair(c[k]) for k in ("phase", "line", "key")})  # both languages
                    for k in ("phase", "line", "key"):  # each part's evidence
                        link(f"role.{c['role']}.journey.{k}", c[k])  # keyed by its place
    redone = {x["at"] for x in links}  # fields this run wrote
    keep = [x for x in (new.get("evidence") or []) if isinstance(x, dict) and x.get("at") not in redone]  # links of fields an earlier run wrote
    new["evidence"] = keep + links  # every drafted sentence with its ids
    return new


# the whole run

def missing_parts(profile: dict) -> list:
    """The parts a profile lacks: what a run without a posting drafts."""
    S = profile.get("summary") or {}  # the top of the resume
    out = []  # the parts to draft
    if any(not p.get("summary") for x in roles_of(profile) for _, _, p in x["projects"] if p.get("resume") is not False):  # a project without sentences
        out.append("items")  # items first
    if not (S.get("headline") and S.get("cards") and S.get("highlights") and S.get("intro")):  # any part of the top
        out.append("summary")  # the top of the resume
    if not profile.get("competencies"):  # no competencies yet
        out.append("competencies")  # the competencies stage
    if not (profile.get("about") and profile.get("motivation")):  # no about me or no motivation
        out.append("about")  # the about stage writes both
    if not (S.get("stats") and S.get("focus")):  # the deck's cover has no tiles or columns
        out.append("deck")  # the deck stage writes them
    return out


def existing_items(dr: Draft, roles: list) -> list:
    """Items from projects that already have summaries (a profile written by hand), so the later stages have facts to read.
    They are context only: nothing about them is written back."""
    out, U = [], dr.ctx.U["ko"]  # the items, and the units for their blocks
    for x in roles:  # each role
        for _, pid, p in x["projects"]:  # each project
            if p.get("summary") and p.get("resume") is not False:  # a project the resume prints
                entry = lambda f: {l: {"text": C.clean_text(pick(p.get(f), l)), "ev": [pid], "names": {}, "frame": False} for l in dr.langs}  # one text per language with the project as evidence
                out.append({"role": x["key"], "project": pid, "rank": 1, "title": entry("title"), "short": entry("title"),  # an item in the shape the stages read
                            "sentences": [{"part": "decision", "entries": {l: {**entry("summary")[l], "ev": list(U["proj"].get(pid, []))[:6]} for l in dr.langs}}]})
    return out


def draft(profile: dict, *, posting_text: str | None = None, style: dict | None = None, langs=LANGS, parts=None, total: int | None = None,
          backend: str | None = None, ask=None, raw: list | None = None) -> tuple[dict, dict]:
    """Write the parts. Returns (new profile, record). Raises Stopped when the model never answered."""
    style = style or load_style(None)  # the default pack when none is given
    posting = posting_of(posting_text)  # company, role, overview and lines, or None
    ctx = Ctx(profile, style, posting)  # what every text is checked against
    dr = Draft(ctx, langs)  # the run's state
    ask = ask or model_ask(backend, raw)  # the model, a replay or a test stand-in
    wanted = list(parts) if parts else (list(PARTS) if posting else missing_parts(profile))  # a posting redrafts every part
    res, stopped = {}, ""  # stage results; why the model stopped
    roles = roles_of(ledger_view(profile))  # roles and projects as the ledger has them
    try:
        items = []  # no drafted items yet
        if "items" in wanted and roles:  # the work-history items first: the later stages read them
            items, descs = stage_items(dr, ask, roles, total or style["resume"]["items"], posting)  # the work-history items and the company lines
            res["items"] = (items, descs)  # kept for the assembly
        if not items:  # no drafted items: the later stages read the profile's own summaries
            items = existing_items(dr, roles_of(profile))  # the person's own items
        if "summary" in wanted:  # the top of the resume
            res["summary"] = stage_summary(dr, ask, items, posting)  # headline, introduction, cards, selected projects
        if "competencies" in wanted:  # the competencies
            res["competencies"] = stage_competencies(dr, ask, items, posting)  # four to six, with their projects
        if "about" in wanted:  # the about me and the motivation
            res["about"] = stage_about(dr, ask, items, posting)  # one call for both
        if "deck" in wanted:  # the deck's opening slides
            res["deck"] = stage_deck(dr, ask, items, posting)  # one call
        dr.repair(ask)  # one call for everything that failed
    except Stopped as e:  # keep what was written before the model stopped
        stopped = str(e)  # the reason goes into the record
        if not dr.texts:  # nothing at all: the caller says so
            raise  # the caller says nothing was drafted
    dr.settle()  # what still fails is dropped
    space = shares(roles, total or style["resume"]["items"], per_lang(style["resume"].get("work_words"), "en", 1200)) if roles else {}  # each role's bounds and words
    new = assemble(profile, dr, res, overwrite=bool(posting) or bool(parts), space=space)  # the drafted parts, each role trimmed to its space
    new["_draft"] = {"schema": SCHEMA_RECORD, "at": datetime.date.today().isoformat(), "style": style.get("name"),  # when, with which pack, from which profile and posting
                     "from": hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16],
                     "posting": {k: (posting or {}).get(k) for k in ("sha", "company", "role", "overview", "lines")} if posting else None,
                     "langs": list(langs), "parts": wanted}  # how the profile was made; the posting's names are what a check allows in the motivation
    rec = {"schema": SCHEMA_RECORD, "parts": wanted, "langs": list(langs), "calls": dr.calls, "stopped": stopped, "trimmed": res.get("_trimmed", []),  # parts, languages, calls and why it stopped
           "texts": [{k: v for k, v in e.items() if k != "rid"} for e in dr.texts], "dropped": dr.dropped,
           "check": check_profile(new, style)}  # the record: every text, every drop, and the independent check of the result
    return new, rec


# checking a drafted profile

def field_texts(profile: dict, lang: str) -> list:
    """Every drafted field of a profile in one language: [(at, text)]. The keys match the "at" of the evidence list."""
    out = []  # (at, text) pairs
    S = profile.get("summary") or {}  # the top of the resume
    for k in ("headline", "intro"):  # one text each
        v = pick(S.get(k), lang)  # the language side
        if isinstance(v, str) and v.strip():  # only real text
            out.append((f"summary.{k}", v))  # keyed like its link
    cards = pick(S.get("cards"), lang) or []  # [[label, text], ...]
    keys = {v: k for k, v in LABELS["cards"][lang].items()}  # label to key
    for c in cards if isinstance(cards, list) else []:  # each card
        if isinstance(c, list) and len(c) > 1:  # a [label, text] card
            out.append((f"summary.cards.{keys.get(c[0], c[0])}", str(c[1])))  # keyed by the card
    rows = {v: k for k, v in LABELS["rows"][lang].items()}  # row label to key
    hls = pick(S.get("highlights"), lang) or []  # [{title, where, rows}]
    for i, h in enumerate(h for h in (hls if isinstance(hls, list) else []) if isinstance(h, dict)):  # each selected project, by position
        out.append((f"summary.highlights.{i}.title", str(h.get("title") or "")))  # its title
        for r in C.as_list(h.get("rows")):  # each row
            if isinstance(r, list) and len(r) > 1:  # a [label, text] row
                out.append((f"summary.highlights.{i}.{rows.get(r[0], r[0])}", str(r[1])))  # keyed by position and row
    for key, head in (("stats", "value"), ("focus", "title")):  # the deck's tiles and columns: [[head, line], ...]
        for i, c in enumerate(c for c in (pick(S.get(key), lang) or []) if isinstance(c, list) and len(c) > 1):  # each one, by position
            out.append((f"summary.{key}.{i}.{head}", str(c[0])))  # its head
            out.append((f"summary.{key}.{i}.text", str(c[1])))  # its line
    for key in ("contents", "glance"):  # one line each
        v = pick(S.get(key), lang)  # the language side
        if isinstance(v, str) and v.strip():  # only real text
            out.append((f"summary.{key}", v))  # keyed like its link
    for ri, r in enumerate(C.as_list(profile.get("roles")), 1):  # the deck's career path
        j = r.get("journey") if isinstance(r, dict) else None  # this role's station
        for k in ("phase", "line", "key") if isinstance(j, dict) else ():  # its three parts
            v = pick(j.get(k), lang)  # the language side
            if isinstance(v, str) and v.strip():  # only real text
                out.append((f"role.{role_key(r, ri)}.journey.{k}", v))  # keyed like its link
    comps = pick(profile.get("competencies"), lang) or []  # [{name, text, evidence}]
    for i, c in enumerate(c for c in (comps if isinstance(comps, list) else []) if isinstance(c, dict)):  # each competency, by position
        out.append((f"competencies.{i}.name", str(c.get("name") or "")))  # its name
        out.append((f"competencies.{i}.text", str(c.get("text") or "")))  # its text
    about = pick(profile.get("about"), lang) or []  # [[title, text], {quote, text}]
    n = 0  # position among the [title, text] sections
    for a in (about if isinstance(about, list) else []):  # the boxed statement and the sections
        if isinstance(a, dict) and a.get("quote"):  # the quote box
            out.append(("about.quote.title", str(a["quote"])))  # the box's title
            out.append(("about.quote.text", str(a.get("text") or "")))  # the box's text
        elif isinstance(a, list) and a:  # a section
            out.append((f"about.{n}.title", str(a[0])))  # the section's title
            out.append((f"about.{n}.text", " ".join(map(str, C.as_list(a[1]))) if len(a) > 1 else ""))  # its paragraphs as one text
            n += 1  # the next position
    mot = pick(profile.get("motivation"), lang)  # one text or several paragraphs
    if mot:  # a motivation is printed
        out.append(("motivation", " ".join(map(str, C.as_list(mot)))))  # paragraphs joined
    for ri, r in enumerate(C.as_list(profile.get("roles")), 1):  # company lines and items
        rk = role_key(r, ri)  # the role's key
        d = pick(r.get("desc"), lang)  # its company line
        if isinstance(d, str) and d.strip():  # printed
            out.append((f"role.{rk}.desc", d))  # keyed like its link
        for pi, p in enumerate(C.as_list(r.get("projects")), 1):  # each project of the role
            if not isinstance(p, dict) or p.get("resume") is False:  # off the resume
                continue  # skip it
            s = pick(p.get("summary"), lang)  # its sentences in the language
            if isinstance(s, str) and s.strip():  # an item with sentences
                pid = project_id(p, rk, pi)  # its id
                out.append((f"project.{pid}.title", str(pick(p.get("title"), lang) or "")))  # its title
                out.append((f"project.{pid}.summary", s))  # its sentences
    return out


def kind_of(at: str) -> str:
    """The part kind of a field key."""
    if at.startswith("project.") and at.endswith(".summary"):  # an item's sentences
        return "item"
    if at.endswith(".value"):  # a proof tile's value on the deck's cover
        return "stat"
    if ".journey." in at:  # a station of the deck's career path
        return "short" if at.endswith(".phase") else "pathkey" if at.endswith(".key") else "deck"
    if at.endswith((".title", ".name", ".short")):  # names of things
        return "title"
    for prefix, kind in (("summary.headline", "headline"), ("summary.intro", "intro"), ("summary.cards.target", "target"), ("summary.cards", "card"),  # the longest prefix first: the target card before the other cards
                         ("summary.highlights", "row"), ("competencies", "competency"), ("about", "about"),  # the selected projects' rows, competencies, about me
                         ("motivation", "motivation"), ("role.", "desc"), ("summary.stats", "deck"), ("summary.focus", "deck"),  # the motivation, the company lines
                         ("summary.contents", "deck"), ("summary.glance", "deck")):  # and the deck's opening slides
        if at.startswith(prefix):  # the first prefix that fits
            return kind
    return "item"


def parts_present(profile: dict, lang: str) -> dict:
    """Which resume parts a profile has in a language: what the renderer would print."""
    S = profile.get("summary") or {}  # the top of the resume
    projects = [p for r in C.as_list(profile.get("roles")) for p in C.as_list(r.get("projects")) if isinstance(p, dict) and p.get("resume") is not False]  # the projects the resume prints
    return {"headline": bool(pick(S.get("headline"), lang)), "intro": bool(pick(S.get("intro"), lang)),
            "cards": len(pick(S.get("cards"), lang) or []), "highlights": len(pick(S.get("highlights"), lang) or []),
            "competencies": len(pick(profile.get("competencies"), lang) or []),
            "items": sum(1 for p in projects if pick(p.get("summary"), lang)), "titles_only": sum(1 for p in projects if not pick(p.get("summary"), lang)),
            "about": len(pick(profile.get("about"), lang) or []), "motivation": bool(pick(profile.get("motivation"), lang)),
            "role_desc": sum(1 for r in C.as_list(profile.get("roles")) if pick(r.get("desc"), lang))}


def check_profile(profile: dict, style: dict | None = None) -> dict:
    """Hold every drafted field against its evidence. Each linked sentence is checked again; any text of a field that its
    sentences do not cover is reported (edited after drafting, or never linked). Returns counts and the flagged items."""
    style = style or load_style(None)  # the default pack when none is given
    ctx = Ctx(profile, style, (profile.get("_draft") or {}).get("posting"))  # ledger_view() inside: ids keep their meaning; the posting the draft was made for
    links = [x for x in profile.get("evidence") or [] if isinstance(x, dict)]  # every drafted sentence
    langs = [l for l in LANGS if any(x.get("lang") == l for x in links)] or ["ko"]  # the languages that were drafted
    out = {"sentences": 0, "fields": 0, "facts": [], "style": [], "claims": [], "polish": [], "unlinked": [], "parts": {}}  # counts and the flagged texts by level
    R = style["resume"]  # the resume options
    for lang in langs:  # each drafted language
        fields = field_texts(profile, lang)  # what the renderer prints
        out["fields"] += len(fields)  # how many fields were looked at
        for at, text in fields:  # each field
            mine = [x for x in links if x.get("at") == at and x.get("lang") == lang]  # the sentences linked to this field
            kind = kind_of(at)  # what the field is
            rest = C.flat(text.replace("==", ""))  # the field's text, to see what the sentences cover
            for x in mine:  # each sentence linked to the field
                out["sentences"] += 1  # counted
                iss = text_issues(x["text"], lang, x.get("ev") or [], x.get("names") or {}, ctx, kind=kind, frame=bool(x.get("frame")), marks=(0, 9))  # the same checks as at drafting time
                rec = {"at": at, "lang": lang, "text": x["text"][:120]}  # where the problem is
                for key, codes in (("facts", FACT_CODES), ("style", STYLE_CODES), ("claims", CLAIM_CODES), ("polish", POLISH_CODES)):  # sorted by level
                    got = [i for i in iss if i["code"] in codes]  # this level's issues
                    if got:  # this level has issues
                        out[key].append({**rec, "issues": got})  # recorded with its place
                rest = rest.replace(C.flat(x["text"]), "", 1)  # what this sentence covers
            if len(re.sub(r"[.,·:;()\-=]", "", rest)) > 6:  # text that no linked sentence covers
                out["unlinked"].append({"at": at, "lang": lang, "text": text[:120], "issues": [issue("edited" if mine else "unlinked", detail=text[:60])]})  # edited after drafting, or never linked
            n = len(re.findall(r"==(.+?)==", text))  # highlights of the whole field
            if kind in ("item", "intro") or at.endswith(".result"):  # these fields take exactly one
                if n != 1:  # not exactly one
                    out["polish"].append({"at": at, "lang": lang, "text": text[:120], "issues": [issue("highlight", detail=f"{n} (wanted 1)")]})  # worth a look, not a failure
            elif n:  # the others take none
                out["style"].append({"at": at, "lang": lang, "text": text[:120], "issues": [issue("highlight", detail=f"{n} (wanted 0)")]})  # a highlight where none belongs prints oddly
            if kind == "item":  # an item's length as a whole
                lim = per_lang(R["item_words"] if lang == "en" else R["item_chars"], lang, None)  # the item limit of the pack
                if lim and length_of(text, lang) > lim:  # over it
                    out["polish"].append({"at": at, "lang": lang, "text": text[:120], "issues": [issue("too_long", detail=f"{length_of(text, lang)} > {lim}")]})  # worth a look, not a failure
            if at.startswith("project.") and at.endswith(".title") and per_lang(R["title_end"], lang, []):  # titles end with a work noun
                if not text.rstrip().lower().endswith(tuple(w.lower() for w in per_lang(R["title_end"], lang, []))):  # the title ends with no work noun of the pack
                    out["polish"].append({"at": at, "lang": lang, "text": text[:120], "issues": [issue("title_end", detail=text[-12:])]})  # worth a look
        out["parts"][lang] = parts_present(profile, lang)  # what the renderer would print
    out["ok"] = not (out["facts"] or out["style"] or out["unlinked"])  # claims and polish are counted, not failed
    return out


def print_check(res: dict, out=None) -> None:
    """The check as text, with the verdict on the last line."""
    out = out or sys.stdout  # the terminal unless the caller gives a stream
    print(t("check_head", n=res["sentences"], fields=res["fields"]), file=out)  # the header
    for lang, p in res["parts"].items():  # the parts per language
        print(t("check_line", mark="info", name=t("c_parts") + f" ({lang})", detail=", ".join(f"{k} {v}" for k, v in p.items())), file=out)  # the parts in one line
    for key, name in (("facts", "c_facts"), ("style", "c_style"), ("unlinked", "c_linked"), ("claims", "c_claims"), ("polish", "c_polish")):  # each level
        items = res[key]  # the flagged texts of this level
        mark = "ok  " if not items else ("FAIL" if key in ("facts", "style", "unlinked") else "note")  # facts, style and unlinked texts fail; claims and polish are notes
        print(t("check_line", mark=mark, name=t(name), detail=str(len(items))), file=out)  # the level and its count
        for it in items[:8]:  # at most eight per level keep the output short
            print(f"         - {it['at']} [{it['lang']}] {'; '.join(issue_text(i) for i in it['issues'])[:200]} | {it['text'][:90]}", file=out)  # where, why and the text
    if res["ok"]:  # the verdict is the last line
        print(t("check_pass", sent=res["sentences"], claims=len(res["claims"]), polish=len(res["polish"])), file=out)  # the verdict
    else:
        print(t("check_fail", facts=len(res["facts"]), style=len(res["style"]), claims=len(res["claims"]), unlinked=len(res["unlinked"])), file=out)  # the verdict


# command line

def read_json(path) -> dict:
    """A JSON file, or a clear stop."""
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # missing or not JSON
        raise SystemExit(f"not a readable JSON file: {path}")  # say which file


def write_json(path, data) -> None:
    """UTF-8, indented, a newline at the end."""
    p = pathlib.Path(path)  # the target
    p.parent.mkdir(parents=True, exist_ok=True)  # the folder may not exist yet
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # readable diffs


def hints_for(path: pathlib.Path) -> list:
    """Folders above a file where a workspace style pack may live."""
    return [str(p) for p in list(path.resolve().parents)[:4]]


class SavedList(list):
    """A list of the model's answers that writes itself to a file after every answer, so a run that stops or fails part
    way keeps what the model already wrote (a replay then costs no call)."""

    def __init__(self, path):  # the file the answers go to
        super().__init__()  # an ordinary empty list
        self.path = path  # where the answers go

    def append(self, item):  # the list's own append, plus a save
        super().append(item)  # keep the answer
        write_json(self.path, {"schema": SCHEMA_RECORD, "answers": list(self)})  # and save every answer so far


def cmd_write(a) -> int:
    """write: reads a profile (and a posting), writes a new profile beside it and the record."""
    src = pathlib.Path(a.profile)  # the input
    prof = read_json(src)  # never changed
    style = load_style(a.style, hints_for(src))  # a workspace pack is found above the profile
    posting = pathlib.Path(a.job).read_text(encoding="utf-8") if a.job else None  # the posting, when given
    raw = SavedList(a.raw) if a.raw else None  # the model's answers, saved after each one when asked to keep them
    ask = replay_ask(read_json(a.replay).get("answers", [])) if a.replay else None  # stored answers instead of the model
    langs = tuple(x for x in (a.langs or "ko,en").split(",") if x in LANGS) or LANGS  # the languages to write
    parts = [x for x in a.parts.split(",") if x in PARTS] if a.parts else None  # the parts to write
    try:
        new, rec = draft(prof, posting_text=posting, style=style, langs=langs, parts=parts, total=a.items, backend=a.backend, ask=ask, raw=raw)  # every stage, the repair and the check
    except Stopped as e:  # nothing came back
        print(t("stopped", why=str(e)[:200]))  # nothing was written
        return 2
    out = pathlib.Path(a.out) if a.out else src.with_name(f"{src.stem}.draft.json")  # beside the input, never over it
    write_json(out, new)  # the new profile
    recp = pathlib.Path(a.record) if a.record else ROOT / "output" / "_draft" / f"{src.stem}.write.json"  # the record's default place
    write_json(recp, rec)  # every text, every drop, the check
    if a.raw and not raw:  # no answer came back: an empty file says so
        write_json(a.raw, {"schema": SCHEMA_RECORD, "answers": []})  # the file exists either way
    kept = sum(1 for e in rec["texts"] if not e.get("gone"))  # texts that survived
    print(t("done", parts=", ".join(rec["parts"]) or "-", langs=", ".join(langs), kept=kept, dropped=len(rec["dropped"]), calls=rec["calls"], out=out, rec=recp))  # the summary line
    for d in rec["dropped"][:10]:  # the first drops, with their reasons
        print(t("drop", at=d["at"], lang=d["lang"], why="; ".join(issue_text(i) for i in d["issues"])[:160]))  # the reasons in plain words
    if rec["stopped"]:  # the model stopped part way
        print(t("stopped_mid", why=rec["stopped"][:160]))  # say so
    print_check(rec["check"])  # the independent check; its last line is the verdict
    return 2 if rec["stopped"] else (0 if rec["check"]["ok"] else 1)


def cmd_check(a) -> int:
    """check: a drafted profile against its evidence."""
    src = pathlib.Path(a.profile)  # the drafted profile
    res = check_profile(read_json(src), load_style(a.style, hints_for(src)))  # a workspace pack is found above the profile
    if a.json:  # for the panel and scripts
        write_json(a.json, res)  # the panel and scripts read this
    print_check(res)  # the verdict is the last line
    return 0 if res["ok"] else 1


def main(argv=None) -> int:
    """Entry point: builds the parser, runs the command, returns its exit code."""
    ap = argparse.ArgumentParser(prog="write_resume.py", description="Draft every resume part from the evidence, and check a drafted profile.")  # prog is fixed, so help shows no path
    sub = ap.add_subparsers(dest="cmd", required=True)  # a bare call prints usage
    w = sub.add_parser("write", help="draft the resume parts")  # drafting
    w.add_argument("profile")  # the profile to draft from
    w.add_argument("--job", help="a job posting (Markdown or text) to write for")  # the posting
    w.add_argument("--style", help="style pack name or path")  # the style pack
    w.add_argument("--langs", help="ko,en (default both)")  # the languages
    w.add_argument("--parts", help="items,summary,competencies,about (default: all with --job, else what is missing)")  # the parts
    w.add_argument("--items", type=int, help="work-history items in all (default from the style pack)")  # the item budget
    w.add_argument("--backend", help="model backend (default: OFFEROWL_LLM or the default order)")  # the backend
    w.add_argument("-o", "--out", help="the new profile (default <profile>.draft.json)")  # where the new profile goes
    w.add_argument("--record", help="the draft record (default output/_draft/<profile>.write.json)")  # where the record goes
    w.add_argument("--raw", help="keep the model's answers here, for audit and replay")  # the answers, for replay
    w.add_argument("--replay", help="use stored answers instead of the model")  # a replay instead of the model
    c = sub.add_parser("check", help="check a drafted profile against its evidence")  # checking a drafted profile
    c.add_argument("profile")  # the drafted profile
    c.add_argument("--style")  # the style pack
    c.add_argument("--json")  # the result as JSON
    a = ap.parse_args(argv)  # None reads sys.argv; tests pass a list
    return cmd_write(a) if a.cmd == "write" else cmd_check(a)


if __name__ == "__main__":  # run as a script, not on import
    sys.exit(main())  # the exit code reaches the shell
