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

import sys  # the engine on the import path
import threading  # one plan at a time
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules

from .facts import text_of  # noqa: E402  plain text

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
