"""A person's whole workspace as one file, to move to another PC or to keep aside, in every way Offerowl runs: a browser saves
the file from the panel, so it works for a pod as it does for the app.

Restoring never deletes: the workspace as it was stays in a folder beside the restored one, and its name is said to the person.
A file is read only when it says it is a backup, and only when no entry of it can land outside the workspace.
"""
from __future__ import annotations

import io  # the file in memory
import json  # the mark inside the file
import logging  # what a refused backup held
import os  # the process id in a working name
import re  # names a backup may hold
import shutil  # the working folder
import stat  # a link in a zip
import tempfile  # a unique name for the backup built in a file, never whole in memory
import time  # the kept folder's name
import zipfile  # the file
from pathlib import Path, PurePosixPath  # paths on disk, and names in a zip

from ...core.workspace import Workspace, retried  # the layout, and moves waited for on Windows
from ..applications import MATERIAL_PREVIEWS  # where a job's materials keep their page pictures, as the applications name it
from ..documents import LIVE  # a job's working folder of the live canvas, as the documents name it

log = logging.getLogger("offerowl.api")  # the API's log
MARK = "offerowl-backup.json"  # the entry that says what this file is
MAX_UNPACKED = 4_000_000_000  # bytes a backup may unpack to: a real workspace is tens of megabytes, a planted zip may be far more
MAX_ENTRIES = 200_000  # entries a backup may hold, for the same reason
ODD_NAME = re.compile(r'[<>"|?*:\\\x00-\x1f]')  # never in a name the workspace writes; a path with one of these could break out of a page or of the folder
BACKUP_PREFIX = ".backup-"  # a backup being made is named by the process that makes it (sweep_leftovers)
SPARE = 64_000_000  # bytes a backup or a restore leaves free beyond what it writes: the panel's own files are written meanwhile
ENTRY = 200  # bytes a zip adds for each file it holds (its two headers), an upper bound for the names a workspace has
PASSING = re.compile(r"\.\d+\.\d+\.tmp$")  # a write in progress (workspace.tmp_name)


def _kept(rel: Path) -> bool:
    """Is this file of the workspace part of a backup? Not the undo steps, which hold whole files under names they choose, not a
    job's working folder, not the page pictures of its materials (made again when they are looked at), not what a deletion
    for good has yet to sweep (.gone), and not a write in progress. The folders of a job it leaves out are named by the
    services that make them."""
    parts = rel.parts  # its folders and name
    if parts[0] in (".history", ".gone") or (parts[0] == "jobs" and len(parts) > 2 and parts[2] == LIVE):  # undo steps, deleted jobs, jobs/<job>/live
        return False  # nothing to keep
    if parts[0] == "jobs" and len(parts) > 4 and parts[2:4] == MATERIAL_PREVIEWS:  # jobs/<job>/materials/.preview: the files themselves are kept
        return False  # pictures of what the backup holds anyway
    return not PASSING.search(rel.name)  # a person's own notes.tmp stays


# Files that are compressed already: stored as they are (deflating PDFs, pictures and Office files again took most of a
# backup's time and saved nothing).
STORED = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".docx", ".pptx", ".xlsx", ".zip", ".gz", ".woff", ".woff2",
          ".mp3", ".m4a", ".ogg", ".webm", ".mp4"}


def room(folder: Path, need: int) -> None:
    """Refuse with disk_full when the disk that holds `folder` has less than `need` bytes free beside SPARE. A backup or a
    restore that ran out of room part way stopped with a half-written file and an error that named a path; for a 784 MB
    workspace a restore needs about 1.5 GB more, a backup its zip beside the workspace (D4-09). A disk that cannot say what it
    has left is tried, and the write itself tells."""
    try:
        free = shutil.disk_usage(folder).free  # what the disk has left
    except OSError:  # a folder the system will not measure
        return
    if free < need + SPARE:  # it would fill the disk
        raise ValueError("disk_full")  # the page says to free some space


def kept_files(ws: Workspace) -> list:
    """(file, its name in the zip) of every file a backup holds, in a fixed order, listed under the workspace's lock."""
    with ws.lock:  # only the listing waits for the writes
        return [(f, rel) for f, rel in ((p, p.relative_to(ws.root)) for p in sorted(ws.root.rglob("*")) if p.is_file()) if _kept(rel)]


def size_of(files: list) -> int:
    """The bytes a backup of these files can take at most: each file whole (a zip stores or shrinks it) and its headers."""
    total = 0  # bytes
    for f, rel in files:  # each file
        try:
            total += f.stat().st_size + ENTRY + len(rel.as_posix().encode("utf-8")) * 2  # its bytes, its headers and its name twice
        except OSError:  # taken off since the listing
            continue  # no longer there: no room needed
    return total


def check_room(ws: Workspace) -> dict:
    """GET /api/v1/workspace/backup?check=1: whether the disk has room for a backup now, before the browser asks for one (a
    download that fails says nothing the page can show). {need} in bytes, or disk_full."""
    need = size_of(kept_files(ws))  # the zip at most
    room(ws.root.parent, need)  # refused when it would not fit
    return {"room": True, "need": need}


def write_file(ws: Workspace, version: int = 1) -> Path:
    """The workspace as a zip in a file inside the data folder (never /tmp: a container's /tmp is memory, and a killed download
    leaves no stray file there), which the caller sends and then deletes. Never whole in memory: a real workspace backs up to
    hundreds of megabytes. The file list is taken under the workspace lock and the zipping runs outside it, so a write is
    never held for the seconds a big workspace takes (D3-05). Files a job's working folder holds for a moment stay out. A
    disk without room for the zip is refused with disk_full before a byte is written (D4-09)."""
    ws.root.parent.mkdir(parents=True, exist_ok=True)  # the data folder, on its own disk
    files = kept_files(ws)  # every file a person would want back (not the undo steps, a working folder, a write in progress)
    room(ws.root.parent, size_of(files))  # the zip at most: refused before anything is written
    fd, name = tempfile.mkstemp(prefix=f"{BACKUP_PREFIX}{os.getpid()}-", suffix=".zip", dir=ws.root.parent)  # beside the workspace, not in it: it is not in its own backup; the pid in the name tells a later start whose it was
    os.close(fd)
    path = Path(name)
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:  # the zipping, outside the lock
            z.writestr(MARK, json.dumps({"app": "offerowl", "backup": version, "at": time.strftime("%Y-%m-%d %H:%M")}))  # what this file is
            for f, rel in files:
                try:
                    z.write(f, rel.as_posix(), compress_type=zipfile.ZIP_STORED if f.suffix.lower() in STORED else zipfile.ZIP_DEFLATED)
                except FileNotFoundError:  # taken off since the listing (a deletion for good): not part of the backup
                    continue
    except BaseException:  # a half-made file goes
        path.unlink(missing_ok=True)
        raise
    return path


def _alive(pid: int) -> bool:
    """Is a process with this id running? (os.kill(pid, 0) on Windows would send Ctrl+C, so it asks the system instead.)"""
    if pid <= 0:  # not a process id
        return False
    if os.name == "nt":  # Windows
        import ctypes  # the system call
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # query-limited-information
        if not handle:  # no such process
            return False
        code = ctypes.c_ulong()  # its exit code
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)  # signal 0 only asks
    except ProcessLookupError:  # gone
        return False
    except OSError:  # alive, owned by another user
        return True
    return True


def sweep_leftovers(ws: Workspace, old_s: int = 6 * 3600) -> int:
    """At server start: delete what a killed restore or backup download left beside the workspace (D3-03, D3-04): the upload's
    .upload-<pid>-<thread>.part, the unpacking folder <workspace>.restoring-<pid> and a backup's .backup-<pid>-*.zip. One is
    kept only when its process still runs and it is not old (a pid is reused). Returns how many went."""
    parent, n = ws.root.parent, 0  # the data folder, and how many went
    shapes = [re.compile(r"\.upload-(\d+)-\d+\.part"), re.compile(r"\.backup-(\d+)-.*\.zip"),
              re.compile(re.escape(ws.root.name) + r"\.restoring-(\d+)")]  # the names the three writers give, each with its pid
    try:
        found = list(parent.iterdir())
    except OSError:  # a folder that cannot be listed: nothing to sweep
        return 0
    for p in found:
        for shape in shapes:
            m = shape.fullmatch(p.name)  # one of ours?
            if not m or p.is_symlink():  # a link of that name is never followed
                continue
            pid = int(m.group(1))  # its owner
            try:
                young = time.time() - p.stat().st_mtime < old_s  # touched lately
            except OSError:
                continue
            if pid == os.getpid() or (young and _alive(pid)):  # this process's own, or a live one's at work
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)  # a half-unpacked workspace
            else:
                p.unlink(missing_ok=True)  # a piece
            n += 1
    return n


def write(ws: Workspace, version: int = 1) -> bytes:
    """The workspace as a zip's bytes (the command line and tests; the panel streams write_file's file)."""
    path = write_file(ws, version)
    try:
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _checked(z: zipfile.ZipFile) -> int:
    """Refuse a file that is not a backup, or one that could write outside the folder it is unpacked in. Returns the bytes
    it unpacks to."""
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
    return total  # what unpacking it writes


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
        unpacked = _checked(z)  # before anything is written
        shutil.rmtree(new, ignore_errors=True)  # what a stopped restore left
        room(root.parent, unpacked)  # the workspace unpacked beside the one there is: refused before a byte of it is written (D4-09)
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


def restore_workspace(api, data) -> dict:
    """A backup in the workspace's place, when no task is writing to it. Returns the name of the folder that keeps the old one."""
    if not api.restoring.acquire(blocking=False):  # two at once would share a working folder
        raise ValueError("busy")  # the page says to wait
    try:
        if any(t.get("state") == "running" for t in api.tasks.state().values()):  # a task would write into a folder that has moved
            raise ValueError("busy")  # the page says to wait
        kept = restore(api.ws, data)  # swapped, or refused with the old files as they were
        api.fits.forget_fits()  # fits of the old files
        api.tasks.forget_live()  # and their pages and pictures
        api.ws.gone.clear()  # a job deleted for good before may be one the backup holds: its folder is the backup's now
        try:
            api.state()  # what the page draws next: the names were fine, but what is in the files?
        except Exception as exc:  # a file of the backup the panel cannot read, which would stop it at every start
            log.warning("backup refused after unpacking: %s", exc)  # for the log only
            take_back(api.ws, kept)  # the person's files as they were
            raise ValueError("not_a_backup") from exc  # the page says so
        return {"kept": kept}  # for the page to say
    finally:
        api.restoring.release()  # the next one may start
