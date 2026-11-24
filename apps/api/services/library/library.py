"""Offerowl's API, the Library: every file the person brought in and every file Offerowl made, in one list. Each row
names its file, whose it is (an application, an edition, or the profile), its size and date, and what can be done to
it as the routes that do it: open it, copy it to the Desktop, take it off. The panel's Library view draws this list and
calls those routes; GET /api/v1/library gives a program the same list and the same routes. What was taken off is listed
apart (GET /api/v1/removed, removed.py), to be put back or deleted for good.

The Library owns none of these files: each service names its own (profile: the sources; applications: the postings and
the materials; documents: the editions' files and the copies that went out; interview: the kits' files), and the rows
here are made from what they give."""

from __future__ import annotations

import re
import time
import urllib.parse
from collections import Counter
from pathlib import Path

from .. import applications, documents, interview, profile  # a job's posting, a copy that went out, a kit's files, a source
from ..applications import FILE_TYPES, ODD_CHARS, RESERVED_NAMES, TEXT_KINDS, decodes  # a file's type and the names every system takes

GROUPS = ("source", "input", "made", "sent", "kit")                                 # brought in for the profile, brought in for an application, made, sent, the interview kit


def q(jid: str) -> str:
    """A job id in a path: Hangul and the rest percent-encoded, as the routes read it."""
    return urllib.parse.quote(jid, safe="")


def stamp(f: Path) -> str:
    """A file's date as 'YYYY-MM-DD HH:MM', from when it was last written."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))


def ext(name: str) -> str:
    """A file's kind by its name: pdf, md, json and the like."""
    return Path(name).suffix.lower().lstrip(".")


def answer(f: Path, name: str | None = None) -> tuple[bytes, str, dict]:
    """(bytes, type, headers) of a file the library opens: text with its character set, its own name for Save as, and a
    web page sandboxed so it runs nothing at the panel's address (materials.answer does the same for a job's files)."""
    data = f.read_bytes()                                                           # byte for byte
    kind = ext(f.name)                                                              # by its name
    ctype = {**FILE_TYPES, "json": "application/json", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(kind, "application/octet-stream")
    if kind in TEXT_KINDS or kind == "json":                                              # text: the browser must know how to read it
        ctype += next((f"; charset={label}" for label, enc in (("utf-8", "utf-8"), ("euc-kr", "cp949")) if decodes(data, enc)), "")
    shown = name or f.name                                                          # the name it is saved under
    plain = re.sub(r'[^\x20-\x7e]|["\\]', "_", shown)                               # for an old browser: plain letters only
    headers = {"Content-Disposition": f"inline; filename=\"{plain}\"; filename*=UTF-8''{urllib.parse.quote(shown, safe='')}"}
    if kind == "html":                                                              # a page at the panel's own address
        headers["Content-Security-Policy"] = "sandbox"                              # no script, no form, an origin of its own
    return data, ctype, headers


def listing(api) -> dict:
    """Every file, inputs first, then what was made from them."""
    ws, t = api.ws, api.tasks                                                       # the files and the builder
    rows: list[dict] = []                                                           # in the order the view reads them

    for m in profile.materials_now(api):                                                   # brought in for the profile, each with the facts it holds now (the count kept when it was read falls behind)
        rows.append({"group": "source", "id": "source:" + m["id"], "name": m.get("name") or m.get("file"), "kind": ext(m.get("name") or ""),
                     "size": m.get("size") or 0, "date": m.get("added") or "", "owner": None,
                     "note": {"facts": m.get("facts") or 0, "state": m.get("state") or "", "error": m.get("error") or ""},
                     "open": "/api/v1/materials/" + m["id"], "export": {"path": "/api/v1/library/export", "body": {"id": "source:" + m["id"]}},
                     "remove": {"path": "/api/v1/materials/remove", "body": {"id": m["id"]}, "undo": True}})   # its facts go with it, and undo brings both back
    ph = profile.photo_file(api)                                                           # the resume's photo
    if ph:
        rows.append({"group": "source", "id": "photo", "name": ph.name, "kind": ext(ph.name), "size": ph.stat().st_size, "date": stamp(ph), "owner": None,
                     "note": {"photo": True}, "open": "/api/v1/photo",
                     "remove": {"path": "/api/v1/photo/remove", "body": {}, "undo": False}})   # no undo step (a picture is no text): its answer names it in the Trash, which puts it back

    def built(owner: dict, oid: str, builds: dict) -> None:                          # an edition's printed files, per language
        for lang, b in sorted((builds or {}).items()):
            for name in documents.PRINTED:                                          # the documents' printed files
                f = documents.printed_file(t, oid, lang, name)                      # jobs/<id>/resume/<lang>/<name>, as the documents keep it
                if f is None:                                                       # this edition has no such file
                    continue
                count = b.get("pages") if name == "resume.pdf" else b.get("slides") if name == "deck.pdf" else None   # how long it is
                rows.append({"group": "made", "id": f"made:{oid}:{lang}:{name}", "name": name, "kind": "pdf", "lang": lang, "size": f.stat().st_size,
                             "date": b.get("at") or stamp(f), "owner": owner, "note": {"count": count, "stale": bool(b.get("stale"))},
                             "open": f"/api/v1/jobs/{q(oid)}/files/{lang}/{name}",
                             "export": {"path": "/api/v1/library/export", "body": {"id": f"made:{oid}:{lang}:{name}"}}})   # this very PDF to the Desktop

    for j in applications.jobs_view(api):                                                       # every application
        with api.gone_meanwhile(j["id"]):                                             # deleted for good while this was read: left out
            jid = j["id"]                                                               # its id
            owner = {"job": jid, "company": j.get("company") or jid, "role": j.get("role") or "", "stage": j.get("stage")}
            posting = applications.posting_file(ws, jid)                                    # the posting as it was read
            if posting.is_file() and posting.stat().st_size:
                rows.append({"group": "input", "id": "posting:" + jid, "name": "posting.md", "kind": "posting", "size": posting.stat().st_size,
                             "date": stamp(posting), "owner": owner, "note": {"chars": j.get("posting_chars") or 0, "head": j.get("posting_head") or ""},
                             "open": f"/api/v1/jobs/{q(jid)}/posting"})
            for m in j.get("materials") or []:                                          # decks, notes and briefs for its interview
                rows.append({"group": "input", "id": f"material:{jid}:{m['id']}", "name": m.get("name") or m.get("title"), "kind": m.get("kind") or ext(m.get("name") or ""),
                             "size": m.get("size") or 0, "date": m.get("added") or "", "owner": owner, "note": {},
                             "open": f"/api/v1/jobs/{q(jid)}/materials/{m['id']}",
                             "export": {"path": "/api/v1/jobs/materials/export", "body": {"job": jid, "id": m["id"]}},
                             "remove": {"path": "/api/v1/jobs/materials/remove", "body": {"job": jid, "id": m["id"]}, "undo": True}})   # off the list; the file stays until it is deleted for good
            qs = j.get("questions") or []                                               # the application form's questions
            if qs:
                rows.append({"group": "input", "id": "questions:" + jid, "name": "questions", "kind": "questions", "size": 0,
                             "date": "", "owner": owner, "note": {"answered": sum(1 for x in qs if str(x.get("answer") or "").strip()), "total": len(qs)},
                             "export": {"path": "/api/v1/jobs/questions/export", "body": {"job": jid}}})   # the questions and answers as a text file
            built(owner, jid, j.get("builds") or {})                                    # its editions
            lk = j.get("locked")                                                        # what went out
            if isinstance(lk, dict) and lk.get("folder"):
                for name, digest in sorted((lk.get("files") or {}).items()):
                    f = documents.sent_file(ws, jid, name)                              # only a recorded copy
                    if f:
                        rows.append({"group": "sent", "id": f"sent:{jid}:{name}", "name": name, "kind": ext(name), "lang": lk.get("lang"), "size": f.stat().st_size,
                                     "date": lk.get("at") or stamp(f), "owner": owner, "note": {"sha256": str(digest)[:12]},
                                     "open": f"/api/v1/jobs/{q(jid)}/sent/{name}",
                                     "export": {"path": "/api/v1/library/export", "body": {"id": f"sent:{jid}:{name}"}}})   # this copy, as it went
            for kind, f in interview.library_files(ws, jid):                               # the interview kit's files, as the kit names them
                if kind == "note":                                                      # the person's scripts and notes
                    rows.append({"group": "kit", "id": f"kit:{jid}:{f.name}", "name": f.name, "kind": ext(f.name), "size": f.stat().st_size,
                                 "date": stamp(f), "owner": owner, "note": {}, "open": f"/api/v1/jobs/{q(jid)}/kit/{q(f.name)}",
                                 "export": {"path": "/api/v1/library/export", "body": {"id": f"kit:{jid}:{f.name}"}}})
                elif kind == "draft":                                                   # a file of the scripts the agent drafted
                    rows.append({"group": "kit", "id": f"kitout:{jid}:{f.name}", "name": f.name, "kind": ext(f.name), "size": f.stat().st_size,
                                 "date": stamp(f), "owner": owner, "note": {"draft": True}, "open": f"/api/v1/jobs/{q(jid)}/kit/out/{f.name}",
                                 "export": {"path": "/api/v1/library/export", "body": {"id": f"kitout:{jid}:{f.name}"}}})
                else:                                                                   # the deck and plan the kit's maker wrote
                    rows.append({"group": "kit", "id": f"kitout:{jid}:{f.name}", "name": f.name, "kind": ext(f.name), "size": f.stat().st_size,
                                 "date": stamp(f), "owner": owner, "note": {"made": True}, "open": f"/api/v1/jobs/{q(jid)}/kit/out/{f.name}",
                                 "export": {"path": "/api/v1/library/export", "body": {"id": f"kitout:{jid}:{f.name}"}}})

    g = documents.general_view(api)                                                          # the edition with no posting
    built({"edition": g["id"], "name": ""}, g["id"], g.get("builds") or {})
    for e in documents.editions_view(api):                                                   # the named general editions
        built({"edition": e["id"], "name": e.get("name") or e["id"]}, e["id"], e.get("builds") or {})

    counts = Counter(r["group"] for r in rows)                                      # rows per group
    return {"rows": rows, "counts": {k: counts.get(k, 0) for k in GROUPS}, "bytes": sum(r.get("size") or 0 for r in rows)}


def file_of(api, row_id: str) -> tuple[Path, str] | None:
    """(file, name to save it under) of one Library row by its id, found the way the listing finds it; None when the id
    names no file of the workspace."""
    ws, t = api.ws, api.tasks
    kind, _, rest = str(row_id).partition(":")                                      # "made:<job>:<lang>:<name>" and the like
    if kind == "source":                                                            # a file brought in for the profile
        return profile.source_file(ws, rest)
    if kind == "made":                                                              # an edition's printed file
        oid, lang, name = rest.rsplit(":", 2) if rest.count(":") >= 2 else ("", "", "")
        if name not in documents.PRINTED or lang not in ("ko", "en"):
            return None
        api.need_job({"job": oid})                                                  # it exists
        f = documents.printed_file(t, oid, lang, name)                              # as the documents keep it
        return (f, f"{oid}-{lang}-{name}") if f else None
    if kind in ("sent", "kit", "kitout"):                                           # a copy that went out, a kit's note, what the kit's maker wrote
        jid, _, name = rest.rpartition(":")
        api.need_job({"job": jid})
        f = documents.sent_file(ws, jid, name) if kind == "sent" else interview.kit_file(ws, jid, name, out=(kind == "kitout"))
        return (f, f"{jid}-{name}") if f else None
    return None


def desk_name(name: str) -> str:
    """A Library file's name as it lands on the Desktop, one every system takes: no character Windows refuses, no name it
    keeps for a device (CON.md), no dot or space at the end, at most 180 bytes with the extension kept whole (a disk takes
    255; a twin's number needs room)."""
    name = ODD_CHARS.sub("_", name)  # refused characters out
    stem, dot, ext = name.rpartition(".")  # the last extension
    if not dot or not stem or not re.fullmatch(r"\w{1,16}", ext):  # no extension, a dot file, or a dot followed by no extension ("notes. ")
        stem, ext = name, ""  # all of it is the name
    stem = stem.strip(" .") or "file"  # Windows takes no name that ends in a dot or a space
    if RESERVED_NAMES.fullmatch(stem.split(".")[0]):  # a device name of Windows, whatever follows it
        stem = "_" + stem  # a mark before it, and it can be made
    suffix = f".{ext}" if ext else ""  # kept whole: the system opens the file by it
    while len((stem + suffix).encode("utf-8")) > 180 and len(stem) > 1:  # one character fewer, never half of one
        stem = stem[:-1]
    return stem.rstrip(" .") + suffix


def export(api, row_id: str) -> str:
    """Copy one Library row's file to the Desktop, byte for byte, under a name of its own (never over another file).
    Returns the name written; refuses a row with no file."""
    import shutil                                                                   # the copy
    found = file_of(api, row_id)
    if not found:                                                                   # no such row, or no file behind it
        raise ValueError("no_file")
    f, name = found
    name = desk_name(name)                                                          # a name every system accepts
    dest_dir = documents.desktop_dir()                                              # where the person looks
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    n = 2
    while dest.exists():                                                            # never over a file already there
        if dest.stat().st_size == f.stat().st_size and dest.read_bytes() == f.read_bytes():   # those very bytes are there already: named, never copied again
            return dest.name
        dest = dest_dir / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    shutil.copyfile(f, dest)
    return dest.name
