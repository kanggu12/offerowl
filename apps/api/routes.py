"""The gateway: every endpoint of Offerowl's API, with no HTTP in it. handle(method, path, query, body) returns (status,
answer, content type). The panel's server and `python3 -m apps.api` put it behind HTTP with the safety rules of web.py;
the command line can call it in this process (client.py). docs/ARCHITECTURE.md lists the same table in words.

The endpoints are the services' own: each service's routes.py holds its table (apps/api/services/<service>/routes.py),
and the gateway gathers them, after its own few for what the API object itself keeps (the health check, the state, the
settings, undo and the history, the schemas). It routes and frames the answers; it does no work of its own. No two
routes of all the tables match one path (tests/app/test_architecture.py checks it), so the order they are gathered in
never decides an answer.

Writes answer {"ok": true, ...} with the whole new state under "state" (the panel redraws from it), unless the query
has state=0. Errors answer {"error": code, "what": detail}: 400 for a refused request, 404 for an unknown path or
file, 500 for a bug (logged, never shown).
"""
from __future__ import annotations

import logging  # bugs go to the log
import re  # the schemas' path

from .core.routing import JSON, NotFound, matches  # the answers' shapes, and how a route's matcher is read
from .core.workspace import HISTORY_MAX  # the undo steps a workspace keeps: the most one request can take back
from .services import agent, applications, documents, insights, interview, library, profile  # the services, each with its table

log = logging.getLogger("offerowl.api")  # the API's log


# ------------------------------------------------------------------ the API object's own endpoints


def get_health(a, q, m):
    """GET /api/v1/health (also /health): liveness; "app" tells Offerowl from another server on the port."""
    return 200, {"ok": True, "app": "offerowl", "api": 1}, JSON  # the desktop app's check reads it


def get_state(a, q, m):
    """GET /api/v1/state: everything the panel draws (a poll: polls that come together share one state)."""
    return 200, a.state_for_poll(), JSON  # fresh, or the one being made when this poll came (nothing written since it began)


def get_history(a, q, m):
    """GET /api/v1/history: the undo steps."""
    return 200, {"steps": a.ws.history()}, JSON


def get_schema(a, q, m):
    """GET /api/v1/schema/<name>: the data model, for tools."""
    from core.schema import validate  # the names
    if m.group(1) not in validate.NAMES:  # unknown name
        raise NotFound(m.group(0))  # 404
    return 200, validate.load(validate.NAMES[m.group(1)])[0], JSON  # the schema itself


def post_undo(a, req, path):
    """POST /api/v1/undo: the undo button; {"only": id} from a toast takes back that step only."""
    t = a.tasks  # long tasks
    with a.ws.lock:  # the newest step is looked at and taken back in one go
        if req.get("only") is not None and str(req["only"]) != a.ws.newest()[0]:  # another change came after it (or it was undone)
            return {"undone": None, "moved": True}  # nothing is taken back: the page says the change is in the history
        label = a.ws.undo()  # the files back
        if label is not None and not t.busy("ingest"):  # a reading's step put back the list as it was while those files were read
            t.unstick()  # so none stays "reading" with no reading running (under the lock: a reading starting now marks its files after this)
    if label is not None:  # something was undone
        a.facts.rebuild()  # the profile follows the restored facts
    return {"undone": label}  # the page says what came back


def post_history_undo(a, req, path):
    """POST /api/v1/history/undo: back to an earlier point of the history."""
    t = a.tasks  # long tasks
    n = req.get("steps")  # how many changes to take back: said, never guessed
    n = int(n) if isinstance(n, str) and n.isdigit() else n  # "2", as a command line may write it
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= HISTORY_MAX:  # none, 0, a negative, a word or more than the history keeps:
        raise ValueError("steps")  # refused before anything is undone (0 or none used to undo the newest change, A3-20)
    done = []  # the labels taken back
    with a.ws.lock:  # the newest step is compared and the steps taken back in one go
        if req.get("newest") is not None and str(req["newest"]) != a.ws.newest()[0]:  # a change came after the list the page drew
            return {"undone": [], "moved": True}  # nothing is taken back: n would now count that newer change too
        for _ in range(n):  # one step at a time
            label = a.ws.undo()  # the newest step
            if label is None:  # nothing left
                break  # stop
            done.append(label)  # remembered
        if done and not t.busy("ingest"):  # as for one undo: no file stays "reading" with no reading running
            t.unstick()
    if done:  # the profile follows
        a.facts.rebuild()  # once
    return {"undone": done}  # what came back


def post_settings(a, req, path):
    """POST /api/v1/settings: the settings menu."""
    a.set_settings(req)  # each value checked
    return None  # the new state is the whole answer


OWN_GET = (  # the API object's own reads
    (("/api/v1/health", "/health"), get_health),
    ("/api/v1/state", get_state),
    ("/api/v1/history", get_history),
    (re.compile(r"/api/v1/schema/([a-z]+)").fullmatch, get_schema),
)
OWN_POST = (  # and writes
    ("/api/v1/undo", post_undo),
    ("/api/v1/history/undo", post_history_undo),
    ("/api/v1/settings", post_settings),
)

SERVICES = (profile, applications, documents, interview, agent, library, insights)  # every service, each with its own table
GET = OWN_GET + tuple(r for s in SERVICES for r in s.GET_ROUTES)  # every read: (matcher, handler)
POST = OWN_POST + tuple(r for s in SERVICES for r in s.POST_ROUTES)  # every write
UPLOADS = {u.path: u for s in SERVICES for u in s.UPLOAD_ROUTES}  # every file upload, by its path (web.py reads its body)


class Router:
    """The API's table. One per running API."""

    def __init__(self, api):
        self.api = api  # the state and the actions

    def handle(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> tuple[int, object, str]:
        """One request. `query` maps names to values (the first of each), `body` is a write's JSON object."""
        query = query or {}  # no query
        try:
            if method == "GET":  # reads
                return self.get(path, query)  # status, answer, type
            if method == "POST":  # writes
                self.api.ws.forget_mine()  # this request's own undo step, if it makes one, is named in its answer
                out = self.post(path, body or {})  # the action
                if out is not None and not isinstance(out, dict):  # a raw answer (never for writes today)
                    return 200, out, JSON  # as it is
                answer = {"ok": True, **(out or {})}  # the action's own fields
                if self.api.ws.mine() and "step" not in answer:  # the undo step this write made: {"only": step} takes back that one alone
                    answer["step"] = self.api.ws.mine()
                self.api.state_dirty()  # a write: the next state is made anew
                if str(query.get("state", "1")) != "0":  # the panel redraws from the state
                    answer["state"] = self.api.state()  # the whole new state
                return 200, answer, JSON  # done
            return 405, {"error": "method"}, JSON  # only GET and POST
        except NotFound:  # no such path or file
            return 404, {"error": "not_found"}, JSON  # an unknown path
        except PermissionError as exc:  # refused by a rule (a locked job), or the system refusing a file
            if exc.errno is not None:  # the system's own refusal (a folder that cannot be written): its words hold the path
                log.exception("%s %s", method, path)  # the path goes to the log, never to the page
                return 500, {"error": "unexpected"}, JSON  # the page shows a general error
            return 403, {"error": str(exc)}, JSON  # names the rule
        except ValueError as exc:  # an action refused the request
            return 400, {"error": "bad_request", "what": str(exc)}, JSON  # "what" names the check
        except Exception:  # a bug: logged, answered
            log.exception("%s %s", method, path)  # the traceback goes to the log, not the page
            return 500, {"error": "unexpected"}, JSON  # the page shows a general error

    def get(self, path: str, q: dict) -> tuple[int, object, str]:
        """The read routes: the first that matches answers."""
        for matcher, handler in GET:  # the API object's own, then each service's
            m = matches(matcher, path)  # True for an exact path, a pattern's match, or None
            if m:
                return handler(self.api, q, m)  # status, answer, type
        raise NotFound(path)  # no route matched

    def post(self, path: str, req: dict) -> dict | None:
        """The JSON writes. Each returns extra fields for the answer, or None."""
        for matcher, handler in POST:  # the API object's own, then each service's
            if matches(matcher, path):
                return handler(self.api, req, path)  # the action's own fields
        raise NotFound(path)  # an unknown write

    @staticmethod
    def upload(path: str):
        """The upload route of a path (core/routing.Upload), or None: web.py reads such a body itself, under the route's cap."""
        return UPLOADS.get(path)
