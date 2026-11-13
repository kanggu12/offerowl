"""A job's own materials: the decks, study notes, company briefs, form answers and solutions a person prepared for one
application, often with the tools they used before Offerowl. They are kept as they came, listed and previewed on the
application's Interview tab, and handed back byte for byte. They are not the profile's sources (workspace.py's
materials): no fact is read from them, and nothing of them goes to the agent.

Kept in jobs/<job>/materials/:
    <name>.<kind>   one file per material, under its own name made safe (no folders, no character a system refuses), with
                    a number added when the name is taken
    index.json      [{"id", "title", "name", "file", "kind", "size", "added", "sha256"}] in the order they came. A record
                    never changes, so taking back an older step can never drop a file added after it; one deleted for good
                    leaves only {"id", "gone": true}, so its id is never given again
    removed.json    the ids taken off the list, and removed_at.json the day each went (for the Removed list): the two files
                    a removal changes, so undo puts an id back, and the file stays in the folder until it is deleted for
                    good (removed.py)
    .preview/<id>/  the page pictures of a PDF, a deck or a Word file, and the PDF LibreOffice made of the last two

The kinds kept: PDF, PowerPoint (.pptx), Word (.docx), Markdown, HTML, text, Python, PNG and JPEG, up to 50 MB each.
"""
from __future__ import annotations

import codecs  # a text file's start decoded without a broken last character
import contextlib  # a lock that is only needed some of the time
import hashlib  # the SHA-256 of what came in
import html  # entities in a markdown line
import logging  # why a preview could not be made, for the log only
import os  # atomic replace, and the process group of a converter
import re  # names, markdown and HTML
import shutil  # copies to the Desktop, LibreOffice and its working folder
import signal  # a converter that hangs is stopped whole
import struct  # a page picture's size, from its PNG header
import subprocess  # LibreOffice, here or in the render container
import tempfile  # a working folder for LibreOffice on this PC
import threading  # one preview made at a time
import unicodedata  # one spelling of a name that a Mac sends decomposed
import urllib.parse  # a file's own name in a header, as RFC 6266 writes it
from pathlib import Path  # paths

from .workspace import now_minute, read_json, retried, sha256, today, tmp_name, write_json  # files and their hashes

ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
log = logging.getLogger("offerowl.panel")  # the panel's log
KINDS = {  # the kinds a job keeps, by their extension, and the type a file of each is answered with
    "pdf": "application/pdf",  # documents and decks printed to PDF
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # explainer decks
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # Word notes and answers
    "md": "text/markdown",  # study notes, company briefs, form answers
    "html": "text/html",  # a saved page, a brief written as HTML
    "txt": "text/plain",  # plain notes
    "py": "text/x-python",  # a live-coding solution
    "png": "image/png",  # a screenshot or a diagram
    "jpg": "image/jpeg",  # a photo of a whiteboard
}
TEXT = ("md", "html", "txt", "py")  # the kinds that are text, answered with their character set
PAGED = ("pdf", "pptx", "docx")  # the kinds a preview shows as page pictures
MAX_BYTES = 50_000_000  # one file: a long deck full of pictures fits, a video does not
PREVIEW_PAGES = 60  # the pages a preview draws: a long document shows its start, and the file holds the rest
TEXT_BYTES = 600_000  # the bytes of a text file a preview shows: a long log shows its start
HTML_BYTES = 5_000_000  # a saved page larger than this is not put in the preview's frame
PAGE_PX = 1100  # the width a page picture is drawn at, whatever the page's size: sharp in the pane, small on disk
CONVERT_S = 180  # seconds LibreOffice may take for one file before it is stopped
FIRST_RUN_S = 900  # seconds render/run.sh may take: the first call may build the render image
LOCK = threading.Lock()  # one preview made at a time: LibreOffice and the pictures are the heavy part
ODD = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')  # never in a file name here: Windows refuses them, and so does a backup's restore (backup.ODD_NAME)
RESERVED = re.compile(r"(?i)(?:con|prn|aux|nul|com\d|lpt\d)")  # names Windows keeps for its devices, with any extension
MAT_ID = re.compile(r"m\d{1,6}")  # a material's id, as add() makes them


# ---------------------------------------------------------------- where they are kept


def folder(ws, jid: str) -> Path:
    """A job's materials folder (job_dir checks the id first, so it can never leave jobs/)."""
    return ws.job_dir(jid) / "materials"  # jobs/<job>/materials/


def records(ws, jid: str) -> list[dict]:
    """Every record of the job's index, the removed ones too, in the order they came."""
    items = read_json(folder(ws, jid) / "index.json", [])  # the index, or nothing yet
    return [r for r in items if isinstance(r, dict) and MAT_ID.fullmatch(str(r.get("id") or "")) and r.get("kind") in KINDS
            and isinstance(r.get("sha256"), str)] if isinstance(items, list) else []  # a hand-edited line that is no record is left out


def removed(ws, jid: str) -> set[str]:
    """The ids taken off the list."""
    got = read_json(folder(ws, jid) / "removed.json", [])  # undo writes this file back
    return {str(x) for x in got} if isinstance(got, list) else set()  # an odd file removes nothing


def removed_days(ws, jid: str) -> dict[str, str]:
    """The day each id was taken off ({} for a removal made before the day was kept)."""
    got = read_json(folder(ws, jid) / "removed_at.json", {})  # written with removed.json, in the same undo step
    return {str(k): str(v) for k, v in got.items()} if isinstance(got, dict) else {}  # an odd file says no day


def removed_records(ws, jid: str) -> list[dict]:
    """The records taken off the list and not deleted for good, in the order they came (the Removed list's rows)."""
    if not folder(ws, jid).is_dir():  # most jobs have no materials: nothing to read
        return []
    gone = removed(ws, jid)  # taken off
    return [r for r in records(ws, jid) if r["id"] in gone]  # still on disk, waiting


def view(rec: dict) -> dict:
    """What the page and the API get of a record: everything but the file's name in the folder."""
    return {k: rec.get(k) for k in ("id", "title", "name", "kind", "size", "added", "sha256")}  # the folder stays the server's


def listing(ws, jid: str) -> list[dict]:
    """The job's materials still on its list, in the order they came."""
    if not folder(ws, jid).is_dir():  # most jobs have none: no file to read
        return []
    gone = removed(ws, jid)  # taken off
    return [view(r) for r in records(ws, jid) if r["id"] not in gone]  # the rest, as the page shows them


def find(ws, jid: str, mid: str) -> dict | None:
    """One material still on the list, by its id, or None."""
    if not MAT_ID.fullmatch(mid or "") or mid in removed(ws, jid):  # a made-up id, or one taken off
        return None
    return next((r for r in records(ws, jid) if r["id"] == mid), None)  # its record


def path_of(ws, jid: str, rec: dict) -> Path:
    """Where a material's file is: in the job's folder, whatever the record says."""
    return folder(ws, jid) / Path(str(rec.get("file") or "")).name  # the name alone, never a path from the record


# ---------------------------------------------------------------- bringing one in


def safe_name(name: str) -> tuple[str, str]:
    """(stem, kind) of a file name as it is kept: no folders of any system, no character a system refuses, no device name of
    Windows, at most 180 bytes. Raises ValueError("material_kind") for a kind a job does not keep."""
    base = unicodedata.normalize("NFC", re.split(r"[\\/]", str(name or ""))[-1])  # the name without its folders, in one spelling
    stem, dot, ext = base.rpartition(".")  # the last extension decides the kind
    ext = ext.lower().strip()  # NOTES.MD is a markdown file too
    ext = {"jpeg": "jpg"}.get(ext, ext)  # a phone's photo.jpeg is a picture like photo.jpg, kept under the one kind
    if not dot or ext not in KINDS:  # no extension, or a kind not kept
        raise ValueError("material_kind")  # the page names the kinds kept
    stem = re.sub(r"\s+", " ", ODD.sub("_", stem)).strip(" .")  # refused characters out, runs of spaces as one, no leading or trailing dot
    if RESERVED.fullmatch(stem.split(".")[0]):  # CON.md cannot be made on Windows
        stem = "_" + stem  # a mark before it, and it can
    while len(f"{stem}.{ext}".encode("utf-8")) > 180:  # a disk takes 255 bytes of a name: room for the number of a twin
        stem = stem[:-1]  # one character fewer, never half of one
    return stem.strip(" .") or "file", ext  # never empty


def free_name(taken: set[str], stem: str, ext: str) -> tuple[str, int]:
    """(the first name not taken, its number): "notes.md" and 1, then "notes (2).md" and 2 ... Names are compared without
    case, as Windows and macOS compare them."""
    name, n = f"{stem}.{ext}", 1  # the name itself first
    while name.lower() in taken:  # its twin is there
        n += 1  # the next number
        name = f"{stem} ({n}).{ext}"  # before the extension
    return name, n


def title_of(name: str, n: int) -> str:
    """The name a material is listed under: the stem it came with, characters a disk refuses and all, and the number its
    file took when the name was taken."""
    stem = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", "", re.split(r"[\\/]", name)[-1].rpartition(".")[0])).strip()[:120] or "file"  # no control characters, one line
    return stem if n == 1 else f"{stem} ({n})"  # a twin says which one it is


def add(ws, jid: str, name: str, data: bytes) -> dict:
    """Keep one file as a job's material, byte for byte, and list it. Returns its record. Raises ValueError with a code: job,
    material_kind, empty, too_large, not_kept."""
    try:
        card = ws.job(jid)  # the job's card on the board
    except ValueError:  # an id no folder could have
        card = None
    if not card or card.get("removed"):  # no such job (the general edition is no job: it has no interview), or one in the Trash
        raise ValueError("job")
    stem, ext = safe_name(name)  # its kept name and kind
    if not data:  # nothing in it
        raise ValueError("empty")
    if len(data) > MAX_BYTES:  # over the cap (the upload's own check stops it sooner)
        raise ValueError("too_large")
    digest = hashlib.sha256(data).hexdigest()  # what came in
    with ws.lock:  # one writer: two uploads never take the same name or id
        d = folder(ws, jid)  # jobs/<job>/materials/
        d.mkdir(parents=True, exist_ok=True)  # made on first use
        raw = read_json(d / "index.json", [])  # the index as written: the records, and the ids left by deletions
        raw = [r for r in raw if isinstance(r, dict) and MAT_ID.fullmatch(str(r.get("id") or ""))] if isinstance(raw, list) else []  # a hand-edited line with no id goes
        items = records(ws, jid)  # every record, the removed ones too: their files are still here
        taken = {p.name.lower() for p in d.iterdir()} | {str(r.get("file") or "").lower() for r in items}  # on disk and in the index
        file, twin = free_name(taken, stem, ext)  # a twin gets a number
        dest = d / file  # where it is kept
        tmp = tmp_name(dest)  # beside it, unique to this writer
        tmp.write_bytes(data)  # the whole file
        retried(os.replace, tmp, dest)  # in place at once: a crash never leaves half a file under the name
        if sha256(dest) != digest:  # read back: what is on disk is what came in
            dest.unlink(missing_ok=True)  # never listed half kept
            raise ValueError("not_kept")
        n = 1 + max([int(r["id"][1:]) for r in raw] or [0])  # the next id: ids are never used twice, a deleted one's neither
        given = unicodedata.normalize("NFC", re.split(r"[\\/]", str(name))[-1])  # the name it came with, without its folders
        if len(given) > 200:  # a name longer than any list shows: shortened before its extension, which says its kind
            given = given[:200 - len(ext) - 1].rstrip() + "." + given.rpartition(".")[2]
        rec = {"id": f"m{n}", "title": title_of(given, twin), "name": given,  # its id, the name it is listed under, the name it came with
               "file": file, "kind": ext, "size": len(data), "added": today(), "sha256": digest}  # where it is, what it is, when, and its hash
        write_json(d / "index.json", raw + [rec])  # listed after the others, the deleted ones' ids kept
    return view(rec)  # as the page shows it


def remove(ws, jid: str, mid: str) -> None:
    """Take a material off the job's list. One undo step brings it back, and so does the Removed list; its file stays in the
    folder until it is deleted for good."""
    rec = find(ws, jid, mid)  # still on the list
    if not rec:  # gone, or never there
        raise ValueError("material")  # a stale page
    rels = [f"jobs/{jid}/materials/removed.json", f"jobs/{jid}/materials/removed_at.json"]  # the two files it changes
    with ws.change({"code": "undo_remove_job_material", "title": rec["title"]}, rels):  # one undo step
        write_json(folder(ws, jid) / "removed.json", sorted(removed(ws, jid) | {mid}))  # one more id off the list
        write_json(folder(ws, jid) / "removed_at.json", {**removed_days(ws, jid), mid: now_minute()})  # and when it went: the day and the hour


def put_back(ws, jid: str, mid: str) -> dict:
    """A material taken off, back on the job's list. One undo step takes it off again. Returns its record as the page shows it."""
    rec = next((r for r in removed_records(ws, jid) if r["id"] == mid), None)  # taken off, not deleted for good
    if not rec:  # back already, deleted, or never there
        raise ValueError("removed")  # a stale page
    rels = [f"jobs/{jid}/materials/removed.json", f"jobs/{jid}/materials/removed_at.json"]  # the files remove() changed
    with ws.change({"code": "undo_put_back", "title": rec["title"]}, rels):  # undo takes it off again
        write_json(folder(ws, jid) / "removed.json", sorted(removed(ws, jid) - {mid}))  # on the list again
        write_json(folder(ws, jid) / "removed_at.json", {k: v for k, v in removed_days(ws, jid).items() if k != mid})  # no day of removal
    return view(rec)


def purge(ws, jid: str, mid: str) -> dict:
    """Delete a material that was taken off, for good: its file, its page pictures, its record (only its id stays, so the id
    is never given again) and its place in removed.json. The caller (removed.py) holds LOCK, so no page picture of it is
    being drawn, and rewrites the undo steps. Returns the record it had."""
    with ws.lock:  # no other write meets this one
        rec = next((r for r in removed_records(ws, jid) if r["id"] == mid), None)  # taken off, not deleted already
        if not rec:  # back on the list, deleted, or never there
            raise ValueError("removed")
        d = folder(ws, jid)  # jobs/<job>/materials/
        try:
            retried(lambda: path_of(ws, jid, rec).unlink(missing_ok=True))  # the file itself, first, waited for a moment while it is held
        except OSError as exc:  # another program has it open (Windows): nothing else changes
            raise ValueError("delete_failed") from exc
        shutil.rmtree(preview_dir(ws, jid, mid), ignore_errors=True)  # its page pictures and the PDF made of it
        raw = read_json(d / "index.json", [])  # the index as written
        write_json(d / "index.json", [{"id": mid, "gone": True} if isinstance(r, dict) and r.get("id") == mid else r
                                      for r in (raw if isinstance(raw, list) else [])])  # its record down to its id
        write_json(d / "removed.json", sorted(removed(ws, jid) - {mid}))  # nothing to list as taken off
        write_json(d / "removed_at.json", {k: v for k, v in removed_days(ws, jid).items() if k != mid})  # nor its day
    return rec


def export(ws, jid: str, mid: str) -> list[str]:
    """A copy of a material on the Desktop under the name it came with, never over another file, read back against the hash
    it came in with. Returns the name written. Raises ValueError: material, material_changed, copy_unreadable."""
    from .tasks import desktop_dir  # the person's Desktop (OFFEROWL_DESKTOP in tests and in the container)
    rec = find(ws, jid, mid)  # still on the list
    if not rec:  # gone, or never there
        raise ValueError("material")
    src = path_of(ws, jid, rec)  # the kept file
    if not src.is_file() or sha256(src) != rec["sha256"]:  # changed or gone since it came in: not what the person added
        raise ValueError("material_changed")
    dest = desktop_dir()  # the Desktop
    dest.mkdir(parents=True, exist_ok=True)  # a fresh Desktop folder in a test or a container
    stem, ext = safe_name(rec.get("name") or rec["file"])  # the name it came with, safe on every system
    name, _ = free_name({p.name.lower() for p in dest.iterdir()}, stem, ext)  # never over a file already there
    shutil.copyfile(src, dest / name)  # a plain copy: the kept one stays
    if sha256(dest / name) != rec["sha256"]:  # read back, byte for byte
        (dest / name).unlink(missing_ok=True)  # nothing half copied stays
        raise ValueError("copy_unreadable")
    return [name]  # the name, never the folder


def answer(ws, jid: str, rec: dict) -> tuple[bytes, str, dict]:
    """(bytes, type, headers) of a material's file as it is kept. A text file names its character set; every file carries
    its own name for a browser's Save as; a web page opens sandboxed, so it can run nothing in the panel's address."""
    data = path_of(ws, jid, rec).read_bytes()  # byte for byte
    kind = rec["kind"]  # the extension decided it
    ctype = KINDS[kind]  # the type of its kind
    if kind in TEXT:  # text: the browser must know how to read it
        ctype += next((f"; charset={label}" for label, enc in (("utf-8", "utf-8"), ("euc-kr", "cp949")) if decodes(data, enc)), "")  # euc-kr is the label browsers read Korean Windows text by
    name = str(rec.get("name") or rec["file"])  # the name it came with
    ascii_name = re.sub(r'[^\x20-\x7e]|["\\]', "_", name)  # for an old browser: plain letters only
    headers = {"Content-Disposition": f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(name, safe='')}"}  # shown where the browser can, saved under its name
    if kind == "html":  # a page of someone else's making, at the panel's own address
        headers["Content-Security-Policy"] = "sandbox"  # with the panel's own policy both apply: no script, no form, an origin of its own
    return data, ctype, headers


def decodes(data: bytes, enc: str) -> bool:
    """True when the bytes read as this encoding."""
    try:
        data.decode(enc)  # strict
        return True
    except UnicodeDecodeError:  # another encoding
        return False


# ---------------------------------------------------------------- previews


def decode(data: bytes, final: bool = True) -> str:
    """Text from a file's bytes: UTF-8, else the Korean Windows encoding, else UTF-8 with stand-ins. With final False the
    bytes are a file's start, and a character cut in two at their end is left out rather than read wrong."""
    for enc in ("utf-8-sig", "cp949"):  # the encodings a person's notes are in, most likely first
        try:
            return codecs.getincrementaldecoder(enc)().decode(data, final=final)  # strict, so a wrong guess fails here
        except UnicodeDecodeError:  # not this one
            continue
    return data.decode("utf-8", "replace")  # anything else: readable, with stand-ins


def read_text(path: Path) -> tuple[str, bool]:
    """(text, cut) of a text file's start; cut is True when the file is longer than a preview shows."""
    with path.open("rb") as f:  # only the start of a long file is read
        data = f.read(TEXT_BYTES + 1)  # one byte more says whether there is more
    cut = len(data) > TEXT_BYTES  # longer than shown
    return decode(data[:TEXT_BYTES], final=not cut), cut  # what is shown


FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")  # a code fence opens or closes
HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")  # a heading, with closing marks dropped
RULE = re.compile(r"^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")  # a horizontal rule
ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")  # a list item, with its indent and its mark
QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")  # a quoted line
ROW = re.compile(r"^\s*\|(.*)\|\s*$")  # a table row between bars
SEP = re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+(?:\s*:?-{2,}:?\s*)?\|?\s*$")  # a table's line under its head
UNDER = re.compile(r"^\s{0,3}(=+|-+)\s*$")  # the line under a heading written the other way (Title, then ===)


def plain(s: str) -> str:
    """Markdown words outside a code span: pictures and links by their words, tags out, the marks of bold, strike-through
    and highlight taken off, entities as characters."""
    held = []  # characters written with a backslash, set aside so no rule below takes them for a mark
    def hold(m):  # one escaped character
        held.append(m.group(1))  # kept as written
        return f"\ue000{len(held) - 1}\ue001"  # a stand-in no rule matches
    s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|<>~=])", hold, s)  # \* is a star, not a mark
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)  # a picture: its words
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)  # a link: its words (the address stays in the file)
    s = re.sub(r"<(https?://[^>\s]+)>", r"\1", s)  # an address in angle brackets: the address
    s = re.sub(r"</?[A-Za-z][^>]*>", "", s)  # tags written into the notes
    s = re.sub(r"\*\*|__|~~|==", "", s)  # bold, strike-through and highlight marks
    s = re.sub(r"(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w)", "", s)  # italic stars; a star between spaces (2 * 3) stays
    s = re.sub(r"\ue000(\d+)\ue001", lambda m: held[int(m.group(1))], s)  # the escaped characters back, as themselves
    return html.unescape(s)  # &amp; and the like as their characters


def inline(s: str) -> str:
    """One line of markdown as plain words; a code span keeps its words as written, without its backticks. Nothing of it
    becomes HTML: the page sets every word as text."""
    parts = re.split(r"`([^`]*)`", s)  # odd parts are code spans
    return re.sub(r"[ \t]+", " ", "".join(p if i % 2 else _words(p) for i, p in enumerate(parts))).strip()  # one space between words


def _words(s: str) -> str:
    """Plain words with every web address kept whole: a link written [words](address) is its words and its address, which
    the panel shows as a link, and an address is held out of the marks' rules (an underscore in it is not emphasis)."""
    held = []  # the addresses, in order

    def hold(u: str) -> str:
        held.append(u)  # kept as written
        return f"\ue002{len(held) - 1}\ue003"  # a stand-in no rule matches

    s = re.sub(r"(?<!!)\[([^\]]+)\]\((https?://[^)\s]+)(?:\s+\"[^\"]*\")?\)", lambda m: f"{m.group(1)} ({hold(m.group(2))})", s)  # a link: its words, its address
    s = re.sub(r"<(https?://[^>\s]+)>", lambda m: hold(m.group(1)), s)  # an address in angle brackets
    s = re.sub(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&*+,;=%()]+", lambda m: hold(m.group(0)), s)  # a bare address
    return re.sub(r"\ue002(\d+)\ue003", lambda m: held[int(m.group(1))], plain(s))  # the marks out, the addresses back


def md_blocks(text: str) -> list[dict]:
    """Markdown as blocks the page draws as text: {"t": "h", "n": level}, "p", "li" (with its mark and depth), "quote", "row"
    (with its cells, "head" for a table's first row), "code" (the lines as written) and "hr". Every text is plain words."""
    out, para, code, fence = [], [], None, ""  # blocks, the paragraph being read, the code block being read, its fence
    def flush():  # the paragraph read so far ends here
        if para:  # there is one
            out.append({"t": "p", "text": inline(" ".join(para))})  # wrapped lines join into one paragraph
            para.clear()  # the next one starts empty
    for line in text.splitlines():  # one pass, line by line
        fm = FENCE.match(line)  # a fence on this line?
        if code is not None:  # inside a code block: lines as written, until its own fence
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):  # the fence that closes it
                out.append({"t": "code", "text": "\n".join(code)})  # the block, whole
                code = None  # back to text
            else:
                code.append(line)  # one more line of code, spaces and all
            continue
        if fm:  # a code block opens
            flush()  # what came before it ends
            code, fence = [], fm.group(1)  # its lines, and the fence that will close it
            continue
        if not line.strip():  # a blank line ends a paragraph
            flush()
            continue
        under = UNDER.match(line)  # Title, then === or ---
        if under and para:  # the paragraph above is a heading
            out.append({"t": "h", "n": 1 if under.group(1)[0] == "=" else 2, "text": inline(" ".join(para))})  # = for the first level, - for the second
            para.clear()  # used
            continue
        hm = HEAD.match(line)  # a heading?
        if hm:
            flush()  # a heading ends a paragraph
            out.append({"t": "h", "n": len(hm.group(1)), "text": inline(hm.group(2))})  # its level and words
            continue
        if RULE.match(line):  # a rule between parts
            flush()
            out.append({"t": "hr"})
            continue
        rm = ROW.match(line)  # a table row?
        if rm:
            flush()
            if SEP.match(line):  # the line under a table's head
                if out and out[-1]["t"] == "row":  # the row above is the head
                    out[-1]["head"] = True
                continue
            out.append({"t": "row", "cells": [inline(c) for c in rm.group(1).split("|")]})  # its cells as words
            continue
        im = ITEM.match(line)  # a list item?
        if im:
            flush()
            mark = im.group(2) if im.group(2)[0].isdigit() else ""  # a numbered item keeps its number; a bullet is drawn
            out.append({"t": "li", "text": inline(im.group(3)), "mark": mark, "depth": min(len(im.group(1).expandtabs(4)) // 2, 4)})  # nested lists step in, four steps at most
            continue
        qm = QUOTE.match(line)  # a quoted line?
        if qm:
            flush()
            if out and out[-1]["t"] == "quote":  # the quote goes on
                out[-1]["text"] = (out[-1]["text"] + " " + inline(qm.group(1))).strip()  # one quote, its lines joined
            else:
                out.append({"t": "quote", "text": inline(qm.group(1))})  # a new quote
            continue
        para.append(line.strip())  # a line of a paragraph
    flush()  # the last paragraph
    if code:  # a fence never closed: what it held
        out.append({"t": "code", "text": "\n".join(code)})
    return out


def frame_html(text: str) -> str:
    """A saved page for the preview's frame: its scripts, its base address and any redirect out (the frame's sandbox runs
    nothing either), and links a click cannot follow. The frame's page takes the panel's policy: nothing loads from elsewhere."""
    out = re.sub(r"<script\b[^>]*>.*?</script\b[^>]*>", "", text, flags=re.S | re.I)  # scripts with their code (an end tag may hold more, "</script foo>")
    out = re.sub(r"<script\b[^>]*>", "", out, flags=re.I)  # a script tag left open
    out = re.sub(r"<base\b[^>]*>", "", out, flags=re.I)  # no other address for its links and pictures
    out = re.sub(r"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh[^>]*>", "", out, flags=re.I)  # no redirect to another page
    return out + "<style>a { pointer-events: none; }</style>"  # last, so the page keeps its own doctype; a link in the frame would leave it


def preview(tasks, jid: str, rec: dict) -> dict:
    """What the page shows of a material, by its kind: {"view": "pages", "pages", "of", "more", "wide"} (PDF, PowerPoint,
    Word), {"view": "text", "text", "cut"} (text, Python), {"view": "blocks", "blocks", "cut"} (Markdown), {"view": "frame",
    "html"} (HTML) or {"view": "image"} (PNG, JPEG); {"missing": code} when it cannot be shown here: no_tools (no
    LibreOffice or PDF reader for it), unreadable, too_large."""
    kind = rec["kind"]  # what it is
    src = path_of(tasks.ws, jid, rec)  # the kept file
    if not src.is_file():  # taken away by hand
        return {"kind": kind, "missing": "unreadable"}
    if kind in ("png", "jpg"):  # the file itself is the picture
        return {"kind": kind, "view": "image"}
    if kind in ("txt", "py"):  # the words as written
        text, cut = read_text(src)  # the start of a long file
        return {"kind": kind, "view": "text", "text": text, "cut": cut}
    if kind == "md":  # notes as headings, paragraphs, lists, tables and code
        text, cut = read_text(src)  # the start of a long file
        return {"kind": kind, "view": "blocks", "blocks": md_blocks(text), "cut": cut}
    if kind == "html":  # a page, in a frame that runs nothing
        if src.stat().st_size > HTML_BYTES:  # too heavy for a frame in the panel
            return {"kind": kind, "missing": "too_large"}
        return {"kind": kind, "view": "frame", "html": frame_html(decode(src.read_bytes()))}  # whole: a page cut in two would not read
    if kind in PAGED:  # PDF, PowerPoint, Word
        return pages(tasks, jid, rec, src)  # page pictures
    return {"kind": kind, "missing": "unreadable"}  # a kind with no view of its own


def preview_dir(ws, jid: str, mid: str) -> Path:
    """Where a material's page pictures are kept."""
    return folder(ws, jid) / ".preview" / mid  # beside the files, hidden on a Mac and on Linux


def page_file(ws, jid: str, rec: dict, n: int) -> Path | None:
    """One page picture of a preview that was made from this very file, or None."""
    cache = preview_dir(ws, jid, rec["id"])  # its pictures
    meta = read_json(cache / "preview.json", {})  # what they were made from
    f = cache / f"p-{n}.png"  # the page asked for
    return f if meta.get("sha256") == rec["sha256"] and 1 <= n <= int(meta.get("pages") or 0) and f.is_file() else None  # only a page of this file


def png_size(path: Path) -> tuple[int, int]:
    """(width, height) of a PNG, from its header."""
    with path.open("rb") as f:  # the first bytes say it
        head = f.read(24)  # the signature and the IHDR chunk
    return struct.unpack(">II", head[16:24]) if len(head) == 24 and head[:8] == b"\x89PNG\r\n\x1a\n" else (0, 0)  # width, height


def pages(tasks, jid: str, rec: dict, src: Path) -> dict:
    """The page pictures of a PDF, or of the PDF LibreOffice makes of a deck or a Word file, made once and kept beside the
    files. A preview that could not be made is not kept, so a later look tries again (the tools may be there by then)."""
    import pdftools  # src/pdftools.py: poppler or PDFium on this PC
    cache = preview_dir(tasks.ws, jid, rec["id"])  # its pictures
    shown = lambda m: {"kind": rec["kind"], "view": "pages", **{k: m[k] for k in ("pages", "of", "more", "wide")}}  # noqa: E731  what the page gets of a made preview
    meta = read_json(cache / "preview.json", None)  # made before?
    if isinstance(meta, dict) and meta.get("sha256") == rec["sha256"] and (cache / "p-1.png").is_file():  # made from this very file
        return shown(meta)  # at once
    with LOCK:  # one at a time; a request that waited finds them made
        if not find(tasks.ws, jid, rec["id"]):  # taken off or deleted for good while this one waited (a deleted job's id is refused here too)
            return {"kind": rec["kind"], "missing": "unreadable"}  # no picture of it is drawn again
        meta = read_json(cache / "preview.json", None)  # made while this one waited?
        if isinstance(meta, dict) and meta.get("sha256") == rec["sha256"] and (cache / "p-1.png").is_file():
            return shown(meta)
        reader = pdftools.reader()  # poppler or PDFium on this PC, else the render container's poppler
        if not reader and (resume_local() or not shutil.which("docker")):  # no reader here, and no container to draw the pages in
            return {"kind": rec["kind"], "missing": "no_tools"}
        shutil.rmtree(cache, ignore_errors=True)  # what an older or a stopped try left
        cache.mkdir(parents=True)  # a clean folder
        pdf = src  # a PDF is its own pages
        if rec["kind"] != "pdf":  # a deck or a Word file: LibreOffice prints it first
            why = convert(src, cache / "doc.pdf")  # "" when the PDF is there
            if why:  # it could not be printed here
                shutil.rmtree(cache, ignore_errors=True)  # nothing half made is kept
                return {"kind": rec["kind"], "missing": why}
            pdf = cache / "doc.pdf"  # its pages
        total, width = 0, 0.0  # the page count and the first page's width, when a reader can say
        if reader:  # read here, at once
            try:
                got = pdftools.info(pdf)  # {"pages", "width", "height"} in points
                total, width = int(got["pages"]), float(got["width"])
            except Exception as exc:  # noqa: BLE001  a damaged file says nothing; the drawing below says whether it reads
                log.info("material %s: no page size: %s", rec["id"], exc)  # for the log
        dpi = max(40, min(150, round(PAGE_PX * 72 / width))) if width > 0 else 100  # the same width in pixels for an A4 page and a slide
        try:
            with tasks.render_lock if not reader else contextlib.nullcontext():  # the container's drawing shares one working folder with the builds
                n = tasks._previews(pdf, cache, "p", dpi, last=PREVIEW_PAGES)  # p-1.png ... as the editions' pages are drawn
        except Exception as exc:  # noqa: BLE001  a damaged PDF, or a reader that stopped on it
            log.warning("material %s: pages not drawn: %s", rec["id"], exc)  # for the log
            n = 0  # nothing to show
        if not n:  # not one page
            shutil.rmtree(cache, ignore_errors=True)  # nothing half made is kept
            return {"kind": rec["kind"], "missing": "unreadable"}
        w, h = png_size(cache / "p-1.png")  # the first page's picture
        more = total > n or (not total and n >= PREVIEW_PAGES)  # pages past the preview's: counted, or likely when no reader could count them
        meta = {"sha256": rec["sha256"], "pages": n, "of": max(total, n), "more": more, "wide": w > h, "dpi": dpi}  # what was made, and from what
        write_json(cache / "preview.json", meta)  # last: a stopped try leaves no record that says it was made
    return shown(meta)


def resume_local() -> bool:
    """True when the render toolchain runs in this process's own system (inside the container, or the browser renderer)."""
    import resume  # src/resume.py: which renderer is in use
    return resume.local()  # its own rule


def soffice_path() -> str | None:
    """This PC's own LibreOffice: on PATH, else where its installer puts it on Windows and macOS (neither adds it to PATH)."""
    found = shutil.which("soffice") or shutil.which("libreoffice")  # Linux packages, or a PATH the person set
    if found:  # on PATH
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):  # Windows: both program folders
        if base and (Path(base) / "LibreOffice" / "program" / "soffice.exe").is_file():  # its installer's place
            return str(Path(base) / "LibreOffice" / "program" / "soffice.exe")
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")  # macOS: the app as dragged into Applications
    return str(mac) if mac.is_file() else None  # none here


def convert(src: Path, dest: Path) -> str:
    """LibreOffice's PDF of a Word or PowerPoint file, written to dest, made in the render toolchain as src/resume.py makes a
    resume's PDF: in the render container through render/run.sh, at once when this process runs inside it, or with this PC's
    own LibreOffice with the browser renderer. Returns "" when made, else why not: no_tools, unreadable."""
    import resume  # src/resume.py: the renderer in use and the font step
    inside = resume.in_container()  # this process runs in the render container or the app image: LibreOffice is here
    container = not inside and not resume.local()  # the container renderer: through render/run.sh
    if container and not shutil.which("docker"):  # no Docker to start it with
        return "no_tools"
    soffice = "soffice" if inside or container else soffice_path()  # the browser renderer: this PC's own LibreOffice, if it has one
    if not soffice:  # none
        return "no_tools"
    work = Path(tempfile.mkdtemp(prefix="offerowl-convert-")) if not container else ROOT / "output" / "_materials" / os.urandom(6).hex()  # the container sees only the repository
    try:
        work.mkdir(parents=True, exist_ok=True)  # the container's folder is made here
        staged = work / f"in{src.suffix.lower()}"  # a plain name: the person's file name never reaches a command line
        shutil.copyfile(src, staged)  # the file as kept
        script = (resume.FONTS + f'timeout {CONVERT_S} soffice "-env:UserInstallation=$3" --headless --convert-to pdf --outdir "$1" "$2"')  # the fonts first, as for a resume; a profile of its own, so a build's LibreOffice is never in the way
        if container:  # run.sh mounts the repository at /work
            rel = work.relative_to(ROOT).as_posix()  # the folder as the container sees it
            cmd, limit = [str(ROOT / "render" / "run.sh"), "bash", "-c", script, "_", rel, f"{rel}/{staged.name}", "file:///tmp/offerowl-lo"], FIRST_RUN_S  # the container's own /tmp is fresh
        elif inside:  # the app image: the same script, here
            cmd, limit = ["bash", "-c", script, "_", str(work), str(staged), (work / "lo").as_uri()], CONVERT_S + 30
        else:  # this PC's LibreOffice, without the container's font step
            cmd, limit = [soffice, f"-env:UserInstallation={(work / 'lo').as_uri()}", "--headless", "--convert-to", "pdf", "--outdir", str(work), str(staged)], CONVERT_S
        code, out = run(cmd, limit)  # bounded in time
        made = work / "in.pdf"  # LibreOffice names it after the file
        if code != 0 or not made.is_file() or made.stat().st_size == 0:  # it did not print
            log.warning("material conversion failed (%s): %s", code, out[-2000:])  # the tool's words, for the log only
            return "unreadable"
        shutil.move(str(made), str(dest))  # beside the material's pictures
        return ""  # made
    except OSError as exc:  # a folder that cannot be written, a tool that cannot start
        log.warning("material conversion failed: %s", exc)  # for the log
        return "unreadable"
    finally:
        shutil.rmtree(work, ignore_errors=True)  # the copy of the person's file does not stay in the engine's folder


def run(cmd: list[str], timeout: float) -> tuple[int | None, str]:
    """(exit code, output) of a converter, in a process group of its own so that one that hangs is stopped whole. None for
    the code when it ran out of time."""
    p = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # one stream for the log
                         start_new_session=True)  # its own group: LibreOffice starts a child of its own
    try:
        out, _ = p.communicate(timeout=timeout)  # waits, with a limit
    except subprocess.TimeoutExpired:  # hung on a file
        try:
            os.killpg(p.pid, signal.SIGKILL)  # the whole group
        except (AttributeError, OSError):  # Windows has no groups of this kind
            p.kill()  # the process itself
        p.communicate()  # reaped
        return None, "timed out"
    return p.returncode, (out or b"").decode("utf-8", "replace")  # its words, for the log
