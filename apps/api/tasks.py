"""The task runner of one panel: each long task in a thread of its own, its record for the page (running with its current
step, done with its result, or an error with a code the panel words in either language and one fix), one model task at a
time (model_lock), and the turn a task waits for while another holds a lock it needs. Long engine output goes to the
panel's log, never to the screen (no file paths or commands on screen).

The tasks themselves are the services' own parts, which Tasks is composed of; each adds its tasks and the state they keep
(its own __init__, run in turn by the super() call in Tasks.__init__):

    services/profile      FactTasks     reading files into facts, the English profile, the profile's own files a build reads
    services/applications Analyses      the posting analysis
                          AnswerTasks   the form's answers and their file
    services/documents    Builds        the engine, an edition's PDFs and checks, the cover letter, the live deck and figures
                          Drafting      the resume's draft, the figures, the depth review, regenerating, tailoring
                          OwnEdition    an application's own edition
                          Exports       the export, the copies that went out, the lock
                          Comparisons   what an edition is held against
    services/interview    Kits          the kits, their servers, the scripts, the talk
    services/agent        AgentTasks    the backend a model task talks to, the run's stop and queue
"""
from __future__ import annotations

import contextlib  # one read of the state, its stamps worked out once (Tasks.one_read); a turn taken and given back
import json  # the records copied for the page
import logging  # the panel's log
import sys  # the engine on the import path
import threading  # one thread per task
import time  # task times
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules

from .core.workspace import Workspace  # noqa: E402  the person's files
from .services.agent import AgentTasks  # noqa: E402  the agent's part: the backend in use
from .services.applications import Analyses, AnswerTasks  # noqa: E402  the applications' parts: the posting analysis, the answers
from .services.documents import Builds, Comparisons, Drafting, Exports, OwnEdition  # noqa: E402  the documents' parts: builds, checks across documents, drafts, export, own editions
from .services.interview import Kits  # noqa: E402  the interview's part: the kits and the talk
from .services.profile import Facts, FactTasks  # noqa: E402  the profile's facts, and its part: reading files, the English profile

log = logging.getLogger("offerowl.panel")  # the panel's log


class Tasks(OwnEdition, Kits, Exports, AnswerTasks, Analyses, Comparisons, Builds, Drafting, FactTasks, AgentTasks):
    """Every long task of one panel. state() is what the panel shows. Each service's part adds its tasks and the state they
    keep (its own __init__, run in turn by the super() call below)."""

    def __init__(self, ws: Workspace, facts: Facts, card):
        self.ws, self.facts, self.card = ws, facts, card  # the workspace, its facts, the agent card
        self.state_lock = threading.Lock()  # guards self.tasks (lock() is the submitted-copy action)
        self.tasks: dict[str, dict] = {}  # key -> {"state", "step", "error", "result", "t"}
        self.model_lock = threading.Lock()  # one model task at a time: the backend is set in the environment
        self._one = threading.local()  # per request thread: the stamps one read of the state already worked out (one_read)
        self.run_no = 0  # counts the tasks started, so a finished thread never ends the next run of its key
        super().__init__()  # each service's part: its locks, its memories, the stand-ins a test sets

    # ------------------------------------------------------------------ bookkeeping

    def state(self) -> dict:
        """A copy of every task's state."""
        with self.state_lock:  # a copy taken under the lock
            return json.loads(json.dumps(self.tasks))  # deep copy, JSON-safe

    def _set(self, key: str, **values) -> None:
        """Change one task's state."""
        with self.state_lock:  # one writer at a time
            self.tasks.setdefault(key, {}).update(values, t=time.time())  # merged, stamped

    def busy(self, key: str) -> bool:
        """The task is running now."""
        with self.state_lock:  # read under the lock
            return (self.tasks.get(key) or {}).get("state") == "running"  # running, not done or failed

    def start(self, key: str, fn, *args) -> bool:
        """Run fn(*args) in a thread as task `key`. False when it is already running."""
        with self.state_lock:  # check and mark in one step
            if (self.tasks.get(key) or {}).get("state") == "running":  # a second click must not start a twin
                return False  # one at a time per key
            self.run_no += 1  # this task's number
            no = self.run_no  # kept in its record
            self.tasks[key] = {"state": "running", "step": "queued", "t": time.time(), "run": no}  # shown at once

        threading.Thread(target=self._run, args=(key, no, fn, args), name=f"task-{key}", daemon=True).start()  # in the background
        return True  # started

    def _run(self, key: str, no: int, fn, args) -> None:
        """Task `key`'s body, run number `no`: fn sets done or error itself; one that returns without saying is done, and
        one that raises is an error with a retry, its trace in the log."""
        try:
            fn(*args)  # the task sets done or error itself
            with self.state_lock:  # read and written in one step
                rec = self.tasks.get(key) or {}  # the record now
                if rec.get("state") == "running" and rec.get("run") == no:  # still this task, and it returned without saying
                    rec.update(state="done", t=time.time())  # a task that set nothing counts as done
        except (Exception, SystemExit) as exc:  # a bug, or a tool that stopped with a message: shown as an error with a retry, logged in full
            log.exception("task %s failed", key)  # the trace goes to the log, not the page
            self._set(key, state="error", error={"code": "unexpected", "detail": type(exc).__name__})  # the page gets a code and a retry

    def forget_tasks_of(self, job_id: str) -> None:
        """A job deleted for good (the Trash): what its tasks said goes from the records, so no record names it."""
        with self.state_lock:  # the records change under their lock
            for k in [k for k in self.tasks if k.endswith(":" + job_id)]:  # analyze:<job>, build:<job> and the rest
                self.tasks.pop(k, None)

    def run_here(self, key: str, fn, *args, wait_s: float = 900) -> bool:
        """Run fn(*args) in this thread as task `key`, the way start() runs it in a thread of its own: the page sees it
        running, and a start of the same key meanwhile is refused (a build the page asks for while tailoring typesets the
        same edition would write its folder twice at once). A run of the key already going (a build the page started) is
        waited for, up to wait_s. False when it never got its turn."""
        deadline = time.time() + wait_s  # how long a running twin is waited for
        while True:
            with self.state_lock:  # check and mark in one step, as start() does
                if (self.tasks.get(key) or {}).get("state") != "running":  # its turn
                    self.run_no += 1  # this run's number
                    no = self.run_no
                    self.tasks[key] = {"state": "running", "step": "queued", "t": time.time(), "run": no}  # shown at once
                    break
            if time.time() > deadline:  # the other run never ended
                return False
            time.sleep(0.5)  # the other run is still going
        self._run(key, no, fn, args)  # here, not in a thread: the caller goes on once it is done
        return True

    @contextlib.contextmanager
    def turn(self, key: str, *locks):
        """The locks, taken in order. One model task and one rendering run at a time, so a task started meanwhile waits;
        while it does, the page says so (step "waiting_turn") instead of seeming stuck at its start, and its own step comes
        back once the locks are its."""
        held, waited, before = [], False, None  # the locks taken, whether it had to wait, and the step it showed then
        try:
            for lock in locks:
                if not lock.acquire(blocking=False):  # another task has it now
                    if not waited:  # said once, however many locks it waits for
                        with self.state_lock:  # read under the lock
                            before = (self.tasks.get(key) or {}).get("step")  # what the page showed
                        self._set(key, step="waiting_turn")  # the page says it waits its turn
                        waited = True
                    lock.acquire()  # its turn
                held.append(lock)
            if waited:  # the page shows its own step again
                self._set(key, step=before)
            yield
        finally:
            for lock in reversed(held):  # given back, last taken first
                lock.release()

    @contextlib.contextmanager
    def one_read(self):
        """One read of the state (App.state): what does not change within it (the deck source's stamp) is worked out once
        instead of once per edition. Per thread, so another request's read never sees this one's memo; nested reads share it."""
        outer = getattr(self._one, "memo", None)  # a read already open in this thread
        if outer is None:  # the first: a fresh memo
            self._one.memo = {}
        try:
            yield
        finally:
            if outer is None:  # the read that opened it closes it: the next poll looks at the files again
                self._one.memo = None
