"""`./offerowl mcp` and `python3 -m apps.mcp`: the MCP server on stdio (apps/mcp/server.py).

    ./offerowl mcp                                  the panel on 127.0.0.1:8797 (or OFFEROWL_PANEL_PORT)
    ./offerowl mcp --url http://127.0.0.1:9000      a panel elsewhere on this PC
    ./offerowl mcp --read-only                      the reading tools only

An agent starts it (`claude mcp add offerowl -- ./offerowl mcp`); a person never types into it. stdout carries the
protocol only, so every word for a person goes to stderr.
"""
from __future__ import annotations

import argparse  # the options
import json  # the links the command bar allows
import os  # where they come
import sys  # stdio and paths
from pathlib import Path  # paths

if __package__ in (None, ""):  # started as a file: make the relative imports work
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repository root, which holds apps/
    __package__ = "apps.mcp"  # noqa: A001  the package this file belongs to
    __import__("apps.mcp")  # the package itself

from .server import Panel, Server, default_url  # noqa: E402  the protocol and the panel's client


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="offerowl mcp", description="Offerowl's tools for AI agents: an MCP server on stdio that drives a running panel.")  # named as the launcher calls it
    ap.add_argument("--url", default=default_url(), help="the panel's address on this PC (default: http://127.0.0.1:8797, or OFFEROWL_PANEL_PORT, or OFFEROWL_MCP_URL)")  # where the API answers
    ap.add_argument("--read-only", action="store_true", help="offer only the tools that read; nothing is written or started")  # for an agent that should only look
    a = ap.parse_args(argv)  # exits with a usage line on a bad option
    try:
        panel = Panel(a.url)  # checked: this PC only
    except ValueError as exc:  # another host, or not http
        print(f"offerowl mcp: {exc}", file=sys.stderr)  # stderr: stdout is the protocol's
        return 2  # a usage error
    for stream in (sys.stdin, sys.stdout):  # JSON-RPC is UTF-8 whatever the console's code page (Windows: cp1252)
        if hasattr(stream, "reconfigure"):  # a text stream of this Python, not a test's replacement
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")  # one message per "\n", never "\r\n"
    links = os.environ.get("OFFEROWL_MCP_LINKS")  # set by the panel's command bar: the links in the person's own words
    try:
        allowed = None if links is None else [str(u) for u in json.loads(links)]  # None: any link (the person's own agent)
    except ValueError:  # a broken list allows nothing rather than anything
        allowed = []
    Server(panel, read_only=a.read_only, links=allowed).serve(sys.stdin, sys.stdout)  # until the client closes stdin
    return 0  # a clean end


if __name__ == "__main__":  # run as a module or a file
    raise SystemExit(main())  # main's answer is the exit code
