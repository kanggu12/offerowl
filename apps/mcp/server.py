"""The MCP server: JSON-RPC 2.0 on stdio, one message per line, and the tools it offers.

Why a server of its own when the API already answers on 127.0.0.1: an agent sees typed tools with their arguments
instead of a route table to read first, every call goes to the panel that is already running (so a task it starts keeps
running, and there is one writer on the workspace, never a second API in another process), and the answers are cut to
what an agent reads: no whole state after each write, a document as its sentences in print order, a deck as the words of
its slides.

Only the standard library: the project has no dependencies, and the part of the protocol a tool server needs (initialize,
ping, tools/list, tools/call) is small. Messages that are not requests (notifications, answers) get no reply, as JSON-RPC says.
"""
from __future__ import annotations

import html  # entities in the deck's words
import json  # the protocol and the API's answers
import os  # the panel's port and address settings
import re  # the deck's tags, the version line
import sys  # stderr for the log
import time  # waiting for a task
import urllib.error  # the API's refusals
import urllib.parse  # paths, queries and the address check
import urllib.request  # the API itself
from pathlib import Path  # the version file

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # the MCP revisions this server speaks, newest first
STAGES = ("preparing", "submitted", "interview", "result")  # the board's columns (apps/api/workspace.py)
ROUND_KINDS = ("call", "first", "second", "third", "final", "coding", "assignment", "culture", "other")  # an interview round's kind (apps/api/tracker.py)
LANGS = ("ko", "en")  # the document languages
THEMES = ("navy", "teal", "mono", "wine", "forest", "slate")  # the colour packs: src/themes.json's six, as apps/api/tasks.py takes them
FILES = ("resume.txt", "resume.pdf", "deck.pdf", "cover.pdf")  # an edition's files the API serves by name
LOCAL = ("127.0.0.1", "localhost")  # the panel answers on this PC only
WAIT_MAX = 600  # seconds a single task call may wait: a client's own timeout is usually near this
TEXT_MAX = 60_000  # characters of one answer's text: a whole posting fits, a runaway answer does not flood the agent


def default_url() -> str:
    """The panel's address: OFFEROWL_MCP_URL, else 127.0.0.1 on OFFEROWL_PANEL_PORT, else the panel's own 8797."""
    if os.environ.get("OFFEROWL_MCP_URL"):  # set in the agent's MCP settings
        return os.environ["OFFEROWL_MCP_URL"]  # as given
    return f"http://127.0.0.1:{os.environ.get('OFFEROWL_PANEL_PORT') or 8797}"  # the same default `offerowl open` uses


def version() -> str:
    """Offerowl's version, from the one place it is written (deploy/python/offerowl/__init__.py); the app image, which leaves that
    folder out, says it in OFFEROWL_VERSION (deploy/docker/Dockerfile); "0" when this copy has neither."""
    if os.environ.get("OFFEROWL_VERSION"):  # the image: its build wrote the version here
        return os.environ["OFFEROWL_VERSION"]
    for f in (Path(__file__).resolve().parents[2] / "deploy" / "python" / "offerowl" / "__init__.py",  # a checkout
              Path(__file__).resolve().parents[3] / "__init__.py"):  # the installed package: the engine sits in offerowl/engine/
        try:
            m = re.search(r'__version__\s*=\s*"([^"]+)"', f.read_text(encoding="utf-8"))  # the version line
        except OSError:  # not there in this layout
            continue  # the next place
        if m:  # found
            return m.group(1)  # e.g. 0.6.0
    return "0"  # unknown, never a guess


class PanelError(Exception):
    """The panel refused a call, or nothing answered: said to the agent as a tool error, never a protocol error."""


class Panel:
    """The running panel's API over HTTP, with what its safety rules ask of a tool (apps/api/web.py): an address on this
    PC, so the Host header names 127.0.0.1 or localhost and the port; writes as a JSON body; no Origin, which marks a tool."""

    def __init__(self, url: str, timeout: float = 120):
        u = urllib.parse.urlsplit(url.rstrip("/"))  # the parts
        if u.scheme != "http" or u.hostname not in LOCAL or not u.port:  # the API never answers anywhere else
            raise ValueError(f"the panel's address must be http://127.0.0.1:<port> or http://localhost:<port>, not {url}")
        self.base = f"http://{u.hostname}:{u.port}"  # no path: every route is absolute
        self.timeout = timeout  # a building step answers at once; reading a long posting link takes longer
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # a proxy setting must never carry a local address away

    def call(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> tuple[bytes, str]:
        """One request; returns the body and its type. A refusal raises PanelError with the API's own error object."""
        q = {k: str(v) for k, v in (query or {}).items() if v is not None}  # unset options stay out
        url = self.base + path + ("?" + urllib.parse.urlencode(q) if q else "")  # the full address
        data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if method == "POST" else None  # a write's JSON body
        req = urllib.request.Request(url, data=data, method=method)  # urllib sets Host from the address
        if data is not None:  # a write
            req.add_header("Content-Type", "application/json")  # the API refuses a write of any other type
        try:
            with self.opener.open(req, timeout=self.timeout) as r:  # the answer
                return r.read(), r.headers.get("Content-Type") or ""  # bytes and type
        except urllib.error.HTTPError as exc:  # the API answered with a refusal
            raw = exc.read()  # its error object
            try:
                err = json.loads(raw)  # {"error": code, "what": detail}
            except ValueError:  # not JSON (never from the API, maybe from another server on the port)
                err = {"error": raw[:200].decode("utf-8", "replace")}  # the start of it
            raise PanelError(json.dumps({"status": exc.code, **(err if isinstance(err, dict) else {"error": err})}, ensure_ascii=False)) from None
        except (urllib.error.URLError, OSError) as exc:  # nothing listens, or the connection broke
            raise PanelError(f"no Offerowl panel answers at {self.base} ({getattr(exc, 'reason', exc)}). "
                             "Start the app, `offerowl panel`, or the container; or pass --url.") from None

    def get(self, path: str, **query) -> object:
        """A read, as JSON (or text, for a text file)."""
        raw, ctype = self.call("GET", path, query)  # the answer
        if ctype.startswith("application/json"):  # most answers
            return json.loads(raw)  # as data
        if ctype.startswith("text/"):  # the resume as plain text, the calendar
            return raw.decode("utf-8", "replace")  # as text
        return raw  # bytes: a PDF or a picture

    def post(self, path: str, body: dict) -> dict:
        """A write, without the whole state the panel redraws from (state=0): an agent reads what it asks for."""
        raw, _ = self.call("POST", path, {"state": "0"}, body)  # the action's own fields only
        return json.loads(raw)  # {"ok": true, ...}


def jpath(job: str) -> str:
    """A job id in a path: Hangul and other letters percent-encoded, as the page does."""
    return urllib.parse.quote(str(job or ""), safe="")  # the API checks the id itself


def need(args: dict, name: str) -> str:
    """A required string argument; a missing one is the agent's mistake, said as a tool error."""
    v = args.get(name)  # as sent
    if not isinstance(v, str) or not v.strip():  # absent or empty
        raise PanelError(f"`{name}` is required")  # the agent fixes the call
    return v.strip()  # trimmed


def card(j: dict) -> dict:
    """A job's card as an agent needs it: who, where it stands, its fit and editions, without the panel's drawing data."""
    keep = ("id", "company", "role", "stage", "dates", "days", "next", "result", "reminders", "rounds", "locked", "removed", "kind",
            "posting_head", "fit", "builds", "own")  # the fields that say something (days: the stages' days that count; rounds: the interviews)
    out = {k: j[k] for k in keep if k in j}  # only those present
    out["questions"] = len(j.get("questions") or [])  # the application's own questions, counted
    out["materials"] = len(j.get("materials") or [])  # the interview materials brought in, counted
    out["interview_kit"] = bool(j.get("kit"))  # whether its interview map was made
    return out  # one card


def sentence_ids(blocks: list) -> list[str]:
    """Every sentence id of a resume model, in print order (the walk documents.resume_text makes)."""
    out = []  # the ids
    for b in blocks or []:  # each block
        if b.get("sid"):  # a headline or another one-sentence block
            out.append(b["sid"])  # its sentence
        out += list(b.get("sids") or [])  # paragraph sentences
        for it in b.get("items") or []:  # cards, competencies, list lines
            if isinstance(it, dict):  # an item of its own
                if it.get("sid"):  # one sentence per item
                    out.append(it["sid"])  # its sentence
                out += [r["sid"] for r in it.get("rows") or [] if isinstance(r, dict) and r.get("sid")]  # key project rows
        for p in b.get("projects") or []:  # a role's projects
            out += list(p.get("sids") or [])  # their sentences
    return list(dict.fromkeys(out))  # each once, order kept


def compact_resume(m: dict) -> dict:
    """The resume model cut to its sentences in print order, each with its state and issues: what an agent checks and edits."""
    if m.get("missing") and not m.get("blocks"):  # it cannot be drawn yet
        return {"kind": "resume", "lang": m.get("lang"), "missing": m["missing"]}  # the reason, e.g. needs_translation
    sents = m.get("sentences") or {}  # sid -> sentence
    order = sentence_ids(m.get("blocks") or [])  # print order
    order += [s for s in sents if s not in order]  # any the walk did not reach, after
    rows = []  # one per sentence
    for sid in order:  # in that order
        s = sents.get(sid)  # its record
        if not s:  # a block naming a sentence that is not there
            continue  # nothing to say
        rows.append({"sid": sid, "text": s.get("text", ""), "state": s.get("state"), "locked": bool(s.get("locked")),  # the words and their standing
                     "issues": s.get("issues") or [],  # what the checks found
                     "evidence": [e.get("where") for e in s.get("evidence") or [] if e.get("where")]})  # where each line comes from, by name
    return {"kind": "resume", "lang": m.get("lang"), "job": m.get("job"), "counts": m.get("counts"), "missing": m.get("missing") or [],
            "draft": m.get("draft"), "sentences": rows}  # the whole document in reading order


def slide_text(page: str) -> list[str]:
    """The words of each slide of the live deck's HTML, one string per slide: an agent reads them, it does not render them."""
    parts = re.split(r'<section class="slide', page)[1:]  # each slide starts here
    out = []  # one text per slide
    for p in parts:  # each slide's markup
        p = p.split(">", 1)[-1]  # the rest of the opening tag (its classes and data- attributes) is not words
        p = re.sub(r"<(script|style)\b.*?</\1>", " ", p, flags=re.S | re.I)  # code and styles say nothing
        words = html.unescape(re.sub(r"<[^>]+>", " ", p))  # tags out, entities back to letters
        out.append(re.sub(r"\s+", " ", words).strip())  # one line per slide
    return out  # in order


def clip(text: str) -> str:
    """An answer's text within TEXT_MAX characters, saying so when it was cut."""
    return text if len(text) <= TEXT_MAX else text[:TEXT_MAX] + f"\n... (cut at {TEXT_MAX} characters)"  # never silently cut


def search(board: dict, query: str, limit: int) -> list[dict]:
    """The board's questions and scripts that hold the query's words, the most words first: the kit's search view's
    keyword search, without the page."""
    words = [w for w in re.split(r"\s+", query.lower()) if w]  # the words asked for
    hits = []  # (score, order, item)
    n = 0  # the board's order, for ties
    for cat in board.get("categories") or []:  # the question map
        for q in cat.get("questions") or []:  # each question
            hay = " ".join([q.get("text", ""), q.get("ask_en", ""), q.get("ask_ko", "")]).lower()  # its words in both languages
            score = sum(1 for w in words if w in hay)  # how many query words it holds
            if score:  # at least one
                hits.append((score, n, {"type": "question", "kind": cat.get("kind"), **q}))  # the question with its coverage
            n += 1  # next in order
    for s in board.get("scripts") or []:  # the scripts
        hay = " ".join([s.get("title_en", ""), s.get("title_ko", ""), s.get("category", ""), s.get("key", ""), s.get("note", ""),
                        json.dumps(s.get("turns") or [], ensure_ascii=False)]).lower()  # its head and its dialogue
        score = sum(1 for w in words if w in hay)  # how many query words it holds
        if score:  # at least one
            hits.append((score, n, {"type": "script", **s}))  # the whole script: the agent came for its words
        n += 1  # next in order
    hits.sort(key=lambda h: (-h[0], h[1]))  # the most words first, then the board's order
    return [h[2] for h in hits[:limit]]  # the best ones


# ---------------------------------------------------------------------- the tools

def S(props: dict, required: tuple = ()) -> dict:
    """An input schema: an object with these properties, no others."""
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


JOB = {"type": "string", "description": "the job's id, as list_jobs shows it ('-general' for the general edition)"}  # every job tool takes it
LANG = {"type": "string", "enum": list(LANGS), "description": "the document language (default ko)"}  # Korean or English
THEME = {"type": "string", "enum": list(THEMES), "description": "the colour pack (default navy)"}  # the six packs


OPEN_WORLD = {"add_job"}  # tools that may reach outside this PC: add_job fetches a posting's link


def link_key(url: str) -> str:
    """A link as two writings of it compare: no spaces round it, no slash at its end."""
    return str(url or "").strip().rstrip("/")


class Server:
    """The protocol and the tools. One per stdio connection."""

    def __init__(self, panel: Panel, read_only: bool = False, links=None):
        self.panel = panel  # the running panel's API
        self.read_only = read_only  # only the reading tools are offered
        # The links add_job may fetch: None, any (the person's own agent, which has its own ways out anyway); else only these.
        # The command bar passes the links in the person's own words: a posting or a file the agent reads can carry
        # instructions, and a link written there could carry what the agent read out to its server in the query.
        self.links = None if links is None else {link_key(u) for u in links}
        self.protocol = PROTOCOLS[0]  # until the client says which it speaks
        self.tools = self._tools()  # name -> definition and its function

    # ------------------------------------------------------------------ the table

    def _tools(self) -> dict:
        """Every tool: name -> (description, input schema, read-only, function)."""
        t = {}  # the table

        def tool(name, desc, schema, read=True):  # a decorator that files a function under its name
            def put(fn):
                t[name] = (desc, schema, read, fn)  # kept with its words
                return fn  # unchanged
            return put

        p = self.panel  # short name below

        @tool("status", "Offerowl's state at a glance: the AI backend, the job in view, how many jobs and facts, running and "
                        "finished tasks, what is missing from the profile, reminders due. Start here.", S({}))
        def status(a):
            st = p.get("/api/v1/state")  # everything the panel draws
            facts = (st.get("facts") or {}).get("counts")  # kept, to confirm, dropped
            agent = st.get("agent") or {}  # the backend card
            return {"app": st.get("app"), "api": st.get("api"), "agent": {k: agent.get(k) for k in ("backend", "state", "found")},  # who writes
                    "job_in_view": st.get("job"), "jobs": len(st.get("jobs") or []), "facts": facts, "problems": st.get("problems"),  # where things stand
                    "tasks": {k: {f: v.get(f) for f in ("state", "step", "error")} for k, v in (st.get("tasks") or {}).items()},  # every task and how it ended
                    "engine": st.get("engine"), "features": st.get("features"), "due": st.get("due"), "undo": st.get("undo"), "today": st.get("today")}

        @tool("list_jobs", "Every application on the board: id, company, role, stage, dates, next step, fit score, the editions "
                           "made per language and whether they are stale.", S({}))
        def list_jobs(a):
            return {"jobs": [card(j) for j in p.get("/api/v1/jobs")["jobs"]]}  # cards without drawing data

        @tool("get_job", "One application: its card and the full posting text.", S({"job": JOB}, ("job",)))
        def get_job(a):
            j = p.get(f"/api/v1/jobs/{jpath(need(a, 'job'))}")  # the card and the posting
            return {**card(j), "plan": j.get("plan"), "posting": clip(j.get("posting") or "")}  # the analysis too

        @tool("job_fit", "How the profile fits a job's posting, line by line: each duty or requirement rated strong, weak or "
                         "none, with the evidence quotes behind it, and the gaps.",
              S({"job": JOB, "quotes": {"type": "boolean", "description": "include each line's evidence quotes (default true)"}}, ("job",)))
        def job_fit(a):
            f = p.get(f"/api/v1/jobs/{jpath(need(a, 'job'))}/fit")  # cached by the panel until something changes
            if a.get("quotes") is False:  # the ratings alone
                for line in f.get("lines") or []:  # each line
                    line["evidence"] = [e.get("where") for e in line.get("evidence") or []]  # names only
            return f

        @tool("read_document", "A document as it will print, sentence by sentence: the resume (each sentence with its state, "
                               "check issues and where its evidence comes from) or the cover letter (paragraphs). Without "
                               "`job`, the general resume.",
              S({"kind": {"type": "string", "enum": ["resume", "cover"]}, "job": JOB, "lang": LANG}, ("kind",)))
        def read_document(a):
            kind, lang = a.get("kind"), a.get("lang") or "ko"  # which and in what language
            if kind == "cover":  # a job's letter
                return p.get("/api/v1/documents/cover", job=need(a, "job"), lang=lang)  # already compact
            return compact_resume(p.get("/api/v1/documents/resume", job=a.get("job") or None, lang=lang))  # cut to its sentences

        @tool("document_file", "An edition's made file. resume.txt comes back as text (the plain resume job sites read); a "
                               "PDF comes back as its size and the address to fetch it from on this PC.",
              S({"job": JOB, "lang": LANG, "file": {"type": "string", "enum": list(FILES)}}, ("job", "file")))
        def document_file(a):
            name = a.get("file")  # which file
            if name not in FILES:  # only the fixed names
                raise PanelError(f"`file` must be one of {', '.join(FILES)}")
            path = f"/api/v1/jobs/{jpath(need(a, 'job'))}/files/{a.get('lang') or 'ko'}/{name}"  # the API's own route
            body = p.get(path)  # 404 when that edition was not made
            if isinstance(body, str):  # the text file
                return clip(body)  # as it is
            return {"file": name, "bytes": len(body), "url": p.base + path}  # a PDF is for a reader, not for the agent's context

        @tool("deck", "The portfolio deck as it will print: how many slides and the words of each. `html` adds the page itself.",
              S({"job": JOB, "lang": LANG, "theme": THEME, "html": {"type": "boolean", "description": "include the full HTML (large)"}}, ("job",)))
        def deck(a):
            page = p.get(f"/api/v1/jobs/{jpath(need(a, 'job'))}/deck/{a.get('lang') or 'ko'}", theme=a.get("theme") or None)  # a page, or why there is none
            if "html" not in page:  # cannot be drawn yet
                return page  # {"missing": code}
            out = {"slides": page.get("slides"), "text": slide_text(page["html"])}  # the words
            if a.get("html") is True:  # asked for
                out["html"] = clip(page["html"])  # the page, within the cap
            return out

        @tool("interview_board", "A job's interview kit: the question map by category (each question with its coverage and the "
                                 "scripts that answer it), the script titles, counts, and the addresses of the kit's search "
                                 "view, practice, cue cards and interview deck.",
              S({"job": JOB, "lang": LANG}, ("job",)))
        def interview_board(a):
            b = p.get(f"/api/v1/jobs/{jpath(need(a, 'job'))}/interview", lang=a.get("lang") or "ko")  # the studio's board
            b["scripts"] = [{k: s.get(k) for k in ("id", "title_en", "title_ko", "category", "key", "draft")} for s in b.get("scripts") or []]  # heads only: interview_search gives the words
            return b

        @tool("interview_search", "Search a job's interview kit by keywords: questions and whole scripts (their dialogue) that "
                                  "hold the words, the most matching first. `ids` returns those scripts or questions instead.",
              S({"job": JOB, "query": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}},
                 "lang": LANG, "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "default 8"}}, ("job",)))
        def interview_search(a):
            b = p.get(f"/api/v1/jobs/{jpath(need(a, 'job'))}/interview", lang=a.get("lang") or "ko")  # the board, scripts with their words
            if not b.get("ready"):  # no kit yet
                return {"ready": False, "hits": [], "hint": "make the kit first: make_interview_kit, or make_documents"}
            ids = [str(x) for x in a.get("ids") or []]  # asked by id
            if ids:  # those items, in the order asked
                every = {s["id"]: {"type": "script", **s} for s in b.get("scripts") or []}  # scripts by id
                every.update({q["id"]: {"type": "question", "kind": c.get("kind"), **q} for c in b.get("categories") or [] for q in c.get("questions") or []})  # questions too
                return {"ready": True, "hits": [every[i] for i in ids if i in every], "unknown": [i for i in ids if i not in every]}
            limit = a.get("limit") if isinstance(a.get("limit"), int) else 8  # how many
            return {"ready": True, "hits": search(b, need(a, "query"), max(1, min(limit, 50)))}  # the best ones

        @tool("form_answers", "An application's own form questions with their limits and the answers kept for them: each "
                              "answer's words, its state (drafted, edited), the facts it cites and its problems.",
              S({"job": JOB}, ("job",)))
        def form_answers(a):
            j = p.get(f"/api/v1/jobs/{jpath(need(a, 'job'))}")  # the card holds them
            return {"questions": [{k: q.get(k) for k in ("id", "text", "limit", "unit", "answer", "state", "cites", "issues", "at")}
                                  for q in j.get("questions") or []]}

        @tool("tracker", "The board's columns with each card, the timeline, and the reminders that are due.", S({}))
        def tracker(a):
            tr = p.get("/api/v1/tracker")  # the board, the timeline and what is due
            return {"stages": tr.get("stages"), "jobs": [card(j) for j in tr.get("jobs") or []], "timeline": tr.get("timeline"), "due": tr.get("due")}

        @tool("insights", "The Insights view's numbers: the funnel (added, submitted, interview, offer), how the ended ones "
                          "ended, the moves per week, every posting's fit, each area of the postings (lines met, in part, not "
                          "met, and how many facts back it, with the unmet lines), the career's spans, the facts by kind, and "
                          "how ready each open application is for its interview.", S({}))
        def insights(a):
            return p.get("/api/v1/insights")  # read as the view reads it

        @tool("library", "Files brought in or made, as the Library view lists them: the profile's files, each application's "
                         "posting, materials and form questions, the PDFs per edition and language, the copies that went out, "
                         "the interview kits. Filter by `group` (source, input, made, sent, kit), `job` or `query` (a name's "
                         "words); `offset` and `limit` page through (50 at most). Each row names the route that opens it and "
                         "the routes that copy it to the Desktop or take it off.",
              S({"group": {"type": "string", "enum": ["source", "input", "made", "sent", "kit"]}, "job": {"type": "string"},
                 "query": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}))
        def library(a):
            d = p.get("/api/v1/library")  # the list and its routes
            rows = d.get("rows") or []
            if a.get("group"):  # one kind of file
                rows = [r for r in rows if r.get("group") == a["group"]]
            if a.get("job"):  # one application's or one edition's
                rows = [r for r in rows if (r.get("owner") or {}).get("job") == a["job"] or (r.get("owner") or {}).get("edition") == a["job"]]
            if a.get("query"):  # by the words of its name
                q = str(a["query"]).lower()
                rows = [r for r in rows if q in str(r.get("name") or "").lower() or q in str((r.get("owner") or {}).get("company") or "").lower()]
            off = max(0, int(a.get("offset") or 0)); lim = max(1, min(int(a.get("limit") or 20), 50))  # a page that fits an answer
            page = [{**{k: r.get(k) for k in ("group", "id", "name", "kind", "lang", "size", "date", "open", "export", "remove") if r.get(k) is not None},
                     "owner": (r.get("owner") or {}).get("job") or (r.get("owner") or {}).get("edition") or "profile"} for r in rows[off:off + lim]]
            return {"counts": d.get("counts"), "total": len(rows), "offset": off, "rows": page, "more": off + lim < len(rows)}

        @tool("task", "A task's state (the key a write tool returned, like tailor:<job>), or every task without `key`. "
                      "`wait` waits up to that many seconds for it to end.",
              S({"key": {"type": "string"}, "wait": {"type": "integer", "minimum": 0, "maximum": WAIT_MAX}}))
        def task(a):
            key = a.get("key")  # one task, or all
            end = time.time() + max(0, min(int(a.get("wait") or 0), WAIT_MAX))  # when to stop waiting
            while True:  # until it ends or the time is up
                tasks = p.get("/api/v1/state").get("tasks") or {}  # every task the panel knows
                if not key:  # all of them
                    return tasks
                rec = tasks.get(key)  # this one
                if rec is None:  # never started in this panel
                    raise PanelError(f"no task {key}; known: {', '.join(sorted(tasks)) or 'none'}")
                if rec.get("state") != "running" or time.time() >= end:  # ended, or the wait is over
                    return {"key": key, **rec}  # as it stands
                time.sleep(1)  # the panel is asked once a second

        # ------------------------------------------------------------------ writes: only what the API already does

        @tool("add_job", "Add an application from a pasted posting (or a link to it). The posting is analyzed at once by "
                         "words (task analyze:<job>); nothing is sent to the AI backend.",
              S({"posting": {"type": "string"}, "url": {"type": "string"}, "company": {"type": "string"}, "role": {"type": "string"}}), read=False)
        def add_job(a):
            if not (a.get("posting") or a.get("url")):  # one of the two
                raise PanelError("`posting` or `url` is required")
            if a.get("url") and self.links is not None and link_key(a["url"]) not in self.links:  # not a link the person wrote
                raise PanelError("only a link the person wrote in their own words is fetched here: ask them for it, or add the posting's text")
            out = p.post("/api/v1/jobs", {k: a[k] for k in ("posting", "url", "company", "role") if a.get(k)})  # the new job
            return {"job": out.get("job"), "task": f"analyze:{out.get('job')}"}  # its id and the analysis to wait for

        @tool("make_documents", "Tailor a job's resume, cover letter and interview kit together with the AI backend, from the "
                                "kept evidence. Returns the task key (tailor:<job>); wait for it with `task`.",
              S({"job": JOB, "lang": LANG, "theme": THEME, "max_pages": {"type": "integer", "minimum": 1, "maximum": 7},
                 "cover": {"type": "boolean", "description": "draft the cover letter too (default true)"},
                 "typeset": {"type": "boolean", "description": "also typeset the PDFs at the end (default false)"}}, ("job",)), read=False)
        def make_documents(a):
            out = p.post("/api/v1/jobs/tailor", {"job": need(a, "job"), "lang": a.get("lang"), "theme": a.get("theme"), "maxPages": a.get("max_pages"),
                                                  "cover": a.get("cover") is not False, "typeset": a.get("typeset") is True})  # as the page asks
            return {"started": out.get("started"), "task": out.get("task")}  # False when one already runs

        @tool("build_pdfs", "Typeset a job's resume, deck and cover letter as PDFs (no AI backend). Task build:<job>.",
              S({"job": JOB, "lang": LANG, "theme": THEME, "max_pages": {"type": "integer", "minimum": 1, "maximum": 7},
                 "cover": {"type": "boolean"}, "blind": {"type": "boolean", "description": "the blind edition (no name, photo or schools)"}}, ("job",)), read=False)
        def build_pdfs(a):
            body = {"job": need(a, "job"), "lang": a.get("lang"), "theme": a.get("theme"), "maxPages": a.get("max_pages"), "cover": a.get("cover") is not False}  # as the page asks
            if isinstance(a.get("blind"), bool):  # unsaid keeps the job's last choice
                body["blind"] = a["blind"]
            out = p.post("/api/v1/jobs/build", body)  # started
            return {"started": out.get("started"), "task": f"build:{body['job']}"}  # the key the panel uses

        @tool("export_documents", "Copy a job's made files to the Desktop. Refused while a sentence has no evidence.",
              S({"job": JOB, "lang": LANG}, ("job",)), read=False)
        def export_documents(a):
            out = p.post("/api/v1/jobs/export", {"job": need(a, "job"), "lang": a.get("lang")})  # the copies
            return {"exported": out.get("exported"), "refused": out.get("refused") or []}  # the names written, and any held back

        @tool("make_interview_kit", "Make a job's interview question map now, without tailoring the rest (no AI backend).",
              S({"job": JOB, "lang": LANG}, ("job",)), read=False)
        def make_interview_kit(a):
            out = p.post("/api/v1/interview/kit", {"job": need(a, "job"), "lang": a.get("lang")})  # the map
            return {"questions": out.get("questions")}  # its size

        @tool("write_interview_scripts", "Have the AI backend write more interview scripts, the likeliest questions first. "
                                         "Task scripts:<job>.", S({"job": JOB, "lang": LANG}, ("job",)), read=False)
        def write_interview_scripts(a):
            out = p.post("/api/v1/interview/scripts", {"job": need(a, "job"), "lang": a.get("lang")})  # started
            return {"started": out.get("started"), "task": out.get("task")}

        @tool("move_job", "Move an application on the board or edit its card: a stage, the stage's date (YYYY-MM-DD), any stage's "
                          "day (`dates`: {stage: YYYY-MM-DD}, empty to clear), the next step or the result. `advance` moves it "
                          "one column right. Write a link the next step comes with (a meeting's, a booking page's) into `next` "
                          "whole, as it was given: the panel shows it as a link to open. One undo step.",
              S({"job": JOB, "stage": {"type": "string", "enum": list(STAGES)}, "date": {"type": "string"},
                 "dates": {"type": "object", "properties": {s: {"type": "string"} for s in STAGES}, "additionalProperties": False},
                 "next": {"type": "string"}, "result": {"type": "string"}, "advance": {"type": "boolean"}}, ("job",)), read=False)
        def move_job(a):
            jid = need(a, "job")  # which card
            if a.get("advance") is True:  # the card's move-on button
                p.post("/api/v1/tracker/next", {"job": jid})  # one column right
            fields = {k: a[k] for k in ("stage", "date", "next", "result") if isinstance(a.get(k), str)}  # only what was sent
            if isinstance(a.get("dates"), dict):  # any stage's day
                fields["dates"] = {k: v for k, v in a["dates"].items() if k in STAGES and isinstance(v, str)}
            if fields:  # an edit too
                p.post("/api/v1/tracker/edit", {"job": jid, **fields})  # one undo step
            if not fields and a.get("advance") is not True:  # nothing asked
                raise PanelError("nothing to change: pass `stage`, `date`, `dates`, `next`, `result` or `advance`")
            return card(next(j for j in p.get("/api/v1/jobs")["jobs"] if j["id"] == jid))  # the card as it is now

        @tool("log_round", "Keep an interview round on an application: its kind, its day (`at` YYYY-MM-DD or YYYY-MM-DDTHH:MM), "
                           "the questions asked (`asked`, one a line) and how it went (`notes`, with any link it came with "
                           "written whole). With `id`, change that round; "
                           "with `id` and `remove`, take it off. A recorded round counts as an interview reached. One undo step.",
              S({"job": JOB, "kind": {"type": "string", "enum": list(ROUND_KINDS)}, "at": {"type": "string"}, "asked": {"type": "string"},
                 "notes": {"type": "string"}, "id": {"type": "string"}, "remove": {"type": "boolean"}}, ("job",)), read=False)
        def log_round(a):
            body = {k: a[k] for k in ("job", "kind", "at", "asked", "notes", "id", "remove") if k in a}  # as sent
            return {"round": p.post("/api/v1/tracker/round", body).get("round")}  # the round as kept

        @tool("add_fact", "Add a fact the person states (for example something they told after an interview): its kind, "
                          "organisation, period, title and statement. It is kept as typed, its own words its evidence. One undo step.",
              S({"kind": {"type": "string", "enum": ["role", "project", "education", "skill", "paper", "patent", "award", "certificate", "other"]},
                 "org": {"type": "string"}, "period": {"type": "string"}, "title": {"type": "string"}, "statement": {"type": "string"}},
                ("kind", "statement")), read=False)
        def add_fact(a):
            body = {k: a[k] for k in ("kind", "org", "period", "title", "statement") if isinstance(a.get(k), str)}  # the fields
            return {"cid": p.post("/api/v1/facts/add", body).get("cid")}  # the new fact's id

        @tool("reminder", "Add a reminder to a job (`at` YYYY-MM-DD and `text`), or mark one done or remove it (`id`).",
              S({"job": JOB, "at": {"type": "string"}, "text": {"type": "string"}, "id": {"type": "string"},
                 "done": {"type": "boolean"}, "remove": {"type": "boolean"}}, ("job",)), read=False)
        def reminder(a):
            body = {k: a[k] for k in ("job", "at", "text", "id", "done", "remove") if k in a}  # as sent
            return {"reminder": p.post("/api/v1/reminders", body).get("reminder")}  # the new one, if any

        return {k: v for k, v in t.items() if v[2] or not self.read_only}  # without the writes when asked

    # ------------------------------------------------------------------ the protocol

    def listing(self) -> list[dict]:
        """tools/list: each tool with its schema and hints."""
        out = []  # in the table's order: the reads first
        for name, (desc, schema, read, _) in self.tools.items():  # each tool
            out.append({"name": name, "description": desc, "inputSchema": schema,  # what the agent sees
                        "annotations": {"readOnlyHint": read, "destructiveHint": False, "idempotentHint": read, "openWorldHint": name in OPEN_WORLD}})  # hints only
        return out

    def run(self, name: str, args: dict) -> dict:
        """tools/call: the tool's answer as text, or its error with isError, which the agent reads and can act on."""
        if name not in self.tools:  # unknown, or a write in read-only mode
            raise KeyError(name)  # a protocol error: the client asked for a tool it was never offered
        try:
            out = self.tools[name][3](args if isinstance(args, dict) else {})  # the call
            text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1)  # JSON for data
            return {"content": [{"type": "text", "text": clip(text)}], "isError": False}  # the answer
        except PanelError as exc:  # refused, or no panel
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}  # the agent reads why
        except Exception as exc:  # a bug here: said, logged, the server stays up
            print(f"offerowl mcp: {name}: {exc!r}", file=sys.stderr)  # for the person's log
            return {"content": [{"type": "text", "text": f"unexpected error in {name}: {exc}"}], "isError": True}

    def handle(self, msg) -> dict | None:
        """One message in, the reply out (None for a notification or anything that is not a request)."""
        if not isinstance(msg, dict) or "method" not in msg:  # an answer to us, or junk: JSON-RPC asks for no reply to answers
            return None if isinstance(msg, dict) else self.error(None, -32600, "invalid request")
        mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}  # the parts
        if "id" not in msg:  # a notification (initialized, cancelled): nothing to answer
            return None
        try:
            if method == "initialize":  # the handshake
                asked = params.get("protocolVersion")  # what the client speaks
                self.protocol = asked if asked in PROTOCOLS else PROTOCOLS[0]  # its own when we know it, else our newest
                return self.result(mid, {"protocolVersion": self.protocol, "capabilities": {"tools": {"listChanged": False}},
                                         "serverInfo": {"name": "offerowl", "title": "Offerowl", "version": version()},
                                         "instructions": "Offerowl turns one evidence-backed profile into a resume, a deck, a cover letter "
                                                         "and an interview kit. Call `status` first, then `list_jobs`. Write tools start "
                                                         "tasks in the running panel; wait for them with `task`."})
            if method == "ping":  # liveness
                return self.result(mid, {})
            if method == "tools/list":  # the tools, all on one page
                return self.result(mid, {"tools": self.listing()})
            if method == "tools/call":  # one tool
                return self.result(mid, self.run(str(params.get("name") or ""), params.get("arguments") or {}))
            return self.error(mid, -32601, f"method not found: {method}")  # resources, prompts: not offered
        except KeyError as exc:  # an unknown tool
            return self.error(mid, -32602, f"unknown tool: {exc.args[0]}")

    @staticmethod
    def result(mid, res: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": res}  # a success

    @staticmethod
    def error(mid, code: int, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}  # a protocol error

    def serve(self, rd, wr) -> None:
        """Read one JSON message per line until the input ends; write each reply as one line."""
        for line in rd:  # blocks until the client sends
            line = line.strip()  # "\r\n" from a Windows client too
            if not line:  # an empty line between messages
                continue  # nothing to do
            try:
                msg = json.loads(line)  # one message
            except ValueError:  # not JSON
                reply = self.error(None, -32700, "parse error")  # said, and the server goes on
            else:
                reply = self.handle(msg)  # the answer, if one is due
            if reply is not None:  # requests only
                wr.write(json.dumps(reply, ensure_ascii=False) + "\n")  # one line, no newline inside: json.dumps escapes them
                wr.flush()  # the client waits for it now
