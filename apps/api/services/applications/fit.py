"""How well the profile fits a posting, line by line, with the evidence that covers each line and the gaps
(core/schema/job.schema.json $defs/fit).

The posting is read and matched by src/cover.py's own plan with words only (no model): its duties, requirements and
preferred lines in the posting's order, each rated strong, weak or none, with the profile's evidence units behind it
and the tools the line names that the profile never shows. The same plan grounds the cover letter, so the fit the page
shows and the letter the agent writes agree. The score is 100 x (strong + half of weak) / lines.

Without an agent the same rating orders the resume for the job (plan_by_words): the skill groups the covered lines
cite lead, and the projects that cover the most lines come first.
"""
from __future__ import annotations

import hashlib  # the cache's keys
import logging  # a fit that failed, for the log
import sys  # the engine on the import path
import threading  # one plan at a time, and the fits made again in the background
import time  # the fits made again after the answer that changed the profile
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[4]  # the repository (or the app's bundle)
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules

from ..profile import text_of  # noqa: E402  plain text (the profile's)

WEIGHT = {"strong": 1.0, "weak": 0.5, "none": 0.0}  # what each rating adds to the score
PLAN_LOCK = threading.Lock()  # src/cover.py's plan is not written for threads: one at a time (each takes milliseconds)
PREPARED = {}  # (profile key, language) -> (units, index): see prepared()


def files_of_projects(prof: dict, evmap: dict, by_cid: dict) -> dict:
    """Project id -> the name of the file its fact was read from, so a fit line can say where its evidence lives."""
    out = {}  # project id -> file name
    for ri, r in enumerate(prof.get("roles") or []):  # employers
        for pi, p in enumerate((r.get("projects") or []) if isinstance(r, dict) else []):  # their projects
            for c in evmap.get(f"roles.{ri}.projects.{pi}") or []:  # the facts behind the project
                f = by_cid.get(c)  # the fact
                if f and (f.get("source") or {}).get("name"):  # read from a named file
                    out[str(p.get("id") or "")] = text_of(f["source"]["name"])  # its file's name
                    break  # one name is enough
    return out  # for the evidence entries


def prepared(cover, prof: dict, lang: str, profile_key: str | None):
    """(units, index) of a profile in a language, worked out once per profile (named by profile_key, the hash of the
    profile's file) and shared by every job's fit: after a profile change every job is planned again, and these two were
    most of that work. None without a key (nothing is kept). The caller holds PLAN_LOCK."""
    if not profile_key:  # a caller that cannot name the profile
        return None
    key = (profile_key, lang)
    if key not in PREPARED:  # this profile, in this language, for the first time
        if len(PREPARED) >= 4:  # older profiles go: a change leaves its predecessors behind
            PREPARED.clear()
        U = cover.units_of(prof, lang)  # the evidence units
        PREPARED[key] = (U, cover.Lex(U) if U["units"] else None)  # and their index (none for a profile with nothing to cite)
    return PREPARED[key]


def compute(prof: dict, posting: str, *, lang: str | None = None, evmap: dict | None = None, cands: list | None = None,
            profile_key: str | None = None) -> dict:
    """The fit of a profile to a posting. Never calls a model. A posting without duty lines gives no lines and a
    score of 0, with `reason` saying so. `profile_key` names the profile (its file's hash) so that its units and their
    index are worked out once for every job."""
    import cover  # src/cover.py: the posting parser, the evidence units and the word matching
    try:
        with PLAN_LOCK:  # one plan at a time
            lang = lang or cover.guess_lang(posting)  # the plan's language, as plan() would guess it
            ready = prepared(cover, prof, lang, profile_key)  # the profile's units and index, shared by every job
            plan = cover.plan(prof, posting, lang=lang, backend="none", motivation=False, max_lines=60,  # words only: instant, and the same plan the letter uses
                              prepared=ready if ready and ready[1] is not None else None)
    except SystemExit as exc:  # no duty or requirement lines, or a profile without citable text
        return {"score": 0, "by": "words", "counts": {"strong": 0, "weak": 0, "none": 0}, "lines": [], "gaps": [],  # an empty fit
                "reason": "no_lines" if "line" in str(exc).lower() or "줄" in str(exc) else "no_evidence"}  # why it is empty
    with PLAN_LOCK:  # the same module, one caller at a time
        ready = prepared(cover, prof, plan["lang"], profile_key)  # the units the plan cited, already worked out
        U = ready[0] if ready else cover.units_of(prof, plan["lang"])  # the evidence units the plan cites
    files = files_of_projects(prof, evmap or {}, {c["cid"]: c for c in cands or []})  # project id -> file name
    lines = []  # one per posting line
    for ln in plan["lines"]:  # in the posting's order
        ev = []  # the evidence entries of this line
        for uid in ln.get("ev") or []:  # each cited id: a project or one unit
            if uid in U["proj"]:  # a whole project: its first block (the resume line) speaks for it
                first = U["index"][U["proj"][uid][0]]  # the project's summary block
                meta = (U.get("meta") or {}).get(uid) or {}  # its company and title
                where = " · ".join(x for x in (meta.get("org"), meta.get("title")) if x) or U["heads"].get(uid, "")  # company and title, else the head line
                ev.append({"unit": uid, "quote": first["text"].replace("==", ""), "where": where,  # the project's words and where they belong
                           "file": files.get(uid, "")})  # where it was read from
            elif uid in U["index"]:  # one unit: a skills row, a summary card
                u = U["index"][uid]  # the unit
                where = {"skills": "skills", "summary": "summary", "competency": "strengths", "education": "education", "section": "lists"}.get(u.get("kind"), "")  # which part of the profile
                ev.append({"unit": uid, "quote": u["text"].replace("==", ""), "where": where, "file": ""})  # its words
        lines.append({"id": ln["id"], "kind": ln.get("kind", ""), "section": ln.get("section", ""), "text": ln["text"],  # the line itself
                      "rating": ln.get("strength", "none"), "missing": list(ln.get("missing") or []), "evidence": ev})  # its rating and evidence
    counts = {k: sum(1 for x in lines if x["rating"] == k) for k in ("strong", "weak", "none")}  # per rating
    score = round(100 * sum(WEIGHT[x["rating"]] for x in lines) / len(lines)) if lines else 0  # strong counts whole, weak half
    gaps = [x["text"] for x in lines if x["rating"] == "none"] + [t for t in plan.get("gap_terms") or [] if t]  # uncovered lines, then tools never shown
    return {"score": int(score), "by": "words", "counts": counts, "lines": lines, "gaps": gaps,  # the fit
            "company": text_of(plan["posting"].get("company")), "role": text_of(plan["posting"].get("role")), "lang": plan["lang"]}  # what the posting names


def plan_by_words(prof: dict, fit: dict) -> dict:
    """The resume's order for a job without an agent: the skill groups that covered lines cite (in posting order), and
    the projects by how many lines they cover. The same keys as src/draft.py task_jd writes."""
    focus, order = [], {}  # skill groups in order; project id -> lines covered
    cats = {str(s.get("category")): s for s in prof.get("skills") or [] if isinstance(s, dict)}  # the profile's groups
    projects = {str(p.get("id")) for r in prof.get("roles") or [] if isinstance(r, dict) for p in r.get("projects") or [] if isinstance(p, dict)}  # its project ids
    for ln in fit.get("lines") or []:  # in the posting's order
        if ln["rating"] == "none":  # an uncovered line orders nothing
            continue  # next line
        for e in ln["evidence"]:  # what covers it
            uid = e.get("unit", "")  # the unit or project id
            if uid.startswith("skills#"):  # a skills row
                name = next((c for c in cats if c.replace(" ", "_") == uid[len("skills#"):]), None)  # the group it names
                if name and name not in focus:  # each group once
                    focus.append(name)  # in the order the posting needs them
            elif uid in projects:  # a project
                order[uid] = order.get(uid, 0) + WEIGHT[ln["rating"]]  # strong lines weigh more
    ranked = [p for p, _ in sorted(order.items(), key=lambda x: -x[1])]  # most covering first (stable for ties)
    return {"skillsFocus": focus[:4], "competencyWeak": [], "projectOrder": ranked, "by": "words"}  # the plan's keys


log = logging.getLogger("offerowl.panel")  # the panel's log


class Fits:
    """The fit of the profile to each job's posting (compute), one cache per panel: made once per posting and profile, and
    after a change of the profile made again in the background while the lists show the last one."""

    def __init__(self, ws, facts):
        self.ws, self.facts = ws, facts  # the workspace (the postings), the profile's facts
        self._fit_cache: dict = {}  # (job, posting hash, profile hash) -> fit
        self._fit_lock = threading.Lock()  # the page's polls and a write may ask for the same fit at once
        self._fit_pending: dict = {}  # job -> (key, posting): fits to make again in the background after the profile changed
        self._fit_worker = None  # the one thread that makes them

    def fit(self, job_id: str, posting: str | None = None) -> dict:
        """The fit of the profile to a job's posting (fit.compute), cached until the posting or the profile changes. A caller
        that read the posting already passes it (the state reads each job's once per poll)."""
        posting = self.ws.posting(job_id) if posting is None else posting  # the posting, read now unless given
        key = (job_id, hashlib.sha1(posting.encode("utf-8")).hexdigest(), self.facts.profile_hash())  # what the fit depends on
        with self._fit_lock:  # one computation per key, and the cache never changes while it is read
            return self._fit_for(key, job_id, posting)  # cached or made now

    def fit_summary(self, job_id: str, posting: str, ended: bool = False) -> dict:
        """The fit the lists show (the cards, the board, the list): the one for the profile now when it is made, else the last
        one made for this posting while a thread makes the new one, so a change of one fact answers at once instead of after
        every application's fit is made again (seconds with a few dozen applications). The fit tab asks fit() itself, made now."""
        key = (job_id, hashlib.sha1(posting.encode("utf-8")).hexdigest(), self.facts.profile_hash())  # what the fit depends on
        with self._fit_lock:
            if key in self._fit_cache:  # made for this profile
                return self._fit_cache[key]
            older = next((v for k, v in self._fit_cache.items() if k[0] == job_id and k[1] == key[1]), None)  # the same posting, an older profile
            if older is None:  # never made for this posting: made now
                return self._fit_for(key, job_id, posting)
            if ended:  # an application that ended keeps the fit it had in the lists; its fit tab makes the new one when opened
                return older
            self._fit_pending[job_id] = (key, posting)  # made again in the background
            if self._fit_worker is None:
                self._fit_worker = threading.Thread(target=self._fit_run, name="fit-again", daemon=True)
                self._fit_worker.start()
        return older  # the last fit, until the new one is there (the next poll)

    def _fit_run(self) -> None:
        """Make the pending fits again, one at a time, then stop. Each is made outside the lock, so a poll that reads the
        lists meanwhile is never kept waiting."""
        time.sleep(0.8)  # after the answer that changed the profile has gone: a thread busy with fits slows every read of a file (the GIL)
        while True:
            with self._fit_lock:
                if not self._fit_pending:  # all made
                    self._fit_worker = None
                    return
                job_id, (key, posting) = self._fit_pending.popitem()
            try:
                if key[2] != self.facts.profile_hash():  # the profile changed again: the next poll asks for the newer one
                    continue
                made = self._fit_make(key, posting)  # the slow part, unlocked
                with self._fit_lock:
                    if key not in self._fit_cache and key[2] == self.facts.profile_hash():
                        self._fit_cache = {k: v for k, v in self._fit_cache.items() if k[0] != job_id}  # older fits of this job go
                        self._fit_cache[key] = made
            except Exception:  # noqa: BLE001  one job's fit failing never stops the others; fit() says it when asked
                log.exception("fit for %s", job_id)

    def forget_fits(self, jid: str | None = None) -> None:
        """The fits made for one job (deleted for good), or for every job (a backup restored in the workspace's place)."""
        with self._fit_lock:  # never while a fit is read or made
            if jid is None:  # every job's
                self._fit_cache.clear()
            else:  # one job's, for every posting and profile
                self._fit_cache = {k: v for k, v in self._fit_cache.items() if k[0] != jid}

    def _fit_make(self, key: tuple, posting: str) -> dict:
        """A fit made now, for a cache key."""
        prof = self.facts.profile()  # the profile now
        return compute(prof, posting, evmap=self.facts.evidence(), cands=self.facts.candidates(), profile_key=key[2]) if posting.strip() and prof.get("roles") else \
            {"score": 0, "by": "words", "counts": {"strong": 0, "weak": 0, "none": 0}, "lines": [], "gaps": [], "reason": "no_profile" if posting.strip() else "no_posting"}

    def _fit_for(self, key: tuple, job_id: str, posting: str) -> dict:
        """The fit for a cache key (the caller holds the lock)."""
        if key not in self._fit_cache:  # not computed for this pair yet
            self._fit_cache = {k: v for k, v in self._fit_cache.items() if k[0] != job_id}  # older fits of this job go
            self._fit_cache[key] = self._fit_make(key, posting)
        return self._fit_cache[key]  # the same answer while nothing changed
