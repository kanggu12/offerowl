"""The API behind HTTP, with the safety rules listed below. apps/panel/server.py adds the page's files to
the same handler; `python3 -m apps.api serve` runs the API alone. (Named web.py, not http.py, so it can never shadow the standard library.)

  - It listens on 127.0.0.1 only (the caller binds it).
  - It answers only requests whose Host names this PC and its port, which stops DNS rebinding.
  - A write needs a JSON body and, from a browser, an Origin of this page: a form post or another site's page cannot
    write here.
  - A file upload needs its own body type and a header of its own (X-File-Name), so a browser asks first (a CORS
    preflight) and this server never says yes.
"""
from __future__ import annotations

import contextlib  # an old upload's piece that will not go
import gzip  # the state, compressed for a browser that takes it
import hashlib  # the state's ETag
import http.server  # the server
import json  # bodies
import logging  # errors to the log
import os  # OFFEROWL_ALLOWED_HOSTS, and an upload's own file name
import threading  # an upload's own file name
import time  # the date in a backup's name
import urllib.error  # the kit's refusals
import urllib.parse  # paths and queries
import urllib.request  # the kit, reached in this process
from pathlib import Path  # the folder an upload is written to

from . import materials  # a job's own materials, sent as files
from .routes import JSON, Router, dumps  # the API's table

MAX_JSON = 2_000_000  # bytes of a JSON request
MAX_UPLOAD = 60_000_000  # bytes of one uploaded file
MAX_BACKUP = 500_000_000  # bytes of a workspace's backup, which holds every file and document: a real one is tens of megabytes
MAX_PHOTO = 10_000_000  # bytes of a resume photo: a phone's full-size picture fits
GZIP_MIN = 1024  # bytes below which compressing costs more than it saves
GZIP_LEVEL = 6  # zlib's usual trade: a few milliseconds for a 100 KB state, a quarter of its bytes
log = logging.getLogger("offerowl.api")  # the API's log
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
       "media-src 'self' blob:; "  # a practice answer played back from its recording in the page (interview.js), nothing from elsewhere
       "frame-src 'none'; "  # no page in a frame, of this address or another: the previews (a deck, a saved web page) are written into theirs (srcdoc)
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")  # nothing loads from elsewhere, nothing frames the page


KIT_BODY_MAX = 32 * 1024 * 1024  # a practice recording passed to the kit: its own cap (transcribe.MAX_BYTES, 30 MiB) and room for the headers
KIT_CSP = "frame-ancestors 'self'; base-uri 'none'; object-src 'none'; form-action 'self'; connect-src 'self'"  # the kit at the panel's address (kit_proxy)
KIT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # straight to the kit on this PC, never through HTTP_PROXY

class ApiHandler(http.server.BaseHTTPRequestHandler):
    """The API's routes over HTTP. Subclasses may answer more GET paths in `extra_get` (the panel's page)."""

    router: Router = None  # set by bind()
    hosts: set = set()  # the Host headers accepted
    origins: set = set()  # the Origins accepted on writes
    server_version = "offerowl"  # no Python version in the headers
    sys_version = ""  # nor the Python build after it
    body_read = False  # set once the request's body is read; a refusal before that reads it first (refuse)
    DRAIN_MAX = 1_000_000  # bytes of a refused request's body read before the answer
    timeout = 120  # seconds a socket read or write may wait: a client that says a length and stops sending, or a kept-alive
    #                connection nobody uses, lets its thread go (http.server closes the connection on the timeout)

    @classmethod
    def bind(cls, router: Router, port: int) -> None:
        """Point the handler at one API and the port it was bound to."""
        cls.router = router  # every request thread shares this one API
        cls.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}  # this PC only
        cls.origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}  # the page's own origins, for writes
        # Behind an Ingress the Host header is the Ingress' own name. The Helm chart lists those names in
        # OFFEROWL_ALLOWED_HOSTS (comma-separated); every other name is still refused.
        for name in filter(None, (h.strip() for h in os.environ.get("OFFEROWL_ALLOWED_HOSTS", "").split(","))):
            cls.hosts.add(name)  # the name as the Ingress sends it
            cls.origins.update({f"https://{name}", f"http://{name}"})  # writes from pages served under that name

    # ------------------------------------------------------------------ plumbing

    def takes_gzip(self) -> bool:
        """The client said it reads gzip (Accept-Encoding), and did not refuse it with q=0. A browser always says so; urllib
        and the panel's own tools do not, and get plain bytes."""
        for part in (self.headers.get("Accept-Encoding") or "").split(","):  # each coding it names
            name, _, params = part.strip().partition(";")  # gzip;q=0.8
            if name.strip().lower() in ("gzip", "*"):  # gzip itself, or any coding
                q = params.strip().lower().replace(" ", "")  # "q=0.5", or "" for no weight
                try:
                    return not q.startswith("q=") or float(q[2:]) > 0  # no weight is 1; q=0 refuses it
                except ValueError:  # a weight that is not a number: taken as given
                    return True
        return False  # not named: plain bytes

    def send_state(self, code: int, body) -> None:
        """The state, which the panel asks for every few seconds: with an ETag, so a poll that finds nothing changed gets a
        304 with no body (If-None-Match), and compressed for a client that takes gzip."""
        data = dumps(body)  # the bytes the ETag names
        if code != 200:  # a failed state: sent as any other answer
            return self.send(code, body)
        tag = 'W/"' + hashlib.sha1(data).hexdigest()[:20] + '"'  # weak: the same state is the same tag compressed or not
        asked = [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]  # the tags the client holds
        if tag in asked or tag[2:] in asked or "*" in asked:  # it holds this very state (a strong spelling of the tag matches too)
            self.send_response(304)  # nothing changed: no body
            self.send_header("ETag", tag)  # the tag it already holds
            self.send_header("Cache-Control", "no-store")  # as every answer: the page asks again itself
            self.send_header("Vary", "Accept-Encoding")  # the bytes depend on the coding asked for
            self.end_headers()  # a 304 has no body
            return
        return self.send(200, data, etag=tag)  # the state itself, compressed by send when the client takes it

    _files: dict = {}  # a page file's path -> (mtime_ns, size, tag, bytes, gzipped bytes or None): read once per change
    _files_lock = threading.Lock()  # request threads ask for the page's files at the same time

    def send_file(self, path: Path, ctype: str) -> None:
        """A file of the page (index.html, a script, a style) with an ETag and `no-cache`: the browser asks every time, so
        the page and its scripts stay in step after an update, and a file it already holds comes back as 304 with no body.
        Compressed for a client that takes gzip (the page's files are 932 KB, 248 KB compressed, which a phone or a panel
        behind an Ingress fetched whole at every load). Read, hashed and compressed once per change of the file."""
        st = path.stat()  # its size and time: a changed file is read again
        key = str(path)
        with self._files_lock:
            hit = self._files.get(key)
        if not hit or hit[0] != st.st_mtime_ns or hit[1] != st.st_size:  # new, or changed since
            raw = path.read_bytes()
            tag = 'W/"' + hashlib.sha1(raw).hexdigest()[:20] + '"'  # weak: the same file is the same tag compressed or not
            zipped = gzip.compress(raw, GZIP_LEVEL, mtime=0) if len(raw) >= GZIP_MIN else None  # a small file goes as it is
            hit = (st.st_mtime_ns, st.st_size, tag, raw, zipped)
            with self._files_lock:
                self._files[key] = hit
        _, _, tag, raw, zipped = hit
        asked = [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]  # the tags the browser holds
        same = tag in asked or tag[2:] in asked or "*" in asked  # it holds this very file
        use_zip = not same and zipped is not None and self.takes_gzip()
        data = b"" if same else zipped if use_zip else raw
        self.send_response(304 if same else 200)
        if not same:
            self.send_header("Content-Type", ctype)
        self.send_header("ETag", tag)  # sent back as If-None-Match at the next load
        self.send_header("Vary", "Accept-Encoding")  # the bytes depend on the coding asked for
        if use_zip:
            self.send_header("Content-Encoding", "gzip")
        if not same:
            self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")  # kept, but asked about every time: never a stale script
        self.send_header("X-Content-Type-Options", "nosniff")  # the browser keeps the type, never guesses one
        self.send_header("Referrer-Policy", "no-referrer")  # links to elsewhere carry no address of this PC
        self.send_header("Content-Security-Policy", CSP)  # nothing loads from elsewhere
        try:
            self.end_headers()
            if data and self.command != "HEAD":  # a 304 and a HEAD have no body
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):  # the browser went away first
            pass

    def send(self, code: int, body, ctype: str = JSON, cache: bool = False, name: str | None = None, etag: str | None = None) -> None:
        """Send one answer. An answer with an ETag (the state) is compressed for a client that takes gzip."""
        data = dumps(body)  # bytes (send_state hands them over already made, and dumps keeps bytes as they are)
        zipped = bool(etag) and len(data) >= GZIP_MIN and self.takes_gzip()  # only the state is compressed (the page polls it)
        if zipped:
            data = gzip.compress(data, GZIP_LEVEL, mtime=0)  # mtime=0: the same state gives the same bytes
        self.send_response(code)  # the status line
        self.send_header("Content-Type", ctype)  # JSON unless the route says otherwise
        if etag:  # the state's tag and how its bytes are coded
            self.send_header("ETag", etag)  # the page sends it back as If-None-Match
            self.send_header("Vary", "Accept-Encoding")  # the bytes depend on the coding asked for
        if zipped:
            self.send_header("Content-Encoding", "gzip")  # the browser unpacks it before the page reads it
        self.send_header("Content-Length", str(len(data)))  # the browser knows where the answer ends
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")  # fonts may be cached, nothing else
        self.send_header("X-Content-Type-Options", "nosniff")  # the browser keeps the type, never guesses one
        self.send_header("Referrer-Policy", "no-referrer")  # links to elsewhere carry no address of this PC
        self.send_header("Content-Security-Policy", CSP)  # nothing loads from elsewhere
        if name:  # a file to save (the calendar file)
            self.send_header("Content-Disposition", f"attachment; filename=\"{name}\"")  # saved, not shown
        for k, v in (getattr(body, "headers", None) or {}).items():  # a file's own headers (routes.FileAnswer): its name, and a sandbox for a web page
            self.send_header(k, v)  # a second policy adds to the first: both apply
        try:
            self.end_headers()  # the body follows
            if self.command != "HEAD":  # a HEAD request gets the headers only
                self.wfile.write(data)  # the answer itself
        except (BrokenPipeError, ConnectionResetError):  # the client hung up first (a refused request it stopped waiting on): nothing to answer
            self.close_connection = True  # this socket is done; no traceback for a normal end

    def log_message(self, fmt, *args):  # errors only, to the log
        if len(args) > 1 and str(args[1])[:1] in "45":  # only 4xx and 5xx answers are worth a line (a timeout's one-word line is not)
            log.info("%s %s", self.address_string(), fmt % args)  # who asked, and what came back

    def refuse(self, code: int, body: dict) -> None:
        """A refusal sent before the request's body was read. The body is read first, up to a megabyte: a socket closed with
        bytes unread is reset, and on Windows the reset can reach the client before the answer does, which then reads as a
        dropped connection instead of the refusal."""
        if self.command == "POST" and not self.body_read:  # a body that may still be on its way
            try:
                n = int(self.headers.get("Content-Length") or 0)  # its size, as the client says
                if 0 < n <= self.DRAIN_MAX:  # a small one: read and dropped
                    self.connection.settimeout(10)  # a client that sends less than it said does not hold the thread
                    self.rfile.read(n)
            except (ValueError, OSError):  # a bad length, or a client that stopped sending: answered all the same
                pass
        self.send(code, body)  # the refusal

    def host_ok(self) -> bool:
        """The Host header names this PC and port (a page of another site cannot read this one by DNS rebinding)."""
        if self.headers.get("Host") in self.hosts:  # 127.0.0.1 or localhost with this port
            return True  # the request may go on
        self.refuse(403, {"error": "host"})  # a rebound name gets nothing
        return False  # the caller stops here

    def cross_site(self, path: str) -> bool:
        """A read another site's page set off: an image, a fetch or a frame pointed at this panel. The answer stays unread
        there, but the work is done all the same (a backup zipped, a kit server started, the agents' commands run), so the
        API and the kits refuse it. The browser names where a request comes from (Sec-Fetch-Site), and a page of another
        origin that fetches sends its Origin. Opening the panel itself from a link elsewhere stays allowed; a client that
        is no browser sends neither header."""
        origin = self.headers.get("Origin")  # a fetch from a page
        if origin and origin not in self.origins:  # of another origin
            return True
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):  # another site, or another port of this PC
            opened = self.headers.get("Sec-Fetch-Mode") == "navigate" and self.headers.get("Sec-Fetch-Dest") == "document"  # a link followed
            return not opened or path.startswith(("/api/", "/kit/"))  # the page may be opened that way, nothing that does work
        return False

    def read_json(self) -> dict:
        """A write's body: same origin, JSON, within the size limit."""
        origin = self.headers.get("Origin")  # browsers send it on writes
        if origin and origin not in self.origins:  # no Origin means a tool, not a page
            raise PermissionError("origin")  # another site's page
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):  # cross-site JSON needs a CORS preflight
            raise PermissionError("type")  # a form post from elsewhere cannot set this type
        n = int(self.headers.get("Content-Length") or 0)  # the body's size, as the client says
        if not 0 <= n <= MAX_JSON:  # a negative or oversized body
            raise PermissionError("length")  # refused before reading
        raw = self.rfile.read(n)  # the request
        self.body_read = True  # nothing left to read for a refusal
        req = json.loads(raw or b"{}")  # as JSON
        if not isinstance(req, dict):  # a list or a number is not a request
            raise ValueError("shape")  # answered as bad_request
        return req  # checked

    def query(self) -> dict:
        """The query's first value per name."""
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}  # name -> value

    # ------------------------------------------------------------------ GET

    def extra_get(self, path: str) -> bool:
        """More GET paths of a subclass (the panel's page and files). True when it answered."""
        return False  # the API alone has none

    def do_HEAD(self):  # noqa: N802  (http.server's names)
        self.do_GET()  # the same answer without the body

    def do_GET(self):  # noqa: N802
        if not self.host_ok():  # DNS rebinding is refused first
            return  # the 403 is already sent
        path = urllib.parse.urlsplit(self.path).path  # without the query
        if self.cross_site(path):  # another site's page asking this one to do work
            return self.refuse(403, {"error": "cross_site"})
        if path.startswith("/kit/"):  # an application's interview kit, at the panel's own address
            return self.kit_proxy("GET")
        try:
            if not path.startswith("/api/") and path != "/health" and self.extra_get(path):  # the page and its files
                return  # answered
        except Exception:  # a bug in a page route: logged, answered
            log.exception("GET %s", path)  # the traceback goes to the log
            return self.send(500, {"error": "unexpected"})  # a general error
        if not path.startswith("/api/") and path != "/health":  # not the API's
            return self.send(404, {"error": "not_found"})  # nothing here
        code, body, ctype = self.router.handle("GET", path, self.query())  # the API answers
        if path == "/api/v1/state" or path.endswith(("/interview/view", "/interview/deck")):  # the state, polled every few seconds, and a kit's scripts (megabytes): a 304 when unchanged, compressed when not
            return self.send_state(code, body)
        name = "offerowl-reminders.ics" if ctype.startswith("text/calendar") else None  # the calendar is a file to save
        name = f"offerowl-backup-{time.strftime('%Y-%m-%d')}.zip" if ctype == "application/zip" else name  # and so is a backup
        return self.send(code, body, ctype, name=name)  # sent

    # ------------------------------------------------------------------ POST

    def do_POST(self):  # noqa: N802
        self.body_read = False  # nothing of this request's body read yet
        if not self.host_ok():  # DNS rebinding is refused first
            return  # the 403 is already sent
        path = urllib.parse.urlsplit(self.path).path  # without the query
        if path.startswith("/kit/"):  # the kit's practice writes, from the panel's own page only
            if (self.headers.get("Origin") or "") not in self.origins:
                return self.refuse(403, {"error": "origin"})
            return self.kit_proxy("POST")
        try:  # the body's checks: refusals become 403, bad bodies 400
            if path == "/api/v1/materials":  # a file upload: its own body type, which no other site's page can send
                return self.upload()  # it checks its own headers
            if path == "/api/v1/workspace/restore":  # a backup, sent the same way
                return self.restore()  # the same checks
            if path == "/api/v1/photo":  # the resume's photo, sent the same way
                return self.photo()  # the same checks
            if path == "/api/v1/interview/scenes":  # interview scripts written before, sent the same way
                return self.scenes()  # the same checks
            if path == "/api/v1/jobs/questions/file":  # a screenshot, a PDF or a saved page of the form, its questions read from it
                return self.question_file()  # the same checks
            if path == "/api/v1/jobs/own-file":  # a document the person made for an edition, kept as it is
                return self.job_file("own_file")  # the same checks
            if path == "/api/v1/jobs/sent-file":  # a file that went out with an application, kept as its submitted copy
                return self.job_file("sent_file")  # the same checks
            if path == "/api/v1/jobs/materials":  # a deck, notes or a brief for a job's materials, sent the same way
                return self.job_material()  # the same checks
            req = self.read_json()  # every other write is JSON
        except PermissionError as exc:  # origin, type or size refused, or the system refusing a file
            if exc.errno is not None:  # the system's own refusal: its words hold a path, which never goes to the page
                log.exception("POST %s", path)  # kept in the log
                return self.send(500, {"error": "unexpected"})  # the page shows a general error
            return self.refuse(403, {"error": str(exc)})  # names the check that refused
        except ValueError:  # not JSON, not an object, or a bad length header
            return self.refuse(400, {"error": "bad_request"})  # nothing was done
        except Exception:  # an upload that failed on its own (a full disk): answered, not a dropped connection
            log.exception("POST %s", path)  # the traceback goes to the log, not the page
            return self.send(500, {"error": "unexpected"})  # the page shows a general error
        code, body, ctype = self.router.handle("POST", path, self.query(), req)  # the API answers
        return self.send(code, body, ctype)  # sent

    def kit_proxy(self, method: str):
        """/kit/<job>/<path>: the interview kit's search view, deck, cue cards and practice, served at the panel's own address.
        Each job's kit runs in this process on a port of its own (tasks.kit_url); its answers are passed on byte for byte, so
        the person needs one address only, and the panel's pages frame it as their own."""
        parts = urllib.parse.urlsplit(self.path)
        rest = parts.path[len("/kit/"):]
        job, slash, sub = rest.partition("/")
        if not slash:  # /kit/<job>: the page's relative links need the folder's slash
            self.send_response(301)
            self.send_header("Location", f"/kit/{job}/" + (f"?{parts.query}" if parts.query else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        api = self.router.api  # the panel's API: it starts the kit for this job
        try:
            jid = api.need_job({"job": urllib.parse.unquote(job)})
        except ValueError:  # no such application, one in the Trash, or a name no job can have (any other error is a bug: answered as one)
            return self.refuse(404, {"error": "no_job"})  # a body still on its way is read first
        base = api.tasks.kit_url(jid)  # this job's own kit server
        if not base:  # no kit yet, or it would not start
            return self.refuse(404, {"error": "no_kit"})
        body = None
        if method == "POST":  # the practice's writes: JSON or a recording
            try:
                n = int(self.headers.get("Content-Length") or 0)  # as the client says
            except ValueError:  # not a number
                return self.refuse(400, {"error": "bad_length"})
            if n < 0:  # rfile.read(-1) would wait for the end of the stream
                return self.refuse(400, {"error": "bad_length"})
            if n > KIT_BODY_MAX:  # over the kit's own cap on a recording
                return self.refuse(413, {"error": "too_large"})
            body = self.rfile.read(n) if n else b""
            self.body_read = True
        url = base + sub + (f"?{parts.query}" if parts.query else "")
        headers = {"Origin": base.rstrip("/")}  # the kit's own origin: its writes check it
        for h in ("Content-Type", "X-File-Name", "Range"):
            if self.headers.get(h):
                headers[h] = self.headers[h]
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with KIT_OPENER.open(req, timeout=600) as r:
                code, data, rh = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:  # the kit's own refusal, passed on
            code, data, rh = e.code, e.read(), e.headers
        except OSError:  # the kit's server is gone
            return self.send(502, {"error": "kit_unreachable"})
        self.send_response(code)
        for h in ("Content-Type", "Content-Security-Policy", "Content-Disposition", "Cache-Control"):
            if rh.get(h):
                self.send_header(h, rh[h])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # the kit's pages now share the panel's origin: framed by the panel's own pages only, no base or plugin, and their requests
        # stay at this address (a second policy beside any the kit sends: a browser keeps to both)
        self.send_header("Content-Security-Policy", KIT_CSP)
        try:
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):  # the page went before the kit's answer came: nothing to answer
            self.close_connection = True

    def file_body(self, cap: int) -> bytes | None:
        """A file as the raw body, its name in X-File-Name; None once a refusal is sent. The type and the custom header make a
        browser ask first (a CORS preflight) before another site's page could send it, and this server never says yes to that."""
        n = self.file_length(cap)  # every check, before a byte is read
        if n is None:  # refused, and answered
            return None
        data = self.rfile.read(n)  # the file
        self.body_read = True  # nothing left to read for a refusal
        return data

    def file_spool(self, cap: int, folder: Path) -> Path | None:
        """The same checks as file_body, the body written in pieces to a file of its own in `folder`: a backup can be hundreds
        of megabytes, and never sits whole in memory. The caller removes the file. None once a refusal is sent. A piece left by
        an upload that was cut off (the server stopped mid-way) goes once it is an hour old."""
        n = self.file_length(cap)  # every check, before a byte is read
        if n is None:  # refused, and answered
            return None
        folder.mkdir(parents=True, exist_ok=True)  # the data folder, on its disk (a container's /tmp is memory)
        for old in folder.glob(".upload-*.part"):  # an earlier upload that never finished
            with contextlib.suppress(OSError):
                if time.time() - old.stat().st_mtime > 3600:  # an hour old: not one on its way now
                    old.unlink()
        f = folder / f".upload-{os.getpid()}-{threading.get_ident()}.part"  # this request's own
        left = n  # bytes still to come
        with f.open("wb") as out:  # written as it arrives
            while left:
                piece = self.rfile.read(min(left, 1 << 20))  # a megabyte at a time
                if not piece:  # the client stopped sending: what came is what is read
                    break
                out.write(piece)
                left -= len(piece)
        self.body_read = True  # nothing left to read for a refusal
        return f

    def file_length(self, cap: int) -> int | None:
        """The checks of an upload: the page's own origin, the raw type and the file name's header, a size within the cap. The
        size, or None once a refusal is sent."""
        origin = self.headers.get("Origin")  # browsers send it on writes
        if origin and origin not in self.origins:  # another site's page
            self.refuse(403, {"error": "origin"})  # refused before reading the body
            return None  # the caller stops
        # both the type and the header force a preflight, which this server never answers
        if (self.headers.get("Content-Type") or "") != "application/octet-stream" or not self.headers.get("X-File-Name"):
            self.refuse(403, {"error": "type"})  # a plain form post stops here
            return None  # the caller stops
        n = int(self.headers.get("Content-Length") or 0)  # the file's size, as the client says
        if n <= 0:  # an empty file has nothing to read
            self.send(400, {"error": "empty"})  # the page says the file is empty
            return None  # the caller stops
        if n > cap:  # over the cap
            self.refuse(413, {"error": "too_large"})  # refused before reading (a body this large is not read: the connection closes)
            return None  # the caller stops
        return n  # checked

    def upload(self) -> None:
        """One file for the workspace's sources."""
        data = self.file_body(MAX_UPLOAD)  # with every check
        if data is None:  # refused, and answered
            return  # nothing more
        name = urllib.parse.unquote(self.headers["X-File-Name"])[:200]  # the file's own name
        recs = self.router.api.ws.add_materials(name, data)  # kept in sources/; a zip gives each file in it
        if not recs:  # a zip with nothing a reader knows
            return self.send(400, {"error": "empty"})  # the page says so
        return self.send(200, {"ok": True, "material": recs[0], "materials": recs})  # the page then asks to read them

    def photo(self) -> None:
        """The resume's photo (JPEG or PNG), in the workspace's profile folder."""
        data = self.file_body(MAX_PHOTO)  # with every check
        if data is None:  # refused, and answered
            return  # nothing more
        try:
            self.router.api.set_photo(data)  # checked and kept
        except ValueError as exc:  # not a JPEG or a PNG
            return self.send(400, {"error": str(exc)})  # the page says so
        return self.send(200, {"ok": True})  # the page draws it

    def scenes(self) -> None:
        """A file of interview scenes (the kit's markdown) into a job's interview folder; the job is in the query."""
        data = self.file_body(MAX_UPLOAD)  # with every check
        if data is None:  # refused, and answered
            return  # nothing more
        name = urllib.parse.unquote(self.headers["X-File-Name"])[:200]  # the file's own name
        try:
            got = self.router.api.add_scenes(str(self.query().get("job") or ""), name, data)  # the job named in the query
        except ValueError as exc:  # not a scene file, or no such job
            return self.send(400, {"error": str(exc)})  # the page says which
        return self.send(200, {"ok": True, **got})  # the page draws the new scenes

    def question_file(self) -> None:
        """A picture or a file of an application form: its text read (OCR for a picture), its questions added to the job in the query."""
        data = self.file_body(MAX_UPLOAD)  # with every check
        if data is None:  # refused, and answered
            return  # nothing more
        name = urllib.parse.unquote(self.headers["X-File-Name"])[:200]  # the file's own name, for its kind
        try:
            got = self.router.api.questions_from_file(str(self.query().get("job") or ""), name, data)  # read and added
        except ValueError as exc:  # no question in it, or no such job
            return self.send(400, {"error": str(exc)})  # the page says which
        return self.send(200, {"ok": True, "added": got})  # the page draws them

    def job_file(self, action: str) -> None:
        """A file for one edition of a job (or a named edition): the job, the language and the kind of document are in the
        query. action is the App method that keeps it (own_file: it stands for the typeset one; sent_file: a submitted copy)."""
        data = self.file_body(MAX_UPLOAD)  # with every check
        if data is None:  # refused, and answered
            return  # nothing more
        name = urllib.parse.unquote(self.headers["X-File-Name"])[:200]  # the file's own name, for its type
        q = self.query()  # job, lang, kind
        try:
            got = getattr(self.router.api, action)(str(q.get("job") or ""), str(q.get("lang") or ""), str(q.get("kind") or ""), name, data)
        except ValueError as exc:  # no such job, a kind or a type it does not take
            return self.send(400, {"error": str(exc)})  # the page says which
        return self.send(200, {"ok": True, **got})  # what was kept

    def job_material(self) -> None:
        """One file for a job's own materials (a deck, notes, a brief, an answer, a solution), kept byte for byte; the job is
        in the query. A kind a job does not keep is refused with material_kind, a file over 50 MB with too_large."""
        data = self.file_body(materials.MAX_BYTES)  # with every check, under the materials' own cap
        if data is None:  # refused, and answered
            return  # nothing more
        name = urllib.parse.unquote(self.headers["X-File-Name"])  # the file's own name, whole: its extension is its kind (materials.add shortens it)
        try:
            rec = materials.add(self.router.api.ws, str(self.query().get("job") or ""), name, data)  # the job named in the query
        except ValueError as exc:  # a kind not kept, no such job
            return self.send(400, {"error": str(exc)})  # the page says which
        return self.send(200, {"ok": True, "material": rec})  # the page draws it in the list

    def restore(self) -> None:
        """A backup in the workspace's place. The workspace as it was stays beside it, and its folder is named in the answer."""
        f = self.file_spool(MAX_BACKUP, self.router.api.ws.root.parent)  # with every check, into the data folder beside the workspace
        if f is None:  # refused, and answered
            return  # nothing more
        try:
            try:
                done = self.router.api.restore(f)  # the workspace, from the file
            finally:
                with contextlib.suppress(OSError):  # held a moment longer on Windows: the hour-old sweep above takes it then
                    f.unlink(missing_ok=True)  # the upload's own file, whatever happened, gone before the answer (after it, a
                    # client that looked at once could still find it: Windows' CI did)
        except ValueError as exc:  # not a backup, too large, or a task is running
            return self.send(400, {"error": str(exc)})  # the page says which
        return self.send(200, {"ok": True, **done})  # the page reloads
