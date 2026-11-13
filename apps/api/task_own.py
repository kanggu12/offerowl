"""Tasks' part for an application's own edition (apps/api/tasks.py inherits it)."""
from __future__ import annotations

from pathlib import Path  # paths
import hashlib  # hashes
import re  # names and patterns
import shutil  # copies and tool lookup

from .facts import Facts  # noqa: E402
from .stamps import file_hash  # noqa: E402
from .workspace import Workspace, read_json, sha256, write_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
# The layout choices an application's own edition may carry (app.own_edition, resume_form.js reads them under these names);
# blind: the edition is made as a blind edition (Tasks.blind_choice), so one brought in blind stays blind
OWN_FORM_KEYS = ("competencyFigure", "footerLabel", "skillsFocus", "skillsStrong", "skillsHighlight", "photo", "plain", "titleView", "blind")


class OwnEdition:
    """An application's own edition: a resume or deck the person brought in for one job, kept beside it, typeset from its own
    profile or handed back as it came, and the cover letter's pages as they were sent."""

    def own_dir(self, job_id: str | None) -> Path | None:
        """The folder of a job's own edition (a resume the person already wrote for it, brought in whole: app.own_edition),
        or None when the job is drafted from the profile."""
        if not job_id or job_id == "-general":  # no job, or the general edition (the profile itself)
            return None
        d = self.ws.job_dir(job_id) / "own"  # beside the job's other files
        return d if (d / "profile" / "profile.json").is_file() else None

    def own_langs(self, job_id: str | None) -> list:
        """The languages a job's own edition was written in: its documents in another language need a translation."""
        d = self.own_dir(job_id)  # the edition, if any
        return list((read_json(d / "own.json", {}) or {}).get("langs") or []) if d else []

    def own_form(self, job_id: str | None, lang: str) -> dict:
        """The layout choices a job's own edition was made with, in this language (own/form.json, app.own_edition)."""
        d = self.own_dir(job_id)  # the edition, if any
        form = (read_json(d / "form.json", {}) or {}).get(lang) if d else None  # its choices for this language
        return {k: v for k, v in (form or {}).items() if k in OWN_FORM_KEYS}  # only what the form reads

    def own_src(self, job_id: str | None, lang: str) -> Path | str | None:
        """The profile a job's own edition prints in this language, "own_lang" when it was brought in without that language,
        or None when the job has no own edition."""
        own = self.own_dir(job_id)  # the edition, if any
        if own is None:
            return None
        return own / "profile" / "profile.json" if lang in self.own_langs(job_id) else "own_lang"

    def own_file(self, job_id: str | None, kind: str, lang: str) -> Path | None:
        """The document the person made for this edition (app.own_file): resume, cover or deck, in this language, or None."""
        if not job_id:  # the general edition keeps its files in the profile (deck.pdf)
            return None
        d = self.ws.job_dir(job_id) / "own" / "files"  # where they are kept
        return next((f for f in sorted(d.glob(f"{kind}_{lang}.*")) if f.suffix in (".pdf", ".docx")), None) if d.is_dir() else None

    def _own_pdf(self, job_id: str | None, kind: str, lang: str, out_dir: Path) -> Path | None:
        """The PDF of the person's own document for this edition: copied, or made from the Word file by LibreOffice (the
        renderer's toolchain). None when there is none. Raises SystemExit like the typesetting when the conversion fails."""
        import resume  # the toolchain
        f = self.own_file(job_id, kind, lang)  # the file, if any
        if f is None:
            return None
        pdf = out_dir / f"own_{kind}.pdf"  # where the edition's PDF of it goes
        if f.suffix == ".pdf":  # already a PDF: as it is
            shutil.copyfile(f, pdf)
        else:
            made = None  # the PDF LibreOffice writes into the engine's folder
            try:
                made = resume.docx_to_pdf(f)  # the Word file through LibreOffice, in the container when it is the renderer
                shutil.copyfile(made, pdf)  # beside the edition
                shutil.copyfile(f, out_dir / f"own_{kind}.docx")  # and the Word file it came from
            finally:  # the person's file does not stay in the engine's folder, made or not: its staged copy and the PDF go
                if made is not None:
                    made.unlink(missing_ok=True)
                (ROOT / "output" / "_inputs" / (hashlib.sha1(str(f.resolve()).encode()).hexdigest()[:8] + "_" + re.sub(r"[^\w가-힣.-]", "_", f.name))).unlink(missing_ok=True)  # named as resume.rel names it
        import pdfmeta  # src/pdfmeta.py: the title and the author a reader shows
        try:
            meta = pdfmeta.read(pdf)  # what the file says of itself
        except Exception:  # noqa: BLE001  a file this cannot read keeps what it has
            meta = {"title": "-", "author": "-"}
        if not meta.get("title") or not meta.get("author"):  # a Word file's PDF often has neither: a recruiter's window would show none
            resume.stamp_meta(pdf, str(out_dir / "profile.json"), str(out_dir / "job.json"), kind)  # the person's name and the document's kind, as Offerowl's own PDFs carry
        return pdf

    def own_stamp(self, job_id: str | None) -> str:
        """What a job's own edition and own files are now (a short hash), "" when it has neither: an edition made from them is
        stale when they change, and never because the profile changed."""
        if not job_id or job_id == "-general":  # the general edition is the profile itself
            return ""
        d = self.ws.job_dir(job_id) / "own"  # the job's own things
        files = sorted(f for f in (d / "files").glob("*") if f.is_file()) if (d / "files").is_dir() else []  # its own documents
        prof = d / "profile" / "profile.json"  # its own edition's words
        if not files and not prof.is_file():  # neither
            return ""
        return hashlib.sha256("|".join(file_hash(f) for f in [prof, *files]).encode()).hexdigest()[:16]

    def facts_for(self, job_id: str | None) -> Facts:
        """The facts a job's documents are made from: the job's own edition when it has one, else the profile's."""
        d = self.own_dir(job_id)  # the edition, if any
        if d is None:  # drafted from the profile
            return self.facts
        key = str(d)  # one reader per edition
        if key not in self._own_facts:  # read once
            from .facts import OwnFacts  # the job's own facts
            self._own_facts[key] = OwnFacts(Workspace(d), self.facts)
        return self._own_facts[key]

    def forget_own(self, job_id: str) -> None:
        """A job's own edition was brought in again or taken away: the next read starts fresh."""
        self._own_facts.pop(str(self.ws.job_dir(job_id) / "own"), None)

    def sent_letter(self, job_id: str, lang: str) -> tuple[Path, str] | None:
        """The cover letter that went out with this application in this language, with its SHA-256, when the lock holds one
        whose bytes are still what was frozen; else None."""
        st = self.ws.job(job_id) or {}  # the job's record
        lock = st.get("locked") if isinstance(st.get("locked"), dict) else None  # what was submitted, if it was
        want = ((lock or {}).get("files") or {}).get("cover.pdf") if (lock or {}).get("lang") == lang else None  # the letter's frozen hash
        if not want or not re.fullmatch(r"[\w-]{1,80}", str(lock.get("folder") or "")):  # no letter went out in this language, or a folder name that is not one
            return None
        f = self.ws.job_dir(job_id) / "submitted" / lock["folder"] / "cover.pdf"  # the frozen copy
        return (f, want) if f.is_file() and sha256(f) == want else None  # only the bytes that were sent

    def letter_pages(self, job_id: str, lang: str) -> int | None:
        """The page pictures of a letter the person made, for an edition made before the build drew them (the Cover letter
        tab shows such a letter only as pictures, so it said "No PDF yet" though the PDF was there). A job submitted with a
        letter shows the copy that went out, byte for byte. Returns the pages drawn, or None when there was nothing to do:
        no edition, a letter Offerowl drafted (its build draws its own pages), or pictures already there."""
        out_dir = self.build_dir(job_id, lang)  # the edition
        b = read_json(out_dir / "build.json", None)  # its record
        if not isinstance(b, dict) or b.get("blind"):  # never made, or a blind edition (it has no letter)
            return None
        cover = b.get("cover") if isinstance(b.get("cover"), dict) else None  # what the build said of its letter
        sent = self.sent_letter(job_id, lang)  # the letter that went out, if one did
        if sent is None and not (cover and cover.get("own")):  # no letter of the person's own
            return None
        if cover and "pages" in cover and (sent is None or cover.get("sent") == sent[1]):  # drawn already, from the right bytes
            return None
        pdf = out_dir / "cover.pdf"  # the edition's letter
        if sent is not None and (not pdf.is_file() or sha256(pdf) != sent[1]):  # submitted: the edition's letter is the copy that went out
            shutil.copyfile(sent[0], pdf)
            (out_dir / "cover.docx").unlink(missing_ok=True)  # a Word file made from another source is not that copy
        if not pdf.is_file():  # nothing to draw
            return None
        n = self._previews(pdf, out_dir / "preview", "c", 110)  # its pages, as a build draws them
        cover = {**(cover or {"state": "done", "issues": [], "notes": ["own_file"]}), "own": True, "pages": n}  # shown as its pages
        if sent is not None:  # which bytes they are
            cover["sent"] = sent[1]
        b["cover"] = cover  # the record says so
        b.setdefault("hashes", {})["cover.pdf"] = file_hash(pdf)  # what an export checks against
        write_json(out_dir / "build.json", b)  # kept with the edition
        return n
