"""The search view's server: one page with the job's items inlined, and a health check.

The page ranks by keywords (BM25) in the browser, so this server only has to read the scene files and hand them over.
It uses the standard library only. The similarity model is optional (`--model DIR`, see dense.py) and off by default.
Practice mode (practice.py) answers under /api/practice/, /cue serves the printable cue cards (cue.py) and /deck the
printable interview deck (deck.py).

    python3 src/interview/cli.py serve --job <workspace>/jobs/<job> [--port 8796]

It listens on 127.0.0.1 only and answers only requests whose Host header names this address (no DNS rebinding).
Edits to the scene files show on the next page load; the page template is read on every load too.
"""
import base64  # a script's hash, as the policy writes it
import hashlib  # that hash
import html  # escaping strings put into the page
import http.server  # the HTTP server
import json  # page data and API answers
import pathlib  # paths
import re  # the page's own scripts
import threading  # one rebuild at a time
import traceback  # a practice call's failure, on the server's output
import time  # build timing
import urllib.parse  # query strings
import sys  # the import path when this file is started as a script

if __package__ in (None, ""):  # started as a script (the panel runs src/interview/server.py): make the package importable
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # src/, where the interview package lives

from interview import corpus, cue, deck, i18n, practice  # scene parsing; cue cards; the interview deck; strings; practice mode

HERE = pathlib.Path(__file__).resolve().parent  # src/interview
PAGE = HERE / "page.html"  # the single-page template
PRACTICE_JS = HERE / "practice.js"  # practice mode, inlined into the page so a saved copy stays one file
FONTS = HERE / "fonts"  # Pretendard and JetBrains Mono, served locally so nothing loads from the internet
FONT_FILES = {"PretendardVariable.woff2", "JetBrainsMono.woff2"}  # the only files the /fonts route serves
SCRIPT = re.compile(r"<script(?![^>]*\b(?:src|type)=)[^>]*>(.*?)</script>", re.S)  # an inline script that runs (not a JSON data block)


def page_policy(body: str, scripts=None) -> str:
    """The script policy of one of this server's pages: only the scripts it was built with run, each named by its hash. A
    script or a handler that text from a scene, a posting or the agent got into the page by a mistake of escaping does not;
    the panel serves these pages on its own address, where a script could call every route of the panel. `scripts` names the
    page's own scripts (their text): the cue cards have their print key's, the interview deck and the talk none at all, so a
    script that a planted file got into them never runs. None: every inline script of the body (the search page, whose data
    script changes with the scenes and holds no '<')."""
    found = SCRIPT.findall(body) if scripts is None else list(scripts)  # the page's own scripts
    hashes = " ".join("'sha256-%s'" % base64.b64encode(hashlib.sha256(m.encode("utf-8")).digest()).decode() for m in found)  # as the browser hashes them
    src = ("'self' " + hashes) if found else "'none'"  # a page built without a script runs none
    return ("default-src 'self'; script-src " + src + "; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'self'")  # practice plays back its recording from a blob; framed by its own address only
SYNONYMS = json.loads((HERE / "synonyms.json").read_text(encoding="utf-8"))["groups"]  # built-in synonym groups
PAGE_FIELDS = ("id", "src", "role", "cat", "tko", "ten", "key", "text", "md")  # the item fields the page reads
MAX_QUERY = 500  # longest similarity query accepted
MAX_JSON = 256 * 1024  # the largest JSON body a practice call may send
PRACTICE_GET = ("/api/practice/setup", "/api/practice/history")  # the practice reads
PRACTICE_POST = ("/api/practice/start", "/api/practice/answer", "/api/practice/followup", "/api/practice/end",
                 "/api/practice/transcribe")  # the practice writes


def view_data(job, items, alts, lang=None, model=False):
    """What a view of the kit reads: every item with its script, the phrasings, the kit's settings the view uses, the
    synonym groups and the view's words in a language (the run's own when none is named). The search page gets it
    inlined; the panel's own view asks the panel for it (apps/api/task_kit.py kit_view)."""
    kit = job.kit  # the job's settings
    return {"items": [{k: it[k] for k in PAGE_FIELDS} for it in items],  # trimmed items
            "alts": alts,  # phrasings feed the keyword index too
            "kit": {k: kit.get(k) for k in ("sections", "strip", "fallback", "weak_hint", "hidden_labels", "examples")},  # what the view reads (examples: the job's own, for the search box)
            "syn": SYNONYMS + list(kit.get("synonyms") or []),  # built-in groups, then the job's own
            "str": i18n.page(lang),  # strings in the view's language
            "model": bool(model)}  # show the similarity switch?


class Index:  # one per server
    """The job's items and the page data built from them; rebuilt when a source file changes."""

    def __init__(self, job, port, model=False):  # the server builds it before the first request
        self.job = job  # the job folder
        self.port = port  # the port the page is served on (a saved copy calls it)
        self.model = model  # whether the page shows the similarity switch
        self.lock = threading.Lock()  # one rebuild at a time
        self.stamp = None  # file sizes and times the data was built from
        self.items, self.alts = [], {}  # parsed items and phrasings
        self.data = "null"  # the page data as JSON text
        self.built_ms = 0  # how long the last build took

    def ensure(self):  # called by every request that needs the data
        """Rebuild if a source file changed (a few stat calls when nothing did)."""
        stamp = corpus.stamp(self.job)  # sizes and change times
        if stamp == self.stamp:  # up to date
            return
        with self.lock:  # only one request rebuilds
            if stamp == self.stamp:  # another request rebuilt while we waited
                return
            t0 = time.time()  # build timer
            self.job.reload_kit()  # kit.json may have changed too: its section names and each file's role are read again
            stamp = corpus.stamp(self.job)  # with the kit as read now (a file whose role changed may have joined or left)
            items, alts = corpus.load(self.job)  # parse the markdown and the phrasings
            payload = view_data(self.job, items, alts, model=self.model)  # everything the page needs, inlined as one JSON object
            payload["port"] = self.port  # where a saved copy finds this server
            self.data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")  # no "<" at all: "</script>" and "<!--<script" cannot end or bend the block
            self.items, self.alts, self.stamp = items, alts, stamp  # publish
            self.built_ms = int((time.time() - t0) * 1000)  # for /api/health

    def page(self):  # the GET / answer
        """The search page with the current items inlined and the strings filled in."""
        self.ensure()  # pick up edits to the markdown
        text = PAGE.read_text(encoding="utf-8")  # read each time, so page edits need no restart
        strings = i18n.page()  # the page's language
        examples = self.job.kit.get("examples")  # the job's own examples for the search box
        if isinstance(examples, dict):  # {"ko": ..., "en": ...}
            examples = examples.get(strings["lang"]) or ""  # the examples in the page's language; empty when missing
        fill = {k: v for k, v in strings.items() if isinstance(v, str)}  # plain strings only (labels is a dict)
        fill["placeholder"] = strings["placeholder"].format(examples=examples or strings["examples"])  # the box's hint
        for k, v in fill.items():  # {{key}} -> the escaped string
            text = text.replace("{{" + k + "}}", html.escape(v, quote=True))  # fill each placeholder; escaping keeps a string from breaking the HTML
        text = text.replace("{{engine_hidden}}", "" if self.model else " hidden")  # no model: no switch
        text = text.replace("/*__DATA__*/null", self.data)  # the template's data placeholder
        # practice mode last, after the slots are filled; "</" escaped so no string in it can close the script tag
        return text.replace("/*__PRACTICE__*/", PRACTICE_JS.read_text(encoding="utf-8").replace("</", "<\\/"))


class Handler(http.server.BaseHTTPRequestHandler):  # the routes; make_server binds a job to a subclass
    """GET / (the page), /cue, /fonts/<file>, /api/health and the practice reads; POST the practice writes; with a
    model also /api/dense and POST /api/model/on|off."""

    server_version = "offerowl-interview"  # no Python version in the header
    sys_version = ""  # nor the Python build after it
    index = None  # set by make_server
    dense = None  # the optional similarity model
    practice = None  # practice mode (practice.Practice), set by make_server
    hosts = set()  # Host headers this server answers
    origins = set()  # Origin headers allowed to call the API

    def log_message(self, fmt, *args):  # replaces the default per-request log
        """Quiet: one line per request would flood the terminal while typing questions."""
        return  # drop the line

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):  # every answer goes through here
        """Send one response with its length. Only this server's own pages may read the answers; a saved copy (Origin: null)
        may read /api/health alone, which says nothing but that the server is up."""
        data = body.encode("utf-8") if isinstance(body, str) else body  # bytes on the wire
        self.send_response(code)  # the status line
        self.send_header("Content-Type", ctype)  # tells the browser how to read the body
        self.send_header("Content-Length", str(len(data)))  # so the browser knows where the body ends
        self.send_header("Cache-Control", "no-store")  # the page changes when the files do
        self.send_header("X-Content-Type-Options", "nosniff")  # the browser keeps the type, never guesses one
        origin = self.headers.get("Origin")  # a page of another origin, or a saved copy from file:// (Origin: null)
        # "null" is also what a sandboxed frame on any web site sends: it may learn that the server is up, never read the kit
        saved = origin == "null" and urllib.parse.urlsplit(self.path).path == "/api/health"
        if origin and (origin in self.origins or saved):  # our own pages, and a saved copy's health check
            self.send_header("Access-Control-Allow-Origin", origin)  # lets that page read the answer
            self.send_header("Access-Control-Allow-Private-Network", "true")  # Chrome's private-network check for 127.0.0.1
        for k, v in (extra or {}).items():  # route-specific headers
            self.send_header(k, v)  # add each extra header
        self.end_headers()  # the blank line before the body
        if self.command != "HEAD":  # HEAD gets headers only
            try:
                self.wfile.write(data)  # the body
            except (BrokenPipeError, ConnectionResetError):  # the client hung up first (a probe that reads only the status): normal, not an error
                self.close_connection = True  # nothing more to send on this socket

    def _json(self, code, obj):  # the API's answers
        """A JSON answer."""
        self._send(code, json.dumps(obj, ensure_ascii=False))  # ensure_ascii off keeps Korean text readable and short

    def _host_ok(self):  # every method checks this first
        """Refuse requests that reach this port under another name (DNS rebinding)."""
        if self.headers.get("Host", "") in self.hosts:  # only names this server knows
            return True  # safe to answer
        self._send(403, "forbidden", "text/plain; charset=utf-8")  # a rebinding page gets nothing useful
        return False  # the caller stops here

    def do_OPTIONS(self):  # the browser asks before a cross-origin POST
        """The CORS preflight: granted to this server's own pages alone (a saved copy moves to the live page instead)."""
        if not self._host_ok():  # the same Host rule as every method
            return
        if self.headers.get("Origin") not in self.origins:  # another site, or "null", which any site's sandboxed frame can send
            self._send(403, "forbidden", "text/plain; charset=utf-8")  # no POST is granted
            return
        # no body; allow the methods and headers the page sends
        self._send(204, b"", "text/plain", {"Access-Control-Allow-Methods": "GET, POST", "Access-Control-Allow-Headers": "*"})

    def do_HEAD(self):  # a HEAD request runs the GET route
        """Headers of a GET."""
        self.do_GET()  # the same route; _send skips the body for HEAD

    def do_GET(self):  # every read request
        """The page, the fonts and the read-only API."""
        if not self._host_ok():  # refuse foreign Host names first
            return
        url = urllib.parse.urlsplit(self.path)  # path and query
        if url.path in ("/", "/index.html"):  # the page
            body = self.index.page()  # the page is built on each load, with the latest files
            self._send(200, body, "text/html; charset=utf-8", {"Content-Security-Policy": page_policy(body)})  # its own scripts only
        elif url.path.startswith("/fonts/"):  # the two font files, nothing else
            name = url.path[len("/fonts/"):]  # the file name after the prefix
            f = FONTS / name  # where it would be on disk
            if name in FONT_FILES and f.is_file():  # allow-list, so a path like ../ never reaches other files
                self._send(200, f.read_bytes(), "font/woff2", {"Cache-Control": "max-age=86400"})  # fonts do not change, so the browser may keep them a day
            else:
                self._send(404, "not found", "text/plain; charset=utf-8")  # any other name
        elif url.path == "/api/health" and self.headers.get("Origin") == "null":  # a saved copy asking whether to move to the live page
            self._json(200, {"ok": True})  # up, and nothing else: "null" may be any site's sandboxed frame
        elif url.path == "/api/health":  # liveness, the model's state and the index size
            self.index.ensure()  # build on first call; pick up edits
            d = self.dense  # None without a model
            self._json(200, {"ok": True, "items": len(self.index.items), "built_ms": self.index.built_ms,  # everything the health check reports, in one answer
                             "model": "bge-m3-int8" if d else None, "state": d.state if d else "none",  # which model, and its state
                             "error": d.error if d else "", "vectors": bool(d and d.mat is not None),  # the last load error, and whether vectors are built
                             "rss_mb": _rss()})  # memory use for the page's tooltip
        elif url.path == "/api/dense":  # every item's best similarity to the query
            self._dense(urllib.parse.parse_qs(url.query).get("q", [""])[0])  # the first q value, empty when missing
        elif url.path == "/cue":  # the printable cue cards
            qs = urllib.parse.parse_qs(url.query)  # ?ids=A1,B2 or ?sec=A,B, and ?roles=scenes,deep
            roles = tuple(r for r in (qs.get("roles", ["scenes"])[0] or "scenes").split(",") if r)  # which kinds of item get cards
            body = cue.page(self.index.job, qs.get("ids", [""])[0] or None, qs.get("sec", [""])[0] or None, roles)  # the page
            self._send(200, body, "text/html; charset=utf-8", {"Content-Security-Policy": page_policy(body, SCRIPT.findall(cue.PRINT_SCRIPT))})  # its print key's script only
        elif url.path == "/deck":  # the printable interview deck
            qs = urllib.parse.parse_qs(url.query)  # ?kinds=posting,resume  ?ids=A1,B2  ?n=6  ?lang=ko
            n = qs.get("n", [""])[0]  # scripts per part
            lang = qs.get("lang", [""])[0]  # the deck's own words
            body = deck.page(self.index.job, qs.get("kinds", [""])[0] or None, qs.get("ids", [""])[0] or None,  # the page
                             int(n) if n.isdigit() else None, lang if lang in ("ko", "en") else None,  # a bad value falls back
                             embedded=qs.get("embed", [""])[0] == "1")  # inside the panel, which names and prints it itself
            self._send(200, body, "text/html; charset=utf-8", {"Content-Security-Policy": page_policy(body, SCRIPT.findall(cue.PRINT_SCRIPT))})  # its print key's script only
        elif url.path == "/talk":  # the presentation interview's script, with the keys to its PDFs (talk.py writes them)
            from interview import talk_page  # the page
            embed = urllib.parse.parse_qs(url.query).get("embed", [""])[0] == "1"  # inside the panel, which has the PDF keys itself
            body = talk_page.served(self.index.job.out_path() / "talk", i18n.lang(), keys=not embed)
            self._send(200, body, "text/html; charset=utf-8", {"Content-Security-Policy": page_policy(body, [])})  # built without a script: none runs
        elif url.path in ("/talk/deck.pdf", "/talk/script.pdf"):  # the talk's slides and script, fixed names only
            f = self.index.job.out_path() / "talk" / url.path.rsplit("/", 1)[1]  # never a name from the request
            if f.is_file():
                self._send(200, f.read_bytes(), "application/pdf", {"Content-Disposition": "inline"})  # shown in the browser's own viewer
            else:
                self._send(404, "not found", "text/plain; charset=utf-8")
        elif url.path in PRACTICE_GET:  # practice reads
            self._practice(url.path, {})  # no body
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")  # an unknown path

    def do_POST(self):  # the model switch
        """Switch the similarity model on or off (only when the server has one)."""
        if not self._host_ok():  # refuse foreign Host names first
            return
        origin = self.headers.get("Origin")  # other web pages must not switch it
        if origin and origin not in self.origins:  # a request from a page that is not ours
            self._send(403, "forbidden", "text/plain; charset=utf-8")  # refuse it
            return
        path = urllib.parse.urlsplit(self.path).path  # the path without a query
        if path in PRACTICE_POST:  # practice mode
            self._practice_post(path)  # reads its own body
            return
        if self.dense is None or path not in ("/api/model/on", "/api/model/off"):  # keyword-only server
            self._send(404, "not found", "text/plain; charset=utf-8")  # nothing to switch
            return
        state = self.dense.switch(path.endswith("/on"))  # loads in the background
        if state == "loading":  # build the vectors once the model is up
            threading.Thread(target=self._warm, daemon=True).start()  # in the background, so this answer returns at once
        self._json(200, {"state": state})  # the page shows the new state

    def _body(self, cap):  # the practice writes send JSON or a recording
        """The request body, or None when it is missing or larger than cap bytes."""
        try:
            n = int(self.headers.get("Content-Length") or 0)  # browsers always send it for fetch bodies
        except ValueError:  # a malformed length
            return None
        if n <= 0 or n > cap:  # empty or too large: refused before reading
            return None
        return self.rfile.read(n)  # exactly the body

    def _practice_post(self, path):  # POST /api/practice/...
        """Read the body (a recording for /transcribe, JSON for the rest) and answer."""
        if path == "/api/practice/transcribe":  # the recording itself
            from interview import transcribe  # its size limit
            audio = self._body(transcribe.MAX_BYTES)  # the browser's recording
            if audio is None:  # empty or too large
                self._json(413, {"error": "recording missing or too large"})
                return
            out = self.practice.transcribe(audio, self.headers.get("Content-Type", ""))  # in a separate process
            self._json(200 if "text" in out else 503, out)  # 503 tells the page to ask for a typed answer
            return
        raw = self._body(MAX_JSON)  # a small JSON object
        try:
            data = json.loads(raw.decode("utf-8")) if raw else None  # the request
        except (UnicodeDecodeError, ValueError):  # not JSON
            data = None
        if not isinstance(data, dict):  # every practice write sends an object
            self._json(400, {"error": "a JSON object is expected"})
            return
        self._practice(path, data)  # the same dispatch as the reads

    def _practice(self, path, d):  # every practice route
        """Dispatch one practice call; a missing session or question is a 404, a bad value a 400."""
        p = self.practice  # practice.Practice
        try:
            if path == "/api/practice/setup":  # what is available
                out = p.setup()
            elif path == "/api/practice/history":  # earlier sessions
                out = {"sessions": p.store.list()}
            elif path == "/api/practice/start":  # a new session
                out = p.start(n=d.get("n", 8), kinds=d.get("kinds"), agent=bool(d.get("agent", True)), seed=d.get("seed"))
            elif path == "/api/practice/answer":  # feedback on one answer
                out = p.answer(d.get("sid"), d.get("qid"), turn=d.get("turn", 0), text=d.get("text", ""), typed=d.get("typed", True),
                               seconds=d.get("seconds"), speech_seconds=d.get("speech_seconds"), pauses=d.get("pauses"),
                               words=d.get("words"), question=d.get("question"))
            elif path == "/api/practice/followup":  # the next question about this answer
                out = p.followup(d.get("sid"), d.get("qid"), turn=d.get("turn", 0))
            else:  # /api/practice/end
                out = p.end(d.get("sid"), seconds=d.get("seconds"))
        except KeyError as e:  # an unknown session or question
            self._json(404, {"error": f"not found: {e}"})
            return
        except (TypeError, ValueError) as e:  # a value of the wrong type
            self._json(400, {"error": str(e)[:200]})
            return
        except Exception:  # noqa: BLE001  anything else (a full disk, a broken scene file): said instead of a dropped connection
            traceback.print_exc()  # the details on the server's own output, where a path or a system's words may stand
            self._json(500, {"error": "unexpected"})  # the page gets a word, never the error's text
            return
        self._json(200, out)

    def _warm(self):  # runs in its own thread after a switch-on
        """Wait for the model, then embed the views so the first query is fast."""
        for _ in range(600):  # up to a minute
            if self.dense.state != "loading":  # loaded or failed: stop waiting
                break
            time.sleep(0.1)  # check ten times a second
        self.index.ensure()  # the current items
        self.dense.ensure(self.index.items, self.index.alts, self.index.stamp, corpus.views)  # embed them now, before the first query

    def _dense(self, q):  # the /api/dense answer
        """Similarity scores for one query, or 503 while the model is off."""
        q = " ".join(q.split())[:MAX_QUERY]  # normalised, so the query cache hits more often
        if not q:  # an empty query has no similarity
            self._json(200, {"scores": [], "ms": 0})  # no scores and no error
            return
        d = self.dense  # a short name for the model
        if d is None or d.state != "on":  # switched off (or still loading): the page keeps to keywords
            # 503 tells the page to keep to keywords; state lets it show why
            self._json(503, {"error": "model " + (d.state if d else "none"), "state": d.state if d else "none"})
            return
        self.index.ensure()  # a file may have changed
        d.ensure(self.index.items, self.index.alts, self.index.stamp, corpus.views)  # vectors for the current items
        t0 = time.time()  # query timer
        try:
            scores = d.scores(q, self.index.items)  # one score per item
        except RuntimeError as e:  # switched off between the check and here, or vectors not ready
            self._json(503, {"error": str(e), "state": d.state})  # the page keeps to keywords
            return
        self._json(200, {"scores": scores, "ms": int((time.time() - t0) * 1000)})  # the scores and the query time, for the page


def _rss():  # for /api/health
    """Resident memory in MB (Linux), for the page's tooltip."""
    from interview import dense  # the helper lives with the model code (no third-party import at module level)
    return dense.rss_mb()  # None where the number cannot be read


# used by serve, the browser checks and the tests
def make_server(job, port=8796, host="127.0.0.1", model_dir=None, threads=6, embedder=None, public_port=None, cache_dir=None,
                out_dir=None, backend=None, practice_ask=None, stt=None):
    """A ready (not yet serving) HTTP server for a job. port 0 picks a free port (tests). out_dir holds the practice
    sessions (default: the job's output folder, created on the first session); backend, practice_ask and stt choose or
    stand in for the model and the speech model of practice mode."""
    d = None  # no model: keyword search only
    if model_dir or embedder:  # the optional similarity half
        from interview import dense  # imported only when asked for
        cache = cache_dir or job.out_dir() / "vectors"  # embedded vectors, kept with the job's other outputs
        d = dense.Dense(model_dir, cache, threads=threads, embedder=embedder)  # starts switched off; the page's switch loads it
    from ownport import Server  # src/ownport.py: the port held alone, so a second kit server never shares 8796 on Windows
    srv = Server((host, port), Handler)  # one thread per request; a stuck request never blocks shutdown
    real = srv.server_address[1]  # the port actually bound
    shown = public_port or real  # the port the browser uses (differs only behind a port mapping)
    index = Index(job, shown, model=d is not None)  # items and page data
    names = {f"127.0.0.1:{shown}", f"localhost:{shown}", f"[::1]:{shown}"}  # accepted Host headers
    prac = practice.Practice(job, out_dir or job.out_path(), backend=backend, ask=practice_ask, stt=stt)  # practice mode; writes only when a session starts
    handler = type("BoundHandler", (Handler,), {"index": index, "dense": d, "hosts": names, "practice": prac,  # a subclass per server, so two servers in one process keep their own state
                                                # origins allowed to call the API: this server's own page under its two names
                                                "origins": {f"http://127.0.0.1:{shown}", f"http://localhost:{shown}"}})
    srv.RequestHandlerClass = handler  # bind this job's index to the handler
    index.ensure()  # parse once before the first request
    return srv, index


if __name__ == "__main__":  # the panel's way in: OFFEROWL_WORKSPACE, OFFEROWL_JOB and OFFEROWL_PORT name what to serve
    import os  # the settings
    from interview import cli  # the serve command does the rest
    args = sys.argv[1:]  # options given on the command line win over the settings
    ws, name = os.environ.get("OFFEROWL_WORKSPACE", ""), os.environ.get("OFFEROWL_JOB", "")  # the panel's workspace and job
    if not args and ws and name:  # started by the panel: serve that job on its port
        args = ["--job", str(pathlib.Path(ws) / "jobs" / name), "--port", os.environ.get("OFFEROWL_PORT", "8796")]
    sys.exit(cli.main(["serve"] + args))  # without either, serve says which option is missing
