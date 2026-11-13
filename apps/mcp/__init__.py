"""Offerowl for AI agents: a Model Context Protocol server on stdio that drives a running panel through its HTTP API.

    ./offerowl mcp [--url http://127.0.0.1:8797] [--read-only]

The tools are a thin, typed layer over /api/v1 (apps/api/routes.py): the panel stays the one process that keeps the
workspace and runs the tasks, and this server only asks it. docs/MCP.md lists the tools.
"""
