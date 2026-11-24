"""Offerowl's API, the Trash: every source, the photo, every job and named edition, and every material of a job that the
person removed, with the day it went. Each can be put back, or deleted for good. The folders a backup's restore
kept aside beside the workspace are listed too, so they can be deleted once they are not wanted.

Taking a thing off never deletes it: undo or this list brings it back. Deleting for good is only for a thing already taken
off, and leaves nothing of it in the workspace: its files, its records, what was read from it, and its copies in the undo
steps (Workspace.scrub), so no undo can bring it back either. What stays is what the page's dialog and docs/APP.md say:
the documents and drafts already made from a file's facts and the details it filled in, copies on the Desktop, backups saved
before, the command bar's history.

    GET  /api/v1/removed                  {"rows": [...], "asides": [...]}
    POST /api/v1/removed/restore  {id}    put back: one undo step takes it off again (the photo has no undo step)
    POST /api/v1/removed/delete   {id}    deleted for good; {"all": true} for every row (an aside only by its own id)

Row ids: source:<id>, photo:<day>-<time>, job:<job> (a job or a named edition), material:<job>:<id>, aside:<folder name>.

The Trash owns none of these things: it lists them, puts them back and deletes them through the service that keeps each
(profile: the sources and the photo; applications: a job's materials; interview, agent and documents: what a job deleted
for good leaves outside its folder or in memory), and rewrites the undo steps once with the edits each owner gives.
"""
from __future__ import annotations

import contextlib  # the locks a deletion holds, as one
import os  # moves, and a working name unique to this process
import re  # ids and folder names
import shutil  # folders deleted whole
import time  # the name of a folder on its way out
from pathlib import Path  # paths

from .. import agent, applications, interview, profile  # the finished runs, a job's materials, a kit's outputs, the sources and the photo
from ...core.workspace import retried  # moves waited for on Windows

ASIDE_FILES = 100_000  # files counted for an aside's size: a folder larger than any workspace stops the count there


# ---------------------------------------------------------------- what is there


def asides(ws) -> list[Path]:
    """The folders backup.restore kept beside the workspace (<workspace>-before-restore-YYYYmmdd-HHMMSS), real folders only:
    a link of that name, or anything else beside the workspace, is never listed and never deleted."""
    root = ws.root.resolve()  # the workspace as the system names it
    name = re.compile(re.escape(root.name) + r"-before-restore-\d{8}-\d{6}")  # the one shape restore() gives them
    try:
        found = list(root.parent.iterdir())  # beside it
    except OSError:  # a parent that cannot be listed: nothing to offer
        return []
    junction = lambda p: getattr(p, "is_junction", lambda: False)()  # noqa: E731  a Windows junction (Python 3.12 and later can tell)
    return sorted(p for p in found if name.fullmatch(p.name) and not p.is_symlink() and not junction(p) and p.is_dir())


def folder_size(path: Path) -> tuple[int, bool]:
    """(bytes, whether the count stopped early) of the files under a folder, links not followed."""
    total, n = 0, 0  # bytes and files so far
    for top, dirs, files in os.walk(path):  # never into a link to a folder
        for f in files:
            n += 1
            if n > ASIDE_FILES:  # larger than any workspace: said as "at least"
                return total, True
            with contextlib.suppress(OSError):  # a file gone meanwhile counts nothing
                total += os.lstat(os.path.join(top, f)).st_size
    return total, False


def _row(rid: str, kind: str, name: str, at: str, size: int, note: dict, owner: dict | None = None, back: bool = True) -> dict:
    """One row of the list, with the routes that put it back and delete it for good, as the Library's rows name theirs."""
    out = {"id": rid, "kind": kind, "name": name, "at": at, "size": size, "note": note, "owner": owner,
           "delete": {"path": "/api/v1/removed/delete", "body": {"id": rid}}}  # every row can go for good
    if back:  # an aside has no put-back: it is a whole workspace
        out["restore"] = {"path": "/api/v1/removed/restore", "body": {"id": rid}}
    return out


def listing(api) -> dict:
    """Everything taken off, the most recently removed first, and the asides (oldest first, as their names sort)."""
    out = []  # the asides
    for p in asides(api.ws):
        size, more = folder_size(p)  # walked: only this read does it
        stamp = p.name[-15:]  # YYYYmmdd-HHMMSS, as restore() named it
        out.append(_row("aside:" + p.name, "aside", p.name, f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]}", size,
                        {"more": more}, back=False))
    return {"rows": rows(api), "asides": out}


def rows(api) -> list[dict]:
    """Everything taken off, the most recently removed first."""
    ws = api.ws
    out: list[dict] = []  # what the Removed list shows
    for m, facts in profile.removed_sources(ws):  # brought in for the profile, each with the facts a put-back brings
        name = str(m.get("name") or m.get("file") or "")
        out.append(_row("source:" + m["id"], "source", name, str(m.get("removed_at") or ""), int(m.get("size") or 0),
                         {"facts": facts, "ext": Path(name).suffix.lower().lstrip("."), "example": bool(m.get("example"))}))
    for pid, ph in profile.kept_photos(ws):  # each photo removed, under its own name
        stamp = pid[6:]  # YYYYmmdd-HHMMSS: the moment it went
        out.append(_row(pid, "photo", "photo" + ph.suffix, f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}", ph.stat().st_size, {"ext": ph.suffix.lstrip(".")}))
    for kind in ("job", "edition"):  # off the board, and the named editions taken off
        for st in ws.jobs(removed=True, kind=kind):
            if st.get("removed"):
                out.append(_row("job:" + st["id"], kind, str(st.get("company") or st.get("role") or st.get("name") or st["id"]),
                                 str(st.get("removed_at") or ""), 0, {"role": str(st.get("role") or "") if kind == "job" else "",
                                                                      "stage": st.get("stage") if kind == "job" else None}))
    for st in ws.jobs():  # a job's materials taken off (a job taken off keeps its own: they come back with it)
        with api.gone_meanwhile(st["id"]):  # deleted for good while this was read: left out
            days = applications.material_removed_days(ws, st["id"])  # the day each went
            for r in applications.removed_materials(ws, st["id"]):
                copy = re.search(r" \((\d+)\)\.\w+$", str(r.get("file") or ""))  # a second file of one name is kept as "name (2).pdf"
                out.append(_row(f"material:{st['id']}:{r['id']}", "material", str(r.get("name") or r.get("title") or ""), days.get(r["id"], ""),
                                 int(r.get("size") or 0), {"ext": r.get("kind"), **({"copy": int(copy.group(1))} if copy else {})},  # which copy, when one name came several times
                                 {"job": st["id"], "company": st.get("company") or st.get("role") or st["id"]}))
    out.sort(key=lambda r: r["at"] or "", reverse=True)  # the newest removal first; one made before the day was kept goes last
    return out


def counts(api) -> dict:
    """How many things the Trash holds, by kind and in all, for the state: the page's discovery lines and the Library's key
    read these without fetching the list. The asides are not counted: they were never taken off."""
    ws = api.ws
    out = {"sources": sum(1 for m in ws.all_materials() if isinstance(m, dict) and m.get("removed")),  # files brought in for the profile
           "photo": len(profile.kept_photos(ws)), "jobs": 0, "editions": 0, "materials": 0}  # the photos; the rest below
    for kind, key in (("job", "jobs"), ("edition", "editions")):  # jobs and named editions
        for st in ws.jobs(removed=True, kind=kind):
            if st.get("removed"):
                out[key] += 1
            elif kind == "job":  # a job on the board: its materials taken off
                with api.gone_meanwhile(st["id"]):  # deleted for good while this was read: nothing of it counts
                    out["materials"] += len(applications.removed_materials(ws, st["id"]))
    out["all"] = sum(out.values())  # the Library's key
    return out


# ---------------------------------------------------------------- putting back


def restore(api, rid: str) -> dict:
    """Put one thing back where it was. Returns what came back; "read_again" when a source comes back to be read again."""
    kind, _, rest = str(rid or "").partition(":")
    if kind == "photo":
        return profile.photo_back(api, str(rid))
    if kind == "source" and profile.SOURCE_ID.fullmatch(rest):
        return profile.source_back(api, rest)
    if kind == "job":
        return _job_back(api, rest)
    if kind == "material":
        jid, _, mid = rest.rpartition(":")  # the job's id has no colon
        _listed_job(api, jid)  # a job on the board: a removed or deleted one's materials are not listed on their own
        return {"material": applications.put_material_back(api.ws, jid, mid)}
    raise ValueError("removed")  # a made-up id


def _listed_job(api, jid: str) -> None:
    """Refuse, as a thing no longer in the Trash, a job that is gone or in the Trash itself (its materials come back with it)."""
    try:
        api.need_job({"job": jid})  # on the board
    except ValueError as exc:  # deleted for good, removed, or never there
        raise ValueError("removed") from exc


def _card(ws, jid: str) -> dict:
    """A job's card when it is in the Trash; refused as "removed" when it is on the board, deleted for good or never there."""
    try:
        st = ws.job(jid)  # a made-up or deleted id is refused by job_dir
    except ValueError as exc:
        raise ValueError("removed") from exc
    if not st or not st.get("removed"):  # on the board, or no card
        raise ValueError("removed")
    return st


def _job_back(api, jid: str) -> dict:
    """A job back on the board, or a named edition back among the editions. One undo step takes it off again."""
    ws = api.ws
    with ws.lock:  # looked up and changed in one step
        st = _card(ws, jid)  # in the Trash
        with ws.change({"code": "undo_put_back", "company": st.get("company") or st.get("role") or st.get("name")}, ws.job_files(jid)):
            st.pop("removed", None)  # on the board again
            st.pop("removed_at", None)  # with no day of removal
            ws.save_job(st)
    return {"job": jid}


# ---------------------------------------------------------------- deleting for good


def _busy(api) -> None:
    """Refuse while a task runs: it could write what is being deleted back (a reading adds facts, a build writes into its job)."""
    if any(t.get("state") == "running" for t in api.tasks.state().values()):
        raise ValueError("busy")  # the page says to wait for the work in progress


def _source(api, mid: str, plan: list) -> dict:
    """Delete a source for good (the caller holds the locks), through the profile, which owns its files. Adds to plan the edit
    the undo steps need: the profile's for its files, then its words out of the steps' labels. Returns what went."""
    words, files = profile.purge_source(api, mid)  # its file, its record, its facts' states and edits, where it filled a detail

    def edit(step: dict) -> bool:  # one undo step without it
        hit = files(step)  # its files first, as the profile gives them
        return _blank(step, words, ("title",)) or hit
    plan.append(edit)
    return {"source": mid}


def _blank(step: dict, words: set, keys: tuple) -> bool:
    """A step's label with these words taken out of the named fields. Whether it changed."""
    label, hit = step.get("label"), False
    if isinstance(label, dict):
        for k in keys:
            if label.get(k) in words:  # the words of a thing deleted for good
                label[k] = ""  # the step says what kind of change it was, without them
                hit = True
    return hit


def _job(api, jid: str, plan: list, after: list) -> dict:
    """Delete a job or a named edition for good (the caller holds the locks and stopped its kit server): its folder with
    everything in it, and whatever names it. Adds to plan the edit the undo steps need, and to after what is done outside the locks."""
    ws, t = api.ws, api.tasks
    st = _card(ws, jid)  # in the Trash
    names = {str(x) for x in (st.get("company"), st.get("role"), st.get("name")) if x}  # how undo labels name it
    for other in ws.jobs(removed=True) + ws.jobs(removed=True, kind="edition"):  # a name another job still has is not its own
        if other["id"] != jid:
            names -= {str(x) for x in (other.get("company"), other.get("role"), other.get("name")) if x}
    path = ws.job_dir(jid)  # its folder, named before its id is refused
    dest = ws.path(".gone", f"{jid}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}")  # out of jobs/ in one move
    if path.is_dir():
        dest.parent.mkdir(exist_ok=True)
        try:
            retried(os.replace, path, dest)  # the board and every list stop seeing it at once
        except OSError as exc:  # a file of it held open (Windows): nothing has changed yet
            raise ValueError("delete_failed") from exc
    ws.gone.add(jid)  # from here a late request or thread is refused, and the id is never given again in this run
    if ws.prefs().get("job") == jid:  # the job in view
        ws.set_prefs(job=None)  # the newest job is in view instead
    agent.forget_runs(ws, jid)  # the autopilot's finished runs that name it

    def edit(step: dict) -> bool:  # one undo step without it
        mine = [rel for rel in step["files"] if rel.startswith(f"jobs/{jid}/")]  # its files
        for rel in mine:
            del step["files"][rel]
        hit = _blank(step, names, ("company",)) or bool(mine)
        label = step.get("label") if isinstance(step.get("label"), dict) else {}
        if mine and label.get("title"):  # what is left of a step that was about it does not quote its words
            hit = _blank(step, {label["title"]}, ("title",)) or hit
        return hit
    plan.append(edit)

    def later() -> None:  # outside the locks: the folder's files, the kit's outputs, the engine's working copies, the memory
        shutil.rmtree(dest, ignore_errors=True)  # a file held open stays for Workspace.sweep
        interview.drop_outputs(ws, jid)  # the interview kit's map and deck
        api.fits.forget_fits(jid)  # its fits
        t.forget_live(jid)  # its live pages and pictures
        t.forget_tasks_of(jid)  # what its tasks said
    after.append(later)
    return {"job": jid}


def _material(api, jid: str, mid: str, plan: list) -> dict:
    """Delete a job's material for good (the caller holds the locks): through the applications service, then the undo steps."""
    ws = api.ws
    rec = applications.purge_material(ws, jid, mid)  # the file, its pictures, its record
    titles = {rec.get("title")} - {None, ""}  # how undo labels name it
    for st in ws.jobs(removed=True):  # a title another material still has is not its own
        titles -= {r.get("title") for r in applications.material_records(ws, st["id"])}
    files = applications.material_undo_edit(jid, mid)  # its id out of the steps' copies of the job's lists, as the materials keep them

    def edit(step: dict) -> bool:  # one undo step without it
        hit = files(step)  # its files first
        return _blank(step, titles, ("title",)) or hit
    plan.append(edit)
    return {"material": mid}


def _photo(api, pid: str, after: list) -> dict:
    """Delete a removed photo for good, through the profile, and later the panel's small copy of it in memory."""
    after.append(profile.purge_photo(api.ws, pid))  # the file goes now (held open: said, and kept); its small copy outside the locks
    return {"photo": pid}


def _aside(api, name: str) -> dict:
    """Delete a folder a restore kept aside, whole. Only one listed by asides(), and never while a restore runs."""
    found = next((p for p in asides(api.ws) if p.name == name), None)
    if not found:  # not one of them
        raise ValueError("removed")
    if not api.restoring.acquire(blocking=False):  # a restore is moving folders beside the workspace now
        raise ValueError("busy")
    try:
        shutil.rmtree(found, ignore_errors=True)  # whole; a file held open stays
    finally:
        api.restoring.release()
    if found.exists():  # something stayed (a file in use on Windows): said, and listed again
        raise ValueError("delete_failed")
    return {"aside": name}


def delete(api, rid: str | None = None, every: bool = False) -> dict:
    """Delete one thing taken off for good, or every one (every=True; the asides only one by one, by their own id). The undo
    steps are rewritten once, whatever went. Returns {"deleted": [ids], "steps": undo steps rewritten}."""
    rid = str(rid or "")
    if not every and rid.startswith("aside:"):  # outside the workspace: none of the rest applies
        return {"deleted": [_aside(api, rid[6:])["aside"]], "steps": 0}
    ws, t = api.ws, api.tasks
    ids = [r["id"] for r in rows(api)] if every else [rid]  # what goes
    if not every and ids[0].partition(":")[0] not in ("source", "job", "material", "photo"):
        raise ValueError("removed")  # a made-up id
    risky = any(i.startswith(("source:", "job:")) for i in ids)  # a reading could add its facts back, a task write into its job
    if risky:
        _busy(api)
    for i in list(ids):  # each job's kit server stops first: it reads the folder that goes
        if i.startswith("job:"):
            jid = i[4:]
            try:
                _card(ws, jid)  # in the Trash: one on the board, or deleted already, is never touched
            except ValueError:  # put back or deleted since the list was read
                if not every:  # asked for by its own key: said
                    raise
                ids.remove(i)  # emptying the trash goes on with the rest
                continue
            for lang in ("ko", "en"):  # the engine's working copies of its editions, while its folder still says what they were
                with contextlib.suppress(OSError):
                    t._clean_engine(jid, lang, t.build_dir(jid, lang))
            t.let_kit_go(jid)  # its kit server, stopped once what was on its way is answered
            with contextlib.suppress(ValueError):
                t.forget_own(jid)  # its own edition's facts, read once
    plan, after, done = [], [], []  # the steps' edits, what is done outside the locks, the ids that went
    steps = 0  # undo steps rewritten
    try:
        with applications.MATERIALS_LOCK, ws.lock:  # no page picture is being drawn, and no other write meets these (in this order, as previews take them)
            if risky:  # a task started while the servers were stopped: looked at again, now that nothing can start in between
                _busy(api)
            try:
                for i in ids:
                    kind, _, rest = i.partition(":")
                    try:
                        if kind == "photo":
                            _photo(api, i, after)
                        elif kind == "source" and profile.SOURCE_ID.fullmatch(rest):
                            _source(api, rest, plan)
                        elif kind == "job":
                            _job(api, rest, plan, after)
                        elif kind == "material":
                            jid, _, mid = rest.rpartition(":")  # the job's id has no colon
                            _listed_job(api, jid)  # a job on the board
                            _material(api, jid, mid, plan)
                        else:  # a made-up id
                            raise ValueError("removed")
                    except ValueError as exc:  # put back or deleted meanwhile: emptying the list goes on with the rest
                        if every and str(exc) == "removed":
                            continue
                        raise
                    done.append(i)
            finally:  # whatever went, its copies in the undo steps go too, even when a later one was refused
                if plan:
                    steps = ws.scrub(lambda step: any([edit(step) for edit in plan]))  # every edit on every step: a list, so none is skipped
                if any(i.startswith("source:") for i in done):  # facts went: the profile follows
                    api.facts.rebuild()
                    profile.stale_translation(api)  # and an English profile made from the one before goes
    finally:  # outside the locks: a build waiting for the workspace never meets a deletion waiting for the build
        for job in after:
            job()
        ws.sweep()  # what an earlier deletion could not delete
    return {"deleted": done, "steps": steps}
