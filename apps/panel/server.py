#!/usr/bin/env python3
"""Offerowl's panel: the page, served beside Offerowl's one HTTP API (apps/api), for people who never open a terminal.

    python3 apps/panel/server.py                      http://127.0.0.1:8797 with the workspace in the data folder
    python3 apps/panel/server.py --workspace DIR      another workspace folder 
    ./offerowl panel                                  the same through the launcher

The page (static/) draws the workspace: navigation on the left, the document on a canvas in the middle, the inspector
on the right. Every piece of work goes through the API's routes (apps/api/routes.py), the same table the command line
can call; the page itself never runs a command. Only the standard library is used.

Safety (apps/api/web.py): the server listens on 127.0.0.1 only; it answers only requests whose Host names this PC and
its port (no DNS rebinding); writes need a JSON body (or a file upload, which needs a header of its own) and an Origin
of this page, so another site's page cannot write here.
"""
from __future__ import annotations  # hints like `Path | None` also load on older Pythons

import argparse  # the command line
import http.server  # the server
import logging  # the panel's log
import logging.handlers  # a capped log file
import mimetypes  # content types of the page's files
import os  # environment
import re  # routes and names
import sys  # paths
from pathlib import Path  # paths

if __package__ in (None, ""):  # started as a file (python3 apps/panel/server.py): make the relative imports work
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repository root, which holds apps/
    __package__ = "apps.panel"  # noqa: A001  the package this file belongs to
    __import__("apps.panel")  # the package itself, so its modules can be found

from apps.api.app import Api, data_dir  # noqa: E402  the API object and the data folder rule
from apps.api.facts import FACT_FILES  # noqa: E402,F401  src/ui/server.py reads it from here
from apps.api.routes import Router  # noqa: E402  the API's table
from apps.api.web import ApiHandler  # noqa: E402  the table behind HTTP

ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
STATIC = Path(__file__).resolve().parent / "static"  # the page
PORT = 8797  # the panel's port (docs/APP.md)
log = logging.getLogger("offerowl.panel")  # the panel's log


class Handler(ApiHandler):
    """The API's routes plus the page, its files, the fonts, the wordmark and the documents' pictures."""

    panel: Api = None  # set by serve(): the API object (src/ui/server.py reads its facts and workspace)

    def extra_get(self, path: str) -> bool:
        """The page's own GET paths. True when answered."""
        if path in ("/", "/index.html"):  # the page itself
            self.send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")  # never cached
            return True  # answered
        m = re.fullmatch(r"/static/([\w.\-]+(?:/[\w.\-]+)?)", path)  # the page's files
        if m and ".." not in m.group(1) and (STATIC / m.group(1)).is_file():  # never a file outside static/
            ctype = mimetypes.guess_type(m.group(1))[0] or "application/octet-stream"  # by the file's extension
            ctype += "; charset=utf-8" if ctype.startswith(("text/", "application/javascript")) else ""  # Korean text decodes right
            self.send(200, (STATIC / m.group(1)).read_bytes(), ctype)  # not cached: page and scripts stay in step
            return True  # answered
        m = re.fullmatch(r"/fonts/(Pretendard-(?:Regular|SemiBold|Bold)\.ttf)", path)  # the repository's own fonts
        if m and (ROOT / "fonts" / m.group(1)).is_file():  # a copy without the fonts answers 404
            self.send(200, (ROOT / "fonts" / m.group(1)).read_bytes(), "font/ttf", cache=True)  # fonts never change
            return True  # answered
        m = re.fullmatch(r"/fonts/(PretendardVariable\.woff2|JetBrainsMono\.woff2)", path)  # the interview kit's web fonts, smaller than the TTFs
        if m and (ROOT / "src" / "interview" / "fonts" / m.group(1)).is_file():  # present with the interview kit
            self.send(200, (ROOT / "src" / "interview" / "fonts" / m.group(1)).read_bytes(), "font/woff2", cache=True)  # fonts never change
            return True  # answered
        m = re.fullmatch(r"/brand/(icon|logo-light|logo-dark)\.svg", path)  # the wordmark and the icon
        if m and (ROOT / "docs" / "assets" / f"{m.group(1)}.svg").is_file():  # a copy without docs answers 404
            self.send(200, (ROOT / "docs" / "assets" / f"{m.group(1)}.svg").read_bytes(), "image/svg+xml")  # not kept by the browser: a new version's logo shows at once
            return True  # answered
        m = re.fullmatch(r"/doc/([0-9A-Za-z가-힣%-]+)/(ko|en)/(preview/[rdc]-\d+\.png|resume\.pdf|deck\.pdf|cover\.pdf)", path)  # the earlier file paths
        if m:  # the same files the API serves under /api/v1/jobs/<job>/files/
            code, body, ctype = self.router.handle("GET", f"/api/v1/jobs/{m.group(1)}/files/{m.group(2)}/{m.group(3)}")  # through the API's checks
            self.send(code, body, ctype)  # sent
            return True  # answered
        return False  # not a page path


def setup_log(data: Path) -> None:
    """The panel's log in the data folder, capped at 2 MB with one older file."""
    (data / "logs").mkdir(parents=True, exist_ok=True)  # the first start has no logs folder
    root = logging.getLogger("offerowl")  # this program's loggers only
    for old in [x for x in root.handlers if getattr(x, "offerowl_panel", False)]:  # a server started before in this process
        root.removeHandler(old)  # its file stops getting the new server's lines
        old.close()  # and is released
    # rotated at 2 MB, so the log can never fill the disk
    h = logging.handlers.RotatingFileHandler(data / "logs" / "panel.log", maxBytes=2_000_000, backupCount=1, encoding="utf-8")
    h.offerowl_panel = True  # marks the handler this function owns
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))  # a time and a level on every line
    root.addHandler(h)  # the panel's and the tasks' lines go to the file
    root.setLevel(logging.INFO)  # info and above, no debug noise


class PortTaken(OSError):
    """The panel's port could not be bound: in use by another program or panel, or kept by the system."""

    def __init__(self, port: int, exc: OSError):
        from ownport import port_words  # src/ownport.py: why, in words
        super().__init__(exc.errno, port_words(port, exc))  # the system's code, and the words main() prints


def serve(port: int = PORT, host: str = "127.0.0.1", data: Path | None = None, workspace: Path | None = None,
          ready=None) -> http.server.ThreadingHTTPServer:
    """Make the server (not started). `ready`, when given, is called with the server once it is bound."""
    from ownport import Server  # src/ownport.py: the port held alone, on Windows too
    data = Path(data or data_dir())  # the data folder
    setup_log(data)  # the log
    try:
        srv = Server((host, port), Handler)  # bound first (port 0 picks a free one): a port that is taken stops the start before anything else runs
    except OSError as exc:  # in use, or kept by the system
        raise PortTaken(port, exc) from exc  # main() says so in words
    try:
        api = Api(data, workspace)  # the state
    except BaseException:  # a workspace that cannot be opened: the port is let go
        srv.server_close()
        raise
    real = srv.server_address[1]  # the port it got
    api.port = real  # the command bar's agent reaches this panel through it (apps/api/ask.py)
    Handler.bind(Router(api), real)  # the API's table, this PC's names and the page's origins
    Handler.panel = api  # every request thread shares this one API object
    srv.daemon_threads = True  # a stuck request never holds the exit
    log.info("panel on http://127.0.0.1:%s, workspace %s", real, api.ws.root)  # where it runs, for the log
    if ready:  # the caller wants the bound server before serving starts
        ready(srv)  # it learns the port
    return srv  # the caller runs serve_forever()


def main(argv: list | None = None) -> int:  # the command line; argv lets a caller pass its own
    for stream in (sys.stdout, sys.stderr):  # what the engine's steps print holds Korean names and paths: UTF-8 whatever the console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="offerowl panel", description="Open Offerowl's local web panel.")  # named as the launcher calls it
    # the environment may set the port too, for a launcher or a container
    ap.add_argument("--port", type=int, default=int(os.environ.get("OFFEROWL_PANEL_PORT") or PORT), help=f"port on 127.0.0.1 (default {PORT})")
    ap.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)  # 0.0.0.0 only inside a container
    ap.add_argument("--workspace", type=Path, default=None, help="the workspace folder (default: the data folder's)")  # over the saved one
    ap.add_argument("--data", type=Path, default=None, help=argparse.SUPPRESS)  # tests
    ap.add_argument("--open", action="store_true", help="open the panel in the browser")  # no address to copy by hand
    a = ap.parse_args(argv)  # None reads the real command line
    # the agent's call log (the figures on its card) goes with the data, which is always writable and stays across starts,
    # not into the engine's folder, which a package install may keep read-only and the one-file app unpacks anew each start
    os.environ.setdefault("OFFEROWL_LLM_LOG", str(Path(a.data or data_dir()) / "logs" / "calls.jsonl"))
    if "llm" in sys.modules:  # already read the setting when it was imported
        sys.modules["llm"].LOG = Path(os.environ["OFFEROWL_LLM_LOG"])
    try:
        srv = serve(a.port, a.host, a.data, a.workspace)  # bound
    except PortTaken as exc:  # said in words, not as a traceback
        print(f"offerowl panel: {exc.strerror}. `offerowl open` shows a panel that is running; `offerowl panel --port <number>` starts one on another port.",
              file=sys.stderr, flush=True)
        return 2  # the start failed
    url = f"http://127.0.0.1:{srv.server_address[1]}/"  # its address
    print(url, flush=True)  # for whoever started it
    if a.open:  # --open was given
        import threading  # the browser is asked once the server below is serving
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # the engine's flat modules
        from open_page import open_page  # never a terminal browser, which waited here before the server served (w3m under WSL)
        later = threading.Timer(0.3, open_page, args=(url,))  # a moment after serve_forever starts
        later.daemon = True  # never holds up the exit
        later.start()  # the page opens in the browser, or the printed address is the way in
    try:  # Ctrl+C ends it quietly
        srv.serve_forever()  # until stopped
    except KeyboardInterrupt:  # Ctrl+C in the terminal
        pass  # a normal stop, no traceback
    return 0  # a clean exit


if __name__ == "__main__":  # run as a script, not imported
    raise SystemExit(main())  # main's answer is the exit code
