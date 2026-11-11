"""Tasks' part for the export, the sent copies and the lock (apps/api/tasks.py inherits it)."""
from __future__ import annotations

from pathlib import Path  # paths
import re  # names and patterns
import shutil  # copies and tool lookup
import tempfile  # temporary folders

from .delivery import desktop_dir  # noqa: E402
from .facts import clean_name  # noqa: E402
from .stamps import file_hash  # noqa: E402
from .workspace import read_json, sha256, today  # noqa: E402



class Exports:
    """What leaves the workspace: an edition's checked files on the Desktop, the copies of what was sent, and the lock that
    freezes a submitted edition byte for byte."""

    def export(self, job_id: str, lang: str, refused: list | None = None) -> list[str]:
        """Copy the edition's PDFs to the Desktop under readable names (and its Word and text files, or its deck as a
        PowerPoint file, when the settings ask for them: apps/api/delivery.py makes and checks those). Only what passed its
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
        blind = rec.get("blind") is True  # a blind edition
        if blind:  # nothing it covers may show in what goes: its words, its titles, its links
            found = self.blind_leaks(out_dir, [f for f in ("resume.pdf", "deck.pdf", "cover.pdf") if f in hashes and (out_dir / f).is_file()])
            if found is None:  # a PDF whose text could not be read is never taken for a clean one
                raise ValueError("blind_unread")
            if found:  # a covered name still shows
                raise ValueError(f"blind_leak:{len(found)}")  # how many patterns, for the page's words
        from . import delivery  # the Word-ready Word files, the PowerPoint copy, the portfolio kept on the Desktop
        settings = self.card.settings_fn()  # what the person asked for
        extras = settings.get("export_extras") is True  # Word and text files too, only when asked
        pptx = settings.get("export_pptx") is True  # the deck as a PowerPoint file too, only when asked
        who = self.person_name(lang)  # the person's name, as the edition's own title writes it
        # the company, or a named edition's own name (one for headhunters and one per role must not land as the same file); the general edition has none
        where = "" if job_id == "-general" else str((st.get("name") if st.get("kind") == "edition" else None) or st.get("company") or st.get("role") or job_id).strip()
        words = {"ko": {"resume": "이력서", "plain": "이력서 일반 양식", "deck": "포트폴리오", "cover": "자기소개서"},  # the file names in the edition's language
                 "en": {"resume": "Resume", "plain": "Resume plain", "deck": "Portfolio", "cover": "Cover letter"}}[lang]  # file name words
        who, where, mark = self.blind_names(who, where, lang) if blind else (who, where, "")  # a blind edition's names
        dest = desktop_dir()  # the Desktop
        dest.mkdir(parents=True, exist_ok=True)  # a fresh Desktop folder in a test
        written, names = [], []  # the copies this export made (taken back on a failure), and every name it reports
        deck_base = None  # the portfolio's name on the Desktop, which its PowerPoint file shares
        try:
            with tempfile.TemporaryDirectory(prefix="offerowl-export-") as tmp:  # the Word and PowerPoint files are made here first
                for key, f in (("resume", "resume.pdf"), ("resume", "resume.docx"), ("plain", "resume_plain.docx"), ("plain", "resume.txt"),  # each file of each document
                               ("deck", "deck.pdf"), ("deck", "deck.pptx"), ("cover", "cover.pdf"), ("cover", "cover.docx")):  # in the order the toast lists them
                    base = delivery.safe_name(who, where, mark, words[key])  # a safe name: a slash in an edition's name ('SRE / Platform') becomes a space
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
        return names  # the names, never the folder

    def blind_names(self, who: str, where: str, lang: str) -> tuple:
        """A blind edition's file name parts: the person's name and the company's or edition's name, each left out when the
        table covers any of it (a file name has no bar), and the word that says it is the blind edition."""
        import blind  # src/blind.py: what the table covers
        table = self.blind_table()  # the table as it is now
        keep = lambda x: "" if blind.hits(x, table) else x  # noqa: E731  a covered name is left out whole
        return keep(who), keep(where), {"ko": "블라인드", "en": "Blind"}[lang]

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
        st = self.ws.job(job_id) or {}  # the job
        who = self.person_name(lang)  # the person's name, as the edition's file names write it
        where = str((st.get("name") if st.get("kind") == "edition" else None) or st.get("company") or st.get("role") or job_id).strip()  # the company
        words = {"ko": {"resume": "이력서", "deck": "포트폴리오", "cover": "자기소개서"}, "en": {"resume": "Resume", "deck": "Portfolio", "cover": "Cover letter"}}[lang]
        who, where, mark = self.blind_names(who, where, lang) if lock.get("blind") is True else (who, where, "")  # a blind edition went out under its names
        extras = self.card.settings_fn().get("export_extras") is True  # Word files too, only when asked
        dest = desktop_dir()  # the Desktop
        dest.mkdir(parents=True, exist_ok=True)  # a fresh Desktop folder in a test
        written = []  # names
        try:
            for f in sorted(hashes):  # each frozen file, by its name: resume.pdf, deck.pdf, cover.pdf and their Word or slide files
                key = Path(f).stem  # resume, deck or cover
                if key not in words or not (folder / f).is_file() or (Path(f).suffix != ".pdf" and not extras):  # the profile and settings kept with an Offerowl lock, a missing copy, or a Word file nobody asked for
                    continue
                if sha256(folder / f) != hashes[f]:  # changed since it was frozen
                    raise ValueError("changed")
                base = " ".join(re.sub(r'[\\/:*?"<>|]+', " ", " ".join(x for x in (who, where, mark, words[key]) if x)).split())[:120]  # a safe name
                name, n = base + Path(f).suffix, 2  # first try
                while (dest / name).exists():  # never overwrite
                    name, n = f"{base} ({n}){Path(f).suffix}", n + 1
                shutil.copyfile(folder / f, dest / name)  # a plain copy: the frozen one stays
                written.append(name)
                if sha256(dest / name) != hashes[f]:  # the copy is the bytes that went out
                    raise ValueError("copy_unreadable")
        except Exception:  # nothing is left half done
            for name in written:
                (dest / name).unlink(missing_ok=True)
            raise
        return written

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
        rec = self.ws.freeze(job_id, files)  # the copies
        rec["lang"] = lang  # which edition was locked
        if (read_json(out_dir / "build.json", {}) or {}).get("blind") is True:  # a blind edition was what went out
            rec["blind"] = True  # its copies keep their blind names on the Desktop
        with self.ws.change({"code": "undo_lock"}, self.ws.job_files(job_id)):  # undo unlocks; the frozen copies stay
            st = self.ws.job(job_id)  # the job
            st["locked"] = rec  # submitted: the panel stops rebuilding it
            st["stage"] = "submitted"  # on the board
            st.setdefault("dates", {})["submitted"] = today()  # the day it was submitted
            self.ws.save_job(st)  # the board moves with it
        return rec  # the record the toast and the card read
