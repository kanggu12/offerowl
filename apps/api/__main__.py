"""Offerowl's API from a shell: serve it alone, or call one endpoint in this process.

    python3 -m apps.api serve [--port N] [--data DIR]           the API on 127.0.0.1 (no page)
    python3 -m apps.api get /api/v1/state [--data DIR]          one read, printed as JSON
    python3 -m apps.api post /api/v1/jobs '{"posting": "..."}'  one write (JSON body), printed as JSON with the tasks it started
    python3 -m apps.api add-file cv.pdf                         a file from disk as material, then read it

Tasks run in the process that starts them, so a write waits for the tasks it started before this command ends; a later
command could not see them.

The panel's server is the same API with the page beside it (apps/panel/server.py).
"""
from __future__ import annotations

import argparse  # the command line
import json  # bodies and answers
import sys  # paths and output
from pathlib import Path  # paths

if __package__ in (None, ""):  # started as a file: make the relative imports work
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repository root, which holds apps/
    __package__ = "apps.api"  # noqa: A001  the package this file belongs to
    __import__("apps.api")  # the package itself

from .client import Client  # noqa: E402  the API in this process


def utf8_stdio() -> None:
    """Print UTF-8 whatever the console's code page: Korean names, paths and messages go through a Windows console, a pipe or a
    file redirected in cp1252, where the system's default encoding would stop the command at the first Hangul letter."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # a text stream of this Python, not a test's replacement
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list | None = None) -> int:
    utf8_stdio()  # the answers hold Korean
    ap = argparse.ArgumentParser(prog="offerowl api", description="Offerowl's API: serve it, or call one endpoint.")  # named as a launcher would call it
    ap.add_argument("cmd", choices=("serve", "get", "post", "add-file"), help="serve the API, read, write, or add a file from disk")  # what to do
    ap.add_argument("arg", nargs="?", default="", help="get and post: the path (/api/v1/...); add-file: the file")  # the path or the file
    ap.add_argument("body", nargs="?", default="{}", help="post: the JSON body (default: {})")  # a write's JSON body
    ap.add_argument("--port", type=int, default=0, help="serve: the port on 127.0.0.1 (default: a free one)")  # serve only
    ap.add_argument("--data", type=Path, default=None, help="the data folder (default: the app's)")  # tests and other setups
    a = ap.parse_args(argv)  # the options
    c = Client(a.data)  # the API in this process
    if a.cmd == "serve":  # the API alone behind HTTP
        from .web import ApiHandler  # the safety rules
        from ownport import Server  # src/ownport.py: the port held alone, on Windows too
        try:
            srv = Server(("127.0.0.1", a.port), ApiHandler)  # this PC only
        except OSError as exc:  # in use, or kept by the system
            from ownport import port_words  # why, in words
            print(f"offerowl api: {port_words(a.port, exc)}. Serve it on another port: offerowl api serve --port <number>.", file=sys.stderr, flush=True)
            return 2  # the start failed
        ApiHandler.bind(c.router, srv.server_address[1])  # the table and the port
        c.api.port = srv.server_address[1]  # the command bar's agent reaches this API through it, never another one's port (apps/api/ask.py)
        print(f"http://127.0.0.1:{srv.server_address[1]}/api/v1/health", flush=True)  # where it answers
        try:
            srv.serve_forever()  # until Ctrl+C
        except KeyboardInterrupt:  # a normal stop
            pass  # no traceback
        return 0  # a clean exit
    try:
        if a.cmd == "get":  # one read
            out = c.get(a.arg)  # the answer
        elif a.cmd == "post":  # one write
            out = c.post(a.arg, json.loads(a.body))  # the answer, without the state
            ended = c.settle()  # the tasks it started run in this process: they end before it does
            if ended and isinstance(out, dict):  # said with the answer
                out = {**out, "tasks": ended}
        else:  # a file from disk
            rec = c.post("/api/v1/materials/file", {"path": a.arg})["material"]  # kept
            c.post("/api/v1/materials/read", {"ids": [rec["id"]]})  # read
            out = c.wait("ingest")  # until the reading ends
    except (RuntimeError, ValueError, OSError, TimeoutError) as exc:  # refused, unreadable, missing, hung
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)  # one line on stderr
        return 1  # a failure
    sys.stdout.write(out.decode("utf-8", "replace") if isinstance(out, bytes) else json.dumps(out, ensure_ascii=False, indent=1) + "\n")  # printed
    return 0  # done


if __name__ == "__main__":  # run as a module or a file
    raise SystemExit(main())  # main's answer is the exit code
