"""Tasks' part for what an edition is held against (apps/api/tasks.py inherits it): a blind edition's ordinary twin, the
edition in the other language, its own deck, and the pages of the copy that last went out (its baseline).

  - A blind edition is typeset a second time without its bars (its twin): every word the bars leave must stand where the
    twin has it, and every pattern of the table must match some edition's words (src/check_blind.py).
  - An edition whose other language was made too is compared with it (src/check_parity.py langs): the edition in the
    language the facts are written in is the source, so the differences are notes on it and defects of the other one, which
    the export holds to the source as it is at that moment.
  - The resume is compared with its deck (src/check_parity.py edition): the slides' project names and periods, the colours
    and the fonts, and the words the style pack's parity.terms hold to one for one thing.
  - The pages of the copy that last went out (export, lock) are kept small (src/baseline.py), with the profile they were
    typeset from, and every later build says which pages changed since, with a picture of the changed bands; POST
    /api/v1/jobs/baseline keeps a build as the new one. The depth review reads the kept profile (depth.py).
"""
from __future__ import annotations

import hashlib  # names of staged files
import logging  # the panel's log
import os  # the environment of a check run outside a build
import shutil  # copies and folders
import subprocess  # a reader's version
import threading  # one write of a build record at a time
import time  # when a baseline was kept
from pathlib import Path  # paths

from ...core.workspace import read_json, write_json  # noqa: E402

log = logging.getLogger("offerowl.panel")  # the panel's log
ROOT = Path(__file__).resolve().parents[4]  # the repository (or the app's bundle)
LANGS = ("ko", "en")  # the editions
BASELINE = "baseline"  # the folder in an edition's folder that keeps its baseline pages (a blind edition's: baseline_blind)
CHANGES = "changes.png"  # the picture of the changed bands, beside the edition's page pictures
MATCHED = "blind_matched.json"  # the mask patterns a blind edition's words took, beside its record (kept out of the state the panel polls)
_record_lock = threading.Lock()  # a build record read, changed and written again by the export and the baseline key


class Comparisons:
    """An edition held against its ordinary twin, its other language, its deck and the copy that last went out."""

    # ------------------------------------------------------------------ running a check where the typesetting runs

    def _compare_tool(self, argv: list, env: dict | None, report: Path) -> dict | None:
        """A check of src/ run where the document checks run (the render container, or this PC with the browser renderer),
        with --report: the report it wrote ({defects, polish, ...}), or None when it did not run."""
        import resume  # its sh() runs the tool where the typesetting runs
        report.unlink(missing_ok=True)  # never an older run's
        try:
            r = resume.sh([*argv, "--report", resume.rel(str(report))], env)  # the check
        except (SystemExit, OSError) as exc:  # no container, no Python there
            log.warning("check %s did not run: %s", argv[1:2], exc)  # for the log only
            return None
        got = read_json(report, None) if report.is_file() else None  # what it wrote
        report.unlink(missing_ok=True)  # read once
        if not isinstance(got, dict):  # it stopped before writing (a loader that refused, a broken file)
            log.warning("check %s wrote no report: %s", argv[1:2], ((r.stdout or "") + (r.stderr or ""))[-1500:])  # the full output for the log
            return None
        return got

    @staticmethod
    def _staged(src: Path, name: str) -> str:
        """A workspace file copied into the engine's folder under a name of this edition's (output/_inputs/<name>), where the
        container sees it and the edition's clean-up takes it away. Repository-relative."""
        dst = ROOT / "output" / "_inputs" / name  # its place
        dst.parent.mkdir(parents=True, exist_ok=True)  # the first build makes it
        shutil.copyfile(src, dst)  # the bytes as kept
        return dst.relative_to(ROOT).as_posix()  # / on every system, as resume.rel writes it

    # ------------------------------------------------------------------ the blind edition's twin

    def blind_twin(self, out_dir: Path, name: str, env: dict, with_deck: bool) -> dict:
        """The ordinary twin of a blind edition: its resume, and its deck when the edition has a drawn one, typeset from the
        same profile and settings with no bars (env carries no blind switch). {"pdf", "deck", "docx", "page"} in the
        engine's folder (its clean-up takes them away with the edition's own files), or {"failed": True}."""
        import resume  # the typesetting
        cfg = {k: v for k, v in (read_json(out_dir / "job.json", {}) or {}).items() if k != "blind"}  # the edition's settings, made ordinary
        cfg["out"] = name + "_twin"  # its own name in the engine's folder: owl_<job>_<lang>_twin, which the clean-up matches
        f = ROOT / "output" / "_inputs" / f"{name}_twin.cfg.json"  # the settings file it is made with
        f.parent.mkdir(parents=True, exist_ok=True)
        write_json(f, cfg)
        try:
            pdf = resume.build(str(out_dir / "profile.json"), str(f), env)  # the resume without bars
            deck = resume.build_deck(str(out_dir / "profile.json"), str(f), env) if with_deck else None  # and the deck
        except (SystemExit, Exception) as exc:  # noqa: BLE001  the edition itself was made; only its check cannot run
            log.warning("blind twin of %s failed: %s", name, str(exc)[-2000:])  # for the log only
            return {"failed": True}
        return {"pdf": Path(pdf), "deck": Path(deck) if deck else None, "docx": Path(pdf).with_suffix(".docx"),
                "page": Path(str(deck)[:-4] + ".html") if deck else None}

    def blind_matched_elsewhere(self, stamp: str, skip: Path) -> set:
        """The mask patterns other blind editions matched when they were last made with this table (their build records'
        blind_matched): a pattern for another edition's words is not dead because this edition lacks them."""
        found = set()  # the patterns
        jobs = self.ws.path("jobs")  # every job and edition
        for d in sorted(jobs.iterdir()) if jobs.is_dir() else []:  # each folder
            for lang in LANGS:
                f = d / "resume" / lang / "build.json"  # its edition's record
                if f.resolve() == skip.resolve() or not f.is_file():  # this edition, or none
                    continue
                rec = read_json(f, {}) or {}
                if rec.get("blind") is True and rec.get("blind_table") == stamp:  # a blind edition of this very table
                    found |= {p for p in read_json(f.parent / MATCHED, []) or [] if isinstance(p, str)}
        return found

    # ------------------------------------------------------------------ the checks across documents

    def reference_lang(self, job_id: str) -> str:
        """The language an application's words are written in first, which the other edition is held to: an own edition's
        first language, else the profile's."""
        langs = self.own_langs(job_id)  # an own edition's languages, in the order it came in
        return langs[0] if langs and langs[0] in LANGS else self.profile_lang()

    def cross_checks(self, job_id: str, lang: str, out_dir: Path, name: str, pdf: Path, deck: Path | None, env: dict,
                     twin: dict | None) -> dict:
        """The checks across the documents of one edition, run after its own checks: the resume against its deck, the edition
        against its other language when that was made, and a blind edition against its twin. {"issues", "notes", "checks",
        "polish", "matched"}: lines and coded findings to add to the build's, and the patterns a blind edition matched."""
        import resume  # staging
        import check_blind as CB  # the blind findings' words
        out = {"issues": [], "notes": [], "checks": [], "polish": [], "matched": None}  # what this adds

        def take(report):  # a check's report into the build's lists
            if not report:  # it did not run: said in the log, and the edition's own checks still stand
                return
            out["checks"] += [x for x in report.get("defects") or [] if isinstance(x, dict) and isinstance(x.get("text"), str)]
            out["polish"] += [x for x in report.get("polish") or [] if isinstance(x, dict) and isinstance(x.get("text"), str)]
        spec = self.style_spec()  # the person's rules
        style = spec if spec == "default" else resume.rel(spec)  # staged where the container sees it
        prof, job = resume.rel(str(out_dir / "profile.json")), resume.rel(str(out_dir / "job.json"))  # this edition, as _check stages it
        if deck is not None and not Path(deck).resolve().is_relative_to((ROOT / "output").resolve()):  # the person's own deck file: theirs as it is,
            deck = None  # never measured against the resume (nor staged into the engine's folder)
        rep = ROOT / "output" / f"{name}.compare.json"  # where the checks write
        # 1. the resume against its deck, and the dated lists (a deck the person made is theirs: its pages are not measured)
        take(self._compare_tool(["python3", "src/check_parity.py", "edition", prof, job, resume.rel(str(pdf)),
                                 *([resume.rel(str(deck))] if deck else []), "--style", style], env, rep))
        # 2. the other language, when its edition was made from words of its own (a resume file the person made is not compared)
        other = "en" if lang == "ko" else "ko"  # the other edition
        od = self.build_dir(job_id, other)  # its folder
        orec = read_json(od / "build.json", {}) or {}  # its record
        if (od / "profile.json").is_file() and (od / "job.json").is_file() and "own_file" not in (orec.get("notes") or []):
            oprof, ojob = self._staged(od / "profile.json", f"{name}_other.profile.json"), self._staged(od / "job.json", f"{name}_other.job.json")
            pair = [prof, job, oprof, ojob] if lang == "ko" else [oprof, ojob, prof, job]  # Korean first
            notes = lang == self.reference_lang(job_id)  # the source's edition: its differences are notes
            take(self._compare_tool(["python3", "src/check_parity.py", "langs", *pair, "--style", style, *(["--notes"] if notes else [])], env, rep))
        # 3. a blind edition against its twin
        if twin is not None:  # a blind edition Offerowl typeset
            if twin.get("failed"):  # its twin could not be made: its bars were not checked, which is never taken for passed
                out["checks"].append(CB.report_item(CB.unchecked()))
            else:
                table = env.get("OFFEROWL_BLIND_TABLE") or "src/blind.json"  # the table the bars were made with
                files = [resume.rel(str(f)) for f in (twin.get("docx"), twin.get("page")) if f and Path(f).is_file()]  # the twin's own words
                got = self._compare_tool(["python3", "src/check_blind.py", "layout", resume.rel(str(twin["pdf"])), resume.rel(str(pdf)),
                                          *([resume.rel(str(twin["deck"])), resume.rel(str(deck))] if twin.get("deck") and deck else []),
                                          "--table", table, "--files", *files], env, rep)
                take(got)
                if got is not None:  # the patterns it matched, kept with the edition for the next blind edition's check
                    out["matched"] = sorted({p for p in got.get("matched") or [] if isinstance(p, str)})
                    seen = set(out["matched"]) | self.blind_matched_elsewhere(self.blind_stamp(), out_dir / "build.json")  # here or elsewhere
                    t = self.blind_table()  # the table as merged
                    keep = set(t.get("mask_keep") or [])  # kept on purpose
                    dead = [p for p in t.get("mask") or [] if p not in seen and p not in keep]  # matched by no blind edition's words
                    note = CB.dead_note(dead)  # a note: a pattern may be meant for an edition not made blind yet
                    if note:
                        out["polish"].append(CB.report_item(note))
        out["issues"] = [x["text"] for x in out["checks"]]  # the defects as lines, as the build keeps every check's
        out["notes"] = [x["text"] for x in out["polish"]]  # and the notes
        return out

    def parity_now(self, job_id: str, lang: str) -> list:
        """The differences between an edition and the edition in the source language as both are now, when this one is the
        other language's (the export holds a translation to its source): the defects' words, [] when there is nothing to
        compare or nothing differs. Run in a folder of its own in the engine's folder, gone again afterwards."""
        ref = self.reference_lang(job_id)  # the source's language
        if lang == ref:  # the source is held to nothing
            return []
        mine, src = self.build_dir(job_id, lang), self.build_dir(job_id, ref)  # the two editions
        if not all((d / f).is_file() for d in (mine, src) for f in ("profile.json", "job.json")):  # one was never made
            return []
        if "own_file" in ((read_json(src / "build.json", {}) or {}).get("notes") or []) or "own_file" in ((read_json(mine / "build.json", {}) or {}).get("notes") or []):
            return []  # a resume file the person made is theirs as it is
        short = hashlib.sha1(f"{self.ws.root.resolve()}|{job_id}|{lang}".encode()).hexdigest()[:8]  # a folder per edition
        tmp = ROOT / "output" / "_inputs" / f"parity_{short}"  # where the container sees the copies
        shutil.rmtree(tmp, ignore_errors=True)  # a fresh one
        tmp.mkdir(parents=True)
        try:
            names = {}  # the staged copies
            for side, d in (("ko", mine if lang == "ko" else src), ("en", mine if lang == "en" else src)):  # Korean first
                for f in ("profile.json", "job.json"):
                    shutil.copyfile(d / f, tmp / f"{side}_{f}")
                    names[f"{side}_{f}"] = (tmp / f"{side}_{f}").relative_to(ROOT).as_posix()
            spec = self.style_spec()  # the person's rules
            if spec != "default":  # a copy of their own in the same folder: a build's staged copy is its own to take away
                shutil.copyfile(spec, tmp / "pack.json")
                spec = (tmp / "pack.json").relative_to(ROOT).as_posix()
            env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_BLIND")}  # no blind switch the server was started with
            got = self._compare_tool(["python3", "src/check_parity.py", "langs", names["ko_profile.json"], names["ko_job.json"],
                                      names["en_profile.json"], names["en_job.json"], "--style", spec], env, tmp / "report.json")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)  # the person's words and rules do not stay in the engine's folder
        if got is None:  # it could not run: the export says so rather than passing it
            raise ValueError("parity_unchecked")
        return [x["text"] for x in got.get("defects") or [] if isinstance(x, dict) and isinstance(x.get("text"), str)]

    # ------------------------------------------------------------------ the baseline: the pages of the copy that last went out

    def baseline_dir(self, job_id: str, lang: str, blind: bool = False) -> Path:
        """Where an edition's baseline pages are kept: beside its previews, in the edition's own folder, one for the ordinary
        edition and one for the blind one (the bars are no change to a page that went out without them)."""
        return self.build_dir(job_id, lang) / (BASELINE + ("_blind" if blind else ""))

    @staticmethod
    def pillow_here() -> bool:
        """Can this process draw and compare pictures (Pillow)? Else the render container does it."""
        import importlib.util  # find_spec looks without importing
        return importlib.util.find_spec("PIL") is not None

    def page_reader(self) -> str:
        """Which program draws an edition's page pictures here, with its version: a baseline drawn by another one cannot be
        compared pixel by pixel (another reader rounds the edges of the letters otherwise)."""
        import pdftools  # the reader of this PC
        memo = getattr(self, "_page_reader", None)  # worked out once per panel
        if memo:
            return memo
        name = pdftools.reader()  # poppler, pdfium, or none (then the container draws them)
        version = ""  # its version
        try:
            if name == "poppler":  # pdftoppm -v writes its version to stderr
                r = subprocess.run(["pdftoppm", "-v"], capture_output=True, text=True, timeout=20)
                version = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[0].split()[-1]
            elif name == "pdfium":  # the library's own build number
                import pypdfium2  # loaded only to read it
                version = str(getattr(pypdfium2, "V_PDFIUM", ""))
            else:  # the render container: its image is named by its recipe's hash
                version = hashlib.md5((ROOT / "render" / "Dockerfile").read_bytes()).hexdigest()[:12]
        except (OSError, subprocess.SubprocessError, ImportError, IndexError):  # not readable: the name alone
            version = ""
        self._page_reader = f"{name or 'container'} {version}".strip()
        return self._page_reader

    @staticmethod
    def made_docs(out_dir: Path) -> set:
        """The documents an edition's last build made (r, d, c), by their PDFs: its preview folder may still hold an older
        letter's pages."""
        return {k for k, f in (("r", "resume.pdf"), ("d", "deck.pdf"), ("c", "cover.pdf")) if (out_dir / f).is_file()}

    def _baseline_run(self, cmd: str, previews: Path, kept: Path, extra: list) -> dict | None:
        """src/baseline.py keep or diff in the render container, for a PC whose Python has no Pillow: the pictures are copied
        into a folder of the engine's, worked on there and the results copied back. The comparison's JSON, or None."""
        import resume  # the container
        short = hashlib.sha1(str(kept.resolve()).encode()).hexdigest()[:8]  # a folder per edition
        tmp = ROOT / "output" / f"_panel_baseline_{short}"  # inside the repository, which the container sees
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            shutil.copytree(previews, tmp / "new") if previews.is_dir() else (tmp / "new").mkdir(parents=True)  # this build's pictures
            if kept.is_dir():  # the baseline's
                shutil.copytree(kept, tmp / "kept")
            rel = lambda p: p.relative_to(ROOT).as_posix()  # noqa: E731  as the container names it
            args = ["python3", "src/baseline.py", cmd, rel(tmp / "new"), rel(tmp / "kept"), *extra]
            if cmd == "diff":  # the comparison and its picture, into the folder
                args += ["--json", rel(tmp / "found.json"), "--picture", rel(tmp / CHANGES)]
            resume.sh(args)
            if cmd == "keep":  # the kept pictures back into the edition's folder
                shutil.rmtree(kept, ignore_errors=True)
                shutil.copytree(tmp / "kept", kept)
                return read_json(kept / "baseline.json", None)
            found = read_json(tmp / "found.json", None)  # what changed
            if (tmp / CHANGES).is_file():  # its picture
                shutil.copyfile(tmp / CHANGES, previews / CHANGES)
            return found
        except (OSError, SystemExit) as exc:  # no container either: no baseline here
            log.warning("baseline %s did not run: %s", cmd, exc)  # for the log only
            return None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)  # nothing of it stays

    def keep_baseline(self, job_id: str, lang: str, why: str) -> dict | None:
        """The edition's page pictures kept as its baseline (why: export, submitted, accepted), small (src/baseline.py), with
        when, from which reader and the hashes of its PDFs. The build record's changes go: this build is the baseline now.
        Returns the baseline's record, or None when there are no pictures to keep."""
        out_dir = self.build_dir(job_id, lang)  # the edition
        previews = out_dir / "preview"  # its pages
        rec = read_json(out_dir / "build.json", {}) or {}  # what the build made
        if not rec or not previews.is_dir() or not any(previews.glob("[rdc]-*.png")):  # nothing made, or no pictures of it
            return None
        record = {"at": time.strftime("%Y-%m-%d %H:%M"), "why": why, "reader": self.page_reader(), "hashes": rec.get("hashes") or {}, "build": rec.get("at") or ""}
        kept = self.baseline_dir(job_id, lang, rec.get("blind") is True)  # where they go: the blind edition's apart
        only = self.made_docs(out_dir)  # the documents this build made
        if self.pillow_here():  # here
            import baseline  # src/baseline.py
            got = baseline.keep(previews, kept, record, only)
        else:  # in the render container
            import json  # the record as an argument
            got = self._baseline_run("keep", previews, kept, ["--record", json.dumps(record, ensure_ascii=False), "--only", ",".join(sorted(only))])
        if got is not None and (out_dir / "profile.json").is_file():  # the words these pages were typeset from, kept with them: the depth review holds
            shutil.copyfile(out_dir / "profile.json", kept / "profile.json")  # a later edition to what went out (depth.py went_out)
        if got is not None:  # the edition shows no changes until a build differs from it
            (previews / CHANGES).unlink(missing_ok=True)
            with _record_lock:
                now = read_json(out_dir / "build.json", {}) or {}
                if now.get("at") == rec.get("at") and "changes" in now:  # the same build: its comparison is void
                    now.pop("changes", None)
                    write_json(out_dir / "build.json", now)
        return got

    def compare_baseline(self, job_id: str, lang: str, out_dir: Path, hashes: dict, blind: bool = False) -> dict | None:
        """What this build's pages changed since the edition's baseline, for its build record: {"since", "why", "docs":
        {resume|deck|cover: {before, after, pages, bands}}, "picture"}, or None when the edition has no baseline. A baseline
        drawn by another reader says so (reader_changed) instead of naming every page."""
        kept = self.baseline_dir(job_id, lang, blind)  # the baseline of the same kind of edition
        rec = read_json(kept / "baseline.json", None)  # its record
        previews = out_dir / "preview"  # this build's pages
        (previews / CHANGES).unlink(missing_ok=True)  # an older comparison's picture never stands for this one
        if not isinstance(rec, dict):  # none kept yet
            return None
        head = {"since": rec.get("at") or "", "why": rec.get("why") or ""}  # when and why it was kept
        if rec.get("reader") != self.page_reader():  # another reader drew it
            return {**head, "reader_changed": True, "docs": {}}
        import baseline as BL  # src/baseline.py
        if hashes and hashes == (rec.get("hashes") or {}):  # the very same PDFs: no page to draw
            return {**head, "docs": {BL.PREFIXES[k]: {"before": n, "after": n, "pages": []} for k, n in (rec.get("pages") or {}).items()}, "picture": False}
        only = self.made_docs(out_dir)  # the documents this build made
        if self.pillow_here():  # here
            docs = BL.compare(previews, kept, only)
            picture = BL.changed(docs) and BL.picture(previews, kept, docs, previews / CHANGES, lang)  # labelled in the edition's language
        else:  # in the render container
            docs = self._baseline_run("diff", previews, kept, ["--only", ",".join(sorted(only)), "--lang", lang]) or {}
            picture = (previews / CHANGES).is_file()
        docs = {k: {x: v.get(x) for x in ("before", "after", "pages")} for k, v in docs.items() if isinstance(v, dict)}  # the bands are in the picture: the record the panel polls stays small
        return {**head, "docs": docs, "picture": bool(picture)}

    def accept_baseline(self, job_id: str, lang: str) -> dict:
        """POST /api/v1/jobs/baseline: the edition's last build kept as its baseline, as an export keeps one. Refused with
        not_built when the edition has no pages."""
        got = self.keep_baseline(job_id, lang, "accepted")  # kept, or nothing to keep
        if got is None:
            raise ValueError("not_built")  # the page says to make the PDFs first
        return {"at": got.get("at"), "why": got.get("why"), "pages": got.get("pages") or {}}
