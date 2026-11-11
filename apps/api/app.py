"""Offerowl's API object: one person's settings, workspace, facts, agent card and long tasks, and every action the panel
(or the command line, or a script) can take on them. routes.py maps the HTTP paths to these methods; nothing here
knows about HTTP.

Every change goes through Workspace.change(), so one undo takes it back and the history lists it.
"""
from __future__ import annotations

import contextlib  # a job read that a deletion may overtake
import hashlib  # cache keys
import json  # the example profile
import logging  # what a refused backup held
import os  # environment
import re  # the names of style packs
import sys  # paths
import threading  # the agent card's first look
import time  # caches
from pathlib import Path  # paths

from . import materials  # a job's own materials, listed with the job
from .agent import BACKENDS, AgentCard  # the agent card
from .autopilot import runs as autopilot_runs  # the finished runs the page lists
from .facts import FACT_FILES, Facts, pick, problems, text_of  # facts and the profile
from .tasks import DECK_STYLES, FORMS, THEMES, Tasks, file_hash  # long tasks
from .workspace import STAGES, Workspace, read_json, retried, today, write_json, write_text  # files, undo, and moves waited for on Windows

log = logging.getLogger("offerowl.api")  # the panel's log
ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
EXAMPLE = ROOT / "examples" / "sample_ko.json"  # the fictional person the first run can try
EXAMPLE_EN = ROOT / "examples" / "sample_full_en.json"  # the same person, written in English, for someone using the panel in English
API_VERSION = 1  # the /api/v1 paths
GENERAL = "-general"  # the folder of the edition with no job; a company name never makes a leading dash
# What the person named when starting Offerowl (a compose file, a Helm value, a shell). Read once, here, since
# Tasks.backend later writes these names for src/llm.py. It keeps a local model from being replaced by an agent found on the PC.
START = {"backend": os.environ.get("OFFEROWL_LLM", "").strip(), "llm_url": os.environ.get("OFFEROWL_LLM_URL", "").strip(),
         "llm_model": os.environ.get("OFFEROWL_LLM_MODEL", "").strip()}


def data_dir() -> Path:
    """The app's data folder (OFFEROWL_DATA_DIR overrides it): %LOCALAPPDATA%\\Offerowl, ~/Library/Application
    Support/Offerowl, or $XDG_DATA_HOME/offerowl (~/.local/share/offerowl). The same rule as apps/desktop/app.py."""
    if os.environ.get("OFFEROWL_DATA_DIR"):  # tests and portable setups
        return Path(os.environ["OFFEROWL_DATA_DIR"]).expanduser().resolve()  # a ~ means the home folder; a relative path stays where it was given
    if sys.platform == "win32":  # Windows keeps app data per user, not roaming
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Offerowl"  # its usual place when unset
    if sys.platform == "darwin":  # macOS has its own folder for app data
        return Path.home() / "Library" / "Application Support" / "Offerowl"  # where Mac apps keep their files
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "offerowl"  # Linux: the XDG rule



def merge_requests(old: tuple | None, new: tuple) -> tuple:
    """Two requests that wait for the same run: the files of both, in order, and the newer posting and choices (the older
    posting when the newer has none). Fields: mids, paths, posting, url, again, theme, pages, job."""
    if not old:  # nothing waited
        return new
    mids = list(old[0]) + [m for m in new[0] if m not in old[0]]  # the files the page sent, both times
    paths = list(old[1]) + [p for p in new[1] if p not in old[1]]  # the files under the paths, both times
    posting, url = (new[2], new[3]) if (new[2].strip() or new[3].strip()) else (old[2], old[3])  # the newer posting, else the older
    return (mids, paths, posting, url, new[4] or old[4], new[5], new[6], new[7] or old[7])  # the newer choices

def is_day(text: str) -> bool:
    """A calendar day written YYYY-MM-DD, as the board's date field sends it."""
    import datetime  # only here
    try:
        return len(text) == 10 and datetime.date.fromisoformat(text).isoformat() == text  # 2026-02-30 and abcd-efghi are not days
    except ValueError:
        return False


class Api:
    """Everything one running Offerowl holds: the settings, the workspace, the facts, the agent card and the tasks."""

    def __init__(self, data: Path, workspace: Path | None = None):  # workspace: --workspace, else the saved setting
        self.data = Path(data)  # settings and logs
        self.data.mkdir(parents=True, exist_ok=True)  # the first start has no folder yet
        self.settings_file = self.data / "settings.json"  # the app's settings
        self.start = {k: v for k, v in START.items() if v and (k != "backend" or v in BACKENDS)}  # a change in the menu takes a value out
        ws_dir = workspace or Path(self.settings().get("workspace") or self.data / "workspace")  # the path setting
        self.ws = Workspace(ws_dir)  # the person's files
        self.facts = Facts(self.ws)  # facts and the profile
        self.card = AgentCard(self.settings)  # the agent card
        self.tasks = Tasks(self.ws, self.facts, self.card)  # long tasks
        self._fit_cache: dict = {}  # (job, posting hash, profile hash) -> fit
        self._fit_lock = threading.Lock()  # the page's polls and a write may ask for the same fit at once
        self._restoring = threading.Lock()  # one restore at a time
        threading.Thread(target=self.card.refresh, kwargs={"force": True}, daemon=True, name="agent").start()  # first look
        threading.Thread(target=self.tasks.letter_pages_all, daemon=True, name="letters").start()  # the pages of letters brought in before the build drew them

    # ------------------------------------------------------------------ settings

    def settings(self) -> dict:
        """The app's settings: language, theme, backend and the local server's address."""
        s = read_json(self.settings_file, {})  # saved choices
        return {"lang": "auto", "theme": "auto", "backend": os.environ.get("OFFEROWL_PANEL_BACKEND", "auto"),  # tests preset the backend
                "llm_url": "", "llm_model": "", **s, **self.start}  # defaults under the saved choices, what was named at the start over both

    PHOTO_KINDS = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png"}  # the start of each file a resume photo may be

    def photo_file(self):
        """The resume's photo in the workspace (profile/photo.jpg or .png), or None."""
        return next((f for f in (self.ws.path("profile", "photo.jpg"), self.ws.path("profile", "photo.png")) if f.is_file()), None)

    def set_photo(self, data: bytes) -> None:
        """A JPEG or a PNG as the resume's photo, by what the file is, not by its name, kept without what the camera
        wrote into it (apps/api/photo.py). It replaces the one before and goes on the resume (the setting can take it off again)."""
        from . import photo  # the metadata blocks out, the picture as it was
        kind = next((k for magic, k in self.PHOTO_KINDS.items() if data.startswith(magic)), None)  # what the bytes are
        if not kind:  # anything else is refused
            raise ValueError("photo")  # the page says to use a JPEG or a PNG
        clean = photo.clean(data, kind)  # no place, phone or time; a broken file is refused here like any other
        self.remove_photo()  # one photo at a time
        f = self.ws.path("profile", f"photo.{kind}")  # where it is kept
        f.parent.mkdir(parents=True, exist_ok=True)  # a new workspace has no profile folder yet
        f.write_bytes(clean)  # the picture alone
        self.set_settings({"photo": True})  # on the resume

    def remove_photo(self, keep: bool = False) -> str | None:
        """The resume's photo taken away. With keep (the person removed it) it waits in the Trash under a name of its own,
        profile/removed-photo-<day>-<time>.<kind>, until it is put back or deleted for good (removed.py): a second photo
        removed later never takes its place. A new photo that replaces it keeps nothing. Returns the Trash's id of the photo
        kept aside ("photo:<day>-<time>"), or None."""
        with self.ws.lock:  # one writer: a put-back or a deletion never meets this half way
            f, kept = self.photo_file(), None  # the photo, if any; its id in the Trash
            if f and keep:  # removed by the person: aside, whole
                base = f"removed-photo-{time.strftime('%Y%m%d-%H%M%S')}"  # the moment it went
                name, n = base, 2  # two removals in one second each keep their own
                while any(self.ws.path("profile", name + ext).exists() for ext in (".jpg", ".png")):
                    name, n = f"{base}-{n}", n + 1
                aside = self.ws.path("profile", name + f.suffix)  # removed-photo-20261110-153000.jpg
                retried(os.replace, f, aside)  # moved, not copied: the picture as it was
                os.utime(aside)  # its date says when it was removed
                kept = "photo:" + name[len("removed-photo-"):]  # how the Trash names it
            for f in (self.ws.path("profile", "photo.jpg"), self.ws.path("profile", "photo.png")):  # either kind
                f.unlink(missing_ok=True)  # gone
            return kept

    def photo_state(self) -> dict | None:
        """What the page shows of the photo: when it changed (for a fresh picture) and whether it goes on the resume."""
        f = self.photo_file()  # the file, if any
        return {"at": int(f.stat().st_mtime), "on": self.settings().get("photo", True) is not False} if f else None

    SCENE_ROLES = (("deep", "deep"), ("terms", "terms"), ("english", "reference"), ("notes", "reference"), ("research", "reference"))  # a kit file's role by the start of its name

    def add_scenes(self, jid: str, name: str, data: bytes) -> dict:
        """Interview scenes written before (the kit's own markdown: "### Q1. question" headings with 핵심, 면접관 and 나 lines) into
        the job's interview folder, beside the ones the agent writes. Refused when the file holds no scene. Returns how many."""
        from interview import corpus  # src/interview/corpus.py: the scene reader the search view uses
        jid = self.need_job({"job": jid})  # which job
        try:
            text = data.decode("utf-8-sig")  # the kit's files are UTF-8
        except UnicodeDecodeError as exc:
            raise ValueError("not_scenes") from exc
        stem = re.sub(r"[^\w가-힣-]+", "_", Path(name).stem).strip("_")[:60] or "scenes"  # a safe name
        role = next((r for start, r in self.SCENE_ROLES if stem.lower().startswith(start)), "scenes")  # deep dives, terms and notes keep their roles
        items = corpus.parse_text(text, stem, stem[:1].upper(), role, f"{stem}.md")  # what the search view would read
        if not items:  # no scene in it
            raise ValueError("not_scenes")
        iv = self.ws.job_dir(jid) / "interview"  # the job's kit folder
        iv.mkdir(parents=True, exist_ok=True)
        dest, n = iv / f"{stem}.md", 2  # never over a file already there
        while dest.exists():
            dest, n = iv / f"{stem}-{n}.md", n + 1
        dest.write_text(text, encoding="utf-8")  # kept as written
        kit = read_json(iv / "kit.json", {}) or {}  # the kit's settings
        if kit.get("sources") is not None:  # a kit that names its files: this one joins with its role
            kit["sources"] = list(kit["sources"]) + [{"file": dest.name, "role": role}]
        elif role != "scenes":  # the default reads every file as scenes: name the roles once
            kit["sources"] = [{"file": f.name, "role": next((r for start, r in self.SCENE_ROLES if f.stem.lower().startswith(start)), "scenes")} for f in sorted(iv.glob("*.md"))]
            kit["sources"].append({"file": "@stories", "role": "reference"})  # the workspace's stories stay searchable
        write_json(iv / "kit.json", kit)  # saved
        self.tasks.ensure_kit(jid, "ko")  # the question map sees them
        return {"scenes": len(items), "file": dest.name}

    def questions_of(self, jid: str) -> list[dict]:
        """A job's application questions as the page shows them: each with its answer's length as the form counts it, and
        the facts the answer rests on (apps/api/answers.py)."""
        from . import answers as A  # the counting
        qs = read_json(self.ws.job_dir(jid) / "questions.json", {}).get("questions") or []  # as kept
        heads = {c["cid"]: " · ".join(x for x in (c.get("org"), c.get("title")) if x) for c in self.facts.candidates()} if any(q.get("cites") for q in qs) else {}  # each fact's name
        return [{**q, "count": A.count(q.get("answer", ""), q.get("unit", "chars")), "cited": [{"id": c, "title": heads.get(c, "")} for c in q.get("cites") or [] if c in heads]} for q in qs]

    def set_questions(self, req: dict) -> None:
        """A job's questions as the page sends them, in order; a question that did not change keeps its answer."""
        import draft  # src/draft.py: the style pack
        from . import answers as A  # the checks
        jid = self.need_job(req)  # which job
        f = self.ws.job_dir(jid) / "questions.json"  # where they are kept
        with A.LOCK:  # the answering task writes here too
            qs = A.clean_questions(req.get("questions"), read_json(f, {}).get("questions") or [])  # checked, ids kept
            if any(q.get("issues") == ["recheck"] for q in qs):  # an answer under a new limit or unit: checked again now, against every kept fact
                by_id = {x["id"]: x["text"] for x in self.tasks.answer_facts(notes=True)}  # what the answers may say, the profile's notes too
                style = draft.style_pack(self.tasks.style_spec())  # the person's rules
                posting = self.tasks.posting_of(jid)  # the names the posting gives
                qs = [{**q, "issues": A.problems(q, q["answer"], [], by_id, style, posting)} if q.get("issues") == ["recheck"] else q for q in qs]  # the length and the rest, as the export will check them
            write_json(f, {"questions": qs})  # kept

    def paste_questions(self, req: dict) -> int:
        """The questions of a form pasted as the form shows them, read with their limits and added after the ones kept.
        Returns how many were added."""
        from . import answers as A  # the reading and the checks
        jid = self.need_job(req)  # which job
        found = A.parse_questions(str(req.get("text") or "")[:20000])  # each question with its limit
        if not found:  # nothing that reads as a question
            raise ValueError("no_questions")
        f = self.ws.job_dir(jid) / "questions.json"  # where they are kept
        with A.LOCK:  # the answering task writes here too
            old = read_json(f, {}).get("questions") or []  # as kept
            have = {q.get("text") for q in old}  # a question pasted twice is kept once
            rows = [{"text": q["text"], "limit": q["limit"], "unit": q["unit"]} for q in old] + [q for q in found if q["text"] not in have]
            write_json(f, {"questions": A.clean_questions(rows, old)})  # ids and answers kept
        return len([q for q in found if q["text"] not in have])

    def questions_from_file(self, jid: str, name: str, data: bytes) -> int:
        """A form's questions read from a file of it: a screenshot (OCR, Korean and English), a PDF, a saved page or a text file."""
        import tempfile  # the file, for a moment
        import ingest  # src/ingest.py: the same readers as the person's files
        jid = self.need_job({"job": jid})  # which job
        suffix = Path(name).suffix.lower()  # its kind, by its name
        if suffix not in ingest.IMAGES + (".pdf", ".txt", ".md", ".html", ".htm", ".docx"):  # a kind with no reader
            raise ValueError("no_questions")
        with tempfile.TemporaryDirectory() as tmp:  # gone afterwards
            f = Path(tmp) / f"form{suffix}"
            f.write_bytes(data)
            if suffix in (".html", ".htm"):  # a saved page: its text without the markup
                from . import postings  # the page reader the links use
                text = postings.page_text(data.decode("utf-8", "replace"))
            else:
                text = ingest.ocr(f, block=True) if suffix in ingest.IMAGES else ingest.to_text(f)  # a screenshot read line by line; a PDF's text layer
        return self.paste_questions({"job": jid, "text": text})

    def edit_answer(self, req: dict) -> None:
        """The person's own words for one answer, checked as a drafted answer is (length, facts, style)."""
        import draft  # src/draft.py: the style pack
        from . import answers as A  # the checks
        jid = self.need_job(req)  # which job
        f = self.ws.job_dir(jid) / "questions.json"  # where they are kept
        qs = read_json(f, {}).get("questions") or []  # as kept
        qid, text = str(req.get("id") or ""), req.get("answer")  # which and what
        if not isinstance(text, str) or len(text) > A.MAX_LIMIT * 2 or not any(q.get("id") == qid for q in qs):  # a stale page or an odd value
            raise ValueError("question")  # refused
        style = draft.style_pack(self.tasks.style_spec())  # the person's rules
        facts = self.tasks.answer_facts(notes=True)  # what the answers may say: the person's own words are checked against the profile's notes too
        with A.LOCK:  # the answering task writes here too: the file as it is now
            qs = read_json(f, {}).get("questions") or []  # read again under the lock
            if not any(q.get("id") == qid for q in qs):  # removed meanwhile
                raise ValueError("question")
            posting = self.tasks.posting_of(jid)  # the names the posting gives
            write_json(f, {"questions": [A.checked_edit(q, text, facts, style, posting) if q.get("id") == qid else q for q in qs]})  # checked and kept

    def style_names(self) -> list[str]:
        """The person's own style packs, kept in the workspace's style/ folder (docs/WRITING.md)."""
        folder = self.ws.path("style")  # where they live
        return sorted(f.stem for f in folder.glob("*.json")) if folder.is_dir() else []  # by name

    def add_style(self, req: dict) -> str:
        """A person's own style pack into the workspace's style/ folder, checked first, so a broken pattern can never stop a
        check later. {name, pack}: the pack is the JSON of docs/WRITING.md. Returns the name it is kept under."""
        name = re.sub(r"[^\w가-힣.-]+", "-", str(req.get("name") or "").strip())[:60].strip("-.") or "mine"  # a safe file name
        if name == "default":  # the shipped pack keeps its name
            name = "mine"
        pack = req.get("pack")  # the rules
        if not isinstance(pack, dict) or not pack or len(json.dumps(pack, ensure_ascii=False)) > 200_000:  # a JSON object of a sane size
            raise ValueError("style")  # the page says it is not a style pack
        if not isinstance(pack.get("banned_chars", ""), str) or any(not isinstance(pack.get(k, {}), dict) for k in ("resume", "cover")):  # the shapes the checks read
            raise ValueError("style")
        words = lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)  # noqa: E731  a list of words or rules
        each = lambda v: words(v) or (isinstance(v, dict) and all(words(x) for x in v.values()))  # noqa: E731  one list, or one per language
        res, cov = pack.get("resume") or {}, pack.get("cover") or {}  # the two objects the writers read
        if not each(res.get("rules", [])) or not each(res.get("banned_words", [])) or not words(cov.get("banned_words", [])):  # the lists the prompts and the checks walk
            raise ValueError("style")
        if not isinstance(pack.get("banned_patterns", []), list):  # a list of [pattern, why]
            raise ValueError("style")
        for row in pack.get("banned_patterns") or []:  # each pattern must compile, or every check would stop on it
            if not (isinstance(row, list) and len(row) == 2 and all(isinstance(x, str) for x in row)):  # [pattern, why]
                raise ValueError("style")
            try:
                re.compile(row[0])  # a broken pattern is refused here, not at the next check
            except re.error as exc:
                raise ValueError("style") from exc
        import tempfile  # the pack read once by the writers' own loader before it is kept
        import write_resume  # src/write_resume.py: its loader reads the cover options too (src/cover.py)
        with tempfile.TemporaryDirectory() as tmp:  # never in the style folder, where the panel lists the packs
            trial = Path(tmp) / f"{name}.json"  # the pack as it would be kept
            write_json(trial, pack)
            try:
                write_resume.load_style(str(trial))  # an unknown numbers policy, say, stops every later draft: stopped here instead
            except (SystemExit, Exception) as exc:  # the loader's message, or a value it cannot use
                raise ValueError("style") from exc
        write_json(self.ws.path("style", f"{name}.json"), pack)  # kept with the workspace (and its backups)
        return name  # the page selects it

    def blind_view(self) -> dict:
        """What the panel shows of the mask table of the blind edition: whether it is the person's own (else Offerowl's, which
        covers nothing), how many patterns each of its lists holds, and its stamp (what an edition's bars were made with)."""
        import blind  # src/blind.py: the lists
        return {"own": self.tasks.blind_file() is not None, "counts": blind.counts(self.tasks.blind_table()),
                "stamp": self.tasks.blind_stamp()}  # which table it is: an edition made with another one says so

    def blind_read(self) -> dict:
        """The mask table as kept: the person's own file, else the shipped one (src/blind.json), with the summary."""
        import blind  # src/blind.py: the shipped table's place
        f = self.tasks.blind_file()  # theirs, if any
        table = read_json(f if f else blind.DEFAULT, {})  # as it is on disk
        return {"table": table if isinstance(table, dict) else {}, **self.blind_view()}

    def set_blind(self, req: dict) -> dict:
        """The person's own mask table for the blind edition, kept as the workspace's blind.json (never in the repository):
        {table} replaces it once it passes src/blind.py's checks (each pattern read alike by Python and JavaScript, colours
        and words of a sane shape and size), {table: null} takes it away, so the shipped table applies again. One undo step.
        Refused with blind_table, or blind_pattern:<list>:<n> for the first pattern that cannot be used. Returns the summary."""
        import blind  # src/blind.py: the checks
        if "table" not in req:  # a request that names no table changes nothing
            raise ValueError("blind_table")
        f = self.ws.path("blind.json")  # beside the profile and the jobs
        table = req["table"]  # the new table, or None
        if table is not None:  # a table to keep: checked first
            found = blind.problems(table)  # what stops it
            if found:  # the first one, in words the page can say
                where = found[0].split(":")  # list:n:why, or key:why
                raise ValueError(f"blind_pattern:{where[0]}:{where[1]}" if where[0] in blind.LISTS and where[1].isdigit() else "blind_table")
        with self.ws.change({"code": "undo_blind"}, ["blind.json"]):  # undo brings the old table back
            if table is None:  # taken away
                f.unlink(missing_ok=True)
            else:  # only the keys the table has: anything else in the file stays out of the workspace
                write_json(f, blind.kept(table))
        return self.blind_view()

    def restore(self, data) -> dict:
        """A backup in the workspace's place, when no task is writing to it. Returns the name of the folder that keeps the old one."""
        from . import backup  # only when asked
        if not self._restoring.acquire(blocking=False):  # two at once would share a working folder
            raise ValueError("busy")  # the page says to wait
        try:
            if any(t.get("state") == "running" for t in self.tasks.state().values()):  # a task would write into a folder that has moved
                raise ValueError("busy")  # the page says to wait
            kept = backup.restore(self.ws, data)  # swapped, or refused with the old files as they were
            self._fit_cache.clear()  # fits of the old files
            self.tasks.live_decks.clear()  # and their pages
            self.tasks.live_figures.clear()  # and their pictures
            self.ws.gone.clear()  # a job deleted for good before may be one the backup holds: its folder is the backup's now
            try:
                self.state()  # what the page draws next: the names were fine, but what is in the files?
            except Exception as exc:  # a file of the backup the panel cannot read, which would stop it at every start
                log.warning("backup refused after unpacking: %s", exc)  # for the log only
                backup.take_back(self.ws, kept)  # the person's files as they were
                raise ValueError("not_a_backup") from exc  # the page says so
            return {"kept": kept}  # for the page to say
        finally:
            self._restoring.release()  # the next one may start

    def set_settings(self, req: dict) -> dict:
        """Change the settings that were sent (each one checked)."""
        s = read_json(self.settings_file, {})  # saved choices
        if req.get("lang") in ("auto", "ko", "en"):  # only a language the page offers
            s["lang"] = req["lang"]  # kept for the next start
        if req.get("theme") in ("auto", "light", "dark"):  # only a theme the page draws
            s["theme"] = req["theme"]  # kept for the next start
        choice = req.get("backend") if req.get("backend") in BACKENDS else None  # only a backend the menu offers
        if choice == "none" and self.settings()["backend"] != "none":  # "No agent" picked from the list: remembered as the switch does,
            s["backend_on"] = self.settings()["backend"]  # so "on" brings back the agent just used, not "auto"
        if req.get("agent") == "off":  # the switch: off, and it remembers what it switched off
            now = self.settings()["backend"]  # the choice in force
            if now != "none":  # switching off twice keeps the first choice
                s["backend_on"] = now  # what the switch brings back
            choice = "none"  # no agent
        elif req.get("agent") == "on":  # the switch: back to what it was, so a local model is not lost on the way
            choice = s.get("backend_on") or "auto"  # never switched off: look for one
        if choice:  # the menu or the switch chose
            s["backend"] = choice  # the agent the tasks will call
            self.start.pop("backend", None)  # from here on the choice wins over what was named at the start
            self.card.look_again()  # look again with the new choice
        if req.get("form") in FORMS:  # only a form the resume has
            s["form"] = req["form"]  # kept for the next build
        if req.get("deck_style") in DECK_STYLES:  # only a look the deck has
            s["deck_style"] = req["deck_style"]  # kept for the next build
        if isinstance(req.get("export_extras"), bool):  # Word and text files on the Desktop too, or the PDFs alone
            s["export_extras"] = req["export_extras"]
        if isinstance(req.get("export_pptx"), bool):  # the portfolio as a PowerPoint file too: a setting of its own, since it is
            s["export_pptx"] = req["export_pptx"]  # a picture of each page that the person asks for, not a file the typesetting already wrote
        turned_on = req.get("desk_portfolio") is True and s.get("desk_portfolio") is not True  # the portfolio kept on the Desktop, just asked for
        if isinstance(req.get("desk_portfolio"), bool):  # the general edition's portfolio kept on the Desktop after every build that passes
            s["desk_portfolio"] = req["desk_portfolio"]
        if isinstance(req.get("photo"), bool):  # the photo on the resume, or not
            s["photo"] = req["photo"]  # kept for the next build
        if isinstance(req.get("style"), str) and (req["style"] == "default" or req["style"] in self.style_names()):  # the writing rules: the shipped pack, or one of the workspace's own
            s["style"] = req["style"]  # every draft and check uses it from now on (Tasks.style_spec)
        for k in ("llm_url", "llm_model"):  # the local model server's address and model
            if isinstance(req.get(k), str):  # a missing or odd value leaves it as it was
                s[k] = req[k].strip()[:300]  # trimmed and bounded
                self.start.pop(k, None)  # the menu wins from here on
                self.card.look_again()  # whether the new address answers is said now, not at the next minute's look
        write_json(self.settings_file, s)  # saved
        if turned_on:  # an edition that passed already goes there now, not at the next build
            from . import delivery  # the portfolio kept on the Desktop
            for lang in ("ko", "en"):  # each language made
                try:
                    delivery.keep_portfolio(self.tasks, lang)  # nothing when that edition was never made or did not pass
                except OSError as exc:  # a Desktop that cannot be written: the next build tries again
                    log.warning("portfolio not kept on the Desktop: %s", exc)  # for the log only
        return self.settings()  # with the defaults filled in again

    def desk_view(self) -> dict:
        """The portfolio desk_portfolio keeps on the Desktop: the names there now ([] when the setting is off)."""
        if self.settings().get("desk_portfolio") is not True:  # off: the Desktop is not even looked at
            return {"kept": []}
        from . import delivery  # its record
        try:
            return {"kept": delivery.kept_names(self.tasks)}  # by name only: a file path never reaches the page
        except OSError:  # a Desktop that cannot be read
            return {"kept": []}

    # ------------------------------------------------------------------ what the page draws

    def profile_hash(self) -> str:
        """The hash of the profile as it is now (an edition made from another one is stale)."""
        return file_hash(self.ws.path("profile", "profile.json"))  # compared with the hash each edition recorded

    def same_profile(self, recorded: str | None) -> bool:
        """Was an edition made from the profile as it is now? It records the profile's content hash (tasks._build); an older
        edition recorded its bytes. The same content written again (a rebuild that changed nothing) is the same profile."""
        from .tasks import content_hash  # the content, whatever its spacing
        src = self.ws.path("profile", "profile.json")  # the profile
        return bool(recorded) and recorded in (content_hash(src), file_hash(src))

    def fit(self, job_id: str, posting: str | None = None) -> dict:
        """The fit of the profile to a job's posting (fit.compute), cached until the posting or the profile changes. A caller
        that read the posting already passes it (the state reads each job's once per poll)."""
        from . import fit as F  # the fit by words
        posting = self.ws.posting(job_id) if posting is None else posting  # the posting, read now unless given
        key = (job_id, hashlib.sha1(posting.encode("utf-8")).hexdigest(), self.profile_hash())  # what the fit depends on
        with self._fit_lock:  # one computation per key, and the cache never changes while it is read
            return self._fit_for(key, job_id, posting, F)  # cached or made now

    def _fit_for(self, key: tuple, job_id: str, posting: str, F) -> dict:
        """The fit for a cache key (the caller holds the lock)."""
        if key not in self._fit_cache:  # not computed for this pair yet
            prof = self.facts.profile()  # the profile now
            self._fit_cache = {k: v for k, v in self._fit_cache.items() if k[0] != job_id}  # older fits of this job go
            self._fit_cache[key] = F.compute(prof, posting, evmap=self.facts.evidence(), cands=self.facts.candidates(), profile_key=key[2]) if posting.strip() and prof.get("roles") else \
                {"score": 0, "by": "words", "counts": {"strong": 0, "weak": 0, "none": 0}, "lines": [], "gaps": [], "reason": "no_profile" if posting.strip() else "no_posting"}
        return self._fit_cache[key]  # the same answer while nothing changed

    def general_view(self) -> dict:
        """The edition made with no job in view: PDFs of the profile as it is, for a person who has not picked a posting yet."""
        from . import documents  # editions
        builds = documents.editions(self.tasks, GENERAL)  # per language
        for b in builds.values():  # each edition
            b["stale"] = not self.same_profile(b.get("profile")) or b.get("draft", "") != self.tasks.draft_stamp(GENERAL) or self.blind_stale(b) or self.deck_stale(b)  # facts, the draft, the mask table or the deck source changed since
        return {"id": GENERAL, "builds": builds}  # the shape of a job, as far as the Documents view reads one

    def jobs_view(self) -> list[dict]:
        """Every job with its analysis, its fit's summary and its last editions."""
        out = []  # one per job
        for st in self.ws.jobs():  # oldest first
            with self.gone_meanwhile(st["id"]):  # deleted for good while this was read: left out
                out.append(self.job_view(st))
        return out  # in the board's order

    @contextlib.contextmanager
    def gone_meanwhile(self, jid: str):
        """Read one job, and leave it out when it was deleted for good while it was read (removed.py takes its folder away
        under the workspace's lock, which a read of the state does not take). Any other error is a bug and says so."""
        try:
            yield
        except (ValueError, OSError):  # its id refused by job_dir, or a file of it gone between a look and a read
            if jid not in self.ws.gone:  # not a deletion: as it was
                raise

    def job_view(self, st: dict) -> dict:
        """One job as the page draws it: its analysis, its fit's summary and its last editions."""
        from . import documents, tracker  # editions, and the days that count
        jd = self.ws.job_dir(st["id"])  # its folder
        plan = read_json(jd / "plan.json", {})  # the posting analysis
        builds = documents.editions(self.tasks, st["id"])  # per language
        for b in builds.values():  # each edition
            b["stale"] = self.stale(st["id"], b)  # facts, the draft or the job's own edition changed since
        posting = self.ws.posting(st["id"])  # empty when it is gone
        f = self.fit(st["id"], posting)  # the fit (cached), from the same reading
        return {**st, "plan": {k: plan.get(k) for k in ("skillsFocus", "competencyWeak", "projectOrder", "at", "by")},  # only what the page shows
                "questions": self.questions_of(st["id"]),  # the application's own questions and their answers
                "materials": materials.listing(self.ws, st["id"]),  # the decks, notes and briefs brought in for its interview
                "builds": builds, "posting_chars": len(posting),  # its editions and the posting's size
                "posting_head": posting.strip().splitlines()[0][:120] if posting.strip() else "",  # its first line, for the card
                "fit": {"score": f["score"], "counts": f["counts"], "gaps": len(f["gaps"])},  # the fit's summary
                "days": tracker.stage_days(st),  # the days of the stages it went through, as the board and the timeline show them
                "kit": self.kit_stamp(st["id"]),  # when the interview kit's map was last made (0: never)
                "own": self.tasks.own_langs(st["id"])}  # the languages of the resume the person brought in for it, if any

    def kit_stamp(self, job_id: str) -> float:
        """When the job's interview map was last written (0 when there is no kit): the page reads the board again on a change."""
        if not (self.ws.job_dir(job_id) / "interview").is_dir():  # no kit folder
            return 0.0  # never made
        f = self.ws.path("out", "interview", job_id, "plan.json")  # where the tailor step writes the map (src/interview's out_dir)
        return round(f.stat().st_mtime, 3) if f.is_file() else 0.0  # its time, or 0 before the first map

    def draft_view(self, prof: dict) -> dict:
        """The profile's parts the pages show beside the facts (picked field by field: the page never gets the file)."""
        roles = [{"org": r.get("org"), "title": r.get("title"), "start": r.get("start"), "end": r.get("end"),  # roles, trimmed
                  "projects": [{"id": p.get("id"), "title": p.get("title"), "period": p.get("period"),
                                "summary": p.get("summary")} for p in r.get("projects") or []]}
                 for r in prof.get("roles") or []]  # what the profile page shows
        return {"person": {k: (prof.get("person") or {}).get(k, "") for k in ("name", "name_en", "email", "phone", "tagline")},  # who
                "headline": text_of(pick((prof.get("summary") or {}).get("headline"))), "roles": roles,  # the headline and roles
                "skills": [{"category": s.get("category", ""), "items": s.get("items") or []} for s in prof.get("skills") or []]}  # skills

    def onboarding(self) -> dict:
        """Where the first run stands: done once the person reached the first resume, or had material before."""
        prefs = self.ws.prefs()  # kept with the workspace
        if "onboarded" in prefs:  # decided: finished, or the tour asked for again
            done = bool(prefs["onboarded"])  # as kept
        else:  # an older workspace with kept facts counts as done
            done = bool(self.ws.materials() and self.facts.view()["counts"]["kept"])  # it has its first resume already
        return {"done": done, "step": prefs.get("onboarding_step") or "welcome", "started": prefs.get("onboarding_started")}  # the page resumes there

    def state(self) -> dict:
        """Everything the page draws, in one answer. The tasks are read first: a task writes its files before it says it has
        ended, so what is read after them is at least as new, and one answer never says a task is done beside what was there
        before it ran (read last, an analysis that ended while the rest was read came back "done" with the words' old plan).
        The facts come as their counts and a stamp: the rows are most of the bytes and only the profile view draws them, from
        /api/v1/facts when the stamp changes."""
        with self.tasks.one_read():  # the deck source's stamp worked out once for every edition, not once per edition
            return self._state()

    def facts_summary(self) -> dict:
        """The facts as the state carries them: the counts, and a stamp of the rows (a short hash of them) that changes with any
        fact's state, edit or text, so the profile view knows when to read the rows again."""
        v = self.facts.view()  # rows and counts
        return {"counts": v["counts"], "rev": hashlib.sha1(json.dumps(v["rows"], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]}

    def _state(self) -> dict:
        """state, inside one read."""
        from . import removed, tracker  # what was taken off, due reminders
        tasks = self.tasks.state()  # first, as the docstring says
        prof = self.facts.profile()  # the profile
        prefs = self.ws.prefs()  # the job in view, the guide
        jobs = self.jobs_view()  # the jobs
        pick = prefs.get("job")  # the job chosen to be in view, or the general edition
        # that job, the general edition when it was chosen, or the newest job when the chosen one is gone
        editions = self.editions_view()  # the named general editions
        current = pick if pick == GENERAL or any(j["id"] == pick for j in jobs + editions) else (jobs[-1]["id"] if jobs else None)
        undo_id, undo_label = self.ws.newest()  # what the undo key takes back, and its name: a toast's Undo sends the name, so it never takes back a later change
        return {  # one answer redraws the whole page
            "app": "offerowl", "api": API_VERSION, "version": app_version(), "settings": self.settings(), "styles": self.style_names(), "blind": self.blind_view(), "desk": self.desk_view(), "photo": self.photo_state(), "agent": self.card.card(), "agent_calls": self.agent_calls(), "materials": self.ws.materials(),
            "facts": self.facts_summary(), "details": self.facts.details(), "draft": self.draft_view(prof), "problems": problems(prof),
            "jobs": jobs, "job": current, "general": self.general_view(), "editions": editions, "tasks": tasks, "runs": autopilot_runs(self.ws), "onboarding": self.onboarding(),
            "english": bool(self.tasks.english_for(current)), "profile_lang": self.tasks.profile_lang(), "engine": self.tasks.engine_ready(),
            "engine_needs": list(self.tasks.engine_needs),  # what the browser renderer lacks, when "engine" says so
            "renderer": self.tasks.renderer_in_use(),  # "html" (this PC's browser) or "container", for the guide's words
            "features": {"cover": self.tasks.cover_available(), "interview": self.tasks.interview_available()},
            "undo": undo_label, "undo_id": undo_id, "history": self.ws.history_count(),  # the steps counted by their files' names, not read
            "removed": removed.counts(self),  # what the Trash holds, by kind: put back or deleted for good there
            "themes": list(THEMES), "stages": list(STAGES),
            "today": today(), "due": tracker.due(jobs), "open": prefs.get("open")}  # the step an entry point asked to open first (src/ui opens the facts)

    # ------------------------------------------------------------------ material and facts

    def add_example(self, lang: str | None = None) -> dict:
        """The fictional example person as material, read at once: the first run's "Try it with an example". In English when
        the panel is, so the first resume a person sees is one they can read."""
        example = EXAMPLE_EN if lang == "en" else EXAMPLE  # by the page's language
        rec = self.ws.add_material(example.name, example.read_bytes())  # kept in sources/ like a picked file
        self.ws.update_material(rec["id"], example=True)  # marked: a run on the person's own files takes it out first
        self.tasks.ingest([rec["id"]])  # read as a profile file: no agent
        return rec  # its record

    def drop_example(self) -> int:
        """Take the fictional example out before a person's own files are read: its file, its facts and the details it
        filled in (remove_material). Returns how many example files went."""
        gone = [m["id"] for m in self.ws.materials() if m.get("example")]  # the example's files still listed
        for mid in gone:  # each, with one undo step each
            self.remove_material(mid)
        return len(gone)

    def fact(self, req: dict) -> None:
        """Keep, drop, edit or put back one fact."""
        cid, act = str(req.get("cid") or ""), req.get("action")  # which and what
        known = {c["cid"]: c for c in self.facts.candidates()}  # every fact
        if cid not in known or act not in ("keep", "drop", "edit", "reset"):  # only a listed fact and a known action
            raise ValueError("fact")  # a stale page or a made-up request
        label = {"code": f"undo_{act}", "title": (known[cid].get("title") or known[cid].get("statement") or "")[:60]}  # the undo button's words
        with self.ws.change(label, FACT_FILES):  # one undo step
            if act == "edit":  # their own wording of the fact
                self.facts.set_edit(cid, req.get("fields") or {})  # their version
                self.facts.set_status(cid, "accepted")  # an edited fact is kept
            else:  # keep, drop or put back
                self.facts.set_status(cid, {"keep": "accepted", "drop": "rejected", "reset": None}[act])  # None: to confirm again
            self.facts.rebuild()  # the profile follows

    def own_edition(self, req: dict) -> dict:
        """Bring in a resume the person already wrote for one job, whole: its items become that job's own facts, all kept,
        in the job's folder apart from the profile, and the job's documents print it as written (tasks.facts_for). A second
        one replaces the first. Returns how many facts it gave."""
        jid = self.need_job(req)  # which job, or a named general edition
        if jid == GENERAL:  # the general edition is the profile itself
            raise ValueError("job")
        doc, langs = req.get("profile"), [x for x in (req.get("langs") or []) if x in ("ko", "en")]  # the edition and its languages
        if not isinstance(doc, dict) or not doc.get("roles") or not langs:  # nothing a resume could print
            raise ValueError("profile")
        import shutil  # the edition before is replaced whole
        from .facts import OwnFacts  # the job's own facts
        root = self.ws.job_dir(jid) / "own"  # beside the job's other files
        with self.ws.lock:  # one writer
            shutil.rmtree(root, ignore_errors=True)  # a second one replaces the first
            self.tasks.forget_own(jid)  # nothing read from the one before
            facts = OwnFacts(Workspace(root), self.facts)  # its own workspace
            n = facts.import_profile(doc, "own", str(req.get("name") or "own edition")[:120])  # its items as facts
            write_json(root / "sources" / "review.json", {c["cid"]: "accepted" for c in facts.candidates()})  # all kept: the person wrote them
            facts.rebuild()  # its profile and evidence
            write_json(root / "own.json", {"langs": langs, "name": str(req.get("name") or "")[:120], "at": today()})  # what it is
            from .tasks import OWN_FORM_KEYS  # the layout choices the form reads
            form = req.get("form") if isinstance(req.get("form"), dict) else {}  # per language, as the edition was made
            write_json(root / "form.json", {lang: {k: v for k, v in (form.get(lang) or {}).items() if k in OWN_FORM_KEYS}
                                            for lang in langs if isinstance(form.get(lang), dict)})  # kept beside it
            self.tasks.forget_own(jid)  # read afresh
        return {"facts": n}

    def add_edition(self, req: dict) -> str:
        """A named general edition (one for headhunters, one per target role): no posting, never on the board. Returns its id."""
        name = " ".join(str(req.get("name") or "").split())[:80]  # its name, on one line, bounded
        if not name:  # a name is what tells it apart
            raise ValueError("name")
        jid = self.ws.new_edition_id(name)  # its folder name
        n = len(self.ws.jobs(removed=True, kind="edition")) + 1  # a counter for the order of editions made the same day
        with self.ws.change({"code": "undo_add_edition", "company": name}, self.ws.job_files(jid)):  # undo takes it away
            self.ws.save_job({"id": jid, "kind": "edition", "name": name, "company": "", "role": name, "created": today(), "seq": n})  # its record
        return jid

    def deck_stale(self, b: dict) -> bool:
        """An edition whose deck was written from another deck source than the one in the workspace now (one made before there
        was a source, or from a PDF, records none and stays as it was)."""
        return bool(b.get("deck_src")) and b.get("deck_src") != self.tasks.deck_stamp()

    def blind_stale(self, b: dict) -> bool:
        """A blind edition made with another mask table than the one kept now: its bars are not the table's."""
        return b.get("blind") is True and b.get("blind_table", "") != self.tasks.blind_stamp()

    def stale(self, jid: str, b: dict) -> bool:
        """Was this edition made from what there is now? An edition made from the job's own edition or own files follows those
        (an older build that did not record them counts as current); any other follows the profile and the draft. A blind
        edition follows its mask table too."""
        if self.blind_stale(b) or self.deck_stale(b):  # the table changed since its bars were drawn, or the deck source since it wrote the deck
            return True
        own = self.tasks.own_stamp(jid)  # the job's own things, if any
        if own:  # printed from them, not from the profile
            return b.get("own") is not None and b.get("own") != own
        return not self.same_profile(b.get("profile")) or b.get("draft", "") != self.tasks.draft_stamp(jid)  # facts or the draft changed since

    def editions_view(self) -> list[dict]:
        """Every named general edition with its last PDFs (the Documents view's picker and canvas read these)."""
        from . import documents  # editions
        out = []  # one per edition
        for st in self.ws.editions():  # oldest first
            with self.gone_meanwhile(st["id"]):  # deleted for good while this was read: left out
                builds = documents.editions(self.tasks, st["id"])  # per language
                for b in builds.values():  # each edition
                    b["stale"] = self.stale(st["id"], b)  # facts, the draft or the job's own edition changed since
                out.append({**st, "builds": builds, "own": self.tasks.own_langs(st["id"])})  # with the languages of the resume brought in for it
        return out

    OWN_KINDS = {"resume": (".pdf", ".docx"), "cover": (".pdf", ".docx"), "deck": (".pdf",)}  # what an own file may stand for, and its types

    def own_file(self, jid: str, lang: str, kind: str, name: str, data: bytes) -> dict:
        """A document the person made for this edition, kept as it is: a resume or a cover letter (PDF or Word) or a portfolio
        (PDF) in one language. When the edition is made it stands for what Offerowl would typeset (tasks._build); a Word
        file is turned into a PDF there. A second one of the same kind and language replaces the first."""
        jid = self.need_job({"job": jid})  # which job or named edition
        ext = Path(name).suffix.lower()  # its type, by its name
        if lang not in ("ko", "en") or kind not in self.OWN_KINDS:  # an edition is Korean or English; three kinds of document
            raise ValueError("bad_request")
        if ext not in self.OWN_KINDS[kind] or not self.ws.sniff_ok(ext, data):  # a type this kind does not take, or bytes that are not it
            raise ValueError("own_file_type")
        d = self.ws.job_dir(jid) / "own" / "files"  # beside the job's own edition
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob(f"{kind}_{lang}.*"):  # the one before, whatever its type
            old.unlink()
        dest = d / f"{kind}_{lang}{ext}"  # one per kind and language
        dest.write_bytes(data)  # kept as it came
        return {"kind": kind, "lang": lang, "file": dest.name, "sha256": hashlib.sha256(data).hexdigest()}

    def sent_file(self, jid: str, lang: str, kind: str, name: str, data: bytes) -> dict:
        """A file that went out with this application (the resume, the portfolio, the cover letter as sent), kept as its
        submitted copy: the lock's frozen folder for that language holds it byte for byte, and the job counts as submitted.
        Each file comes on its own; the ones of one language gather in one folder."""
        jid = self.need_job({"job": jid})  # which job
        ext = Path(name).suffix.lower()  # its type, by its name
        if lang not in ("ko", "en") or kind not in self.OWN_KINDS or ext not in (".pdf", ".docx", ".pptx") or not self.ws.sniff_ok(ext, data):
            raise ValueError("own_file_type")  # three kinds; a PDF, a Word file or slides
        with self.ws.lock:  # one writer
            st = self.ws.job(jid)  # its record
            rec = st.get("locked") if isinstance(st.get("locked"), dict) and st["locked"].get("brought") and st["locked"].get("lang") == lang else None
            folder = rec["folder"] if rec else time.strftime("%Y%m%d-%H%M%S") + "-sent"  # the folder of this language's copies
            dest = self.ws.job_dir(jid) / "submitted" / folder  # beside the locks made here
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / (kind + ext)  # resume.pdf, deck.pdf, cover.pdf and the like
            target.write_bytes(data)  # as it was sent
            files = {**(rec or {}).get("files", {}), target.name: hashlib.sha256(data).hexdigest()}  # its hash with the others
            write_json(dest / "hashes.json", files)  # beside the copies, as freeze() writes it
            with self.ws.change({"code": "undo_lock"}, self.ws.job_files(jid)):  # undo unlocks; the copies stay
                st = self.ws.job(jid)  # read again inside the step
                st["locked"] = {"at": (rec or {}).get("at") or today(), "folder": folder, "files": files, "lang": lang, "brought": True, "name": name[:120]}
                if st.get("stage") == "preparing":  # sent: on the board it moves on (a later stage stays)
                    st["stage"] = "submitted"
                    st.setdefault("dates", {})["submitted"] = today()
                self.ws.save_job(st)  # the board moves with it
        return {"kind": kind, "lang": lang, "file": target.name, "folder": folder}

    def keep_all(self, material: str | None = None) -> int:
        """Keep every fact still to confirm, or only those of one material (the example's, kept for a first look while the
        person's own facts wait for their review). Returns how many."""
        st = self.facts.status()  # states
        todo = [c["cid"] for c in self.facts.candidates() if c["cid"] not in st  # still to confirm
                and (material is None or (c.get("source") or {}).get("material") == material)]  # of that material, when one is named
        with self.ws.change({"code": "undo_keep_all", "n": len(todo)}, FACT_FILES):  # one undo takes them all back
            for cid in todo:  # each fact nobody decided on yet
                st[cid] = "accepted"  # kept
            write_json(self.ws.path("sources", "review.json"), st)  # one write for all of them
            self.facts.rebuild()  # the profile follows
        return len(todo)  # how many, beside the new state

    def add_fact(self, req: dict) -> str:
        """A fact typed by the person."""
        if not str(req.get("statement") or req.get("title") or "").strip():  # a fact needs some words
            raise ValueError("empty")  # nothing to keep
        with self.ws.change({"code": "undo_typed", "title": str(req.get("title") or "")[:60]}, FACT_FILES):  # one undo step
            cid = self.facts.add_typed(req)  # listed and kept
            self.facts.rebuild()  # the profile follows
        return cid  # its id; the new state lists it

    def details(self, req: dict) -> None:
        """The person's own fields (autosaved while typing: one undo step per field and pause)."""
        fields = {k: v for k, v in (req.get("fields") or {}).items() if isinstance(v, str)}  # text only
        key = "details:" + ",".join(sorted(fields))  # one step while typing in the same field
        with self.ws.change({"code": "undo_details", "fields": sorted(fields)}, FACT_FILES, coalesce=key):  # pauses merge
            src = req.get("src") if isinstance(req.get("src"), dict) else None  # a run says which file each field came from
            self.facts.set_details(fields, src)  # saved, typed or found
            self.facts.rebuild()  # the profile follows

    def remove_material(self, mid: str) -> None:
        """Take a source and every fact read from it out of the profile. One undo brings it all back. Its file stays in
        sources/ until it is deleted for good from the Removed list (removed.py), and what it takes along waits in
        sources/removed/<id>.json (its facts, the imported profile it was, the example's details), so the list can put it
        back after later changes too."""
        rec = next((m for m in self.ws.materials() if m.get("id") == mid), None)  # listed and not taken off already
        if not rec:  # a stale page, or a made-up id
            raise ValueError("material")
        stash = {"candidates": []}  # what it takes along, for the Removed list's put-back
        # one undo brings it all back, the stash included: undone, the stash goes
        with self.ws.change({"code": "undo_remove_material", "title": str(rec.get("name") or "")[:60]}, FACT_FILES + [f"sources/removed/{mid}.json"]):
            self.ws.update_material(mid, removed=True, removed_at=today())  # hidden, with the day the list shows
            if rec.get("example"):  # its name, email and phone leave with it, unless the person changed them since
                from .facts import details_from  # the fields a profile file fills in
                det = self.facts.details()  # what "Your details" holds
                for doc in (EXAMPLE, EXAMPLE_EN):  # either language of the example
                    for k, v in details_from(json.loads(doc.read_text(encoding="utf-8"))).items():  # each field it fills
                        if v and det.get(k) == v:  # still the example's
                            stash.setdefault("details", {})[k] = det.pop(k)  # empty again; a put-back fills it once more
                            if isinstance(det.get("_src"), dict) and k in det["_src"]:
                                stash.setdefault("src", {})[k] = det["_src"].pop(k)  # and where it came from
                write_json(self.ws.path("profile", "details.json"), det)  # saved
            cands = self.facts.candidates()  # every fact listed now
            stash["candidates"] = [c for c in cands if (c.get("source") or {}).get("material") == mid]  # its own, as they were
            if any(c.get("origin") == "profile" for c in stash["candidates"]):  # an imported profile file
                base = self.ws.path("profile", "base.json")  # the profile its facts point into
                stash["base"] = read_json(base, None)  # kept for a put-back
                base.unlink(missing_ok=True)  # it goes with them
            write_json(self.ws.path("sources", "candidates.json"),  # the list without its facts
                       {"kept": [c for c in cands if (c.get("source") or {}).get("material") != mid],
                        "dropped": read_json(self.ws.path("sources", "candidates.json"), {}).get("dropped", [])})  # the record stays
            write_json(self.ws.path("sources", "removed", f"{mid}.json"), stash)  # what a put-back takes from
            self.facts.rebuild()  # the profile follows

    # ------------------------------------------------------------------ jobs

    def set_posting(self, jid: str, posting: str) -> None:
        """A job's posting replaced by the text the person pasted (a posting whose duties the reading missed): one undo step."""
        posting = str(posting or "").strip()[:200000]  # the text, bounded as a posting
        if len(posting) < 20:  # too short to be a posting
            raise ValueError("posting")  # nothing to analyze
        job = self.ws.job(jid) or {}  # its card, for the undo key's words
        with self.ws.change({"code": "undo_posting", "company": job.get("company") or job.get("role") or jid}, [f"jobs/{jid}/posting.md"]):
            write_text(self.ws.job_dir(jid) / "posting.md", posting + "\n")  # as pasted

    def add_job(self, req: dict, select: bool = True) -> str:
        """A job from a pasted posting or a link: its folder, the posting, its card on the board. Returns its id. With
        select False (a run adds it) the job in view stays as it is."""
        posting = str(req.get("posting") or "").strip()  # the posting
        url = str(req.get("url") or "").strip()  # or the link it lives at
        if not posting and url:  # a link alone: fetch the page's text once
            from . import postings  # the fetch
            got = postings.fetch(url, allow_local=os.environ.get("OFFEROWL_ALLOW_LOCAL_LINKS") == "1")  # raises ValueError with a code
            posting = got["text"]  # the posting's text
        company, role = str(req.get("company") or "").strip()[:80], str(req.get("role") or "").strip()[:80]  # both optional, bounded
        if len(posting) < 20:  # too short to be a posting
            raise ValueError("posting")  # nothing to analyze
        if not company and not role:  # nothing typed: the posting's own words name it
            from . import fit as F  # the posting parser
            f = F.compute({"schema": "resume-profile/0.1", "roles": [{"org": "-", "projects": [{"id": "x", "title": "-", "summary": "-"}]}]}, posting)  # parse only
            company = (f.get("company") or "")[:80]  # the company the posting names
            role = f.get("role") or posting.splitlines()[0]  # its title, else its first line
            role = re.sub(r"\s*[(\[].*?[)\]]\s*", " ", role.lstrip("# ")).strip()  # a note in brackets ("(가상의 예제)")
            role = re.sub(r"\s*(?:채용\s*공고|채용|모집|공고|job posting|hiring)\s*$", "", role, flags=re.I).strip()  # the posting's own word for itself
            if company and role.startswith(company):  # the company named twice
                role = role[len(company):].strip(" -·|,")
            role = role[:80]  # bounded
        jid = self.ws.new_job_id(company, role or posting.splitlines()[0])  # its folder name
        n = len(self.ws.jobs(removed=True)) + 1  # a counter for the order of jobs made the same day
        # undo takes the job away, the questions a posting brought along with it
        with self.ws.change({"code": "undo_add_job", "company": company or role}, self.ws.job_files(jid) + [f"jobs/{jid}/questions.json"]):
            write_text(self.ws.job_dir(jid) / "posting.md", posting + "\n")  # the posting as pasted
            from . import answers as A  # a posting that lists the form's questions brings them along
            asked = A.parse_questions(posting, strict=True)  # only questions with a limit, or under a questions heading
            if asked:  # nobody types them again
                write_json(self.ws.job_dir(jid) / "questions.json", {"questions": A.clean_questions(asked, [])})
            self.ws.save_job({"id": jid, "company": company, "role": role, "created": today(), "seq": n,  # its card, first column
                              "stage": "preparing", "dates": {"preparing": today()}, "next": "", "result": "",
                              **({"url": url[:2000]} if url else {})})  # where it was read from
        if select:  # the person added it: in view
            self.ws.set_prefs(job=jid)
        return jid  # the route starts its analysis

    def agent_calls(self) -> dict:
        """The agent card's figures (apps/api/agent.py calls_summary), read at most every few seconds."""
        from .agent import calls_summary  # the call log's summary
        now = time.time()  # the clock
        if now - getattr(self, "_calls_at", 0) > 4:  # the page polls each second while a run goes
            self._calls, self._calls_at = calls_summary(backend=(self.card.card() or {}).get("backend") or None), now  # read again: the card's agent only
        return self._calls  # the figures

    def autopilot(self, req: dict) -> dict:
        """Start one run from the person's files to finished documents (apps/api/autopilot.py, task "autopilot")."""
        from . import autopilot as AP  # the run
        mids = [str(x) for x in req.get("ids") or [] if any(m["id"] == str(x) for m in self.ws.materials())]  # files the page uploaded
        paths = [str(x) for x in req.get("paths") or [] if str(x).strip()][:50]  # paths the person pasted
        posting, url = str(req.get("posting") or "")[:20000], str(req.get("url") or "")[:2000]  # the posting, if any
        with_job = bool(posting.strip() or url.strip())  # a posting turns on the job's steps
        again = self.need_job({"job": req["again"]}) if req.get("again") else ""  # one edition's PDFs once more
        job = self.need_job({"job": req["job"]}) if req.get("job") else ""  # a job already added: its documents from the facts kept
        if job and not self.facts.profile().get("roles"):  # nothing to tailor yet
            raise ValueError("no_files")
        theme = req.get("theme") if req.get("theme") in THEMES else "navy"  # the colour the person picked on the canvas
        pages = max(1, min(7, int(req.get("max_pages") or 3))) if str(req.get("max_pages") or "3").isdigit() else 3  # the page limit, 1 to 7 as /jobs/build takes it (routes.pages_of) and the panel offers
        if not again and not job and not mids and not paths and not (with_job and self.facts.profile().get("roles")):  # nothing to read, and no career kept to tailor
            raise ValueError("no_files")
        files, skipped = AP.collect(paths)  # what the paths hold (walked once: the run reads this list)
        paths = [str(f) for f in files] or paths  # the files themselves, so the run does not walk the folders again (none found: the run says why)
        est = AP.estimate(len(mids) + len(files), with_job)  # calls and minutes
        said = {"task": "autopilot", "files": len(mids) + len(files), "skipped": skipped[:20], "estimate": est}  # the answer's facts
        req_now = (mids, paths, posting, url, again, theme, pages, job)  # this request
        for _ in range(3):  # a run that ends between the look and the start: look again
            with self.tasks.state_lock:  # read together with the chain's ending (autopilot.chain)
                if (self.tasks.tasks.get("autopilot") or {}).get("state") == "running":  # a run in progress: this one follows it
                    self.tasks.autopilot_next = merge_requests(self.tasks.autopilot_next, req_now)  # with anything already waiting
                    return {"started": False, "queued": True, **said}
            self.tasks.autopilot_stop.clear()  # a new run
            if self.tasks.start("autopilot", AP.chain, self, *req_now):  # in the background
                return {"started": True, "queued": False, **said}
        return {"started": False, "queued": False, **said}  # never seen: the page says it did not start

    def job_in(self, req: dict) -> str | None:
        """The job a request names, or None when it names none (the general edition)."""
        return self.need_job(req) if req.get("job") else None  # checked like any job

    def need_job(self, req: dict) -> str:
        """The job a request names, checked. A job or an edition in the Trash is refused like one that is not there: nothing
        is made, changed or started for it until it is put back (removed.py), so no task writes into a folder on its way out."""
        jid = str(req.get("job") or "")  # which job
        if jid == GENERAL:  # the edition with no job: a folder with no card on the board
            return jid
        st = self.ws.job(jid) if jid else None  # its card (a made-up id is refused by job_dir)
        if not st or st.get("removed"):  # no such job, or one in the Trash
            raise ValueError("job")  # answered as bad_request
        return jid  # it exists

    def board(self, req: dict) -> None:
        """Move a job on the board or change its date, next step or result. Taking it off ({"removed": true}) records the
        day, for the Removed list; undo or that list puts it back."""
        with self.ws.lock:  # looked up and changed in one step: a job deleted for good meanwhile is refused, never half written
            jid = self.need_job(req)  # which job
            st = self.ws.job(jid)  # its status
            off = req.get("removed") is True and not st.get("removed")  # taken off now (only an explicit true removes)
            # one undo step per change of the card; a removal says so on the undo key, an edition in its own words
            code = ("undo_remove_edition" if st.get("kind") == "edition" else "undo_remove_job") if off else "undo_board"
            with self.ws.change({"code": code, "company": st.get("company") or st.get("role") or st.get("name")}, self.ws.job_files(jid),
                                coalesce=f"board:{jid}:{','.join(sorted(k for k in req if k != 'job'))}"):  # typing in the same fields merges
                st = self.ws.job(jid)  # read again inside the step
                if req.get("stage") in STAGES and req["stage"] != st.get("stage"):  # a move
                    st["stage"] = req["stage"]  # the new column
                    st.setdefault("dates", {})[req["stage"]] = today()  # the day it moved
                if isinstance(req.get("date"), str) and (not req["date"] or is_day(req["date"])):  # a real day (YYYY-MM-DD), or empty to clear
                    st.setdefault("dates", {})[st["stage"]] = req["date"]  # the date of the stage it is in
                for stage, day in (req.get("dates") or {}).items() if isinstance(req.get("dates"), dict) else ():  # any stage's day, as the progress tab edits them
                    if stage in STAGES and isinstance(day, str) and (not day or is_day(day)):  # a real day, or empty to clear
                        st.setdefault("dates", {})[stage] = day
                for k in ("next", "result", "company", "role"):  # the card's free text fields
                    if isinstance(req.get(k), str):  # only the fields that were sent
                        st[k] = req[k].strip()[:1000 if k in ("next", "result") else 200]  # trimmed and bounded: a next step may hold a meeting's long link whole
                if off:  # off the board: undo, or the Removed list, brings it back
                    st["removed"], st["removed_at"] = True, today()  # with the day the list shows
                self.ws.save_job(st)  # one write for every change

    def next_stage(self, jid: str) -> None:
        """Move a job one column to the right."""
        with self.ws.lock:  # looked up and moved in one step (board takes the same lock again)
            st = self.ws.job(jid)  # its status
            if not st:  # no such job
                raise ValueError("job")  # answered as bad_request
            i = STAGES.index(st.get("stage", "preparing")) if st.get("stage") in STAGES else 0  # an unknown stage counts as the first
            self.board({"job": jid, "stage": STAGES[min(i + 1, len(STAGES) - 1)]})  # through board(): undo and the date

    def round(self, req: dict) -> dict | None:
        """Add, change or remove an interview round on a job (tracker.set_round). One undo step."""
        from . import tracker  # the rounds' rules
        with self.ws.lock:  # looked up and changed in one step: a job deleted for good meanwhile is refused
            jid = self.need_job(req)  # which job
            st = self.ws.job(jid)  # its status
            with self.ws.change({"code": "undo_round", "company": st.get("company") or st.get("role")}, self.ws.job_files(jid)):  # one undo step
                rec = tracker.set_round(st, req)  # checked
                self.ws.save_job(st)  # saved
        return rec  # the round as kept

    def reminder(self, req: dict) -> dict | None:
        """Add a reminder to a job, or mark one done or remove it. One undo step."""
        from . import tracker  # the reminder rules
        with self.ws.lock:  # looked up and changed in one step: a job deleted for good meanwhile is refused
            jid = self.need_job(req)  # which job
            st = self.ws.job(jid)  # its status
            with self.ws.change({"code": "undo_reminder", "company": st.get("company") or st.get("role")}, self.ws.job_files(jid)):  # one undo step
                if req.get("id"):  # an existing reminder
                    tracker.set_reminder(st, str(req["id"]), done=req.get("done") if isinstance(req.get("done"), bool) else None,
                                         remove=req.get("remove") is True)  # done, not done, or removed
                    rec = None  # nothing new
                else:  # a new one
                    rec = tracker.add_reminder(st, str(req.get("at") or ""), str(req.get("text") or ""))  # checked
                self.ws.save_job(st)  # saved
        return rec  # the new reminder, for the answer

    # ------------------------------------------------------------------ the first run

    def set_onboarding(self, req: dict) -> None:
        """Remember where the first run stands (not undoable: it is where you are, not what you made)."""
        values = {}  # the changed keys
        if req.get("step") in ("welcome", "language", "agent", "files", "preview"):  # only the steps the page has
            values["onboarding_step"] = req["step"]  # resumed there after a reload
            if req["step"] == "welcome" or not self.ws.prefs().get("onboarding_started"):  # the clock of the first run
                values.setdefault("onboarding_started", time.time())  # when it began
        if isinstance(req.get("done"), bool):  # finished, or the tour asked for again
            values["onboarded"] = req["done"]  # the workspace opens from now on, or the tour shows again
        if values:  # something to keep
            self.ws.set_prefs(**values)  # kept with the workspace

_VERSION = None  # read once: it changes only with a new copy of Offerowl


def app_version() -> str:
    """Offerowl's version for the bar beside the wordmark, from the one place it is written (as the MCP server reads it)."""
    global _VERSION
    if _VERSION is None:
        from apps.mcp.server import version  # deploy/python/offerowl/__init__.py
        _VERSION = version()
    return _VERSION
