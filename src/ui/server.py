#!/usr/bin/env python3
"""The fact review screen, folded into the panel: it is the profile view of apps/panel, with the same merge
rules (src/review.py). This entry point stays for the command-line flow of docs/USAGE.md, where `offerowl ingest` writes
output/_ingest/candidates.json and this screen confirms them.

  python3 src/ui/server.py                 the panel on 127.0.0.1:8798 (OFFEROWL_UI_PORT changes the port)

The workspace is the panel's own data folder. Candidates the command line found are added to it each time this starts
(each fact once: the same fact keeps its id), and their file names are shown without their folders.
"""
import json  # the command line's candidates
import os  # the port setting
import pathlib  # paths
import sys  # the import path

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
from apps.panel import server  # noqa: E402  the panel

CLI_CANDS = ROOT / "output" / "_ingest" / "candidates.json"  # what `offerowl ingest` writes


def import_cli_candidates(panel) -> int:
    """Add the command line's candidates to the panel's facts. Returns how many were new."""
    if not CLI_CANDS.is_file():  # no command-line run yet
        return 0  # nothing from the command line
    data = json.loads(CLI_CANDS.read_text(encoding="utf-8"))  # {"kept": [...], "dropped": [...]}
    name_of = lambda f: ("", pathlib.Path(f).name)  # no material record: only the file's name is shown
    new = panel.facts.ingest_candidates(data.get("kept") or [], name_of)  # as panel facts
    with panel.ws.change({"code": "undo_add_material", "n": 1}, server.FACT_FILES):  # one undo takes them back
        n = panel.facts.add_candidates(new)  # only the new ones
        panel.facts.rebuild()  # the profile follows the new facts
    return n  # how many were new


def main() -> int:
    port = int(os.environ.get("OFFEROWL_UI_PORT") or 8798)  # the fact review screen's port (docs/APP.md)
    srv = server.serve(port, "127.0.0.1", None)  # this PC only, on the panel's own data folder
    added = import_cli_candidates(server.Handler.panel)  # the command line's facts
    server.Handler.panel.ws.set_prefs(open=2)  # the page opens on "Confirm facts"
    print(f"http://127.0.0.1:{srv.server_address[1]}/  (facts from the command line: {added} new)", flush=True)  # the port it got
    try:
        srv.serve_forever()  # until stopped
    except KeyboardInterrupt:  # Ctrl+C
        pass  # a quiet stop
    return 0  # a normal stop is a success


if __name__ == "__main__":  # run as a program
    raise SystemExit(main())  # its exit code
