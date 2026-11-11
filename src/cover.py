#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cover letters: plan, draft, build and check (docs/DOCUMENTS.md).

A cover letter answers the lines of one job posting, in the posting's order, with facts from the person's profile. It
repeats no sentence of the resume, carries no numbers unless the style pack allows them, and fits one page.

  offerowl cover plan  <profile.json> <posting.md> [-o plan.json] [--lang ko|en] [--company X] [--role Y]
        split the posting into duties and requirements, match each line to evidence ids, mark what the profile
        cannot show (strength none, or tools named but missing)
  offerowl cover draft <profile.json> <plan.json> [-o cover.json] [--style pack] [--resume file]
        write the paragraphs through llm.run(); every sentence carries evidence ids and the fact check drops any
        sentence with a number, name or tool that its evidence lacks
  offerowl cover build <profile.json> <cover.json> [--job job.json] [--dest dir]
        render DOCX and PDF in the container (src/cover_form.js, then LibreOffice); retries tighter spacing for one page
  offerowl cover check <profile.json> <cover.json> [--pdf cover.pdf] [--resume file] [--style pack]
        fact check, no resume sentence repeated, duties covered in the posting's order, style, one page
  offerowl cover run   <profile.json> <posting.md> [--dir out] [--resume file]     all four in a row

The backend comes from llm.run(): the signed-in Claude Code CLI by default, `--backend none` for no model. Without a
model `plan` still works (word matching), and `draft` writes an empty skeleton for a person to fill.
Messages follow OFFEROWL_LANG (ko or en).
"""
from __future__ import annotations  # lets the `str | None` hints below load on older Python versions too

import argparse  # command line
import collections  # token counts
import copy  # plan copies
import dataclasses  # check context
import difflib  # longest shared run between two token lists
import hashlib  # evidence fingerprints
import json  # all files are JSON
import math  # BM25
import os  # environment
import pathlib  # paths
import re  # most of the text work
import shutil  # staging files for the container
import subprocess  # the container
import sys  # exit codes

import draft as D  # pick() for {ko, en} fields
import factcheck as F  # number, name and organisation primitives
import llm  # the one backend
import pdftools  # the text, size and line boxes of a finished PDF, with poppler or PDFium

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
PROMPTS = ROOT / "src" / "prompts"  # prompt templates (cover_*.md)
SCHEMA_PLAN = "offerowl-cover-plan/0.1"  # plan.json
SCHEMA_COVER = "offerowl-cover/0.1"  # cover.json

# messages (Korean and English)

MSG = {  # one table per language with the same keys; t() falls back to English
    "en": {
        "no_lines": "No duties or requirements found in the posting. Give a posting with a list of responsibilities, or use a model backend.",
        "bad_json": "{path} is not a readable {what}",
        "plan_done": "plan: {n} lines ({duties} duties, {reqs} requirements, {prefs} preferred): {strong} strong, {weak} weak, {none} none; "
                     "{groups} paragraphs planned; matched by {how} -> {path}",
        "plan_gaps": "  not shown by the profile: {lines}",
        "plan_missing": "  tools the profile does not show (the letter must not claim them): {terms}",
        "plan_warn": "  note: {why}",
        "draft_done": "draft: {paras} paragraphs, {sents} sentences kept, {dropped} dropped by the fact check, {words} words, {calls} model calls -> {path}",
        "draft_drop": "  dropped ({code}): {text}",
        "draft_skeleton": "No model answered ({why}). Wrote an empty skeleton to fill by hand -> {path}",
        "build_done": "build: {pages} page(s) at density {density} -> {pdf}",
        "build_fail": "build failed:\n{log}",
        "build_long": "The letter runs to {pages} pages even at the tightest spacing. Shorten the paragraphs (about {over} words over).",
        "check_head": "cover check: {sents} sentences, {lines} posting lines",
        "check_pass": "cover check: PASS ({ok} passed, {skip} not run)",
        "check_fail": "cover check: FAIL ({bad} failed, {ok} passed, {skip} not run)",
        "c_facts": "fact check", "c_evidence": "evidence ids", "c_repeat": "no resume sentence repeated", "c_duties": "duties covered in order",
        "c_gaps": "no claim beyond the profile", "c_style": "style pack", "c_length": "length", "c_page": "one page", "c_layout": "layout",
        "c_claims": "claim strength", "r_claims": "{n} sentences checked, {k} claim more than their evidence",
        "r_facts": "{n} sentences checked, {k} flagged", "r_evidence": "{n} sentences, {k} without a valid evidence id",
        "r_repeat": "{n} sentences against {m} resume lines, {k} repeated", "r_repeat_src": "the profile's resume-bound text (no resume file given)",
        "r_duties": "{a} of {b} planned lines answered, order {order}", "r_gaps": "{k} claims of tools the profile lacks, {m} lines marked none answered",
        "r_style": "{k} style problems", "r_length": "{w} (limit {lim})", "r_page": "{p} page(s)", "r_layout": "{k} layout problems",
        "r_skip_pdf": "no PDF given", "r_skip_plan": "no plan inside the cover file",
        "order_ok": "ok", "order_bad": "broken",
        "i_empty": "empty sentence", "i_unknown_id": "unknown evidence id {id}", "i_no_ev": "no evidence id (only a framing sentence may go without)",
        "i_frame_ev": "a framing sentence must not cite evidence", "i_frame_where": "framing sentences belong to the opening and the closing",
        "i_number": "number not allowed: {detail}", "i_number_word": "counted amount not allowed: {detail}",
        "i_name": "name or tool not in the cited evidence: {detail}", "i_org": "organisation not in the cited evidence: {detail}",
        "i_name_src": "declared source for {detail} is not in the cited evidence", "i_gap_term": "claims a tool the profile does not show: {detail}",
        "i_banned_char": "banned character {detail}", "i_banned_pattern": "banned wording: {detail}", "i_banned_word": "banned word: {detail}",
        "i_too_long": "sentence too long ({detail} words)", "i_repeat": "repeats a resume line ({detail})", "i_claim": "{detail}",
        "i_stale": "evidence {id} changed or vanished since the plan was made",
        "i_gap_line": "answers line {id}, which the plan marks as not shown by the profile",
        "i_missing_line": "line {id} is not answered", "i_order": "line {a} is answered after line {b}",
        "i_words": "{w} words, limit {lim}", "i_pages": "{p} pages", "i_over_budget": "cut to keep the letter within {detail}",
    },
    "ko": {
        "no_lines": "공고에서 업무나 자격 요건을 찾지 못했다. 담당 업무 목록이 있는 공고를 주거나 모델 백엔드를 쓴다.",
        "bad_json": "{path} 를 {what} 로 읽지 못했다",
        "plan_done": "계획: 공고 {n}줄(업무 {duties}, 자격 {reqs}, 우대 {prefs}) 가운데 강함 {strong}, 약함 {weak}, 없음 {none}; "
                     "문단 {groups}개 계획; 짝짓기 방식 {how} -> {path}",
        "plan_gaps": "  프로필이 보여 주지 못하는 줄: {lines}",
        "plan_missing": "  프로필에 없는 도구(편지에 쓰면 안 된다): {terms}",
        "plan_warn": "  참고: {why}",
        "draft_done": "초안: 문단 {paras}개, 문장 {sents}개 남김, 사실 대조에서 {dropped}개 버림, {words}단어, 모델 호출 {calls}번 -> {path}",
        "draft_drop": "  버림({code}): {text}",
        "draft_skeleton": "모델이 답하지 못했다({why}). 사람이 채울 빈 틀을 썼다 -> {path}",
        "build_done": "조판: {pages}쪽, 간격 단계 {density} -> {pdf}",
        "build_fail": "조판 실패:\n{log}",
        "build_long": "가장 좁은 간격에서도 {pages}쪽이다. 문단을 줄인다(약 {over}단어 넘침).",
        "check_head": "자기소개서 검사: 문장 {sents}개, 공고 {lines}줄",
        "check_pass": "자기소개서 검사: 통과(통과 {ok}, 실행 안 함 {skip})",
        "check_fail": "자기소개서 검사: 실패(실패 {bad}, 통과 {ok}, 실행 안 함 {skip})",
        "c_facts": "사실 대조", "c_evidence": "근거 번호", "c_repeat": "이력서 문장 되풀이 없음", "c_duties": "공고 순서대로 업무 대응",
        "c_gaps": "프로필 밖 주장 없음", "c_style": "문체 묶음", "c_length": "분량", "c_page": "한 쪽", "c_layout": "조판",
        "c_claims": "주장 세기", "r_claims": "문장 {n}개 검사, {k}개가 근거보다 세게 주장",
        "r_facts": "문장 {n}개 검사, {k}개 걸림", "r_evidence": "문장 {n}개 가운데 근거 번호가 틀린 것 {k}개",
        "r_repeat": "문장 {n}개를 이력서 {m}줄과 대조, {k}개 되풀이", "r_repeat_src": "프로필의 이력서용 글(이력서 파일을 주지 않음)",
        "r_duties": "계획한 {b}줄 가운데 {a}줄에 답함, 순서 {order}", "r_gaps": "프로필에 없는 도구를 주장한 것 {k}개, 없음으로 표시한 줄에 답한 것 {m}개",
        "r_style": "문체 문제 {k}개", "r_length": "{w}(상한 {lim})", "r_page": "{p}쪽", "r_layout": "조판 문제 {k}개",
        "r_skip_pdf": "PDF 를 주지 않음", "r_skip_plan": "자기소개서 파일에 계획이 없음",
        "order_ok": "맞음", "order_bad": "어긋남",
        "i_empty": "빈 문장", "i_unknown_id": "없는 근거 번호 {id}", "i_no_ev": "근거 번호가 없다(틀을 잡는 문장만 없어도 된다)",
        "i_frame_ev": "틀을 잡는 문장은 근거를 달지 않는다", "i_frame_where": "틀을 잡는 문장은 첫 문단과 끝 문단에만 둔다",
        "i_number": "쓸 수 없는 숫자: {detail}", "i_number_word": "쓸 수 없는 수량 표현: {detail}",
        "i_name": "달아 둔 근거에 없는 이름이나 도구: {detail}", "i_org": "달아 둔 근거에 없는 회사·기관 이름: {detail}",
        "i_name_src": "{detail} 의 원문이 달아 둔 근거에 없다", "i_gap_term": "프로필에 없는 도구를 주장: {detail}",
        "i_banned_char": "금지 글자 {detail}", "i_banned_pattern": "금지 꼴: {detail}", "i_banned_word": "금지 낱말: {detail}",
        "i_too_long": "문장이 길다({detail}단어)", "i_repeat": "이력서 줄과 겹침({detail})", "i_claim": "{detail}",
        "i_stale": "근거 {id} 가 계획을 만든 뒤 바뀌었거나 없어졌다",
        "i_gap_line": "계획이 프로필로 보일 수 없다고 한 {id} 줄에 답했다",
        "i_missing_line": "{id} 줄에 답하지 않았다", "i_order": "{a} 줄에 {b} 줄보다 늦게 답했다",
        "i_words": "{w}단어, 상한 {lim}", "i_pages": "{p}쪽", "i_over_budget": "분량 상한 {detail} 안에 들도록 뺌",
    },
}


def ui_lang() -> str:
    """Language of the messages: OFFEROWL_LANG, else the locale, else English."""
    v = (os.environ.get("OFFEROWL_LANG") or os.environ.get("LANG") or "en").lower()  # the panel sets OFFEROWL_LANG
    return "ko" if v.startswith("ko") else "en"  # only two languages exist


def t(key: str, **kw) -> str:
    """One message in the user's language (English when a Korean entry is missing)."""
    table = MSG[ui_lang()]  # the chosen language
    return (table.get(key) or MSG["en"][key]).format(**kw)  # fall back to English, then fill the placeholders


def issue(code: str, **kw) -> dict:
    """One problem with a sentence: a stable code for programs and the detail for people."""
    return {"code": code, **kw}  # kw holds id, detail, ...


def issue_text(i: dict) -> str:
    """The message of an issue in the user's language."""
    return t("i_" + i["code"], **{k: v for k, v in i.items() if k != "code"})  # the detail fills the placeholders


# small helpers

def as_list(v) -> list:
    """None or one value as a list."""
    return [] if v is None else (v if isinstance(v, list) else [v])  # profiles are loose about lists


def flat(s: str) -> str:
    """Lowercase without whitespace: a form that survives line breaks and spacing differences."""
    return re.sub(r"\s+", "", s or "").lower()  # used for substring tests


def hangul_share(text: str) -> float:
    """Share of Hangul among the letters of a text."""
    letters = re.findall(r"[A-Za-z가-힣]", text or "")  # letters of both scripts
    return (len(re.findall(r"[가-힣]", text or "")) / len(letters)) if letters else 0.0  # 0 for text without letters


def guess_lang(text: str) -> str:
    """ko when a fifth of the letters are Hangul, else en."""
    return "ko" if hangul_share(text) > 0.2 else "en"  # a few Korean names inside an English text stay below the line


def strip_md(s: str) -> str:
    """A line of Markdown as plain text: emphasis, headings, quotes and links removed."""
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s or "")  # [text](url) becomes text
    s = re.sub(r"[*_`]{1,3}", "", s)  # emphasis and code marks
    s = re.sub(r"==", "", s)  # highlight marks of the resume
    s = re.sub(r"^\s*(?:#{1,6}\s+|>\s*)", "", s)  # heading and quote markers
    return re.sub(r"\s+", " ", s).strip()  # one space between words


def read_json(path, what: str = "JSON file"):
    """A JSON file, or a clear stop when it cannot be read."""
    try:  # an unreadable file must end the run with a message, not a traceback
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))  # the file as data
    except (OSError, ValueError):  # OSError covers a missing path, ValueError covers invalid JSON
        raise SystemExit(t("bad_json", path=path, what=what))  # say which file and what it should be


def write_json(path, data) -> None:
    """Write JSON the way every file here is written: UTF-8, indented, newline at the end."""
    p = pathlib.Path(path)  # target
    p.parent.mkdir(parents=True, exist_ok=True)  # the folder may not exist yet
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # readable diffs


def prompt_text(name: str, **kw) -> str:
    """A prompt template from src/prompts with {{key}} placeholders filled in."""
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")  # the template
    for k, v in kw.items():  # every placeholder given
        text = text.replace("{{" + k + "}}", str(v))  # braces of the JSON examples stay untouched
    return text.strip()  # no stray blank lines at the ends


# the posting

BULLET = re.compile(r"^\s*(?:[-*•·ㆍ▪◦○●■□▶▷✓✔]|\d{1,2}[.)])\s+")  # list markers in English and Korean postings
# Heading words, checked in this order: "Preferred Qualifications" must win over "Qualifications".
HEADINGS = [
    ("preferred", r"preferred(?: qualifications?| skills?| experience| requirements?)?|nice[- ]to[- ]haves?|bonus(?: points)?|a plus|desired(?: skills| qualifications)?|우대(?: ?사항| ?조건| ?요건)?|이런 (?:분|경험)(?:이면|이라면) 더 좋"),
    ("requirement", r"(?:minimum |basic |required |key )?(?:qualifications?|requirements?)|required skills|what (?:you(?:'|’)ll|you will) (?:need|bring)|what we(?:'|’)re looking for|must[- ]haves?|who you are|자격 ?요건|지원 ?자격|필수(?: ?요건| ?자격| ?사항)?|이런 분을 찾"),
    ("duty", r"(?:key |main |primary )?(?:responsibilities|duties)|what (?:you(?:'|’)ll|you will) do|the role|about the role|day[- ]to[- ]day|주요 ?업무|담당 ?업무|하는 일|업무 ?내용|업무 ?소개|합류하면 함께 할 일"),
    ("other", r"job overview|overview|about (?:us|the company|the team|the job)|company(?: overview)?|benefits|perks|compensation|location|how to apply|hiring process|process|전형(?: ?절차)?|복지|혜택|근무 ?(?:조건|지|환경)|회사 ?소개|팀 ?소개|공고 ?개요"),
]
META = re.compile(r"^(?:date posted|requisition id|job id|posted|location|team|department|company|role|title|type|근무지|부서|직무|회사)\s*[:：]\s*(.+)$", re.I)  # "Key: value" lines


def heading_kind(line: str) -> str | None:
    """The section kind a line introduces (duty, requirement, preferred, other), or None when it is not a heading."""
    s = re.sub(r"^[■□▶▷◆◇●○▪•※★☆▣]+\s*", "", strip_md(line).strip())  # a square or star in front of a Korean heading is decoration
    s = s.strip(" \t:：[]【】<>-")  # drop brackets and the trailing colon
    if not s or len(s) > 50 or len(s.split()) > 8:  # headings are short; a long line is text
        return None
    for kind, pat in HEADINGS:  # in priority order, so that "Preferred Qualifications" is not read as "Qualifications"
        if re.fullmatch(pat, s, re.I):  # the whole line must be the heading words
            return kind  # the first matching kind wins, so the order of HEADINGS decides
    return None  # an ordinary line of text


def fenced_body(text: str) -> str:
    """The posting itself: the largest fenced block when the file wraps the posting in one, else the whole text."""
    blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)  # fenced blocks
    return max(blocks, key=len) if blocks else text  # notes around the fence are not part of the posting


def front_matter(text: str) -> tuple[dict, str]:
    """Simple `key: value` front matter between two --- lines, and the text after it."""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)  # the block at the top
    # no front matter block: nothing to read, and the text stays whole
    if not m:
        return {}, text
    meta = {}  # collects the pairs found between the two dash lines
    for ln in m.group(1).splitlines():  # one pair per line
        k, _, v = ln.partition(":")  # split at the first colon only, so a value may contain more colons
        if v.strip():  # a line without a colon or without a value is not a pair
            meta[k.strip().lower()] = v.strip().strip("\"'")  # values may be quoted
    return meta, text[m.end():]  # the posting proper starts after the closing dash line


def clean_item(s: str) -> str:
    """One posting line as plain text without the list marker or trailing punctuation."""
    s = BULLET.sub("", s)  # the bullet
    return strip_md(s).rstrip(" ;,.。")  # emphasis marks and closing punctuation


def parse_company(text: str, meta: dict) -> str:
    """The company name: front matter, then the usual English openings ('At X', 'About X', 'We are X', 'X is a ...'), then a Korean first sentence."""
    if meta.get("company"):  # the person's own statement wins
        return meta["company"]
    name = r"([A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){0,3})"  # up to four capitalised words
    for pat in (r"\bAt\s+" + name + r"\s*(?:\(|[–—-]|,|:|\bwe\b|\bour\b)",  # "At Acme Cloud, we ..."
                r"\bAbout\s+" + name + r"\b", r"\bJoin\s+" + name + r"\b",  # "About Acme", "Join Acme"
                r"\b(?:We are|We(?:'|’)re|Welcome to)\s+" + name + r"\b",  # "We are Acme Cloud"
                r"(?:^|[.\n])\s*" + name + r"\s+(?:is|are)\s+(?:a|an|the)\b"):  # "Acme Cloud is a company that ..."
        m = re.search(pat, text)  # first hit wins
        if m:
            return m.group(1).strip()
    m = re.search(r"(?:^|[.\n])\s*([가-힣A-Za-z0-9&.]{2,20}?)(?:은|는)\s", text)  # '델타페이는 ...' style first sentence
    return m.group(1).strip() if m else ""  # empty when unknown: the letter then names no company


def parse_posting(text: str) -> dict:
    """Split a posting into title, company, overview and the ordered lines (duty, requirement, preferred)."""
    meta, text = front_matter(text)  # front matter first
    body = fenced_body(text)  # then the fenced block, when there is one
    lines = [ln.rstrip() for ln in body.splitlines()]  # trailing spaces are noise; leading ones stay because BULLET reads them
    pre, other, items, where = [], [], [], []  # text before the first heading, overview sections, list lines, place of work
    kind, section = None, ""  # current section kind and its heading text
    chunk = []  # lines of the current list section
    def flush():  # turn the collected lines of one list section into items
        if not chunk:  # nothing was collected since the last heading
            return
        bulleted = any(BULLET.match(c) for c in chunk)  # does this section use list markers?
        cur = None  # the item being built; None until the first list marker is seen
        for c in chunk:  # one pass in order keeps the order of the posting
            if bulleted:  # marked sections need grouping by marker, plain ones do not
                if BULLET.match(c):  # a new item
                    # start an item and register it at once: wrapped lines below grow the same list
                    cur = [clean_item(c)]
                    items.append([kind, section, cur])
                elif cur is not None:  # a wrapped line continues the item above
                    cur.append(strip_md(c))  # extends the list that is already stored in items
            else:  # plain lines: each one is an item
                # each plain line is a whole item
                cur = [clean_item(c)]
                items.append([kind, section, cur])
        chunk.clear()  # the next section starts with an empty chunk
    for raw in lines:  # top to bottom, so the posting's order is kept
        s = raw.strip()  # the stripped copy is for tests, raw is what gets collected
        # blank lines carry nothing and do not close a section
        if not s:
            continue
        k = heading_kind(s)  # a kind name, or None for an ordinary line
        if k:  # a heading closes the section before it
            flush()  # store the items of the section that just ended before the kind changes
            kind, section = k, strip_md(s).strip(" :：[]【】<>")  # later lines belong to this section; its heading text is kept for the location test
            continue
        if kind in ("duty", "requirement", "preferred"):  # list sections only collect lines here; flush() turns them into items
            chunk.append(raw)  # collected now, split into items when the section ends
        elif kind == "other" and re.search(r"location|근무", section, re.I):  # a place-of-work section feeds the location field, not the overview
            where.append(clean_item(raw))  # the place of work
        elif kind == "other":  # any other section is company or team description
            other.append(clean_item(raw))  # goes into the overview that the letter reads for context
        else:  # text before the first heading
            pre.append(strip_md(s))  # the title and the Key: value lines are picked out of this later
    flush()  # the last section has no heading after it to close it
    got, seen = [], set()  # drop duplicate lines, keep the order
    for k, sec, parts in items:  # an item may hold several physical lines when it wrapped
        txt = " ".join(p for p in parts if p).strip()  # a wrapped item becomes one line
        if len(txt) < 3 or flat(txt) in seen:  # too short to be a duty, or the same line under another heading
            continue
        seen.add(flat(txt))  # compared without spacing or case, so a reformatted copy matches too
        got.append({"kind": k, "section": sec, "text": txt})  # the clean record the planner works on
    info = {}  # "Key: value" lines at the top (location, team, ...)
    rest = []  # lines that are not Key: value pairs: the title and the description
    # pick out metadata lines, keep the rest
    for ln in pre:
        m = META.match(ln)
        if m:
            info[ln.split(":")[0].split("：")[0].strip().lower()] = m.group(1).strip()  # the key is cut at an ASCII or full-width colon and lowercased so lookups ignore case
        else:
            rest.append(ln)  # the title and the description are found in what remains
    title = meta.get("role") or meta.get("title") or next((ln for ln in rest if len(ln) <= 90), "")  # the first short line is the title
    prose = [ln for ln in rest if ln != title] + other  # what remains describes the company and the team
    overview = " ".join(prose)[:1800]  # context for the letter; capped to keep prompts small
    company = parse_company(" ".join(prose), meta)  # guessed from the description text, never from the list lines
    return {"title": title, "company": company, "location": meta.get("location") or info.get("location") or info.get("근무지", "") or " ".join(where),  # location: front matter, then a metadata line, then the place-of-work section
            "overview": overview, "items": got}  # items are the duty, requirement and preferred lines in posting order


def llm_posting(text: str, backend: str | None) -> dict | None:
    """Fallback for postings the parser cannot read: ask the model for the lines, keep only lines that really occur in the text."""
    try:  # a model call can fail in several ways and none may stop the plan
        out = llm.run("cover-posting", prompt_text("cover_posting", posting=text[:12000]), want_json=True,  # the posting is cut to keep the prompt small
                      required=("items",), backend=backend,  # an answer without an items key is rejected inside llm.run
                      system="You read job postings. Copy lines exactly. Return only JSON.")  # the system line forbids rewriting: lines are matched against the text afterwards
    except (llm.LLMUnavailable, ValueError):  # no backend, or an answer that never took the required shape
        return None  # no model, or no usable answer: the caller reports it
    hay = flat(text)  # lines must be found in the posting itself
    items = []  # only lines that pass the text check below end up here
    for it in as_list(out.get("items")):  # as_list: the model may return one object instead of a list
        # keep a known kind whose text really occurs in the posting, so the model cannot invent a duty
        if isinstance(it, dict) and it.get("kind") in ("duty", "requirement", "preferred") and flat(str(it.get("text", ""))) in hay:
            items.append({"kind": it["kind"], "section": it["kind"], "text": " ".join(str(it["text"]).split())})  # the fallback has no headings, so the section is the kind itself; whitespace is normalised
    return {"company": str(out.get("company") or ""), "title": str(out.get("role") or ""), "items": items}  # the model's role field becomes the posting title


# evidence units
# A unit is one citable piece of the profile. Project text splits into blocks (a bullet, a paragraph, a table row), so a
# sentence can point at the lines it rests on. An id without a number (alpha-1) means the whole project.

def clean_text(s) -> str:
    """Profile text as one plain line."""
    return re.sub(r"\s+", " ", re.sub(r"==|\*\*", "", str(s or ""))).strip()  # no highlight or bold marks, one space


def split_blocks(md: str) -> list[str]:
    """Markdown body text as blocks: each bullet, table row and paragraph. A heading is not a block of its own: it prefixes the block under it."""
    md = re.sub(r"<!--.*?-->", "", str(md or ""), flags=re.S)  # HTML comments are notes to the person, not facts
    blocks, cur, head = [], [], ""  # finished blocks, the one in progress, and a heading waiting for its text
    in_table = False  # the first row of a table is its header

    def flush():  # closes the block in progress
        nonlocal head  # head is reassigned below, so it cannot be a plain local
        if cur:  # nothing to close when no text was collected
            blocks.append(clean_text((head + ": " if head else "") + " ".join(cur)))  # the block text, led by its heading when one is waiting
            head = ""  # the heading belongs to the first block under it only
            cur.clear()  # emptied in place: split_blocks keeps using the same list object

    for raw in md.splitlines():  # line by line, so tables and bullets are recognised by their shape
        s = raw.strip()  # the trimmed line, for the shape tests below
        if not s or re.fullmatch(r"[-*_]{3,}", s):  # blank line or rule ends a block
            # a blank line or a rule closes the block and ends any table
            flush()
            in_table = False
            continue
        if s.startswith("|"):  # table row
            flush()  # text collected so far is not part of the table row
            if re.fullmatch(r"[|\s:-]+", s):  # the separator row
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]  # outer bars removed first so the ends do not yield empty cells
            if not in_table:  # header row: names the columns, says nothing itself
                in_table = True  # the rows after the header are data
                continue
            blocks.append(clean_text(" : ".join(c for c in cells if c)))  # a data row is one block; empty cells add nothing
            continue
        in_table = False  # any line that is not a row ends the table, so the next table's header is skipped again
        if re.match(r"#{1,6}\s", s):  # heading: waits for the text under it
            flush()  # the paragraph above ends where a heading starts
            head = s.lstrip("# ").strip()  # the # marks are removed so the heading reads as a plain prefix
        elif BULLET.match(raw):  # each bullet is its own block
            flush()  # a bullet never merges into the text before it
            cur.append(BULLET.sub("", raw).strip())  # the marker is removed so the block starts with its words
        else:  # paragraph text or a wrapped line
            cur.append(s)  # wrapped lines of one paragraph join into a single block
    flush()  # the last block has no blank line after it
    return [b for b in blocks if len(b) >= 4]  # drop leftovers such as a lone marker


def role_head(r: dict) -> str:
    """The words that identify a role in every project of it: company, title, department, place and period."""
    career = r.get("career") or {}  # the ledger form keeps names here
    parts = [r.get("org"), r.get("heading"), r.get("title"), r.get("dept"), r.get("place"), r.get("start"), r.get("end"), r.get("period")]  # every field a profile may use for a role, in both the generic and the exported shape
    for lang in ("ko", "en"):  # both spellings of the company and the role
        c = career.get(lang) or {}  # a language entry may be missing
        parts += [c.get("name"), c.get("role"), c.get("dept")]  # name, role and department as written in that language
    parts.append(career.get("title"))  # a title kept on the career entry itself
    seen, out = set(), []  # drop repeats, keep the order
    for p in parts:  # the order of the parts decides the order of the head
        p = clean_text(p)  # None and numbers become plain text, empty when absent
        # skip empty fields and repeats; the first spelling stays, in order
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return " | ".join(out)  # the bar separates fields the way the project heads do


def figure_text(fig) -> list[str]:
    """The sentences hidden in a portfolio figure (steps, rows, caption)."""
    # a project may have no figure, or a malformed one
    if not isinstance(fig, dict):
        return []
    out = []  # collects the sentences hidden in the figure
    # the caption says what the figure shows
    if fig.get("caption"):
        out.append(clean_text(fig["caption"]))
    for row in as_list(fig.get("steps") if fig.get("type") == "flow" else fig.get("rows")):  # flow figures keep their text in steps, the other types in rows
        # a row is a list of cells; anything else has no text to cite
        if isinstance(row, list):
            out.append(clean_text(" : ".join(str(x) for x in row)))
    return [o for o in out if o]  # empty strings are dropped


def units_of(profile: dict, lang: str = "ko") -> dict:
    """All citable units of a profile. Returns {units, index (unit by id), proj (unit ids by project id), heads}."""
    units, index, proj, heads, meta = [], {}, {}, {}, {}  # results; meta holds company, title and period of each project for listings

    def add(uid, text, *, kind, pid=None, head="", resume=False):  # registers one citable unit; skips empty text and ids that are already taken
        text = clean_text(text)  # one plain line; None becomes empty text
        if not text or uid in index:  # nothing to cite, or the id is taken
            return
        u = {"id": uid, "pid": pid, "kind": kind, "head": head, "text": text, "resume": resume}  # resume marks text the resume itself prints, which the letter must not copy
        units.append(u)  # the ordered list, for scanning every unit
        index[uid] = u  # the lookup by id
        # the blocks of a project are listed under its id: an id without a number means the whole project
        if pid:
            proj.setdefault(pid, []).append(uid)

    S = profile.get("summary") or {}  # headline, intro, cards, highlights, layers
    add("summary#headline", S.get("headline"), kind="summary", resume=True)  # the headline is printed on the resume, hence resume=True
    intro = D.pick(S.get("intro"), lang)  # pick takes the language side of a {ko, en} field
    add("summary#intro", intro if isinstance(intro, str) else "", kind="summary", resume=True)  # a missing or non-text intro becomes empty text, which add() ignores
    direction = D.pick(S.get("direction"), lang)  # the direction or position the person states for themselves (not printed on the resume)
    add("summary#direction", direction if isinstance(direction, str) else "", kind="summary")  # citable by the opening and the motivation
    for i, c in enumerate(as_list(D.pick(S.get("cards"), lang)), 1):  # [[title, text], ...]
        # cards in loose profiles may be malformed; only [title, text] lists are used
        if isinstance(c, list):
            add(f"summary#c{i}", " : ".join(str(x) for x in c), kind="summary", resume=True)
    for i, h in enumerate(as_list(D.pick(S.get("highlights"), lang)), 1):  # [{title, where, rows}]
        if isinstance(h, dict):  # a highlight is {title, where, rows}; any other shape has no text to cite
            rows = "; ".join(" : ".join(str(x) for x in r) for r in as_list(h.get("rows")) if isinstance(r, list))  # the cells of a row are joined, and the rows are joined with semicolons
            add(f"summary#h{i}", f"{h.get('title', '')} ({h.get('where', '')}): {rows}", kind="summary", resume=True)  # title and place lead the text so the unit names its own subject
    for i, row in enumerate(as_list(D.pick(S.get("layers"), lang)), 1):  # [[layer, tech, where], ...]
        # a layer row is [layer, tech, where]: its cells become one line
        if isinstance(row, list):
            add(f"summary#l{i}", " | ".join(str(x) for x in row), kind="summary", resume=True)
    for i, c in enumerate(as_list(D.pick(profile.get("competencies"), lang)), 1):  # [[head, text], ...]
        # only the heading and the text (first two cells) of a competency are citable
        if isinstance(c, list) and c:
            add(f"competencies#{i}", ": ".join(clean_text(x) for x in c[:2]), kind="competency", resume=True)
    for i, a in enumerate(as_list(D.pick(profile.get("about"), lang)), 1):  # [[title, paragraphs], ...]
        # [title, paragraphs]: the paragraphs are cited, the title is not
        if isinstance(a, list) and len(a) > 1:
            add(f"about#{i}", " ".join(clean_text(x) for x in as_list(a[1])), kind="statement", resume=True)
    mot = D.pick(profile.get("motivation"), lang)  # the motivation text in the letter's language
    for i, m in enumerate(as_list(mot), 1):  # a single string or a list of them
        add(f"motivation#{i}", m if isinstance(m, str) else "", kind="statement", resume=True)  # a non-text entry becomes empty text, which add() ignores

    for ri, r in enumerate(as_list(profile.get("roles")), 1):  # ri numbers a role that has neither key nor org
        rk = clean_text(r.get("key") or r.get("org") or f"role{ri}").replace(" ", "_")  # role key
        head = role_head(r)  # the words that identify the role, attached to each of its units
        add(f"role:{rk}", head, kind="role", head=head)  # the role is a unit itself, so a sentence can cite who the person worked for
        for ci, c in enumerate(as_list(r.get("context")), 1):  # business overview and similar sections of the role
            for bi, b in enumerate(split_blocks(str(c.get("body_md", ""))), 1):  # each bullet or paragraph is its own citable block
                add(f"{rk}#c{ci}.{bi}", (clean_text(c.get("title")) + ": " if c.get("title") else "") + b, kind="context", head=head)  # the section title leads the block so the unit says which section it came from
        for pi, p in enumerate(as_list(r.get("projects")), 1):  # a project without an id gets role key plus position
            pid = str(p.get("id") or f"{rk}-{pi}")  # project id
            ptitle, pperiod = D.pick(p.get("title"), lang), D.pick(p.get("period"), lang)  # a drafted profile holds {ko, en} pairs; the letter's language is read
            phead = head + " | " + clean_text(ptitle) + (" | " + clean_text(pperiod) if pperiod else "")  # role head, project title and period: what the model sees above the blocks of a project
            heads[pid] = phead  # kept for prompts and for unit_text()
            # company, title and period of each project, for the candidate list shown to the model
            meta[pid] = {"org": clean_text(r.get("org") or (r.get("career") or {}).get("en", {}).get("name") or r.get("heading") or rk),
                         "title": clean_text(ptitle), "period": clean_text(pperiod)}
            n = 0  # block counter
            # adds the next numbered block of this project
            def put(text, resume=False):
                nonlocal n  # n is rebound below, so it is declared nonlocal
                # empty text is skipped before it takes a number
                if clean_text(text):
                    n += 1
                    add(f"{pid}#{n}", text, kind="project", pid=pid, head=phead, resume=resume)
            put(D.pick(p.get("summary"), lang), resume=True)  # the resume prints the summary
            for q in as_list(D.pick(p.get("points"), lang)):  # portfolio bullets are not on the resume
                put(D.pick(q, lang))  # each bullet is a block of its own, so a sentence can point at one
            put(D.pick(p.get("notes"), lang))  # the free notes of a project; the resume flag stays False like the bullets
            for b in split_blocks(D.pick(p.get("body_md", ""), lang)):  # the ledger form keeps the ledger text here
                put(b)  # a body of several blocks becomes several units
            # text inside a figure is citable evidence like any other block
            for f in figure_text(p.get("figure")):
                put(f)
            if pid not in proj:  # a project without text still has its title as evidence
                put(ptitle)  # the title alone still names the project and gives it something to cite

    for s in as_list(profile.get("skills")):  # category: items
        # a skills row needs a category; spaces in the id become underscores so an id has no blanks
        if isinstance(s, dict) and s.get("category"):
            add("skills#" + clean_text(s["category"]).replace(" ", "_"), f"{s['category']}: {', '.join(map(str, as_list(s.get('items'))))}", kind="skills")
    for i, s in enumerate(as_list(profile.get("sections")), 1):  # certificates, awards, papers
        # a section is a list of items (certificates, awards) or a text body (papers)
        if isinstance(s, dict):
            body = ", ".join(map(str, as_list(s.get("items")))) or " ".join(split_blocks(s.get("body_md", "")))  # the list items when present, else the text blocks of the body
            add(f"sections#{i}", f"{s.get('title', '')}: {body}", kind="section")
    for i, e in enumerate(as_list(profile.get("education")), 1):  # the plain and the exported shapes
        if isinstance(e, dict):  # a stray string in the list has no school or title fields
            loc = e.get(lang) or e.get("ko") or {}  # the letter's language first, Korean as the fallback
            text = f"{loc.get('title', '')} {loc.get('sub', '')}" if isinstance(loc, dict) and loc else " ".join(str(e.get(k, "")) for k in ("school", "major", "degree"))  # exported shape: title and sub of the language; generic shape: school, major and degree
            add(f"education#{i}", text, kind="education")  # numbered like the sections above
    return {"units": units, "index": index, "proj": proj, "heads": heads, "meta": meta}  # the units in order, plus the lookups that the other functions use


def unit_text(U: dict, uid: str) -> str:
    """The evidence text behind one id: a block, or all blocks of a project, with the words that name its company and role."""
    if uid in U["index"]:  # one unit
        # the head comes first, so the evidence names its company and role
        u = U["index"][uid]
        return (u["head"] + "\n" + u["text"]).strip()
    if uid in U["proj"]:  # a whole project
        return (U["heads"][uid] + "\n" + "\n".join(U["index"][x]["text"] for x in U["proj"][uid])).strip()  # the project head, then every block: the whole project is the evidence
    return ""  # unknown id: the caller reports it


def known_id(U: dict, uid: str) -> bool:
    """Is this a block id or a project id of the profile?"""
    return uid in U["index"] or uid in U["proj"]  # a project id is as good as a block id


def project_of(U: dict, uid: str) -> str:
    """The project id of a block id (or the id itself)."""
    return (U["index"][uid]["pid"] or uid) if uid in U["index"] else uid  # a loose unit keeps its own id; an unknown id passes through unchanged


def evidence_hash(U: dict, ids) -> str:
    """Fingerprint of the evidence behind some ids, to tell later that the profile changed under a plan."""
    h = hashlib.sha256()  # a fixed-size fingerprint of text that may be long
    for uid in sorted(set(ids)):  # order must not matter
        h.update(uid.encode() + b"\0" + unit_text(U, uid).encode() + b"\0")  # NUL bytes keep id and text from running together, so ('a', 'bc') differs from ('ab', 'c')
    return h.hexdigest()[:16]  # sixteen hex digits are plenty to notice a change and stay short in plan.json


# word matching (the part of planning that needs no model)

# words that never tell one posting line from another; terms() and relevance() skip them
STOP_EN = set("""a an the and or of to in on for with by at from as is are was were be been being this that these those it its into over via per vs not no
we you your our their they them i my me his her he she who whom which what when where how than then also can will would should may might must
do does did done have has had having more most other such only own same so too very just about above after again against all any because
before below between both during each few further here if once out off up down under until while ability experience experiences strong knowledge
understanding work working team teams familiarity years year proven expertise skills skill excellent good including related field degree bachelor
bachelors master preferred required plus etc new using use used able like well across within ensure including include includes etc one two three
looking join help helps provide provides providing role position candidate candidates responsible responsibilities responsibility""".split())  # posting boilerplate
# English words and the Korean stems that mean the same, so that an English posting can find Korean evidence and the reverse.
BRIDGE = {
    "automation": "자동화", "automate": "자동화", "automated": "자동화", "dashboard": "대시보드", "dashboards": "대시보드",
    "monitoring": "모니터링 감시 관측", "observability": "관측 모니터링", "alert": "알림 경보", "alerts": "알림 경보", "alerting": "알림 경보",
    "metric": "지표 메트릭", "metrics": "지표 메트릭", "incident": "장애 사고", "incidents": "장애 사고", "outage": "장애", "failure": "장애",
    "failures": "장애", "troubleshoot": "원인 분석 장애", "troubleshooting": "원인 분석 장애", "cause": "원인", "oncall": "온콜 당직 당번",
    "on-call": "온콜 당직 당번", "rotation": "당번 교대", "customer": "고객 고객사", "customers": "고객 고객사", "client": "고객 고객사",
    "support": "지원 문의", "collaborate": "협업 협력", "collaboration": "협업 협력", "pipeline": "파이프라인", "pipelines": "파이프라인",
    "deploy": "배포", "deployment": "배포", "deployments": "배포", "release": "릴리스 배포", "rollback": "원복 롤백 되돌",
    "infrastructure": "인프라", "cluster": "클러스터", "clusters": "클러스터", "storage": "스토리지", "network": "네트워크", "networking": "네트워크",
    "security": "보안", "compliance": "규제 인증 감사", "audit": "감사", "scheduler": "스케줄러", "container": "컨테이너", "containers": "컨테이너",
    "virtualization": "가상화", "design": "설계", "designed": "설계", "architecture": "아키텍처 설계", "performance": "성능", "optimization": "최적화 개선",
    "latency": "지연", "test": "시험 테스트 검증", "testing": "시험 테스트 검증", "documentation": "문서 문서화", "document": "문서 문서화",
    "migration": "이관 마이그레이션", "migrate": "이관 마이그레이션", "availability": "가용성", "reliability": "신뢰성 안정", "recovery": "복구",
    "payment": "결제", "payments": "결제", "settlement": "정산", "order": "주문", "orders": "주문", "event": "이벤트", "events": "이벤트",
    "cache": "캐시", "caching": "캐시", "database": "데이터베이스", "backend": "백엔드", "service": "서비스", "services": "서비스",
    "platform": "플랫폼", "mentor": "교육 양성", "training": "교육 학습", "code": "코드", "script": "스크립트", "scripting": "스크립트",
    "review": "검토", "approval": "승인", "retry": "재시도", "idempotent": "멱등", "idempotency": "멱등", "queue": "큐", "stream": "스트림",
    "operations": "운영", "operation": "운영", "maintenance": "유지보수 점검", "capacity": "용량 증설", "scalability": "확장", "incident-response": "장애 대응",
}
KO_BRIDGE = collections.defaultdict(set)  # Korean stem to English words, the reverse of BRIDGE
# filled once at import, so a Korean stem finds its English words
for _en, _ko in BRIDGE.items():
    for _k in _ko.split():
        KO_BRIDGE[_k].add(_en)
# Well-known tool and product names (lowercase). A posting line that names one the profile lacks marks a gap; the list is general
# knowledge about software, not about any person.
TOOLS = set("""python go golang java rust c++ c# javascript typescript bash perl ruby php sql ansible terraform puppet chef saltstack pulumi jenkins gitlab github
bitbucket argo argocd helm docker podman kubernetes k8s openshift istio envoy nginx haproxy prometheus grafana loki thanos elk elasticsearch kibana splunk
datadog newrelic opentelemetry kafka rabbitmq redis postgresql postgres mysql mariadb mongodb oracle cassandra aws azure gcp linux unix ubuntu centos rhel slurm
mpi ucx nccl rccl cuda rocm hip openacc gcc clang llvm intel aocc pgi nvidia amd infiniband roce lustre gpfs ceph nfs vmware kvm vault consul nomad git svn jira
confluence pagerduty rhcsa rhce cka ckad flink spark hadoop hive airflow dbt snowflake bigquery tensorflow pytorch rust swift kotlin scala""".split())
# How the common tools are written in Korean text, so that a Korean profile that says 리눅스 counts as naming Linux.
TRANSLIT = {"linux": "리눅스", "unix": "유닉스", "kubernetes": "쿠버네티스", "docker": "도커", "python": "파이썬", "java": "자바", "ansible": "앤서블",
            "jenkins": "젠킨스", "terraform": "테라폼", "git": "깃", "github": "깃허브", "gitlab": "깃랩", "prometheus": "프로메테우스",
            "grafana": "그라파나", "kafka": "카프카", "redis": "레디스", "mysql": "마이에스큐엘", "nginx": "엔진엑스", "aws": "에이더블유에스",
            "azure": "애저", "javascript": "자바스크립트", "typescript": "타입스크립트", "elasticsearch": "엘라스틱서치", "kibana": "키바나",
            "hadoop": "하둡", "spark": "스파크", "airflow": "에어플로", "helm": "헬름", "argocd": "아르고", "openshift": "오픈시프트",
            "ethernet": "이더넷", "infiniband": "인피니밴드", "nvidia": "엔비디아", "intel": "인텔", "oracle": "오라클", "google": "구글",
            "microsoft": "마이크로소프트", "naver": "네이버", "samsung": "삼성", "windows": "윈도우", "android": "안드로이드", "excel": "엑셀"}
HANGUL_STEM = re.compile(r"[가-힣]{2,}")  # a Korean word
LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:[./-][A-Za-z0-9+#]+)*")  # a Latin word, kept whole when dotted or hyphenated


def terms(text: str) -> list[str]:
    """Search terms of a text: Latin words, Korean stems and Korean syllable pairs (a stem changes endings, a pair survives them)."""
    out = []  # Latin terms stay plain, Korean ones carry the prefix k: or b:
    for m in LATIN_TOKEN.finditer(text or ""):  # dotted and hyphenated words are single tokens here and are split below
        w = m.group(0).lower()  # case does not matter for matching
        for p in [w] + [x for x in re.split(r"[./-]", w) if x and x != w]:  # ci/cd gives ci/cd, ci and cd
            # single letters and boilerplate words would match almost every unit
            if len(p) > 1 and p not in STOP_EN:
                out.append(p)
    for w in HANGUL_STEM.findall(text or ""):
        stem = F.JOSA.sub("", w) or w  # strip the particle at the end of a word
        out.append("k:" + stem)  # the whole stem, prefixed so it cannot collide with a Latin term
        out += ["b:" + stem[i:i + 2] for i in range(len(stem) - 1)]  # overlapping syllable pairs
    return out  # repeats stay in the list on purpose: term frequency counts them


def bridge_terms(term: str) -> list[str]:
    """Terms of the other language that mean the same as this one."""
    if term in BRIDGE:  # English word to Korean stems and their pairs
        return [x for k in BRIDGE[term].split() for x in ["k:" + k] + ["b:" + k[i:i + 2] for i in range(len(k) - 1)]]  # each Korean stem whole and as syllable pairs, the same forms that terms() produces
    if term.startswith("k:") and term[2:] in KO_BRIDGE:  # Korean stem to English words
        return sorted(KO_BRIDGE[term[2:]])  # sorted so the query order is stable from run to run
    return []  # no twin is known


class Lex:
    """BM25 over the evidence units (word matching with a small English-Korean bridge)."""

    def __init__(self, U: dict):  # everything BM25 needs is computed once, up front
        self.U = U  # the units
        self.tf = {u["id"]: collections.Counter(terms(u["head"] + " " + u["text"])) for u in U["units"]}  # term counts per unit
        self.len = {k: sum(v.values()) for k, v in self.tf.items()}  # unit lengths
        self.avg = (sum(self.len.values()) / len(self.len)) if self.len else 1.0  # average length
        self.df = collections.Counter(t for c in self.tf.values() for t in c)  # in how many units a term occurs
        self.n = len(self.tf)  # number of units

    def idf(self, t: str) -> float:
        """Rarer terms weigh more."""
        return math.log(1 + (self.n - self.df.get(t, 0) + 0.5) / (self.df.get(t, 0) + 0.5))  # the +1 inside the log keeps idf above zero even for a term that is in most units

    def query(self, text: str) -> list[str]:
        """Terms of a posting line, plus the bridged terms of the other language."""
        q = terms(text)  # the posting line's own terms come first, the bridged ones follow
        return list(dict.fromkeys(q + [b for t_ in q for b in bridge_terms(t_)]))  # unique, in order

    def score(self, q: list[str], uid: str) -> float:
        """BM25 score of one unit for a query."""
        tf, ln, s = self.tf[uid], self.len[uid], 0.0  # term counts and length of this unit, and the running score
        # a term the unit lacks adds nothing; query terms are unique, so none counts twice
        for t_ in q:
            f = tf.get(t_, 0)
            if f:
                s += self.idf(t_) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * ln / self.avg))  # k1 = 1.2, b = 0.75
        return s  # 0.0 when no query term occurs in the unit

    def rank(self, text: str, k: int = 6) -> list[tuple[str, float]]:
        """Projects (or loose units) ranked for a text: best block plus a quarter of the next two."""
        q = self.query(text)  # the line's terms plus their twins in the other language
        best = collections.defaultdict(list)  # project (or unit) id to block scores
        # score every unit; those with no shared term stay out
        for uid in self.tf:
            sc = self.score(q, uid)
            if sc > 0:
                best[self.U["index"][uid]["pid"] or uid].append(sc)  # units of one project pool their scores; a loose unit stands alone
        ranked = [(pid, sorted(v, reverse=True)[0] + 0.25 * sum(sorted(v, reverse=True)[1:3])) for pid, v in best.items()]  # the best block counts in full and the next two a quarter each, so a project with support edges out a lone match of equal strength
        return sorted(ranked, key=lambda x: -x[1])[:k]  # highest score first; k keeps the prompt short

    def keywords(self, pid: str, n: int = 14) -> list[str]:
        """The most distinctive words of a project's text (tf x idf; the company and role words of its head are left out): tool names and
        technical nouns that its opening words may not show."""
        tf = collections.Counter()  # term counts over the whole project text
        for uid in self.U["proj"].get(pid, [pid]):  # a loose unit is its own one-block project
            tf.update(terms(self.U["index"][uid]["text"]))  # the text only, not the head, so company and role words stay out
        scored = [(c * self.idf(t_), t_) for t_, c in tf.items() if not t_.startswith("b:") and len(t_) > 2]  # tf x idf; syllable pairs and very short terms make poor keywords
        return [t_[2:] if t_.startswith("k:") else t_ for _, t_ in sorted(scored, reverse=True)[:n]]  # the k: prefix is dropped because the model reads plain words

    def shared_terms(self, text: str, pid: str, n: int = 3) -> list[str]:
        """The words (bridged ones included) that link a posting line to a project's text, rarest first."""
        # all terms of the project text, to test the terms of the line against
        have = set()
        for uid in self.U["proj"].get(pid, [pid]):
            have |= set(terms(self.U["index"][uid]["text"]))
        hit = [t_ for t_ in self.query(text) if t_ in have and not t_.startswith("b:")]  # terms of the line that the project also has; syllable pairs are skipped as unreadable
        return [t_[2:] if t_.startswith("k:") else t_ for t_ in sorted(hit, key=lambda x: -self.idf(x))[:n]]  # rarest first, since a rare shared word says more than a common one; prefix dropped for reading

    def coverage(self, text: str, uids) -> float:
        """Weighted share of the line's terms that the given evidence shows (a term counts when its bridged twin is shown)."""
        base = [x for x in terms(text) if not x.startswith("b:")]  # whole words, not syllable pairs
        # a line without whole words (only filler) has nothing to weigh
        if not base:
            return 0.0
        # terms of every block of every cited project or loose unit
        have = set()
        for pid in uids:
            for uid in (self.U["proj"].get(pid) or [pid]):
                if uid in self.tf:  # an id that is not a unit has no terms
                    have |= set(self.tf[uid])  # union over all cited blocks
        got = sum(self.idf(x) for x in base if x in have or any(b in have for b in bridge_terms(x)))  # a term counts when the evidence has it or its twin in the other language
        return got / sum(self.idf(x) for x in base)  # weighted by rarity, so missing a rare tool costs more than missing a common word


# names, numbers and tools in a sentence

WORD = LATIN_TOKEN  # the tokens the name rules look at
# languages, months and weekdays are written with capitals but name no tool
COMMON_CAPS = set("""i english korean chinese japanese vietnamese indian american european asian january february march april may june july august
september october november december monday tuesday wednesday thursday friday saturday sunday""".split())  # capitalised words that are not names of things


def name_like(part: str, initial: bool) -> bool:
    """Does a word look like the name of a tool, product, company or place (and not an ordinary word)?"""
    if len(part) < 2:  # too short to be a name
        return False  # a single letter (I, A) is not a name
    if part.isupper():  # whole-word capitals are acronyms or product names
        return True  # AI, AWS, SQL
    if re.search(r"[a-z][A-Z]", part) or re.search(r"\d", part) or re.search(r"[+#]", part):  # inner capitals, digits, + and # are marks of product names
        return True  # gRPC, PostgreSQL, S3, C++
    return part[0].isupper() and not initial  # a capitalised word inside a sentence


def name_parts(text: str):
    """Words of a sentence as (part, initial) pairs; compounds split at / . and -; apostrophes dropped."""
    clean = re.sub(r"[’']s\b", "", text)  # possessives
    clean = re.sub(r"[’']\w+", "", clean)  # other contractions
    for sent in re.split(r"(?<=[.!?:;])\s+", clean):  # sentence starts are capitalised without meaning
        for i, m in enumerate(WORD.finditer(sent)):  # the position tells whether a capital only marks a sentence start
            for j, part in enumerate(p for p in re.split(r"[./-]", m.group(0)) if p):  # pieces of a compound such as Node.js are judged one by one
                yield part, (i == 0 and j == 0)  # only the very first piece of a sentence is flagged as initial


def strict_name(part: str) -> bool:
    """A word that is a name wherever it stands: upper-case, mixed-case, with a digit or with + or #."""
    return len(part) >= 2 and (part.isupper() or bool(re.search(r"[a-z][A-Z]|\d|[+#]", part)))  # no position rule here: a vocabulary word must be a name wherever it stands


# Tool names that are also everyday words: written in lowercase or at the start of a sentence they are not taken for the tool.
ORDINARY_TOOLS = {"go", "swift", "spark", "chef", "salt", "vault", "consul", "nomad", "puppet", "ruby", "flask", "rust", "ray", "dask", "pipe", "stack",
                  "rest", "put", "get", "post", "head", "patch", "delete", "ring", "mesh", "fold", "core", "node", "pod", "job", "jobs"}


def tool_vocab(U: dict) -> dict:
    """Words that the profile uses as tool or product names (lowercase), each with the first unit ids that hold it: the unmistakable names (AWS,
    PostgreSQL, S3) of project, context and section text, and every single-word item of a skills row (Kubernetes, Terraform). Category
    names of skills rows, words inside longer items ('Web' of 'Amazon Web Services') and the labels of summary rows (CHALLENGE, RESULT)
    are left out, so that ordinary words are never taken for tools. A sentence may not use a vocabulary word that its evidence lacks."""
    vocab = {}  # lowercase word to the first two unit ids that hold it

    def add(low, uid):  # records one candidate word, with its source for the hint under a rejected name
        if re.match(r"[a-z][a-z0-9+#./-]+$", low) and low not in F.COMMON_EN and low not in ORDINARY_TOOLS:  # starts with a letter, not an everyday word
            if len(vocab.setdefault(low, [])) < 2 and uid not in vocab[low]:  # two sources are enough for a hint and keep the vocabulary small
                vocab[low].append(uid)  # remember where the word lives

    for u in U["units"]:  # every unit of the profile is scanned once
        if u["kind"] == "skills":  # skills rows list tools on purpose, so they get the generous rule
            for item in u["text"].split(":", 1)[-1].split(","):  # the items after the category name
                item = re.sub(r"\(([^)]*)\)", r" \1 ", item).strip()  # Amazon Web Services(AWS) becomes Amazon Web Services AWS
                words = item.split()  # a multi-word item is a tool only through its strict words below
                if len(words) == 1:  # a single-word item is a tool by itself
                    for w in re.split(r"[/]", words[0]):  # an item such as CI/CD names two tools
                        add(w.lower(), u["id"])  # sentences are compared in lowercase
                for w in words:  # a longer item still contributes its unmistakable words
                    if strict_name(w):  # but not its ordinary words, such as Web in Amazon Web Services
                        add(w.lower(), u["id"])  # AWS and similar names join the vocabulary
        elif u["kind"] in ("project", "context", "section"):  # prose units give only names that cannot be ordinary words
            for part, _ in name_parts(u["head"] + " " + u["text"]):  # the head (company, role) and the text are scanned alike
                if strict_name(part):  # a capital at the start of a word proves nothing, so only strict names pass
                    add(part.lower(), u["id"])  # same lowercase key as the skills rows use
    return vocab  # name_issues demands evidence for every word in here


def name_locations(U: dict) -> dict:
    """Every name-like word of the profile (lowercase), each with the first unit ids that hold it. Used only to tell a sentence where its word lives."""
    out = {}  # lowercase word to the first two unit ids that hold it
    for u in U["units"]:  # all units, not only the cited ones: the hint must point to wherever the word lives
        for part, _ in name_parts(u["head"] + " " + u["text"]):  # same scan as the vocabulary, but looser
            low = part.lower()  # sentence words are compared in lowercase
            if name_like(part, False) and low not in F.COMMON_EN and len(out.setdefault(low, [])) < 2 and u["id"] not in out[low]:  # initial=False, so a capital counts even at a sentence start; two sources at most
                out[low].append(u["id"])  # the hint names these units
    return out  # only the hint under a rejected name reads this


# spelled-out amounts count as numbers, like digits
EN_COUNT = re.compile(r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
                      r"forty|fifty|sixty|seventy|eighty|ninety|hundred|hundreds|thousand|thousands|million|millions|billion|dozen|dozens|double|doubled|triple|"
                      r"tripled|twice|half|zero)\b", re.I)  # spelled-out amounts (one stays: it is also a pronoun)
KO_COUNT = re.compile(r"(?<![가-힣])(?:두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무|수십|수백|수천|수만|십여|백여|천여)"
                      r"(?:\s+(?:개|곳|번|가지|명|대|건|차례|단계|배|달|주|해|분기|종|장|쪽)|(?:개|곳|번|가지|명|건|차례|단계))")  # spelled-out Korean amounts; the counter must be a word of its own, so 차세대, 세대, 열대 and 세종 are not counts (한 stays out: it is the everyday 'a' as often as 'one')


def number_issues(text: str, evidence: str, policy: str) -> list[dict]:
    """Numbers in a sentence. Policy forbid: none at all. Policy evidence: only numbers the evidence also states."""
    bad = []  # issues in the order a person reads them: digits, then counted words
    nums = {(v, k) for v, k in F.number_tokens(text)}  # standalone numbers with their kind (%, x)
    words = F.number_words(text) | {w.lower() for w in EN_COUNT.findall(text)} | {re.sub(r"\s+", "", w) for w in KO_COUNT.findall(text)}  # amounts written in words are numbers too, in both languages
    if policy == "forbid":  # strict style: any number at all is a problem
        if nums:  # digits and counted words are reported separately
            bad.append(issue("number", detail=", ".join(f"{v:g}{k}" for v, k in sorted(nums)[:5])))  # at most five are shown and sorted, so the message is stable
        if words:  # counted words have their own code
            bad.append(issue("number_word", detail=", ".join(sorted(words)[:5])))  # same limit of five
        return bad  # nothing to compare against when numbers are forbidden
    ev_nums, ev_words = F.number_tokens(evidence), F.number_words(evidence) | {w.lower() for w in EN_COUNT.findall(evidence)}  # what the evidence states
    extra = sorted(x for x in nums if x not in ev_nums)  # value and kind must both match, so 50 percent is not 50
    if extra:  # the letter states a figure that the cited evidence does not
        bad.append(issue("number", detail=", ".join(f"{v:g}{k}" for v, k in extra[:5])))  # limit of five, as above
    extra_w = sorted(w for w in words if w not in ev_words and w not in {re.sub(r"\s+", "", x) for x in KO_COUNT.findall(evidence)})  # Korean counts are compared without spaces, English ones in lowercase
    if extra_w:  # a counted word the evidence never uses
        bad.append(issue("number_word", detail=", ".join(extra_w[:5])))  # limit of five, as above
    return bad  # empty when every number is backed by the evidence


def allowed_token(low: str, pool: set, allow: set, evidence_flat: str = "") -> bool:
    """Is a lowercase word allowed: in the cited evidence (plural tolerant, or spelled in Korean), a connecting word, or an allowed name?"""
    # allowed when the evidence has it (plural tolerant), it is a connecting word, a non-name capital, an allowed name, or a Korean spelling found in the evidence
    return (F.plural_ok(low, pool) or low in F.COMMON_EN or low in COMMON_CAPS or low in allow
            or bool(TRANSLIT.get(low) and TRANSLIT[low] in evidence_flat))


def name_issues(text: str, evidence: str, allow: set, vocab: dict, where: dict, lang: str) -> list[dict]:
    """Names and tools in a sentence that the cited evidence does not hold.

    English: capitalised, upper-case and mixed-case words must occur in the evidence, and so must any word that the profile
    uses as a tool name elsewhere. Korean: every Latin word and every organisation name must occur."""
    pool = F.latin_tokens(evidence)  # lowercase Latin words of the evidence
    ev_flat = re.sub(r"\s+", "", evidence)  # for Korean spellings of tools
    bad, seen = [], set()  # seen keeps the report to one issue per word
    if lang == "en":  # English letters judge capitals; Korean letters judge every Latin word
        for part, initial in name_parts(text):  # initial says whether a capital only marks the start of a sentence
            low = part.lower()  # the evidence pool holds lowercase words
            if low in seen or not (name_like(part, initial) or low in vocab):  # an ordinary word needs no evidence
                continue  # already reported, or an ordinary word: nothing to check
            if not allowed_token(low, pool, allow, ev_flat):  # a name that no cited text holds is what this check exists for
                seen.add(low)  # report each word once even when it is used twice
                hint = where.get(low) or vocab.get(low)  # point to the units that do hold the word, so the person can cite them
                bad.append(issue("name", detail=part + (f" (see {', '.join(hint)})" if hint else "")))  # detail is the word as written plus, when known, where it lives
    else:  # Korean letter: any Latin word must come from the evidence
        new = sorted(w for w in F.latin_tokens(text) if not F.plural_ok(w, pool) and w not in allow)  # plural tolerant against the evidence pool; allowed names are exempt
        if new:  # only the first five words are listed
            bad.append(issue("name", detail=", ".join(w + (f" (see {', '.join(where[w])})" if where.get(w) else "") for w in new[:5])))  # each word carries its home units when known
        ev_flat = flat(evidence)  # organisations are compared as lowercase text without spaces
        orgs = sorted(o for o in F.korean_orgs(text) if o not in ev_flat and flat(o) not in allow)  # organisation-like words (bank, pay, university endings) that neither the evidence nor the posting allows
        if orgs:  # separate code, since the fix is different from a missing tool
            bad.append(issue("org", detail=", ".join(orgs[:5])))  # first five only
    return bad  # empty means every name and organisation is backed


# the plan

def line_ids(items: list[dict]) -> list[dict]:
    """Number the posting lines: d1.. for duties, q1.. for requirements, p1.. for preferred ones; `order` follows the posting."""
    count = collections.Counter()  # running number per kind
    out = []  # plan lines in posting order
    for order, it in enumerate(items, 1):  # order is the position in the posting, counted from 1
        pre = {"duty": "d", "requirement": "q", "preferred": "p"}[it["kind"]]  # d for duty, q for requirement, p for preferred
        count[pre] += 1  # numbering restarts for every kind
        out.append({"id": f"{pre}{count[pre]}", "order": order, **it})  # id is for citing a line, order for checking the sequence of answers
    return out  # the lines are copied from the parsed items, not edited in place


def mentions(text: str, term: str) -> bool:
    """Does a text name the term? Latin terms match whole words in any case (or their Korean spelling); Korean terms match as text."""
    if re.search(r"[가-힣]", term):  # Korean has no word boundaries, so compare as text
        return flat(term) in flat(text)  # spaces and case must not hide a hit
    if re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.I):  # whole words only: Rust must not hit trusted
        return True  # the English spelling is present
    ko = TRANSLIT.get(term.lower())  # the usual Korean spelling of a known tool, if there is one
    return bool(ko and ko in re.sub(r"\s+", "", text))  # 리눅스 names Linux


def clean_terms(declared) -> list[str]:
    """Missing-tool declarations as tool words: 'AMD (AOCC' gives AMD and AOCC, 'UNIX/Linux' gives UNIX and Linux, 'Bachelor's Degree' gives nothing.
    A Korean term stays whole. Only words on the known-tool list or written like a product name survive."""
    out = []  # clean tool words, no repeats
    for x in declared:  # the model declared these, so they are untrusted text
        x = str(x).strip()  # the model may return something that is not a string
        if re.search(r"[가-힣]", x):  # a Korean term is kept as it is
            if len(x) >= 3 and x not in out:  # two characters are too vague to count as a tool
                out.append(x)  # the Korean term is kept as written
            continue  # no Latin splitting for Korean terms
        for m in LATIN_TOKEN.finditer(x):  # a declaration such as AMD (AOCC holds two Latin words
            for w in [m.group(0)] + re.split(r"[./-]", m.group(0)):  # the token itself and its pieces, so UNIX/Linux gives UNIX, Linux and the whole
                low = w.lower()  # the known-tool list is lowercase
                if w and len(low) > 2 and (low in TOOLS or strict_name(w)) and w not in out:  # only known tools or product-looking words survive; Bachelor fails both tests
                    out.append(w)  # keep the spelling the model used
    return out  # may be empty when the model declared nothing useful


def computed_missing(lex: Lex, text: str, uids) -> list[str]:
    """Tools the line names (from the known-tool list, or written like a product name) that the given evidence does not show."""
    have = set()  # terms that the given evidence contains
    for pid in uids:  # uids may be project ids or loose unit ids
        for uid in (lex.U["proj"].get(pid) or [pid]):  # a project expands to its blocks, a loose id stands for itself
            if uid in lex.tf:  # only indexed units have term counts
                have |= set(lex.tf[uid])  # the terms of this block
    have_text = " ".join(unit_text(lex.U, e) for e in uids)  # for the Korean spellings
    out = []  # tools the line names and the evidence lacks
    for m in LATIN_TOKEN.finditer(text):  # every Latin token of the posting line
        for w in dict.fromkeys(re.split(r"[./-]", m.group(0)) if re.search(r"[./-]", m.group(0)) else [m.group(0)]):  # UNIX/Linux gives UNIX and Linux
            low = w.lower()  # both the tool list and the term index are lowercase
            tool = low in TOOLS or bool(re.search(r"[a-z][A-Z]", w) or re.search(r"\d", w))  # on the tool list, or written like a product
            if tool and len(low) > 2 and low not in have and w not in out and not mentions(have_text, w):  # mentions() also finds a Korean spelling, which the term index misses
                out.append(w)  # keep the posting's own spelling
    return out  # gaps for this line, to be filtered against the whole profile later


def missing_in(lex: Lex, text: str, ev, declared) -> list[str]:
    """Tools a line names that the chosen evidence does not show: the model's list and the known-tool list, minus what the evidence has."""
    have_text = " ".join(unit_text(lex.U, e) for e in ev)  # the evidence as one string
    return [x for x in dict.fromkeys(clean_terms(declared) + computed_missing(lex, text, ev)) if not mentions(have_text, x)]  # the model's list first, then the computed one; repeats go, order stays


def holder_of(lex: Lex, term: str, ev) -> str | None:
    """An entry that names the term and is not chosen yet: a skills row first, then the project block that scores best."""
    best, best_sc = None, -1.0  # no entry found yet
    for u in lex.U["units"]:  # search the whole profile, not only the entries already chosen
        pid = u["pid"] or u["id"]  # a unit outside any project is its own entry
        if pid in ev or not mentions(u["text"], term):  # skip entries already chosen and entries that do not name the tool
            continue  # nothing to rank here
        sc = {"skills": 3.0, "project": 2.0, "context": 1.5}.get(u["kind"], 1.0) - (0.5 if u["resume"] else 0.0)  # a skills row names tools plainly
        if sc > best_sc:  # strictly greater, so the first of equal scores wins
            best, best_sc = pid, sc  # remember the best holder so far
    return best  # None when no other entry names the term


def valid_ids(U: dict, raw) -> list[str]:
    """Keep the ids that exist, as project ids; drop the rest."""
    out = []  # project ids that exist
    for x in as_list(raw):  # the model may return one id or a list
        x = str(x).strip()  # ids arrive as free text
        pid = project_of(U, x) if known_id(U, x) else ""  # an unknown id is dropped, a block id is widened to its project
        if pid and pid not in out:  # one entry per project, in the model's order
            out.append(pid)  # keep the first mention only
    return out  # may be empty: the caller then treats the line as not shown


def deterministic_groups(lines: list[dict], max_groups: int = 5) -> list[dict]:
    """Group neighbouring usable lines into paragraphs: at most three lines each, a new paragraph when the evidence stops overlapping."""
    use = [l for l in lines if l["strength"] != "none" and l["ev"] and (l["kind"] == "duty" or l["strength"] == "strong")]  # duties, and requirements that are plainly shown
    groups = []  # paragraphs being built: lines plus a private evidence set
    for l in use:  # lines arrive in posting order
        cur = groups[-1] if groups else None  # the paragraph that is currently being filled
        ev = set(l["ev"])  # the evidence ids of this line
        if cur and len(cur["lines"]) < 3 and (ev & cur["_ev"] or len(cur["lines"]) < 2):  # a paragraph takes a second line freely, a third only when the evidence overlaps
            cur["lines"].append(l["id"])  # join the open paragraph
            cur["_ev"] |= ev  # the paragraph's evidence grows with each line
        else:  # the paragraph is full or the evidence stopped overlapping
            groups.append({"lines": [l["id"]], "_ev": set(ev)})  # start a new paragraph with a copy of the set
    while len(groups) > max_groups:  # merge the two neighbours with the fewest lines together
        i = min(range(len(groups) - 1), key=lambda j: len(groups[j]["lines"]) + len(groups[j + 1]["lines"]))  # the pair with the fewest lines together keeps paragraphs even
        groups[i]["lines"] += groups[i + 1]["lines"]  # lines of the right neighbour move left
        groups[i]["_ev"] |= groups[i + 1]["_ev"]  # so does its evidence
        del groups[i + 1]  # the merged neighbour is gone
    by_id = {l["id"]: l for l in lines}  # looked up for the theme text
    return [{"id": f"g{i}", "lines": g["lines"], "theme": "; ".join(by_id[x]["text"][:40] for x in g["lines"][:2])} for i, g in enumerate(groups, 1)]  # ids g1.. in order; the theme is the start of the first two lines; the private _ev set is left out


def check_groups(raw, lines: list[dict], max_groups: int = 5) -> list[dict] | None:
    """Accept the model's grouping only when it is sound: known usable lines, no repeats, the posting's order kept."""
    usable = {l["id"]: l for l in lines if l["strength"] != "none" and l["ev"]}  # only lines with evidence that the profile can show may be answered
    seen, groups = set(), []  # seen makes sure a line sits in one group only
    for g in as_list(raw):  # the model's answer is untrusted, so every shape is checked
        if not isinstance(g, dict):  # a group must be an object
            return None  # one bad group rejects the whole grouping, the caller falls back
        ids = [str(x) for x in as_list(g.get("lines"))]  # line ids as strings
        if not ids or any(x not in usable or x in seen for x in ids):  # unknown, weak-none or repeated line
            return None  # same: reject everything rather than repair
        seen.update(ids)  # later groups may not repeat these lines
        ids.sort(key=lambda x: usable[x]["order"])  # the posting's order inside a group
        groups.append({"lines": ids, "theme": str(g.get("theme") or "")[:80]})  # the theme is cut short to keep prompts small
    if not groups or len(groups) > max_groups:  # no groups, or more paragraphs than a page holds
        return None  # the plan then groups the lines itself
    groups.sort(key=lambda g: usable[g["lines"][0]]["order"])  # groups follow the posting by their first line
    for a, b in zip(groups, groups[1:]):  # a later group must start after the earlier one ends
        if usable[a["lines"][-1]]["order"] > usable[b["lines"][0]]["order"]:  # an earlier group ends after the next one starts: the answers would be out of order
            return None  # reject, do not reorder lines across groups
    for i, g in enumerate(groups, 1):  # ids are given last, after sorting
        g["id"] = f"g{i}"  # g1, g2, ... in posting order
    return groups  # sound grouping, ready for the paragraph plan


def trim_groups(groups: list[dict], lines: list[dict], max_lines: int) -> tuple[list[dict], list[str]]:
    """Keep the lines that matter most when the groups hold more than a one-page letter can answer: duties before requirements
    before preferred lines, strong before weak inside a kind, then the posting's order. A requirement the profile shows in
    part ranks above a nice-to-have it shows fully: the submitted letters answer the compiler and English requirements and
    leave the preferred storage lines to the resume. Returns (groups without the dropped lines, dropped ids)."""
    by = {l["id"]: l for l in lines}  # line lookup for the ranking key
    held = [x for g in groups for x in g["lines"]]  # every line some paragraph holds, in group order
    if len(held) <= max_lines:  # nothing to cut
        return groups, []  # unchanged, nothing dropped
    rank = lambda x: ({"duty": 0, "requirement": 1, "preferred": 2}[by[x]["kind"]], {"strong": 0, "weak": 1}.get(by[x]["strength"], 2), by[x]["order"])  # smaller sorts first: duty before requirement before preferred, strong before weak, then posting order
    keep = set(sorted(held, key=rank)[:max_lines])  # the best max_lines lines survive
    out = []  # groups without the dropped lines
    for g in groups:  # groups keep their order and their themes
        ids = [x for x in g["lines"] if x in keep]  # only the surviving lines of this group, in their old order
        if ids:  # a group that lost every line disappears
            out.append({**g, "lines": ids})  # the rest of the group (theme) stays
    for i, g in enumerate(out, 1):  # renumber, since a group may be gone
        g["id"] = f"g{i}"  # ids stay g1, g2, ... without holes
    return out, [x for x in held if x not in keep]  # the dropped ids go into the plan notes


# A line about a degree, years of experience or a certificate is answered by the resume, not by a paragraph of the letter
ROUTINE_LINE = re.compile(r"\bdegree\b|bachelor|master'?s|ph\.?\s?d|diploma|\b\d+\s*\+?\s*years?\b|\byears of\b|certif|"
                          r"학위|학사|석사|박사|\d+\s*년\s*이상|경력\s*\d+\s*년|자격증", re.I)


def partial_cover(lex: Lex, l: dict) -> float:
    """How much of a line its evidence shows once the tools it names and the profile lacks are set aside."""
    text = l["text"]  # the line as the posting writes it
    for m in l.get("missing") or []:  # a missing tool is a gap, not a part of the line the evidence could show
        text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(m) + r"(?![A-Za-z0-9])", " ", text)  # the missing tool is cut out of the line
    return lex.coverage(text, l["ev"])  # weighted share of the remaining terms


def add_weak_lines(groups: list[dict], lines: list[dict], lex: Lex | None = None, how: str = "model", max_groups: int = 5) -> tuple[list[dict], list[str]]:
    """Give a paragraph to the weak lines that have evidence and no paragraph yet: the profile shows part of what they ask,
    and a one-page letter should answer that part (a compiler requirement shown by porting work, an English line shown by
    work with partners abroad). Lines about degrees, years or certificates stay out. A line inside the span of a group joins
    it; lines between groups form a new group together; the groups stay in the posting's order. Returns (groups, added ids)."""
    by = {l["id"]: l for l in lines}  # lines by id
    held = {x for g in groups for x in g["lines"]}  # lines a paragraph already answers
    def shown_in_part(l):  # the model judged the line partly shown; a line lowered for a missing tool, or rated by words, must show the rest in its words
        if how == "model" and l.get("source") != "model":  # the model left this line out of its answer: the word rating is too rough to act on
            return False
        if l.get("lowered") or l.get("source") == "words":  # weak because of a missing tool, or by word overlap only
            return bool(lex) and partial_cover(lex, l) >= 0.3
        return True  # the model's own "weak": part of the line is shown
    todo = [l for l in lines if l["strength"] == "weak" and l["ev"] and l["id"] not in held and l["kind"] in ("duty", "requirement")
            and not ROUTINE_LINE.search(l["text"]) and shown_in_part(l)]  # weak lines with evidence, without a paragraph, that a paragraph can answer
    if not todo:  # nothing to add
        return groups, []
    out = [{**g, "lines": list(g["lines"])} for g in groups]  # copies, so the caller's groups stay as they were
    span = lambda g: (min(by[x]["order"] for x in g["lines"]), max(by[x]["order"] for x in g["lines"]))  # the first and last line order of a group
    fresh = []  # weak lines that fall between groups, in order
    for l in todo:  # in the posting's order
        home = next((g for g in out if span(g)[0] < l["order"] < span(g)[1]), None)  # a group whose span holds the line
        if home:  # inside a group: join it
            home["lines"].append(l["id"])  # the line joins the group whose span holds it
            home["lines"].sort(key=lambda x: by[x]["order"])  # the posting's order inside the group
        else:  # between groups: keep for a new group
            fresh.append(l)  # kept for a new group
    for l in fresh:  # neighbouring weak lines share one new group
        prev = next((g for g in out if g.get("_new") and abs(span(g)[1] - l["order"]) <= 3  # a new group close before it
                     and not any(span(h)[0] < l["order"] and span(h)[0] > span(g)[1] for h in out if h is not g)), None)  # a new group just before it, with no old group between them
        if prev:  # join it, and let the theme name both lines
            prev["lines"].append(l["id"])  # the line joins it
            prev["theme"] = (prev["theme"] + "; " + by[l["id"]]["text"][:40])[:80]  # the theme names both lines
        else:
            out.append({"lines": [l["id"]], "theme": by[l["id"]]["text"][:60], "_new": True})  # the line's own words name the paragraph until a person edits the theme
    out.sort(key=lambda g: span(g)[0])  # groups follow the posting by their first line
    while len(out) > max_groups:  # merge the two neighbours with the fewest lines together
        i = min(range(len(out) - 1), key=lambda j: len(out[j]["lines"]) + len(out[j + 1]["lines"]))  # the neighbours with the fewest lines together
        out[i]["lines"] = sorted(out[i]["lines"] + out[i + 1]["lines"], key=lambda x: by[x]["order"])  # their lines merge in the posting's order
        out[i]["theme"] = "; ".join(t for t in (out[i].get("theme"), out[i + 1].get("theme")) if t)[:80]  # and their themes
        del out[i + 1]  # the right neighbour is gone
    for i, g in enumerate(out, 1):  # ids g1.. in order; the private marker goes
        g["id"] = f"g{i}"  # ids in order
        g.pop("_new", None)  # the private marker goes
    return out, [l["id"] for l in todo]


def match_with_model(lex: Lex, lines: list[dict], role: str, company: str, backend: str | None, cand: dict) -> dict | None:
    """One model call: for every posting line the best entries, a strength, missing tools; plus paragraph groups and overall fit."""
    U = lex.U  # the profile's units, for the details of each entry
    index = []  # one line per profile entry: where, when, title, opening words and the words that mark the rest of it
    q_all = lex.query(" ".join(l["text"] for l in lines))  # every posting line at once, to find the blocks of a project that speak to the posting
    for pid in cand["projects"]:  # one index row per project
        m = U["meta"][pid]  # company, title and period of the project
        body = " ".join(U["index"][x]["text"] for x in U["proj"][pid])[:200]  # the opening words
        best = sorted(U["proj"][pid], key=lambda b: -lex.score(q_all, b))[:2]  # the two blocks that share the most terms with the posting
        deep = " / ".join(f"[{b}] {U['index'][b]['text'][:150]}" for b in best if lex.score(q_all, b) > 0 and b != U["proj"][pid][0])  # work deep inside the project, which the opening words hide
        index.append(f"{pid} | {m['org']} | {m['period']} | {m['title']} | {body} | key words: {', '.join(lex.keywords(pid))}"
                     + (f" | also: {deep}" if deep else ""))  # the key words and the deep blocks show what the opening may hide
    for uid in cand["loose"]:  # summary, skills and similar units belong to no project
        index.append(f"{uid} | {U['index'][uid]['text'][:160]}")  # a short cut of the text is enough to recognise the unit
    hints = {l["id"]: [f"{pid}[{','.join(lex.shared_terms(l['text'], pid))}]" for pid, _ in lex.rank(l["text"], 3)] for l in lines}  # best word matches and the words that link them
    listing = "\n".join(f"{l['id']}. [{l['kind']}] {l['text']}" + (f"  (word-match hints: {', '.join(hints[l['id']])})" if hints[l['id']] else "") for l in lines)  # the posting lines, each with its word-match hints
    prompt = prompt_text("cover_match", role=role or "(not stated)", at_company=f" at {company}" if company else "", lines=listing, index="\n".join(index))  # the template lives in src/prompts; role and company fill the placeholders
    try:  # a missing or failing model is not an error here
        return llm.run("cover-match", prompt, want_json=True, required=("lines",), backend=backend,  # one call for all lines; the answer must hold a lines list
                       system="You review how well a profile matches a job posting. Never stretch a match. Return only JSON.")  # the system text tells the model never to stretch a match
    except (llm.LLMUnavailable, ValueError):  # no model, or no usable answer
        return None  # the caller falls back to word matching


def candidates(lex: Lex, lines: list[dict], limit: int = 120) -> dict:
    """The entries shown to the model: every project when the profile is small, else the best for each line (plus all small units)."""
    U = lex.U  # the profile's units
    projs = list(U["proj"])  # every project id
    loose = [u["id"] for u in U["units"] if not u["pid"] and u["kind"] in ("summary", "skills", "context", "section", "education", "competency")]  # units outside projects that can still carry evidence
    if len(projs) + len(loose) <= limit:  # a small profile fits the prompt whole
        return {"projects": projs, "loose": loose}  # nothing to choose
    keep = []  # too many entries for one prompt: the best twelve per line
    for l in lines:  # each posting line nominates its own best projects
        keep += [pid for pid, _ in lex.rank(l["text"], 12)]  # the union of the best projects over all lines
    keep = list(dict.fromkeys(keep))[: max(20, limit - len(loose))]  # drop repeats, then cap so the prompt stays within the limit
    return {"projects": [p for p in keep if p in U["proj"]], "loose": loose[:40]}  # keep only real projects; loose units are capped as well


def plan(profile: dict, posting_text: str, *, lang: str | None = None, company: str | None = None, role: str | None = None,
         backend: str | None = None, allow: list | None = None, motivation: bool = True, max_lines: int = 12,
         prepared: tuple | None = None) -> dict:
    """Turn a posting into the cover plan: its lines in order, the evidence for each, honest strengths and gaps, paragraph groups.
    `prepared` is (units_of(profile, lang), Lex of them), already worked out for this very profile and `lang` (which the
    caller then names): the panel's fit plans one posting after another against the same profile, and neither depends on
    the posting. Nothing here changes either one."""
    parsed = parse_posting(posting_text)  # the lines of the posting, parsed without a model first
    notes = []  # things the user should know about how the plan was made
    if len(parsed["items"]) < 2 and backend != "none":  # an unusual layout: ask the model for the lines
        got = llm_posting(posting_text, backend)  # the model only copies lines, and those are checked against the text
        if got and len(got["items"]) >= 2:  # an answer with fewer than two lines is no better than the parser
            parsed = {**parsed, **{k: got[k] or parsed.get(k, "") for k in ("company", "title")}, "items": got["items"]}  # the items always come from the model; company and title only when it gave one
            notes.append("posting lines were read by the model and checked against the text")  # tells the user where the lines came from
    if not parsed["items"]:  # no duty or requirement at all: stop with a clear message
        raise SystemExit(t("no_lines"))  # the command line shows this text, without a traceback
    lang = lang or guess_lang(posting_text)  # the letter follows the posting's language unless told otherwise
    company = (company if company is not None else parsed["company"]).strip()  # an explicit empty value is respected; None falls back to the posting
    role = (role if role is not None else parsed["title"]).strip()  # same rule as for the company
    lines = line_ids(parsed["items"])  # ids d1.., q1.., p1.. in posting order
    U, lex = prepared if prepared else (units_of(profile, lang), None)  # the evidence units, in the letter's language
    if not U["units"]:  # a profile without citable text cannot support a single claim
        raise SystemExit(t("bad_json", path="profile", what="profile with roles"))  # say so instead of writing an empty plan
    lex = lex or Lex(U)  # the index for word matching and for the hints
    model = None  # stays None when no model is asked or none answers
    if backend != "none":  # one call for the matching
        model = match_with_model(lex, lines, role, company, backend, candidates(lex, lines))  # None when the model is down or answers badly
    by_id = {str(x.get("id")): x for x in as_list(model.get("lines")) if isinstance(x, dict)} if model else {}  # the model's answers keyed by posting line id; anything that is not an object is skipped
    how = "model" if by_id else "words"  # recorded in the plan as matched_by
    if not by_id:  # the user should know the strengths are only rough
        notes.append("no model matched the lines; matching used words only, so strengths are rough")  # no model answer, or none that named a line
    whole = " ".join(u["head"] + " " + u["text"] for u in U["units"])  # all evidence text, to tell a gap from a tool shown elsewhere
    for l in lines:  # decide evidence, strength and missing tools for every line
        m = by_id.get(l["id"])  # the model's entry for this line, if there is one
        if m:  # the model's view, checked against the profile
            ev = valid_ids(U, m.get("ids"))  # only ids that exist, widened to project ids
            strength = str(m.get("strength") or "none").lower()  # the model's own label, lowercased
            strength = strength if strength in ("strong", "weak", "none") else "none"  # an unknown label counts as none
            if not ev:  # strength without any real entry behind it
                strength = "none"  # a match without an existing entry is no match
            declared = [str(x) for x in as_list(m.get("missing")) if isinstance(x, str) and re.search(r"[A-Za-z가-힣]", x) and mentions(l["text"], x.split("(")[0].strip() or x)]  # only terms the line really names
            basis = str(m.get("basis") or "")[:200]  # the model's reason, kept short for the plan file
        else:  # words only: the two best projects, and one more entry (a skills row, a summary line) when it is not a resume line
            ranked = lex.rank(l["text"], 8)  # the best eight projects and loose units for this line
            ev = [pid for pid, _ in ranked if pid in U["proj"]][:2]  # the two best projects
            ev += [pid for pid, _ in ranked if pid not in U["proj"] and not U["index"][pid]["resume"]][:1]  # plus one loose unit, never a resume line that would only repeat the resume
            cov = lex.coverage(l["text"], ev)  # share of the line's weighted terms that this evidence shows
            strength = "strong" if cov >= 0.55 else ("weak" if cov >= 0.25 else "none")  # rough cut-offs, used only when no model judged the line
            if strength == "none":  # too little overlap to count as evidence
                ev = []  # a line with no evidence stays out of the letter
            declared, basis = [], f"word overlap {cov:.2f}"  # no model, so no declared tools; the basis shows the score
        miss = missing_in(lex, l["text"], ev, declared)  # tools the line names that the chosen entries do not show
        for term in list(miss):  # a tool the chosen entries lack but another entry names: add that entry
            holder = holder_of(lex, term, ev) if mentions(whole, term) else None  # only when some other entry of the profile names the tool
            if holder and len(ev) < 4:  # at most four entries per line
                ev.append(holder)  # the line can now cite where the tool is shown
        if ev:  # the added entries may have shown the tools, so count again
            miss = missing_in(lex, l["text"], ev, declared)  # the same test, now with the larger evidence
        lowered = strength == "strong" and bool(miss)  # only a strong line is lowered by a missing tool; weak and none stay as they are
        if lowered:  # a line is not strongly shown when a tool it names is not
            strength = "weak"  # the line keeps its evidence but not its strength
        l.update(ev=ev, strength=strength, missing=miss, basis=basis, source=("model" if m else "words"), lowered=lowered)  # the plan line now carries its evidence, strength, gaps and origin
    gap_terms = []  # a tool is a gap only when no entry of the profile names it
    for l in lines:  # gather the tools no entry shows, over all lines
        for x in l["missing"]:  # missing tools of this line
            if not mentions(whole, x) and len(x) > 2 and x not in gap_terms:  # named elsewhere in the profile means not a gap; very short terms are noise
                gap_terms.append(x)  # the letter must never claim these
    groups = check_groups(model.get("groups"), lines) if model else None  # the model's grouping when it is sound
    if groups is None:  # None means the model gave no grouping or an unsound one
        groups = deterministic_groups(lines)  # else neighbouring lines, by the plan itself
        if model:  # with no model there is nothing to explain, the matching note above covers it
            notes.append("the model's paragraph groups were not sound; the plan groups neighbouring lines itself")  # the user learns why the grouping looks mechanical
    groups, weak_added = add_weak_lines(groups, lines, lex, how)  # weak lines with evidence get a paragraph too
    if weak_added:  # say which, so the user can take them out again
        notes.append(f"weak lines with evidence were given a paragraph: {', '.join(weak_added)}")  # listed, so a person can take them out again
    groups, trimmed = trim_groups(groups, lines, max_lines)  # a one-page letter answers only so many lines
    if trimmed:  # lines were cut to fit one page
        notes.append(f"{len(trimmed)} lines were left out to keep the letter to one page: {', '.join(trimmed)}")  # names the lines, so the user can add them back by hand
    answered = {x for g in groups for x in g["lines"]}  # lines that a paragraph will answer
    for l in lines:  # mark which lines the letter will answer
        l["use"] = l["id"] in answered  # use is the plan's final word on a line
        if not l["use"]:  # say why a line stays out of the letter
            # the reason is the first rule that fits: nothing shown, over the budget, left out by the model's grouping, or a requirement without strong evidence
            l["skipped"] = (("the profile does not show it" if how == "model" else "no matching words in the profile") if l["strength"] == "none" or not l["ev"] else
                            "over the one-page budget" if l["id"] in trimmed else
                            "left out of the paragraph plan" if model else "a requirement or preferred line without strong evidence")
    fit = valid_ids(U, model.get("fit")) if model else []  # the model's view of the projects that fit the whole posting
    if not fit:  # the projects that fit the whole posting best
        total = collections.Counter()  # summed scores per project
        for pid, sc in lex.rank(" ".join(l["text"] for l in lines), 5):  # rank against the whole posting at once
            total[pid] += sc  # a project may appear more than once in the ranking
        fit = [p for p, _ in total.most_common(4)]  # the four best
    used = {e for l in lines for e in l["ev"]} | set(fit)  # every id the plan relies on, for the fingerprint below
    return {"schema": SCHEMA_PLAN, "lang": lang,  # plain data only: it is written to plan.json as it is
            "posting": {"company": company, "role": role, "location": parsed.get("location", ""), "overview": parsed.get("overview", ""),  # posting facts that the letter and its checks draw on
                        "sha": hashlib.sha256(posting_text.encode()).hexdigest()[:16]},  # fingerprint of the posting text
            "lines": lines, "groups": groups, "fit": fit, "gap_terms": gap_terms, "allow": list(allow or []),  # allow holds names the user lets the letter use besides the company and role
            "motivation": bool(motivation and parsed.get("overview")), "matched_by": how, "notes": notes,  # a why-this-team paragraph needs an overview to be written from
            "evidence_hash": evidence_hash(U, used)}  # stale_issues compares this against the profile later


# the style pack
# The style pack is the same JSON file the resume drafts use (src/style/<name>.json). Cover letters read its banned_chars and
# banned_patterns, and an optional "cover" object for the options below.

COVER_DEFAULTS = {  # every cover option has a default, so a style pack may leave the cover object out
    "numbers": "forbid",  # forbid: no number in the letter; evidence: only numbers that the cited evidence states too
    "banned_words": [],  # words and phrases the letter must not use (case-insensitive)
    "tone": {"en": "plain and specific, in the first person, without hype or flattery",
             "ko": "담백하고 구체적인 1인칭, 합니다체, 과장이나 아부 표현 없이"},  # one line the draft prompt carries
    "max_words": {"en": 560},  # budget of the whole body for a one-page letter in English (words)
    "max_chars": {"ko": 1900},  # the same for Korean (characters without spaces)
    "sentence_words": 55, "sentence_chars": 140,  # a sentence longer than this is a run-on
    # Reusing a phrase of the resume is normal; copying a sentence is not.
    # A sentence repeats the resume when it shares a run of repeat_run words (characters in Korean), or a run of at least repeat_min that
    # makes up repeat_share of the sentence.
    "repeat_run": {"en": 14, "ko": 40}, "repeat_min": {"en": 6, "ko": 14}, "repeat_share": 0.6,
    "max_paragraphs": 7,  # body paragraphs, opening and closing included
}


def load_style(spec: str | None = None, hints=()) -> dict:
    """The style pack by name (src/style/<name>.json, or <workspace>/style/<name>.json) or by path, merged with the cover defaults."""
    spec = spec or "default"  # no name given: the empty default pack
    if "/" in spec or spec.endswith(".json"):  # a path: as given, then from the repository root (plans store paths relative to it)
        cands = [pathlib.Path(spec), ROOT / spec]
    else:  # a name: the packs shipped in src/style, then the workspace's own
        cands = [ROOT / "src" / "style" / f"{spec}.json"] + [pathlib.Path(h) / "style" / f"{spec}.json" for h in hints]
    for f in cands:  # first file that exists
        if f.is_file():  # the first candidate that exists wins
            pack = read_json(f, "style pack")  # stops with a message when the file is not valid JSON
            break  # do not look at the later candidates
    else:  # the loop ended without a hit
        raise SystemExit(f"style pack not found: {spec}")  # a typo must not switch the rules off silently
    cover = copy.deepcopy(COVER_DEFAULTS)  # the defaults, which the pack's own cover object overrides
    for k, v in (pack.get("cover") or {}).items():  # nested options merge, plain ones replace
        cover[k] = {**cover[k], **v} if isinstance(v, dict) and isinstance(cover.get(k), dict) else v  # dict options merge key by key, anything else is replaced whole
    if cover["numbers"] not in ("forbid", "evidence"):  # an unknown policy would silently allow numbers
        raise SystemExit("style cover.numbers must be forbid or evidence")  # fail early with the allowed values in the message
    return {"banned_chars": pack.get("banned_chars", ""), "banned_patterns": pack.get("banned_patterns", []), "cover": cover, "name": spec}  # the banned lists come from the resume pack, the cover options are merged above


def style_issues(text: str, style: dict, lang: str) -> list[dict]:
    """Banned characters, patterns and words, and run-on sentences."""
    bad = []  # every style problem of the sentence
    for c in style.get("banned_chars", ""):  # banned_chars is a string, one banned character each
        if c in text:  # plain substring test is enough for one character
            bad.append(issue("banned_char", detail=repr(c)))  # repr makes an invisible or look-alike character visible
    for pat, why in style.get("banned_patterns", []):  # each pattern comes with a reason for the message
        if re.search(pat, text):  # the pattern is a regular expression
            bad.append(issue("banned_pattern", detail=why))  # the reason is shown, not the pattern
    for w in style["cover"].get("banned_words", []):  # options that only cover letters have
        hit = re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", text, re.I) if re.match(r"[A-Za-z]", w) else (w in text)  # Latin words match as whole words in any case, so leveraged is not leverage; Korean words match as text
        if hit:  # banned word found
            bad.append(issue("banned_word", detail=w))  # the word itself is the detail
    n = len(text.split()) if lang == "en" else len(re.sub(r"\s", "", text))  # length in words for English, in characters without spaces for Korean
    lim = style["cover"]["sentence_words"] if lang == "en" else style["cover"]["sentence_chars"]  # the limit is stored per unit in the style pack
    if n > lim:  # longer than the limit is a run-on sentence
        bad.append(issue("too_long", detail=n))  # detail is the measured length
    return bad  # empty means the wording is within the pack


# the fact check of one sentence

@dataclasses.dataclass  # a plain record that the checks pass around
class Ctx:
    """What a sentence is checked against."""
    lang: str  # letter language
    U: dict  # evidence units
    style: dict  # style pack with cover options
    allow: set  # words allowed everywhere: company, role, place of the posting, plus the plan's own list
    overview: set  # names that the posting's overview uses (allowed in the opening and the motivation)
    gap_terms: list  # tools the profile lacks and the posting asks for
    vocab: dict  # tool and product names of the whole profile: a sentence may not use one that its evidence lacks
    where: dict  # name-like words of the profile with where they live, for the hint under a rejected name
    glossary: list = dataclasses.field(default_factory=list)  # (Korean, English) spellings of names: one side in a sentence, the other in its evidence
    lex: object = None  # word matching over the units, to narrow a cited project to the blocks a claim is held against


def make_ctx(U: dict, plan: dict, style: dict, glossary: list | None = None) -> Ctx:
    """The checking context of a plan. `glossary` comes from factcheck.glossary_of(profile)."""
    post = plan.get("posting", {})  # a hand-made plan may have no posting block
    ident = " ".join([post.get("company", ""), post.get("role", ""), post.get("location", "")] + list(plan.get("allow", [])))  # company, role and place of work may be named freely, with the plan's own list
    allow = set(F.latin_tokens(ident)) | {flat(x) for x in [post.get("company", "")] + list(plan.get("allow", [])) if x}  # Latin words and whole Korean names
    ov = post.get("overview", "")  # the overview is the posting's text about the company and team
    names = {p.lower() for p, ini in name_parts(ov) if name_like(p, ini)} if plan.get("lang") == "en" else set(F.latin_tokens(ov))  # English: name-like words of the overview; Korean: its Latin words
    return Ctx(plan.get("lang", "en"), U, style, allow, names, list(plan.get("gap_terms", [])), tool_vocab(U), name_locations(U),  # the vocabulary and the word locations are built once here, not for every sentence
               list(glossary or []), Lex(U))  # the glossary and the word index, also built once


def evidence_for(U: dict, ids) -> str:
    """The text a sentence may rest on: the cited blocks or projects, each with the words that name its company and role."""
    return "\n".join(unit_text(U, i) for i in ids)  # every unit_text carries its head, so company and role words count as evidence


def fact_issues(s: dict, kind: str, ctx: Ctx) -> list[dict]:
    """Everything wrong with one sentence: ids, numbers, names, tools claimed beyond the profile, style. Empty means it passes."""
    text, bad = s["text"], []  # bad collects the issues of the sentence
    if not text.strip():  # an empty sentence cannot be checked further
        return [issue("empty")]  # nothing else is worth reporting then
    unknown = [i for i in s["ev"] if not known_id(ctx.U, i)]  # cited ids that the profile does not have
    bad += [issue("unknown_id", id=i) for i in unknown]  # one issue per unknown id
    valid = [i for i in s["ev"] if known_id(ctx.U, i)]  # only these count as evidence below
    if s.get("frame"):  # a sentence that only frames the letter
        if valid:  # a framing sentence claims nothing, so it must cite nothing
            bad.append(issue("frame_ev"))  # a frame must not cite evidence
        if kind not in ("opening", "motivation", "closing"):  # frames belong to the opening, the motivation and the closing only
            bad.append(issue("frame_where"))  # a frame in the wrong paragraph kind
    elif not valid and not unknown:  # a claim without any id; unknown ids were reported above already
        bad.append(issue("no_ev"))  # every claim needs evidence
    E = evidence_for(ctx.U, valid)  # the text the sentence may rest on
    declared = []  # names the sentence spells differently from the evidence, with a source that must be in the evidence
    for written, src in (s.get("names") or {}).items():  # names maps a spelling used in the sentence to its spelling in the evidence
        if written and written.lower() in text.lower():  # a declaration for a name the sentence does not use is ignored
            if src and flat(src) in flat(E):  # the source must really be in the cited evidence, ignoring spaces and case
                declared.append(written)  # this spelling is now backed
            else:  # the declared source is not in the cited evidence
                bad.append(issue("name_src", detail=written))  # a made-up source cannot launder a name
    declared += F.glossary_accept(text, E, ctx.glossary)  # a spelling whose twin in the other language stands in the cited evidence needs no declaration
    E_ext = E + "\n" + "\n".join(declared)  # the verified spellings count as evidence words
    allow = set(ctx.allow) | (ctx.overview if kind in ("opening", "motivation") else set())  # the posting's overview names are allowed only where the letter speaks of the company
    bad += number_issues(text, E, ctx.style["cover"]["numbers"])  # the policy comes from the style pack: forbid or evidence
    bad += name_issues(text, E_ext, allow, ctx.vocab, ctx.where, ctx.lang)  # checked against E_ext, so declared spellings count
    if valid and not s.get("frame"):  # a claim of leading, designing, building or owning must not outgrow its evidence
        for c in F.claim_issues(text, claim_blocks(ctx, valid, text)):  # each claim class against the cited blocks
            bad.append(issue("claim", detail=F.claim_text(c, ui_lang())))  # the message quotes the evidence's word
    for g in ctx.gap_terms:  # a tool the posting asks for and the profile lacks must not be claimed
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(g) + r"(?![A-Za-z0-9])", text, re.I):  # whole word, any case, so rust and Rust are the same tool
            bad.append(issue("gap_term", detail=g))  # claims a tool that the profile does not show
    return bad + style_issues(text, ctx.style, ctx.lang)  # style problems come last in the list


def claim_blocks(ctx: Ctx, ids, text: str) -> list[str]:
    """The evidence a claim is held against: each cited block, and for a cited project the three blocks that share the most
    terms with the sentence (all of its blocks when none does)."""
    out = []  # block texts
    q = ctx.lex.query(text) if ctx.lex else []  # the sentence's terms with their twins in the other language
    for i in ids:  # each cited id
        if i in ctx.U["index"]:  # one unit
            out.append(ctx.U["index"][i]["text"])  # the block's own text
        elif i in ctx.U["proj"]:  # a whole project: its blocks that speak to the sentence
            blocks = ctx.U["proj"][i]  # the project's blocks
            scored = sorted(((ctx.lex.score(q, b) if ctx.lex else 0.0, b) for b in blocks), reverse=True)  # best first
            best = [b for sc, b in scored[:3] if sc > 0] or blocks  # every block when none shares a term
            out += [ctx.U["index"][b]["text"] for b in best]  # the blocks that speak to the sentence
    return out


def norm_sentence(x) -> dict | None:
    """A sentence object from whatever the model returned; None when there is no text."""
    if isinstance(x, str):  # a bare string is a sentence without tags
        x = {"text": x}  # same shape as an object, so the rest of the function is one path
    if not isinstance(x, dict):  # neither text nor object
        return None  # dropped by the caller
    text = " ".join(str(x.get("text", "")).replace("==", "").split())  # highlight marks go and whitespace collapses
    if not text:  # nothing left to say
        return None  # dropped by the caller
    names = x.get("names") if isinstance(x.get("names"), dict) else {}  # a model may send a list or a string here, and only an object is usable
    return {"text": text, "ev": list(dict.fromkeys(str(e).strip() for e in as_list(x.get("ev")) if str(e).strip())),  # ids are deduplicated with the order kept, and empty ones are dropped
            "duties": list(dict.fromkeys(str(d).strip() for d in as_list(x.get("duties")) if str(d).strip())),  # the posting line ids this sentence answers
            "frame": bool(x.get("frame")), "names": {str(k): str(v) for k, v in names.items()}}  # names becomes a map from text to text


# the resume: what the letter must not repeat

def resume_lines(profile: dict, lang: str) -> list[str]:
    """The text that the resume of this profile prints (summary, intro, competencies, statements): the stand-in when no resume file is given."""
    U = units_of(profile, lang)  # the same units that the plan cites
    return [u["text"] for u in U["units"] if u["resume"]]  # units flagged resume are what the resume prints


def resume_source(spec: str | None, profile: dict, lang: str) -> tuple[list[str], str]:
    """(lines of the resume, where they came from). A PDF is read for its text, text files as they are, and when nothing is given the profile itself."""
    if spec:  # a resume file was given
        p = pathlib.Path(spec)  # the file kind is judged by its suffix
        if p.suffix.lower() == ".pdf":  # a PDF's text layer
            out = pdftools.text(p)  # with poppler or PDFium
            return [ln.strip() for ln in out.splitlines() if ln.strip()], str(p)  # blank lines go; the path says where the lines came from
        if p.suffix.lower() == ".json":  # a profile file stands for its own resume text
            return resume_lines(read_json(p, "profile"), lang), str(p)  # read_json stops with a message when the file is not JSON
        return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()], str(p)  # any other file is read as plain text
    return resume_lines(profile, lang), t("r_repeat_src")  # no file given: the profile's resume-bound text stands in


def run_tokens(text: str, lang: str) -> list[str]:
    """The tokens a shared run is counted in: words for English, characters for Korean."""
    text = (text or "").lower()  # case must not hide a repeat
    if lang == "ko":  # Korean runs are counted in characters
        return list(re.sub(r"[^\w]", "", text))  # characters; spaces and punctuation differ between a PDF and the draft
    return re.findall(r"[a-z0-9]+", text.replace("’", "'").replace("'", ""))  # words


def shared_run(text: str, resume: str, lang: str) -> tuple[int, str]:
    """Length and text of the longest run that a sentence shares with the resume."""
    a, b = run_tokens(text, lang), run_tokens(resume, lang)  # the sentence and the resume, as token lists
    if not a or not b:  # nothing to compare
        return 0, ""  # no run at all
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))  # autojunk off: it would skip frequent tokens and miss real repeats
    sep = "" if lang == "ko" else " "  # Korean runs are characters, so they join without spaces
    return m.size, sep.join(b[m.b:m.b + m.size])  # the shared text is read from the resume side, for the message


def is_repeat(run: int, size: int, lang: str, style: dict) -> bool:
    """Is a shared run of `run` tokens in a sentence of `size` tokens a copy of the resume?"""
    cov = style["cover"]  # the repeat limits live in the cover options
    return run >= cov["repeat_run"][lang] or (run >= cov["repeat_min"][lang] and size > 0 and run / size >= cov["repeat_share"])  # a long run alone, or a shorter run that is most of the sentence


def repeat_hits(paragraphs: list[dict], resume: list[str], lang: str, style: dict) -> dict:
    """{(paragraph index, sentence index): (run length, shared text)} for sentences that repeat a resume line."""
    blob = "\n".join(resume)  # the sentence is compared with all resume lines at once
    hits = {}  # keyed by the place of the sentence
    for pi, par in enumerate(paragraphs):  # paragraph index
        for si, s in enumerate(par["sentences"]):  # sentence index inside the paragraph
            n, sh = shared_run(s["text"], blob, lang)  # length and text of the longest shared run
            if is_repeat(n, len(run_tokens(s["text"], lang)), lang, style):  # the size of the sentence in the same unit decides what share the run makes up
                hits[(pi, si)] = (n, sh)  # remember where it is and what was copied
    return hits  # empty when the letter says everything in its own words


# coverage of the posting's lines, in order

def answered_lines(paragraphs: list[dict]) -> dict:
    """{line id: (paragraph index, sentence index) of the first sentence that answers it}. A sentence without tags answers its paragraph's lines."""
    first = {}  # line id to the place of its first answer
    for pi, par in enumerate(paragraphs):  # paragraph index
        for si, s in enumerate(par["sentences"]):  # sentence index inside the paragraph
            for d in (s.get("duties") or par.get("duties") or []):  # tags on the sentence win, untagged sentences take the paragraph's lines
                first.setdefault(d, (pi, si))  # only the first answer counts for the order check
    return first  # lines that nobody answers are simply absent


def coverage_issues(paragraphs: list[dict], plan: dict) -> list[dict]:
    """Planned lines without an answer, answers out of the posting's order, and answers to lines the profile cannot show."""
    bad = []  # missing, out of order, and gap answers
    lines = {l["id"]: l for l in plan.get("lines", [])}  # plan lines by id
    first = answered_lines(paragraphs)  # where each line is first answered
    wanted = [l for l in plan.get("lines", []) if l.get("use")]  # the lines the plan decided to answer
    for l in wanted:  # every wanted line needs an answer
        if l["id"] not in first:  # planned but nobody answers it
            bad.append(issue("missing_line", id=l["id"]))  # the line stays open
    seen = sorted(((first[l["id"]], l) for l in wanted if l["id"] in first), key=lambda x: x[1]["order"])  # by posting order
    for (pos_a, a), (pos_b, b) in zip(seen, seen[1:]):  # a comes before b in the posting
        if pos_a > pos_b:  # a comes first in the posting, but its answer sits after b's answer
            bad.append(issue("order", a=a["id"], b=b["id"]))  # "line a is answered after line b": one issue per neighbouring pair that is crossed
    for d in first:  # answers to lines that the plan marks as not shown
        if d in lines and not lines[d].get("use") and lines[d].get("strength") == "none":  # answering an unused line is fine unless the profile has nothing for it
            bad.append(issue("gap_line", id=d))  # the letter would claim something the profile cannot show
    return bad  # empty means complete, in order and within the profile


# drafting

# system message sent with every drafting call; the checks later enforce the same limits
SYSTEM = ("You write a cover letter from facts the person gave. Use only the facts in the evidence you cite. Never add numbers, tools, products, "
          "clients, places or results that the evidence does not state. Return only JSON.")
EV_CAP = 2400  # characters of one project shown to the model; the blocks that fit the posting lines best are kept
LANGNAME = {"ko": "Korean", "en": "English"}  # how the prompts name the letter's language
KIND_PURPOSE = {  # what each paragraph kind is asked to do; the plan listing and the repair request print these lines
    "opening": ("Opening. Say which role you apply for. Then give the thread of your career in one sentence that names three or four of "
                "the clients, places and systems the evidence names, and the side of the work you were on (for example the supplier who runs a "
                "customer's systems), so a reader sees at once why you fit. When the evidence or the plan states your direction, carry it."),
    "motivation": ("Why this team. Say what draws you to one thing the posting says about the company or the team's work, and show where your "
                   "own work already meets it with one or two named facts from the evidence listed. Do not describe your own writing or "
                   "restate the posting. Claim nothing about the company that the posting does not say."),
    "duties": ("Answer the posting lines below, in the order given, with what you did. Open with the paragraph's subject in the posting's "
               "terms, then connect the facts into one account of that subject, the most telling first: a named client or system and what "
               "came of it before routine steps. Say where each thing happened inside its sentence; a paragraph whose sentences all begin "
               "with a company's name reads as a list."),
    "closing": "Closing. One or two framing sentences: thanks, and an offer to talk. No facts about you.",
}


def display_name(profile: dict, lang: str) -> str:
    """The name for the signature: 'Last, First' becomes 'First Last' in English letters."""
    P = profile.get("person") or {}  # a profile without a person block must not crash the signature
    if lang == "en" and P.get("name_en"):  # only an English letter uses the romanised name, and only when the profile has one
        n = P["name_en"]  # the name as stored, which may be written Last, First
        return " ".join(reversed([x.strip() for x in n.split(",", 1)])) if "," in n else n  # swap Last, First into First Last; a name without a comma passes through as it is
    return P.get("name", "")  # a Korean letter signs with the Korean name; empty when the profile has none


def paragraph_plan(plan: dict, U: dict, lex: Lex | None = None) -> list[dict]:
    """The paragraphs of the letter: opening, optional motivation, one per planned group, closing; with the evidence each may use.
    With a word index, a duty paragraph also gets the projects that word matching ranks high for its lines, and the opening
    every project the plan matched: facts deep inside a project the plan did not choose (a checkpoint design, compile and
    link errors) were otherwise out of reach."""
    heads = [u["id"] for u in U["units"] if u["kind"] == "role"][-2:][::-1]  # the two most recent roles
    summary = [u["id"] for u in U["units"] if u["id"].startswith("summary#") and u["id"] != "summary#direction"]  # headline, intro, cards, highlights, layers: where clients and places are named
    statements = [u["id"] for u in U["units"] if u["kind"] == "statement" or u["id"] == "summary#direction"]  # the person's own about, motivation and direction
    by_id = {l["id"]: l for l in plan["lines"]}  # lines by id, to collect the evidence of each group
    used = list(dict.fromkeys(e for g in plan["groups"] for x in g["lines"] for e in by_id[x]["ev"])) if lex else []  # every entry the planned lines rest on
    pool = list(dict.fromkeys(plan.get("fit", []) + summary + heads + statements + used))  # the opening may cite all of them
    broad = [i for i in summary if i.startswith(("summary#l", "summary#h"))]  # the layers and highlights show the whole path through the stack
    paras = [{"id": "p1", "kind": "opening", "lines": [], "pool": pool}]  # the opening is always first
    if plan.get("motivation"):  # only when the posting said something about the company
        paras.append({"id": f"p{len(paras) + 1}", "kind": "motivation", "lines": [], "pool": list(dict.fromkeys(plan.get("fit", []) + broad + statements))})  # the best-fitting projects, the broad rows and the person's own statements
    for g in plan["groups"]:  # one paragraph per planned group, in the posting's order
        ev = list(dict.fromkeys(e for x in g["lines"] for e in by_id[x]["ev"]))  # the evidence of all its lines, without repeats
        if lex:  # projects that word matching ranks high for a line join the pool
            for x in g["lines"]:  # each line of the group
                ranked = [(pid, sc) for pid, sc in lex.rank(by_id[x]["text"], 6) if pid in U["proj"]]  # projects only; loose rows are in the plan already
                top = ranked[0][1] if ranked else 0.0  # the best score for this line
                ev += [pid for pid, sc in ranked[:3] if sc >= 0.4 * top and pid not in ev][:2]  # at most two more per line, close to the best
            ev = list(dict.fromkeys(ev))  # once each, in order
        paras.append({"id": f"p{len(paras) + 1}", "kind": "duties", "lines": list(g["lines"]), "pool": ev, "theme": g.get("theme", "")})  # the group's theme travels along with the paragraph
    paras.append({"id": f"p{len(paras) + 1}", "kind": "closing", "lines": [], "pool": []})  # the closing has no facts to cite
    return paras  # the skeleton of the letter; draft fills in the sentences


def evidence_listing(U: dict, lex: Lex, ids, focus, glossary=None) -> str:
    """The evidence block of a prompt: for every id, its blocks as `[id] text`; long projects keep the blocks that fit `focus` best.
    `focus` is one text, or {id: text} so that each project keeps the blocks that fit the paragraphs it serves. With a glossary,
    a last line lists the names the evidence holds with their spelling in the other language."""
    out, seen = [], set()  # prompt lines, and the project ids already listed
    for pid in ids:  # the ids mix project ids and loose unit ids
        # the same project can sit in several pools; show it once
        if pid in seen:
            continue
        seen.add(pid)
        if pid in U["proj"]:  # a project id lists its blocks; a block id lists one unit (see the branch below)
            blocks = list(U["proj"][pid])  # copy, so trimming never touches the unit table
            if sum(len(U["index"][b]["text"]) for b in blocks) > EV_CAP:  # keep the blocks that matter for the posting
                q = lex.query(focus.get(pid, "") if isinstance(focus, dict) else focus)  # terms of the lines this project serves, to score each block
                best = sorted(blocks, key=lambda b: -lex.score(q, b))  # most relevant block first
                keep, size = set(), 0  # keep holds the chosen block ids, size their characters so far
                for b in best:  # best first, so the cap cuts the weakest blocks
                    if size + len(U["index"][b]["text"]) <= EV_CAP or not keep:  # a block that would pass the cap is skipped, but the best block always stays so a project is never empty
                        keep.add(b)  # this block goes into the prompt
                        size += len(U["index"][b]["text"])  # count its characters against the cap
                blocks = [b for b in blocks if b in keep]  # back to the profile's own order, so the text reads as its author wrote it
            out.append(f"{pid}: {U['heads'][pid]}")  # project line with company, role and period, so the model knows whose work it is
            out += [f"  [{b}] {'(resume) ' if U['index'][b]['resume'] else ''}{U['index'][b]['text']}" for b in blocks]  # one line per block; the id in brackets is what a sentence cites, and (resume) marks text the resume already prints
        elif pid in U["index"]:  # a loose unit such as a summary line or a skills row
            u = U["index"][pid]  # the unit behind that id
            out.append(f"[{pid}] {'(resume) ' if u['resume'] else ''}{u['text']}")  # same bracket form as the project blocks, so one citing rule covers both
    if glossary:  # the names in this evidence, with the spelling of the other language, so the letter keeps them
        text = " ".join(out)  # everything listed above
        names = [f"{ko} = {en}" for ko, en in glossary if ko in text and len(ko) >= 2][:40]  # pairs whose Korean side is in the listed evidence
        if names:  # at least one pair applies
            out.append("Names in this evidence and their English spelling (keep them; no declaration needed): " + "; ".join(names))  # the model sees each spelling it may use
    return "\n".join(out)  # one prompt line per entry


def rules_text(plan: dict, style: dict, lang: str, mixed_language: bool) -> str:
    """The shared sentence rules, with the number, name and gap rules that fit this plan and style."""
    cov = style["cover"]  # the cover options of the style pack
    # the number rule follows the style pack: forbid bans every count, evidence allows only what the cited text states
    numbers = ("- Write no numbers at all: no digits, no spelled-out counts (two, three, dozens), no years, no percentages. Say several, many, every or each instead."
               if cov["numbers"] == "forbid" else "- Use a number only when the cited evidence states the same number.")
    names = "- Write tool and product names exactly as the evidence spells them. Do not name a company, client, institution, place or certificate that the cited evidence does not name."  # names must be spelled as the evidence spells them, and none may be invented
    if mixed_language:  # the evidence may spell a name differently from the letter, so the respelling rule is added
        # the model declares each respelled name with its exact source text; fact_issues later looks that text up in the cited evidence
        names += (f" The evidence may spell a name in another language than the letter ({LANGNAME[lang]}). Then write the name the usual way in {LANGNAME[lang]} and add it to \"names\": "
                  "{\"your spelling\": \"the exact text from the evidence\"}.")
    gaps = plan.get("gap_terms", [])  # tools the posting asks for and the profile does not show
    missing = ("- The posting asks for the following, and the profile does not show it. Never claim it, and do not hint at it: " + ", ".join(gaps) + ".") if gaps else ""  # forbid claiming them and hinting at them; no rule at all when the plan has no gaps
    words = [w for w in cov.get("banned_words", [])]  # banned words of the style pack, told to the model before the checker enforces them
    chars = style.get("banned_chars", "")  # banned characters sit at the top level of the style pack, not under cover
    tone = f"Tone: {cov['tone'][lang] if isinstance(cov['tone'], dict) else cov['tone']}."  # the tone is per language when given as a table, else one text for both
    avoid = (" Avoid these words and phrases: " + ", ".join(words) + ".") if words else ""  # listed only when the pack bans words
    never = (" Never use these characters: " + " ".join(chars) + ".") if chars else ""  # characters are joined with spaces so that each one can be read
    return prompt_text("cover_rules", numbers_rule=numbers, names_rule=names, missing_rule=missing, style=tone + avoid + never)  # tone, avoided words and banned characters become one line of the template


def budget_text(style: dict, lang: str) -> str:
    """The length target in words or characters."""
    hi = budget_of(style, lang)  # the same limit that trim_to_budget and the check enforce
    return f"{hi} words" if lang == "en" else f"{hi} characters"  # English counts words, Korean counts characters


def allocation(paras: list[dict], budget: int) -> dict:
    """How much of the budget each paragraph may use: the opening and the motivation a fixed share, the closing a small one, and a duty
    paragraph a base plus a share for every posting line it answers. Models keep to a limit per paragraph better than to one for the letter."""
    weight = {p["id"]: {"opening": 1.8, "motivation": 1.6, "closing": 0.6}.get(p["kind"], 0.8 + 0.9 * len(p["lines"])) for p in paras}  # the opening and the motivation get a fixed share, the closing a small one, a duty paragraph more for each line it answers
    total = sum(weight.values())  # shares are relative, so they are scaled to the budget below
    return {pid: max(10, int(budget * w / total)) for pid, w in weight.items()}  # at least 10, so a small budget never gives a paragraph a zero limit


def plan_listing(paras: list[dict], plan: dict, limits: dict | None = None, unit: str = "words") -> str:
    """The paragraph plan as the prompt shows it."""
    by_id = {l["id"]: l for l in plan["lines"]}  # planned lines by id, to print the lines of each paragraph
    out = []  # one text block per paragraph
    for p in paras:  # in the letter's order
        row = f"{p['id']} ({p['kind']}): {KIND_PURPOSE[p['kind']]}" + (f" At most {limits[p['id']]} {unit}." if limits else "")  # header with the paragraph's purpose and, when limits are given, its size limit
        if p.get("theme"):  # the paragraph's theme, which a person may have edited in plan.json
            row += f"\n   Theme: {p['theme']}"  # under the paragraph's header
        if p["kind"] in ("opening", "motivation") and plan.get("direction"):  # a direction the person wrote into the plan
            row += f"\n   The person's stated direction (their own words; you may restate it as a framing sentence): {plan['direction']}"  # a frame sentence may restate it
        for x in p["lines"]:  # the posting lines this paragraph answers, in the posting's order
            row += f"\n   {x}. {by_id[x]['text']}" + (f"  [not shown by the profile: {', '.join(by_id[x]['missing'])}]" if by_id[x]["missing"] else "")  # tools the profile lacks are flagged, so the model does not claim them
        if p["pool"]:  # the evidence ids this paragraph may cite
            row += "\n   Evidence to use: " + ", ".join(p["pool"])  # ids only; the text of the evidence comes in the evidence block of the prompt
        out.append(row)  # one block per paragraph
    return "\n".join(out)  # the blocks go into the prompt as one text


def ask_model(task: str, prompt: str, backend: str | None):
    """One model call that must return {"paragraphs": [...]}; None when the model is unavailable or never gets the form right."""
    try:  # a model call fails in two different ways, and the caller treats them differently
        return llm.run(task, prompt, system=SYSTEM, want_json=True, required=("paragraphs",), backend=backend)  # llm.run parses the JSON, checks the required key and asks again once when the shape is wrong
    except llm.LLMUnavailable as e:  # no backend or no login: the exception itself travels back
        return e  # the caller reports why
    except ValueError:  # the model answered, but never in the required shape
        return None  # None means an unusable answer; draft turns it into the skeleton text


def check_paragraph(par: dict, sents: list[dict], ctx: Ctx) -> tuple[list[dict], list[dict]]:
    """Fact-check the sentences of one paragraph. Returns (kept sentences, dropped [{text, issues}])."""
    keep, drop = [], []  # sentences that pass, and the rejected ones with their issues
    for s in sents:  # each sentence is judged alone, so one bad sentence never costs its neighbours
        if not s["ev"] and par["kind"] in ("opening", "motivation", "closing"):  # no evidence in a framing paragraph: a framing sentence
            s["frame"] = True  # marked, so fact_issues accepts the missing ids as intended
        bad = fact_issues(s, par["kind"], ctx)  # the paragraph kind decides where a framing sentence may stand
        if bad:  # a sentence with any issue is dropped
            drop.append({"paragraph": par["id"], "text": s["text"], "issues": bad})  # keep the text and the reasons: the repair request and the report show them
        else:  # nothing wrong with the sentence
            keep.append(s)  # a clean sentence stays in the paragraph
    return keep, drop  # both lists go back to the caller, which tracks the dropped ones


def draft(profile: dict, plan: dict, *, style: dict | None = None, resume: list[str] | None = None, backend: str | None = None, repairs: int = 1,
          raw: list | None = None) -> dict:
    """Write the letter: one model call for the body, one optional call to repair what the checks rejected."""
    lang = plan["lang"]  # the plan fixes the language of the letter
    U = units_of(profile, lang)  # evidence is read from the profile as it is now, so stale_issues can notice a changed profile
    style = style or load_style(None)  # the default style pack when the caller gives none
    glossary = F.glossary_of(profile)  # names across languages, from the profile itself
    ctx = make_ctx(U, plan, style, glossary)  # what every sentence is checked against: allowed names, tool vocabulary, gap terms, glossary
    resume = resume if resume is not None else resume_lines(profile, lang)  # an explicit empty list means no resume to compare with; only None falls back to the profile's resume text
    lex = ctx.lex  # word matching, to pick the evidence blocks that fit the posting
    paras = paragraph_plan(plan, U, lex)  # the fixed skeleton of the letter: kind, lines and evidence pool of each paragraph
    by_line = {l["id"]: l["text"] for l in plan["lines"]}  # line texts, for the focus of each project
    everything = " ".join(l["text"] for l in plan["lines"])  # all posting lines as one text: the focus of the opening and the motivation
    focus = {}  # id to the lines of the paragraphs whose pool holds it, used to rank the blocks of long projects
    for p in paras:  # each paragraph
        for i in p["pool"]:  # each id it may cite
            focus[i] = (focus.get(i, "") + " " + (" ".join(by_line[x] for x in p["lines"]) or everything)).strip()  # the lines of the paragraphs it serves; the opening and motivation take the whole posting
    mixed = lang == "en" and hangul_share(" ".join(u["text"] for u in U["units"])) > 0.2  # evidence in Korean, letter in English
    ids = list(dict.fromkeys(i for p in paras for i in p["pool"]))  # every id any paragraph may cite, once, for the evidence block of the prompt
    rules = rules_text(plan, style, lang, mixed or lang == "ko")  # the respelling rule is always given for a Korean letter, and for an English letter over Korean evidence
    limits = allocation(paras, budget_of(style, lang))  # a word limit for every paragraph, from the budget of the letter
    post = plan["posting"]  # company, role and overview of the posting
    # prompt fields that the draft call and the repair call have in common
    shared = dict(language=LANGNAME[lang], role=post.get("role") or "(role not stated)",
                  at_company=f" at {post['company']}" if post.get("company") else "", rules=rules)
    calls = 0  # model calls actually made, reported in the stats
    # the one call for the whole body: paragraph plan with limits, size target, evidence and rules
    result = ask_model("cover-draft", prompt_text("cover_draft", overview=post.get("overview", "") or "(none)", plan=plan_listing(paras, plan, limits, "words" if lang == "en" else "characters"),
                                                  words=budget_text(style, lang), evidence=evidence_listing(U, lex, ids, focus, glossary), **shared), backend)  # the glossary line ends the evidence block
    calls += 1
    if raw is not None and isinstance(result, dict):  # only a usable answer is worth keeping for audit
        raw.append({"task": "cover-draft", "answer": result})  # what the model wrote, kept for audit and for re-checking after a rule change
    # starts empty and is filled below; the plan travels along so that check can run on this file alone
    cover = {"schema": SCHEMA_COVER, "lang": lang, "job": {"company": post.get("company", ""), "role": post.get("role", "")},
             "signature": display_name(profile, lang), "paragraphs": [], "dropped": [], "unresolved": [], "plan": plan}
    if not isinstance(result, dict):  # no model: an empty skeleton that a person can fill
        cover["paragraphs"] = [{"id": p["id"], "kind": p["kind"], "duties": p["lines"], "sentences": [], "todo": p["pool"]} for p in paras]  # one empty paragraph per planned paragraph; todo lists the evidence ids a person may use
        cover["why_empty"] = str(result) if isinstance(result, Exception) else "the model's answer was not usable"  # the exception text when the backend was unavailable, else a fixed reason
        cover["stats"] = stats_of(cover, 0)  # nothing was written, so no call counts
        return cover  # stop before the checks: there is nothing to check in a skeleton
    got = {str(p.get("id")): p for p in as_list(result.get("paragraphs")) if isinstance(p, dict)}  # the model's paragraphs by id; anything that is not an object is ignored
    for p in paras:  # walk the planned paragraphs, so the letter keeps the plan's order and ids and extra paragraphs from the model are ignored
        sents = [x for x in (norm_sentence(s) for s in as_list((got.get(p["id"]) or {}).get("sentences"))) if x]  # normalise whatever shape the model used; entries without text vanish
        keep, drop = check_paragraph(p, sents, ctx)  # the fact check decides per sentence
        cover["paragraphs"].append({"id": p["id"], "kind": p["kind"], "duties": p["lines"], "sentences": keep})  # the line ids are kept so that coverage can be checked later
        cover["dropped"] += drop  # rejected sentences are listed for the repair request and the report
    for _ in range(repairs):  # one repair round: rewrite the paragraphs that lost sentences, repeat the resume or leave a line unanswered
        todo = repair_targets(cover, paras, plan, resume, style)  # paragraphs with a dropped sentence, a resume repeat or an unanswered line
        if not todo:  # a clean draft needs no second call
            break  # no second call is needed, so the rounds end
        fixed = ask_model("cover-repair", prompt_text("cover_repair", items=repair_listing(cover, paras, todo, plan, ctx, resume), evidence=evidence_listing(  # ask only about those paragraphs, with the verdict on each sentence
            U, lex, list(dict.fromkeys(i for p in paras if p["id"] in todo for i in p["pool"])), focus, glossary), **shared), backend)  # the evidence pool of just the paragraphs being rewritten
        calls += 1  # the repair is a model call too
        if raw is not None and isinstance(fixed, dict):  # the same audit record as for the first answer
            raw.append({"task": "cover-repair", "answer": fixed})  # the repair answer as the model wrote it, before any check
        if not isinstance(fixed, dict):  # no usable repair: keep the first draft as it is
            break  # a repair that failed ends the rounds
        back = {str(p.get("id")): p for p in as_list(fixed.get("paragraphs")) if isinstance(p, dict)}  # the rewritten paragraphs by id
        for idx, p in enumerate(paras):  # idx is also the position in cover["paragraphs"], which still holds every planned paragraph here
            if p["id"] not in todo or p["id"] not in back:  # leave paragraphs that were not asked about, or that the model did not return
                continue  # on to the next paragraph
            sents = [x for x in (norm_sentence(s) for s in as_list(back[p["id"]].get("sentences"))) if x]  # same normalising as for the first draft
            keep, drop = check_paragraph(p, sents, ctx)  # rewritten sentences face the same fact check
            cover["paragraphs"][idx]["sentences"] = keep  # replaces all sentences of that paragraph; the model was told to repeat the accepted ones that still fit
            cover["dropped"] += [{**d, "round": "repair"} for d in drop]  # tagged with the round, so that repair_listing can leave them out of a later request
    cover["paragraphs"] = [p for p in cover["paragraphs"] if p["sentences"]]  # a paragraph with no sentence left is not printed
    cover["dropped"] += trim_to_budget(cover, plan, style, limits)  # the model may write more than one page holds
    for issue_ in coverage_issues(cover["paragraphs"], plan) + repeat_report(cover, resume, style) + stale_issues(U, plan):  # what is still wrong after the repair; issue_ keeps the issue() helper from being shadowed
        cover["unresolved"].append(issue_)  # what the model could not fix; `check` fails on these
    cover["stats"] = stats_of(cover, calls)  # counts of what is printed, plus the model calls made
    return cover  # the letter, with its dropped and unresolved lists


def budget_of(style: dict, lang: str) -> int:
    """The size limit of the body: words in English, characters in Korean."""
    return style["cover"]["max_words"]["en"] if lang == "en" else style["cover"]["max_chars"]["ko"]  # each language has its own key because the two units differ


def size_of(cover: dict) -> int:
    """The size of the body in the unit of its limit."""
    w, c = words_of(cover)  # both counts at once; the letter's language picks one
    return w if cover["lang"] == "en" else c  # English budgets count words, Korean budgets characters


def par_size(par: dict, lang: str) -> int:
    """The size of one paragraph in the unit of the budget."""
    text = " ".join(x["text"] for x in par["sentences"])  # the sentences joined as the paragraph prints them
    return len(text.split()) if lang == "en" else len(re.sub(r"\s", "", text))  # the same unit as the budget, so the size can be held against the paragraph's limit


def relevance(sentence: dict, par: dict, plan: dict, lang: str) -> float:
    """How closely a sentence speaks to the posting lines it answers: shared content words (syllable pairs in Korean), scaled by its length."""
    ids = sentence.get("duties") or par.get("duties") or []  # the lines this sentence answers; a sentence without tags answers its paragraph's lines
    lines = " ".join(l["text"] for l in plan["lines"] if l["id"] in ids)  # the text of those posting lines
    if not lines:  # nothing to compare with
        return 1.0  # the opening, the motivation and the closing answer no line: they are cut last
    def words(text):  # content words of a text; the form depends on the language
        if lang == "ko":  # Korean endings change the form of a word, so overlapping syllable pairs are compared instead of whole words
            return {w[i:i + 2] for w in re.findall(r"[가-힣]{2,}", text) for i in range(len(w) - 1)}  # every overlapping pair of syllables in each Hangul word
        return {w.rstrip("s") for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in STOP_EN}  # customers ~ customer
    a, b = words(sentence["text"]), words(lines)  # word sets of the sentence and of the lines it answers
    return len(a & b) / (len(a) ** 0.5 + 1)  # shared words, divided by the square root of the sentence's own words so long sentences do not win by length alone; +1 avoids a zero divisor


def trim_to_budget(cover: dict, plan: dict, style: dict, limits: dict) -> list[dict]:
    """Cut the letter to its budget. The paragraph that is furthest over its own limit gives up the sentence that speaks least to its posting
    lines, as long as no planned line loses its only answer and no paragraph is left empty. Returns the dropped sentences."""
    out, hi, lang = [], budget_of(style, cover["lang"]), cover["lang"]  # the dropped sentences, the limit for the whole body, and the letter's language
    while size_of(cover) > hi:  # cut one sentence per round until the body fits
        pick = None  # the (paragraph, sentence) to cut in this round
        open_lines = {i["id"] for i in coverage_issues(cover["paragraphs"], plan) if i["code"] == "missing_line"}  # lines that already lack an answer: a cut cannot make that worse
        order = sorted(enumerate(cover["paragraphs"]), key=lambda x: (-(par_size(x[1], lang) - limits.get(x[1]["id"], 0)), -x[0]))  # most over first
        for pi, par in order:  # the paragraph furthest over comes first; if it has nothing safe to give, the next one is tried
            if len(par["sentences"]) < 2:  # a paragraph with one sentence cannot give one up
                continue  # a paragraph keeps at least one sentence
            options = []  # every sentence of this paragraph that could safely go
            for si, sent in enumerate(par["sentences"]):  # try each sentence as the one to cut
                trial = copy.deepcopy(cover["paragraphs"])  # work on a copy; the real letter changes only after the choice is made
                del trial[pi]["sentences"][si]  # the letter as it would be without this sentence
                if {i["id"] for i in coverage_issues(trial, plan) if i["code"] == "missing_line"} <= open_lines:  # refuse any cut after which another planned line has no answer
                    options.append((relevance(sent, par, plan, lang), -si, si))  # least relevant first, the later one on a tie
            # the first paragraph in order that has a safe cut gives it up, and the search ends
            if options:
                pick = (pi, min(options)[2])
                break
        if pick is None:  # every paragraph was tried and none could give anything up
            break  # nothing can go without losing an answer: `check` reports the length
        gone = cover["paragraphs"][pick[0]]["sentences"].pop(pick[1])  # now cut the chosen sentence from the real letter
        out.append({"paragraph": cover["paragraphs"][pick[0]]["id"], "text": gone["text"], "issues": [issue("over_budget", detail=hi)], "round": "trim"})  # recorded with round trim, so the report can tell cuts for length from fact-check drops
    return out  # the dropped sentences join the list of dropped ones in draft


def stale_issues(U: dict, plan: dict) -> list[dict]:
    """The plan was made from other evidence than the profile holds now: its ids may point at changed text."""
    if not plan.get("evidence_hash"):  # no fingerprint, nothing to compare
        return []  # a hand-made plan has no fingerprint
    used = {e for l in plan.get("lines", []) for e in l.get("ev", [])} | set(plan.get("fit", []))  # the ids the plan relied on, the same set plan() hashed
    return [] if evidence_hash(U, used) == plan["evidence_hash"] else [issue("stale", id=", ".join(sorted(used))[:60])]  # a different hash means the text behind those ids changed; the id list in the issue is capped at 60 characters


def repeat_report(cover: dict, resume: list[str], style: dict) -> list[dict]:
    """The repeats that remain in the final letter, as issues with their place."""
    out = []  # issues with their place in the letter
    for (pi, si), (n, sh) in repeat_hits(cover["paragraphs"], resume, cover["lang"], style).items():  # the same hits as the check, with paragraph id and sentence index so a person can find them
        out.append({**issue("repeat", detail=sh[:60]), "paragraph": cover["paragraphs"][pi]["id"], "sentence": si})  # the shared text, cut to 60 characters, is the detail
    return out  # the repeats that remain after drafting


def repair_targets(cover: dict, paras: list[dict], plan: dict, resume: list[str], style: dict) -> list[str]:
    """Paragraph ids worth another model call: a sentence was dropped, a sentence repeats the resume, or a planned line lost its answer."""
    hit = {p["id"] for p in paras if any(d["paragraph"] == p["id"] for d in cover["dropped"])}  # paragraphs that lost a sentence to the fact check
    live = [p for p in cover["paragraphs"] if p["sentences"]]  # only paragraphs that still have sentences; repeat_hits reports positions in this list
    for (pi, _), _v in repeat_hits(live, resume, cover["lang"], style).items():  # pi indexes live, not paras, so it is mapped back to an id through live
        hit.add(live[pi]["id"])  # a paragraph with a sentence copied from the resume
    lost = {i["id"] for i in coverage_issues(live, plan) if i["code"] == "missing_line"}  # posting lines that no sentence answers any more
    hit |= {p["id"] for p in paras if set(p["lines"]) & lost}  # the paragraphs planned to answer those lines
    return [p["id"] for p in paras if p["id"] in hit]  # in the letter's order, so the request lists paragraphs as the letter does


def repair_listing(cover: dict, paras: list[dict], todo: list[str], plan: dict, ctx: Ctx, resume: list[str]) -> str:
    """The repair request: each paragraph with its accepted sentences and the verdict on the rejected ones."""
    by_id = {l["id"]: l for l in plan["lines"]}  # planned lines by id, to print what each paragraph answers
    blob = "\n".join(resume)  # the resume as one text, to test each accepted sentence for a repeat again
    out = []  # one block per paragraph to rewrite
    for p in paras:  # in the letter's order
        if p["id"] not in todo:  # paragraphs with nothing to fix are not sent
            continue  # on to the next paragraph
        cur = next((c for c in cover["paragraphs"] if c["id"] == p["id"]), {"sentences": []})  # the paragraph as it stands now; an empty stand-in when every sentence was dropped
        row = [f"{p['id']} ({p['kind']}): {KIND_PURPOSE[p['kind']]}"]  # header with the paragraph's purpose
        row += [f"   answers {x}. {by_id[x]['text']}" for x in p["lines"]]  # the posting lines the paragraph must answer
        if p["pool"]:  # the evidence ids the rewrite may cite
            row.append("   evidence to use: " + ", ".join(p["pool"]))  # ids only; the text is in the evidence block of the request
        for s in cur["sentences"]:  # accepted sentences are shown, so the model keeps them when they still fit
            n, sh = shared_run(s["text"], blob, ctx.lang)  # the longest run this sentence shares with the resume
            verdict = f"rejected: repeats the resume (\"{sh[:60]}\"); say it in other words" if is_repeat(n, len(run_tokens(s["text"], ctx.lang)), ctx.lang, ctx.style) else "accepted"  # an accepted sentence can still copy the resume; then the model is told to say it in other words
            row.append(f"   - [{verdict}] {s['text']}")  # the verdict in brackets, then the sentence
        for d in cover["dropped"]:  # sentences the fact check rejected
            if d["paragraph"] == p["id"] and d.get("round") != "repair":  # only this paragraph's rejections, and not those of an earlier repair round
                row.append(f"   - [rejected: {'; '.join(issue_text(i) for i in d['issues'])}] {d['text']}")  # the reasons in plain words, as the report prints them
        out.append("\n".join(row))  # the paragraph's lines become one block
    return "\n\n".join(out)  # a blank line between the paragraphs


def words_of(cover: dict) -> tuple[int, int]:
    """(words, characters) of the body as printed."""
    text = " ".join(s["text"] for p in cover["paragraphs"] for s in p["sentences"])  # the body as printed: all sentences of all paragraphs in order
    return len(text.split()), len(re.sub(r"\s", "", text))  # words split at spaces; characters ignore all whitespace, the Korean unit


def stats_of(cover: dict, calls: int) -> dict:
    """Counts for the draft summary."""
    w, c = words_of(cover)  # both counts, so the summary can show either
    return {"words": w, "chars": c, "sentences": sum(len(p["sentences"]) for p in cover["paragraphs"]), "calls": calls}  # the counts kept in cover.json and shown in the draft summary


# the check
EVIDENCE_CODES = {"unknown_id", "no_ev", "frame_ev", "frame_where"}  # problems with the ids of a sentence
STYLE_CODES = {"banned_char", "banned_pattern", "banned_word", "too_long"}  # problems with the wording
GAP_CODES = {"gap_term"}  # claims beyond the profile
CLAIM_CODES = {"claim"}  # a part claimed larger than the evidence states


def pdf_pages(pdf: str) -> int:
    """Number of pages of a PDF."""
    return pdftools.info(pdf)["pages"]  # 0 for an unreadable file, which makes the one-page check fail


def orphan_lines(pdf: str) -> list[str]:
    """Paragraph ends that leave one word alone on the last line (a polish item, not a failure)."""
    xml = pdftools.bbox_layout(pdf)  # every text line and word with its position
    out = []  # polish findings
    for pn, body in enumerate(re.findall(r"<page[^>]*>(.*?)</page>", xml, re.S), 1):  # page by page, numbered from 1 for the messages
        rows = []  # (top, left, right, bottom, words) of every text line
        for m in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', body, re.S):  # the position box of each text line and the markup inside it
            words = re.findall(r"<word[^>]*>(.*?)</word>", m.group(5), re.S)  # the words of that line
            rows.append((float(m.group(2)), float(m.group(1)), float(m.group(3)), float(m.group(4)), words))  # top first, so sorting puts the lines in reading order
        rows.sort()  # top to bottom, so neighbours in the list are neighbours on the page
        wide = [r for r in rows if len(r[4]) >= 8]  # prose lines
        if not wide:  # a page without prose lines has no paragraph ends to judge
            continue  # on to the next page
        right, left = max(r[2] for r in wide), min(r[1] for r in wide)  # the text block's edges, taken from the full prose lines
        for prev, cur in zip(rows, rows[1:]):  # each line against the line above it
            same_paragraph = cur[0] - prev[3] < 5  # a paragraph gap is wider than the space between two lines of one paragraph
            if len(cur[4]) == 1 and abs(cur[1] - left) < 4 and prev[2] >= right - 8 and len(prev[4]) >= 8 and same_paragraph:  # a single word at the left edge, under a prose line that ran to the right edge, inside one paragraph
                out.append(f"p{pn}: '{cur[4][0]}' alone after '{' '.join(prev[4][-3:])}'")  # page number, the lone word and the words before it
    return out  # never a failure; layout_issues passes these on as polish items


def layout_issues(pdf: str) -> tuple[list[str], list[str]]:
    """(problems, polish items) of the rendered page: body touching the footer, a number split from its unit, lone words at paragraph ends."""
    bad, polish = [], []  # failures, and items that are only worth a look
    try:  # the line-level checks of the resume code are optional here
        import check_render as CR  # the same line-level checks the resume gets
        bad += CR.footer_clearance(str(pdf)) + CR.number_unit_split(str(pdf))  # a body touching the footer and a number split from its unit are failures
    except ImportError:  # without that module the rest still runs
        pass  # the polish check below still runs, so only the resume checks are lost
    polish += orphan_lines(pdf)  # lone words at paragraph ends are a polish item, never a failure
    return bad, polish  # the check treats the two lists differently


def check_cover(profile: dict, cover: dict, *, plan: dict | None = None, pdf: str | None = None, resume_spec: str | None = None,
                style_spec: str | None = None, hints=()) -> dict:
    """Run every check of a letter. Returns {ok, checks: [{key, status, detail, items}], sentences, lines}."""
    lang = cover["lang"]  # the letter's own language drives the checks, not the interface language
    plan = plan or cover.get("plan")  # the plan saved inside the cover file when no plan file is given
    style = load_style(style_spec or (plan or {}).get("style") or "default", hints)  # the explicit style first, then the one the plan was made with, then the default
    U = units_of(profile, lang)  # evidence as the profile holds it now
    shell = {"lang": lang, "posting": {**cover.get("job", {}), "overview": ""}, "gap_terms": [], "lines": []}  # a hand-written letter has no plan
    ctx = make_ctx(U, plan or shell, style, F.glossary_of(profile))  # the shell supplies only the job names, so allowed names still come from the cover file
    paras = cover["paragraphs"]  # the paragraphs as saved, in print order
    flagged, total = [], 0  # sentences with problems, and how many sentences were looked at
    for par in paras:  # every paragraph, whatever its kind
        for si, raw in enumerate(par["sentences"]):  # si stays in the report so a person can find the sentence
            s = norm_sentence(raw)  # a hand-edited file may hold plain strings or odd objects; same normalising as at drafting time
            total += 1  # empty sentences count too
            if s is None:  # no text at all: report it as an empty sentence and go on
                flagged.append({"paragraph": par["id"], "sentence": si, "text": "", "issues": [issue("empty")]})  # reported as an empty sentence, with its place
                continue  # nothing more to check on an empty sentence
            if not s["ev"] and par.get("kind") in ("opening", "motivation", "closing"):  # framing paragraphs may hold sentences without evidence
                s["frame"] = True  # same rule as at drafting time
            bad = fact_issues(s, par.get("kind", "duties"), ctx)  # a file without paragraph kinds is read as duties, the strictest place for a framing sentence
            if bad:  # keep the sentence text for the report
                flagged.append({"paragraph": par["id"], "sentence": si, "text": s["text"], "issues": bad})  # paragraph id and position let the report point at the sentence
    checks = []  # one entry per check, in the order they are printed

    def add(key, status, detail, items=()):  # append one check result; items are the flagged places
        checks.append({"key": key, "status": status, "detail": detail, "items": list(items)})  # items are copied into a list, so the result owns its data

    def pick_codes(codes):  # the flagged sentences that have an issue of these codes, with only those issues
        out = []  # the flagged sentences that remain for this check
        for f in flagged:  # every flagged sentence once
            sub = [i for i in f["issues"] if i["code"] in codes]  # only the issues of the wanted codes, so one problem is reported under one check
            if sub:  # sentences with no issue of this kind drop out
                out.append({**f, "issues": sub})  # the same sentence record with a reduced issue list
        return out  # the flagged items of one check

    rest = EVIDENCE_CODES | STYLE_CODES | GAP_CODES | CLAIM_CODES  # codes that have their own check; whatever is left belongs to the facts check
    ev_items = pick_codes(EVIDENCE_CODES)  # problems with the evidence ids
    stale = [{"paragraph": "-", "sentence": 0, "text": "", "issues": [i]} for i in (stale_issues(U, plan) if plan else [])]  # the profile may have changed since the plan was made
    add("evidence", "fail" if ev_items or stale else "pass", t("r_evidence", n=total, k=len(ev_items)), ev_items + stale)  # a stale plan fails this check too, because its ids may point at changed text
    fact_items = [{**f, "issues": [i for i in f["issues"] if i["code"] not in rest]} for f in flagged if any(i["code"] not in rest for i in f["issues"])]  # numbers, names, organisations and empty sentences: what remains after the other checks took their codes
    add("facts", "fail" if fact_items else "pass", t("r_facts", n=total, k=len(fact_items)), fact_items)  # k counts flagged sentences, not issues
    resume, src = resume_source(resume_spec, profile, lang)  # src says where the resume text came from and is shown in the detail
    hits = repeat_hits(paras, resume, lang, style)  # sentences that copy the resume, by position
    # each hit becomes a flagged item; the shared text, cut to 60 characters, is the detail
    rep_items = [{"paragraph": paras[pi]["id"], "sentence": si, "text": paras[pi]["sentences"][si]["text"], "issues": [issue("repeat", detail=sh[:60])]}
                 for (pi, si), (n, sh) in hits.items()]
    add("repeat", "fail" if rep_items else "pass", t("r_repeat", n=total, m=len(resume), k=len(rep_items)) + f" [{src}]", rep_items)
    if plan and plan.get("lines"):  # duty coverage needs a plan with lines
        # cov holds unanswered lines, answers out of order and answers to lines the plan marks none
        cov = coverage_issues(paras, plan)
        wanted = [l for l in plan["lines"] if l.get("use")]  # the lines the plan wants answered
        done = len(wanted) - len([c for c in cov if c["code"] == "missing_line"])  # wanted lines minus the unanswered ones
        order_ok = not any(c["code"] == "order" for c in cov)  # shown in the detail as a word
        add("duties", "fail" if cov else "pass", t("r_duties", a=done, b=len(wanted), order=t("order_ok" if order_ok else "order_bad")),  # any coverage issue fails, including an answer to a line marked none
            [{"paragraph": "-", "sentence": 0, "text": "", "issues": [c]} for c in cov])  # each issue becomes an item without sentence text
    else:  # no plan means nothing to compare with: skipped, never passed
        add("duties", "skip", t("r_skip_plan"))  # the detail says the plan is missing
    claim_items = pick_codes(CLAIM_CODES)  # led, designed, built or owned where the evidence says helped, proposed or with the team
    add("claims", "fail" if claim_items else "pass", t("r_claims", n=total, k=len(claim_items)), claim_items)  # a claim beyond the evidence fails the letter
    gap_items = pick_codes(GAP_CODES)  # claims of tools the profile lacks
    add("gaps", "fail" if gap_items else "pass", t("r_gaps", k=len(gap_items), m=len([c for c in (coverage_issues(paras, plan) if plan else []) if c["code"] == "gap_line"])), gap_items)  # answers to lines marked none are only counted here; they fail the duties check
    sty = pick_codes(STYLE_CODES)  # banned characters, patterns and words, and run-on sentences
    add("style", "fail" if sty else "pass", t("r_style", k=len(sty)), sty)  # k counts flagged sentences
    # the body is measured in both units, but only the language's own unit is held against the style pack's limit
    w, c = words_of(cover)
    lim = budget_of(style, lang)  # the limit from the style pack, the same one trim_to_budget used
    used = w if lang == "en" else c
    add("length", "fail" if used > lim else "pass", t("r_length", w=f"{w} words" if lang == "en" else f"{c} chars", lim=lim),  # the detail names the unit
        [{"paragraph": "-", "sentence": 0, "text": "", "issues": [issue("words", w=used, lim=lim)]}] if used > lim else [])  # the failing item carries both numbers for the message
    if pdf and pathlib.Path(pdf).is_file():  # the page and layout checks need the rendered file; a path that does not exist counts as not given
        n = pdf_pages(pdf)  # pages of the rendered letter
        add("page", "pass" if n == 1 else "fail", t("r_page", p=n), [] if n == 1 else [{"paragraph": "-", "sentence": 0, "text": "", "issues": [issue("pages", p=n)]}])  # exactly one page passes; zero pages, an unreadable file, fails
        bad, polish = layout_issues(pdf)  # failures and polish items from the rendered page
        add("layout", "fail" if bad else "pass", t("r_layout", k=len(bad)) + (f"; polish: {len(polish)}" if polish else ""),  # polish items do not fail the check; they only add a count to the detail
            [{"paragraph": "-", "sentence": 0, "text": x, "issues": []} for x in bad + polish])  # a layout item has no sentence, so its message goes into the text field
    else:  # no PDF given or found: both checks are skipped, not passed
        add("page", "skip", t("r_skip_pdf"))  # the reason is that no PDF was given
        add("layout", "skip", t("r_skip_pdf"))  # the same reason
    return {"ok": not any(c["status"] == "fail" for c in checks), "checks": checks, "sentences": total,  # ok only when no check failed; skipped checks do not fail it
            "lines": len((plan or {}).get("lines", []))}  # the number of posting lines, for the header line


def print_check(res: dict, out=None) -> None:
    """The check as text: one line per check, the flagged items under it, and a last line with the verdict."""
    out = out or sys.stdout  # the terminal unless the caller gives a stream
    print(t("check_head", sents=res["sentences"], lines=res["lines"]), file=out)  # header: sentences and posting lines that were checked
    for c in res["checks"]:  # one line per check, in the order they ran
        mark = {"pass": "ok  ", "fail": "FAIL", "skip": "skip"}[c["status"]]  # marks of equal width, so the lines stay aligned
        print(f"  [{mark}] {t('c_' + c['key'])}: {c['detail']}", file=out)  # the check's name and its detail
        for it in c["items"][:8]:  # at most eight flagged items per check keep the output short
            why = "; ".join(issue_text(i) for i in it["issues"])  # all issues of the item, in the user's language
            where = f"{it['paragraph']}.{it['sentence'] + 1} " if it["paragraph"] != "-" else ""  # paragraph and a 1-based sentence number; items without a place get none
            print(f"         - {where}{why}{(' | ' + it['text'][:90]) if it['text'] and why else it['text'][:140]}", file=out)  # with a reason the sentence follows after a bar, cut to 90 characters; layout items have no reason and print their text alone, up to 140
    # the count of each status, for the verdict line
    ok = sum(1 for c in res["checks"] if c["status"] == "pass")
    bad = sum(1 for c in res["checks"] if c["status"] == "fail")
    skip = sum(1 for c in res["checks"] if c["status"] == "skip")
    print(t("check_pass", ok=ok, skip=skip) if not bad else t("check_fail", bad=bad, ok=ok, skip=skip), file=out)  # the last line is the verdict


# build

def in_container() -> bool:
    """Inside the render container the tools are on the path, so render/run.sh is not needed."""
    return pathlib.Path("/.dockerenv").exists()  # Docker creates this file in every container it starts


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a render tool: through render/run.sh on the host (LibreOffice and the fonts live in the container), directly inside it.
    On Windows render/run.sh cannot start (a shell script), so OFFEROWL_RENDERER=container there says what to do, as resume.sh does."""
    if not in_container() and sys.platform == "win32":  # the container named on Windows
        import resume  # its message, in both languages
        raise SystemExit(resume.t("container_on_windows"))
    full = cmd if in_container() else [str(ROOT / "render" / "run.sh")] + cmd  # on the host the run.sh script starts the container; inside it the tool runs as it is
    return subprocess.run(full, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")  # run from the repository root so relative paths like src/ work; output is captured for the caller to read


def stage(path) -> str:
    """A path the container can read: inside the repository as is, anywhere else copied to output/_inputs/ first."""
    p = pathlib.Path(path).resolve()  # an absolute path, so that relative_to can tell whether it is inside the repository
    try:  # the container mounts the repository, so a path inside it can be handed over as it is
        return p.relative_to(ROOT).as_posix()  # the path relative to the repository root, with / on every system
    except ValueError:  # outside the repository: the container cannot see the file
        dst = ROOT / "output" / "_inputs" / (hashlib.sha1(str(p).encode()).hexdigest()[:8] + "_" + re.sub(r"[^\w.-]", "_", p.name))  # a hash of the full path keeps two files of the same name apart; odd characters in the name are replaced
        dst.parent.mkdir(parents=True, exist_ok=True)  # the staging folder may not exist yet
        shutil.copy(p, dst)  # copy the file into the mounted tree
        return dst.relative_to(ROOT).as_posix()  # hand the container the path relative to the repository


def out_name(cover_path: pathlib.Path, cfg: dict) -> str:
    """The name of the rendered files: letters, digits, Hangul, - and _ only, so no path or shell character gets through."""
    where = cover_path.resolve().parent  # a file called cover.json is named after its job folder: jobs/<job>/cover/cover.json is named <job>_cover
    if where.name == "cover":  # jobs/<job>/cover/ holds the file
        where = where.parent  # use the job folder's name instead
    base = cfg.get("out") or (where.name + "_" + cover_path.stem if cover_path.stem == "cover" else cover_path.stem)  # a name from the job file wins; a plain cover.json takes the job folder's name so that letters of different jobs do not overwrite each other
    return re.sub(r"[^\w가-힣-]", "_", base)[:60]  # only safe characters, and a bounded length for the file system


def build(profile_path, cover_path, job_path=None, dest=None) -> dict:
    """Render the letter to DOCX and PDF in the container, tightening the spacing until it fits one page. Returns {pdf, docx, pages, density}."""
    cover_path = pathlib.Path(cover_path)  # callers may pass strings
    cfg = read_json(job_path, "job file") if job_path else {}  # render settings come from the optional job file
    out = out_name(cover_path, cfg)  # the base name of the output files
    cfg = {**cfg, "out": out}  # the renderer must write the name that is looked for below
    jobf = ROOT / "output" / "_inputs" / f"{out}.job.json"  # the settings, staged where the container can read them
    jobf.parent.mkdir(parents=True, exist_ok=True)  # the staging folder may not exist yet
    jobf.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")  # the container reads the settings from this file
    pdf, docx = ROOT / "output" / f"{out}.pdf", ROOT / "output" / f"{out}.docx"  # where the renderer will put its results
    for f in (pdf, docx):  # both results
        f.unlink(missing_ok=True)  # a failed build must not leave an old file that looks fresh
    import resume  # the renderer switch (OFFEROWL_RENDERER) lives there
    if resume.renderer() == "html":  # the PC's own Chrome or Edge, no Docker (docs/ARCHITECTURE.md)
        RH = resume.html_renderer()  # src/render_html/render.py
        def write(level):  # the DOCX at one density level, with the same writer the container runs
            w = subprocess.run([resume.node(), "src/cover_form.js", stage(profile_path), stage(cover_path),
                                jobf.relative_to(ROOT).as_posix(), "--density", str(level)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")  # the writer runs on the host here
            return w.returncode, w.stdout[-1200:] + w.stderr[-1200:]  # the exit code and the tail of its output, for the error message
        res = RH.fit_pages(write, docx, pdf, max_pages=1)  # tighter spacing until one page, as the container script does
        if "error" in res or not pdf.exists():  # a failed write or print, or no PDF at all
            raise SystemExit(t("build_fail", log=res.get("error", "")))  # the same failure message as the container path
        info = {"pdf": str(pdf), "docx": str(docx), "pages": res["pages"], "density": res["level"]}  # the same report shape as the container path
    else:  # the container path, unchanged
        script = ('bash src/fonts.sh >/dev/null 2>&1; d=0; n=0; for d in 0 1 2; do '  # fonts first, output silenced; then up to three tries, each with tighter spacing
                  'node src/cover_form.js "$1" "$2" "$3" --density "$d" || exit 3; '  # render the DOCX at this density; exit 3 marks a failure of this step
                  'soffice --headless --convert-to pdf --outdir output "output/$4.docx" >/dev/null || exit 4; '  # convert to PDF; exit 4 marks a failure of LibreOffice
                  'n=$(pdfinfo "output/$4.pdf" | awk \'/^Pages:/{print $2}\'); [ "$n" = 1 ] && break; done; echo "density $d pages $n"')  # stop at the first density that gives one page; the last output line reports density and page count for the host
        r = sh(["bash", "-c", script, "_", stage(profile_path), stage(cover_path), jobf.relative_to(ROOT).as_posix(), out])  # the arguments become $1 to $4 in the script (profile, cover, job settings, output name); _ fills $0
        m = re.search(r"density (\d+) pages (\d+)", r.stdout)  # the script's last line says which density gave how many pages
        if r.returncode != 0 or not pdf.exists() or not m:  # a failed step, a missing PDF or a missing report line all count as a failed build
            raise SystemExit(t("build_fail", log=(r.stdout[-1200:] + r.stderr[-1200:])))  # the tail of both streams, where the error message is
        info = {"pdf": str(pdf), "docx": str(docx), "pages": int(m.group(2)), "density": int(m.group(1))}  # paths inside the repository, pages and density from the script's report
    resume.stamp_meta(pdf, str(profile_path), str(jobf), "cover")  # the letter's title and the person's name, not the build name
    if dest:  # copy the results next to the letter's data
        d = pathlib.Path(dest)  # the folder for the copies
        d.mkdir(parents=True, exist_ok=True)  # it may not exist yet
        for k, f in (("pdf", pdf), ("docx", docx)):  # both results are copied
            shutil.copy(f, d / f"{cover_path.stem}{f.suffix}")  # the copy is named like the cover file, for example cover.pdf beside cover.json
            info[k] = str(d / f"{cover_path.stem}{f.suffix}")  # report the copy as the result
    return info  # paths, page count and the density that was used


# command line

def workspace_hints(folder: pathlib.Path) -> list[pathlib.Path]:
    """Folders where a style pack named in a plan may live: the folder itself and the four above it (for jobs/<job>/cover that reaches the workspace root)."""
    here = pathlib.Path(folder).resolve()  # resolve first, so that '..' and links do not hide a parent
    return [here] + list(here.parents)[:4]  # the nearest folders first: a workspace's style/ sits at most four levels up


def default_dir(posting: pathlib.Path) -> pathlib.Path:
    """Where a posting's cover files go: jobs/<job>/cover/ inside a workspace, else beside the posting."""
    p = posting.resolve()  # absolute, so the parent folders can be inspected
    return p.parent / "cover" if p.parent.parent.name == "jobs" else p.parent  # a posting at jobs/<job>/posting.md puts its files into jobs/<job>/cover; any other posting gets them beside it


def cmd_plan(a) -> int:  # the plan command: posting to plan.json
    prof, post = read_json(a.profile, "profile"), pathlib.Path(a.posting)  # the profile is loaded now; the posting is read as text below
    pl = plan(prof, post.read_text(encoding="utf-8"), lang=a.lang, company=a.company, role=a.role, backend=a.backend,  # options pass through as given; None lets plan() decide
              allow=a.allow, motivation=not a.no_motivation)  # the flag is negative on the command line and positive in plan()
    out = pathlib.Path(a.out) if a.out else default_dir(post) / "plan.json"  # without -o the plan goes next to the posting's cover files
    pl["style"] = a.style or "default"  # remember the style, so draft and check use the same rules without being told again
    write_json(out, pl)  # written before the summary, so the path it prints exists
    kinds = collections.Counter(l["kind"] for l in pl["lines"])  # counts for the summary line
    st = collections.Counter(l["strength"] for l in pl["lines"])  # how many lines are strong, weak or none
    print(t("plan_done", n=len(pl["lines"]), duties=kinds["duty"], reqs=kinds["requirement"], prefs=kinds["preferred"], strong=st["strong"], weak=st["weak"],  # the summary: lines by kind, matches by strength, paragraphs planned
            none=st["none"], groups=len(pl["groups"]), how=pl["matched_by"], path=out))  # the path says where the plan went
    gone = [f"{l['id']} ({l['text'][:40]})" for l in pl["lines"] if l["strength"] == "none"]  # lines the profile cannot show, each with a short quote to recognise it
    if gone:  # say nothing when every line has some evidence
        print(t("plan_gaps", lines="; ".join(gone)))  # one line that lists the lines without evidence
    if pl["gap_terms"]:  # tools that the letter must not claim
        print(t("plan_missing", terms=", ".join(pl["gap_terms"])))  # one line that lists the missing tools
    for n in pl["notes"]:  # notes on how the plan was made, such as a model fallback or trimmed lines
        print(t("plan_warn", why=n))  # each note on its own line
    return 0  # gaps are information, not errors


def cmd_draft(a) -> int:  # the draft command: plan.json to cover.json
    prof, pl = read_json(a.profile, "profile"), read_json(a.plan, "plan")  # both files are needed before anything is written
    plan_dir = pathlib.Path(a.plan).resolve().parent  # outputs and style lookups are relative to the plan's folder
    style = load_style(a.style or pl.get("style"), hints=workspace_hints(plan_dir))  # the command line wins over the style recorded in the plan; style/ is also searched in the folders above the plan
    resume, _ = resume_source(a.resume, prof, pl["lang"])  # what the letter must not repeat; where it came from is not needed here
    raw = [] if a.raw else None  # the model's raw answers are collected only when the raw option asks for them
    cover = draft(prof, pl, style=style, resume=resume, backend=a.backend, repairs=a.repairs, raw=raw)  # the model calls and the fact check happen here
    if a.raw:  # keep the raw answers, so a rule change can be re-checked without new model calls
        write_json(a.raw, raw)  # a list of task and answer records
    cover["style"] = style["name"]  # check loads the same style pack later
    out = pathlib.Path(a.out) if a.out else plan_dir / "cover.json"  # by default cover.json beside the plan
    write_json(out, cover)  # written even for a skeleton, so a person can fill it
    if cover.get("why_empty"):  # no model answered: an empty skeleton was written
        print(t("draft_skeleton", why=cover["why_empty"][:120], path=out))  # the reason is cut, so a long error stays short
        return 2  # exit 2 stops a run: the later steps cannot work on an empty letter
    st = cover["stats"]  # counts for the summary line
    print(t("draft_done", paras=len(cover["paragraphs"]), sents=st["sentences"], dropped=len(cover["dropped"]), words=st["words"], calls=st["calls"], path=out))  # the summary: paragraphs, sentences kept and dropped, words, model calls
    for d in cover["dropped"][:6]:  # the first six rejections are enough to see the pattern
        print(t("draft_drop", code=d["issues"][0]["code"], text=d["text"][:100]))  # the code first, then a cut of the sentence
    for u in cover["unresolved"][:6]:  # problems the repair did not fix
        print("  - " + issue_text(u))  # one line each, in the user's language
    return 1 if cover["unresolved"] else 0  # exit 1 means open problems; a run goes on to build and check anyway


def cmd_build(a) -> int:  # the build command: cover.json to DOCX and PDF
    info = build(a.profile, a.cover, a.job, a.dest or pathlib.Path(a.cover).resolve().parent)  # the results are copied beside the cover file unless a destination is given
    print(t("build_done", pages=info["pages"], density=info["density"], pdf=info["pdf"]))  # pages and spacing step reached, and where the PDF is
    if info["pages"] > 1:  # the loop ends after the tightest spacing, so more than one page is still possible
        cover = read_json(a.cover, "cover")  # read again, to estimate how much to cut
        w, _ = words_of(cover)  # only the word count is needed
        print(t("build_long", pages=info["pages"], over=max(20, w // 8)))  # a rule of thumb: about an eighth of the words, never fewer than 20
        return 1  # exit 1: the letter is not yet one page
    return 0  # one page was reached


def cmd_check(a) -> int:  # the check command: every check of a finished letter
    prof, cover = read_json(a.profile, "profile"), read_json(a.cover, "cover")  # both files are required
    plan_ = read_json(a.plan, "plan") if a.plan else None  # an optional plan file; without it check_cover uses the plan saved in the cover; the underscore avoids the plan() function name
    cdir = pathlib.Path(a.cover).resolve().parent  # the cover file's folder, searched for style packs
    res = check_cover(prof, cover, plan=plan_, pdf=a.pdf, resume_spec=a.resume, style_spec=a.style or cover.get("style"), hints=workspace_hints(cdir))  # the style from the command line, else the one the cover file recorded
    if a.json:  # a machine-readable copy for other programs
        write_json(a.json, res)  # the whole result object, as check_cover returned it
    print_check(res)  # the readable result
    return 0 if res["ok"] else 1  # the exit status mirrors the verdict, for scripts


def cmd_run(a) -> int:  # the run command: all four steps in a row
    post = pathlib.Path(a.posting)  # the posting file
    d = pathlib.Path(a.dir) if a.dir else default_dir(post)  # the output folder: the given one, else the posting's default
    base = ["--backend", a.backend] if a.backend else []  # the backend option goes only to the steps that call a model
    steps = [["plan", a.profile, a.posting, "-o", str(d / "plan.json")] + base + (["--style", a.style] if a.style else []),  # plan: the style option goes here and travels on inside plan.json
             ["draft", a.profile, str(d / "plan.json"), "-o", str(d / "cover.json")] + base + (["--resume", a.resume] if a.resume else []),  # draft: reads the plan just written; the resume is passed only when given
             ["build", a.profile, str(d / "cover.json")] + (["--job", a.job] if a.job else []),  # build: renders cover.json, with optional job settings
             ["check", a.profile, str(d / "cover.json"), "--pdf", str(d / "cover.pdf"), "--json", str(d / "check.json")] + (["--resume", a.resume] if a.resume else [])]  # check: also gets the PDF, so page and layout are checked
    for st in steps:  # in order; each step runs through the entry point the command line uses
        rc = main(st)  # the exit code of this step
        if rc not in (0, 1) or (st[0] != "check" and rc == 2):  # only exit codes 0 and 1 let the next step run
            return rc  # a stop that later steps cannot get past (no model, build failure)
    return rc  # the verdict of the last step, check


def main(argv=None) -> int:  # entry point: builds the parser, picks the handler and returns its exit code
    ap = argparse.ArgumentParser(prog="offerowl cover", description="Cover letters: plan, draft, build and check.")  # named as the launcher calls it, never a path
    sub = ap.add_subparsers(dest="cmd", required=True)  # required, so a bare call prints usage instead of failing later
    # plan: profile and posting are positional, the rest are options
    p = sub.add_parser("plan", help="posting -> lines matched to evidence")
    p.add_argument("profile"), p.add_argument("posting")
    p.add_argument("-o", "--out"), p.add_argument("--lang", choices=("ko", "en")), p.add_argument("--company"), p.add_argument("--role")
    p.add_argument("--backend"), p.add_argument("--style"), p.add_argument("--allow", action="append", default=[], help="a name the letter may use besides the company and role")  # allow can repeat and collects into a list
    p.add_argument("--no-motivation", action="store_true")  # turns the motivation paragraph off
    p.set_defaults(fn=cmd_plan)  # the subcommand names its handler here; main() calls it
    # draft: a plan file takes the place of the posting
    p = sub.add_parser("draft", help="plan -> paragraphs with evidence ids, fact-checked")
    p.add_argument("profile"), p.add_argument("plan")
    p.add_argument("-o", "--out"), p.add_argument("--style"), p.add_argument("--resume"), p.add_argument("--backend")
    p.add_argument("--repairs", type=int, default=1), p.add_argument("--raw", help="write the model's raw answers here")  # repair rounds after the first draft, 0 for none; raw names a file for the model's answers
    p.set_defaults(fn=cmd_draft)  # cmd_draft gets the parsed options
    # build: the cover file, with job settings and a copy destination
    p = sub.add_parser("build", help="render DOCX and PDF")
    p.add_argument("profile"), p.add_argument("cover")
    p.add_argument("--job"), p.add_argument("--dest")
    p.set_defaults(fn=cmd_build)  # cmd_build gets the parsed options
    # check: the cover file; plan, PDF, resume and style are optional
    p = sub.add_parser("check", help="fact check, repeats, duty coverage, style, one page")
    p.add_argument("profile"), p.add_argument("cover")
    p.add_argument("--plan"), p.add_argument("--pdf"), p.add_argument("--resume"), p.add_argument("--style"), p.add_argument("--json")
    p.set_defaults(fn=cmd_check)  # cmd_check gets the parsed options
    # run: the posting and the options of all four steps
    p = sub.add_parser("run", help="plan, draft, build and check in a row")
    p.add_argument("profile"), p.add_argument("posting")
    p.add_argument("--dir"), p.add_argument("--resume"), p.add_argument("--backend"), p.add_argument("--style"), p.add_argument("--job")
    p.set_defaults(fn=cmd_run)  # cmd_run gets the parsed options
    a = ap.parse_args(argv)  # None reads sys.argv; the tests and cmd_run pass a list
    return a.fn(a)  # the handler's exit code becomes the process exit code


if __name__ == "__main__":  # run only as a script, not on import
    sys.exit(main())  # the exit code of main() reaches the shell
