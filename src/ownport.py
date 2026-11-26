"""One server to a port, on every system Offerowl runs on.

Python's HTTP server turns on SO_REUSEADDR. On Linux and macOS that only lets a new server take a port its last run left
waiting; on Windows it lets a second server bind a port another one is listening on, and the two then share that port's
requests (measured with Python 3.14 on Windows: a second http.server binds the port of a running one). So on Windows the
port is taken with SO_EXCLUSIVEADDRUSE instead, and a second start is refused there as it is everywhere else. The panel,
the API served alone, the interview kit's view and the agent's stand-in all bind through this class.
"""
from __future__ import annotations

import contextlib  # a read that may fail
import http.server  # the threaded server the rest of Offerowl serves with
import os  # the cap, from the environment
import socket  # the socket option
import sys  # which system this is
import threading  # the requests served at once, counted

MAX_REQUESTS = 64  # requests a server serves at once, unless OFFEROWL_MAX_REQUESTS says otherwise


def cap_from_env() -> int:
    """OFFEROWL_MAX_REQUESTS, the requests a server serves at once (4 to 1024); anything else keeps MAX_REQUESTS."""
    try:  # a word or an empty value is no number
        n = int(os.environ.get("OFFEROWL_MAX_REQUESTS") or MAX_REQUESTS)
    except ValueError:
        return MAX_REQUESTS
    return n if 4 <= n <= 1024 else MAX_REQUESTS  # too few would refuse the page's own requests; too many is no cap


BUSY_PAGE = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
             "<meta http-equiv=\"refresh\" content=\"3\"><title>Offerowl</title><style>"
             "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f1ea;color:#23211d;font:16px/1.6 system-ui,sans-serif}"
             "@media(prefers-color-scheme:dark){body{background:#141414;color:#ececec}}"
             "main{padding:24px 16px;max-width:30em}h1{margin:0 0 8px;font-size:20px}p{margin:4px 0}</style></head><body><main>"
             "<h1>Offerowl is answering many requests at once.</h1><p>The page loads again in a moment.</p>"
             "<p lang=\"ko\">Offerowl이 요청을 많이 받고 있습니다. 잠시 뒤 다시 불러옵니다.</p></main></body></html>")  # a person's page: both languages, it reloads itself (the server does not know the person's language)


def wants_page(first: bytes) -> bool:
    """Does what came of a request look like a browser opening a page: a GET that is not the API's and takes HTML?"""
    line, _, rest = first.partition(b"\r\n")  # the request line, then the headers
    parts = line.split(b" ")  # method, path, version
    if len(parts) < 2 or parts[0] != b"GET" or parts[1].startswith(b"/api/"):  # the API answers in JSON
        return False
    return any(h.lower().startswith(b"accept:") and b"text/html" in h.lower() for h in rest.split(b"\r\n"))  # a browser says so


def busy_answer(retry_after: int, page: bool = False) -> bytes:
    """The whole answer to a request no slot is free for: 503, when to try again, and a code the page reads (core.js). For a
    browser opening a page (`page`) the body is a small page of its own that reloads, never raw JSON (D3-11)."""
    body = BUSY_PAGE.encode("utf-8") if page else b'{"error": "busy"}'  # a page for a person, the code for the page's script
    kind = "text/html; charset=utf-8" if page else "application/json"
    head = (f"HTTP/1.1 503 Service Unavailable\r\nContent-Type: {kind}\r\nRetry-After: {retry_after}\r\n"
            f"Connection: close\r\nContent-Length: {len(body)}\r\n\r\n")
    return head.encode("ascii") + body


class Server(http.server.ThreadingHTTPServer):
    """A threaded HTTP server that holds its port alone. Built like http.server.ThreadingHTTPServer; refuses, with the system's
    "address in use" error, a port another server already listens on. It serves at most max_threads requests at once
    (OFFEROWL_MAX_REQUESTS, 64 by default): a client that opens connection after connection, or a burst more than the slots,
    makes the next ones wait slot_wait seconds for a free slot, and is then answered 503 with Retry-After at once, without a
    thread, where a thread each would grow without end. The panel's own page needs a handful at a time and tries again."""

    daemon_threads = True  # a stuck request never holds the exit
    # Connections the system holds for the accept loop. Python's own is 5: in a burst every connection past them was dropped
    # and asked for again by its client a second, then 3, 7 and 15 seconds later (measured: 300 at once took 27 s, the last
    # waiting in those retries, though the panel answers one in a few milliseconds). The system caps it (somaxconn).
    request_queue_size = 512
    max_threads = None  # requests served at once: None reads OFFEROWL_MAX_REQUESTS (cap_from_env)
    slot_wait = 1.0  # seconds a new connection waits for a free slot before it is answered "busy"
    retry_after = 2  # seconds the busy answer asks a client to wait before it tries again

    def __init__(self, *args, **kwargs):
        self.cap = self.max_threads or cap_from_env()  # the slots, kept for the stop that waits for them (apps/panel/server.py)
        self._slots = threading.BoundedSemaphore(self.cap)  # one per request being served
        super().__init__(*args, **kwargs)  # binds (and on Windows, holds) the port

    def process_request(self, request, client_address):
        """Start the request's thread when a slot is free; answer "busy" when none frees in time (the accept loop stays free
        to stop, and to answer the next)."""
        if not self._slots.acquire(timeout=self.slot_wait):  # every slot busy for too long
            self.busy(request)  # 503 with Retry-After: the client tries again in a moment
            return
        try:
            super().process_request(request, client_address)  # its own thread
        except Exception:  # the thread did not start: its slot is free again
            self._slots.release()
            raise

    def busy(self, request) -> None:
        """Answer a request no slot is free for, on the accepting thread, in a few milliseconds: what came of the request is
        read first (a close with it unread would reset the connection and lose the answer), then 503, then the close."""
        try:
            request.settimeout(0.2)  # a client that sends nothing does not hold the accept loop
            first = b""  # what came of the request
            with contextlib.suppress(OSError):  # nothing came, or the client is gone
                first = request.recv(65536)  # the request line and headers, as far as they came
            request.settimeout(1)  # the answer is small: it fits the socket's buffer at once
            request.sendall(busy_answer(self.retry_after, wants_page(first)))  # 503, Retry-After, JSON for the API, a page for a browser
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
