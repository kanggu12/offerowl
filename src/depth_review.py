#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The depth review: does each printed project item (resume) and each page of the deck show the engineering? (docs/WRITING.md)

The fact checks hold every sentence to its evidence: nothing is claimed that the evidence does not say. They cannot see a
sentence that is true and thin: "operated the payment platform" passes every check and says nothing a hiring engineer can
weigh. This step reads each unit as such a reader would and says what it leaves out:

  depth_scope         what the person was responsible for, and the situation
  depth_hard          what made the work hard: a constraint, the scale, a failure and its cost, requirements that pulled
                      against each other, what did not work first
  depth_decision      what the person decided, and the alternative set aside
  depth_mechanism     why the result came about, in technical terms
  depth_names         general words where the evidence names the systems, tools, clients and places
  depth_routine       routine work written as an achievement
  depth_circumstance  a circumstance written as an achievement (the only or first developer, alone, a team's size, a join date)
  depth_thinner       the unit lost a difficulty, a mechanism or names that the copy that went out printed

Every finding offers one way on: a rewrite that cites the unit's evidence (the evidence holds more than the words say; it
passes the draft's own checks, src/write_resume.py text_issues, or it is not offered), or a question for the person (the
evidence does not hold it: "What made this hard? What failed first? Why did it work?"). An answer becomes evidence through
the fact flow (apps/api/depth.py). Findings are notes: an agent's judgment never stops an export by itself.

Each unit the agent reads gets a verdict on the three core parts: what made the work hard, the decision with the alternative
it beat, and why the result came about. The agent copies the printed words that state each part; a part counts as stated
only when those words are found in the unit (said_in), and for what made the work hard only when they do not just name where
the work began (is_situation: "scattered metadata" or "a closed network" alone is a starting situation, not a difficulty).
So the verdict follows a rule the code applies, not a word the model picks (verdict_of): all three stated is strong, one
missing is adequate, two or three missing is thin. A strong unit keeps
no finding of the agent's but names and routine; a stated part takes no finding; a missing part always has one (the agent's,
else its own question). Thin units are listed first, and their missing parts are the procedure's gate: each is fixed from
the evidence or answered by the person (apps/mcp/skills/offerowl-application/SKILL.md); the rest are suggestions.

Two checks need no agent and run always: circumstance claims (patterns in both languages) and the names, tools and
organisations the copy that went out printed and the unit lost. The rest is asked of the AI backend, in batches.

  python3 src/depth_review.py review <profile.json> [--lang ko|en] [--style pack] [--deck deck.pdf] [--against old.json]
        [--backend name] [--max-calls N] [-o out.json] [--raw answers.json] [--replay answers.json]
  python3 src/depth_review.py show <review.json>

The input profile is never changed. The panel, the API, the command line `offerowl depth` and the MCP server run the same
review (apps/api/depth.py).
"""
from __future__ import annotations  # `str | None` hints on older Python versions

import argparse  # the command line
import datetime  # when a review was made
import hashlib  # stable ids of units and findings
import json  # every file is JSON
import math  # how rare a word of a title is
import os  # the language of messages
import pathlib  # paths
import re  # the patterns and the sentence cut
import sys  # exit codes and the import path

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # the engine's flat modules, however this file was started
import cover as C  # evidence units, word matching, the plain-text helpers
import factcheck as F  # Latin words and organisation names, for what a unit lost
import llm  # the one door to a model
import write_resume as W  # the ledger view, the ids, the draft's own checks and its shared rules

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
SCHEMA = "offerowl-depth/0.1"  # the review's own file
LANGS = ("ko", "en")  # the languages a review is made in
CODES = ("depth_scope", "depth_hard", "depth_decision", "depth_mechanism", "depth_names", "depth_routine", "depth_circumstance", "depth_thinner")  # every finding's code, in the order a reader weighs them
SHORT = {c[len("depth_"):]: c for c in CODES}  # the model answers with the short word ("hard"); the record keeps the code
CORE = ("hard", "decision", "mechanism")  # the three parts a verdict weighs: what made it hard, the choice and what it beat, why it worked
CORE_CODES = {"depth_" + p for p in CORE}  # their findings' codes: on a thin unit, the gate
VERDICTS = ("thin", "adequate", "strong")  # a unit's verdict, the weakest first
RANK = {"thin": 0, "adequate": 1, None: 2, "strong": 3}  # the order units are listed in: the gate, the suggestions, the units with no verdict, then the strong
STRONG_KEEPS = {"depth_names", "depth_routine"}  # the agent's only notes on a strong unit: a general word where the evidence names the system, routine work dressed up
WAYS = ("rewrite", "ask")  # the two ways on from a finding
STATES = ("open", "applied", "answered", "left")  # what became of a finding: still to do, rewrite used, answered, left as it is
BATCH_CHARS = 36_000  # the units of one call, in characters: big enough for a career's items, small enough to stay sharp
POOL_CHARS = 2_800  # the evidence one unit shows the model: its best blocks, not its whole ledger
PAGE_CHARS = 1_600  # the words of one deck page the model reads: a dense slide holds about this many
MIN_PAGE = 160  # a page with fewer letters of words is a cover, a divider or an end page: nothing to review
HEAD_CHARS = 240  # a page's title area: its first lines with words, where the section label, the project's number and its title stand
PAIR_FLOOR = 0.6  # the share of a project's title (its rare words weighing more) a page's title area must hold to be paired with it
PAIR_MARGIN = 0.15  # how far the best project must stand ahead of the next: closer, the page names two and stays unpaired
MAX_CALLS = 8  # calls one review may take unless the caller or OFFEROWL_DEPTH_CALLS says otherwise
SYSTEM = ("You review resume items and portfolio pages for the depth a senior engineer's documents need. Judge only from the "  # what every call is
          "printed words and the evidence given. A rewrite uses only facts its cited evidence states, and never makes the person's "
          "part larger than the evidence does. Never invent a difficulty, a reason, an alternative or a mechanism. Return only JSON.")

MSG = {  # what this step says, in both languages with the same keys
    "en": {
        "head": "depth review ({lang}): {units} units ({items} items, {slides} deck pages), {findings} findings: {rewrites} rewrites, {questions} questions; {calls} model calls",
        "no_agent": "  no AI backend: only the checks that need none ran (circumstances, what the copy that went out printed)",
        "unreviewed": "  {n} units were not read by the agent",
        "unreviewed_limit": "  {n} units were not read by the agent: the call limit ({calls}) was reached",
        "unanswered": "  {n} of them were in a batch the agent answered, but its answer left them out",
        "stopped": "  the AI backend stopped part way: {why}",
        "no_deck": "  the deck was not read: no deck PDF was given",
        "no_baseline": "  no copy went out yet: nothing to compare with",
        "verdicts": "  verdicts: {thin} thin (fill these first), {adequate} adequate, {strong} strong{unrated}",
        "unrated_n": ", {n} with no verdict",
        "unit": "- {mark}{title} [{where}]{parts}",
        "mark_thin": "[thin] ",
        "mark_adequate": "[adequate] ",
        "mark_strong": "[strong] ",
        "parts": ": not said: {parts}",
        "p_hard": "what made it hard",
        "p_decision": "the decision and its alternative",
        "p_mechanism": "why it worked",
        "finding": "    {code} ({way}{gate}): {missing}",
        "gate_mark": ", fill first",
        "rewrite": "      rewrite: {text}  <- {ev}",
        "question": "      question: {question}",
        "clean": "    (nothing missing)",
        # what a missing core part says when the agent rated it missing and gave no finding of its own
        "m_hard": "The words do not say what made the work hard.",
        "m_decision": "The words do not say what was decided, and what was set aside.",
        "m_mechanism": "The words do not say why the result came about.",
        # the questions a rule-based finding asks, and the ones a finding falls back to when its rewrite failed a check
        "q_scope": "What were you responsible for there, and what was the situation?",
        "q_hard": "What made this hard: a constraint, the scale, a failure, or something that did not work first?",
        "q_decision": "What did you decide there, and what did you set aside?",
        "q_mechanism": "Why did it work? What in the design made the result happen?",
        "q_names": "Which systems, tools or clients was this about?",
        "q_routine": "What came of this work beyond keeping it running?",
        "q_circumstance": "What did you build or decide there? Write the work instead of the circumstance ('{quote}').",
        "q_circumstance_plain": "What did you build or decide there? Write the work instead of the circumstance.",
        "q_thinner": "The copy that went out named {lost}. Do they still hold? Bring them back if they do.",
        "m_circumstance": "It states a circumstance ('{quote}') where the work should be.",
        "m_thinner": "The copy that went out named {lost}, which these words no longer say.",
    },
    "ko": {
        "head": "깊이 검토({lang}): 단위 {units}개(이력서 항목 {items}, 덱 쪽 {slides}), 찾은 것 {findings}개: 고쳐 쓴 문장 {rewrites}, 질문 {questions}; 모델 호출 {calls}번",
        "no_agent": "  AI 백엔드 없음: 모델이 필요 없는 검사만 돌았다(상황 서술, 나간 사본과의 대조)",
        "unreviewed": "  {n}개 단위는 에이전트가 읽지 못했다",
        "unreviewed_limit": "  {n}개 단위는 에이전트가 읽지 못했다: 호출 한도({calls})에 닿았다",
        "unanswered": "  그 가운데 {n}개는 에이전트가 답한 묶음에 있었지만 답에서 빠졌다",
        "stopped": "  AI 백엔드가 중간에 멈췄다: {why}",
        "no_deck": "  덱은 읽지 않았다: 덱 PDF가 없다",
        "no_baseline": "  아직 나간 사본이 없다: 견줄 것이 없다",
        "verdicts": "  판정: 빈약 {thin}(먼저 채울 것), 무난 {adequate}, 충실 {strong}{unrated}",
        "unrated_n": ", 판정 없음 {n}",
        "unit": "- {mark}{title} [{where}]{parts}",
        "mark_thin": "[빈약] ",
        "mark_adequate": "[무난] ",
        "mark_strong": "[충실] ",
        "parts": ": 빠진 것 {parts}",
        "p_hard": "어려웠던 점",
        "p_decision": "결정과 대안",
        "p_mechanism": "효과가 난 까닭",
        "finding": "    {code} ({way}{gate}): {missing}",
        "gate_mark": ", 먼저 채울 것",
        "rewrite": "      고쳐 쓴 문장: {text}  <- {ev}",
        "question": "      질문: {question}",
        "clean": "    (빠진 것 없음)",
        "m_hard": "무엇이 어려웠는지 쓰여 있지 않다.",
        "m_decision": "무엇을 정했고 무엇을 택하지 않았는지 쓰여 있지 않다.",
        "m_mechanism": "왜 그 결과가 났는지 쓰여 있지 않다.",
        "q_scope": "그 일에서 맡은 범위와 상황은 무엇이었나요?",
        "q_hard": "무엇이 어려웠나요? 제약, 규모, 실패, 처음에 안 된 방법 가운데 무엇이었나요?",
        "q_decision": "그때 무엇을 정했고, 무엇을 택하지 않았나요?",
        "q_mechanism": "왜 효과가 났나요? 설계의 어떤 점이 그 결과를 만들었나요?",
        "q_names": "어떤 시스템, 도구, 고객사에 대한 일이었나요?",
        "q_routine": "유지하는 일 말고 그 일로 무엇이 달라졌나요?",
        "q_circumstance": "거기서 무엇을 만들거나 정했나요? 상황('{quote}') 대신 한 일을 씁니다.",
        "q_circumstance_plain": "거기서 무엇을 만들거나 정했나요? 상황 대신 한 일을 씁니다.",
        "q_thinner": "나간 사본에는 {lost}가 있었습니다. 아직 맞다면 되살립니다.",
        "m_circumstance": "한 일 자리에 상황('{quote}')을 썼다.",
        "m_thinner": "나간 사본에 있던 {lost}가 이 글에는 없다.",
    },
}


def call_limit() -> int:
    """The calls one review may take: OFFEROWL_DEPTH_CALLS when it is a whole number of zero or more, else MAX_CALLS."""
    v = str(os.environ.get("OFFEROWL_DEPTH_CALLS") or "").strip()  # the person's setting, if any
    return int(v) if v.isdigit() else MAX_CALLS  # a word or a negative number is no limit: the default stands


def ui_lang() -> str:
    """Language of the messages: OFFEROWL_LANG, else the locale, else English."""
    v = (os.environ.get("OFFEROWL_LANG") or os.environ.get("LANG") or "en").lower()  # the panel sets OFFEROWL_LANG
    return "ko" if v.startswith("ko") else "en"  # only two languages exist


class Blank(dict):
    """Placeholders a message names and the caller did not give stay empty, never an error: a finding the agent gave without
    its quote still gets its question."""

    def __missing__(self, key):  # an absent value
        return ""


def t(key: str, in_lang: str | None = None, **kw) -> str:
    """One message in a language (the person's unless given), English when a Korean entry is missing."""
    table = MSG[in_lang or ui_lang()]  # a finding's own words follow the document, the lines on screen the person
    return (table.get(key) or MSG["en"][key]).format_map(Blank(kw))  # fall back to English, then fill the placeholders


# ---------------------------------------------------------------- sentences, as the canvas cuts them

def sentences(text: str) -> list[str]:
    """A paragraph cut into sentences exactly as the canvas cuts it (apps/api/evidence.py sentences): after a full stop, a
    question or an exclamation mark followed by a space, never inside a ==highlight==, never inside "3.5". A rewrite names the
    sentence it replaces by its words, and the canvas finds it again by the same cut."""
    text = str(text or "").strip()  # plain text
    out, buf, inside, i = [], "", False, 0  # the sentences, the one being read, inside ==...==, the position
    while i < len(text):  # one character at a time (a mark is two)
        if text.startswith("==", i):  # a highlight mark opens or closes
            inside = not inside  # the state flips
            buf += "=="  # the mark stays in the sentence
            i += 2  # past the mark
            continue  # the next character
        ch = text[i]  # this character
        buf += ch  # kept
        if ch in ".!?" and not inside and (i + 1 == len(text) or text[i + 1] == " ") and not re.match(r"\s?\d", text[i + 1:i + 3]):  # a sentence end, not "3.5"
            out.append(buf.strip())  # one sentence
            buf = ""  # the next one starts
        i += 1  # on
    if buf.strip():  # the rest
        out.append(buf.strip())  # the last sentence
    return [s for s in out if s]  # no empty ones


def plain(text) -> str:
    """A sentence's words for comparing: no marks, one space, no end mark (the canvas compares sentences so: drafts.plain)."""
    return re.sub(r"\s+", " ", str(text or "").replace("==", "")).strip().rstrip(".").strip()  # the same text however it was joined


def short_hash(*parts) -> str:
    """A short stable id from some texts: the same unit and code keep their id from one review to the next."""
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]  # ten hex digits never collide in one profile


# ---------------------------------------------------------------- the units: printed items and deck pages

def role_head(r: dict, lang: str) -> str:
    """A role's short name in a language, for the line that says where a unit belongs."""
    return W.role_name(r, lang)  # the draft's own rule: the short name, else the name, else the key


def items_of(profile: dict, lang: str) -> list:
    """The project items the resume prints in this language, in print order: those on the resume (not `resume: false`),
    written for this language or for both (`lang`), with words of their own. A project with a title alone prints no
    sentences and has nothing to weigh."""
    out = []  # one unit per item
    for ri, r in enumerate(C.as_list(profile.get("roles")), 1):  # numbered from 1, as the draft numbers them
        if not isinstance(r, dict):  # a broken entry is skipped by every reader
            continue  # nothing printed
        rk = W.role_key(r, ri)  # the role's key: its context blocks start with it
        for pi, p in enumerate(C.as_list(r.get("projects")), 1):  # each project of the role
            if not isinstance(p, dict) or p.get("resume") is False:  # off the resume
                continue  # not printed
            if p.get("lang") and p.get("lang") != lang:  # an item written for the other language prints only there
                continue  # not in this edition
            text = W.pick(p.get("summary"), lang)  # the words the item prints
            if not isinstance(text, str) or not text.strip():  # a title alone
                continue  # nothing to weigh
            pid = W.project_id(p, rk, pi)  # the id the evidence uses
            period = C.clean_text(W.pick(p.get("period"), lang))  # when, for the line that says where it belongs
            out.append({"id": f"item:{pid}", "kind": "item", "pid": pid, "role": rk, "title": C.clean_text(W.pick(p.get("title"), lang)),  # the unit
                        "where": " | ".join(x for x in (role_head(r, lang), period) if x), "text": C.clean_text(text) if "==" not in text else " ".join(text.split()),  # its words as printed, marks kept
                        "sentences": sentences(" ".join(text.split()))})  # cut as the canvas cuts them
    return out


def pages_of(pdf: str | pathlib.Path) -> list[str]:
    """The words of each page of a deck PDF, one string per page, its lines kept (src/pdftools.py: poppler or PDFium): the first
    lines hold the page's title, which pairs the page with its project."""
    import pdftools as P  # the PDF's text, read only when a deck is given
    n = P.info(str(pdf)).get("pages") or 0  # how many pages
    return ["\n".join(" ".join(line.split()) for line in P.text(str(pdf), first=k, last=k).splitlines() if line.strip())  # each line on one line, the lines kept
            for k in range(1, int(n) + 1)]


def slides_of(pages: list, lang: str) -> list:
    """The deck's pages as units: each page whose words are long enough to describe work (a cover, a divider or an end page
    holds a few words and is left out)."""
    out = []  # one unit per page worth reading
    for n, page in enumerate(pages or [], 1):  # numbered from 1, as a reader numbers pages
        lines = [" ".join(line.split()) for line in str(page or "").splitlines() if line.strip()]  # its lines, each on one line
        words = " ".join(lines)  # its words on one line
        if len(re.sub(r"\s", "", words)) < MIN_PAGE:  # a cover, a divider, an end page
            continue  # nothing to weigh
        head = ""  # the title area: the first lines that hold words (a section label, the company, the project's number, its title)
        for line in lines:  # in reading order
            if re.search(r"[A-Za-z가-힣]{2,}", line):  # a page number or a date is no title
                head = f"{head} {line}".strip()
            if len(head) >= HEAD_CHARS:  # enough to hold a title and a subtitle
                break
        out.append({"id": f"slide:{n}", "kind": "slide", "page": n, "title": words[:80], "where": f"p.{n}", "text": words[:PAGE_CHARS],  # its words, bounded
                    "head": head[:HEAD_CHARS], "sentences": []})  # its title area; a page's words are not cut into sentences: a rewrite of a page is a suggestion to use
    return out


# ---------------------------------------------------------------- the evidence each unit is read with

class Pools:
    """The evidence a unit is read with: its project's own ledger blocks, the entries it names in `evidence: [ids]`, its
    role's context, and, for an item that has no ledger of its own (a resume written by hand beside a ledger of the same
    company), the role's projects that the resume does not print, ranked by the words they share with it."""

    def __init__(self, profile: dict, lang: str):
        self.profile = profile  # the edition's profile
        self.base = W.ledger_view(profile)  # ids are read against the ledger as it was before any draft
        self.U = C.units_of(self.base, lang)  # the units in the review's language
        self.lex = C.Lex(self.U)  # word matching, to rank blocks for a unit
        self.lang = lang  # the review's language
        self.printed = set()  # the projects the resume prints in this language
        self.roles = {}  # project id -> role key
        self.named = {}  # project id -> the entries it names as its evidence
        self.titles = {}  # project id -> its titles (the ledger's, and the one the edition prints), to pair a deck page with its project
        self.elsewhere = set()  # the other language's own items: never a unit's evidence
        for ri, r in enumerate(C.as_list(self.base.get("roles")), 1):  # every project of every role
            rk = W.role_key(r, ri)  # the role's key
            for pi, p in enumerate(C.as_list(r.get("projects")) if isinstance(r, dict) else [], 1):  # its projects
                if not isinstance(p, dict):  # a broken entry
                    continue  # skipped
                pid = W.project_id(p, rk, pi)  # the id the units use
                self.roles[pid] = rk  # its role
                self.named[pid] = [str(x) for x in C.as_list(p.get("evidence")) if isinstance(x, str)]  # the entries it says it rests on
                self.titles[pid] = [C.clean_text(W.pick(p.get("title"), lang))]  # its ledger title in this language
                if p.get("resume") is not False and (not p.get("lang") or p.get("lang") == lang):  # printed in this language
                    self.printed.add(pid)  # its blocks are its own words, never another item's evidence
                elif p.get("resume") is not False and p.get("lang"):  # the other language's own item: the same words translated, no ledger
                    self.elsewhere.add(pid)
        for ri, r in enumerate(C.as_list(profile.get("roles")), 1):  # the titles the edition prints (a draft may word them otherwise)
            rk = W.role_key(r, ri) if isinstance(r, dict) else ""
            for pi, p in enumerate(C.as_list(r.get("projects")) if isinstance(r, dict) else [], 1):
                if isinstance(p, dict):
                    shown = C.clean_text(W.pick(p.get("title"), lang))  # its printed title in this language
                    pid = W.project_id(p, rk, pi)
                    if shown and shown not in self.titles.setdefault(pid, []):
                        self.titles[pid].append(shown)

    def text(self, uid: str) -> str:
        """One unit's text."""
        return self.U["index"][uid]["text"] if uid in self.U["index"] else ""  # empty for an unknown id

    def blocks(self, ref: str) -> list:
        """The block ids of a project id, or the id itself when it is one block."""
        if ref in self.U["proj"]:  # a whole project
            return list(self.U["proj"][ref])  # its blocks
        return [ref] if ref in self.U["index"] else []  # one block, or nothing for an id the profile no longer has

    def ranked(self, text: str, ids: list) -> list:
        """Some block ids, the ones sharing the most words with a text first (ties keep their order)."""
        q = self.lex.query(text)  # the text's terms with their twins in the other language
        scored = [(self.lex.score(q, i), k, i) for k, i in enumerate(ids) if i in self.lex.tf]  # each block's score
        return [i for s, _, i in sorted(scored, key=lambda x: (-x[0], x[1])) if s > 0]  # sharing nothing: left out

    def take(self, ids: list, budget: int, seen: set) -> list:
        """Blocks in order until the budget of characters is spent, each once."""
        out = []  # (id, text)
        for i in ids:  # in the order given
            if i in seen:  # already listed for this unit
                continue  # once
            s = self.text(i)[:900]  # its words; a long block keeps its start
            if not s or (budget < len(s) and out):  # empty, or past the budget once something is listed
                continue  # the next may be shorter
            seen.add(i)  # listed
            out.append((i, s))  # with its id
            budget -= len(s)  # spent
        return out

    def pool(self, unit: dict) -> list:
        """(id, text) of the evidence a unit is read with, its own first, within POOL_CHARS."""
        printed = plain(unit.get("text"))  # the unit's own words: never listed as their own evidence
        pid = unit.get("pid") or self.pair(unit)  # an item's project, or the project a deck page speaks of
        seen = {b for b in (self.blocks(pid) if pid else []) if len(plain(self.text(b))) >= 12 and plain(self.text(b)) in printed}  # its block that is the printed words themselves (a resume written by hand)
        query = " ".join([unit.get("title") or "", unit.get("text") or ""])  # what the unit says
        own = [b for b in (self.blocks(pid) if pid else []) if b not in seen]  # the project's own ledger blocks
        named = [b for ref in (self.named.get(pid) or []) for b in self.blocks(ref)]  # the entries it names as its evidence
        out = self.take(own + named, POOL_CHARS, seen)  # its own words first, in the ledger's order
        rk = self.roles.get(pid) if pid else None  # its role
        if rk:  # the role's context: what the company did, for whom
            ctx = [u["id"] for u in self.U["units"] if u["kind"] == "context" and u["id"].startswith(rk + "#c")]  # the role's context blocks
            out += self.take(self.ranked(query, ctx)[:3], POOL_CHARS // 4, seen)  # the three that speak to the unit
        if len(own) + len(named) < 2:  # no ledger of its own: the role's ledger (or the whole profile's, for a page that names no project)
            others = [b for p, r in self.roles.items() if (r == rk or not rk) and p != pid and p not in self.printed and p not in self.elsewhere for b in self.U["proj"].get(p, [])]  # the ledger: projects not printed
            out += self.take(self.ranked(query, others), POOL_CHARS - sum(len(s) for _, s in out), seen)  # the blocks that share most with the unit
        return out

    def pair(self, unit: dict) -> str | None:
        """The project a deck page speaks of, by its title (docs/WRITING.md): the project whose title's words the page's title
        area holds most, its rare words weighing more (a slide often words its title otherwise than the resume's item does),
        two words and PAIR_FLOOR of the title at least. None when no title is held so, or when two projects are held within
        PAIR_MARGIN of each other (a contents page, a page about two pieces of work): an unpaired page's answer names its project."""
        if unit.get("kind") != "slide":  # only a page is paired
            return None
        words = lambda text: set(re.findall(r"[0-9A-Za-z가-힣]{2,}", str(text or "").lower()))  # noqa: E731  the words of a text, two letters at least
        head = words(unit.get("head") or str(unit.get("text", ""))[:HEAD_CHARS])  # the page's title area
        titles = {p: [words(t) for t in ts if len(words(t)) >= 2] for p, ts in self.titles.items()}  # each project's titles, as words
        df = {}  # in how many projects' titles each word stands: "development" names no project, a product's name does
        for ts in titles.values():
            for w in set().union(*ts) if ts else set():
                df[w] = df.get(w, 0) + 1
        weight = lambda w: math.log(1 + max(1, len(titles)) / df.get(w, 1))  # noqa: E731  a rarer word weighs more
        scored = []  # (how much of its best title the page holds, project)
        for p, ts in titles.items():  # every project
            best = 0.0
            for tw in ts:  # each of its titles
                shared = tw & head  # the words the page holds
                if len(shared) >= 2:  # one word names no project
                    best = max(best, sum(weight(w) for w in shared) / (sum(weight(w) for w in tw) or 1))
            if best >= PAIR_FLOOR:  # held enough to be named
                scored.append((best, p))
        if not scored:  # the page names no project's title
            return None
        scored.sort(key=lambda x: -x[0])  # the best held first
        if len(scored) > 1 and scored[0][0] - scored[1][0] < PAIR_MARGIN:  # two projects held alike: which one is not known
            return None
        return scored[0][1]


# ---------------------------------------------------------------- the checks that need no agent

def names_of(text: str, lang: str = "ko") -> set:
    """The names a text prints: the tools, products, clients and places a copy can lose, as the fact check reads them
    (src/factcheck.py, src/cover.py). In a Korean text every Latin word is such a name (three letters at least), with the
    Korean organisation names; in an English text every word is Latin, so only the words that look like names count:
    capitals inside a sentence, acronyms, inner capitals, digits (Kubernetes, AWS, PostgreSQL, S3), never an ordinary word."""
    plain_text = re.sub(r"[\u2010-\u2013\u2212]", "-", str(text or "").replace("==", ""))  # marks are no words; a typeset hyphen (Blue\u2011green) is the plain one
    if lang == "en":  # an English text: the name-like words only
        return {w.lower() for w, initial in C.name_parts(plain_text) if C.name_like(w, initial) and w.lower() not in C.COMMON_CAPS
                and len(re.sub(r"[^a-z]", "", w.lower())) >= 3} | F.korean_orgs(plain_text)  # a month, a language or "AI" alone is no name a copy can lose
    latin = {w for w in F.latin_tokens(plain_text) if len(re.sub(r"[^a-z]", "", w)) >= 3}  # three letters at least: AI or PM alone is no name a copy can lose
    return latin | F.korean_orgs(plain_text)  # with the organisations a Korean text names


def lost_names(old: str, new: str, lang: str = "ko") -> list:
    """The names an older version printed and the new words do not, in the older version's order. A name the new words still
    hold in any case or form counts as kept."""
    now = names_of(new, lang) | F.latin_tokens(re.sub(r"[\u2010-\u2013\u2212]", "-", str(new or "")))  # every Latin word of the new words: a name written in lower case is still there
    gone, seen = [], set()  # in order, once each
    for w in sorted(names_of(old, lang), key=lambda x: str(old).lower().find(x.lower())):  # in the order the old words name them
        if w not in now and not F.plural_ok(w, now) and w not in seen:  # gone from the new words
            seen.add(w)  # once
            gone.append(w)  # lost
    return gone


def match_old(unit: dict, old_units: list) -> dict | None:
    """The same item in an older version: the one with the same project id, or None. A title is no identity: another project
    may share most of its words, and holding an item to another project's words would invent what it lost."""
    if unit.get("kind") != "item":  # a page has no stable identity across versions
        return None
    return next((o for o in old_units if o.get("pid") and o.get("pid") == unit.get("pid")), None)  # one id, one project


def rule_findings(unit: dict, lang: str, old: dict | None) -> list:
    """The findings that need no agent: circumstance phrases, and the names the copy that went out printed and this unit lost."""
    out = []  # findings
    said = F.circumstances(unit.get("text", ""))  # circumstance phrases (src/factcheck.py)
    if said:  # one at least
        q = said[0]  # the first is quoted
        out.append(finding(unit, "depth_circumstance", t("m_circumstance", lang, quote=q), "ask", question=t("q_circumstance", lang, quote=q), by="rule", quote=q))
    if old:  # the copy that went out had this unit
        gone = lost_names(old.get("text", ""), unit.get("text", ""), lang)  # what it named and this one does not, by the edition's language
        if gone:  # the unit is thinner than what went out
            names = ", ".join(gone[:6])  # the first few, for the words
            out.append(finding(unit, "depth_thinner", t("m_thinner", lang, lost=names), "ask", question=t("q_thinner", lang, lost=names), by="rule", lost=gone[:12], went_out=old.get("text", "")[:600]))
    return out


def finding(unit: dict, code: str, missing: str, way: str, *, rewrite: dict | None = None, question: str = "", by: str = "agent", **more) -> dict:
    """One finding: its stable id, its code, what is missing, its way on, and its state."""
    out = {"id": "f" + short_hash(unit["id"], code), "unit": unit["id"], "code": code, "missing": " ".join(str(missing or "").split())[:400],  # the id stays across reviews of the same unit
           "way": way, "by": by, "state": "open"}  # the way on, who found it, and that it is still to do
    if rewrite:  # the evidence holds what is missing
        out["rewrite"] = rewrite  # {replaces, text, ev, names}
    if question:  # the evidence does not: the person is asked
        out["question"] = " ".join(str(question).split())[:400]  # one question
    out.update({k: v for k, v in more.items() if v})  # the quote, the names lost, the words that went out
    return out


# ---------------------------------------------------------------- the agent's part

def unit_block(unit: dict, pool: list, old: dict | None) -> str:
    """One unit as the prompt shows it: its id, title and place, its printed words, the version that went out, its evidence."""
    lines = [f"### {unit['id']} | {unit.get('title', '')} | {unit.get('where', '')}"]  # the head the answer names
    if unit["kind"] == "item":  # an item's sentences, each a line the rewrite may name
        lines.append("Printed sentences:")
        lines += [f"- {s}" for s in unit["sentences"]]  # as printed, marks kept
    else:  # a page's words
        lines.append(f"Words on the page: {unit['text']}")
    if old and plain(old.get("text")) != plain(unit.get("text")):  # the copy that went out said it otherwise
        lines.append(f"Version that went out: {old['text'][:800]}")
    lines.append("Evidence (id, then text):")  # what a rewrite may cite
    lines += [f"[{i}] {s}" for i, s in pool] or ["(none: only the person can add what is missing)"]  # nothing to cite: every finding is a question
    return "\n".join(lines)


def prompt_for(batch: list, lang: str, style: dict) -> str:
    """The review prompt for a batch of (unit, pool, old) triples."""
    kinds = {u["kind"] for u, _, _ in batch}  # items, pages, or both
    what = " and ".join(x for x in (("project items" if "item" in kinds else ""), ("portfolio pages" if "slide" in kinds else "")) if x)  # what is read
    page_rule = ('- A page that is not about one piece of work (a cover, contents, a chapter divider, an end page) gets "skip": true and no findings.'
                 if "slide" in kinds else "")  # only a deck has such pages
    return W.prompt_text("depth_review", what=what, language={"ko": "Korean", "en": "English"}[lang], rules=W.rules_text(style),  # the template with the shared sentence rules
                         page_rule=page_rule, style_line=("Korean rewrites: " + W.ko_style(style)) if lang == "ko" else 'English rewrites: past tense, no "I", start with a verb.',  # the sentence style a rewrite keeps
                         units="\n\n".join(unit_block(u, p, o) for u, p, o in batch))  # every unit of the batch


def batches(rows: list) -> list:
    """(unit, pool, old) rows grouped so that each call's units stay within BATCH_CHARS."""
    out, cur, size = [], [], 0  # the groups, the open one and its size
    for row in rows:  # in print order
        n = len(unit_block(*row))  # its size in the prompt
        if cur and size + n > BATCH_CHARS:  # the open group is full
            out.append(cur)  # closed
            cur, size = [], 0  # the next one starts
        cur.append(row)  # this unit joins the open group
        size += n  # its size counts
    return out + ([cur] if cur else [])  # the last group too


def model_ask(backend: str | None, raw: list | None):
    """The real model through llm.run(); every answer is kept in `raw` for audit and replay. A wrong shape is not asked
    again (retries=0): a review's calls are counted before it starts, and a batch the model garbled is said, not repeated."""
    def ask(task: str, prompt: str, required: tuple):  # the signature of write_resume's ask, so a test's stand-in fits both
        try:
            out = llm.run(task, prompt, system=SYSTEM, want_json=True, required=required, backend=backend, timeout=900, retries=0)  # one call per batch
        except llm.LLMUnavailable as e:  # no backend, or it stopped
            raise W.Stopped(str(e))  # the caller keeps what was found before
        except ValueError:  # it answered, but not in the shape asked for
            out = None  # an unusable answer counts as none
        if raw is not None:  # kept as the model wrote it, before any check
            raw.append({"task": task, "answer": out})
        return out
    return ask


def checked_rewrite(f: dict, unit: dict, pool_ids: set, ctx, lang: str) -> tuple[dict | None, list]:
    """A rewrite the model offered, held to the draft's own checks: it replaces a sentence the unit prints (or adds one), it
    cites only the unit's evidence, and its words pass the fact, name, claim and style checks against what it cites.
    Returns (the rewrite, []) or (None, the reasons)."""
    text = " ".join(str(f.get("text") or "").split())  # the new words
    if not text:  # nothing written
        return None, ["empty"]
    ev = [str(i) for i in C.as_list(f.get("ev")) if str(i) in pool_ids]  # only ids the unit was shown
    if not ev:  # it cites nothing it was shown
        return None, ["no_ev"]
    replaces = " ".join(str(f.get("replaces") or "").split())  # the sentence it stands for, "" to add one
    if unit["kind"] == "item" and replaces and plain(replaces) not in {plain(s) for s in unit["sentences"]}:  # a sentence the item does not print
        return None, ["replaces"]
    if unit["kind"] == "item" and replaces:  # the item's own words for it, so the canvas finds it by the same cut
        replaces = next(s for s in unit["sentences"] if plain(s) == plain(replaces))
    names = {str(k): str(v) for k, v in (f.get("names") or {}).items()} if isinstance(f.get("names"), dict) else {}  # spellings the evidence holds otherwise
    R = ctx.style["resume"]  # the pack's lengths: one sentence may take most of an item's room, not more
    limit = int(W.per_lang(R["item_words"] if lang == "en" else R["item_chars"], lang, 75 if lang == "en" else 300) * 0.6)  # a rewrite that runs on would push the pages
    issues = W.text_issues(text, lang, ev, names, ctx, kind="item" if unit["kind"] == "item" else "deck", marks=(0, 1), limit=limit)  # the draft's own checks
    bad = [i for i in issues if i["code"] in W.FACT_CODES | W.STYLE_CODES | W.CLAIM_CODES | {"circumstance"}]  # facts, style and claims refuse it, and a circumstance (the very thing a review takes out); other polish does not
    if bad:  # it says what the evidence does not, or how the rules do not allow
        return None, list(dict.fromkeys(i["code"] for i in bad))  # each reason once
    return {"replaces": replaces, "text": text, "ev": ev, "names": names}, []


def agent_findings(unit: dict, answer: dict, pool_ids: set, ctx, lang: str) -> list:
    """The model's findings for one unit, each checked: a known code, a way on, and a rewrite that passes the checks (a
    rewrite that fails becomes the question, so nothing the evidence does not hold is ever offered as words to print)."""
    out, seen = [], {}  # findings; per code, where its finding stands in out and whether its rewrite passed
    for f in C.as_list(answer.get("findings")) if isinstance(answer, dict) else []:  # each one the model gave
        if not isinstance(f, dict):  # a stray value
            continue
        code = SHORT.get(str(f.get("code") or "").strip().lower().removeprefix("depth_"))  # "hard" or "depth_hard" alike
        if not code or (code in seen and seen[code][1]):  # an unknown code, or a code whose finding already offers words that pass
            continue
        hint = {"quote": next(iter(F.circumstances(unit.get("text", ""))), ""), "lost": ""}  # what a code's own question quotes, when the words hold it
        key = "q_circumstance_plain" if code == "depth_circumstance" and not hint["quote"] else "q_" + code[6:]  # never an empty quote in the words
        missing = str(f.get("missing") or "").strip() or t(key, lang, **hint)  # what is missing; the question's words when it said none
        rw, why = (checked_rewrite(f, unit, pool_ids, ctx, lang) if str(f.get("way")) == "rewrite" else (None, []))  # the rewrite, checked
        question = str(f.get("question") or "").strip() or t(key, lang, **hint)  # its own question, else the code's
        if rw:  # the evidence holds it, and the words pass
            made = finding(unit, code, missing, "rewrite", rewrite=rw, question=question if f.get("question") else "")
        else:  # the person is asked
            made = finding(unit, code, missing, "ask", question=question, rejected=why)  # a rewrite that failed says why
        if code in seen:  # a second finding of a code whose first offers no words that pass
            if not rw:  # it offers none either: the first stands
                continue
            out[seen[code][0]] = made  # its passing rewrite takes the first one's place: one finding per code
        else:
            out.append(made)
        seen[code] = (out.index(made), bool(rw))  # where it stands, and whether it offers words
    return out


def merge(rule: list, agent: list) -> list:
    """The agent's findings with the rule-based ones: one finding per code, the agent's wording and rewrite first, the rule's
    quote and lost names kept on it."""
    by = {f["code"]: f for f in agent}  # the agent's, by code
    for f in rule:  # the rule-based ones
        if f["code"] in by:  # the agent found it too
            by[f["code"]].update({k: f[k] for k in ("quote", "lost", "went_out") if k in f})  # what the rule saw stays on it
        else:  # only the rule found it
            by[f["code"]] = f
    return sorted(by.values(), key=lambda f: CODES.index(f["code"]))  # in the order a reader weighs them


# ---------------------------------------------------------------- the verdict: strong, adequate or thin

def quote_words(text) -> str:
    """Words for finding a quote in a unit: no marks or quotation marks, a typeset hyphen or dash as the plain one, one space,
    lower case. A model that copies the words drops a mark or a curly quote; the words themselves stay."""
    s = str(text or "").replace("==", "").replace("**", "")  # the highlight and bold marks are no words
    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)  # Blue\u2011green, 2023\u20132024: one hyphen however it was typeset
    s = re.sub(r"[\"'\u2018\u2019\u201c\u201d\u300c\u300d\u300e\u300f]", "", s)  # quotation marks of both languages
    return re.sub(r"\s+", " ", s).strip().lower()  # one space, one case


# What made the work hard, in words that say how: a limit or an inability, a failure or a first try that did not work, a cost
# of time or load, requirements held at once, something that had to hold, a cause. The verbs and connectives of each kind, in
# both languages: a quote that holds one says how the work was hard, whatever it names.
DIFFICULTY = re.compile("|".join((
    # Korean: an inability or a limit ("할 수 없었다", "하지 못했다", "하면 안 되는", "한계", "부족")
    r"수\s?(?:가\s)?없", r"못", r"불가", r"(?<![가-힣])안\s?(?:되|됐|돼)", r"않", r"어렵", r"어려", r"힘들", r"한계", r"제약", r"제한", r"부족",
    r"모자", r"초과", r"넘쳐", r"넘치", r"병목", r"포화", r"감당",
    # Korean: a failure, or what did not work first ("멈췄다", "끊겼다", "머물자", "처음에는", "했지만")
    r"실패", r"멈[추췄춰춤]", r"끊[기겼어]", r"깨[지졌]", r"터[지졌]", r"다운[되됐돼]", r"죽[었는어]", r"누락", r"유실", r"어긋", r"틀어", r"꼬[여였이]",
    r"머[물무]", r"그[쳤치]", r"처음에는", r"처음엔", r"첫\s?(?:시도|버전|프로토타입)", r"[했였됐었]으나", r"[했였됐었이하]지만", r"그러나", r"오히려", r"되돌", r"롤백",
    # Korean: the cost of time or load ("사흘이 걸렸다", "아침까지 밀렸다", "요청이 급증")
    r"걸[렸리려]", r"밀렸", r"밀려", r"밀리[면고는지]", r"늦[어게]", r"급증", r"폭증", r"쌓[여였이]",
    # Korean: requirements held at once, and what had to hold ("동시에", "멈추지 않고", "중단 없이", "해야 했다", "이내")
    r"동시에", r"상충", r"충돌", r"맞부딪", r"엇갈", r"면서도", r"사이에서", r"해야", r"하여야", r"지켜야", r"맞춰야", r"유지한\s?채", r"유지하며",
    r"중단\s?없이", r"무중단으로", r"이내", r"만에",
    # Korean: a cause ("때문에", "탓에", "~라서")
    r"때문", r"탓에", r"라서",
    # English: an inability or a limit
    r"\bcould(?: not|n't)\b", r"\bcannot\b", r"\bcan't\b", r"\bunable\b", r"\bimpossible\b", r"\blimit", r"\bconstrain", r"\btoo\b", r"\bran out\b",
    r"\bexceed", r"\bbottleneck", r"\bsaturat", r"\bhard to\b", r"\bdifficult",
    # English: a failure, or what did not work first
    r"\bfail", r"\bbroke", r"\bcrash", r"\bstall", r"\bstopped\b", r"\bwent down\b", r"\boutage", r"\blost\b", r"\bstuck\b", r"\bstayed at\b",
    r"\bdid(?: not|n't) work\b", r"\bat first\b", r"\bfirst (?:attempt|try|version|prototype)\b", r"\bbut\b", r"\bhowever\b", r"\bthough\b", r"\broll(?:ed)? back\b",
    # English: the cost of time or load
    r"\btook (?:\w+ )?(?:minutes?|hours?|days?|weeks?|months?)\b", r"\bpiled\b", r"\bspiked\b", r"\bbacklog", r"\bslowed\b", r"\bdelayed\b", r"\bcostly\b", r"\bexpensive\b",
    # English: requirements held at once, and what had to hold
    r"\bat once\b", r"\bat the same time\b", r"\bwhile\b", r"\bconflict", r"\bcompeting\b", r"\btrade-?off", r"\bhad to\b", r"\bmust\b", r"\brequired\b",
    r"\bwithout\b", r"\bwithin (?:a |an |one |two |three |\d)", r"\bno downtime\b", r"\bzero downtime\b",
    # English: a cause
    r"\bbecause\b", r"\bdue to\b",
)))


def shows_difficulty(quote) -> bool:
    """Whether a quote holds a word that says how the work was hard (DIFFICULTY)."""
    return bool(DIFFICULTY.search(quote_words(quote)))  # marks, quotes and case aside, as said_in reads it


# Where the work began: a place or an environment, the equipment, the material, a structure or a state. A quote whose last word
# is one of them, with no word of DIFFICULTY in it, only names the starting situation ("scattered metadata", "a slow query",
# "a closed network"), however it is described: not what made solving it hard. A quote that ends on an event, a problem or a
# consequence ("a race between two writers", "a stale cache key", "the retry storm") is left to the agent's judgment.
SETTING_KO = ("환경", "망", "네트워크", "센터", "서버룸", "클러스터", "인프라", "시스템", "플랫폼", "서버", "장비", "가속기", "노드", "현장",
              "데이터", "산출물", "로그", "코드", "코드베이스", "문서", "쿼리", "스크립트", "설정", "파일", "구조", "상태", "상황", "체계", "운영", "레거시")
SETTING_KO_NOT = ("전망", "희망", "욕망", "사망", "도망")  # words that end like a network and are none
SETTING_EN = ("environment", "network", "center", "centre", "cluster", "infrastructure", "system", "platform", "server", "hardware", "site",
              "data", "metadata", "artifact", "log", "code", "codebase", "document", "doc", "query", "queries", "script", "configuration", "config",
              "file", "structure", "state", "situation", "setup", "architecture", "monolith", "stack", "operation", "process", "accelerator", "node", "gpu")
PARTICLES = ("에서는", "에서도", "에서", "에는", "으로", "에게", "에", "의", "은", "는", "이", "가", "을", "를", "로", "와", "과", "도", "만")  # what follows a Korean noun


def is_situation(quote) -> bool:
    """Whether a quote for what made the work hard only names where the work began: its last word is a setting, the equipment,
    the material, a structure or a state (SETTING_KO, SETTING_EN), and no word in it says how the work was hard (DIFFICULTY)."""
    words = quote_words(quote)  # the quote as said_in reads it
    if not words or DIFFICULTY.search(words):  # nothing, or it says how it was hard
        return False
    last = re.sub(r"[^\w가-힣-]+$", "", words.split(" ")[-1])  # its last word, without a stop or a bracket after it
    if re.search(r"[가-힣]$", last):  # a Korean word: the particle after the noun goes first
        for pa in PARTICLES:  # the longest first, as listed
            if last.endswith(pa) and len(last) > len(pa):
                last = last[:-len(pa)]
                break
        return last.endswith(SETTING_KO) and not last.endswith(SETTING_KO_NOT)  # a compound ends on its head: 폐쇄망, 데이터센터
    return last in SETTING_EN or last.rstrip("s") in SETTING_EN or last.removesuffix("es") in SETTING_EN  # a plural is the same thing


MIN_PIECE = 4  # letters each piece of a quote holds at least: "AI" or "설계" alone points at nothing


def found_in_order(pieces: list, words: str) -> bool:
    """Whether the pieces stand in the words one after another, in the order given."""
    at = 0  # where the next piece may start
    for piece in pieces:  # in the quote's order
        k = words.find(piece, at)  # the first place at or after the last piece's end
        if k < 0:  # not there, or only before the piece that comes first
            return False
        at = k + len(piece)  # the next piece comes after this one
    return True


def said_in(quote, text) -> bool:
    """Whether a quote the agent gave stands in the unit's words: each of its pieces (a quote may skip words with "...") is
    found in them in the quote's order, as written or with the spaces left out (Korean spacing varies as words are
    copied). Each piece holds four letters at least, and the quote six: fewer point at nothing."""
    pieces = [p.strip(" .,;:") for p in re.split(r"\.\.\.|\u2026", quote_words(quote))]  # the pieces either side of a skip, without the end marks a copy adds
    pieces = [p for p in pieces if p]  # a skip at either end leaves an empty piece
    if not pieces or sum(len(p) for p in pieces) < 6 or any(len(p.replace(" ", "")) < MIN_PIECE for p in pieces):  # "AI", "설계", "... 및 ...": nothing a reader could weigh
        return False
    words = quote_words(text)  # the unit's words, the same way
    return found_in_order(pieces, words) or found_in_order([p.replace(" ", "") for p in pieces], words.replace(" ", ""))  # as written, or with the spaces left out


def quote_counts(part: str, quote: str, printed: str) -> str:
    """Why a quote for a part counts or not: "" when it counts, "not_in_words" when the unit's words do not hold it, and
    "situation" when it is a quote for what made the work hard that only names where the work began (is_situation)."""
    if not said_in(quote, printed):  # the words do not say it
        return "not_in_words"
    if part == "hard" and is_situation(quote):  # a starting situation, not what made solving it hard
        return "situation"
    return ""  # it counts


def judge_parts(unit: dict, answer: dict) -> tuple[dict, dict, dict] | None:
    """The core parts the unit's words state, by the agent's quotes, with the quotes that did not count and why:
    ({part: the quote that counts, or ""}, {part: a quote that did not count}, {part: why}). A quote counts when the words
    hold it (said_in), for what made the work hard when it does not just name where the work began (quote_counts), when no
    other part counted the same words ("repeated"), and when the three parts do not all come from one sentence ("one_sentence":
    one sentence never makes a unit strong; the last of the three does not count). None when the answer rates nothing (an
    answer in the shape before verdicts, or a garbled one): the unit has no verdict."""
    st = answer.get("stated") if isinstance(answer, dict) else None  # {"hard": "...", "decision": "", "mechanism": "..."}
    if not isinstance(st, dict):  # nothing rated
        return None
    printed = f"{unit.get('title', '')}\n{unit.get('text', '')}"  # what the unit prints: its title and its words
    parts, refused, why = {}, {}, {}  # per part: the quote that counts; a quote that did not, and why
    for p in CORE:  # the three parts
        quotes = [" ".join(q.split()) for q in C.as_list(st.get(p)) if isinstance(q, str) and q.strip()]  # one quote, or several
        parts[p] = next((q for q in quotes if not quote_counts(p, q, printed)), "")  # the first that counts
        if not parts[p] and quotes:  # the agent gave words, and none counted
            refused[p], why[p] = quotes[0][:300], quote_counts(p, quotes[0], printed)
    seen = {}  # the words each counted quote holds, by the part that counted them first
    for p in CORE:  # in the parts' order
        key = quote_words(parts[p]).replace(" ", "")  # the words, however spaced
        if key and key in seen:  # the same words already counted for another part: once only
            refused[p], why[p], parts[p] = parts[p][:300], "repeated", ""
        elif key:
            seen[key] = p
    if all(parts[p] for p in CORE):  # all three: they must not all come from one sentence
        cut = [unit.get("title", "")] + (unit.get("sentences") or sentences(unit.get("text", "")))  # the title, then each sentence (a page's words cut as an item's are)
        where = [next((k for k, x in enumerate(cut) if said_in(parts[p], x)), None) for p in CORE]  # the one sentence that holds each quote, if one does
        if where[0] is not None and where[0] == where[1] == where[2]:  # one sentence for all three
            refused["mechanism"], why["mechanism"], parts["mechanism"] = parts["mechanism"][:300], "one_sentence", ""
    return parts, refused, why


def stated_parts(unit: dict, answer: dict) -> dict | None:
    """The core parts the unit's words state (judge_parts): {part: the quote that counts, or ""}, or None when nothing was rated."""
    got = judge_parts(unit, answer)  # the whole judgment
    return got[0] if got else None


def refused_quotes(unit: dict, answer: dict, parts: dict | None = None) -> tuple[dict, dict]:
    """The quotes the agent gave for a part that do not count, and why (judge_parts): kept on the unit, so a reader sees why a
    part it called stated counts as missing. Returns ({part: quote}, {part: why})."""
    got = judge_parts(unit, answer)  # the same judgment
    return (got[1], got[2]) if got else ({}, {})


def verdict_of(parts: dict) -> str:
    """The verdict of a unit by the rule: all three core parts stated is strong, one missing adequate, two or three thin."""
    missing = sum(1 for p in CORE if not parts.get(p))  # the parts its words do not state
    return "thin" if missing >= 2 else "strong" if missing == 0 else "adequate"


def by_verdict(unit: dict, agent: list, parts: dict, verdict: str, lang: str) -> list:
    """The agent's findings held to the unit's verdict: a strong unit keeps only names and routine; a part the words state
    takes no finding (the agent quoted where it is said); a part they do not state always has one, the agent's or, when it
    gave none, the part's own question."""
    keep = []  # the findings that stand
    for f in agent:  # each finding the agent gave, checked already
        if verdict == "strong" and f["code"] not in STRONG_KEEPS:  # a strong unit: names and routine only, when the agent saw them matter
            continue
        if f["code"] in CORE_CODES and parts.get(f["code"][len("depth_"):]):  # a part the words state: nothing is missing there
            continue
        keep.append(f)
    have = {f["code"] for f in keep}  # the codes that have a finding
    for p in CORE:  # every missing part has a way on
        if not parts.get(p) and "depth_" + p not in have:  # rated missing, and no finding of the agent's says so
            keep.append(finding(unit, "depth_" + p, t("m_" + p, lang), "ask", question=t("q_" + p, lang)))  # the part's own question
    return sorted(keep, key=lambda f: CODES.index(f["code"]))  # in the order a reader weighs them


def gate_open(unit: dict) -> bool:
    """A thin unit whose missing parts are not all done: a finding of a core part still open (not used, answered or left)."""
    return unit.get("verdict") == "thin" and any(f.get("gate") and f.get("state") == "open" for f in unit.get("findings") or [])


def order_key(unit: dict) -> tuple:
    """Where a unit stands in the list: thin first (the most parts missing first), then adequate, then the units with no
    verdict, then strong; in print order within each."""
    return RANK.get(unit.get("verdict"), RANK[None]), -len(unit.get("missing") or []), unit.get("n", 0)


# ---------------------------------------------------------------- the review

def review(profile: dict, lang: str = "ko", *, style: dict | None = None, pages: list | None = None, old: dict | None = None,
           ask=None, backend: str | None = None, max_calls: int = MAX_CALLS, raw: list | None = None, earlier: dict | None = None) -> dict:
    """Review an edition in one language. profile: the profile it prints (a draft merged in). pages: the words of its deck's
    pages, or None. old: the profile of the copy that last went out, or None. ask: a stand-in for the model (tests, a
    replay); without it the backend is asked, and with the `none` backend only the rule-based checks run. earlier: the last
    review, whose left findings stay left while their unit's words stay the same. Returns the review (SCHEMA)."""
    style = style or W.load_style(None)  # the default pack when none is given
    units = items_of(profile, lang) + slides_of(pages or [], lang)  # what is read, in print order
    old_units = items_of(old, lang) if old else []  # the same edition as it went out
    pools = Pools(profile, lang)  # the evidence each unit is read with
    ctx = W.Ctx(profile, style, (profile.get("_draft") or {}).get("posting"))  # what a rewrite is checked against, as a draft's sentence is
    rows = [(u, pools.pool(u), match_old(u, old_units)) for u in units]  # each unit with its evidence and its older self
    found = {u["id"]: rule_findings(u, lang, o) for u, _, o in rows}  # the checks that need no agent
    agent_on = ask is not None or (llm.chosen(backend)[0] != "none")  # an agent can be asked
    calls, stopped, read, skipped = 0, "", set(), set()  # model calls, why it stopped, units the agent read, pages it set aside
    limited, asked = False, set()  # whether the call limit left batches unasked; the units whose batch the agent answered
    rated = {}  # unit id -> (verdict, the parts its words state, the quotes that did not count, and why)
    if agent_on and rows:  # the agent's part
        ask = ask or model_ask(backend, raw)  # the model, a replay or a test's stand-in
        for batch in batches(rows):  # one call per batch
            if calls >= max_calls:  # the limit the caller set
                limited = True  # the reason the rest stays unread, said in the notes
                break  # the rest stays unread, and the review says how many
            calls += 1  # counted before it is made
            try:
                got = ask("depth-review", prompt_for(batch, lang, style), ("units",))  # {"units": [{"id", "findings": [...]}]}
            except W.Stopped as e:  # the backend stopped
                stopped = str(e)[:300]  # said in the review
                break  # what was found so far stays
            answers = {}  # by unit id, as the prompt wrote it, with its kind left off ("alpha-1" for "item:alpha-1"), or with the rest of its head line
            for a in C.as_list((got or {}).get("units") if isinstance(got, dict) else None):
                if isinstance(a, dict):
                    k = str(a.get("id") or "").strip().removeprefix("###").split(" | ")[0].strip()  # the id the model wrote; a model that copies the whole "### id | title | place" line still names its unit
                    answers[k] = a
                    for kind in ("item:", "slide:"):  # a model may drop the kind before the id: the unit is the same
                        if ":" not in k:
                            answers.setdefault(kind + k, a)
            for u, pool, _ in batch:  # each unit of the batch
                asked.add(u["id"])  # its batch was asked and answered: an unread one was left out by the agent
                a = answers.get(u["id"])  # its answer
                if a is None:  # the model left it out
                    continue  # unread: counted below
                try:  # one unit's odd answer never costs the others theirs
                    if a.get("skip") is True and u["kind"] == "slide":  # a page that is no piece of work
                        skipped.add(u["id"])  # set aside: no findings
                    else:
                        mine = agent_findings(u, a, {i for i, _ in pool}, ctx, lang)  # the agent's findings, checked
                        judged = judge_parts(u, a)  # the core parts its words state, by quotes found in them, and the quotes that did not count
                        parts = judged[0] if judged else None
                        rate = (verdict_of(parts), parts, judged[1], judged[2]) if judged else None  # rated: the verdict follows the rule
                        if rate:  # and the findings follow the verdict
                            mine = by_verdict(u, mine, parts, rate[0], lang)
                        found[u["id"]] = merge(found[u["id"]], mine)  # merged with the rule's
                        if rate:  # kept once the unit's findings stand, so a unit with a verdict is always a unit read
                            rated[u["id"]] = rate
                    read.add(u["id"])  # the agent read it
                except Exception:  # noqa: BLE001  an answer in a shape no check foresaw: the unit stays unread and is counted
                    continue
    keep = {}  # findings the person left, by id, with the words they were left on
    for eu in (earlier or {}).get("units") or []:  # the last review
        for f in eu.get("findings") or []:  # each of its findings
            if f.get("state") == "left":  # the person decided to leave it
                keep[f["id"]] = eu.get("hash")  # stays left while the words stay the same
    out_units = []  # the record's units
    for n, (u, pool, o) in enumerate(rows):  # in print order, numbered so the order can be had again
        if u["id"] in skipped:  # a page the agent set aside
            continue
        h = short_hash(u.get("text"))  # the words as reviewed
        fs = found[u["id"]]  # its findings
        verdict, parts, refused, refused_why = rated.get(u["id"], (None, None, {}, {}))  # its verdict, when the agent rated it
        for f in fs:  # a finding left before, on the same words, stays left
            if keep.get(f["id"]) == h:
                f["state"] = "left"
            f["verdict"] = verdict  # each finding says its unit's verdict
            f["gate"] = verdict == "thin" and f["code"] in CORE_CODES  # a thin unit's missing part: fixed from evidence or answered before the edition goes out
        paired = pools.pair(u) if u["kind"] == "slide" else None  # the project a deck page speaks of: an answer about the page belongs to it
        out_units.append({**{k: u[k] for k in ("id", "kind", "title", "where", "text") if k in u},
                          **({"pid": u["pid"], "role": u["role"]} if u["kind"] == "item" else {"page": u["page"], **({"pid": paired} if paired else {})}),
                          "sentences": u.get("sentences") or [], "hash": h, "reviewed": u["id"] in read or not agent_on,  # read by the agent, or only the rules were asked
                          "n": n, "verdict": verdict, "stated": parts, "missing": [p for p in CORE if not parts[p]] if parts else [],  # the verdict, the quotes of what is said, the parts not said
                          **({"refused": refused, "refused_why": refused_why} if refused else {}), "gate": verdict == "thin",  # a quote that did not count, and why; a thin unit is the procedure's gate
                          "evidence": [i for i, _ in pool], "findings": fs})
    out_units.sort(key=order_key)  # thin first: what to fill comes before what to polish
    notes = []  # what the review could not do, said
    if not agent_on:  # no agent: only the rules ran
        notes.append("no_agent")
    if pages is None:  # no deck was read
        notes.append("no_deck")
    if old is None:  # nothing went out yet
        notes.append("no_baseline")
    unread = sum(1 for x in out_units if not x["reviewed"])  # units the agent never read
    if unread:  # the limit was reached, it stopped, or its answer left them out
        notes.append(f"unreviewed:{unread}")
    left_out = sum(1 for x in out_units if not x["reviewed"] and x["id"] in asked)  # asked and answered, but not about them
    if left_out:  # the agent's answer left these out (or answered them in a shape no check could read)
        notes.append(f"unanswered:{left_out}")
    if limited:  # the call limit stopped the review before every batch was asked
        notes.append("limit")
    if stopped:  # the backend stopped
        notes.append("stopped")
    every = [f for x in out_units for f in x["findings"]]  # every finding
    counts = {"units": len(out_units), "items": sum(1 for x in out_units if x["kind"] == "item"), "slides": sum(1 for x in out_units if x["kind"] == "slide"),
              "findings": len(every), "rewrites": sum(1 for f in every if f["way"] == "rewrite"), "questions": sum(1 for f in every if f["way"] == "ask"),
              "open": sum(1 for f in every if f["state"] == "open"), "unreviewed": unread,  # what the panel and the command line say
              **{v: sum(1 for x in out_units if x["verdict"] == v) for v in VERDICTS}, "unrated": sum(1 for x in out_units if not x["verdict"]),  # the verdicts
              "gates": sum(1 for x in out_units if gate_open(x))}  # thin units with a missing part still open
    return {"schema": SCHEMA, "lang": lang, "at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "agent": agent_on,  # when, and whether an agent read it
            "backend": (llm.chosen(backend)[0] if ask is None else "stand-in") if agent_on else "none", "calls": calls, "stopped": stopped,
            "max_calls": max_calls, "notes": notes, "counts": counts, "units": out_units}


def calls_needed(profile: dict, lang: str = "ko", pages: list | None = None, old: dict | None = None) -> int:
    """How many model calls a review of this edition makes: count them before a real run."""
    units = items_of(profile, lang) + slides_of(pages or [], lang)  # what would be read
    pools = Pools(profile, lang)  # with its evidence
    old_units = items_of(old, lang) if old else []  # and its older self
    return len(batches([(u, pools.pool(u), match_old(u, old_units)) for u in units]))  # one call per batch


# ---------------------------------------------------------------- the command line

def print_review(rec: dict, out=None) -> None:
    """The review as text: a head line, then each unit with its findings, then what the review could not do."""
    out = out or sys.stdout  # the terminal unless the caller gives a stream
    c = rec.get("counts") or {}  # the counts
    print(t("head", lang=rec.get("lang"), units=c.get("units", 0), items=c.get("items", 0), slides=c.get("slides", 0), findings=c.get("findings", 0),
            rewrites=c.get("rewrites", 0), questions=c.get("questions", 0), calls=rec.get("calls", 0)), file=out)  # the head
    if any(c.get(v) for v in VERDICTS):  # the agent rated units: how many of each, thin first
        print(t("verdicts", thin=c.get("thin", 0), adequate=c.get("adequate", 0), strong=c.get("strong", 0),
                unrated=t("unrated_n", n=c["unrated"]) if c.get("unrated") else ""), file=out)
    for u in sorted(rec.get("units") or [], key=order_key):  # thin first, as the record keeps them
        v = u.get("verdict")  # its verdict, or none
        parts = ", ".join(t("p_" + p) for p in u.get("missing") or [])  # the core parts its words do not state
        print(t("unit", mark=t("mark_" + v) if v else "", title=u.get("title", ""), where=u.get("where", ""), parts=t("parts", parts=parts) if parts else ""), file=out)  # the unit
        if not u.get("findings"):  # nothing missing
            print(t("clean"), file=out)
        for f in u.get("findings") or []:  # each finding
            print(t("finding", code=f["code"], way=f["way"], gate=t("gate_mark") if f.get("gate") else "", missing=f.get("missing", "")), file=out)  # what is missing, and whether it is the gate
            if f.get("rewrite"):  # the words to use
                print(t("rewrite", text=f["rewrite"]["text"], ev=", ".join(f["rewrite"]["ev"])), file=out)
            if f.get("question"):  # the question to answer
                print(t("question", question=f["question"]), file=out)
    for n in rec.get("notes") or []:  # what it could not do
        key = n.split(":")[0]  # unreviewed:N carries its count
        if key == "no_agent":
            print(t("no_agent"), file=out)
        elif key == "unreviewed":  # each reason said as it was: the call limit, a stop (said below), or an answer that left units out
            notes = rec.get("notes") or []
            print(t("unreviewed_limit" if "limit" in notes else "unreviewed", n=n.split(":")[1], calls=rec.get("max_calls")), file=out)
        elif key == "unanswered":
            print(t("unanswered", n=n.split(":")[1]), file=out)
        elif key == "stopped":
            print(t("stopped", why=rec.get("stopped", "")[:160]), file=out)
        elif key == "no_deck":
            print(t("no_deck"), file=out)
        elif key == "no_baseline":
            print(t("no_baseline"), file=out)


def cmd_review(a) -> int:
    """review: reads a profile (and its deck and the copy that went out), writes the review."""
    src = pathlib.Path(a.profile)  # the edition's profile
    prof = W.read_json(src)  # never changed
    style = W.load_style(a.style, W.hints_for(src))  # a workspace pack is found above the profile
    pages = pages_of(a.deck) if a.deck else None  # the deck's words, when given
    old = W.read_json(a.against) if a.against else None  # the copy that went out, when given
    raw = W.SavedList(a.raw) if a.raw else None  # the model's answers, saved after each one when asked to keep them
    ask = W.replay_ask(W.read_json(a.replay).get("answers", [])) if a.replay else None  # stored answers instead of the model
    if a.count:  # only how many calls it would make
        print(calls_needed(prof, a.lang, pages, old))
        return 0
    rec = review(prof, a.lang, style=style, pages=pages, old=old, ask=ask, backend=a.backend, max_calls=a.max_calls if a.max_calls is not None else call_limit(), raw=raw)  # the review
    if a.out:  # kept for the panel or a script
        W.write_json(a.out, rec)
    print_review(rec)  # what it found
    return 0


def cmd_show(a) -> int:
    """show: a review kept before, as text."""
    print_review(W.read_json(a.review))  # the same lines as the review printed
    return 0


def main(argv=None) -> int:
    """Entry point: builds the parser, runs the command, returns its exit code."""
    ap = argparse.ArgumentParser(prog="depth_review.py", description="Review the depth of each printed project item and deck page.")  # prog is fixed, so help shows no path
    sub = ap.add_subparsers(dest="cmd", required=True)  # a bare call prints usage
    r = sub.add_parser("review", help="review an edition's profile (and its deck)")  # the review
    r.add_argument("profile")  # the edition's profile
    r.add_argument("--lang", default="ko", choices=LANGS)  # the edition's language
    r.add_argument("--style", help="style pack name or path")  # the person's rules
    r.add_argument("--deck", help="the edition's deck PDF")  # its pages are read too
    r.add_argument("--against", help="the profile of the copy that last went out")  # what it is held against
    r.add_argument("--backend", help="model backend (default: OFFEROWL_LLM or the default order)")  # the backend
    r.add_argument("--max-calls", type=int, default=None, help="model calls the review may take (default: OFFEROWL_DEPTH_CALLS, else 8)")  # the call limit
    r.add_argument("--count", action="store_true", help="print how many model calls the review would make, and stop")  # count before a real run
    r.add_argument("-o", "--out", help="keep the review here as JSON")  # for a script
    r.add_argument("--raw", help="keep the model's answers here, for audit and replay")  # the answers
    r.add_argument("--replay", help="use stored answers instead of the model")  # no call
    s = sub.add_parser("show", help="print a review kept before")  # a kept review
    s.add_argument("review")  # its file
    a = ap.parse_args(argv)  # None reads sys.argv; tests pass a list
    return cmd_review(a) if a.cmd == "review" else cmd_show(a)


if __name__ == "__main__":  # run as a script, not on import
    sys.exit(main())  # the exit code reaches the shell
