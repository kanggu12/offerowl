"""Offerowl's composition root: the API object of one running panel. It builds the core (the workspace) and what the
services keep for the panel's life (the profile's facts, the agent's card, the applications' fits, the task runner made
of every service's task part), keeps the pieces they all share (the settings, the job a request names, the state the
panel polls, composed of every service's part of it) and hands itself to the services, which take it as `api`. It does
no work of its own: every action is a service's (apps/api/services), and the gateway (routes.py) maps the paths to them;
nothing here knows about HTTP.

Every change goes through Workspace.change(), so one undo takes it back and the history lists it.
"""
from __future__ import annotations

import contextlib  # a job read that a deletion may overtake
import logging  # the panel's log
import os  # environment
import sys  # paths
import threading  # the agent card's first look
from pathlib import Path  # paths

from .core.workspace import STAGES, Workspace, read_json, today, write_json  # files, undo, the board's columns, the day
from .services import applications, documents, library, profile  # the services the state is made of
from .services.agent import BACKENDS, AgentCard, finished_runs  # the agent card, and the finished runs the page lists
from .services.documents import DECK_STYLES, FORMS, THEMES  # the choices a document offers
from .services.profile import Facts, problems  # facts and the profile
from .tasks import Tasks  # long tasks

log = logging.getLogger("offerowl.api")  # the panel's log
ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
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


class Api:
    """Everything one running Offerowl holds: the settings, the workspace, the facts, the agent card, the fits, the tasks,
    and the state the panel polls. The services take it as `api` and do the work."""

    def __init__(self, data: Path, workspace: Path | None = None):  # workspace: --workspace, else the saved setting
        self.data = Path(data)  # settings and logs
        self.data.mkdir(parents=True, exist_ok=True)  # the first start has no folder yet
        self.settings_file = self.data / "settings.json"  # the app's settings
        self.start = {k: v for k, v in START.items() if v and (k != "backend" or v in BACKENDS)}  # a change in the menu takes a value out
        ws_dir = workspace or Path(self.settings().get("workspace") or self.data / "workspace")  # the path setting
        self.ws = Workspace(ws_dir)  # the person's files
        try:  # a workspace from before 0.15.0 names jobs in Hangul, so its addresses did too: renamed once, the old names kept as aliases
            moved = self.ws.ascii_job_ids()
            if moved:
                log.info("job ids made ASCII: %s", moved)
        except (OSError, ValueError):  # a folder another program holds open (Windows): tried again at the next start
            log.exception("job ids not made ASCII yet")
        self.facts = Facts(self.ws)  # facts and the profile
        self.card = AgentCard(self.settings)  # the agent card
        self.tasks = Tasks(self.ws, self.facts, self.card)  # long tasks
        self.fits = applications.Fits(self.ws, self.facts)  # the applications' fits, cached per posting and profile
        self._state_gen = 0  # bumped by every write: a state made before it is never answered after it
        self._state_cv = threading.Condition()  # one poll's state made at a time: polls that come meanwhile take its answer
        self._state_making = False  # a poll's state is being made now
        self._state_last = None  # (writes seen when it began, state): the last one made for a poll
        self._settings_lock = threading.Lock()  # two changes of the settings at once (two quick switches) never lose one
        self.restoring = threading.Lock()  # one restore at a time (the Library's backup, and the Trash's folders kept aside)
        threading.Thread(target=self.card.refresh, kwargs={"force": True}, daemon=True, name="agent").start()  # first look
        threading.Thread(target=self.tasks.letter_pages_all, daemon=True, name="letters").start()  # the pages of letters brought in before the build drew them

    def settings(self) -> dict:
        """The app's settings: language, theme, backend and the local server's address."""
        s = read_json(self.settings_file, {})  # saved choices
        return {"lang": "auto", "theme": "auto", "backend": os.environ.get("OFFEROWL_PANEL_BACKEND", "auto"),  # tests preset the backend
                "llm_url": "", "llm_model": "", **s, **self.start}  # defaults under the saved choices, what was named at the start over both

    def _set_settings_locked(self, req: dict) -> bool:
        """set_settings' reading, checking and writing of settings.json, under its lock. True when the portfolio kept on the
        Desktop was just turned on, or its size changed while it is on."""
        s = read_json(self.settings_file, {})  # saved choices
        # each setting's type (D3-13): a value of the wrong type is refused with the setting's name; a string the page no longer
        # offers (a stale page's form) is left as before, ignored, so the rest of that request still applies
        text = ("lang", "theme", "backend", "agent", "form", "deck_style", "style", "llm_url", "llm_model")  # strings
        flags = ("export_extras", "export_pptx", "desk_portfolio", "photo")  # booleans
        for k in text:
            if k in req and not isinstance(req[k], str):
                raise ValueError(k)  # 400 bad_request, what names the setting
        for k in flags:
            if k in req and not isinstance(req[k], bool):
                raise ValueError(k)
        if "corners" in req and req["corners"] is not None and not isinstance(req["corners"], str):  # a string, or null to clear
            raise ValueError("corners")
        if "deck_max_mb" in req and req["deck_max_mb"] is not None and (isinstance(req["deck_max_mb"], bool) or not isinstance(req["deck_max_mb"], (int, float))):  # a number, or null to clear
            raise ValueError("deck_max_mb")
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
        size = s.get("deck_max_mb")  # the size that portfolio was held to (apps/api/services/documents/delivery.py), to see a change
        if "deck_max_mb" in req and req["deck_max_mb"] is None:  # cleared: the deck goes as it was made
            s.pop("deck_max_mb", None)
        elif isinstance(req.get("deck_max_mb"), (int, float)) and not isinstance(req["deck_max_mb"], bool) and 0 < req["deck_max_mb"] <= 1000:  # a size in MB a file can be held to
            s["deck_max_mb"] = req["deck_max_mb"]
        turned_on = turned_on or (s.get("desk_portfolio") is True and s.get("deck_max_mb") != size)  # a new size: the copy kept is made again now
        if "corners" in req and req["corners"] is None:  # cleared: rounded corners, as the documents always had them
            s.pop("corners", None)
        elif req.get("corners") in ("round", "square"):  # the corners of the figures, the logo tiles and the built-in deck (Tasks.corners)
            s["corners"] = req["corners"]
        if isinstance(req.get("photo"), bool):  # the photo on the resume, or not
            s["photo"] = req["photo"]  # kept for the next build
        if isinstance(req.get("style"), str) and (req["style"] == "default" or req["style"] in profile.style_names(self)):  # the writing rules: the shipped pack, or one of the workspace's own
            s["style"] = req["style"]  # every draft and check uses it from now on (Tasks.style_spec)
        for k in ("llm_url", "llm_model"):  # the local model server's address and model
            if isinstance(req.get(k), str):  # a missing or odd value leaves it as it was
                s[k] = req[k].strip()[:300]  # trimmed and bounded
                self.start.pop(k, None)  # the menu wins from here on
                self.card.look_again()  # whether the new address answers is said now, not at the next minute's look
        write_json(self.settings_file, s)  # saved
        return turned_on

    def set_settings(self, req: dict) -> dict:
        """Change the settings that were sent (each one checked)."""
        with self._settings_lock:  # read, changed and written as one: a second change waits for the first
            turned_on = self._set_settings_locked(req)
        if turned_on:  # an edition that passed already goes there now, not at the next build
            for lang in ("ko", "en"):  # each language made
                try:
                    documents.keep_portfolio(self.tasks, lang)  # nothing when that edition was never made or did not pass
                except OSError as exc:  # a Desktop that cannot be written: the next build tries again
                    log.warning("portfolio not kept on the Desktop: %s", exc)  # for the log only
        return self.settings()  # with the defaults filled in again

    def job_in(self, req: dict) -> str | None:
        """The job a request names, or None when it names none (the general edition)."""
        return self.need_job(req) if req.get("job") else None  # checked like any job

    def need_job(self, req: dict) -> str:
        """The job a request names, checked. A job or an edition in the Trash is refused like one that is not there: nothing
        is made, changed or started for it until it is put back (the Library's Trash), so no task writes into a folder on its way out."""
        jid = str(req.get("job") or "")  # which job
        if jid == GENERAL:  # the edition with no job: a folder with no card on the board
            return jid
        jid = self.ws.resolve_job(jid)  # an id from before a rename (an old address) finds the job
        st = self.ws.job(jid) if jid else None  # its card (a made-up id is refused by job_dir)
        if not st or st.get("removed"):  # no such job, or one in the Trash
            raise ValueError("job")  # answered as bad_request
        return jid  # it exists

    @contextlib.contextmanager
    def gone_meanwhile(self, jid: str):
        """Read one job, and leave it out when it was deleted for good while it was read (removed.py takes its folder away
        under the workspace's lock, which a read of the state does not take). Any other error is a bug and says so."""
        try:
            yield
        except (ValueError, OSError):  # its id refused by job_dir, or a file of it gone between a look and a read
            if jid not in self.ws.gone:  # not a deletion: as it was
                raise

    def state(self) -> dict:
        """Everything the page draws, in one answer. The tasks are read first: a task writes its files before it says it has
        ended, so what is read after them is at least as new, and one answer never says a task is done beside what was there
        before it ran (read last, an analysis that ended while the rest was read came back "done" with the words' old plan).
        The facts come as their counts and a stamp: the rows are most of the bytes and only the profile view draws them, from
        /api/v1/facts when the stamp changes."""
        with self.tasks.one_read():  # the deck source's stamp worked out once for every edition, not once per edition
            return self._state()

    def state_for_poll(self) -> dict:
        """The state for a page's poll (GET /api/v1/state). Polls that come while one is being made wait for it and take its
        answer, unless something was written since it began: five tabs polling at once made five states, and with many
        applications two tabs took several times one tab's time. Never older than the poll by more than one state's making."""
        with self._state_cv:
            while self._state_making:  # one is being made: wait for it
                self._state_cv.wait(timeout=30)
                last = self._state_last
                if last is not None and last[0] == self._state_gen:  # made from what is there now
                    return last[1]
            self._state_making, gen = True, self._state_gen
        st = None
        try:
            st = self.state()
            return st
        finally:  # the next poll goes on, with this one's answer or making its own
            with self._state_cv:
                self._state_making = False
                self._state_last = (gen, st) if st is not None else None
                self._state_cv.notify_all()

    def state_dirty(self) -> None:
        """A write happened: the next state is made anew (never one from before it)."""
        self._state_gen += 1

    def _state(self) -> dict:
        """state, inside one read."""
        tasks = self.tasks.state()  # first, as the docstring says
        prof = self.facts.profile()  # the profile
        prefs = self.ws.prefs()  # the job in view, the guide
        jobs = applications.jobs_view(self)  # the jobs
        pick = prefs.get("job")  # the job chosen to be in view, or the general edition
        editions = documents.editions_view(self)  # the named general editions
        current = applications.job_in_view(pick, jobs, editions)  # that job, the general edition when it was chosen, or the newest job when the chosen one is gone
        undo_id, undo_label = self.ws.newest()  # what the undo key takes back, and its name: a toast's Undo sends the name, so it never takes back a later change
        return {  # one answer redraws the whole page
            "app": "offerowl", "api": API_VERSION, "version": app_version(), "settings": self.settings(), "styles": profile.style_names(self), "blind": profile.blind_view(self), "desk": documents.desk_view(self), "photo": profile.photo_state(self), "agent": self.card.card(), "agent_calls": self.card.calls(), "materials": profile.materials_now(self),
            "facts": profile.facts_summary(self), "details": self.facts.details(), "draft": profile.draft_view(prof), "problems": problems(prof),
            "jobs": jobs, "job": current, "general": documents.general_view(self), "editions": editions, "tasks": tasks, "runs": finished_runs(self.ws), "onboarding": profile.onboarding(self),
            "english": bool(self.tasks.english_for(current)), "profile_lang": self.tasks.profile_lang(), "engine": self.tasks.engine_ready(),
            "engine_needs": list(self.tasks.engine_needs),  # what the browser renderer lacks, when "engine" says so
            "renderer": self.tasks.renderer_in_use(),  # "html" (this PC's browser) or "container", for the guide's words
            "features": {"cover": self.tasks.cover_available(), "interview": self.tasks.interview_available()},
            "undo": undo_label, "undo_id": undo_id, "history": self.ws.history_count(),  # the steps counted by their files' names, not read
            "removed": library.removed_counts(self),  # what the Trash holds, by kind: put back or deleted for good there
            "themes": list(THEMES), "stages": list(STAGES),
            "today": today(), "due": applications.due(jobs), "open": prefs.get("open")}  # the step an entry point asked to open first (src/ui opens the facts)

_VERSION = None  # read once: it changes only with a new copy of Offerowl


def app_version() -> str:
    """Offerowl's version for the bar beside the wordmark, from the one place it is written (as the MCP server reads it)."""
    global _VERSION
    if _VERSION is None:
        from apps.mcp.server import version  # src/version.py
        _VERSION = version()
    return _VERSION
