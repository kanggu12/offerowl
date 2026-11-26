"""One server to a port, on every system Offerowl runs on.

Python's HTTP server turns on SO_REUSEADDR. On Linux and macOS that only lets a new server take a port its last run left
waiting; on Windows it lets a second server bind a port another one is listening on, and the two then share that port's
requests (measured with Python 3.14 on Windows: a second http.server binds the port of a running one). So on Windows the
port is taken with SO_EXCLUSIVEADDRUSE instead, and a second start is refused there as it is everywhere else. The panel,
the API served alone, the interview kit's view and the agent's stand-in all bind through this class.
"""
from __future__ import annotations

import base64  # the busy page's script, named by its hash in the page's policy
import contextlib  # a read that may fail
import hashlib  # that hash
import http.server  # the threaded server the rest of Offerowl serves with
import os  # the cap, from the environment
import socket  # the socket option
import sys  # which system this is
import threading  # the requests served at once, counted
from pathlib import Path  # the wordmark's file

MAX_REQUESTS = 64  # requests a server serves at once, unless OFFEROWL_MAX_REQUESTS says otherwise


def cap_from_env() -> int:
    """OFFEROWL_MAX_REQUESTS, the requests a server serves at once (4 to 1024); anything else keeps MAX_REQUESTS."""
    try:  # a word or an empty value is no number
        n = int(os.environ.get("OFFEROWL_MAX_REQUESTS") or MAX_REQUESTS)
    except ValueError:
        return MAX_REQUESTS
    return n if 4 <= n <= 1024 else MAX_REQUESTS  # too few would refuse the page's own requests; too many is no cap


LOGO = Path(__file__).resolve().parents[1] / "docs" / "assets" / "logo-light.svg"  # the wordmark the panel's bar shows (a copy without docs has none)
LOGO_INKS = (('<circle cx="21.8" cy="37.6" r="3" fill="#1B2E4B"/>', '<circle cx="21.8" cy="37.6" r="3" style="fill:var(--pupil)"/>'),  # the eyes' pupils
             ('<circle cx="42.2" cy="37.6" r="3" fill="#1B2E4B"/>', '<circle cx="42.2" cy="37.6" r="3" style="fill:var(--pupil)"/>'),
             ('fill="#1B2E4B"', 'style="fill:var(--owl)"'), ('stroke="#FFFFFF"', 'style="stroke:var(--brow)"'),  # the owl and its brows
             ('fill="#1D1C1D"', 'style="fill:var(--ink)"'))  # the word: the colours logo-dark.svg gives them, by the theme's variables
BUSY_WORDS = {  # the page's words, in the language the browser asks for first (language)
    "en": ("Offerowl is answering many requests at once.", "This page loads again in {n} seconds.", "Load now"),
    "ko": ("Offerowl이 요청을 많이 받고 있습니다.", "{n}초 뒤 이 화면을 다시 불러옵니다.", "지금 불러오기"),
}
LIGHT = ("color-scheme:light;--desk:#f3f3f4;--desk-top:#f8f8f9;--desk-low:#ececed;--dot:rgba(0,0,0,.11);--ink:#171717;--ink-2:#404148;"
         "--card:rgba(255,255,255,.6);--rim:rgba(0,0,0,.075);"
         "--lift:inset 0 1px 0 rgba(255,255,255,.95),0 0 0 1px rgba(0,0,0,.075),0 1px 2px rgba(0,0,0,.04),0 14px 30px -22px rgba(0,0,0,.3);"
         "--key:#171717;--key-ink:#fff;--key-rim:#131313;--key-deep:#000;--owl:#1B2E4B;--brow:#FFFFFF;--pupil:#1B2E4B")  # the missing page's light theme, as measured
DARK = ("color-scheme:dark;--desk:#121214;--desk-top:#161619;--desk-low:#0e0e10;--dot:rgba(255,255,255,.075);--ink:#ededed;--ink-2:#d4d4d9;"
        "--card:rgba(31,32,36,.62);--rim:rgba(255,255,255,.08);"
        "--lift:inset 0 1px 0 rgba(255,255,255,.07),0 0 0 1px rgba(255,255,255,.08),0 1px 0 rgba(0,0,0,.4),0 18px 38px -24px rgba(0,0,0,.95);"
        "--key:#ededed;--key-ink:#111;--key-rim:#c2c2c2;--key-deep:#d6d6d6;--owl:#2A4A78;--brow:#E9EEF6;--pupil:#16263E")  # and its dark one
BUSY_STYLE = (":root{" + LIGHT + "}@media (prefers-color-scheme:dark){:root:not([data-theme=light]){" + DARK + "}}:root[data-theme=dark]{" + DARK + "}"
              "html{background:var(--desk)}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;box-sizing:border-box;color:var(--ink);"
              "font:13px/1.6 Pretendard,'Pretendard TTF',system-ui,-apple-system,'Segoe UI','Apple SD Gothic Neo','Malgun Gothic',sans-serif}"
              "body::before{content:'';position:fixed;inset:0;z-index:-2;background:linear-gradient(180deg,var(--desk-top) 0,var(--desk) 45%,var(--desk-low) 100%)}"
              "body::after{content:'';position:fixed;inset:0;z-index:-1;background:radial-gradient(var(--dot) 1px,transparent 1.35px) 0 0/22px 22px;"
              "-webkit-mask-image:linear-gradient(#000 0,rgba(0,0,0,.6) 55%,rgba(0,0,0,.28) 100%);mask-image:linear-gradient(#000 0,rgba(0,0,0,.6) 55%,rgba(0,0,0,.28) 100%)}"
              "main{width:min(440px,100%)}section{display:grid;gap:12px;justify-items:start;padding:20px;border:1px solid var(--rim);border-radius:2px;"
              "background:var(--card);box-shadow:var(--lift);-webkit-backdrop-filter:blur(14px) saturate(1.15);backdrop-filter:blur(14px) saturate(1.15)}"
              ".mark{display:block;height:24px;width:auto;margin-bottom:4px}h1{margin:0;font-size:14px;font-weight:700;line-height:1.3}p{margin:0;color:var(--ink-2)}"
              "a{display:inline-flex;align-items:center;height:36px;box-sizing:border-box;padding:0 16px;border:1px solid var(--key-rim);border-radius:2px;"
              "background:var(--key);color:var(--key-ink);font-size:14px;font-weight:500;text-decoration:none}a:hover{background:var(--key-deep);border-color:var(--key-deep)}"
              "a:focus-visible{outline:2px solid var(--owl);outline-offset:2px}")  # the missing page's desk, glass card and key (web.py missing_page), held in the page: the busy server hands out no file
BUSY_SCRIPT = ('try{var t=localStorage.getItem("offerowl-theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}'
               'catch(e){}')  # the theme the person picked in the panel (theme.js keeps it in this browser); without it, the system's
BUSY_CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-"
            + base64.b64encode(hashlib.sha256(BUSY_SCRIPT.encode("utf-8")).digest()).decode("ascii")
            + "'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")  # its own style and that one script, nothing else at all
_LOGO_SVG = []  # the wordmark, read once ([] until then)


def logo_svg() -> str:
    """The wordmark drawn inline in the theme's colours, or "" when this copy has no docs (the page shows its words alone)."""
    if not _LOGO_SVG:  # read once
        try:
            svg = LOGO.read_text(encoding="utf-8")  # the light file; the dark one differs only in these colours
            for a, b in LOGO_INKS:  # each colour by the theme's variable
                svg = svg.replace(a, b)  # in the theme's colours
            svg = svg.replace("<svg ", '<svg class="mark" aria-hidden="true" ', 1).replace(' role="img"', "").replace(' aria-label="offerowl"', "")  # a picture beside the words, not a second name
        except OSError:  # no docs folder in this copy
            svg = ""  # the words alone
        _LOGO_SVG.append(svg)  # kept for every busy page
    return _LOGO_SVG[0]


def busy_page(lang: str, retry_after: int) -> str:
    """The page a person opening the panel gets while every slot is taken: the panel's desk, the missing page's glass card
    with the wordmark, one language (the browser's first of Korean and English, language), and a reload after exactly
    Retry-After seconds. It was plain system text in both languages that reloaded after 3 s against Retry-After 2 (D4-12).
    Everything is in the page itself: the busy server serves no other file."""
    head, line, key = BUSY_WORDS.get(lang, BUSY_WORDS["en"])  # the words
    return (f'<!doctype html><html lang="{lang if lang in BUSY_WORDS else "en"}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="refresh" content="{retry_after}"><title>Offerowl</title><style>{BUSY_STYLE}</style><script>{BUSY_SCRIPT}</script></head>'
            f'<body><main><section aria-labelledby="busy-h">{logo_svg()}<h1 id="busy-h">{head}</h1><p>{line.format(n=retry_after)}</p>'
            f'<a href="">{key}</a></section></main></body></html>')  # the key loads the same address now


def language(first: bytes) -> str:
    """The busy page's one language, by what came of the request: "ko" when its Accept-Language ranks Korean above English (by
    weight, the first named winning a tie), else "en". The panel's own choice is kept in the browser, which this answer
    never reads."""
    for h in first.split(b"\r\n")[1:]:  # the headers, as far as they came
        name, _, value = h.partition(b":")  # its name and value
        if name.strip().lower() != b"accept-language":  # another header
            continue  # not the one asked about
        best, best_q = "en", -1.0  # the language chosen and its weight
        for part in value.decode("latin-1").split(","):  # "ko-KR,ko;q=0.9,en-US;q=0.8"
            tag, _, params = part.strip().partition(";")  # the language, then its weight
            base = tag.strip().lower().split("-")[0]  # ko-KR is Korean
            q = 1.0  # no weight is 1
            for param in params.split(";"):  # ";q=0.9"
                k, _, v = param.strip().partition("=")  # q and its number
                if k.strip() == "q":  # its weight
                    try:
                        q = float(v)  # its weight
                    except ValueError:  # a weight that is no number: taken as written first
                        q = 1.0  # as if none were said
            if base in BUSY_WORDS and q > best_q:  # a language the page has, weighed above the one before
                best, best_q = base, q  # the best so far
        return best
    return "en"  # no Accept-Language came


def wants_page(first: bytes) -> bool:
    """Does what came of a request look like a browser opening a page: a GET that is not the API's and takes HTML?"""
    line, _, rest = first.partition(b"\r\n")  # the request line, then the headers
    parts = line.split(b" ")  # method, path, version
    if len(parts) < 2 or parts[0] != b"GET" or parts[1].startswith(b"/api/"):  # the API answers in JSON
        return False
    return any(h.lower().startswith(b"accept:") and b"text/html" in h.lower() for h in rest.split(b"\r\n"))  # a browser says so


def busy_answer(retry_after: int, page: bool = False, lang: str = "en") -> bytes:
    """The whole answer to a request no slot is free for: 503, when to try again, and a code the page reads (core.js). For a
    browser opening a page (`page`) the body is a page of its own in `lang` that reloads after retry_after seconds, never
    raw JSON (D3-11, D4-12)."""
    body = busy_page(lang, retry_after).encode("utf-8") if page else b'{"error": "busy"}'  # a page for a person, the code for the page's script
    kind = "text/html; charset=utf-8" if page else "application/json"
    extra = f"Content-Security-Policy: {BUSY_CSP}\r\nX-Content-Type-Options: nosniff\r\nCache-Control: no-store\r\n" if page else ""  # the page runs its one script and loads nothing
    head = (f"HTTP/1.1 503 Service Unavailable\r\nContent-Type: {kind}\r\nRetry-After: {retry_after}\r\n{extra}"
            f"Connection: close\r\nContent-Length: {len(body)}\r\n\r\n")
    return head.encode("ascii") + body


class Server(http.server.ThreadingHTTPServer):
    """A threaded HTTP server that holds its port alone. Built like http.server.ThreadingHTTPServer; refuses, with the system's
    "address in use" error, a port another server already listens on. It serves at most max_threads requests at once
    (OFFEROWL_MAX_REQUESTS, 64 by default): a client that opens connection after connection, or a burst more than the slots,
    makes the next ones wait slot_wait seconds for a free slot, each in a short thread of its own, and each is then answered
    503 with Retry-After in its own second, where a thread each for the whole request would grow without end. At most
    wait_cap connections wait at once; one past them is answered busy at once, on the accept loop. The panel's own page
    needs a handful at a time and tries again."""

    daemon_threads = True  # a stuck request never holds the exit
    # Connections the system holds for the accept loop. Python's own is 5: in a burst every connection past them was dropped
    # and asked for again by its client a second, then 3, 7 and 15 seconds later (measured: 300 at once took 27 s, the last
    # waiting in those retries, though the panel answers one in a few milliseconds). The system caps it (somaxconn).
    request_queue_size = 512
    max_threads = None  # requests served at once: None reads OFFEROWL_MAX_REQUESTS (cap_from_env)
    slot_wait = 1.0  # seconds a new connection waits for a free slot before it is answered "busy"
    retry_after = 2  # seconds the busy answer asks a client to wait before it tries again
    wait_cap = None  # connections that may wait for a slot at once: None is four times the slots

    def __init__(self, *args, **kwargs):
        self.cap = self.max_threads or cap_from_env()  # the slots, kept for the stop that waits for them (apps/panel/server.py)
        self._slots = threading.BoundedSemaphore(self.cap)  # one per request being served
        self._waiting = threading.BoundedSemaphore(self.wait_cap or 4 * self.cap)  # one per connection waiting for a slot
        super().__init__(*args, **kwargs)  # binds (and on Windows, holds) the port

    def process_request(self, request, client_address):
        """Start the request's thread when a slot is free. When none is, the connection waits for one in a short thread of
        its own, so the accept loop takes the next connection at once: the wait was on the accept loop, and twelve clients
        with every slot held were answered "busy" one a second, the last after nine (D4-03)."""
        if self._slots.acquire(blocking=False):  # a free slot: served now
            self._serve(request, client_address)  # in a thread of its own
            return
        if not self._waiting.acquire(blocking=False):  # as many waiting already as may: no thread more
            self.busy(request, read_wait=0)  # 503 at once, with what of the request has come
            return
        try:
            threading.Thread(target=self._wait_for_slot, args=(request, client_address), daemon=True, name="slot-wait").start()  # waits beside the loop
        except Exception:  # the thread did not start: answered here, its place among the waiting free again
            self._waiting.release()  # its place among the waiting
            self.busy(request, read_wait=0)  # answered here

    def _serve(self, request, client_address) -> None:
        """The request in a thread of its own, its slot taken already."""
        try:
            super().process_request(request, client_address)  # its own thread
        except Exception:  # the thread did not start: its slot is free again
            self._slots.release()
            raise

    def _wait_for_slot(self, request, client_address) -> None:
        """One connection's wait for a free slot, in its own short thread: served in this thread when one frees in time,
        else answered "busy" (503 with Retry-After) at the end of its own wait, whatever the others wait for."""
        try:
            got = self._slots.acquire(timeout=self.slot_wait)  # a slot, or the wait is over
        finally:
            self._waiting.release()  # no longer waiting
        if not got:  # every slot still busy
            self.busy(request)  # the client tries again in a moment
            return
        self.process_request_thread(request, client_address)  # served here; its slot goes back at the end

    def busy(self, request, read_wait: float = 0.2) -> None:
        """Answer a request no slot is free for, in a few milliseconds: what came of the request is read first (a close with it
        unread would reset the connection and lose the answer), then 503, then the close. read_wait 0 reads only what has come
        (the accept loop, which never waits on one client)."""
        try:
            request.settimeout(read_wait)  # a client that sends nothing does not hold the thread (0: not at all)
            first = b""  # what came of the request
            with contextlib.suppress(OSError):  # nothing came, or the client is gone
                first = request.recv(65536)  # the request line and headers, as far as they came
            request.settimeout(1)  # the answer is small: it fits the socket's buffer at once
            request.sendall(busy_answer(self.retry_after, wants_page(first), language(first)))  # 503, Retry-After, JSON for the API, a page for a browser
        except OSError:  # the client went away meanwhile: nothing to answer
            pass
        finally:
            self.shutdown_request(request)  # closed, as a handled request is

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)  # the request, answered and closed
        finally:
            self._slots.release()  # its slot, for the next one

    if sys.platform == "win32":  # where SO_REUSEADDR would share a port that is in use
        allow_reuse_address = False  # never set it

        def server_bind(self):
            """Bind with the port held alone (a second server's bind fails with WinError 10048)."""
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # no other socket may bind it while this one lives
            super().server_bind()  # then as usual


def port_words(port: int, exc: OSError) -> str:
    """Why a port could not be bound, in words for the command line: taken by another program (or a panel already running),
    or kept by the system (a port Windows reserves answers WinError 10013)."""
    import errno  # the codes, each system's own
    taken = exc.errno in (errno.EADDRINUSE, 10048)  # Linux and macOS, and Windows' own number
    if taken:
        return f"port {port} is in use: another program, or an Offerowl panel already running, holds it"
    return f"port {port} cannot be used on this PC ({exc.strerror or exc})"
