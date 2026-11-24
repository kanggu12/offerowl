"""The person's sources: the files brought in for the profile, as the Library opens them and as the Trash lists them, puts
them back and deletes them for good (apps/api/services/library/removed.py asks here, never reading these files itself).

A source taken off (remove_material) waits with what it took along in sources/removed/<id>.json: its facts, the
imported profile it was, the example's details. Putting it back brings those back in one undo step; deleting it for good
leaves nothing of it in the profile's files nor in the undo steps' copies of them.
"""
from __future__ import annotations

import json  # the undo steps' copies of files, and the example's details
import re  # ids
from pathlib import Path  # paths

from ...core.workspace import dump_json, gone, now_minute, read_json, write_json  # files, their one spelling, a file deleted or refused, the minute
from .facts import FACT_FILES  # the files a fact change touches

SOURCE_ID = re.compile(r"m\d{1,9}")  # a source's id, as Workspace.add_material makes them
ROOT = Path(__file__).resolve().parents[4]  # the repository (or the app's bundle)
EXAMPLE = ROOT / "examples" / "sample_ko.json"  # the fictional person the first run can try
EXAMPLE_EN = ROOT / "examples" / "sample_full_en.json"  # the same person, written in English, for someone using the panel in English
REBUILT = ("profile/profile.json", "profile/evidence.json")  # made again from the fact files after every undo (apps/api/routes.py): no step needs its copy


def materials_now(api) -> list[dict]:
    """The person's files, each read one with the facts it holds now: the count kept when it was read falls behind once a
    fact of it is merged or deleted, and the Make view showed one more than the profile."""
    from collections import Counter  # facts per file
    held = Counter((c.get("source") or {}).get("material") for c in api.facts.candidates())
    return [{**m, "facts": held.get(m["id"], 0)} if m.get("state") == "done" else m for m in api.ws.materials()]


def add_example(api, lang: str | None = None) -> dict:
    """The fictional example person as material, read at once: the first run's "Try it with an example". In English when
    the panel is, so the first resume a person sees is one they can read."""
    example = EXAMPLE_EN if lang == "en" else EXAMPLE  # by the page's language
    made_up = {m["id"] for m in api.ws.materials() if m.get("example")}  # the example's own files, if it was added before
    st = api.facts.status()  # each fact's state
    if any(st.get(c["cid"]) == "accepted" and (c.get("source") or {}).get("material") not in made_up for c in api.facts.candidates()):
        raise ValueError("example_over_own")  # the person's own facts are kept: the made-up person would replace their profile
    rec = api.ws.add_material(example.name, example.read_bytes())  # kept in sources/ like a picked file
    api.ws.update_material(rec["id"], example=True)  # marked: a run on the person's own files takes it out first
    api.tasks.ingest([rec["id"]])  # read as a profile file: no agent
    return rec  # its record


def drop_example(api) -> int:
    """Take the fictional example out before a person's own files are read: its file, its facts and the details it
    filled in (remove_material). Returns how many example files went."""
    gone = [m["id"] for m in api.ws.materials() if m.get("example")]  # the example's files still listed
    for mid in gone:  # each, with one undo step each
        remove_material(api, mid)
    return len(gone)


def remove_material(api, mid: str) -> None:
    """Take a source and every fact read from it out of the profile. One undo brings it all back. Its file stays in
    sources/ until it is deleted for good from the Removed list (the Library's removed.py), and what it takes along waits in
    sources/removed/<id>.json (its facts, the imported profile it was, the example's details), so the list can put it
    back after later changes too."""
    rec = next((m for m in api.ws.materials() if m.get("id") == mid), None)  # listed and not taken off already
    if not rec:  # a stale page, or a made-up id
        raise ValueError("material")
    stash = {"candidates": []}  # what it takes along, for the Removed list's put-back
    # one undo brings it all back, the stash included: undone, the stash goes
    with api.ws.change({"code": "undo_remove_material", "title": str(rec.get("name") or "")[:60]}, FACT_FILES + [f"sources/removed/{mid}.json"]):
        api.ws.update_material(mid, removed=True, removed_at=now_minute())  # hidden, with the day and hour the list shows
        if rec.get("example"):  # its name, email and phone leave with it, unless the person changed them since
            from .facts import details_from  # the fields a profile file fills in
            det = api.facts.details()  # what "Your details" holds
            for doc in (EXAMPLE, EXAMPLE_EN):  # either language of the example
                for k, v in details_from(json.loads(doc.read_text(encoding="utf-8"))).items():  # each field it fills
                    if v and det.get(k) == v:  # still the example's
                        stash.setdefault("details", {})[k] = det.pop(k)  # empty again; a put-back fills it once more
                        if isinstance(det.get("_src"), dict) and k in det["_src"]:
                            stash.setdefault("src", {})[k] = det["_src"].pop(k)  # and where it came from
            write_json(api.ws.path("profile", "details.json"), det)  # saved
        cands = api.facts.candidates()  # every fact listed now
        stash["candidates"] = [c for c in cands if (c.get("source") or {}).get("material") == mid]  # its own, as they were
        if any(c.get("origin") == "profile" for c in stash["candidates"]):  # an imported profile file
            base = api.ws.path("profile", "base.json")  # the profile its facts point into
            stash["base"] = read_json(base, None)  # kept for a put-back
            base.unlink(missing_ok=True)  # it goes with them
        write_json(api.ws.path("sources", "candidates.json"),  # the list without its facts
                   {"kept": [c for c in cands if (c.get("source") or {}).get("material") != mid],
                    "dropped": read_json(api.ws.path("sources", "candidates.json"), {}).get("dropped", [])})  # the record stays
        write_json(api.ws.path("sources", "removed", f"{mid}.json"), stash)  # what a put-back takes from
        api.facts.rebuild()  # the profile follows


def source_file(ws, mid: str) -> tuple[Path, str] | None:
    """(file, name) of a file brought in for the profile, by its id, or None when it is not on the list."""
    rec = next((m for m in ws.materials() if m.get("id") == mid), None)  # listed, not removed
    if not rec:
        return None
    f = ws.path("sources", str(rec.get("file") or ""))  # kept under its safe name
    return (f, str(rec.get("name") or f.name)) if f.is_file() and f.parent == ws.path("sources") else None


def stash_file(ws, mid: str) -> Path:
    """What a source took along when it was taken off (remove_material): its facts, the imported profile it was, the
    example's details."""
    return ws.path("sources", "removed", f"{mid}.json")


def removed_source(ws, mid: str) -> dict | None:
    """A source's record when it is taken off and not deleted for good, else None."""
    return next((m for m in ws.all_materials() if isinstance(m, dict) and m.get("id") == mid and m.get("removed")), None)


def removed_sources(ws) -> list[tuple[dict, int]]:
    """Every source taken off and not deleted for good, as the Trash lists them: (its record, the facts a put-back brings)."""
    out = []  # in the order they were brought in
    for m in ws.all_materials():  # brought in for the profile
        if not (isinstance(m, dict) and m.get("removed") and SOURCE_ID.fullmatch(str(m.get("id") or ""))):  # on the list, or no record
            continue
        stash = read_json(stash_file(ws, m["id"]), None)  # what it took along
        out.append((m, len(stash.get("candidates") or []) if isinstance(stash, dict) else int(m.get("facts") or 0)))  # the facts it gives back
    return out


def of(c, mid: str) -> bool:
    """Was this fact read from the source mid?"""
    return isinstance(c, dict) and isinstance(c.get("source"), dict) and c["source"].get("material") == mid


def from_steps(ws, mid: str) -> list[dict]:
    """A source's facts as the newest undo step that still holds them has them (a source taken off before its facts were
    kept aside), or []."""
    for snap in ws.snapshots("sources/candidates.json"):  # newest first
        got = [c for c in (snap.get("kept") or []) if of(c, mid)] if isinstance(snap, dict) else []
        if got:
            return got
    return []


def source_back(api, mid: str) -> dict:
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
            cands = from_steps(ws, mid)
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


def held(cands: list) -> bool:
    """Do these facts include an imported profile's?"""
    return any(isinstance(c, dict) and c.get("origin") == "profile" for c in cands)


def clean_source_data(rel: str, data, mid: str, stored: str, cids: set) -> tuple[object, bool]:
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


def purge_source(api, mid: str) -> tuple[set, object]:
    """Delete a source for good (the caller, the Trash, holds the locks): its file, its record, what it took along, its facts'
    states and edits, and where it filled a detail. Returns (the words undo labels name it by, the edit every undo step needs
    for its files: edit(step) says whether it changed the step; the Trash takes the words out of the labels)."""
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
            new, changed = clean_source_data(rel, data, mid, stored, cids)
            if changed:
                write_json(ws.root / rel, new)
    api.tasks.read_texts.pop(mid, None)  # the text its reading found, kept in memory for a run

    def edit(step: dict) -> bool:  # one undo step's files without it
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
            if rel == "sources/candidates.json" and isinstance(data, dict) and held([c for c in data.get("kept") or [] if of(c, mid)]) \
                    and files.get("profile/base.json") is not None:  # it was the imported profile then: that base is its own
                files["profile/base.json"] = None
                hit = True
            new, changed = clean_source_data(rel, data, mid, stored, cids)
            if changed:
                files[rel] = dump_json(new)
                hit = True
        made = step.get("made")
        if isinstance(made, dict):  # the records a step made
            for rel, ids in made.items():
                if isinstance(ids, list) and mid in ids:
                    made[rel] = [i for i in ids if i != mid]
                    hit = True
        return hit
    return words, edit


def stale_translation(api) -> None:
    """The English profile, when it was made from a profile that is no longer the one there is: it may hold the words of
    facts deleted for good, and no edition uses it (tasks.english_profile)."""
    t = api.tasks
    f = api.ws.path("profile", "profile.en.json")
    if f.is_file() and t.profile_lang() != "en" and t.english_profile() is None:  # a translation of another profile
        f.unlink(missing_ok=True)
