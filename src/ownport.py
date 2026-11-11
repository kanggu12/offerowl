"""One server to a port, on every system Offerowl runs on.

Python's HTTP server turns on SO_REUSEADDR. On Linux and macOS that only lets a new server take a port its last run left
waiting; on Windows it lets a second server bind a port another one is listening on, and the two then share that port's
requests (measured with Python 3.14 on Windows: a second http.server binds the port of a running one). So on Windows the
port is taken with SO_EXCLUSIVEADDRUSE instead, and a second start is refused there as it is everywhere else. The panel,
the API served alone, the interview kit's view and the agent's stand-in all bind through this class.
"""
from __future__ import annotations

import http.server  # the threaded server the rest of Offerowl serves with
import socket  # the socket option
import sys  # which system this is
import threading  # the requests served at once, counted


class Server(http.server.ThreadingHTTPServer):
    """A threaded HTTP server that holds its port alone. Built like http.server.ThreadingHTTPServer; refuses, with the system's
    "address in use" error, a port another server already listens on. It serves at most max_threads requests at once: a
    program on this PC that opens connection after connection makes the next ones wait (and, past slot_wait seconds, closes
    them), where a thread each would grow without end. The panel's own page needs a handful at a time."""

    daemon_threads = True  # a stuck request never holds the exit
    max_threads = 64  # requests served at once
    slot_wait = 10  # seconds a new connection waits for a free one before it is closed

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(self.max_threads)  # one per request being served
        super().__init__(*args, **kwargs)  # binds (and on Windows, holds) the port

    def process_request(self, request, client_address):
        """Start the request's thread when a slot is free; close the connection when none frees in time (the accept loop
        stays free to stop)."""
        if not self._slots.acquire(timeout=self.slot_wait):  # every slot busy for too long
            self.shutdown_request(request)  # closed unanswered: the client may try again
            return
        try:
            super().process_request(request, client_address)  # its own thread
        except Exception:  # the thread did not start: its slot is free again
            self._slots.release()
            raise

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
