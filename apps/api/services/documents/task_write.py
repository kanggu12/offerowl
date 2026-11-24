"""Tasks' part for the drafted words (apps/api/tasks.py inherits it): the documents service's drafting tasks. The resume's
sentences written from the evidence, the deck's figures, the depth review as a task, one sentence written again from its
evidence, and one action that tailors a job's three documents at once; and which English profile an edition can use.

A job's posting is read where the applications keep it (posting_file); the sentence rules are the profile's evidence.
"""
from __future__ import annotations

import logging  # the panel's log
from pathlib import Path  # paths

from .. import applications  # a job's posting
from ...core.stamps import file_hash  # noqa: E402  the draft's stamp
from ...core.workspace import read_json, today, write_json  # noqa: E402  files

log = logging.getLogger("offerowl.panel")  # the panel's log
FIGURE_CALLS = 6  # model calls one round of figures may take; projects share a call when there are many
MEASURED_CALLS = 0  # calls of figure_draft's measured step: off until its charts are judged worth their place on a real profile


class Drafting:
    """The words the agent writes for an edition, and the tasks that write them."""

    def __init__(self):
        super().__init__()  # the other parts' own
        self.write_ask = None  # a test's stand-in for the model in the resume draft
        self.figure_ask = None  # and in the figure step
        self.depth_ask = None  # and in the depth review (depth.py)

    def write_resume(self, job_id: str, lang: str = "ko") -> bool:
        """The resume's sentences written from the evidence (task "write:<job>")."""
        return self.start(f"write:{job_id}", self._write_task, job_id, lang)  # one per job at a time

    def _write_task(self, job_id: str, lang: str) -> None:
        key = f"write:{job_id}"  # this task
        self._set(key, step="writing_resume")  # the step the page shows
        got = self._write(job_id, lang, every=True)  # asked for: every part written again
        if got["state"] == "done":  # written
            got["depth"] = self._depth_stage(key, job_id, lang)  # the drafting run's last stage: what each item still leaves out
            self._set(key, state="done", step="", result=got)  # the page shows the counts
        else:  # no agent, or it never answered
            self._set(key, state="error", error={"code": "agent_unavailable" if got["state"] == "needs_agent" else "agent_stopped"})  # the band says which

    def depth(self, job_id: str, lang: str = "ko") -> bool:
        """The depth review of an edition (task "depth:<job>", depth.py): what each project item and deck page leaves out."""
        return self.start(f"depth:{job_id}", self._depth_task, job_id, lang)  # one per edition at a time

    def _depth_task(self, job_id: str, lang: str) -> None:
        key = f"depth:{job_id}"  # this task
        self._set(key, step="reviewing_depth")  # the step the page shows
        from . import depth  # the review
        try:
            rec = depth.run(self, job_id, lang, ask=self.depth_ask, key=key)  # the agent in use, else the checks that need none
        except ValueError as exc:  # no English profile yet, say
            self._set(key, state="error", error={"code": str(exc), "lang": lang})  # the band names the fix, on the sheet of that language
            return
        except Exception as exc:  # noqa: BLE001  a review that broke: the sheet says so with a retry, the trace goes to the log
            log.exception("depth review of %s %s failed", job_id, lang)
            self._set(key, state="error", error={"code": "unexpected", "detail": type(exc).__name__, "lang": lang})
            return
        self._set(key, state="done", step="", result=depth.summary(rec))  # the page reads the review itself

    def _depth_stage(self, key: str, job_id: str, lang: str) -> dict | None:
        """The depth review as the last stage of a drafting run (the write and tailor tasks): its summary, or None when it could
        not run (the draft stands either way: a review never stops one)."""
        from . import depth  # the review
        self._set(key, step="reviewing_depth")  # the step the page shows
        try:
            return depth.summary(depth.run(self, job_id, lang, ask=self.depth_ask, key=key))
        except Exception:  # noqa: BLE001  a review that broke is said in the log; the draft is kept
            log.exception("depth review of %s %s failed", job_id, lang)
            return None

    def draw_figures(self, job_id: str, lang: str = "ko") -> bool:
        """The deck's figures, drawn from each printed project's evidence (task "figures:<job>")."""
        return self.start(f"figures:{job_id}", self._figures_task, job_id, lang)  # one per job at a time

    def _figures_task(self, job_id: str, lang: str) -> None:
        key = f"figures:{job_id}"  # this task
        self._set(key, step="drawing_figures")  # the step the page shows
        got = self._figures(job_id, lang)  # the figures
        if got["state"] == "done":  # drawn
            self._set(key, state="done", step="", result=got)  # the page shows the counts
        else:  # no agent, no draft, or it never answered
            self._set(key, state="error", error={"code": "agent_unavailable" if got["state"] == "needs_agent" else "needs_draft" if got["state"] == "needs_draft" else "agent_stopped"})  # the band says which

    def _figures(self, job_id: str, lang: str) -> dict:
        """Figures for the deck through src/figure_draft.py, kept in the draft in force. Every number and name in a figure must be in
        that project's evidence, and a proposal that fails a check goes back once and is left out if it fails again."""
        from . import drafts as D  # where a draft is kept
        import figure_draft as FD  # src/figure_draft.py
        d, owner = D.load(self, job_id)  # the draft in force
        if not d:  # the slides read the draft's sentences, so it comes first
            return {"state": "needs_draft"}  # the page offers to write the resume
        src = self.facts.profile_file()  # the facts' profile
        now = D.merged(read_json(src, {}), d)  # what the deck prints
        langs = list((d.get("_draft") or {}).get("langs") or [lang])  # the languages the draft has
        printed = {p.get("id") for r in now.get("roles") or [] for p in r.get("projects") or [] if isinstance(p, dict) and p.get("resume") is not False and p.get("deck") is not False}  # the projects on the resume
        with self.model_lock:  # one model task at a time
            if self.backend() == "none":  # no agent: the slides keep their cards
                return {"state": "needs_agent"}  # the page offers to turn it on
            now, gone = FD.prune(now, langs, only=printed)  # figures today's checks turn down go first, so their places are asked for again
            doc = FD.propose(now, only=printed, langs=langs, max_calls=FIGURE_CALLS, ask=self.figure_ask, measured_calls=MEASURED_CALLS)  # the proposals, each checked
            if any(f["status"] != "ok" for e in doc["projects"] for f in e["figures"]):  # one came back with a finding
                doc = FD.repair(doc, now, ask=self.figure_ask)  # one more call with the findings
        if doc.get("errors") and not doc["projects"]:  # the model never answered
            log.info("figures %s stopped: %s", job_id, doc["errors"][:2])  # for the log only
            return {"state": "failed"}  # the page offers to try again
        FD.review(doc, accept=["all"])  # what passed every check is taken; the rest stays out
        new, added, notes = FD.apply(doc, now)  # the figures on the projects
        by_id = {p.get("id"): p for r in new.get("roles") or [] for p in r.get("projects") or [] if isinstance(p, dict)}  # the projects with their figures
        for r in d.get("roles") or []:  # the stored draft's roles
            for p in r.get("projects") or [] if isinstance(r, dict) else []:  # and projects
                got = by_id.get(p.get("id")) if isinstance(p, dict) and p.get("id") in printed else None  # the same project, when this run looked at it
                if got is None:  # a project off the resume keeps what it has
                    continue
                for k in D.FIGURE_KEYS:  # what the step adds or took out
                    if got.get(k):  # drawn
                        p[k] = got[k]  # kept with the draft
                    else:  # none left
                        p.pop(k, None)  # a figure the checks turned down does not come back
        total = sum(len(e["figures"]) for e in doc["projects"])  # every proposal
        record = read_json(self.ws.job_dir(owner) / "draft.record.json", {}) or {}  # what the draft's run did
        record["figures"] = {"added": added, "left_out": total - added, "calls": doc.get("calls", 0), "replaced": len(gone)}  # and this one
        with self.ws.change({"code": "undo_figures"}, D.files(owner)):  # one undo step
            write_json(self.ws.job_dir(owner) / "draft.json", d)  # the draft with its figures
            write_json(self.ws.job_dir(owner) / "draft.record.json", record)  # what the page shows
        return {"state": "done", **record["figures"]}  # the task's result

    def _write(self, job_id: str, lang: str, every: bool = False) -> dict:
        """Write the resume from the evidence through src/write_resume.py, and keep it with the job (drafts.py).
        Locked sentences keep their words. A job writes for its posting, the general edition for no job in particular.
        Returns {state, ...}: done with the counts, needs_agent, or failed."""
        from . import documents as DOC  # the sentences as they are drawn now
        from . import drafts as D  # where a draft is kept
        from ..profile import replaced  # one sentence of a paragraph (the profile's evidence rules)
        import write_resume as W  # src/write_resume.py
        job_path = self.ws.job_dir(job_id)  # the job's folder
        posting = applications.posting_file(self.ws, job_id)  # where the applications keep it; the general edition has none
        text = posting.read_text(encoding="utf-8") if posting.is_file() else None  # what it writes for
        prof = D.with_ids(self.facts.profile())  # every project with an id
        langs = ("en",) if self.profile_lang() == "en" else ("ko", "en")  # a profile in Korean gets both, written side by side
        with self.model_lock:  # one model task at a time
            backend = self.backend()  # which agent
            if backend == "none":  # no agent: the facts stay on the canvas
                return {"state": "needs_agent"}  # the page offers to turn it on
            try:
                parts = list(W.PARTS) if text or every else None  # a job, or the person asking, rewrites every part; a run's general edition keeps the resume text a profile already holds and writes only what is missing
                new, rec = W.draft(prof, posting_text=text, style=W.load_style(self.style_spec()), langs=langs, parts=parts, backend=backend, ask=self.write_ask)  # by the person's own rules when they chose a pack
            except W.Stopped as exc:  # the model never answered
                log.info("draft %s stopped: %s", job_id, exc)  # for the log only
                return {"state": "failed"}  # the page offers to try again
        old = read_json(job_path / "draft.json", None)  # the last draft of this job
        D.carry_figures(new, old, read_json(self.ws.job_dir(D.GENERAL) / "draft.json", None))  # figures drawn already stay
        new["_locks"] = {}  # this draft's own
        for code in langs:  # each language it wrote
            before = D.merged(prof, old) if old else prof  # the ids of the locks in force
            locks = ((old or {}).get("_locks") or {}).get(code) if old else (self.facts.locks() if code == "ko" else {})  # a draft's own, else the facts'
            new["_locks"][code] = D.carry_locks(locks, before, D.links_of(old, code), new, prof, code, replaced)  # moved with their projects
        record = {"at": today(), "calls": rec.get("calls"), "stopped": rec.get("stopped") or "", "trimmed": rec.get("trimmed") or [],  # what the run did
                  "counts": {"written": len(rec.get("texts") or []), "rewritten": sum(1 for x in rec.get("texts") or [] if x.get("round") == "repair"),  # the page's counts
                             "dropped": len(rec.get("dropped") or [])}}  # texts that never passed
        with self.ws.change({"code": "undo_draft"}, D.files(job_id)):  # one undo step takes the whole draft back
            write_json(job_path / "draft.json", new)  # the drafted profile
            write_json(job_path / "draft.record.json", record)  # what the page shows
        DOC.resume(self, lang, "navy", job_id)  # a draft the canvas cannot read must fail here, inside the task
        return {"state": "done", **record["counts"]}  # the task's result

    def drafted_english(self, job_id: str | None) -> bool:
        """Does the draft in force for this job (or the general one) hold English sentences?"""
        from . import drafts as D  # where a draft is kept
        d, _ = D.load(self, job_id)  # the job's own, else the general edition's
        return bool(d) and "en" in ((d.get("_draft") or {}).get("langs") or [])  # written in English too

    def english_for(self, job_id: str | None) -> Path | None:
        """The English profile an English edition of this job can use: a full translation, or a partial one when the job's draft
        holds the English the partial one leaves out. None when the edition must ask for a translation first."""
        own = self.own_dir(job_id)  # a job's own edition was written in its languages, and needs no translation
        if own is not None:
            return own / "profile" / "profile.json" if "en" in self.own_langs(job_id) else None
        p = self.english_profile()  # the translation of this very profile
        if p is None or self.profile_lang() == "en":  # none, or the profile is English itself
            return p  # as it is
        return p if not read_json(p, {}).get("_partial") or self.drafted_english(job_id) else None  # a partial one needs the draft's English

    def draft_stamp(self, job_id: str) -> str:
        """A short hash of the draft a job draws from ("" with none): PDFs made before a new draft are stale."""
        from . import drafts as D  # where a draft is kept
        owner = D.owner(self, job_id)  # the job's own, else the general edition's (decided without parsing them again)
        return file_hash(self.ws.job_dir(owner) / "draft.json") if owner else ""  # the file as it is now

    def tailor(self, job_id: str, lang: str, theme: str, max_pages: int, with_cover: bool = True, typeset: bool = False) -> bool:
        """One action for a job: the resume ordered for it, the cover letter drafted from the same plan, and the
        interview kit's question map (task "tailor:<job>"). `typeset` also makes the PDFs when the typesetting can run."""
        return self.start(f"tailor:{job_id}", self._tailor, job_id, lang, theme, max_pages, with_cover, typeset)  # one per job at a time

    def _tailor(self, job_id: str, lang: str, theme: str, max_pages: int, with_cover: bool, typeset: bool) -> None:
        key = f"tailor:{job_id}"  # this task
        parts = {"resume": "running", "cover": "waiting" if with_cover else "skipped", "interview": "waiting"}  # each document's state
        self._set(key, step="analysis", parts=dict(parts))  # the page shows the three parts
        self._analyze(job_id)  # the resume's order for this job (the agent, else the words); its own task record says how
        self._set(key, step="writing_resume", parts=dict(parts))  # the step the page shows
        wrote = self._write(job_id, lang)  # its sentences for this job, when an agent is on
        parts["resume"] = "failed" if wrote["state"] == "failed" else "done"  # with no agent the canvas still follows the plan
        out = self.edition_inputs(job_id, lang, theme, max_pages)  # the edition's inputs
        if isinstance(out, str):  # a name, an email or the translation is missing
            parts.update(cover="blocked" if with_cover else "skipped", interview="blocked")  # the other two need a resume
            self._set(key, state="error", step="", parts=parts, error={"code": out})  # the band names the fix
            return  # nothing else to do
        if typeset and not self.engine_ready():  # the PDFs too, where the typesetting can run
            self._set(key, step="typesetting_resume", parts=dict(parts))  # the step the page shows
            self.run_here(f"build:{job_id}", self._build, job_id, lang, theme, max_pages, with_cover, True)  # the existing build, as a build of its own (its task record keeps the details; the page's own build waits)
            built = read_json(self.build_dir(job_id, lang) / "build.json", {})  # what it made
            parts["cover"] = ((built.get("cover") or {}).get("state") or "failed") if with_cover and not built.get("blind") else "skipped"  # the letter came with it; a blind edition has none
        elif with_cover:  # the letter drafted without typesetting
            self._set(key, step="writing_cover", parts=dict(parts))  # the step the page shows
            got = self._cover(job_id, lang, out, render=False)  # plan and draft (the agent writes it)
            parts["cover"] = (got or {}).get("state", "unavailable")  # drafted, needs_agent or failed
        self._set(key, step="interview_kit", parts=dict(parts))  # the step the page shows
        try:
            rows = self.ensure_kit(job_id, lang)  # the question map, without a model
            parts["interview"] = "done"  # the studio can open
            drafted, stopped = 0, False  # scenes the agent wrote, and whether it stopped
            if self.card.chosen() != "none" and rows:  # an agent is on: a few scripts for the likeliest questions
                drafted, stopped = self._draft_scenes(job_id)  # at most five, checked before anyone reads them
                rows = self.ensure_kit(job_id, lang)  # the map again: it now holds the agent's expected questions and sees its drafts
            result_iv = {"questions": len(rows), "drafted": drafted, "stopped": stopped}  # for the page
        except Exception:  # the kit could not be made: the rest still stands
            log.exception("interview kit for %s failed", job_id)  # the trace for the log
            parts["interview"], result_iv = "failed", {}  # the page says so
        stops = [k for k, v in parts.items() if v == "failed"] + (["scripts"] if result_iv.get("stopped") else [])  # what the agent did not finish
        depth_seen = self._depth_stage(key, job_id, lang) if wrote["state"] == "done" else None  # the drafting run's last stage, with the deck it made
        self._set(key, state="done", step="", parts=parts, result={"interview": result_iv, "stopped": stops, "depth": depth_seen})  # all three answered, and what to try again

    REGEN_WAYS = {  # a direction the person picks with one press, never types: how the rewrite should change the sentence
        "shorter": "Make it clearly shorter: keep the action and the change, drop the rest.",
        "plainer": "Use plainer, everyday words a recruiter outside the field reads at once.",
        "result": "Lead with what changed as a result, then what was done to get there.",
    }

    def regen(self, sid: str, lang: str = "ko", job: str | None = None, way: str = "") -> bool:
        """New words for one sentence from its evidence alone (task "regen:<sentence>"), in a direction the person picked."""
        return self.start(f"regen:{sid}", self._regen, sid, lang, job, way if way in self.REGEN_WAYS else "")  # one per sentence at a time

    def _regen(self, sid: str, lang: str, job: str | None = None, way: str = "") -> None:
        import draft  # src/draft.py: the checks every suggestion passes
        import llm  # src/llm.py: the one door to a model
        from . import documents  # the resume model and the edit path
        key = f"regen:{sid}"  # this task
        R = documents.model(self, lang, job)  # the sentences now
        rec = R.sent.get(sid)  # this sentence
        if not rec:  # a stale page
            self._set(key, state="error", error={"code": "bad_request"})  # refused
            return  # nothing else to do
        if rec.get("locked"):  # a locked sentence keeps its words
            self._set(key, state="error", error={"code": "locked"})  # the page says to unlock it first
            return  # nothing else to do
        ev = R.evidence_text(sid) or "\n".join(e.get("quote", "") for e in rec.get("evidence") or [])  # what it may say
        if not ev.strip():  # nothing to write from
            self._set(key, state="error", error={"code": "no_evidence"})  # the page says so
            return  # nothing else to do
        words = "Korean" if lang == "ko" else "English"  # the sentence's language
        limit = max(40, int(len(rec["text"]) * 0.7)) if way == "shorter" else max(60, min(200, len(rec["text"]) + 40))  # shorter when asked, else about as long as it is now
        prompt = (f"Evidence:\n<<<\n{ev[:6000]}\n>>>\n\nRewrite this resume sentence in {words} using only facts from the evidence. "  # the task
                  f"One sentence, under {limit} characters, plain past tense, what was done and what changed. At most one short "
                  f"result phrase in ==double equals==. Never add numbers, tools, products, clients or results that are not in the evidence.\n"
                  + (f"{self.REGEN_WAYS[way]}\n" if way else "")  # the direction the person picked
                  + f"Sentence now: {rec['text']}\n"
                  'Return JSON: {"text": "..."}')  # the answer's shape
        with self.turn(key, self.model_lock):  # one model task at a time, said on the page while it waits
            backend = self.backend()  # which agent
            if backend == "none":  # no agent: said plainly
                self._set(key, state="error", error={"code": "agent_unavailable"})  # the band offers to turn the agent on
                return  # nothing else to do
            self._set(key, step="asking_agent")  # the step the page shows
            try:
                out = llm.run("panel-regenerate", prompt, system=draft.SYSTEM, want_json=True, required=("text",), backend=backend, timeout=180)  # one small call
            except llm.LLMUnavailable:  # the agent did not answer
                self._set(key, state="error", error={"code": "agent_unavailable"})  # the same band as with no agent
                return  # nothing else to do
            except ValueError:  # the answer never had the right form
                self._set(key, state="error", error={"code": "agent_stopped"})  # the page offers to try again
                return  # nothing else to do
        new = str((out or {}).get("text") or "").strip()  # the proposal
        why = draft.check_text(new, ev, style=draft.style_pack(self.style_spec()), max_len=limit + 20, highlight=(0, 1), lang=lang)  # numbers, names, style, length
        if why:  # it said something the evidence does not
            from ..profile import issue_codes  # the page's codes (the profile's evidence rules)
            self._set(key, state="error", error={"code": "regen_rejected", "issues": issue_codes([w for w in why if ":" in w])})  # what stopped it
            return  # the sentence stays as it was
        documents.edit_sentence(self, sid, new, lang, job)  # saved as an edit: one undo step, and the evidence check runs again
        self._set(key, state="done", step="", result={"text": new})  # the page shows the new words
