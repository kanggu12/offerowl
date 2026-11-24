"""The agent service's endpoints, as the gateway (apps/api/routes.py) gathers them: each path with its handler. A read
answers (status, answer, content type); a write answers the fields of its {"ok": true, ...}, or None (core/routing.py says
how a table is read)."""
from __future__ import annotations

from ...core.routing import JSON  # most answers
from . import ask, autopilot  # the command bar, the run from files to documents


# ------------------------------------------------------------------ reads


def get_agent(a, q, m):
    """GET /api/v1/agent: the agent card, read again now (?refresh=1 skips the cache)."""
    return 200, a.card.refresh(force=str(q.get("refresh", "0")) == "1"), JSON  # ?refresh=1 skips the cache


def get_ask(a, q, m):
    """GET /api/v1/ask: the command bar: what was asked and answered, and whether an ask runs now."""
    return 200, {"history": ask.history(a), "running": a.tasks.busy("ask")}, JSON


# ------------------------------------------------------------------ writes


def post_autopilot(a, req, path):
    """POST /api/v1/autopilot: files or folders in, finished documents out."""
    return autopilot.start(a, req)  # the run's key, the files it found and its estimate


def post_autopilot_stop(a, req, path):
    """POST /api/v1/autopilot/stop: the person stops a run; the step in progress finishes first."""
    t = a.tasks  # long tasks
    with t.state_lock:  # together with the chain's look at what waits
        t.autopilot_next = None  # a stop is for everything asked so far: what waited goes too
        t.autopilot_stop.set()
    return None  # the new state is the whole answer


def post_ask(a, req, path):
    """POST /api/v1/ask: the command bar: the person's words to the agent, which acts through Offerowl's own tools."""
    return {"started": ask.start(a, str(req.get("text") or ""))}  # False while an ask still runs


def post_ask_clear(a, req, path):
    """POST /api/v1/ask/clear: the command bar's history emptied."""
    return {"cleared": ask.clear(a)}  # how many asks went


def post_login(a, req, path):
    """POST /api/v1/agent/login: the agent card's sign-in button."""
    return {"started": a.card.start_login()}  # False when no CLI is on this PC


def post_refresh(a, req, path):
    """POST /api/v1/agent/refresh: the agent card's check-again."""
    a.card.refresh(force=True)  # the CLIs are asked now
    return None  # the new state is the whole answer


GET = (  # the reads
    ("/api/v1/agent", get_agent),
    ("/api/v1/ask", get_ask),
)
POST = (  # the writes
    ("/api/v1/autopilot", post_autopilot),
    ("/api/v1/autopilot/stop", post_autopilot_stop),
    ("/api/v1/ask", post_ask),
    ("/api/v1/ask/clear", post_ask_clear),
    ("/api/v1/agent/login", post_login),
    ("/api/v1/agent/refresh", post_refresh),
)
UPLOADS = ()  # no file comes to the agent as it is
