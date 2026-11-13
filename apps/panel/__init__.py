"""Offerowl's panel: the local web app a person uses without a terminal (docs/APP.md).

server.py serves the page (static/) beside Offerowl's one HTTP API (apps/api), which keeps the workspace, the facts,
the agent card and the tasks. The page never runs a command: every change goes through the API.
"""
