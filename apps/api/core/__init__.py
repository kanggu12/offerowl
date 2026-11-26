"""The storage and the shared kernel every service of apps/api/services stands on. It knows no service: a service imports
the core, never the other way round (tests/app/test_architecture.py keeps it so).

    workspace.py   the workspace folder: its paths, JSON written whole through a rename, the one writer lock, the undo
                   steps, the job and source records with the Trash's marks on them, and the moves Windows makes wait
    stamps.py      a file's version without reading it, and the short hashes of files the panel's every poll asks for
    routing.py     what every service's table and the gateway share: the answers' shapes, a route's matcher, an upload's
                   route, the request's language, a request's text field (a string or refused)
"""
