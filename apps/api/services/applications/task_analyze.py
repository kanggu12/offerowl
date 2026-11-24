"""Tasks' part for a job's posting analysis (apps/api/tasks.py inherits it): the plan that orders a resume's skill groups,
strengths and projects for one posting, by the agent when one is on, else by the fit's words on this PC. Kept as the job's
plan.json, which the applications service owns (the documents read it through plan_of)."""
from __future__ import annotations

import logging  # the panel's log

from ...core.workspace import read_json, today, write_json  # files, and the day a plan was made

log = logging.getLogger("offerowl.panel")  # the panel's log


def plan_of(ws, jid: str) -> dict:
    """A job's posting analysis as kept ({} before the first one): what orders the resume and the deck for its posting."""
    return read_json(ws.job_dir(jid) / "plan.json", {})  # jobs/<job>/plan.json


class Analyses:
    """A job's posting analysis: the task, and the plan it keeps."""

    def analyze(self, job_id: str, agent: bool = True, step: bool = True) -> bool:
        """Match the posting to the profile (task "analyze:<job>"). agent=False keeps it on this PC, by words. step=False
        makes no undo step of its own: the analysis that follows adding a job or pasting its posting belongs to that change,
        whose step holds plan.json (a step of its own would come after it and turn the toast's Undo into "moved")."""
        return self.start(f"analyze:{job_id}", self._analyze, job_id, agent, step)  # one analysis per job at a time

    def _analyze(self, job_id: str, agent: bool = True, step: bool = True) -> None:
        import draft  # src/draft.py
        from . import fit  # the fit by words, this service's own
        key = f"analyze:{job_id}"  # this task
        rel = f"jobs/{job_id}/plan.json"  # where the plan is kept
        for _ in range(3):  # a posting pasted again, or taken back by an undo, while this ran: the plan follows the newer text
            path = self.ws.job_dir(job_id) / "posting.md"  # the posting
            if not path.is_file():  # the job was taken back meanwhile (the toast's Undo): no plan for a job no longer there
                self._set(key, state="done", step="", result={})
                return
            posting = path.read_text(encoding="utf-8")  # the posting as it is now
            plan = self._plan_of(key, posting, agent, draft, fit)  # the analysis itself
            with (self.ws.change({"code": "undo_analysis"}, [rel]) if step else self.ws.lock):  # its own undo step, or part of the change that started it
                if path.is_file() and path.read_text(encoding="utf-8") == posting:  # still the posting it was made from
                    write_json(self.ws.path(rel), plan)  # saved with the job
                    break
        else:  # the posting kept changing: the last paste's own analysis, or the next one, writes the plan
            self._set(key, state="done", step="", result={})
            return
        self._set(key, state="done", step="", result={k: plan.get(k) for k in ("skillsFocus", "projectOrder", "by")})  # the page shows these

    def _plan_of(self, key: str, posting: str, agent: bool, draft, fit) -> dict:
        """The plan of one posting against the profile as it is now: the agent's when it answers, else the fit by words."""
        prof = self.facts.profile()  # the profile as it is now
        self._set(key, step="asking_agent")  # the step the page shows
        cfg, by = None, "words"  # the agent's plan when it answers, else the words
        with self.turn(key, self.model_lock):  # one model task at a time, said on the page while it waits
            if agent and self.backend() != "none":  # an agent is on and may be asked: it picks what the job needs
                try:
                    cfg, steps = draft.task_jd(prof, posting)  # skill groups first, strengths back, project order
                    by = "agent"  # made by the agent
                except draft.Stopped as exc:  # the agent stopped or was never there: the words still give an order
                    log.info("analysis stopped, words instead: %s", exc)  # the reason for the log
                    cfg = None  # fall back below
        if cfg is None:  # no agent, or it stopped: the fit by words orders the resume
            self._set(key, step="matching_words")  # the step the page shows
            cfg = fit.plan_by_words(prof, fit.compute(prof, posting, evmap=self.facts.evidence(), cands=self.facts.candidates()))  # no model
        plan = {k: cfg.get(k) for k in ("skillsFocus", "competencyWeak", "projectOrder") if cfg.get(k)}  # what the build uses
        plan.update(at=today(), profile=self.facts.profile_hash(), by=by)  # when, from which profile (the profile's own hash), by whom
        return plan
