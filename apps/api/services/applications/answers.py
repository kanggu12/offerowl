"""Answers to an application's own questions (a Korean application's 자기소개서 문항, or a form's "Why do you want to work
here?"), each within the question's own limit.

The person adds a job's questions with their limits. The agent writes each answer from the kept facts that speak to that
question (ranked by the rare words they share with it, BM25, so one long project cannot crowd out the fact that answers
it) and the posting, and names the facts it used. Every answer is then checked like every drafted sentence: each number,
name and tool against the facts it cites, the style pack's banned characters and patterns, and its length. One that
fails is written once more with the reasons; what still fails is kept with its problems shown, for the person to fix.
An edit by the person is checked the same way.

Kept in jobs/<job>/questions.json:
    {"questions": [{"id", "text", "limit", "unit": "chars"|"words", "answer", "cites": [fact ids], "state", "issues", "at"}]}
"""
import collections  # word counts
import json  # the questions file, read as the autopilot reads it
import math  # the rarity weight
import re  # words and sentences
import threading  # one writer of a job's questions at a time
import time  # when an answer was written
from pathlib import Path  # paths

from ...core.routing import text_field  # a request's text, or refused
from ...core.workspace import read_json, write_json  # the questions file

UNITS = ("chars", "words")  # a limit in characters (Korean forms count them with spaces) or in words
MAX_QUESTIONS = 12  # questions one job keeps: a form rarely has more
MAX_LIMIT = 5000  # the largest limit one question may set
ROOM = 7000  # characters of facts one answer is written from
SHORT = 0.6  # an answer under this share of its limit is said to be short: a form wants the room used
# words left in an answer for the person to fill: a slot in angle brackets (<link>, <회사명>), a to-do mark, an ellipsis in
# brackets, a template's double braces, a row of circles (○○ 회사), or a bracketed slot name. A form would send them as they are
PLACEHOLDER = re.compile(r"<[^<>\s][^<>\n]{0,38}>|\b(?:TODO|TBD|FIXME)\b|\[(?:…|\.{3})\]|\{\{[^{}\n]{0,40}\}\}|[○◯]{2,}"
                         r"|\[(?:링크|주소|회사명?|이름|날짜|숫자|link|url|name|company|date|number|insert[^\]\n]{0,20})\]", re.I)


def questions_file(ws, jid: str) -> Path:
    """Where a job's questions and answers are kept (job_dir checks the id first)."""
    return ws.job_dir(jid) / "questions.json"


def kept_questions(ws, jid: str) -> list[dict]:
    """A job's application questions as kept, none when it has none (the autopilot asks here before it answers them)."""
    f = questions_file(ws, jid)  # jobs/<job>/questions.json
    return (json.loads(f.read_text(encoding="utf-8")).get("questions") or []) if f.is_file() else []


def placeholders(answer: str) -> list[str]:
    """The slots an answer still holds, as its problems ("placeholder:<link>"): each once, three at most."""
    seen: list[str] = []  # in the order they stand
    for m in PLACEHOLDER.finditer(answer or ""):  # every slot
        if m.group(0)[:40] not in seen:  # once each
            seen.append(m.group(0)[:40])
    return [f"placeholder:{w}" for w in seen[:3]]  # named, as the page shows them


def with_placeholders(q: dict) -> list:
    """An answer's problems as kept, with the slots it still holds: an answer checked before this check existed shows them too."""
    issues = list(q.get("issues") or [])  # as kept
    return issues + [p for p in placeholders(str(q.get("answer") or "")) if p not in issues]  # the slots not said yet


def lang_of(text: str) -> str:
    """The language of a question: Korean when it holds Hangul, else English. The answer is written in it."""
    return "ko" if re.search(r"[가-힣]", text or "") else "en"


def count(text: str, unit: str) -> int:
    """An answer's length as the form counts it: characters with spaces, or words."""
    text = (text or "").strip()  # as it would be pasted
    return len(text.split()) if unit == "words" else len(text)


def words(text: str) -> list[str]:
    """The words of a text for ranking: lower case, Korean words without their last particle, one-letter words left out."""
    out = []  # the words
    for w in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*|[가-힣]+|\d+", (text or "").lower()):  # Latin words, Hangul runs, numbers
        if re.fullmatch(r"[가-힣]+", w) and len(w) > 2:  # a Korean word: its particle goes (프로젝트를 -> 프로젝트)
            w = re.sub(r"(?:으로|에서|에게|까지|부터|이며|이고|하고|와|과|을|를|이|가|은|는|의|에|로|도)$", "", w)
        if len(w) > 1:  # one letter says nothing
            out.append(w)
    return out


def rank(facts: list[dict], query: str, room: int = ROOM) -> list[dict]:
    """The facts that speak to the query, best first, until the room is full. BM25: a word few facts use counts for much
    more than a word many use. A fact with no shared word still comes after the others, so the room is always used."""
    docs = [words(f["text"]) for f in facts]  # each fact's words
    df = collections.Counter(w for d in docs for w in set(d))  # how many facts use each word
    n, avg = len(docs) or 1, (sum(len(d) for d in docs) / len(docs)) if docs else 1.0  # how many, how long on average
    q = set(words(query))  # the question's words
    scored = []  # (score, order, fact)
    for i, (f, d) in enumerate(zip(facts, docs)):  # each fact
        tf = collections.Counter(d)  # its word counts
        s = sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * 2.2 / (tf[w] + 1.2 * (0.5 + 0.5 * len(d) / avg)) for w in q if tf[w])
        scored.append((-s, i, f))  # higher first, then in the profile's order
    out, used = [], 0  # chosen, characters taken
    for _, _, f in sorted(scored):  # best first
        if used + len(f["text"]) > room and out:  # full
            break
        out.append(f)  # taken
        used += len(f["text"])
    return out


PROMPT = """You write one answer to a job application's question, in {language}, from the person's facts below and nothing else.

Question:
<<<
{question}
>>>
Limit: {limit} {unit_words}. Aim for {low} to {limit}.

The posting, for what the company asks for:
<<<
{posting}
>>>

The person's facts, each after its id in brackets:
<<<
{facts}
>>>

Rules:
- Use only these facts. Never add a number, tool, product, client, name or result they do not hold.
- Answer what is asked, in the order it is asked when it asks several things.
- Write the person's own part as the facts state it: helping is not leading, a proposal is not a decision.
- Plain sentences in {language}. No headings, no lists, no quotation of the question, no greeting.
{rules}
Return JSON: {{"answer": "...", "cites": ["id", ...]}}"""


def prompt_for(q: dict, posting: str, facts: list[dict], style: dict, fix: list[str] | None = None) -> str:
    """The prompt for one question, and the reasons to fix when it is written a second time."""
    lang = lang_of(q["text"])  # the answer's language
    unit_words = ("characters including spaces" if lang == "ko" else "characters") if q["unit"] == "chars" else "words"  # how the form counts
    rules = [f"- {r}" for r in ((style.get("resume") or {}).get("rules") or {}).get(lang, [])]  # the person's own rules in words
    if (style.get("resume") or {}).get("numbers") == "forbid":  # a person who writes no figures
        rules.append("- Write no numbers at all; say the scale in words.")
    if fix:  # the second time: what was wrong
        rules.append("- The last answer had these problems; fix every one: " + "; ".join(fix))
    listing = "\n".join(f"[{f['id']}] {f['text']}" for f in facts)  # the facts with their ids
    return PROMPT.format(language="Korean" if lang == "ko" else "English", question=q["text"], limit=q["limit"],
                         unit_words=unit_words, low=int(q["limit"] * 0.85), posting=(posting or "(none)")[:3000],
                         facts=listing, rules="\n".join(rules))


LOCK = threading.Lock()  # questions.json is read, changed and written by the page and by the answering task: one at a time


def problems(q: dict, answer: str, cites: list[str], facts: dict, style: dict, posting: str = "") -> list[str]:
    """What is wrong with one answer, in words (empty means it passes): its length, a number, name or tool its cited facts
    do not hold, and the style pack's banned characters and patterns."""
    import draft  # src/draft.py: the style pack's checks
    import factcheck as F  # src/factcheck.py: numbers, names and tools against the evidence
    out = []  # the problems
    n = count(answer, q["unit"])  # its length as the form counts it
    if not answer.strip():  # nothing written
        return ["empty"]
    if n > q["limit"]:  # over the limit
        out.append(f"too_long:{n}/{q['limit']}")
    elif n < q["limit"] * SHORT:  # far under it
        out.append(f"too_short:{n}/{q['limit']}")
    evidence = "\n".join(facts[c] for c in cites if c in facts) or "\n".join(facts.values())  # what it may say
    # a number, name or tool the facts do not hold; in an English answer every word is Latin, so its words are not each held
    # against the facts (as for a translated sentence, apps/api/services/profile/evidence.py): its numbers and organisations still are
    names = "\n".join(x for x in (q.get("text"), posting) if x)  # the question's and the posting's names: about the company, not the person
    out += [f"unsupported:{x}" for x in F.unsupported(answer, evidence, check_latin=lang_of(q["text"]) == "ko", names=names)]
    out += [f"style:{x}" for x in draft.style_issues(answer, style)]  # banned characters and patterns
    if re.search(r"\*\*[^*\n]+\*\*|^#{1,6}\s", answer, re.M):  # Markdown's bold and headings: a form's box shows the marks as they are (not __init__ or a blank ____)
        out.append("markup")  # said, and a drafted answer is written once more without them; it never stops the export
    out += placeholders(answer)  # a slot left to fill: said, written once more by the agent, and the export waits for it
    return out


def write(q: dict, posting: str, facts: list[dict], style: dict, ask) -> dict:
    """One answer: written, checked, written once more with the reasons when it fails. ask(prompt) is the model's
    answer as a dict. Returns the question with its answer, its cites, its state and its problems."""
    by_id = {f["id"]: f["text"] for f in facts}  # every kept fact, for the check
    chosen = rank(facts, q["text"] + "\n" + (posting or "")[:600])  # the facts that speak to it
    fix = None  # the reasons, the second time
    for _ in range(2):  # once, and once more
        got = ask(prompt_for(q, posting, chosen, style, fix)) or {}  # the model's answer
        answer = re.sub(r"\s+\n", "\n", str(got.get("answer") or "")).strip()  # its words
        cites = [str(c) for c in (got.get("cites") or []) if str(c) in by_id]  # only facts that exist
        issues = problems(q, answer, cites, by_id, style, posting)  # what is wrong
        if not issues:  # it passes
            break
        fix = issues  # tell the second try
    return {**q, "answer": answer, "cites": cites, "state": "drafted", "issues": issues, "at": time.strftime("%Y-%m-%d %H:%M")}


def checked_edit(q: dict, answer: str, facts: list[dict], style: dict, posting: str = "") -> dict:
    """The person's own words for an answer, checked as a drafted one is, against every kept fact: the person may bring in
    a true figure from a fact the draft did not cite, and has no way to change the cites."""
    by_id = {f["id"]: f["text"] for f in facts}  # every kept fact
    issues = problems(q, answer, [], by_id, style, posting)  # no cites: the answer is checked against all the kept facts
    return {**q, "answer": answer.strip(), "state": "edited", "issues": issues, "at": time.strftime("%Y-%m-%d %H:%M")}


# Reading a form's questions from its own words, so nobody types them again: a numbered question, a question mark or a
# Korean request ending ("기술해 주세요"), and the limit written beside it ("500자 이내", "최대 1,000자", "300 words").
LIMIT_RE = re.compile(r"(?:최대|공백\s*(?:포함|제외)|up\s+to|max(?:imum)?\.?)?\s*\(?\s*(\d{1,2}(?:,\d{3})|\d{2,5})\s*"
                      r"(글자|자|bytes?|바이트|단어|words?(?![a-z])|characters?(?![a-z])|chars?(?![a-z]))", re.I)  # a number and its unit
NUMBERED_RE = re.compile(r"^\s*(?:\[\s*\d{1,2}\s*\]|\(?\d{1,2}[.)]|[①-⑳]|Q\s*\d{1,2}[.:)]?|문항\s*\d{1,2}[.:)]?|질문\s*\d{1,2}[.:)]?)\s*")  # 1. 1) [1] ① Q1 문항 1
ASKS_RE = re.compile(r"(\?|？|(?:주십시오|주세요|하십시오|하시오|바랍니다|해\s*주세요|기술|서술|작성|설명)\s*[.)]?$|^(?:describe|tell us|explain|why|what|how)\b)", re.I)  # a question or a request
SECTION_RE = re.compile(r"(자기\s*소개서|자소서|에세이|문항|사전\s*질문|essay|application questions|questions)", re.I)  # a heading over a form's questions


def limit_of(line: str):
    """(limit, unit) written in a line, or None. Bytes count a Korean character as two, so they become half as many characters."""
    m = LIMIT_RE.search(line)  # the first number with a unit
    if not m or m.group(1).startswith("0"):  # none, or a number OCR lost the start of ("]000자")
        return None
    n, unit = int(m.group(1).replace(",", "")), m.group(2).lower()  # the number and its unit
    if unit in ("byte", "bytes", "바이트"):  # a form that counts bytes
        return max(20, min(MAX_LIMIT, n // 2)), "chars"
    if unit.startswith("word") or unit == "단어":
        return max(20, min(MAX_LIMIT, n)), "words"
    return max(20, min(MAX_LIMIT, n)), "chars"


def parse_questions(text: str, strict: bool = False) -> list[dict]:
    """The questions a form or a posting writes out, each with its limit: [{text, limit, unit}]. strict (a posting): only
    a question with a limit, or one under a heading that names the form's questions, so a duty line is never taken."""
    rows, section, last = [], False, None  # the questions; under a questions heading; the last question (a limit may follow it)
    for raw in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()  # one line, tidy
        line = re.sub(r"(?<=[\s(\[])[\]|lI](?=,?\d{3}\s*(?:자|글자|bytes?|바이트|words?|단어))", "1", line)  # OCR's 1 read as ] | l I before a limit
        if not line:
            continue
        lim = limit_of(line)  # a limit written on it
        bare = LIMIT_RE.sub("", line)  # the line without its limit
        bare = re.sub(r"[\(\[]\s*(?:이내|이하|내외|以内)?\s*[\)\]]", "", bare)  # brackets the limit left empty
        bare = re.sub(r"\s*(?:이내|이하|내외)\s*[)\]]?\s*$", "", bare).strip(" -:·|/")  # the limit's own words
        while bare.endswith((")", "]")) and bare.count("(") + bare.count("[") < bare.count(")") + bare.count("]"):  # a bracket whose opening went with the limit
            bare = bare[:-1].rstrip()
        numbered = bool(NUMBERED_RE.match(bare))  # a numbered line
        body = NUMBERED_RE.sub("", bare).strip()  # the question's words
        own = (numbered or bool(lim)) and len(body) >= 2 and bool(re.search(r"[가-힣A-Za-z]", body))  # "1. 지원 동기 (500자)": a numbered line, or one with its own limit, is a question however short (B3-04)
        if len(body) < 8 and not (len(body) >= 4 and "?" in body) and not own:  # a line that only carried a limit (a short question still counts): it belongs to the question before it
            if lim and last is not None and not last.get("_lim"):
                last.update(limit=lim[0], unit=lim[1], _lim=True)
            elif SECTION_RE.search(line):  # a heading
                section = True
            continue
        if len(body) < 40 and SECTION_RE.search(body) and not ASKS_RE.search(body):  # a heading line over the questions
            section = True
            continue
        asks = bool(ASKS_RE.search(body)) or numbered  # it reads as a question
        if not asks or (strict and not lim and not section):  # a duty, a sentence of the posting
            continue
        q = {"text": body[:600], "limit": lim[0] if lim else 0, "unit": lim[1] if lim else ("words" if lang_of(body) == "en" else "chars"), "_lim": bool(lim)}
        rows.append(q)
        last = q
    out = []  # the questions, with a usual limit where none was written
    for q in rows[:MAX_QUESTIONS]:
        out.append({"text": q["text"], "limit": q["limit"] or (150 if q["unit"] == "words" else 500), "unit": q["unit"],
                    **({} if q["limit"] else {"assumed": True})})  # no limit written: the usual one, said to the person (B3-20)
    return out


def clean_questions(rows, old: list[dict]) -> list[dict]:
    """The questions a page sent, checked and bounded; an unchanged question keeps its answer and its id. An id stays
    with its question across saves (a task writing answers matches on the id and the text), and a new question gets a
    number no other question has used here."""
    if not isinstance(rows, list):  # not a list
        raise ValueError("questions")
    olds = [o for o in old if isinstance(o, dict) and o.get("text")]  # the questions as kept
    kept = {o["text"]: o for o in olds}  # answers by their question
    used = {int(m.group(1)) for o in olds for m in [re.fullmatch(r"q(\d+)", str(o.get("id") or ""))] if m}  # numbers already taken
    nxt = max(used, default=0) + 1  # the next free number
    out, taken = [], set()  # the clean list, the ids given out in it
    for r in rows[:MAX_QUESTIONS]:  # in the page's order, bounded
        if not isinstance(r, dict):  # a broken row
            continue
        if not isinstance(r.get("text") or "", str):  # a question of 5 or ["x"] was kept as the words "5" (D4-05)
            raise ValueError("questions")
        text = re.sub(r"\s+", " ", r.get("text") or "").strip()[:600]  # the question as one line
        if not text:  # an empty row
            continue
        unit = r.get("unit") if r.get("unit") in UNITS else "chars"  # characters unless words
        try:
            raw = int(r.get("limit") or 0)  # what the page sent
        except (TypeError, ValueError):  # not a number
            raw = 0
        limit = max(20, min(MAX_LIMIT, raw)) if raw > 0 else (500 if unit == "chars" else 150)  # a sane limit, else the usual form's
        prev = kept.get(text, {})  # the same question before: its answer stays
        qid = prev.get("id") if prev.get("id") and prev.get("id") not in taken else None  # its old id, once
        if not qid:  # a new question
            while f"q{nxt}" in taken:  # never an id this list already holds
                nxt += 1
            qid, nxt = f"q{nxt}", nxt + 1  # a number nobody had
        taken.add(qid)
        same = prev and prev.get("limit") == limit and prev.get("unit") == unit  # the answer was checked against this very limit
        out.append({"id": qid, "text": text, "limit": limit, "unit": unit, "answer": prev.get("answer", ""),
                    "cites": prev.get("cites", []), "state": prev.get("state", "empty"),
                    "issues": prev.get("issues", []) if same else (["recheck"] if prev.get("answer") else []), "at": prev.get("at", "")})  # a new limit asks for a new check
    return out


# ---------------------------------------------------------------- a job's questions, as the panel's keys change them


def questions_of(api, jid: str) -> list[dict]:
    """A job's application questions as the page shows them: each with its answer's length as the form counts it, and
    the facts the answer rests on (answers.py)."""
    qs = read_json(api.ws.job_dir(jid) / "questions.json", {}).get("questions") or []  # as kept
    heads = {c["cid"]: " · ".join(x for x in (c.get("org"), c.get("title")) if x) for c in api.facts.candidates()} if any(q.get("cites") for q in qs) else {}  # each fact's name
    return [{**q, "issues": with_placeholders(q), "count": count(q.get("answer", ""), q.get("unit", "chars")),  # a slot left to fill is said even under an answer checked before
             "cited": [{"id": c, "title": heads.get(c, "")} for c in q.get("cites") or [] if c in heads]} for q in qs]


def set_questions(api, req: dict) -> None:
    """A job's questions as the page sends them, in order; a question that did not change keeps its answer."""
    import draft  # src/draft.py: the style pack
    jid = api.need_job(req)  # which job
    f = api.ws.job_dir(jid) / "questions.json"  # where they are kept
    st = api.ws.job(jid)  # its name, for the undo key
    with LOCK, api.ws.change({"code": "undo_questions", "company": st.get("company") or st.get("role")}, [f"jobs/{jid}/questions.json"]):  # one undo step: a question removed comes back with its answer
        now = read_json(f, {}).get("questions") or []  # as kept
        seen = req.get("seen")  # the ids the page had when it sent this list
        if isinstance(seen, list) and [str(x) for x in seen] != [q.get("id") for q in now]:  # another window changed them meanwhile: its question and answer would be lost
            raise ValueError("questions_moved")
        qs = clean_questions(req.get("questions"), now)  # checked, ids kept
        if any(q.get("issues") == ["recheck"] for q in qs):  # an answer under a new limit or unit: checked again now, against every kept fact
            by_id = {x["id"]: x["text"] for x in api.tasks.answer_facts(notes=True)}  # what the answers may say, the profile's notes too
            style = draft.style_pack(api.tasks.style_spec())  # the person's rules
            posting = api.tasks.posting_of(jid)  # the names the posting gives
            qs = [{**q, "issues": problems(q, q["answer"], [], by_id, style, posting)} if q.get("issues") == ["recheck"] else q for q in qs]  # the length and the rest, as the export will check them
        write_json(f, {"questions": qs})  # kept


def paste_questions(api, req: dict) -> tuple[int, int, int]:
    """The questions of a form pasted as the form shows them, read with their limits and added after the ones kept.
    Returns how many were added, how many of them had no limit written (given the usual one), and how many were kept
    already (B4-06: a paste of questions all there said "0 questions added." as a success)."""
    jid = api.need_job(req)  # which job
    found = parse_questions(text_field(req, "text")[:20000])  # each question with its limit: a pasted list that is no text is refused
    if not found:  # nothing that reads as a question
        raise ValueError("no_questions")
    f = api.ws.job_dir(jid) / "questions.json"  # where they are kept
    st = api.ws.job(jid)  # its name, for the undo key
    with LOCK, api.ws.change({"code": "undo_questions", "company": st.get("company") or st.get("role")}, [f"jobs/{jid}/questions.json"]):  # the answering task writes here too; one undo step
        old = read_json(f, {}).get("questions") or []  # as kept
        have = {q.get("text") for q in old}  # a question pasted twice is kept once
        first = {}  # each question of the paste once, where it first stands
        for q in found:
            first.setdefault(q["text"], q)
        new = [q for text, q in first.items() if text not in have]  # the ones added
        rows = [{"text": q["text"], "limit": q["limit"], "unit": q["unit"]} for q in old] + [{k: v for k, v in q.items() if k != "assumed"} for q in new]
        write_json(f, {"questions": clean_questions(rows, old)})  # ids and answers kept
    there = sum(1 for text in first if text in have)  # the ones the job held already
    return len(new), sum(1 for q in new if q.get("assumed")), there


def questions_from_file(api, jid: str, name: str, data: bytes) -> int:
    """A form's questions read from a file of it: a screenshot (OCR, Korean and English), a PDF, a saved page or a text file.
    Returns how many were added."""
    jid = api.need_job({"job": jid})  # which job
    return paste_questions(api, {"job": jid, "text": form_text(api, jid, name, data)})[0]  # how many came in


def form_text(api, jid: str, name: str, data: bytes) -> str:
    """The text of a file of a form, read as its kind is read (questions_from_file adds the questions in it)."""
    import tempfile  # the file, for a moment
    import ingest  # src/ingest.py: the same readers as the person's files
    jid = api.need_job({"job": jid})  # which job
    suffix = Path(name).suffix.lower()  # its kind, by its name
    if suffix not in ingest.IMAGES + (".pdf", ".txt", ".md", ".html", ".htm", ".docx"):  # a kind with no reader
        raise ValueError("no_questions")
    with tempfile.TemporaryDirectory() as tmp:  # gone afterwards
        f = Path(tmp) / f"form{suffix}"
        f.write_bytes(data)
        if suffix in (".html", ".htm"):  # a saved page: its text without the markup
            from . import postings  # the page reader the links use
            text = postings.page_text(data.decode("utf-8", "replace"))
        else:
            text = ingest.ocr(f, block=True) if suffix in ingest.IMAGES else ingest.to_text(f)  # a screenshot read line by line; a PDF's text layer
    return text  # the questions are read from it by paste_questions


def edit_answer(api, req: dict) -> None:
    """The person's own words for one answer, checked as a drafted answer is (length, facts, style)."""
    import draft  # src/draft.py: the style pack
    jid = api.need_job(req)  # which job
    f = api.ws.job_dir(jid) / "questions.json"  # where they are kept
    qs = read_json(f, {}).get("questions") or []  # as kept
    qid, text = text_field(req, "id"), req.get("answer")  # which and what
    if not isinstance(text, str) or len(text) > MAX_LIMIT * 2 or not any(q.get("id") == qid for q in qs):  # a stale page or an odd value
        raise ValueError("question")  # refused
    style = draft.style_pack(api.tasks.style_spec())  # the person's rules
    facts = api.tasks.answer_facts(notes=True)  # what the answers may say: the person's own words are checked against the profile's notes too
    st = api.ws.job(jid)  # its name, for the undo key
    with LOCK, api.ws.change({"code": "undo_answer", "company": st.get("company") or st.get("role")}, [f"jobs/{jid}/questions.json"], coalesce=f"answer:{jid}:{qid}"):  # the answering task writes here too: the file as it is now; one undo step per answer and pause
        qs = read_json(f, {}).get("questions") or []  # read again under the lock
        if not any(q.get("id") == qid for q in qs):  # removed meanwhile
            raise ValueError("question")
        posting = api.tasks.posting_of(jid)  # the names the posting gives
        write_json(f, {"questions": [checked_edit(q, text, facts, style, posting) if q.get("id") == qid else q for q in qs]})  # checked and kept
