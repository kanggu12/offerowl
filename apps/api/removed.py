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
"""
from __future__ import annotations

import contextlib  # the locks a deletion holds, as one
import json  # the undo steps' copies of files
import os  # moves, and a working name unique to this process
import re  # ids and folder names
import shutil  # folders deleted whole
import time  # the name of a folder on its way out
from pathlib import Path  # paths

from . import materials as M  # a job's own materials
from .facts import FACT_FILES  # the files a fact change touches
from .workspace import dump_json, read_json, retried, write_json  # files, their one spelling, moves waited for

SOURCE_ID = re.compile(r"m\d{1,9}")  # a source's id, as Workspace.add_material makes them
PHOTO = re.compile(r"removed-photo-(\d{8}-\d{6}(?:-\d{1,3})?)\.(jpg|png)")  # a removed photo's file, as app.remove_photo names it
REBUILT = ("profile/profile.json", "profile/evidence.json")  # made again from the fact files after every undo (routes.py): no step needs its copy
ASIDE_FILES = 100_000  # files counted for an aside's size: a folder larger than any workspace stops the count there


# ---------------------------------------------------------------- what is there


def kept_photos(ws) -> list[tuple[str, Path]]:
    """The photos the person removed, kept aside by app.remove_photo, newest first: (id in the Trash, file)."""
    found = []  # (stamp, file)
    folder = ws.path("profile")  # where they wait
    for f in folder.iterdir() if folder.is_dir() else []:
        m = PHOTO.fullmatch(f.name)  # only the names remove_photo gives
        if m and f.is_file() and not f.is_symlink():
            found.append((m.group(1), f))
    return [("photo:" + stamp, f) for stamp, f in sorted(found, reverse=True)]  # the stamps sort as the moments they name


def kept_photo(ws, pid: str) -> Path | None:
    """One removed photo by its id in the Trash, or None."""
    return next((f for i, f in kept_photos(ws) if i == pid), None)


def stash_file(ws, mid: str) -> Path:
    """What a source took along when it was taken off (app.remove_material): its facts, the imported profile it was, the
    example's details."""
    return ws.path("sources", "removed", f"{mid}.json")


def removed_source(ws, mid: str) -> dict | None:
    """A source's record when it is taken off and not deleted for good, else None."""
    return next((m for m in ws.all_materials() if isinstance(m, dict) and m.get("id") == mid and m.get("removed")), None)


def of(c, mid: str) -> bool:
    """Was this fact read from the source mid?"""
    return isinstance(c, dict) and isinstance(c.get("source"), dict) and c["source"].get("material") == mid


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
    for m in ws.all_materials():  # brought in for the profile
        if not (isinstance(m, dict) and m.get("removed") and SOURCE_ID.fullmatch(str(m.get("id") or ""))):  # on the list, or no record
            continue
        stash = read_json(stash_file(ws, m["id"]), None)  # what it took along
        facts = len(stash.get("candidates") or []) if isinstance(stash, dict) else int(m.get("facts") or 0)  # the facts a put-back brings
        name = str(m.get("name") or m.get("file") or "")
        out.append(_row("source:" + m["id"], "source", name, str(m.get("removed_at") or ""), int(m.get("size") or 0),
                         {"facts": facts, "ext": Path(name).suffix.lower().lstrip("."), "example": bool(m.get("example"))}))
    for pid, ph in kept_photos(ws):  # each photo removed, under its own name
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
            days = M.removed_days(ws, st["id"])  # the day each went
            for r in M.removed_records(ws, st["id"]):
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
           "photo": len(kept_photos(ws)), "jobs": 0, "editions": 0, "materials": 0}  # the photos; the rest below
    for kind, key in (("job", "jobs"), ("edition", "editions")):  # jobs and named editions
        for st in ws.jobs(removed=True, kind=kind):
            if st.get("removed"):
                out[key] += 1
            elif kind == "job":  # a job on the board: its materials taken off
                with api.gone_meanwhile(st["id"]):  # deleted for good while this was read: nothing of it counts
                    out["materials"] += len(M.removed_records(ws, st["id"]))
    out["all"] = sum(out.values())  # the Library's key
    return out


# ---------------------------------------------------------------- putting back


def restore(api, rid: str) -> dict:
    """Put one thing back where it was. Returns what came back; "read_again" when a source comes back to be read again."""
    kind, _, rest = str(rid or "").partition(":")
    if kind == "photo":
        return _photo_back(api, str(rid))
    if kind == "source" and SOURCE_ID.fullmatch(rest):
        return _source_back(api, rest)
    if kind == "job":
        return _job_back(api, rest)
    if kind == "material":
        jid, _, mid = rest.rpartition(":")  # the job's id has no colon
        _listed_job(api, jid)  # a job on the board: a removed or deleted one's materials are not listed on their own
        return {"material": M.put_back(api.ws, jid, mid)}
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


def _from_steps(ws, mid: str) -> list[dict]:
    """A source's facts as the newest undo step that still holds them has them (a source taken off before its facts were
    kept aside), or []."""
    for snap in ws.snapshots("sources/candidates.json"):  # newest first
        got = [c for c in (snap.get("kept") or []) if of(c, mid)] if isinstance(snap, dict) else []
        if got:
            return got
    return []


def _source_back(api, mid: str) -> dict:
    """A source back on the list with its facts as they were, and the details and the imported profile it took along. When
    they cannot come back whole (taken off before they were kept aside and no undo step holds them, or another imported
    profile is in its place now) it comes back unread, to be read again."""
    ws, facts = api.ws, api.facts
    with ws.lock:  # one writer
        rec = removed_source(ws, mid)
        if not rec:  # back already, deleted, or never there
            raise ValueError("removed")
        stash = read_json(stash_file(ws, mid), None)  # what it took along
        took = stash if isinstance(stash, dict) else {}  # {} for a source taken off by an older Offerowl, or an odd file
        if took:  # kept when it was taken off
            cands, whole = [c for c in took.get("candidates") or [] if isinstance(c, dict)], True
        else:  # the undo steps may still hold its facts
            cands = _from_steps(ws, mid)
            whole = bool(cands) or not rec.get("facts")  # nothing to bring back is whole too
        if whole and not cands and rec.get("facts"):  # it gave facts, and none came along (another profile file had replaced them)
            whole = False  # read again, it gives them anew
        base = took.get("base")  # the imported profile it was
        if any(c.get("origin") == "profile" for c in cands) and not (isinstance(base, dict) and facts.base() is None):  # its profile is gone, or another one is in its place
            whole = False
        # one undo takes it off again: the stash comes back with it
        with ws.change({"code": "undo_put_back", "title": str(rec.get("name") or "")[:60]}, FACT_FILES + [f"sources/removed/{mid}.json"]):
            if whole:
                now = read_json(ws.path("sources", "candidates.json"), {})  # the list as it is
                kept = [c for c in now.get("kept") or [] if isinstance(c, dict)]
                have = {c.get("cid") for c in kept}  # a fact that is there already stays once
                write_json(ws.path("sources", "candidates.json"), {"kept": kept + [c for c in cands if c.get("cid") not in have],
                                                                    "dropped": now.get("dropped") or []})
                if isinstance(base, dict):  # an imported profile: its base comes back with its facts
                    write_json(ws.path("profile", "base.json"), base)
                det = facts.details()  # "Your details"
                src = det.get("_src") if isinstance(det.get("_src"), dict) else {}
                gave = took.get("details") if isinstance(took.get("details"), dict) else {}  # the example's fields
                where = took.get("src") if isinstance(took.get("src"), dict) else {}  # and where they came from
                for k, v in gave.items():  # back where the person left them empty
                    if v and not det.get(k):
                        det[k] = v
                        if k in where:
                            src[k] = where[k]
                if gave:
                    det["_src"] = src
                    write_json(ws.path("profile", "details.json"), det)
                ws.update_material(mid, removed=None, removed_at=None)  # on the list again, as it was read
            else:  # its facts are not there to bring back: read again, it gives them anew
                ws.update_material(mid, removed=None, removed_at=None, state="new", facts=0)
            stash_file(ws, mid).unlink(missing_ok=True)  # used
            facts.rebuild()  # the profile follows
    return {"source": mid, "read_again": not whole}


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


def _photo_back(api, pid: str) -> dict:
    """A removed photo, back on the resume's details. A photo added since is not lost: it goes to the Trash under a name of
    its own. Each move leaves every file under a name the Trash lists, so a move that fails hides nothing."""
    ws = api.ws
    with ws.lock:  # one writer
        kept = kept_photo(ws, pid)
        if not kept:  # back already, deleted, or never there
            raise ValueError("removed")
        api.remove_photo(keep=True)  # the photo there now, if any, goes to the Trash first
        dest = ws.path("profile", "photo" + kept.suffix)  # photo.jpg or photo.png
        retried(os.replace, kept, dest)  # then this one takes its place
        os.utime(dest)  # a new date: the page draws it afresh
    return {"photo": pid}


# ---------------------------------------------------------------- deleting for good


def _busy(api) -> None:
    """Refuse while a task runs: it could write what is being deleted back (a reading adds facts, a build writes into its job)."""
    if any(t.get("state") == "running" for t in api.tasks.state().values()):
        raise ValueError("busy")  # the page says to wait for the work in progress


def _held(cands: list) -> bool:
    """Do these facts include an imported profile's?"""
    return any(isinstance(c, dict) and c.get("origin") == "profile" for c in cands)


def _clean_source_data(rel: str, data, mid: str, stored: str, cids: set) -> tuple[object, bool]:
    """One fact file's data without a source: its facts, its record of files dropped by the reading, what was decided and
    edited about its facts, and where "Your details" took a field from it (the field's value stays: the person kept it).
    Returns (data, changed)."""
    if rel == "sources/materials.json" and isinstance(data, list):  # its record
        new = [m for m in data if not (isinstance(m, dict) and m.get("id") == mid)]
    elif rel == "sources/candidates.json" and isinstance(data, dict):  # its facts, and the reading's note of its file
        dropped = [d for d in data.get("dropped") or [] if not of(d, mid) and not (isinstance(d, dict) and re.split(r"[\\/]", str(d.get("file") or ""))[-1] == stored)]
        new = {**data, "kept": [c for c in data.get("kept") or [] if not of(c, mid)], "dropped": dropped}
    elif rel in ("sources/review.json", "sources/edits.json") and isinstance(data, dict):  # kept, dropped or edited
        new = {k: v for k, v in data.items() if k not in cids}
    elif rel == "profile/details.json" and isinstance(data, dict) and isinstance(data.get("_src"), dict):  # where a field came from
        new = {**data, "_src": {k: v for k, v in data["_src"].items() if not (isinstance(v, dict) and v.get("material") == mid)}}
    else:  # nothing of it here
        return data, False
    return new, new != data


def _source(api, mid: str, plan: list) -> dict:
    """Delete a source for good (the caller holds the locks): its file, its record, what it took along, its facts' states and
    edits, and where it filled a detail. Adds to plan the edit the undo steps need. Returns what went."""
    ws = api.ws
    items = ws.all_materials()  # every record
    rec = next((m for m in items if isinstance(m, dict) and m.get("id") == mid and m.get("removed")), None)
    if not rec:  # back on the list, deleted already, or never there
        raise ValueError("removed")
    stored = Path(str(rec.get("file") or "")).name  # its file's name in sources/
    stash = read_json(stash_file(ws, mid), None)  # what it took along
    mine = {c.get("cid"): c for c in (stash.get("candidates") or [] if isinstance(stash, dict) else []) if isinstance(c, dict)}  # its facts
    for snap in ws.snapshots("sources/candidates.json"):  # and every copy of them the undo steps hold
        for c in (snap.get("kept") or []) if isinstance(snap, dict) else []:
            if of(c, mid):
                mine.setdefault(c.get("cid"), c)
    live = api.facts.candidates()  # the facts listed now (another file may give the same fact: its state stays)
    cids = {cid for cid in mine if cid} - {c.get("cid") for c in live}
    words = {str(c.get("title") or c.get("statement") or "")[:60] for c in mine.values()} | {str(rec.get("name") or "")[:60]}  # how undo labels name them
    words -= {str(c.get("title") or c.get("statement") or "")[:60] for c in live}  # words another fact still has are not its own
    words.discard("")
    gone(ws.material_path(rec))  # the file itself, first: held open elsewhere, nothing else changes
    gone(stash_file(ws, mid))  # and what it took along (its facts' words), before any record changes
    write_json(ws.path("sources", "materials.json"), [m for m in items if not (isinstance(m, dict) and m.get("id") == mid)])  # its record
    high = ws.prefs().get("sources_high")  # its id is never given again (Workspace.add_material)
    ws.set_prefs(sources_high=max(int(mid[1:]), high if isinstance(high, int) else 0))
    for rel in ("sources/candidates.json", "sources/review.json", "sources/edits.json", "profile/details.json"):  # the fact files as they are now
        data = read_json(ws.root / rel, None)
        if data is not None:
            new, changed = _clean_source_data(rel, data, mid, stored, cids)
            if changed:
                write_json(ws.root / rel, new)
    api.tasks.read_texts.pop(mid, None)  # the text its reading found, kept in memory for a run

    def edit(step: dict) -> bool:  # one undo step without it
        files, hit = step["files"], False
        for rel in list(files):
            if rel in REBUILT or rel == f"sources/removed/{mid}.json":  # made again after any undo, or its own stash
                del files[rel]
                hit = True
                continue
            text = files[rel]
            if not text or rel not in FACT_FILES:  # a file it never was in
                continue
            try:
                data = json.loads(text)
            except ValueError:  # a copy of a broken file: no undo writes it as data
                continue
            if rel == "sources/candidates.json" and isinstance(data, dict) and _held([c for c in data.get("kept") or [] if of(c, mid)]) \
                    and files.get("profile/base.json") is not None:  # it was the imported profile then: that base is its own
                files["profile/base.json"] = None
                hit = True
            new, changed = _clean_source_data(rel, data, mid, stored, cids)
            if changed:
                files[rel] = dump_json(new)
                hit = True
        made = step.get("made")
        if isinstance(made, dict):  # the records a step made
            for rel, ids in made.items():
                if isinstance(ids, list) and mid in ids:
                    made[rel] = [i for i in ids if i != mid]
                    hit = True
        return _blank(step, words, ("title",)) or hit
    plan.append(edit)
    return {"source": mid}


def gone(f: Path) -> None:
    """Delete one file, or refuse with delete_failed when the system will not (another program holds it open on Windows), so
    a deletion stops before it has changed anything else."""
    try:
        retried(lambda: f.unlink(missing_ok=True))  # Windows lets go of a file a scanner holds in a moment
    except OSError as exc:  # its words hold the path: the page gets the code only
        raise ValueError("delete_failed") from exc


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
    runs = ws.path("out", "runs.json")  # the autopilot's finished runs
    kept = [r for r in read_json(runs, []) if isinstance(r, dict) and r.get("job") != jid] if runs.is_file() else None
    if kept is not None:
        write_json(runs, kept)

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
        shutil.rmtree(ws.path("out", "interview", jid), ignore_errors=True)  # the interview kit's map and deck
        with api._fit_lock:
            api._fit_cache = {k: v for k, v in api._fit_cache.items() if k[0] != jid}  # its fits
        for memo in (t.live_decks, t.live_figures):  # its live pages and pictures
            for k in [k for k in list(memo) if k[0] == jid]:
                memo.pop(k, None)
        with t.state_lock:  # what its tasks said
            for k in [k for k in t.tasks if k.endswith(":" + jid)]:
                t.tasks.pop(k, None)
    after.append(later)
    return {"job": jid}


def _material(api, jid: str, mid: str, plan: list) -> dict:
    """Delete a job's material for good (the caller holds the locks): materials.purge, then the undo steps."""
    ws = api.ws
    rec = M.purge(ws, jid, mid)  # the file, its pictures, its record
    titles = {rec.get("title")} - {None, ""}  # how undo labels name it
    for st in ws.jobs(removed=True):  # a title another material still has is not its own
        titles -= {r.get("title") for r in M.records(ws, st["id"])}
    rels = (f"jobs/{jid}/materials/removed.json", f"jobs/{jid}/materials/removed_at.json")

    def edit(step: dict) -> bool:  # one undo step without it
        hit = False
        for rel in rels:
            text = step["files"].get(rel)
            try:
                data = json.loads(text) if text else None
            except ValueError:
                continue
            new = [x for x in data if x != mid] if isinstance(data, list) else {k: v for k, v in data.items() if k != mid} if isinstance(data, dict) else data
            if new != data:
                step["files"][rel] = dump_json(new)
                hit = True
        return _blank(step, titles, ("title",)) or hit
    plan.append(edit)
    return {"material": mid}


def _photo(api, pid: str, after: list) -> dict:
    """Delete a removed photo for good, and the panel's small copy of it in memory."""
    from . import photo  # the small copies
    kept = kept_photo(api.ws, pid)
    if not kept:
        raise ValueError("removed")
    gone(kept)  # held open elsewhere: said, and kept

    def later() -> None:
        with photo._thumbs_lock:
            photo._thumbs.clear()  # the next look makes one of the photo there is
    after.append(later)
    return {"photo": pid}


def _aside(api, name: str) -> dict:
    """Delete a folder a restore kept aside, whole. Only one listed by asides(), and never while a restore runs."""
    found = next((p for p in asides(api.ws) if p.name == name), None)
    if not found:  # not one of them
        raise ValueError("removed")
    if not api._restoring.acquire(blocking=False):  # a restore is moving folders beside the workspace now
        raise ValueError("busy")
    try:
        shutil.rmtree(found, ignore_errors=True)  # whole; a file held open stays
    finally:
        api._restoring.release()
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
            with t.kit_lock:
                got = t.kit_srvs.pop(jid, None)
            if got:
                t._stop_kit_later(got[0])
            with contextlib.suppress(ValueError):
                t.forget_own(jid)  # its own edition's facts, read once
    plan, after, done = [], [], []  # the steps' edits, what is done outside the locks, the ids that went
    steps = 0  # undo steps rewritten
    try:
        with M.LOCK, ws.lock:  # no page picture is being drawn, and no other write meets these (in this order, as previews take them)
            if risky:  # a task started while the servers were stopped: looked at again, now that nothing can start in between
                _busy(api)
            try:
                for i in ids:
                    kind, _, rest = i.partition(":")
                    try:
                        if kind == "photo":
                            _photo(api, i, after)
                        elif kind == "source" and SOURCE_ID.fullmatch(rest):
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
                    stale_translation(api)
    finally:  # outside the locks: a build waiting for the workspace never meets a deletion waiting for the build
        for job in after:
            job()
        ws.sweep()  # what an earlier deletion could not delete
    return {"deleted": done, "steps": steps}


def stale_translation(api) -> None:
    """The English profile, when it was made from a profile that is no longer the one there is: it may hold the words of
    facts deleted for good, and no edition uses it (tasks.english_profile)."""
    t = api.tasks
    f = api.ws.path("profile", "profile.en.json")
    if f.is_file() and t.profile_lang() != "en" and t.english_profile() is None:  # a translation of another profile
        f.unlink(missing_ok=True)
