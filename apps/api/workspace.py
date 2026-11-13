"""The user's workspace on disk: where each file lives, safe writes, the undo history, the jobs and their board.

The layout is described in docs/ARCHITECTURE.md ("Your workspace"):

    profile/      profile.json (built from the confirmed facts), base.json (an imported profile), details.json
    sources/      the material added, materials.json, candidates.json, review.json, edits.json
    jobs/<job>/   posting.md, plan.json, status.json, resume/, cover/, interview/, submitted/, materials/ (materials.py)
    .history/     undo snapshots, newest last
    .gone/        a job's folder on its way out after "Delete for good" (removed.py); swept, never in a backup

Every change goes through Workspace.change(), which keeps the files it touches as they were, so one undo puts them
back. Nothing here talks to the agent or renders anything.
"""
from __future__ import annotations

import contextlib  # the change() context manager
import datetime  # dates on the board
import hashlib  # hashes of the frozen copies
import json  # every state file is JSON
import logging  # a file a failed change could not put back
import os  # atomic replace
import re  # job folder names
import shutil  # copies of submitted files
import sys  # Windows, where an open file stops a move for a moment
import threading  # one writer at a time
import time  # undo coalescing
from pathlib import Path  # paths

HISTORY_MAX = 50  # undo steps kept; the oldest goes first
PASSING = re.compile(r"\.\d+\.\d+\.tmp$")  # a write in progress (tmp_name): <name>.<process>.<thread>.tmp
STALE_S = 3600  # a write takes a moment: one an hour old has no writer left
COALESCE_S = 4.0  # typing in one field within this many seconds is one undo step
STAGES = ("preparing", "submitted", "interview", "result")  # the board's columns, in order

log = logging.getLogger("offerowl.panel")  # the panel's log


def today() -> str:
    """Today's date as the board shows it (YYYY-MM-DD, local time)."""
    return datetime.date.today().isoformat()  # local date; the board has no time of day


def now_minute() -> str:
    """This minute (YYYY-MM-DD HH:MM, local time): when a thing was taken off, so that several taken off on one day are told apart."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")  # the Trash shows the day and the hour


def read_json(path: Path, default):
    """A JSON file, or `default` when it is missing or unreadable (a half-written file must not stop the panel)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # the file as data
    except (OSError, ValueError):
        return default  # missing or broken: start from the default


def tmp_name(path: Path) -> Path:
    """A temporary file beside the target, unique to this process and thread (two writers never share one)."""
    return path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")  # same disk, so the rename is atomic


def retried(op, *args):
    """op(*args), a move (os.replace, Path.rename), waited for on Windows: there a file someone has open, as the page's next
    read of the state or a virus scanner looking at a new file, refuses the move with PermissionError for a moment (pip waits
    the same way). Elsewhere the error stands at once; on Windows after about two seconds."""
    for _ in range(40):  # 40 tries, 50 ms apart
        try:
            return op(*args)  # moved
        except PermissionError:  # held open for the moment, or refused for good
            if sys.platform != "win32":  # nowhere else does an open file stop a move
                raise
            time.sleep(0.05)  # a read of the state is over in a moment
    return op(*args)  # the last try: its error goes to the caller


def dump_json(data) -> str:
    """Data as the text every JSON file of the workspace holds. One spelling, so a file's text in an undo step that was
    rewritten (Workspace.scrub) still compares equal to the file on disk when they hold the same."""
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"  # readable on disk, Korean as it is


def write_json(path: Path, data) -> None:
    """Write JSON through a temporary file and a rename, so a crash never leaves half a file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)  # the folder may be new
    tmp = tmp_name(path)  # beside the target, same disk, unique to this writer
    tmp.write_text(dump_json(data), encoding="utf-8")  # readable on disk
    retried(os.replace, tmp, path)  # atomic on every system


def write_text(path: Path, text: str) -> None:
    """Write text the same safe way (postings)."""
    path.parent.mkdir(parents=True, exist_ok=True)  # the folder may be new
    tmp = tmp_name(path)  # beside the target, unique to this writer
    tmp.write_text(text, encoding="utf-8")  # the whole text
    retried(os.replace, tmp, path)  # atomic replace


def stored_name(mid: str, base: str) -> str:
    """A source's name on disk: its id, then its own name cut to 180 bytes (a disk takes 255; Korean takes three a letter)
    before the extension, which stays whole because the reader goes by it."""
    stem, dot, ext = base.rpartition(".")  # the last extension
    if not dot or not stem or not re.fullmatch(r"\w{1,16}", ext):  # no extension, a dot file, or a dot followed by no extension
        stem, ext = base, ""  # all of it is the name
    suffix = f".{ext}" if ext else ""  # kept whole
    head = f"{mid}_{stem}"  # the id first: it makes the name unique
    while len((head + suffix).encode("utf-8")) > 180 and len(head) > len(mid) + 1:  # one character fewer, never half of one
        head = head[:-1]
    return head.rstrip(" .") + suffix  # Windows takes no name that ends in a dot or a space


def slug(text: str) -> str:
    """A folder name from a company or role: letters, digits and Hangul kept, the rest dashes, at most 32 characters."""
    s = re.sub(r"[^0-9a-z가-힣]+", "-", (text or "").lower()).strip("-")  # safe characters only
    return s[:32].strip("-") or "job"  # never empty


def sha256(path: Path) -> str:
    """The SHA-256 of a file, for the frozen copies of a submitted application."""
    h = hashlib.sha256()  # streaming hash
    with path.open("rb") as f:  # binary read
        for block in iter(lambda: f.read(1 << 20), b""):  # one MiB at a time
            h.update(block)  # add the block
    return h.hexdigest()  # hex string


class Workspace:
    """One person's workspace folder. All writes take the same lock, so two requests never interleave."""

    def __init__(self, root: Path):
        self.root = Path(root)  # the workspace folder
        self.lock = threading.RLock()  # re-entrant: change() calls write helpers that also lock
        self.gone: set[str] = set()  # jobs deleted for good while this process runs: a late request or thread never makes their folder again, and their name is not given out
        self._mine = threading.local()  # per thread: the name of the undo step this thread's last change made (a request's answer says it: mine())
        for sub in ("profile", "sources", "jobs", "style", ".history"):  # the layout of docs/ARCHITECTURE.md
            (self.root / sub).mkdir(parents=True, exist_ok=True)  # created on first use
        self.sweep()  # what a deletion that was stopped half way left behind
        self.sweep_writes()  # and what a write stopped half way left (the PC turned off mid-save)

    # ---------------------------------------------------------------- paths

    def path(self, *parts: str) -> Path:
        """A path inside the workspace."""
        return self.root.joinpath(*parts)  # plain join; callers pass fixed names

    def posting(self, job_id: str) -> str:
        """A job's posting as pasted, "" when it is gone: the one reader of posting.md the state, the fit and the answers share."""
        f = self.job_dir(job_id) / "posting.md"
        return f.read_text(encoding="utf-8") if f.is_file() else ""

    def job_dir(self, job_id: str) -> Path:
        """A job's folder. The id is checked against the folder-name rule so it can never leave jobs/."""
        if not re.fullmatch(r"[0-9a-z가-힣-]{1,40}", job_id or "") or job_id in self.gone:  # same characters slug() makes; a job deleted for good has no folder
            raise ValueError("job id")  # a request with a made-up id, or one that came late
        return self.root / "jobs" / job_id  # inside jobs/

    def sweep(self) -> None:
        """Finish the deletions that could not finish: everything under .gone/ goes, and so do the undo steps a deletion could
        not rewrite (stuck.txt). A file someone still holds open (Windows) stays for now and is tried again at the next start or
        the next deletion."""
        shutil.rmtree(self.path(".gone"), ignore_errors=True)  # never follows a link: a link in its place is left alone
        with self.lock:  # no change adds or uses a step meanwhile
            self._sweep_stuck()

    def sweep_writes(self) -> int:
        """Delete the temporary files writes left behind when they were stopped half way (tmp_name's names), once they are an
        hour old, so no writer can still be using one. The person's own files ending in .tmp never match. Returns how many."""
        cutoff, n = time.time() - STALE_S, 0  # older than this, and how many went
        for f in self.root.rglob("*.tmp"):  # never into a link to a folder
            try:
                if PASSING.search(f.name) and f.is_file() and not f.is_symlink() and f.stat().st_mtime < cutoff:  # a write's own, and old
                    f.unlink()
                    n += 1
            except OSError:  # gone meanwhile, or held open (Windows): the next start tries again
                continue
        return n

    # ---------------------------------------------------------------- undo

    def _snapshot_files(self, rels) -> dict:
        """The text of each file (relative path) as it is now; None for a file that does not exist."""
        out = {}  # relative path -> text or None
        for rel in rels:  # each file the change will touch
            p = self.root / rel  # absolute path
            out[rel] = p.read_text(encoding="utf-8") if p.is_file() else None  # None means 'did not exist'
        return out

    def _history(self) -> list[Path]:
        """The undo snapshots, oldest first."""
        return sorted(self.path(".history").glob("*.json"))  # names are zero-padded counters

    # Lists that also grow outside any undo step (a file added is listed at once, before it is read): an undo puts back the
    # records it had and drops the ones the step itself made, and keeps the records added since, whose files stay on disk.
    MERGED = ("sources/materials.json",)

    @staticmethod
    def _ids(text: str | None) -> list:
        """The ids of the records in a merged list's text."""
        try:
            return [m.get("id") for m in (json.loads(text) if text else []) if isinstance(m, dict)]  # each record's id
        except ValueError:  # a broken file has no records to keep apart
            return []

    @contextlib.contextmanager
    def change(self, label: dict, rels, coalesce: str | None = None):
        """Make a change that one undo can take back. `rels` names every file (relative to the workspace) the change
        may write. `label` says what it was, for the undo button. Changes with the same `coalesce` key made within a
        few seconds are one undo step (typing in a field saves on every pause)."""
        with self.lock:  # one change at a time
            before = self._snapshot_files(rels)  # the files as they were
            try:
                yield  # the caller writes
            except BaseException:  # it stopped half way: what it wrote has no undo step, so it goes now
                self._put_back(before)  # the files as they were before the change
                raise  # the caller's error is still the answer
            after = self._snapshot_files(rels)  # the files as they are now
            if after == before:  # nothing changed: no undo step
                return
            made = {rel: self._ids(after[rel]) for rel in self.MERGED if rel in after}  # what each merged list held right after the step
            hist = self._history()  # existing steps
            if coalesce and hist:  # typing in the same field again
                last = read_json(hist[-1], {})  # newest step
                if last.get("coalesce") == coalesce and time.time() - float(last.get("t") or 0) < COALESCE_S:
                    last["t"] = time.time()  # extend the window; keep the older 'before'
                    for rel, ids in made.items():  # the records this longer step made
                        last.setdefault("made", {})[rel] = sorted(set((last.get("made") or {}).get(rel) or []) | set(ids), key=str)
                    write_json(hist[-1], last)  # the same step covers this edit too
                    self._mine.step = f"{int(hist[-1].stem)}:{last['t']}"  # its name now (newest() names it the same way)
                    return
            n = int(hist[-1].stem) + 1 if hist else 1  # next counter
            t = time.time()  # the step's time, part of its name
            write_json(self.path(".history", f"{n:06d}.json"),
                       {"t": t, "label": label, "coalesce": coalesce, "files": before, "made": made})  # the restore point
            self._mine.step = f"{n}:{t}"  # for the answer to this thread's request: its own step, whatever another writer did since
            for old in self._history()[:-HISTORY_MAX]:  # keep the newest HISTORY_MAX
                old.unlink(missing_ok=True)  # the oldest steps go

    def _put_back(self, before: dict) -> None:
        """Write the files of a change that stopped half way back as they were (under the lock, so nobody wrote meanwhile)."""
        for rel, text in before.items():  # each file the change could write
            p = self.root / rel  # absolute path
            try:
                if text is None:  # it did not exist before the change
                    p.unlink(missing_ok=True)  # so it goes
                    if p.parent.parent == self.path("jobs"):  # a job's folder the change made: its name is free again
                        try:
                            p.parent.rmdir()  # only when nothing else is in it
                        except OSError:  # other files stay, and the folder with them
                            pass
                elif not p.is_file() or p.read_text(encoding="utf-8") != text:  # written meanwhile
                    write_text(p, text)  # its old text back
            except OSError as exc:  # a file that cannot be put back: the others still are, and the log says which
                log.warning("could not put back %s after a failed change: %s", rel, exc)

    def history(self) -> list[dict]:
        """The undo steps, newest first, as the History tab lists them: {n, t, label}."""
        out = []  # newest first
        for f in reversed(self._history()):  # every step
            rec = read_json(f, {})  # its record
            out.append({"n": int(f.stem), "t": rec.get("t"), "label": rec.get("label") or {},  # its number, time and words
                        "id": f"{int(f.stem)}:{rec.get('t')}"})  # its name as newest() gives it: the page sends the newest one back with an undo
        return out  # the files themselves never leave this module

    def undo_label(self) -> dict | None:
        """What the next undo would take back, or None."""
        return self.newest()[1]  # newest step's label

    def newest(self) -> tuple[str | None, dict | None]:
        """(a name for the newest step, its label), or (None, None) without one. The name is the step's number and time: a
        page that offers to take back the change it just made sends it along, and the undo happens only while that step is
        still the newest (a number alone comes round again once a step is undone and another is made)."""
        hist = self._history()  # all steps
        if not hist:  # nothing to undo
            return None, None
        rec = read_json(hist[-1], {})  # one read for both
        return f"{int(hist[-1].stem)}:{rec.get('t')}", rec.get("label") or {}  # its name, what it was

    def mine(self) -> str | None:
        """The name of the undo step this thread's last change made (None when it made none since forget_mine): a write's
        answer carries it, so a toast's Undo takes back that change and never one another writer made just after it."""
        return getattr(self._mine, "step", None)

    def forget_mine(self) -> None:
        """Start a request with no step of its own (a thread may serve several, as the in-process client's does)."""
        self._mine.step = None

    def history_count(self) -> int:
        """How many undo steps there are, by their files' names: the page's poll never reads the steps themselves."""
        return len(self._history())

    def snapshots(self, rel: str):
        """Each undo step's copy of one file, newest first, as data (JSON files only): what a thing taken off before it was
        kept aside can still be brought back from (removed.py)."""
        for f in reversed(self._history()):  # newest first
            text = (read_json(f, {}).get("files") or {}).get(rel)  # the file as it was before that step
            if text:  # the step holds it
                try:
                    yield json.loads(text)  # as data
                except ValueError:  # a copy of a broken file
                    continue

    def scrub(self, edit) -> int:
        """Rewrite the undo steps after something was deleted for good, so that no step can bring it back. edit(step) changes
        one step's record in place (the texts under "files", "made", the label) and says whether it did. A step left with
        no file goes; so does a changed step that would now put back exactly what is there anyway (the removal of the thing
        just deleted). A step is read again for a moment when the system holds it (Windows: an antivirus or the indexer);
        one that is not a step's JSON, or still cannot be read, goes (it cannot be checked, and its text may hold anything).
        A changed step that cannot be written is deleted instead; when one can be neither, every other step is still done
        and ValueError("delete_failed") says so. Returns how many steps were changed."""
        with self.lock:  # no change may add or use a step meanwhile
            steps, changed, stuck = [], set(), []  # the readable steps oldest first, the ones the edit touched, the ones that stayed as they were
            for f in self._history():  # every step
                try:
                    step = json.loads(retried(lambda f=f: f.read_text(encoding="utf-8")))  # its record, waited for while it is held
                except FileNotFoundError:  # gone meanwhile
                    continue
                except (OSError, ValueError):  # unreadable, or not JSON
                    step = None
                if not isinstance(step, dict) or not isinstance(step.get("files"), dict):  # broken: nothing an undo could put back
                    self._drop(f, stuck)  # gone with whatever it held
                    continue
                if edit(step):  # the caller took its thing out
                    changed.add(f)
                steps.append((f, step))
            later = {}  # file -> its text right after the step in hand: the copy the next step up holds, else the file itself
            for f, step in reversed(steps):  # newest first, so "after" is known before each step is judged
                files = step["files"]  # relative path -> text before the step
                if f in changed:  # only steps the deletion changed are judged or rewritten
                    same = all(text == (later[rel] if rel in later else self._snapshot_files([rel])[rel]) for rel, text in files.items())  # undoing it would change nothing
                    if not files or same:  # nothing left to put back
                        self._drop(f, stuck)
                    else:
                        try:
                            write_json(f, step)  # the step without the deleted thing
                        except OSError:  # it cannot be written: it goes instead, with the thing it held
                            self._drop(f, stuck)
                later.update(files)  # for the step before this one, these are the texts after it
            if stuck:  # a step that could be neither rewritten nor deleted still holds what was deleted: named, so it goes later
                self._remember_stuck(stuck)
                raise ValueError("delete_failed")
            return len(changed)

    STUCK = "stuck.txt"  # in .history: the undo steps a deletion for good could not rewrite or delete (never a step: not *.json)

    def _remember_stuck(self, names: list) -> None:
        """Name undo steps that still hold something deleted for good, so sweep() deletes them at the next start or deletion."""
        f = self.path(".history", self.STUCK)
        try:
            old = f.read_text(encoding="utf-8").split() if f.is_file() else []  # named before
            write_text(f, "\n".join(sorted(set(old) | set(names))) + "\n")
        except OSError:  # the folder itself refuses: nothing more can be done now
            pass

    def _sweep_stuck(self) -> None:
        """Delete the undo steps a deletion for good could not (stuck.txt), as far as the system lets go of them now."""
        f = self.path(".history", self.STUCK)
        if not f.is_file():
            return
        left = []  # those still held
        for name in f.read_text(encoding="utf-8").split():
            if re.fullmatch(r"\d{6}\.json", name):  # a step's own name: nothing else is ever deleted from here
                self._drop(self.path(".history", name), left)
        try:
            if left:
                write_text(f, "\n".join(left) + "\n")
            else:
                f.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _drop(f: Path, stuck: list) -> None:
        """Delete one undo step, waited for while the system holds it; when it cannot be, name it in stuck."""
        try:
            retried(lambda: f.unlink(missing_ok=True))  # Windows lets go of a file in a moment
        except OSError:  # held for good
            stuck.append(f.name)

    def undo(self) -> dict | None:
        """Put back the files of the newest step and forget it. Returns its label, or None when there is nothing."""
        with self.lock:  # no change may run meanwhile
            hist = self._history()  # all steps
            if not hist:  # nothing to undo
                return None
            step = read_json(hist[-1], {})  # newest step
            for rel, text in (step.get("files") or {}).items():  # each file as it was
                p = self.root / rel  # absolute path
                if not p.resolve().is_relative_to(self.root.resolve()):  # never write outside the workspace: a sibling folder shares its name's start
                    continue
                if rel in self.MERGED:  # the records it had, and those added since the step
                    known = set(self._ids(text)) | set((step.get("made") or {}).get(rel) or [])  # before the step, or made by it
                    since = [m for m in read_json(p, []) if isinstance(m, dict) and m.get("id") not in known]  # added after it
                    write_json(p, (json.loads(text) if text else []) + since)  # the step's own records go back as they were
                elif text is None:  # it did not exist before the change
                    p.unlink(missing_ok=True)  # so it goes
                    if p.parent.parent == self.path("jobs"):  # a job's folder the step made: gone with its last file, so its name is free again
                        try:
                            p.parent.rmdir()  # only when nothing else is in it
                        except OSError:  # files of later work stay, and the folder with them
                            pass
                else:
                    write_text(p, text)  # its old text back
            hist[-1].unlink(missing_ok=True)  # the step is used
            return step.get("label") or {}  # what was undone

    # ---------------------------------------------------------------- settings of this workspace

    def prefs(self) -> dict:
        """Small choices kept with the workspace (the job in view, the guide hidden)."""
        return read_json(self.path("prefs.json"), {})  # empty when new

    def set_prefs(self, **values) -> None:
        """Change some of those choices (not undoable: they are where you are, not what you made)."""
        with self.lock:  # one writer
            p = self.prefs()  # current
            p.update(values)  # changed keys
            write_json(self.path("prefs.json"), p)  # saved

    # ---------------------------------------------------------------- materials

    def materials(self) -> list[dict]:
        """The material added, in the order it came, without the removed ones."""
        return [m for m in read_json(self.path("sources", "materials.json"), []) if not m.get("removed")]  # visible ones

    def all_materials(self) -> list[dict]:
        """Every material record, the removed ones too (undo needs them)."""
        return read_json(self.path("sources", "materials.json"), [])  # the whole list

    def add_material(self, name: str, data: bytes) -> dict:
        """Keep one file in sources/ under a safe name and list it. Returns its record."""
        with self.lock:  # one writer
            items = self.all_materials()  # existing
            on_disk = [int(m.group(1)) for f in self.path("sources").glob("m*_*") if (m := re.match(r"m(\d+)_", f.name))]  # files kept, listed or not
            high = self.prefs().get("sources_high")  # the highest id ever given: a source deleted for good leaves neither a record nor a file to count
            n = 1 + max([int(m["id"][1:]) for m in items if re.fullmatch(r"m\d+", m.get("id", ""))] + on_disk + [high if isinstance(high, int) else 0])  # next id, never one a file has or had
            mid = f"m{n}"  # material id
            base = re.sub(r"[^\w가-힣.() -]+", "_", Path(name).name).strip() or "file"  # safe file name, no folders
            stored = stored_name(mid, base)  # unique by the id prefix, at most 180 bytes, its extension kept
            (self.path("sources") / stored).write_bytes(data)  # the file itself
            rec = {"id": mid, "name": Path(name).name[:200], "file": stored, "size": len(data),
                   "kind": kind_of(base, data), "added": today(), "state": "new", "facts": 0}  # its record
            items.append(rec)  # listed
            write_json(self.path("sources", "materials.json"), items)  # saved
            return rec

    ARCHIVE_KINDS = {".pdf", ".docx", ".pptx", ".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".png", ".jpg", ".jpeg"}  # what a zip may hold that the readers know
    LINKEDIN_CAREER = {"profile.csv", "positions.csv", "education.csv", "skills.csv", "certifications.csv", "projects.csv", "publications.csv",
                       "honors.csv", "languages.csv", "courses.csv", "patents.csv", "volunteering.csv"}  # a LinkedIn export's files about the person's own career
    ARCHIVE_FILES, ARCHIVE_BYTES = 300, 300_000_000  # a zip's files and their bytes once unpacked: past either, the rest stays packed

    def add_materials(self, name: str, data: bytes) -> list[dict]:
        """One upload as sources: a zip (a LinkedIn data export, a folder of old documents someone zipped) gives each file in it
        the readers know, under the zip's name; anything else is one file. Returns their records."""
        import io  # the zip in memory
        import zipfile  # its members
        if not (Path(name).suffix.lower() == ".zip" and zipfile.is_zipfile(io.BytesIO(data))):  # one ordinary file
            return [self.add_material(name, data)]
        out, total = [], 0  # the records, the bytes unpacked so far
        stem = Path(name).stem[:60]  # the zip's name, before each file's
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = {Path(i.filename).name.lower() for i in z.infolist()}  # what the zip holds
            linkedin = "positions.csv" in names  # a LinkedIn data export: its career files are named this way
            for info in z.infolist():
                if linkedin and Path(info.filename).name.lower() not in self.LINKEDIN_CAREER:  # connections, messages, invitations: other people's, never read
                    continue
                inner = Path(info.filename)  # the member's path inside the zip, never used as a path here
                if info.is_dir() or inner.suffix.lower() not in self.ARCHIVE_KINDS or any(part.startswith((".", "__MACOSX")) for part in inner.parts):
                    continue  # folders, kinds no reader knows, hidden files and a Mac's resource forks
                if len(out) >= self.ARCHIVE_FILES or total + info.file_size > self.ARCHIVE_BYTES:  # a zip far larger than a career
                    break
                body = z.read(info)  # its bytes
                total += len(body)
                if body:  # an empty member is nothing to read
                    out.append(self.add_material(f"{stem} - {inner.name}", body))
        return out

    def update_material(self, mid: str, **values) -> None:
        """Change a material's record (its reading state, its fact count). A value of None takes the key out."""
        with self.lock:  # one writer
            items = self.all_materials()  # all records
            for m in items:  # find it
                if m.get("id") == mid:
                    m.update({k: v for k, v in values.items() if v is not None})  # new values
                    for k in [k for k, v in values.items() if v is None]:  # a key no longer true of it (removed, once it is back)
                        m.pop(k, None)
            write_json(self.path("sources", "materials.json"), items)  # saved

    def material_path(self, rec: dict) -> Path:
        """Where a material's file is kept."""
        return self.path("sources", Path(rec["file"]).name)  # inside sources/, whatever the record says

    # ---------------------------------------------------------------- jobs

    def jobs(self, removed: bool = False, kind: str = "job") -> list[dict]:
        """Every job's status, oldest first (the board's order). Removed jobs are left out unless asked for. kind "edition"
        lists the named general editions instead (no posting, never on the board)."""
        out = []  # status records
        for d in sorted(self.path("jobs").iterdir()) if self.path("jobs").is_dir() else []:  # each job folder
            st = read_json(d / "status.json", None) if d.name not in self.gone else None  # its status (a job deleted for good has none)
            if isinstance(st, dict) and (removed or not st.get("removed")) and (st.get("kind") or "job") == kind:  # a real, visible one of that kind
                out.append(st)
        return sorted(out, key=lambda s: (s.get("created") or "", s.get("seq") or 0))  # oldest first

    @staticmethod
    def sniff_ok(ext: str, data: bytes) -> bool:
        """Do the first bytes match the type the name gives: a PDF starts with %PDF, a Word file or slides are a zip."""
        return data.startswith(b"%PDF") if ext == ".pdf" else data.startswith(b"PK\x03\x04") if ext in (".docx", ".pptx") else False

    def editions(self) -> list[dict]:
        """The named general editions, oldest first: editions with no posting, kept like a job's but off the board."""
        return self.jobs(kind="edition")

    def new_edition_id(self, name: str) -> str:
        """A new folder name for a named edition: a dash, then the name (no company name starts with one), made unique."""
        base = ("-" + slug(name or "edition"))[:40]  # readable name, apart from every job's
        taken = ({d.name for d in self.path("jobs").iterdir()} if self.path("jobs").is_dir() else set()) | self.gone  # existing folders, and the names of those deleted for good
        jid, n = base, 2  # first try the plain name
        while jid in taken or jid == "-general":  # already used, or the general edition's own folder
            jid, n = f"{base}-{n}"[:40], n + 1  # add a counter
        return jid

    def new_job_id(self, company: str, role: str) -> str:
        """A new folder name for a job: the company (else the role), made unique with -2, -3 ..."""
        base = slug(company or role or "job")  # readable name
        taken = ({d.name for d in self.path("jobs").iterdir()} if self.path("jobs").is_dir() else set()) | self.gone  # existing folders, and the names of those deleted for good
        jid, n = base, 2  # first try the plain name
        while jid in taken:  # already used
            jid, n = f"{base}-{n}"[:40], n + 1  # add a counter
        return jid

    def job(self, job_id: str) -> dict | None:
        """One job's status, or None."""
        st = read_json(self.job_dir(job_id) / "status.json", None)  # its record
        return st if isinstance(st, dict) else None

    def job_files(self, job_id: str) -> list[str]:
        """The files of a job a change may touch (relative to the workspace), for change()."""
        return [f"jobs/{job_id}/status.json", f"jobs/{job_id}/posting.md", f"jobs/{job_id}/plan.json"]

    def save_job(self, st: dict) -> None:
        """Write a job's status."""
        write_json(self.job_dir(st["id"]) / "status.json", st)  # into its folder

    def freeze(self, job_id: str, files: dict[str, Path]) -> dict:
        """Keep frozen copies of what was submitted, with their hashes: jobs/<job>/submitted/<time>/. Returns the record."""
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")  # one folder per lock
        dest = self.job_dir(job_id) / "submitted" / stamp  # frozen copies
        dest.mkdir(parents=True, exist_ok=True)  # new folder
        hashes = {}  # file name -> sha256
        for name, src in files.items():  # each document
            shutil.copy2(src, dest / name)  # an exact copy
            hashes[name] = sha256(dest / name)  # what it was
        write_json(dest / "hashes.json", hashes)  # kept beside the copies
        return {"at": today(), "folder": stamp, "files": hashes}  # the lock record


def kind_of(name: str, data: bytes) -> str:
    """What kind of material a file is, by its name and first bytes: profile, pdf, word, slides, image, text or other."""
    low = name.lower()  # extension test
    if low.endswith(".json"):  # maybe an Offerowl profile
        try:
            doc = json.loads(data.decode("utf-8"))  # parse it
            if isinstance(doc, dict) and str(doc.get("schema", "")).startswith("resume-profile/"):  # our schema
                return "profile"
        except (UnicodeDecodeError, ValueError):
            pass  # not JSON after all
        return "text"  # other JSON is read as text
    if low.endswith(".pdf"):
        return "pdf"
    if low.endswith(".docx"):
        return "word"
    if low.endswith(".pptx"):
        return "slides"
    if low.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")):
        return "image"
    if low.endswith((".md", ".txt", ".csv", ".yaml", ".yml")):
        return "text"
    return "other"  # read as nothing; the panel says so
