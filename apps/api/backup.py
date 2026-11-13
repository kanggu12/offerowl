"""A person's whole workspace as one file, to move to another PC or to keep aside, in every way Offerowl runs: a browser saves
the file from the panel, so it works for a pod as it does for the app.

Restoring never deletes: the workspace as it was stays in a folder beside the restored one, and its name is said to the person.
A file is read only when it says it is a backup, and only when no entry of it can land outside the workspace.
"""
from __future__ import annotations

import io  # the file in memory
import json  # the mark inside the file
import os  # the process id in a working name
import re  # names a backup may hold
import shutil  # the working folder
import stat  # a link in a zip
import time  # the kept folder's name
import zipfile  # the file
from pathlib import Path, PurePosixPath  # paths on disk, and names in a zip

from .workspace import Workspace, retried  # the layout, and moves waited for on Windows

MARK = "offerowl-backup.json"  # the entry that says what this file is
MAX_UNPACKED = 4_000_000_000  # bytes a backup may unpack to: a real workspace is tens of megabytes, a planted zip may be far more
MAX_ENTRIES = 200_000  # entries a backup may hold, for the same reason
ODD_NAME = re.compile(r'[<>"|?*:\\\x00-\x1f]')  # never in a name the workspace writes; a path with one of these could break out of a page or of the folder
PASSING = re.compile(r"\.\d+\.\d+\.tmp$")  # a write in progress (workspace.tmp_name)


def _kept(rel: Path) -> bool:
    """Is this file of the workspace part of a backup? Not the undo steps, which hold whole files under names they choose, not a
    job's working folder, not the page pictures of its materials (made again when they are looked at), not what a deletion
    for good has yet to sweep (.gone), and not a write in progress."""
    parts = rel.parts  # its folders and name
    if parts[0] in (".history", ".gone") or (parts[0] == "jobs" and len(parts) > 2 and parts[2] == "live"):  # undo steps, deleted jobs, jobs/<job>/live
        return False  # nothing to keep
    if parts[0] == "jobs" and len(parts) > 4 and parts[2:4] == ("materials", ".preview"):  # jobs/<job>/materials/.preview: the files themselves are kept
        return False  # pictures of what the backup holds anyway
    return not PASSING.search(rel.name)  # a person's own notes.tmp stays


def write(ws: Workspace, version: int = 1) -> bytes:
    """The workspace as a zip's bytes. Files a job's working folder holds for a moment stay out."""
    out = io.BytesIO()  # built in memory: the server answers it in one piece
    with ws.lock, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:  # no write of this workspace lands half way through
        z.writestr(MARK, json.dumps({"app": "offerowl", "backup": version, "at": time.strftime("%Y-%m-%d %H:%M")}))  # what this file is
        for f in sorted(p for p in ws.root.rglob("*") if p.is_file()):  # every file, in a fixed order
            rel = f.relative_to(ws.root)  # its name in the zip
            if _kept(rel):  # what a person would want back
                z.write(f, rel.as_posix())  # kept
    return out.getvalue()  # the file


def _checked(z: zipfile.ZipFile) -> None:
    """Refuse a file that is not a backup, or one that could write outside the folder it is unpacked in."""
    if MARK not in z.namelist():  # any other zip
        raise ValueError("not_a_backup")  # the page says so
    if len(z.infolist()) > MAX_ENTRIES:  # far more files than any workspace holds
        raise ValueError("too_large")  # the page says so
    total = 0  # what it unpacks to
    for info in z.infolist():  # every entry
        name = PurePosixPath(info.filename)  # as written in the file
        if name.is_absolute() or ".." in name.parts or ODD_NAME.search(info.filename):  # outside the folder on any system, or a name that could break out of a page
            raise ValueError("not_a_backup")  # nothing of it is written
        if stat.S_ISLNK(info.external_attr >> 16):  # a link could point anywhere
            raise ValueError("not_a_backup")  # the same answer
        total += info.file_size  # as the file says
    if total > MAX_UNPACKED:  # a zip that unpacks to more than any workspace holds
        raise ValueError("too_large")  # the page says so


def aside_name(root: Path) -> Path:
    """Where the workspace goes aside before a restore: beside it, named by the time, with a number when a restore made
    in the same second holds that name (the rename would fail on it, or on an empty one take its place)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")  # when, to the second
    kept, n = root.with_name(f"{root.name}-before-restore-{stamp}"), 2  # the plain name first
    while kept.exists():  # taken by an earlier restore
        kept, n = root.with_name(f"{root.name}-before-restore-{stamp}-{n}"), n + 1  # the next number
    return kept


def restore(ws: Workspace, data) -> str:
    """Put a backup in the workspace's place: `data` is its bytes, or the file it was written to (the panel writes an upload
    to a file, so a large backup never sits whole in memory). Returns the name of the folder that keeps the workspace as it was."""
    try:
        z = zipfile.ZipFile(data if isinstance(data, (str, os.PathLike)) else io.BytesIO(data))  # read from the file, or from memory
    except zipfile.BadZipFile as exc:  # not a zip at all
        raise ValueError("not_a_backup") from exc  # the page says so
    root = ws.root  # the workspace's folder
    new = root.with_name(f"{root.name}.restoring-{os.getpid()}")  # beside it, on the same disk, so the swap is one rename
    kept = aside_name(root)  # never deleted: the person may want it back
    with z:  # closed in every case
        _checked(z)  # before anything is written
        shutil.rmtree(new, ignore_errors=True)  # what a stopped restore left
        try:
            z.extractall(new)  # the names were checked above
            (new / MARK).unlink()  # the mark is not part of a workspace
            if not (new / "profile").is_dir():  # a mark without a workspace behind it
                raise ValueError("not_a_backup")  # the current files stay as they are
            shutil.rmtree(new / ".history", ignore_errors=True)  # undo steps name files of the workspace they came from: a backup carries none
            Workspace(new)  # the layout, for a backup made before a folder was added: a file where a folder belongs stops here
            with ws.lock:  # no write lands between the two renames
                kept = aside_name(root)  # named again now: a restore made in the same second took the first name meanwhile
                retried(root.rename, kept)  # the workspace as it was, aside
                try:
                    retried(new.rename, root)  # the backup in its place
                except OSError:  # the second rename failed
                    if root.is_dir() and not any(root.iterdir()):  # something made an empty folder in the gap
                        root.rmdir()  # it holds nothing
                    retried(kept.rename, root)  # back as it was
                    raise  # and said
        except OSError as exc:  # a full disk, a file held open, a file where a folder belongs
            raise ValueError("restore_failed") from exc  # the page says it could not
        finally:
            shutil.rmtree(new, ignore_errors=True)  # nothing left of the working folder
    return kept.name  # for the page to say


def take_back(ws: Workspace, kept: str) -> None:
    """The workspace as it was, in place of a restored one the panel cannot read. The restored files go: they came from the backup."""
    aside = ws.root.with_name(kept)  # the folder restore() named
    with ws.lock:  # no write lands in between
        shutil.rmtree(ws.root)  # the file the person still has
        retried(aside.rename, ws.root)  # back
