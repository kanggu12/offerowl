"""The API called in this process, with no server and no port: what the command line wraps.

    from apps.api.client import Client
    c = Client(data=Path("~/offerowl-data"))          # the same data folder the app uses (default: the app's)
    c.post("/api/v1/materials/file", {"path": "cv.pdf"})   # a file from disk (the command line's own way in)
    c.get("/api/v1/jobs/gamma/fit")

    python3 -m apps.api get /api/v1/state             # the same from a shell (see __main__.py)

Every call goes through routes.Router, the table the panel's server uses, so the command line and the panel can
never drift apart. Tasks run in threads as they do for the panel; wait() polls one until it ends.
"""
from __future__ import annotations

import json  # answers
import time  # waiting for tasks
from pathlib import Path  # paths

from .app import Api, data_dir  # the API object and the default data folder
from .routes import Router  # the table


class Client:
    """One API in this process."""

    def __init__(self, data: Path | None = None, workspace: Path | None = None):
        self.api = Api(Path(data).expanduser() if data else data_dir(), workspace)  # the state and the actions
        self.router = Router(self.api)  # the table

    def get(self, path: str, **query) -> object:
        """A read. Raises RuntimeError with the error code when the API refuses it."""
        code, body, _ = self.router.handle("GET", path, {k: str(v) for k, v in query.items()})  # the table answers
        if code >= 400:  # refused
            raise RuntimeError(json.dumps(body, ensure_ascii=False))  # the code and what
        return body  # JSON as data, or bytes for files

    def post(self, path: str, body: dict | None = None, state: bool = False) -> dict:
        """A write. The whole state comes back only when asked (the command line rarely needs it)."""
        if path == "/api/v1/materials/file":  # the command line's way to add a file: from disk, by its path
            p = Path(str((body or {}).get("path") or "")).expanduser()  # the file
            rec = self.api.ws.add_material(p.name, p.read_bytes())  # kept in sources/ like an upload
            return {"ok": True, "material": rec}  # then read it with /materials/read
        code, out, _ = self.router.handle("POST", path, {"state": "1" if state else "0"}, body or {})  # the table answers
        if code >= 400:  # refused
            raise RuntimeError(json.dumps(out, ensure_ascii=False))  # the code and what
        return out  # the action's fields

    def wait(self, key: str, timeout: float = 900) -> dict:
        """Wait until a task ends (done or error) and return its record. Only a task of this process can be waited for:
        one this process never started is said at once, not after the timeout."""
        start = time.time()  # for the grace below
        end = start + timeout  # give up after this
        while time.time() < end:  # until the deadline
            rec = self.api.tasks.state().get(key) or {}  # the task now
            if rec.get("state") in ("done", "error"):  # ended either way
                return rec  # its record
            if not rec and time.time() - start > 2:  # never started here: tasks live in the process that starts them
                raise RuntimeError(f"no task {key} in this process")
            time.sleep(0.2)  # not a busy loop
        raise TimeoutError(key)  # a hung task

    def settle(self, timeout: float = 900) -> dict:
        """Wait until no task of this process runs, and return how each one ended ({key: state})."""
        end = time.time() + timeout  # give up after this
        while time.time() < end:  # until the deadline
            tasks = self.api.tasks.state()  # every task this process knows
            if not any(t.get("state") == "running" for t in tasks.values()):  # all ended
                return {k: t.get("state") for k, t in tasks.items()}  # how
            time.sleep(0.2)  # not a busy loop
        raise TimeoutError("tasks still running")  # a hung task
