"""What the person does with the facts, as the panel's keys do it: one fact kept, dropped, edited or put back, every fact
still to confirm kept at once, a fact typed, the details typed (each one undo step); and what the page draws of them: the
facts' counts and a stamp of their rows, the profile's parts beside them, and where the first run stands."""
from __future__ import annotations

import hashlib  # the rows' stamp
import json  # the rows' text, for the stamp
import time  # when the first run began

from ...core.workspace import write_json  # files
from .facts import DETAIL_KEYS, FACT_FILES, pick, text_of  # the fields "Your details" holds, the files a fact change touches, a field in one language, plain text


def fact(api, req: dict) -> None:
    """Keep, drop, edit or put back one fact."""
    cid, act = str(req.get("cid") or ""), req.get("action")  # which and what
    known = {c["cid"]: c for c in api.facts.candidates()}  # every fact
    if cid not in known or act not in ("keep", "drop", "edit", "reset"):  # only a listed fact and a known action
        raise ValueError("fact")  # a stale page or a made-up request
    label = {"code": f"undo_{act}", "title": (known[cid].get("title") or known[cid].get("statement") or "")[:60]}  # the undo button's words
    if act == "edit":  # the fact as it would read after the edit: a title or a statement must stay
        fields = req.get("fields") or {}
        after = {**known[cid], **(api.facts.edits().get(cid) or {}), **(fields if isinstance(fields, dict) else {})}
        if not str(after.get("title") or "").strip() and not str(after.get("statement") or "").strip():
            raise ValueError("fact_empty")  # a blank fact is never saved
    with api.ws.change(label, FACT_FILES):  # one undo step
        if act == "edit":  # their own wording of the fact
            api.facts.set_edit(cid, req.get("fields") or {})  # their version
            api.facts.set_status(cid, "accepted")  # an edited fact is kept
        else:  # keep, drop or put back
            api.facts.set_status(cid, {"keep": "accepted", "drop": "rejected", "reset": None}[act])  # None: to confirm again
        api.facts.rebuild()  # the profile follows


def keep_all(api, material: str | None = None) -> int:
    """Keep every fact still to confirm, or only those of one material (the example's, kept for a first look while the
    person's own facts wait for their review). Returns how many."""
    st = api.facts.status()  # states
    todo = [c["cid"] for c in api.facts.candidates() if c["cid"] not in st  # still to confirm
            and (material is None or (c.get("source") or {}).get("material") == material)]  # of that material, when one is named
    with api.ws.change({"code": "undo_keep_all", "n": len(todo)}, FACT_FILES):  # one undo takes them all back
        for cid in todo:  # each fact nobody decided on yet
            st[cid] = "accepted"  # kept
        write_json(api.ws.path("sources", "review.json"), st)  # one write for all of them
        api.facts.rebuild()  # the profile follows
    return len(todo)  # how many, beside the new state


def add_fact(api, req: dict) -> str:
    """A fact typed by the person."""
    if not str(req.get("statement") or "").strip() and not str(req.get("title") or "").strip():  # a fact needs some words
        raise ValueError("fact_empty")  # nothing to keep (its own word: "empty" is a posting's page with no text)
    with api.ws.change({"code": "undo_typed", "title": str(req.get("title") or "")[:60]}, FACT_FILES):  # one undo step
        cid = api.facts.add_typed(req)  # listed and kept
        api.facts.rebuild()  # the profile follows
    return cid  # its id; the new state lists it


def details(api, req: dict) -> None:
    """The person's own fields (autosaved while typing: one undo step per field and pause)."""
    raw = req.get("fields") or {}
    if not isinstance(raw, dict):  # a string, a number or a list where the fields go
        raise ValueError("fields")
    if any(k not in DETAIL_KEYS or not isinstance(v, str) for k, v in raw.items()):  # a field the card has not, or a value that is no text (an email of 123):
        raise ValueError("fields")  # refused with its reason, never answered ok with nothing kept (A3-16)
    fields = dict(raw)  # text only, the card's own fields
    key = "details:" + ",".join(sorted(fields))  # one step while typing in the same field
    with api.ws.change({"code": "undo_details", "fields": sorted(fields)}, FACT_FILES, coalesce=key):  # pauses merge
        src = req.get("src") if isinstance(req.get("src"), dict) else None  # a run says which file each field came from
        api.facts.set_details(fields, src)  # saved, typed or found
        api.facts.rebuild()  # the profile follows


def facts_summary(api) -> dict:
    """The facts as the state carries them: the counts, and a stamp of the rows (a short hash of them) that changes with any
    fact's state, edit or text, so the profile view knows when to read the rows again."""
    v = api.facts.view()  # rows and counts
    return {"counts": v["counts"], "rev": hashlib.sha1(json.dumps(v["rows"], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]}


def draft_view(prof: dict) -> dict:
    """The profile's parts the pages show beside the facts (picked field by field: the page never gets the file)."""
    roles = [{"org": r.get("org"), "title": r.get("title"), "start": r.get("start"), "end": r.get("end"),  # roles, trimmed
              "projects": [{"id": p.get("id"), "title": p.get("title"), "period": p.get("period"),
                            "summary": p.get("summary")} for p in r.get("projects") or []]}
             for r in prof.get("roles") or []]  # what the profile page shows
    return {"person": {k: (prof.get("person") or {}).get(k, "") for k in ("name", "name_en", "email", "phone", "tagline")},  # who
            "headline": text_of(pick((prof.get("summary") or {}).get("headline"))), "roles": roles,  # the headline and roles
            "skills": [{"category": s.get("category", ""), "items": s.get("items") or []} for s in prof.get("skills") or []]}  # skills


def onboarding(api) -> dict:
    """Where the first run stands: done once the person reached the first resume, or had material before."""
    prefs = api.ws.prefs()  # kept with the workspace
    if "onboarded" in prefs:  # decided: finished, or the tour asked for again
        done = bool(prefs["onboarded"])  # as kept
    else:  # an older workspace with kept facts counts as done
        done = bool(api.ws.materials() and api.facts.view()["counts"]["kept"])  # it has its first resume already
    return {"done": done, "step": prefs.get("onboarding_step") or "welcome", "started": prefs.get("onboarding_started")}  # the page resumes there


def set_onboarding(api, req: dict) -> None:
    """Remember where the first run stands (not undoable: it is where you are, not what you made)."""
    values = {}  # the changed keys
    if req.get("step") in ("welcome", "language", "agent", "files", "preview"):  # only the steps the page has
        values["onboarding_step"] = req["step"]  # resumed there after a reload
        if req["step"] == "welcome" or not api.ws.prefs().get("onboarding_started"):  # the clock of the first run
            values.setdefault("onboarding_started", time.time())  # when it began
    if isinstance(req.get("done"), bool):  # finished, or the tour asked for again
        values["onboarded"] = req["done"]  # the workspace opens from now on, or the tour shows again
    if values:  # something to keep
        api.ws.set_prefs(**values)  # kept with the workspace
