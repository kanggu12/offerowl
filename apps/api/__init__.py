"""Offerowl's one HTTP API: the panel uses it, the command line can wrap it, and the panel never shells out.

    app.py       the API object: settings, workspace, facts, the agent card, tasks, and every action
    routes.py    every endpoint in one table, without HTTP (docs/ARCHITECTURE.md lists them)
    web.py       the table behind HTTP with the safety rules (Host, Origin, body types)
    client.py    the same table called in this process, for the command line and scripts
    documents.py the canvas's documents; evidence.py the resume model with each sentence's evidence
    fit.py       how a profile fits a posting; tracker.py the board, timeline and reminders
    studio.py    the interview studio's board; postings.py a posting from a link
    materials.py a job's own materials (decks, notes, briefs, answers, code): kept as they came, previewed, handed back
    workspace.py, facts.py, tasks.py, agent.py, standin.py: files and undo, facts, long tasks, the agent, its stand-in
    task_own.py, task_kit.py, task_export.py, task_answers.py: the long tasks' parts by area (Tasks inherits them)
    stamps.py    a file's version and its hash, worked out once while it is unchanged; delivery.py where the export goes
"""
import sys  # the import path
from pathlib import Path  # paths

_ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
for _p in (str(_ROOT), str(_ROOT / "src")):  # core/schema and the engine's flat modules
    if _p not in sys.path:  # once
        sys.path.insert(0, _p)  # found from anywhere
