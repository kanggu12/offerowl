"""Offerowl's one HTTP API: the panel uses it, the command line can wrap it, and the panel never shells out. One process,
one folder of files, split into services that each own their files and their endpoints (docs/ARCHITECTURE.md "The
services"):

    core/        the storage and the shared kernel: the workspace (paths, JSON written whole, the writer lock, undo, the
                 job and source records), the files' stamps, and what every route table shares
    services/    profile, applications, documents, interview, agent, library and insights: each with its modules, its
                 own routes.py and an __init__ that says what it owns and offers
    app.py       the composition root: builds the core and what the services keep for the panel's life, keeps the
                 settings and composes the state; no domain work of its own
    tasks.py     the task runner (threads, task records, the model lock), composed of the services' task parts
    routes.py    the gateway: gathers every service's table, without HTTP (docs/ARCHITECTURE.md lists the endpoints)
    web.py       the table behind HTTP with the safety rules (Host, Origin, body types)
    client.py    the same table called in this process, for the command line and scripts
"""
import sys  # the import path
from pathlib import Path  # paths

_ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
for _p in (str(_ROOT), str(_ROOT / "src")):  # core/schema and the engine's flat modules
    if _p not in sys.path:  # once
        sys.path.insert(0, _p)  # found from anywhere
