"""What the export writes besides the checked PDFs, and the portfolio kept on the Desktop.

The export (Tasks.export) copies an edition's checked PDFs to the Desktop. Two settings add files made from them at that
moment, each checked before it goes:

- export_extras: the resume's and the cover letter's Word files, made ready for Word (src/docx_word.py: the line heights
  LibreOffice set, Pretendard embedded, the PDF's title and author) and, where this PC reaches Word, opened in it: Word's
  page count must be the PDF's (src/office_check.py). A Word file the person brought in goes as it came.
- export_pptx: the portfolio deck as a PowerPoint file (src/deck_pptx.py), read back against the PDF, and opened in
  PowerPoint where this PC reaches it: its slide count must be the PDF's page count.

A file that fails stays home and is named in the export's answer under "refused", with the reason; the PDFs go all the
same. On a PC with no Office the opening is left out, and nothing is said about it.

desk_portfolio, a third setting, keeps the general edition's portfolio on the Desktop: each build of it that passes its
checks copies its deck PDF there, one file per language under a fixed name, and replaces only the copy it wrote itself,
known by the hash it recorded (the workspace's out/desk_portfolio.json). A file of that name it did not write, or one
the person changed since, is never touched: the copy takes the next free name instead. A blind edition is never copied.
"""
from __future__ import annotations

import logging  # the panel's log
import os  # an atomic replace on the Desktop
import re  # the names
import shutil  # the copies
import threading  # one writer of the record at a time
from pathlib import Path  # paths

from .drafts import GENERAL  # the edition with no job
from .workspace import read_json, retried, sha256, tmp_name, write_json  # the record, the hash that recognises a copy, a temporary name of this writer's own
import subprocess  # programs started
import sys  # the interpreter and the import path


# ---------------------------------------------------------------- the Desktop and the file manager (from apps/api/tasks.py)

WSL_DESKTOP = []  # the Windows Desktop as WSL sees it, looked up once ([] until then, [None] when there is none)


from open_page import in_wsl  # noqa: E402  this server runs inside WSL on a Windows PC (src/open_page.py: the engine's one test of it)


def windows_desktop() -> Path | None:
    """Under WSL, the person's Windows Desktop (the folder OneDrive may have moved), in the form WSL reads it; None when
    Windows does not answer. PowerShell is asked to answer in UTF-8: piped, it would answer in the console's code page."""
    if WSL_DESKTOP:  # asked before
        return WSL_DESKTOP[0]
    found = None  # until Windows answers
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",  # the shell's own answer, as on Windows
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; [Environment]::GetFolderPath('Desktop')"],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=15)
        lines = [x.strip() for x in r.stdout.decode("utf-8", "replace").splitlines() if x.strip()]  # its lines, a profile's greeting aside
        if r.returncode == 0 and lines and re.match(r"^[A-Za-z]:\\", lines[-1]):  # a drive path, as Windows writes it
            u = subprocess.run(["wslpath", "-u", lines[-1]], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)  # the same folder from WSL (a Korean user name too)
            if u.returncode == 0 and u.stdout.strip() and Path(u.stdout.strip()).is_dir():  # there
                found = Path(u.stdout.strip())
    except (OSError, subprocess.SubprocessError):  # no interop, or it hung
        found = None  # the Linux Desktop then
    WSL_DESKTOP.append(found)  # once
    return found


def desktop_dir() -> Path:
    """The person's Desktop folder (OFFEROWL_DESKTOP overrides it): Windows' known folder, which OneDrive may move; the
    same Windows folder when the server runs in WSL; else ~/Desktop, or on Linux the folder xdg-user-dir names."""
    if os.environ.get("OFFEROWL_DESKTOP"):  # tests and unusual setups
        return Path(os.environ["OFFEROWL_DESKTOP"]).expanduser()  # the folder named, with ~ expanded
    if in_wsl():  # the person looks at the Windows Desktop, not the Linux home
        found = windows_desktop()  # asked once
        if found:
            return found
    if sys.platform == "win32":  # the shell's own answer
        try:
            import ctypes  # Windows API
            from ctypes import wintypes  # types
            from uuid import UUID  # the folder's GUID

            class GUID(ctypes.Structure):  # the struct SHGetKnownFolderPath takes
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),  # the GUID layout Windows expects
                            ("Data4", wintypes.BYTE * 8)]
            u = UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")  # FOLDERID_Desktop
            g = GUID(u.fields[0], u.fields[1], u.fields[2], (wintypes.BYTE * 8).from_buffer_copy(u.bytes[8:]))  # the known folder's id in that layout
            out = ctypes.c_wchar_p()  # the answer
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:  # 0 is S_OK: the shell answered
                return Path(out.value)  # where Windows shows the Desktop
        except (OSError, AttributeError, ValueError):  # an old Windows or no shell32: fall back
            pass  # fall through to the usual place
    if sys.platform.startswith("linux") and shutil.which("xdg-user-dir"):  # a localized Desktop name
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, encoding="utf-8", errors="replace")  # the Desktop's name in the person's language
        if r.returncode == 0 and r.stdout.strip():  # only a real answer counts
            return Path(r.stdout.strip())  # that folder
    return Path.home() / "Desktop"  # macOS and the rest


def open_in_files(path: Path) -> bool:
    """Show a folder in the system's file manager. False when this system has none to open."""
    try:
        if sys.platform == "win32":  # each system's own file manager
            os.startfile(str(path))  # noqa: S606  Explorer
        elif sys.platform == "darwin":  # Finder
            subprocess.Popen(["open", str(path)])  # Finder
        elif in_wsl() and shutil.which("explorer.exe"):  # WSL: Windows' own Explorer, given the folder's Windows path
            win = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5).stdout.strip()  # C:\... or \\wsl.localhost\...
            if not win:  # wslpath did not answer
                return False
            subprocess.Popen(["explorer.exe", win], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)  # never waited on: interop holds a call until Windows' side ends
        elif shutil.which("xdg-open"):  # a Linux desktop
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # the desktop's
        else:
            return False  # no file manager here (a server, WSL without one)
        return True  # it was asked to open
    except (OSError, subprocess.SubprocessError):  # the program could not start
        return False  # say so: the panel shows one line

log = logging.getLogger("offerowl.panel")  # the panel's log
RECORD = ("out", "desk_portfolio.json")  # the copies desk_portfolio wrote: {lang: {name, sha256}}
WORDS = {"ko": "포트폴리오", "en": "Portfolio"}  # the deck's word in a file name, as the export names it
DESK_LOCK = threading.Lock()  # a build and the switch turned on may keep the portfolio at once: the record is read and written by one


def safe_name(*parts: str) -> str:
    """A file name of these parts on any system: no character Windows refuses, spaces once, at most 120 characters."""
    return " ".join(re.sub(r'[\\/:*?"<>|]+', " ", " ".join(x for x in parts if x)).split())[:120]


def free_name(dest: Path, base: str, suffix: str) -> str:
    """base + suffix, or base (2) + suffix and on: the first name no file on the Desktop has."""
    name, n = base + suffix, 2  # first try
    while (dest / name).exists():  # never over another file
        name, n = f"{base} ({n}){suffix}", n + 1
    return name


def word_ready(tasks, out_dir: Path, f: str, tmp: Path, refused: list) -> Path | None:
    """The edition's Word file f (resume.docx or cover.docx) as it goes to the Desktop: the person's own as it came, else a
    Word-ready copy in tmp that Word, where this PC reaches it, lays out on as many pages as the PDF. None when it must
    stay home; refused then says why ({file, why})."""
    import docx_word  # src/docx_word.py: the copy and its read-back
    import office_check  # src/office_check.py: Word on this PC
    import pdfmeta  # src/pdfmeta.py: the PDF's title, author and pages
    src, pdf = out_dir / f, out_dir / f.replace(".docx", ".pdf")  # the Word file and the PDF typeset from it
    own = out_dir / ("own_" + f)  # the person's own Word file, when the edition came with one
    if own.is_file() and own.read_bytes() == src.read_bytes():  # theirs: never changed
        return src
    if not pdf.is_file():  # nothing to take its title from or measure it against: as the build wrote it
        return src
    meta = pdfmeta.read(pdf)  # the title and the author the export has checked
    title, author = meta.get("title") or "", meta.get("author") or ""
    made = tmp / f  # the copy
    try:
        docx_word.ready(src, made, title, author)  # line heights, fonts, title and author
        bad = docx_word.problems(made, title, author)  # read back
    except Exception as exc:  # noqa: BLE001  not a Word file of the shape the typesetting writes: this one file stays home, the PDFs still go
        bad = [f"{type(exc).__name__}: {exc}"]
    if bad:  # never a half-made copy
        log.warning("Word copy of %s not made: %s", f, bad)  # for the log only
        refused.append({"file": f, "why": "docx_unready"})
        return None
    if office_check.available("word"):  # Word on this PC: it lays the file out as the person who gets it will
        try:
            pages = office_check.count("word", made)
        except Exception as exc:  # noqa: BLE001  Word was there and did not open it, or Windows did not answer
            log.warning("Word did not open %s: %s", f, exc)
            refused.append({"file": f, "why": "word_unopened"})
            return None
        want = pdfmeta.pages(pdf)  # the PDF's pages
        if pages != want:  # Word breaks the pages elsewhere: this file would not be the document that was checked
            refused.append({"file": f, "why": f"word_pages:{pages}:{want}"})
            return None
    return made


def powerpoint(tasks, out_dir: Path, tmp: Path, refused: list) -> Path | None:
    """The deck as a PowerPoint file in tmp, read back against its PDF and, where this PC reaches PowerPoint, opened in it
    with as many slides as the PDF has pages. None when it must stay home; refused then says why."""
    import deck_pptx  # src/deck_pptx.py: the copy and its read-back
    import office_check  # src/office_check.py: PowerPoint on this PC
    import pdfmeta  # src/pdfmeta.py: the PDF's title and author
    pdf = out_dir / "deck.pdf"  # the checked deck
    meta = pdfmeta.read(pdf)  # its title and author
    title, author = meta.get("title") or "", meta.get("author") or ""
    made = tmp / "deck.pptx"  # the copy

    def pictures(p, folder: Path) -> list:  # the pages drawn on this PC, or in the typesetting's container
        n = tasks._previews(p, folder, "page", deck_pptx.DPI)  # page-1.png ...
        return [folder / f"page-{i}.png" for i in range(1, n + 1)]
    try:
        text = tasks.pdf_text(pdf)  # each page's words, a form feed after each
        slides = deck_pptx.make(pdf, made, title, author, pictures=pictures, text=lambda _p: text)
        bad = deck_pptx.problems(made, pdf, title, author, text.split("\f"))  # read back
    except (Exception, SystemExit) as exc:  # noqa: BLE001  no reader, no container, a page that would not draw: this one file stays home
        bad = [f"{type(exc).__name__}: {exc}"]
    if bad:  # never a half-made copy
        log.warning("PowerPoint copy not made: %s", bad)  # for the log only
        refused.append({"file": "deck.pptx", "why": "pptx_unmade"})
        return None
    if office_check.available("powerpoint"):  # PowerPoint on this PC
        try:
            shown = office_check.count("powerpoint", made)
        except Exception as exc:  # noqa: BLE001  PowerPoint was there and did not open it, or Windows did not answer
            log.warning("PowerPoint did not open the deck: %s", exc)
            refused.append({"file": "deck.pptx", "why": "ppt_unopened"})
            return None
        if shown != slides:  # not one slide per page
            refused.append({"file": "deck.pptx", "why": f"ppt_slides:{shown}:{slides}"})
            return None
    return made


def _record(tasks) -> dict:
    """The copies desk_portfolio wrote, by language."""
    rec = read_json(tasks.ws.path(*RECORD), {})  # kept with the workspace
    return rec if isinstance(rec, dict) else {}


def _ours(dest: Path, mine) -> bool:
    """The recorded copy is on the Desktop, byte for byte as it was written: this setting may replace it."""
    if not isinstance(mine, dict) or not isinstance(mine.get("name"), str) or not mine.get("sha256"):  # nothing recorded
        return False
    f = dest / Path(mine["name"]).name  # a name, never a path from the record
    return f.is_file() and sha256(f) == mine["sha256"]


def kept_names(tasks) -> list[str]:
    """The portfolio copies desk_portfolio keeps on the Desktop now (by the record, and still there), for the panel."""
    from .tasks import desktop_dir  # the person's Desktop
    rec = _record(tasks)  # what it wrote
    dest = desktop_dir()
    return [Path(rec[k]["name"]).name for k in ("ko", "en") if isinstance(rec.get(k), dict) and isinstance(rec[k].get("name"), str)
            and (dest / Path(rec[k]["name"]).name).is_file()]  # still on the Desktop


def kept_copy(tasks, lang: str, deck: Path) -> str | None:
    """The name of the portfolio desk_portfolio keeps on the Desktop for this language when it is this deck, byte for
    byte: the export then names it instead of writing a second copy beside it."""
    from .tasks import desktop_dir  # the person's Desktop
    if tasks.card.settings_fn().get("desk_portfolio") is not True:  # turned off: the export makes its own copy again
        return None
    mine = _record(tasks).get(lang)  # its copy in this language
    if not deck.is_file() or not isinstance(mine, dict) or mine.get("sha256") != sha256(deck):  # another deck
        return None
    return Path(mine["name"]).name if _ours(desktop_dir(), mine) else None  # there and unchanged


def keep_portfolio(tasks, lang: str) -> str | None:
    """With desk_portfolio on, the general edition's deck PDF in this language copied to the Desktop, when its build passed
    its checks: in place of the copy this setting wrote before (recognised by its recorded hash), else under the first free
    name. Returns the name on the Desktop, or None when nothing was copied."""
    from .tasks import desktop_dir, file_hash  # the Desktop, and the short hash a build records
    import pdfmeta  # src/pdfmeta.py: the deck's title and author
    if tasks.card.settings_fn().get("desk_portfolio") is not True:  # off unless asked for
        return None
    out_dir = tasks.build_dir(GENERAL, lang)  # the general edition in this language
    rec = read_json(out_dir / "build.json", {}) or {}  # what its build checked
    cover = rec.get("cover") if isinstance(rec.get("cover"), dict) else {}  # the letter's own result
    deck = out_dir / "deck.pdf"  # its deck
    if rec.get("blind") is True or rec.get("issues") or cover.get("issues"):  # a blind edition, or checks that failed
        return None
    if not deck.is_file() or file_hash(deck) != (rec.get("hashes") or {}).get("deck.pdf"):  # not the deck that was checked
        return None
    meta = pdfmeta.read(deck)  # what a reader shows in its title bar
    if not meta.get("title") or not meta.get("author") or re.fullmatch(r"owl_(?:cover_)?[0-9a-f]{8}.*", meta.get("title") or ""):  # no title of its own
        return None
    dest = desktop_dir()  # the Desktop
    dest.mkdir(parents=True, exist_ok=True)  # a fresh Desktop folder in a test
    full = sha256(deck)  # the bytes that go
    base = safe_name(tasks.person_name(lang), WORDS[lang])  # 홍길동 포트폴리오, Gildong Hong Portfolio
    with DESK_LOCK:  # the record read, the copy made and the record written as one step
        record = _record(tasks)  # what it wrote before
        mine = record.get(lang)  # in this language
        ours = _ours(dest, mine)  # its own earlier copy is there, unchanged
        old = Path(mine["name"]).name if ours else None  # that copy's name
        same_base = old is not None and (old == base + ".pdf" or re.fullmatch(re.escape(base) + r" \(\d+\)\.pdf", old))  # under the name it would take now
        if same_base and mine.get("sha256") == full:  # already this deck
            return old
        name = old if same_base else free_name(dest, base, ".pdf")  # in place of its own copy, else a name no file has
        part = tmp_name(dest / name)  # written whole first, beside it, under a name of this writer's own
        if part.exists():  # never over a file that is there
            return None
        shutil.copyfile(deck, part)
        retried(os.replace, part, dest / name)  # in place at once
        if sha256(dest / name) != full:  # a copy that does not read back is never left
            (dest / name).unlink(missing_ok=True)
            return None
        if old and old != name and _ours(dest, mine):  # its earlier copy under a name the person's no longer gives (a new name, say): replaced
            (dest / old).unlink(missing_ok=True)
        record[lang] = {"name": name, "sha256": full}  # what to recognise next time
        write_json(tasks.ws.path(*RECORD), record)
        return name
