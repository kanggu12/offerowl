"""A page to test: either one already being served (--url) or a server started here on a free port.

The checks run in the real page with Playwright's Chromium, because the ranking and the card layout happen in the
browser. Playwright is optional: without it the browser commands say how to install it and stop.
"""
import contextlib  # the server's lifetime around a check
import threading  # the server runs beside the browser

from interview import i18n  # messages


def playwright_or_none():  # checked before any browser work
    """Playwright's async API, or None when it is not installed."""
    try:
        from playwright.async_api import async_playwright  # optional dependency
        return async_playwright  # the caller opens it with async with
    except ImportError:  # not installed: the caller prints how to get it
        return None  # None tells the caller to print the install hint


@contextlib.contextmanager  # so callers use with and the server always stops
def served(job, url=None, port=0):  # used by the cards and eval commands
    """Yield the page's URL: the given one, or a server for this job started on a free port and stopped afterwards."""
    if url:  # a page someone already serves
        yield url.rstrip("/") + "/"  # one trailing slash, so paths join the same way
        return  # nothing to stop: this code did not start it
    from interview import server  # the HTTP server
    srv, _ = server.make_server(job, port=port)  # port 0: a free one
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)  # beside the browser
    th.start()  # serve while the checks run
    try:
        u = f"http://127.0.0.1:{srv.server_address[1]}/"  # the page
        print(i18n.t("starting_server", url=u), flush=True)  # show which page the checks use
        yield u  # the checks run here
    finally:
        srv.shutdown()  # stop serving
        srv.server_close()  # free the port


def parse_size(s):  # for the --size options
    """'2560x1300' -> (2560, 1300)."""
    w, h = s.lower().split("x")  # width and height in CSS pixels
    return int(w), int(h)  # Playwright wants numbers
