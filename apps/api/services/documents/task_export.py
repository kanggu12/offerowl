"""Tasks' part for the export, the sent copies and the lock (apps/api/tasks.py inherits it)."""
from __future__ import annotations

from pathlib import Path  # paths
import hashlib  # a sent file's SHA-256
import logging  # the panel's log
import re  # names and patterns
import shutil  # copies and tool lookup
import tempfile  # temporary folders
import time  # the folder of a language's sent copies

from .. import applications  # noqa: E402  the board's card, moved when the documents go out
from .delivery import desktop_dir  # noqa: E402
from ..profile import clean_name  # noqa: E402  the person's name as a file carries it (the profile's)
from ...core.stamps import file_hash  # noqa: E402
from ...core.workspace import read_json, sha256, today, write_json  # noqa: E402
from .editions import OWN_KINDS  # noqa: E402  what a file of an edition may stand for, and its types

log = logging.getLogger("offerowl.panel")  # the panel's log
SENT_FILE = re.compile(r"^(resume|deck|cover)\.(pdf|docx|pptx)$")  # the copies a lock keeps (keep_sent_file, Workspace.freeze)
DESK_WORDS = {"ko": {"resume": "이력서", "plain": "이력서 일반 양식", "deck": "포트폴리오", "cover": "자기소개서"},  # each document's word in a file name, in the edition's language
              "en": {"resume": "Resume", "plain": "Resume plain", "deck": "Portfolio", "cover": "Cover letter"}}
DESK_KEY = {"resume.pdf": "resume", "resume.docx": "resume", "resume_plain.docx": "plain", "resume.txt": "plain", "deck.pdf": "deck",
            "deck.pptx": "deck", "cover.pdf": "cover", "cover.docx": "cover"}  # an edition's file -> the document it is, as the export names it


def sent_file(ws, jid: str, name: str) -> Path | None:
    """A copy that went out with an application, by its name, or None: only the files the lock recorded (the Library lists
    and opens them through this)."""
    lk = (ws.job(jid) or {}).get("locked")  # what was submitted
    if not SENT_FILE.match(name) or not isinstance(lk, dict) or name not in (lk.get("files") or {}):
        return None
    base = (ws.job_dir(jid) / "submitted").resolve()  # where every lock keeps its copies
    f = (base / Path(str(lk.get("folder") or "")).name / name).resolve()  # the folder's own name only: never a path from the record
    return f if f.is_file() and base in f.parents else None


def keep_sent_file(api, jid: str, lang: str, kind: str, name: str, data: bytes) -> dict:
    """A file that went out with this application (the resume, the portfolio, the cover letter as sent), kept as its
    submitted copy: the lock's frozen folder for that language holds it byte for byte, and the job counts as submitted.
    Each file comes on its own; the ones of one language gather in one folder."""
    jid = api.need_job({"job": jid})  # which job
    ext = Path(name).suffix.lower()  # its type, by its name
    if lang not in ("ko", "en") or kind not in OWN_KINDS or ext not in (".pdf", ".docx", ".pptx") or not api.ws.sniff_ok(ext, data):
        raise ValueError("own_file_type")  # three kinds; a PDF, a Word file or slides
    with api.ws.lock:  # one writer
        st = api.ws.job(jid)  # its record
        rec = st.get("locked") if isinstance(st.get("locked"), dict) and st["locked"].get("brought") and st["locked"].get("lang") == lang else None
        folder = rec["folder"] if rec else time.strftime("%Y%m%d-%H%M%S") + "-sent"  # the folder of this language's copies
        dest = api.ws.job_dir(jid) / "submitted" / folder  # beside the locks made here
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / (kind + ext)  # resume.pdf, deck.pdf, cover.pdf and the like
        target.write_bytes(data)  # as it was sent
        files = {**(rec or {}).get("files", {}), target.name: hashlib.sha256(data).hexdigest()}  # its hash with the others
        write_json(dest / "hashes.json", files)  # beside the copies, as freeze() writes it
        with api.ws.change({"code": "undo_lock"}, api.ws.job_files(jid)):  # undo unlocks; the copies stay
            st = api.ws.job(jid)  # read again inside the step
            st["locked"] = {"at": (rec or {}).get("at") or today(), "folder": folder, "files": files, "lang": lang, "brought": True, "name": name[:120]}
            applications.mark_sent(st, always=False)  # sent: on the board it moves on (a later stage stays), by the board's rule
            api.ws.save_job(st)  # the board moves with it
    return {"kind": kind, "lang": lang, "file": target.name, "folder": folder}


class Exports:
    """What leaves the workspace: an edition's checked files on the Desktop, the copies of what was sent, and the lock that
    freezes a submitted edition byte for byte."""

    def export(self, job_id: str, lang: str, refused: list | None = None) -> list[str]:
        """Copy the edition's PDFs to the Desktop under readable names (and its Word and text files, or its deck as a
        PowerPoint file, when the settings ask for them: delivery.py makes and checks those). Only what passed its
        checks goes, byte for byte as checked, and each PDF copy is read back: its pages, its title and its author. Raises
        ValueError with the reason when nothing may go. Returns the names on the Desktop; a Word or PowerPoint file that
        failed its own check stays home and is added to `refused` ({file, why}). The general edition's deck that the
        setting desk_portfolio keeps on the Desktop is named, not copied twice. A job locked as submitted in this language
        gives the copies that went out instead (export_sent). A blind edition's PDFs are read first and refused
        (blind_leak:<n>) when any pattern of the table as it is now shows in them; their names say "블라인드" or "Blind" and
        leave out a name the table covers."""
        refused = [] if refused is None else refused  # the files kept home, for the caller that asks
        st = self.ws.job(job_id) or {}  # the job
        lock = st.get("locked") if isinstance(st.get("locked"), dict) else None  # what was submitted, if it was
        if lock and lock.get("lang") == lang and lock.get("folder"):  # submitted in this language: those exact copies are what goes
            return self.export_sent(job_id, lang, lock)
        out_dir, rec, hashes, blind = self.checked(job_id, lang)  # what may go, or the reason nothing may
        from . import delivery  # the Word-ready Word files, the PowerPoint copy, the portfolio kept on the Desktop
        settings = self.card.settings_fn()  # what the person asked for
        extras = settings.get("export_extras") is True  # Word and text files too, only when asked
        pptx = settings.get("export_pptx") is True  # the deck as a PowerPoint file too, only when asked
        words = DESK_WORDS[lang]  # the file names in the edition's language
        who, where, mark = self.desk_parts(job_id, lang, blind)  # the person, the company or the edition's name, a blind edition's mark
        dest = desktop_dir()  # the Desktop
        dest.mkdir(parents=True, exist_ok=True)  # a fresh Desktop folder in a test
        written, names = [], []  # the copies this export made (taken back on a failure), and every name it reports
        deck_base = None  # the portfolio's name on the Desktop, which its PowerPoint file shares
        try:
            with tempfile.TemporaryDirectory(prefix="offerowl-export-") as tmp:  # the Word and PowerPoint files are made here first
                for key, f in (("resume", "resume.pdf"), ("resume", "resume.docx"), ("plain", "resume_plain.docx"), ("plain", "resume.txt"),  # each file of each document
                               ("deck", "deck.pdf"), ("deck", "deck.pptx"), ("cover", "cover.pdf"), ("cover", "cover.docx")):  # in the order the toast lists them
                    base = delivery.safe_name(who, where, mark, words[key], delivery.made_day(rec))  # the day the build made it last; a safe name: a slash in an edition's name ('SRE / Platform') becomes a joint, as every space does (SRE_Platform)
                    if f == "deck.pptx":  # made from the deck that goes, beside it under its name
                        if not pptx or deck_base is None:  # not asked for, or no deck went
                            continue
                        src, base = delivery.powerpoint(self, out_dir, Path(tmp), refused), deck_base
                    else:
                        src = out_dir / f  # the edition's copy
                        if not src.is_file() or (not f.endswith(".pdf") and not extras):  # a document not made this time, or a Word or text file nobody asked for
                            continue  # nothing to copy
                        if f in ("resume.docx", "cover.docx"):  # the Word file a person sends: ready for Word, and the same pages there
                            src = delivery.word_ready(self, out_dir, f, Path(tmp), refused)
                    if src is None:  # it stayed home: refused says why
                        continue
                    if f == "deck.pdf" and job_id == "-general" and not blind:  # the portfolio desk_portfolio keeps there already, this very deck
                        kept = delivery.kept_copy(self, lang, src)
                        if kept:  # named, never copied beside itself
                            names.append(kept)
                            deck_base = Path(kept).stem
                            continue
                    name = delivery.free_name(dest, base, src.suffix)  # never over another file
                    shutil.copyfile(src, dest / name)  # a plain copy: the edition stays where it is
                    written.append(name)  # taken back below if anything after it fails
                    names.append(name)
                    if f == "deck.pdf":  # its PowerPoint file goes under the same name
                        deck_base = Path(name).stem
                    if src.suffix == ".pdf" and (file_hash(dest / name) != hashes.get(f) or not self.reads_back(dest / name, src)):  # the bytes that were checked, as a recruiter will open them
                        raise ValueError("copy_unreadable")  # the page says so
                    if src.suffix != ".pdf" and sha256(dest / name) != sha256(src):  # a Word, text or PowerPoint file: the bytes made and checked
                        raise ValueError("copy_unreadable")
        except Exception:  # nothing is left on the Desktop half done: every copy of this export goes
            for name in written:
                (dest / name).unlink(missing_ok=True)
            raise
        try:  # these pages are what went out: a later build says which of them it changed (task_compare.py)
            self.keep_baseline(job_id, lang, "export")
        except Exception:  # noqa: BLE001  the copies went; a baseline that could not be kept is said in the log
            log.exception("baseline of %s %s not kept", job_id, lang)
        return names  # the names, never the folder

    def checked(self, job_id: str, lang: str) -> tuple:
        """(the edition's folder, its build record, the hashes of the bytes checked, whether it is blind) once every check
        that guards what leaves the workspace passed: the export and the lock both ask, so a copy frozen as submitted (which
        export_sent later copies without checking again) passed the same checks as one exported. Raises ValueError with the
        reason the page words: checks_failed, changed, parity:<n>, parity_unchecked, blind_unread or blind_leak:<n>."""
        out_dir = self.build_dir(job_id, lang)  # the edition
        rec = read_json(out_dir / "build.json", {})  # what the build checked
        cover = rec.get("cover") if isinstance(rec.get("cover"), dict) else {}  # the letter's own result
        if rec.get("issues") or cover.get("issues"):  # a document that failed its checks is never sent, the letter included
            raise ValueError("checks_failed")  # the page points at the problems
        hashes = rec.get("hashes") or {}  # the bytes that were checked
        for f in ("resume.pdf", "deck.pdf", "cover.pdf"):  # every PDF that may go
            if (out_dir / f).is_file() and (f not in hashes or file_hash(out_dir / f) != hashes[f]):  # never checked (an edition from before the checked delivery has no record), or changed after its check
                raise ValueError("changed")  # the page says to make the PDFs again
        import pdfmeta  # src/pdfmeta.py: the title and the author a reader shows
        for f in hashes:  # before anything is copied: a PDF that still carries no title of its own (an older build) is made again
            if not (out_dir / f).is_file():  # a document not made this time
                continue
            try:
                meta = pdfmeta.read(out_dir / f)  # what a reader shows in its title bar
            except Exception:  # noqa: BLE001  a file this cannot read is not sent either
                meta = {}
            if not meta.get("title") or not meta.get("author") or re.fullmatch(r"owl_(?:cover_)?[0-9a-f]{8}.*", meta.get("title") or ""):  # no title, or the build's name
                raise ValueError("changed")  # the page says to make the PDFs again
        bad = self.parity_now(job_id, lang)  # a translation is held to its source as both are now (task_compare.py)
        if bad:  # it says less than the source, or otherwise
            raise ValueError(f"parity:{len(bad)}")  # how many differences, for the page's words
        blind = rec.get("blind") is True  # a blind edition
        if blind:  # nothing it covers may show in what goes: its words, its titles, its links
            found = self.blind_leaks(out_dir, [f for f in ("resume.pdf", "deck.pdf", "cover.pdf") if f in hashes and (out_dir / f).is_file()])
            if found is None:  # a PDF whose text could not be read is never taken for a clean one
                raise ValueError("blind_unread")
            if found:  # a covered name still shows
                raise ValueError(f"blind_leak:{len(found)}")  # how many patterns, for the page's words
        return out_dir, rec, hashes, blind

    def blind_names(self, who: str, where: str, lang: str) -> tuple:
        """A blind edition's file name parts: the person's name and the company's or edition's name, each left out when the
        table covers any of it (a file name has no bar), and the word that says it is the blind edition."""
        import blind  # src/blind.py: what the table covers
        table = self.blind_table()  # the table as it is now
        keep = lambda x: "" if blind.hits(x, table) else x  # noqa: E731  a covered name is left out whole
        return keep(who), keep(where), {"ko": "블라인드", "en": "Blind"}[lang]

    def desk_parts(self, job_id: str, lang: str, blind: bool) -> tuple:
        """(the person's name, the company or a named edition's own name, the blind edition's word) an edition's files carry
        on the Desktop: the export, the copies that went out and the Library's copy all name them so. The general edition
        names no company; a named edition its own name, so one for headhunters and one per role never land as one file."""
        st = self.ws.job(job_id) or {}  # the job or the named edition
        who = self.person_name(lang)  # the person's name, as the edition's own title writes it
        where = "" if job_id == "-general" else str((st.get("name") if st.get("kind") == "edition" else None) or st.get("company") or st.get("role") or job_id).strip()
        return self.blind_names(who, where, lang) if blind else (who, where, "")  # a blind edition's names leave out what its table covers

    def export_name(self, job_id: str, lang: str, file: str, sent: bool = False) -> str | None:
        """The name an edition's file takes on the Desktop when the Documents view exports it (홍길동_감마랩스_이력서_20261126.pdf):
        underscores and the day it was made, or for a copy that went out (`sent`) the day it went. The Library's export of the
        same file takes this name too: it was "-general-ko-deck.pdf" (D4-08). None for a file the export never names."""
        from . import delivery  # the safe name and the day
        key = DESK_KEY.get(file)  # the document it is
        if not key or lang not in DESK_WORDS:  # profile.json and the like
            return None
        if sent:  # what went out: the lock's day and its blind mark
            lock = (self.ws.job(job_id) or {}).get("locked")  # the record of what went out
            rec = lock if isinstance(lock, dict) else {}  # its day and its blind mark
        else:  # the edition as its last build made it
            rec = read_json(self.build_dir(job_id, lang) / "build.json", {})  # the build's record
            rec = rec if isinstance(rec, dict) else {}  # an object, or nothing known
        who, where, mark = self.desk_parts(job_id, lang, rec.get("blind") is True)  # the names it carries
        return delivery.safe_name(who, where, mark, DESK_WORDS[lang][key], delivery.made_day(rec)) + Path(file).suffix

    def person_name(self, lang: str) -> str:
        """The person's name for a file on the Desktop: the English name in English (as the PDF's own title and author write
        it, src/resume.py stamp_meta), else the name; a ledger's '홍 길 동 (Gil-Dong Hong)' is read as both."""
        person = self.facts.profile().get("person") or {}  # whose documents
        ko, en = clean_name(str(person.get("name") or ""), str(person.get("name_en") or ""))  # joined syllables, the Latin name apart
        return ((en if lang == "en" else "") or ko).strip()  # an English file reads as English

    def export_sent(self, job_id: str, lang: str, lock: dict) -> list[str]:
        """The copies a submitted application went out with (the lock's folder), copied to the Desktop under the edition's
        readable names, each checked against the hash kept when it was frozen, byte for byte. They are not checked again
        nor stamped: they are the record of what was sent. Returns the names written."""
        folder = self.ws.job_dir(job_id) / "submitted" / Path(str(lock["folder"])).name  # the frozen copies, never a path from the record
        hashes = lock.get("files") or {}  # their hashes when frozen
        words = {k: DESK_WORDS[lang][k] for k in ("resume", "deck", "cover")}  # the documents that go: a plain resume's Word file stays with the lock
        who, where, mark = self.desk_parts(job_id, lang, lock.get("blind") is True)  # a blind edition went out under its names
        from . import delivery  # the safe name and the day, as export() names its files
        extras = self.card.settings_fn().get("export_extras") is True  # Word files too, only when asked
        dest = desktop_dir()  # the Desktop
        dest.mkdir(parents=True, exist_ok=True)  # a fresh Desktop folder in a test
        written, reused = [], []  # names copied now; names already holding those bytes
        try:
            for f in sorted(hashes):  # each frozen file, by its name: resume.pdf, deck.pdf, cover.pdf and their Word or slide files
                key = Path(f).stem  # resume, deck or cover
                if key not in words or not (folder / f).is_file() or (Path(f).suffix != ".pdf" and not extras):  # the profile and settings kept with an Offerowl lock, a missing copy, or a Word file nobody asked for
                    continue
                if sha256(folder / f) != hashes[f]:  # changed since it was frozen
                    raise ValueError("changed")
                base = delivery.safe_name(who, where, mark, words[key], delivery.made_day(lock))  # named as every export names its files: underscores and the day it went (it was "홍길동 감마 이력서.pdf")
                name, n, same = base + Path(f).suffix, 2, None  # first try
                while (dest / name).exists():  # never overwrite
                    if sha256(dest / name) == hashes[f]:  # those very bytes are there already: named again, never copied again (exports piled up "(741)" copies)
                        same = name
                        break
                    name, n = f"{base}_{n}{Path(f).suffix}", n + 1  # numbered as free_name numbers, with no space
                if same:
                    reused.append(same)  # said as written, never removed when a later file fails
                    continue
                shutil.copyfile(folder / f, dest / name)  # a plain copy: the frozen one stays
                written.append(name)
                if sha256(dest / name) != hashes[f]:  # the copy is the bytes that went out
                    raise ValueError("copy_unreadable")
        except Exception:  # nothing is left half done
            for name in written:
                (dest / name).unlink(missing_ok=True)
            raise
        return sorted(written + reused)

    @staticmethod
    def reads_back(copy: Path, src: Path) -> bool:
        """A PDF copy reads as its source: the same bytes, the same page count, and a title and an author of its own
        (src/pdfmeta.py), not a build name."""
        import pdfmeta  # src/pdfmeta.py
        if copy.read_bytes() != src.read_bytes():  # a short or damaged copy
            return False
        meta = pdfmeta.read(copy)  # what a reader shows in its title bar
        if not meta.get("title") or not meta.get("author") or re.fullmatch(r"owl_(?:cover_)?[0-9a-f]{8}.*", meta["title"] or ""):  # the build's name, or none
            return False
        return pdfmeta.pages(copy) > 0  # at least one page in its tree

    def lock(self, job_id: str, lang: str) -> dict | None:
        """Freeze what was submitted: exact copies and their hashes in jobs/<job>/submitted/, the board's card moved to
        submitted with today's date. None when the edition was never made."""
        out_dir = self.build_dir(job_id, lang)  # the edition
        files = {f: out_dir / f for f in ("resume.pdf", "resume.docx", "resume_plain.docx", "resume.txt", "deck.pdf", "cover.pdf", "cover.docx", "profile.json", "job.json")  # everything this edition is made of
                 if (out_dir / f).is_file()}  # what there is
        if "resume.pdf" not in files:  # no resume, nothing to lock
            return None  # the endpoint answers bad_request
        self.checked(job_id, lang)  # what the export would refuse is never frozen as sent: export_sent copies it later unchecked
        rec = self.ws.freeze(job_id, files)  # the copies
        rec["lang"] = lang  # which edition was locked
        if (read_json(out_dir / "build.json", {}) or {}).get("blind") is True:  # a blind edition was what went out
            rec["blind"] = True  # its copies keep their blind names on the Desktop
        with self.ws.change({"code": "undo_lock"}, self.ws.job_files(job_id)):  # undo unlocks; the frozen copies stay
            st = self.ws.job(job_id)  # the job
            st["locked"] = rec  # submitted: the panel stops rebuilding it
            applications.mark_sent(st)  # on the board, with the day it was submitted (the board's rule)
            self.ws.save_job(st)  # the board moves with it
        try:  # these pages are what went out (task_compare.py)
            self.keep_baseline(job_id, lang, "submitted")
        except Exception:  # noqa: BLE001  the copies are frozen; a baseline that could not be kept is said in the log
            log.exception("baseline of %s %s not kept", job_id, lang)
        return rec  # the record the toast and the card read
