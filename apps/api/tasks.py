"""The API's long tasks, each in a thread of its own: reading material (src/ingest.py), the posting analysis
(src/draft.py task_jd, or the fit by words without an agent), the English profile (src/draft.py task_translate), making
the typeset documents (src/resume.py's build, build_deck and the document checks), the cover letter (src/cover.py, called
in this process), the interview kit (src/interview, in this process), tailoring all three for a job at once, and
regenerating one sentence from its evidence.

A task's state is kept in memory for the panel to show: running with its current step, done with its result, or an
error with a code the panel words in either language and one fix. Long engine output goes to the panel's log, never
to the screen (no file paths or commands on screen).
"""
from __future__ import annotations

import base64  # the live deck's pictures
import contextlib  # one read of the state, its stamps worked out once (Tasks.one_read)
import hashlib  # build names and profile hashes
import html as htmlmod  # a picture's path, escaped in its attribute
import json  # files
import logging  # the panel's log
import mimetypes  # a picture's type, by its name
import os  # environment for the engine
import re  # parsing engine output
import shutil  # copies and tool lookup
import subprocess  # previews and the interview kit
import sys  # the engine on the import path
import threading  # one thread per task
import time  # task times
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules

from .facts import FACT_FILES, Facts, problems  # noqa: E402  facts and the profile
from .workspace import Workspace, read_json, retried, today, write_json  # noqa: E402  files
from .stamps import HASH_CACHE_MAX, RACY_NS, _cached, _content_hash, _file_hash, _hash_cache, _hash_lock, content_hash, file_hash, file_stamp  # noqa: E402,F401  the stamps and hashes (apps/api/stamps.py), named here as before
from .delivery import WSL_DESKTOP, desktop_dir, in_wsl, open_in_files, windows_desktop  # noqa: E402,F401  the Desktop and the file manager (apps/api/delivery.py)
from .task_own import OwnEdition, OWN_FORM_KEYS  # noqa: E402,F401  Tasks' part in apps/api/task_own.py
from .task_kit import Kits, KIT_KEEP, KIT_GRACE, SCRIPTS_AT_ONCE, SCRIPT_WORKERS  # noqa: E402,F401  Tasks' part in apps/api/task_kit.py
from .task_export import Exports  # noqa: E402,F401  Tasks' part in apps/api/task_export.py
from .task_answers import AnswerTasks  # noqa: E402,F401  Tasks' part in apps/api/task_answers.py

log = logging.getLogger("offerowl.panel")  # the panel's log
THEMES = ("navy", "teal", "mono", "wine", "forest", "slate")  # src/themes.json's packs
FORMS = ("detailed", "compact", "table")  # the resume's forms (src/resume_form.js)
DECK_STYLES = ("classic", "clean")  # the deck's looks (src/portfolio/style_clean.css)
LANGS = ("ko", "en")  # the editions
FIGURE_CALLS = 6  # model calls one round of figures may take; projects share a call when there are many
MEASURED_CALLS = 0  # calls of figure_draft's measured step: off until its charts are judged worth their place on a real profile


def in_image() -> bool:
    """Inside one of Offerowl's own images (the render container, the app image), where the tools are called directly. The
    engine's own rule (src/resume.py: in_container), so the panel's state and the builds never disagree about where they run:
    a container without LibreOffice (a dev container, a CI job's) is taken for a PC."""
    import resume  # src/resume.py, on the path set above
    return resume.in_container()


def letter_sentences(path: Path) -> int:
    """How many sentences with words a drafted cover letter holds (0 for a missing file or an empty skeleton)."""
    doc = read_json(path, None)  # the draft
    paras = doc.get("paragraphs") if isinstance(doc, dict) else None  # its paragraphs
    return sum(1 for p in paras or [] if isinstance(p, dict) for s in p.get("sentences") or [] if isinstance(s, dict) and str(s.get("text") or "").strip())  # with words


def clean_reason(text: str) -> str:
    """The engine's own reason, without paths or commands, for a detail line under an error ("" when nothing is left)."""
    errs = [line.split("Error:", 1)[1].strip() for line in text.splitlines() if "Error:" in line]  # node's thrown message
    line = (errs[0] if errs else "").strip()  # the first one
    line = re.sub(r"(/[\w.\-가-힣]+)+/?|[A-Za-z]:\\[^\s]+|\boutput/\S+|\bsrc/\S+", "", line)  # paths out
    return re.sub(r"\s{2,}", " ", line).strip()[:200]  # one short line


LIVE_PICTURES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")  # what a slide shows
LIVE_PICTURE_MAX = 20_000_000  # bytes of one: a page is sent whole


def is_svg_image(html: str, at: int) -> bool:
    """Is the attribute at this place of the page inside an SVG <image> tag (not an <a> or a <link>)?"""
    start = html.rfind("<", 0, at)  # the tag the attribute belongs to
    return bool(re.match(r"<image\b", html[start:start + 7]))  # an SVG picture


def live_html(html: str, allowed: tuple = ()) -> str:
    """The deck's print page as a page for the canvas's frame: pictures in the page (a frame cannot read file:// paths, and no
    path of this PC reaches the page), the fonts from the panel, no measuring script, and links that a click cannot follow.
    Only a picture the page itself asks for counts, from the engine's folders or `allowed`: words on a slide that look like a path stay words."""
    roots = [ROOT.resolve(), *[Path(a).resolve() for a in allowed]]  # where a slide's pictures come from
    def picture(m):  # one picture of the page
        attr, p = m.group(1), htmlmod.unescape(m.group(2))  # src of an <img>, or href / xlink:href of an SVG <image>; the path as the writer wrote it, escaped for an attribute
        for prefix, there in (("/work/", ROOT), ("/offerowl-assets/", Path(os.environ.get("OFFEROWL_ASSETS") or ROOT / "assets"))):  # the container's mounts
            if p.startswith(prefix):  # written in the container
                p = str(there / p[len(prefix):])  # the same file here
        f = Path(p)  # the file
        try:
            real = f.resolve()  # through any link
            good = real.suffix.lower() in LIVE_PICTURES and any(real.is_relative_to(r) for r in roots) and real.is_file() and real.stat().st_size <= LIVE_PICTURE_MAX  # a picture, from where pictures are, of a size a page can hold
        except OSError:  # a path this system cannot read
            good = False  # not one
        if not good:  # a picture that is gone, or anything else
            return f'{attr}=""'  # draws nothing
        kind = mimetypes.guess_type(real.name)[0] or "image/png"  # by its extension
        return f'{attr}="data:{kind};base64,{base64.b64encode(real.read_bytes()).decode()}"'  # in the page
    # every picture, whole, spaces and all: an <img src>, and an SVG <image href> (the timeline's logo tiles), which a frame
    # cannot read from file:// either. A link's href stays as written: a click in the frame follows nothing
    out = re.sub(r'(?<![\w-])(src|href|xlink:href)="file://([^"]*)"', lambda m: picture(m) if m.group(1) == "src" or is_svg_image(html, m.start()) else m.group(0), html)
    out = re.sub(r"""url\(["']?\.\./fonts/(Pretendard-[A-Za-z]+\.ttf)["']?\)""", r'url("/fonts/\1")', out)  # the panel serves the same fonts
    out = re.sub(r"<script\b[^>]*>.*?</script>", "", out, flags=re.S)  # the frame runs nothing
    out = out.replace('<pre id="probe-out"></pre>', "")  # nor needs the measurements' place
    frame = ("<style>@media screen { html, body { margin: 0; padding: 0; background: transparent; overflow: hidden; text-rendering: geometricPrecision; } "  # the canvas is behind the frame, the pane scrolls, and scaled glyphs keep the spacing they print with
             ".slide { margin: 0 0 24px 0; box-shadow: none; } a { pointer-events: none; color: inherit; } }</style>")  # a link in a frame would leave the deck
    return out.replace("</head>", frame + "</head>", 1)  # after the deck's own styles


def ledger_parts(prof: dict) -> int:
    """The most "##" parts any of the profile's lists has: how far an edition can be trimmed, one part at a time."""
    return max([len(re.findall(r"(?m)^##\s", str(s.get("body_md") or ""))) for s in prof.get("sections") or []] or [0])


def ledger_for_resume(prof: dict, style: dict, compact: int = 0, drop: int = 0) -> dict:
    """The profile's own lists (papers, patents, awards, certificates, talks: sections with a markdown body) as a resume
    prints them, by the person's rules: a table row or a list line a banned pattern names stays out (a certificate the
    person never held, a name never used), a banned character becomes a colon, and a list of links alone (press) stays
    out of a resume. A section the person marked keeps its mark; nothing else changes. compact N (an edition over its page
    limit) keeps each list's first N parts, by its "##" headings: the person lists the strongest first. drop N leaves out the
    last N lists that would print, when even their first parts run over: the person lists them in order of weight too."""
    pats = []  # the rules' patterns that compile
    for row in style.get("banned_patterns") or []:
        try:
            pats.append(re.compile(row[0]))
        except (re.error, TypeError, IndexError):  # a pack the panel refused would never get here; a shipped one is checked
            continue
    banned = str(style.get("banned_chars") or "")  # characters the person never prints
    out = []  # the sections as printed
    for s0 in prof.get("sections") or []:
        s = dict(s0)  # a copy: the profile stays as kept
        body = s.get("body_md")
        if isinstance(body, str) and body.strip():  # a ledger body
            body = re.sub(r"<!--[\s\S]*?-->", "", body)  # the person's notes to themselves never print, so they go first
            lines = [ln for ln in body.splitlines() if not any(p.search(ln) for p in pats)]  # a row or a line the rules name goes
            text = "\n".join(lines)
            for c in banned:  # a banned dash in a heading or a cell
                text = text.replace(f" {c} ", ": ").replace(c, ":")
            if compact:  # an edition over its page limit: the first parts of each list
                heads = [m.start() for m in re.finditer(r"(?m)^##\s", text)]  # where each part starts
                if len(heads) > compact:  # more parts than kept: the later ones go
                    text = text[:heads[compact]].rstrip()
            s["body_md"] = text
            visible = [ln.strip() for ln in text.splitlines() if ln.strip()]  # what would print
            if visible and "resume" not in s0 and all(ln.startswith(("-", "*")) and re.search(r"https?://", ln) for ln in visible):  # links alone
                s["resume"] = False  # a press list belongs on a profile page, not on a resume
        out.append(s)
    if drop:  # the last lists that would print go, from the end
        printed = [i for i, s in enumerate(out) if s.get("body_md") and s.get("resume") is not False]
        for i in printed[-drop:]:
            out[i] = {**out[i], "resume": False}
    return {**prof, "sections": out} if prof.get("sections") else prof


class Tasks(OwnEdition, Kits, Exports, AnswerTasks):
    """Every long task of one panel. state() is what the panel shows."""

    def __init__(self, ws: Workspace, facts: Facts, card):
        self.ws, self.facts, self.card = ws, facts, card  # the workspace, its facts, the agent card
        self.state_lock = threading.Lock()  # guards self.tasks (lock() is the submitted-copy action)
        self.tasks: dict[str, dict] = {}  # key -> {"state", "step", "error", "result", "t"}
        self.model_lock = threading.Lock()  # one model task at a time: the backend is set in the environment
        self.read_texts = {}  # material id -> the text its last reading found (the run's contact step looks for the name in it)
        self.render_lock = threading.RLock()  # one rendering at a time: it is the heavy part. Re-entrant: a failed build cleans up while it holds it
        self.live_lock = threading.Lock()  # one live deck at a time, which also makes a second request wait for the first one's answer
        self.live_decks: dict[tuple, dict] = {}  # (job, language, colours) -> the last live page and what it was made from
        self.live_figures: dict[tuple, dict] = {}  # (job, language, colours) -> the resume's figures for the canvas and what they were drawn from
        self.standin = None  # the stand-in server, started when the stand-in backend is used
        # what the person's environment said at the start: a local model's address and name are set here while one is in use,
        # and these come back when another backend is chosen (codex takes OFFEROWL_LLM_MODEL as its -m)
        self.env0 = {k: os.environ.get(k) for k in ("OFFEROWL_LLM_URL", "OFFEROWL_LLM_MODEL")}
        self.unstick()  # a file left "reading" by a reading that never ended (the app was closed, or it broke)
        self._one = threading.local()  # per request thread: the stamps one read of the state already worked out (one_read)
        self._lang = (None, "")  # (the profile file's stamp, its language): profile_lang reads the profile again only when it changed
        self.write_ask = None  # a test's stand-in for the model in the resume draft
        self.figure_ask = None  # and in the figure step
        self.kit_srvs = {}  # job -> (its own kit server, the agent it was given) for the panel's /kit/<job>/, the most recent last (kit_url)
        self.kit_lock = threading.Lock()  # one start at a time: two first requests never bind two servers for one job
        self.autopilot_stop = threading.Event()  # the person asked a run of apps/api/autopilot.py to stop
        self.autopilot_next = None  # a run asked for while one ran: it starts when that one ends (autopilot.chain)
        self.run_no = 0  # counts the tasks started, so a finished thread never ends the next run of its key
        self._own_facts: dict[str, Facts] = {}  # each job's own edition, read once (own_dir)

    # ------------------------------------------------------------------ bookkeeping

    def state(self) -> dict:
        """A copy of every task's state."""
        with self.state_lock:  # a copy taken under the lock
            return json.loads(json.dumps(self.tasks))  # deep copy, JSON-safe

    def _set(self, key: str, **values) -> None:
        """Change one task's state."""
        with self.state_lock:  # one writer at a time
            self.tasks.setdefault(key, {}).update(values, t=time.time())  # merged, stamped

    def busy(self, key: str) -> bool:
        """The task is running now."""
        with self.state_lock:  # read under the lock
            return (self.tasks.get(key) or {}).get("state") == "running"  # running, not done or failed

    def start(self, key: str, fn, *args) -> bool:
        """Run fn(*args) in a thread as task `key`. False when it is already running."""
        with self.state_lock:  # check and mark in one step
            if (self.tasks.get(key) or {}).get("state") == "running":  # a second click must not start a twin
                return False  # one at a time per key
            self.run_no += 1  # this task's number
            no = self.run_no  # kept in its record
            self.tasks[key] = {"state": "running", "step": "queued", "t": time.time(), "run": no}  # shown at once

        def body():
            try:
                fn(*args)  # the task sets done or error itself
                with self.state_lock:  # read and written in one step
                    rec = self.tasks.get(key) or {}  # the record now
                    if rec.get("state") == "running" and rec.get("run") == no:  # still this task, and it returned without saying
                        rec.update(state="done", t=time.time())  # a task that set nothing counts as done
            except (Exception, SystemExit) as exc:  # a bug, or a tool that stopped with a message: shown as an error with a retry, logged in full
                log.exception("task %s failed", key)  # the trace goes to the log, not the page
                self._set(key, state="error", error={"code": "unexpected", "detail": type(exc).__name__})  # the page gets a code and a retry
        threading.Thread(target=body, name=f"task-{key}", daemon=True).start()  # in the background
        return True  # started

    # ------------------------------------------------------------------ the agent

    def backend(self) -> str:
        """Point src/llm.py at the backend in use and return the name its run() takes ('none' when off)."""
        name = self.card.chosen()  # from the settings
        s = self.card.settings_fn()  # the settings
        if name == "standin":  # tests and the app's check: the stand-in as an OpenAI-compatible server
            if self.standin is None:  # started once, reused after
                from .standin import serve  # only now
                self.standin = serve(0)  # a free port
            os.environ["OFFEROWL_LLM_URL"] = f"http://127.0.0.1:{self.standin.server_address[1]}"  # llm.py reads it per call
            os.environ["OFFEROWL_LLM_MODEL"] = "standin"  # the model name the stand-in ignores
            name = "openai-compat"  # llm.py reaches the stand-in this way
        elif name == "openai-compat":  # a local model server
            os.environ["OFFEROWL_LLM_URL"] = s.get("llm_url", "")  # the address from the menu
            os.environ["OFFEROWL_LLM_MODEL"] = s.get("llm_model", "") or "default"  # a name is required by the request
        else:  # an agent CLI, or none: the local model's values go, and what the start was given comes back
            for k, v in self.env0.items():
                if v is None:
                    os.environ.pop(k, None)  # not set at the start
                else:
                    os.environ[k] = v  # set at the start, by the person
        os.environ["OFFEROWL_LLM"] = name  # draft.py's calls take no backend argument; the OFFEROWL_ name wins in llm.py
        return name  # what ingest.extract takes

    # ------------------------------------------------------------------ 1. reading material

    def ingest(self, mids: list[str]) -> bool:
        """Read the listed materials and add the facts found (task "ingest")."""
        return self.start("ingest", self._ingest, list(mids))  # a copy of the ids: the caller's list may change

    def unstick(self, mids=None) -> None:
        """Files still marked "reading" go back to "new" (all of them, or those named): no reading is running for them, and
        the row would otherwise turn forever. They can be read again."""
        for m in self.ws.all_materials():  # every record, removed ones too
            if m.get("state") == "reading" and (mids is None or m.get("id") in mids):
                self.ws.update_material(m["id"], state="new")  # not read

    def _ingest(self, mids: list[str], stop=None) -> None:
        try:
            self._read(mids, stop)  # the reading itself
        except BaseException:  # it broke or was stopped hard: no file of it stays "reading"
            self.unstick(mids)
            raise  # the task records the error as before

    def _read(self, mids: list[str], stop=None) -> None:
        import ingest  # src/ingest.py
        recs = {m["id"]: m for m in self.ws.materials() if m["id"] in mids}  # the materials asked for
        profiles = [m for m in recs.values() if m["kind"] == "profile"]  # Offerowl profile files
        files = [m for m in recs.values() if m["kind"] != "profile"]  # everything else goes to the agent
        for m in recs.values():  # every file shows that it is being read
            self.ws.update_material(m["id"], state="reading", error="")  # shown at once
        by_mid, errors = {}, []  # imported profiles per material, problems
        for m in profiles:  # read as they are: no agent
            try:
                doc = json.loads(self.ws.material_path(m).read_text(encoding="utf-8"))  # the profile
                import review  # the profile's shape rules
                review.normalize(json.loads(json.dumps(doc)))  # a broken profile stops here, not at the build
                by_mid[m["id"]] = ("profile", doc)  # imported below, inside the undo step
            except (OSError, ValueError) as exc:  # unreadable or not the profile shape
                log.warning("profile %s unreadable: %s", m["id"], exc)  # the reason for the log
                self.ws.update_material(m["id"], state="error", error="profile_invalid")  # the page names the problem and offers removal
        texts, paths = {}, []  # converted text per file, files that have text
        self._set("ingest", step="reading_files")  # the step the page shows
        for m in files:  # turn each file into text first: empty ones need no agent
            p = self.ws.material_path(m)  # its file
            try:
                texts[str(p)] = ingest.to_text(p)  # PDF, Word, slides, text; images and scans through OCR
            except Exception as exc:  # a broken file
                log.warning("material %s unreadable: %s", m["id"], exc)  # the reason for the log
                texts[str(p)] = ""  # treated as a file without text
            self.read_texts[m["id"]] = texts[str(p)]  # kept for the run's contact step
            if texts[str(p)].strip():  # only files with text go to the agent
                paths.append(p)  # to the agent
            else:
                self.ws.update_material(m["id"], state="no_text")  # nothing to read in it
        asked_stop = stop  # the person's stop, from a run (autopilot.py)
        kept, dropped, stop = [], [], None  # facts found, facts without a quote, why the agent stopped
        if paths:  # no file with text: no model call
            self._set("ingest", step="asking_agent", files=len(paths))  # the pill says the agent is reading
            with self.model_lock:  # one model task at a time
                backend = self.backend()  # which agent
                try:
                    kept, dropped = ingest.extract(paths, backend=backend, texts=texts, stop=asked_stop)  # quotes checked against the text
                except ingest.Partial as exc:  # the agent stopped part way, or was never there, or the person stopped it
                    kept, dropped = exc.kept, exc.dropped  # what was read so far stays
                    stop = "stopped" if str(exc) == "stopped" else ("agent_unavailable" if not exc.asked else "agent_stopped")  # none asked: no agent; some asked: it stopped
                    log.info("ingest stopped: %s", exc)  # the reason for the log
        name_of = {str(self.ws.material_path(m)): (m["id"], m["name"]) for m in files}  # file -> material
        new = self.facts.ingest_candidates(kept, lambda f: name_of.get(f, ("", "")))  # panel candidates
        with self.ws.change({"code": "undo_add_material", "n": len(recs)}, FACT_FILES):  # one undo takes it all back
            count = 0  # facts added
            for mid, (_, doc) in by_mid.items():  # the profile files read earlier
                n = self.facts.import_profile(doc, mid, recs[mid]["name"])  # its items as facts to confirm
                self.ws.update_material(mid, state="done", facts=n)  # its count shows on its row
                count += n  # for the task's total
            count += self.facts.add_candidates(new, dropped)  # facts found by the agent
            for m in files:  # each file's own count and state
                if str(self.ws.material_path(m)) not in [str(p) for p in paths]:  # a file without text was marked already
                    continue  # no text: already marked
                n = sum(1 for c in new if c["source"]["material"] == m["id"])  # its facts
                state = "done" if not stop or n else ("needs_agent" if stop == "agent_unavailable" else "stopped")  # the file's own outcome
                self.ws.update_material(m["id"], state=state, facts=n)  # shown on its row
            self.facts.rebuild()  # the profile follows the facts
        if stop and stop != "stopped":  # an agent problem is the task's error; a stop the person asked for is not
            errors.append(stop)  # kept for the error band
        self._set("ingest", state="error" if errors else "done", step="", added=count,  # the task's end and how many facts came in
                  error={"code": errors[0]} if errors else None)  # the error band's code

    # ------------------------------------------------------------------ 3. the posting analysis

    def write_resume(self, job_id: str, lang: str = "ko") -> bool:
        """The resume's sentences written from the evidence (task "write:<job>")."""
        return self.start(f"write:{job_id}", self._write_task, job_id, lang)  # one per job at a time

    def _write_task(self, job_id: str, lang: str) -> None:
        key = f"write:{job_id}"  # this task
        self._set(key, step="writing_resume")  # the step the page shows
        got = self._write(job_id, lang, every=True)  # asked for: every part written again
        if got["state"] == "done":  # written
            self._set(key, state="done", step="", result=got)  # the page shows the counts
        else:  # no agent, or it never answered
            self._set(key, state="error", error={"code": "agent_unavailable" if got["state"] == "needs_agent" else "agent_stopped"})  # the band says which

    def draw_figures(self, job_id: str, lang: str = "ko") -> bool:
        """The deck's figures, drawn from each printed project's evidence (task "figures:<job>")."""
        return self.start(f"figures:{job_id}", self._figures_task, job_id, lang)  # one per job at a time

    def _figures_task(self, job_id: str, lang: str) -> None:
        key = f"figures:{job_id}"  # this task
        self._set(key, step="drawing_figures")  # the step the page shows
        got = self._figures(job_id, lang)  # the figures
        if got["state"] == "done":  # drawn
            self._set(key, state="done", step="", result=got)  # the page shows the counts
        else:  # no agent, no draft, or it never answered
            self._set(key, state="error", error={"code": "agent_unavailable" if got["state"] == "needs_agent" else "needs_draft" if got["state"] == "needs_draft" else "agent_stopped"})  # the band says which

    def _figures(self, job_id: str, lang: str) -> dict:
        """Figures for the deck through src/figure_draft.py, kept in the draft in force. Every number and name in a figure must be in
        that project's evidence, and a proposal that fails a check goes back once and is left out if it fails again."""
        from . import drafts as D  # where a draft is kept
        import figure_draft as FD  # src/figure_draft.py
        d, owner = D.load(self, job_id)  # the draft in force
        if not d:  # the slides read the draft's sentences, so it comes first
            return {"state": "needs_draft"}  # the page offers to write the resume
        src = self.ws.path("profile", "profile.json")  # the facts' profile
        now = D.merged(read_json(src, {}), d)  # what the deck prints
        langs = list((d.get("_draft") or {}).get("langs") or [lang])  # the languages the draft has
        printed = {p.get("id") for r in now.get("roles") or [] for p in r.get("projects") or [] if isinstance(p, dict) and p.get("resume") is not False and p.get("deck") is not False}  # the projects on the resume
        with self.model_lock:  # one model task at a time
            if self.backend() == "none":  # no agent: the slides keep their cards
                return {"state": "needs_agent"}  # the page offers to turn it on
            now, gone = FD.prune(now, langs, only=printed)  # figures today's checks turn down go first, so their places are asked for again
            doc = FD.propose(now, only=printed, langs=langs, max_calls=FIGURE_CALLS, ask=self.figure_ask, measured_calls=MEASURED_CALLS)  # the proposals, each checked
            if any(f["status"] != "ok" for e in doc["projects"] for f in e["figures"]):  # one came back with a finding
                doc = FD.repair(doc, now, ask=self.figure_ask)  # one more call with the findings
        if doc.get("errors") and not doc["projects"]:  # the model never answered
            log.info("figures %s stopped: %s", job_id, doc["errors"][:2])  # for the log only
            return {"state": "failed"}  # the page offers to try again
        FD.review(doc, accept=["all"])  # what passed every check is taken; the rest stays out
        new, added, notes = FD.apply(doc, now)  # the figures on the projects
        by_id = {p.get("id"): p for r in new.get("roles") or [] for p in r.get("projects") or [] if isinstance(p, dict)}  # the projects with their figures
        for r in d.get("roles") or []:  # the stored draft's roles
            for p in r.get("projects") or [] if isinstance(r, dict) else []:  # and projects
                got = by_id.get(p.get("id")) if isinstance(p, dict) and p.get("id") in printed else None  # the same project, when this run looked at it
                if got is None:  # a project off the resume keeps what it has
                    continue
                for k in D.FIGURE_KEYS:  # what the step adds or took out
                    if got.get(k):  # drawn
                        p[k] = got[k]  # kept with the draft
                    else:  # none left
                        p.pop(k, None)  # a figure the checks turned down does not come back
        total = sum(len(e["figures"]) for e in doc["projects"])  # every proposal
        record = read_json(self.ws.job_dir(owner) / "draft.record.json", {}) or {}  # what the draft's run did
        record["figures"] = {"added": added, "left_out": total - added, "calls": doc.get("calls", 0), "replaced": len(gone)}  # and this one
        with self.ws.change({"code": "undo_figures"}, D.files(owner)):  # one undo step
            write_json(self.ws.job_dir(owner) / "draft.json", d)  # the draft with its figures
            write_json(self.ws.job_dir(owner) / "draft.record.json", record)  # what the page shows
        return {"state": "done", **record["figures"]}  # the task's result

    def _write(self, job_id: str, lang: str, every: bool = False) -> dict:
        """Write the resume from the evidence through src/write_resume.py, and keep it with the job (apps/api/drafts.py).
        Locked sentences keep their words. A job writes for its posting, the general edition for no job in particular.
        Returns {state, ...}: done with the counts, needs_agent, or failed."""
        from . import documents as DOC  # the sentences as they are drawn now
        from . import drafts as D  # where a draft is kept
        from .evidence import replaced  # one sentence of a paragraph
        import write_resume as W  # src/write_resume.py
        job_path = self.ws.job_dir(job_id)  # the job's folder
        posting = job_path / "posting.md"  # the general edition has none
        text = posting.read_text(encoding="utf-8") if posting.is_file() else None  # what it writes for
        prof = D.with_ids(self.facts.profile())  # every project with an id
        langs = ("en",) if self.profile_lang() == "en" else ("ko", "en")  # a profile in Korean gets both, written side by side
        with self.model_lock:  # one model task at a time
            backend = self.backend()  # which agent
            if backend == "none":  # no agent: the facts stay on the canvas
                return {"state": "needs_agent"}  # the page offers to turn it on
            try:
                parts = list(W.PARTS) if text or every else None  # a job, or the person asking, rewrites every part; a run's general edition keeps the resume text a profile already holds and writes only what is missing
                new, rec = W.draft(prof, posting_text=text, style=W.load_style(self.style_spec()), langs=langs, parts=parts, backend=backend, ask=self.write_ask)  # by the person's own rules when they chose a pack
            except W.Stopped as exc:  # the model never answered
                log.info("draft %s stopped: %s", job_id, exc)  # for the log only
                return {"state": "failed"}  # the page offers to try again
        old = read_json(job_path / "draft.json", None)  # the last draft of this job
        D.carry_figures(new, old, read_json(self.ws.job_dir(D.GENERAL) / "draft.json", None))  # figures drawn already stay
        new["_locks"] = {}  # this draft's own
        for code in langs:  # each language it wrote
            before = D.merged(prof, old) if old else prof  # the ids of the locks in force
            locks = ((old or {}).get("_locks") or {}).get(code) if old else (self.facts.locks() if code == "ko" else {})  # a draft's own, else the facts'
            new["_locks"][code] = D.carry_locks(locks, before, D.links_of(old, code), new, prof, code, replaced)  # moved with their projects
        record = {"at": today(), "calls": rec.get("calls"), "stopped": rec.get("stopped") or "", "trimmed": rec.get("trimmed") or [],  # what the run did
                  "counts": {"written": len(rec.get("texts") or []), "rewritten": sum(1 for x in rec.get("texts") or [] if x.get("round") == "repair"),  # the page's counts
                             "dropped": len(rec.get("dropped") or [])}}  # texts that never passed
        with self.ws.change({"code": "undo_draft"}, D.files(job_id)):  # one undo step takes the whole draft back
            write_json(job_path / "draft.json", new)  # the drafted profile
            write_json(job_path / "draft.record.json", record)  # what the page shows
        DOC.resume(self, lang, "navy", job_id)  # a draft the canvas cannot read must fail here, inside the task
        return {"state": "done", **record["counts"]}  # the task's result

    def analyze(self, job_id: str, agent: bool = True) -> bool:
        """Match the posting to the profile (task "analyze:<job>"). agent=False keeps it on this PC, by words."""
        return self.start(f"analyze:{job_id}", self._analyze, job_id, agent)  # one analysis per job at a time

    def _analyze(self, job_id: str, agent: bool = True) -> None:
        import draft  # src/draft.py
        from . import fit  # the fit by words
        key = f"analyze:{job_id}"  # this task
        posting = (self.ws.job_dir(job_id) / "posting.md").read_text(encoding="utf-8")  # the posting
        prof = self.facts.profile()  # the profile as it is now
        self._set(key, step="asking_agent")  # the step the page shows
        cfg, by = None, "words"  # the agent's plan when it answers, else the words
        with self.model_lock:  # one model task at a time
            if agent and self.backend() != "none":  # an agent is on and may be asked: it picks what the job needs
                try:
                    cfg, steps = draft.task_jd(prof, posting)  # skill groups first, strengths back, project order
                    by = "agent"  # made by the agent
                except draft.Stopped as exc:  # the agent stopped or was never there: the words still give an order
                    log.info("analysis stopped, words instead: %s", exc)  # the reason for the log
                    cfg = None  # fall back below
        if cfg is None:  # no agent, or it stopped: the fit by words orders the resume
            self._set(key, step="matching_words")  # the step the page shows
            cfg = fit.plan_by_words(prof, fit.compute(prof, posting, evmap=self.facts.evidence(), cands=self.facts.candidates()))  # no model
        plan = {k: cfg.get(k) for k in ("skillsFocus", "competencyWeak", "projectOrder") if cfg.get(k)}  # what the build uses
        plan.update(at=today(), profile=file_hash(self.ws.path("profile", "profile.json")), by=by)  # when, from which profile, by whom
        with self.ws.change({"code": "undo_analysis"}, [f"jobs/{job_id}/plan.json"]):  # undo takes the analysis back
            write_json(self.ws.job_dir(job_id) / "plan.json", plan)  # saved with the job
        self._set(key, state="done", step="", result={k: plan.get(k) for k in ("skillsFocus", "projectOrder", "by")})  # the page shows these

    # ------------------------------------------------------------------ the English profile

    def translate(self, job_id: str | None = None) -> bool:
        """Write the English profile for English editions (task "translate"). When the job's resume draft holds English, only
        what the draft does not hold is translated."""
        return self.start("translate", self._translate, job_id)  # one translation at a time

    def drafted_english(self, job_id: str | None) -> bool:
        """Does the draft in force for this job (or the general one) hold English sentences?"""
        from . import drafts as D  # where a draft is kept
        d, _ = D.load(self, job_id)  # the job's own, else the general edition's
        return bool(d) and "en" in ((d.get("_draft") or {}).get("langs") or [])  # written in English too

    def english_for(self, job_id: str | None) -> Path | None:
        """The English profile an English edition of this job can use: a full translation, or a partial one when the job's draft
        holds the English the partial one leaves out. None when the edition must ask for a translation first."""
        own = self.own_dir(job_id)  # a job's own edition was written in its languages, and needs no translation
        if own is not None:
            return own / "profile" / "profile.json" if "en" in self.own_langs(job_id) else None
        p = self.english_profile()  # the translation of this very profile
        if p is None or self.profile_lang() == "en":  # none, or the profile is English itself
            return p  # as it is
        return p if not read_json(p, {}).get("_partial") or self.drafted_english(job_id) else None  # a partial one needs the draft's English

    def _translate(self, job_id: str | None = None) -> None:
        import draft  # src/draft.py
        src = self.ws.path("profile", "profile.json")  # the Korean profile
        prof = self.facts.profile()  # as it is now
        partial = self.drafted_english(job_id)  # the draft writes most of the words already
        self._set("translate", step="asking_agent")  # the step the page shows
        with self.model_lock:  # one model task at a time
            if self.backend() == "none":  # no agent: say so without calling
                self._set("translate", state="error", error={"code": "agent_unavailable"})  # the band offers to turn the agent on
                return  # nothing else to do
            try:
                new, steps = draft.task_translate(prof, draft.style_pack(self.style_spec()), skip_drafted=partial)  # every field that passes the checks
            except draft.Stopped as exc:  # stopped part way: what was done is kept
                new, steps = exc.result, exc.log  # what was translated before it stopped
                if not steps:  # nothing at all came back
                    self._set("translate", state="error", error={"code": "agent_unavailable"})  # the same band as with no agent
                    return  # nothing else to do
        new["_from"] = content_hash(src)  # which Korean profile it was made from: its content, so writing it again the same changes nothing
        if partial:  # the draft's parts were not asked for
            new["_partial"] = True  # an edition without such a draft asks for the rest
        write_json(self.ws.path("profile", "profile.en.json"), new)  # beside the Korean one
        kept = sum(1 for s in steps if s.get("kept"))  # fields translated
        self._set("translate", state="done", step="", result={"fields": kept, "skipped": len(steps) - kept})  # how many fields made it through the checks

    def profile_lang(self) -> str:
        """The language the profile itself is written in: Korean when Hangul makes up a fair share of its text. Remembered while
        the profile file is unchanged: the state asks several times a poll, and counting the letters is most of its time."""
        stamp = file_stamp(self.ws.path("profile", "profile.json"))  # None: missing (built now) or written just now
        lang = self._lang  # one read of the pair: another thread may replace it meanwhile
        if stamp is not None and lang[0] == stamp:  # the same file as last time
            return lang[1]
        text = json.dumps(self.facts.profile(), ensure_ascii=False)  # every word of it
        han = sum(1 for ch in text if "\uac00" <= ch <= "\ud7a3")  # Hangul syllables
        latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())  # Latin letters
        out = "ko" if han * 3 >= latin * 0.5 and han > 20 else "en"  # a syllable carries more than a letter
        if stamp is not None:  # a version that can be told again: remembered
            self._lang = (stamp, out)
        return out

    @contextlib.contextmanager
    def one_read(self):
        """One read of the state (App.state): what does not change within it (the deck source's stamp) is worked out once
        instead of once per edition. Per thread, so another request's read never sees this one's memo; nested reads share it."""
        outer = getattr(self._one, "memo", None)  # a read already open in this thread
        if outer is None:  # the first: a fresh memo
            self._one.memo = {}
        try:
            yield
        finally:
            if outer is None:  # the read that opened it closes it: the next poll looks at the files again
                self._one.memo = None

    def english_profile(self) -> Path | None:
        """The English profile when it was made from the profile as it is now, else None. A profile written in English
        is its own English profile."""
        if self.profile_lang() == "en":  # nothing to translate
            return self.ws.path("profile", "profile.json")  # the profile itself
        p = self.ws.path("profile", "profile.en.json")  # the translation
        if not p.is_file():  # never translated
            return None  # the English edition must ask for it
        src, made = self.ws.path("profile", "profile.json"), read_json(p, {}).get("_from")  # the profile, and the one it was made from
        return p if made and made in (content_hash(src), file_hash(src)) else None  # only a translation of this very profile (an older one names its bytes)

    # ------------------------------------------------------------------ 4. the documents

    engine_needs: list = []  # what the browser renderer lacks, when engine_ready said so (the page names each)

    def engine_ready(self) -> str:
        """'' when the typesetting can run here, else why not: 'engine_not_ready' (its libraries are not installed),
        'renderer_missing' (no container runtime, not inside the container, and no browser that can typeset), or on Windows
        'browser_missing' (the browser is the only way there; engine_needs says what it lacks)."""
        needs = []  # what the browser renderer lacks, worked out here and set once below: the state is read by several request
        #             threads at once, and one emptying the list while another reads it gave "renderer_missing" with no reason
        if not (ROOT / "node_modules" / "docx").is_dir():  # the resume writer's library
            self.engine_needs = needs  # nothing the browser lacks: the libraries come first
            return "engine_not_ready"  # the fix button installs them
        # not inside one of Offerowl's images, and no container runtime on this PC, or Windows, where the container's starter
        # (render/run.sh, a shell script) cannot run
        if not in_image() and (sys.platform == "win32" or not shutil.which("docker")):
            try:  # the browser renderer may still typeset here (docs/ARCHITECTURE.md)
                import resume  # the renderer switch lives in src/resume.py
                rep = resume.renderers()  # which renderers this PC can run
                if rep["html"]["ok"]:  # this PC's own Chrome or Edge can typeset
                    if os.environ.get("OFFEROWL_RENDERER") != "html":  # set once: every poll asks, and request threads share the environment
                        os.environ["OFFEROWL_RENDERER"] = "html"  # builds from this process use it from now on
                    self.engine_needs = needs  # nothing lacking
                    return ""  # ready, through the browser
                needs = [str(n) for n in rep["html"].get("needs") or []]  # what it lacks: a browser, Node.js, Pillow, fonts
            except Exception as exc:  # a broken probe must not hide the real reason below
                log.warning("renderer probe failed: %s", exc)  # for the log
            self.engine_needs = needs  # one assignment: a reader sees the old list or the new one, never an emptied one
            if sys.platform == "win32":  # Docker cannot help here: the page names what the browser lacks
                return "browser_missing"
            return "renderer_missing"  # neither Docker nor a usable browser: the fix button links to the guide
        self.engine_needs = needs  # ready: nothing lacking
        return ""  # ready

    def renderer_in_use(self) -> str:
        """The renderer the PDFs are made with, as the build picks it: "html" (this PC's Chrome or Edge) or "container"."""
        try:  # the build's own choice (src/resume.py): OFFEROWL_RENDERER, the browser on Windows, Docker where it is
            import resume  # the renderer switch
            return resume.renderer()  # cheap after the first answer: the browser's probe is kept
        except (Exception, SystemExit):  # an unknown OFFEROWL_RENDERER stops a build with its message, not the page's state
            return "container"  # the guide's general words

    def setup_engine(self) -> bool:
        """Install the typesetting libraries once (task "setup"): the one step that needs the network."""
        return self.start("setup", self._setup)  # one install at a time

    def _setup(self) -> None:
        self._set("setup", step="installing")  # the step the page shows
        env = {**os.environ, "OFFEROWL_NET": "1"}  # run.sh opens the network for this alone
        # inside one of Offerowl's images, on Windows (render/run.sh is a shell script it cannot start), or no Docker but npm here
        direct = in_image() or sys.platform == "win32" or (not shutil.which("docker") and shutil.which("npm"))
        npm = shutil.which("npm")  # its full path: on Windows npm is npm.cmd, which a command list without a shell never finds
        if direct and npm is None:  # nothing here can install them
            self._set("setup", state="error", step="", error={"code": "setup_failed", "detail": "npm"})  # the page says so, with its retry
            return
        cmd = [npm, "ci"] if direct else [str(ROOT / "render" / "run.sh"), "npm", "ci"]  # otherwise through the container
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=900)  # npm ci
        log.info("setup: %s", (r.stdout + r.stderr)[-2000:])  # its output, for the log only
        ok = r.returncode == 0 and (ROOT / "node_modules" / "docx").is_dir()  # really there
        self._set("setup", state="done" if ok else "error", step="", error=None if ok else {"code": "setup_failed"})  # done only when the library is really there

    def build(self, job_id: str, lang: str, theme: str, max_pages: int, cover: bool = True, blind: bool | None = None) -> bool:
        """Make the resume, the deck and (when asked and available) the cover letter for a job (task "build:<job>"). blind: True
        or False makes it a blind edition or an ordinary one; None keeps what the edition was (blind_choice)."""
        return self.start(f"build:{job_id}", self._build, job_id, lang, theme, max_pages, cover, False, blind)  # one build per job at a time

    # ------------------------------------------------------------------ the blind edition

    def blind_file(self) -> Path | None:
        """The person's own mask table (the workspace's blind.json, app.set_blind), or None: then src/blind.json, which covers
        nothing."""
        f = self.ws.path("blind.json")  # beside the profile and the jobs, never in the repository
        return f if f.is_file() else None

    def blind_table(self) -> dict:
        """The table a blind edition is made and checked with now: the person's own over the shipped one (src/blind.py)."""
        import blind  # src/blind.py: the merge and the patterns
        f = self.blind_file()  # their table, if any
        mine = read_json(f, {}) if f else {}  # as kept
        return blind.merged(mine if isinstance(mine, dict) else {})

    # ------------------------------------------------------------------ the person's own deck source

    def deck_dir(self) -> Path | None:
        """The person's own deck source: the workspace's deck/ folder with its build.js (docs/DOCUMENTS.md), or None: then each
        edition's deck is drawn from the profile, or is the portfolio PDF the profile names."""
        d = self.ws.path("deck")  # beside the profile and the jobs
        return d if (d / "build.js").is_file() else None

    def deck_stamp(self) -> str:
        """What the person's deck source is now (a short hash of its files' names and contents, "" for none): an edition whose deck
        was written from another source is stale. Worked out again only when a file of the folder changed (the state asks for it
        once per edition, so within one read of the state it is worked out once: one_read)."""
        memo = getattr(self._one, "memo", None)  # the read of the state this thread is in, if any
        if memo is not None and "deck" in memo:  # already worked out in this read
            return memo["deck"]
        out = self._deck_stamp_now()  # the folder looked at
        if memo is not None:  # kept for the rest of this read
            memo["deck"] = out
        return out

    def _deck_stamp_now(self) -> str:
        """deck_stamp, from the folder as it is now."""
        d = self.deck_dir()  # the source, if any
        if d is None:
            return ""
        files = sorted(p for p in d.rglob("*") if p.is_file())  # every file of it
        stats = [p.stat() for p in files]  # one stat per file, not one per number below
        key = (str(d), len(files), max((st.st_mtime_ns for st in stats), default=0), sum(st.st_size for st in stats))  # cheap to read
        if getattr(self, "_deck_stamp", (None, ""))[0] != key:  # changed since it was last worked out
            h = hashlib.sha256()  # names and contents
            for p in files:
                h.update(str(p.relative_to(d)).encode() + b"\0" + file_hash(p).encode())  # each file's hash is itself remembered while it is unchanged
            self._deck_stamp = (key, h.hexdigest()[:16])
        return self._deck_stamp[1]

    def _stage_deck(self, suffix: str = "deck") -> str | None:
        """The person's deck source copied into the engine's folder, where its scripts find the engine's libraries (in the
        container too): repository-relative, or None when there is none. A build stages it under the render lock and its
        clean-up takes it away; a live page stages its own copy (suffix) and takes it away itself."""
        d = self.deck_dir()  # the source, if any
        if d is None:
            return None
        dst = ROOT / "output" / "_inputs" / (hashlib.sha1(str(d.resolve()).encode()).hexdigest()[:8] + "_" + suffix)  # named as resume.rel names its copies
        shutil.rmtree(dst, ignore_errors=True)  # a fresh copy: a file removed from the source does not linger
        shutil.copytree(d, dst)
        return dst.relative_to(ROOT).as_posix()  # / on every system, as resume.rel writes it

    def blind_stamp(self) -> str:
        """What the person's table is now (a short hash of its content, "" for none): a blind edition made with another table is
        stale."""
        f = self.blind_file()  # their table, if any
        return content_hash(f) if f else ""

    def blind_choice(self, job_id: str, lang: str, asked: bool | None) -> bool:
        """Is this build of an edition a blind one? What the build asks (the panel's switch); else what the edition was when it
        was last made, so making it again never drops the bars a person turned on (nor adds them); else what a job's own
        edition was brought in as (own/form.json "blind"), which also wins when that edition was brought in again since."""
        if isinstance(asked, bool):  # the switch, or a build that names it
            return asked
        prev = read_json(self.build_dir(job_id, lang) / "build.json", {}) or {}  # the edition as last made
        form = self.own_form(job_id, lang)  # how a job's own edition was made
        if prev and not ("blind" in form and prev.get("own") != self.own_stamp(job_id)):  # made before, from the same own edition
            return prev.get("blind") is True
        return form.get("blind") is True  # the first build, or a new own edition: as it was brought in

    def blind_env(self, lang: str, on: bool) -> dict:
        """The environment of one edition's typesetting: this process's without any blind switch it was started with, and for a
        blind edition its own (OFFEROWL_BLIND, its language, and the person's table staged where the typesetting reads it,
        OFFEROWL_BLIND_TABLE). Every build gets a copy of its own, so one edition's switches never reach another's and the
        server's own environment is never changed."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_BLIND")}  # no switch carried over from the start
        if on:  # a blind edition
            env.update(OFFEROWL_BLIND="1", OFFEROWL_BLIND_LANG=lang)  # its bars, band and label in its language
            f = self.blind_file()  # the person's table, if any
            if f:  # staged in the engine's folder (resume.rel), where the container sees it; _clean_engine takes it out again
                import resume  # the staging rule
                env["OFFEROWL_BLIND_TABLE"] = resume.rel(str(f))
        return env

    def pdf_text(self, pdf: Path) -> str:
        """A PDF's text layer: read on this PC when it has a reader, else by the engine's container (poppler), through a
        folder of the engine's own that is gone again afterwards."""
        import pdftools  # poppler or PDFium on this PC
        if pdftools.reader():  # either reader here: no container needed
            return pdftools.text(pdf)
        import resume  # the container's tools
        tmp = ROOT / "output" / "_panel_text"  # inside the repository, which the container sees
        shutil.rmtree(tmp, ignore_errors=True)  # a clean folder
        tmp.mkdir(parents=True)
        try:
            shutil.copyfile(pdf, tmp / "in.pdf")  # the PDF where the container finds it
            return resume.sh(["pdftotext", resume.rel(str(tmp / "in.pdf")), "-"]).stdout or ""  # its text
        except (OSError, SystemExit) as exc:  # no reader anywhere (no container, no poppler): read as nothing, which the caller refuses
            log.warning("pdf text unread: %s", exc)  # for the log only
            return ""
        finally:
            shutil.rmtree(tmp, ignore_errors=True)  # nothing of it stays

    def blind_leaks(self, out_dir: Path, files) -> list[str] | None:
        """The table's leak and mask patterns that a blind edition's PDFs still show: in their text layer, in the title, author
        and outline strings of every revision of each file, and in their links' addresses (src/pdfmeta.py strings). [] when
        nothing covered shows; None when a PDF's text could not be read, which never counts as clean."""
        import blind  # src/blind.py: where the patterns match
        import pdfmeta  # the strings a PDF keeps besides its text layer
        table, found = self.blind_table(), []  # the table as it is now: a pattern added since the build counts too
        for f in files:  # each PDF that would go
            text = self.pdf_text(out_dir / f)  # what a reader can copy out of it
            if not text.strip():  # an edition's resume and deck always hold text: nothing read is not nothing found
                return None
            found += blind.leaks(text + "\n" + "\n".join(pdfmeta.strings(out_dir / f)), table)  # its words and its strings
        return list(dict.fromkeys(found))  # each pattern once

    def build_dir(self, job_id: str, lang: str) -> Path:
        """Where a job's edition in one language is kept."""
        return self.ws.job_dir(job_id) / "resume" / lang  # jobs/<job>/resume/<lang>/

    def photo_for_build(self):
        """The resume's photo (the workspace's profile/photo.jpg or .png) when the setting puts it on the resume, else None."""
        if self.card.settings_fn().get("photo", True) is False:  # taken off the resume
            return None
        return next((f for f in (self.ws.path("profile", "photo.jpg"), self.ws.path("profile", "photo.png")) if f.is_file()), None)

    def style_spec(self) -> str:
        """The style pack every draft and check uses: "default", or the path of the person's own pack in the workspace's
        style/ folder, chosen in the panel (the inspector's Style tab). A pack that has gone counts as the default."""
        name = str(self.card.settings_fn().get("style") or "default")  # the choice
        f = self.ws.path("style", f"{name}.json")  # where a person's pack lives
        return str(f) if name != "default" and re.fullmatch(r"[\w가-힣.-]{1,60}", name) and f.is_file() else "default"  # only a pack that is there

    def look(self) -> dict:
        """The form and the deck's look chosen in the panel, as job.json names them."""
        s = self.card.settings_fn()  # the saved choices
        return {"form": s.get("form") if s.get("form") in FORMS else FORMS[0], "deckStyle": s.get("deck_style") if s.get("deck_style") in DECK_STYLES else DECK_STYLES[0]}  # the first of each is the default

    def edition_cfg(self, job_id: str | None, lang: str, theme: str) -> dict:
        """What resume_form.js and deck_slides.js read for an edition (its job.json, without the output name, the page limit
        and the photo). A job drafted from the profile takes the posting analysis's order and focus; a job's own edition
        keeps its own order and adds the layout choices it was made with."""
        own = self.own_dir(job_id) is not None  # the person's own edition prints as made
        plan = {} if own or not job_id else read_json(self.ws.job_dir(job_id) / "plan.json", {})  # the posting analysis, if any
        cfg = {"lang": lang, "theme": theme if theme in THEMES else "navy", "style": self.style_spec(), **self.look(),
               **{k: plan[k] for k in ("skillsFocus", "competencyWeak", "projectOrder") if plan.get(k)}}
        cfg.update({k: v for k, v in self.own_form(job_id, lang).items() if k != "photo"})  # the photo is the build's to stage
        return cfg

    def letter_pages_all(self) -> dict:
        """letter_pages for every job and named edition, in both languages: run once when the panel starts. {job|lang: pages}."""
        done = {}  # what was drawn
        try:
            every = [*self.ws.jobs(), *self.ws.editions()]  # every job and named edition
        except OSError:  # a workspace that went away meanwhile (a test's folder)
            return done
        for st in every:  # each one
            for lang in LANGS:  # each edition
                try:
                    n = self.letter_pages(st["id"], lang)  # drawn when it was missing
                except Exception:  # noqa: BLE001  one letter that cannot be drawn leaves the others
                    log.exception("letter pages for %s %s", st.get("id"), lang)  # the trace for the log
                    continue
                if n is not None:  # something was done
                    done[f"{st['id']}|{lang}"] = n
        return done

    def _build(self, job_id: str, lang: str, theme: str, max_pages: int, with_cover: bool = True, write_cover: bool = False,
               blind: bool | None = None) -> None:
        """The PDFs of an edition. It typesets what is there: only tailoring (write_cover) asks the agent for a new letter.
        blind: a blind edition (blind_choice): the resume and a deck Offerowl draws, with the person's table's bars, the
        page-1 band and the footer label. What no bar can cover stays out of it, and its notes say so: a file the person
        made (their resume is typeset from the edition's words instead; their portfolio, the profile's deck.pdf included, is
        left out), the cover letter (written to one company), and the plain words for job sites."""
        import resume  # src/resume.py: the existing pipeline
        key = f"build:{job_id}"  # this task
        if lang not in LANGS or theme not in THEMES:  # the panel only offers these
            self._set(key, state="error", error={"code": "bad_request"})  # the page never sends these; a stale page might
            return  # nothing else to do
        prof = self.facts_for(job_id).profile()  # the profile now: the job's own edition when it has one
        bad = problems(prof)  # what stops a resume
        if bad:  # a name, an email or a job is missing
            self._set(key, state="error", error={"code": bad[0]})  # the band names the first one
            return  # nothing else to do
        why = self.engine_ready()  # can it typeset here
        if why:  # no typesetting tools here
            self._set(key, state="error", error={"code": why})  # the band offers the fix
            return  # nothing else to do
        own = self.own_src(job_id, lang)  # the job's own edition, when the person brought one in
        if own == "own_lang":  # brought in without this language
            self._set(key, state="error", error={"code": "own_lang"})  # said in words: the person brings that language in too
            return
        src = own or self.ws.path("profile", "profile.json")  # the job's own, or the Korean profile
        if lang == "en" and own is None:  # the English edition needs the English profile
            src = self.english_for(job_id)  # made from this profile, in full or with this job's draft
            if src is None:  # no English profile of this profile yet
                self._set(key, state="error", error={"code": "needs_translation"})  # the band offers to translate
                return  # nothing else to do
        blind = self.blind_choice(job_id, lang, blind)  # a blind edition, or an ordinary one
        if blind:  # its table must be one the typesetting can read: a file changed by hand since it was kept is refused here
            import blind as B  # src/blind.py: the table's checks
            f = self.blind_file()  # the person's own table, if any
            if f and B.problems(read_json(f, None)):  # broken: a blind edition never falls back to covering nothing
                self._set(key, state="error", error={"code": "blind_table"})  # the band says to pick the table again
                return
        out_dir = self.build_dir(job_id, lang)  # where this edition goes
        out_dir.mkdir(parents=True, exist_ok=True)  # jobs/<job>/resume/<lang>/
        name = "owl_" + self.short(job_id) + "_" + lang  # the engine's output name
        cfg = {"out": name, "maxPages": max_pages, **self.edition_cfg(job_id, lang, theme)}  # job.json: what resume_form.js and deck_slides.js read
        cfg.pop("blind", None)  # what the edition was brought in as gives way to what this build is
        if blind:  # kept with the edition: this one was made blind
            cfg["blind"] = True
        form = self.own_form(job_id, lang)  # a job's own edition: how it was made
        photo = self.photo_for_build() if form.get("photo") is not False and not blind else None  # the resume's photo, unless the edition was made without one; a blind edition has none (a face is not covered by a bar)
        if photo:  # staged where the engine reads it, in the container too (resume.rel copies it into output/_inputs)
            cfg["photo"] = {"file": resume.rel(str(photo)), "layout": "flush",  # the photo fills its 3:4 cell
                            **{k: v for k, v in (form.get("photo") or {}).items() if k in ("layout", "w")}}  # or the edition's own cell
        write_json(out_dir / "job.json", cfg)  # kept with the edition
        self._edition_profile(job_id, src, lang, out_dir)  # the profile it was made from (the lock freezes it too)
        left = []  # what a blind edition leaves out, for its notes
        from_source = False  # whether the deck was written from the person's deck source
        with self.render_lock:  # one rendering at a time
            # this edition's own switches, never the server's environment. Made under the lock: the person's table is staged
            # under one name for every edition, and another build's clean-up (which takes the lock too) must not take it away mid-build
            env = self.blind_env(lang, blind)
            env.pop("OFFEROWL_DECK_SOURCE", None)  # never one the server was started with
            deck_src = self._stage_deck()  # the person's own slides, when they keep them in the workspace
            if deck_src:  # every edition's deck is written from them (the job's own deck file still comes first)
                env["OFFEROWL_DECK_SOURCE"] = deck_src
            try:
                self._set(key, step="typesetting_resume")  # the step the page shows
                # the person's own resume file stands for the typeset one; a blind edition typesets the edition's words, which it can cover
                mine = None if blind else self._own_pdf(job_id, "resume", lang, out_dir)
                if blind and self.own_file(job_id, "resume", lang):  # their own file is set aside
                    left.append("blind_own_file")
                pdf = mine or resume.build(str(out_dir / "profile.json"), str(out_dir / "job.json"), env)  # docx and PDF
                import pdfmeta  # the page count, read from the PDF
                if pdfmeta.pages(pdf) > max_pages and own is None and mine is None:  # over the limit: the lists keep as many of their first parts as fit (a person's own edition prints whole)
                    full = ledger_parts(read_json(out_dir / "profile.json", {}))  # the longest list's parts
                    tries = [(keep, 0) for keep in range(full - 1, 0, -1)] + [(1, n) for n in range(1, 4)]  # one part fewer each time; then the last lists, one at a time
                    for keep, drop in tries:  # so the last page stays as full as it can
                        self._edition_profile(job_id, src, lang, out_dir, compact=keep, drop=drop)
                        pdf = resume.build(str(out_dir / "profile.json"), str(out_dir / "job.json"), env)  # typeset again
                        if pdfmeta.pages(pdf) <= max_pages:  # it fits
                            break
                self._set(key, step="printing_deck")  # the step the page shows
                if blind and (self.own_file(job_id, "deck", lang) or resume.blind_leaves_deck(str(out_dir / "profile.json"), str(out_dir / "job.json"), env)):
                    deck = None  # the person's own portfolio cannot be covered: a blind edition leaves it out, never replaced by a drawn one
                    left.append("blind_no_deck")
                else:  # 16:9 deck PDF: the person's own, or one drawn (a blind one with its bars)
                    own_deck = None if blind else self._own_pdf(job_id, "deck", lang, out_dir)  # the job's own deck file, if any
                    deck = own_deck or resume.build_deck(str(out_dir / "profile.json"), str(out_dir / "job.json"), env)
                    from_source = bool(deck_src) and own_deck is None  # written from the person's deck source
            except SystemExit as exc:  # resume.py stops with the tool's output
                text = str(exc)  # its output
                log.warning("build %s failed: %s", job_id, text[-3000:])  # in full, for the log only
                code = "needs_translation" if re.search(r"언어|\ben\b", clean_reason(text)) and lang == "en" else "build_failed"  # an English edition missing its English text
                self._set(key, state="error", error={"code": code, "detail": clean_reason(text)})  # the cleaned reason, never a path
                self._clean_engine(job_id, lang, out_dir)  # a failed build leaves nothing behind either
                return  # nothing else to do
            self._set(key, step="checking")  # the step the page shows
            # the document checks; a resume the person made is theirs as it is: its pages are shown, not measured against the profile.
            # A resume the person wrote prints whole (it is never shortened to fit), so its own length is never over the limit: the
            # panel's limit (three by default) made a six-page edition brought in fail its checks when it was made again, and its
            # export was refused with nothing the person could change
            limit = max_pages if own is None else max(max_pages, pdfmeta.pages(pdf))
            issues, notes = ([], ["own_file"]) if mine else self._check(str(out_dir / "profile.json"), pdf, deck, limit, env)
            self._set(key, step="previews")  # the step the page shows
            for f in ("resume.pdf", "resume.docx", "resume_plain.docx", "resume.txt", "deck.pdf"):  # the last edition's files go first
                (out_dir / f).unlink(missing_ok=True)  # an old file must never pass for a new one
            shutil.copyfile(pdf, out_dir / "resume.pdf")  # the resume
            docx = out_dir / "own_resume.docx" if mine else pdf.with_suffix(".docx")  # its Word file (the person's own, when it came as one)
            if docx.is_file():  # the Word copy, when LibreOffice wrote it
                shutil.copyfile(docx, out_dir / "resume.docx")  # beside the PDF
            if deck:  # the deck, unless a blind edition left it out
                shutil.copyfile(deck, out_dir / "deck.pdf")
            if mine or blind:  # no plain words for a resume the person made (its words are in its file), nor for a blind edition (a Word or text file of plain words cannot carry the bars)
                log.info("plain resume of %s left out: %s", job_id, "own resume file" if mine else "blind edition")  # for the log only
            else:
                try:  # the same words in one column, for a job site that reads a file by itself
                    plain_docx, plain_txt = resume.build_plain(str(out_dir / "profile.json"), str(out_dir / "job.json"))  # a Word file and a text file
                    shutil.copyfile(plain_docx, out_dir / "resume_plain.docx")  # beside the others
                    shutil.copyfile(plain_txt, out_dir / "resume.txt")  # and the text
                except (SystemExit, OSError) as exc:  # the typeset documents stand without them
                    log.warning("plain resume of %s failed: %s", job_id, str(exc)[-2000:])  # for the log only
            pages = self._previews(out_dir / "resume.pdf", out_dir / "preview", "r", 110)  # resume pages
            if deck:  # deck slides
                slides = self._previews(out_dir / "deck.pdf", out_dir / "preview", "d", 80)
            else:  # none: the last edition's slide pictures go too
                for old in (out_dir / "preview").glob("d-*.png"):
                    old.unlink()
                slides = 0
        for f in ("cover.pdf", "cover.docx"):  # the last letter's files
            (out_dir / f).unlink(missing_ok=True)  # they never stand for this edition's
        if blind:  # a letter is written to one company by name: a blind edition has none
            cover = None
            if with_cover and ((out_dir / "cover" / "cover.json").is_file() or self.own_file(job_id, "cover", lang)):  # a letter that is there would have been made
                left.append("blind_no_cover")
        else:
            if with_cover and self.cover_available():  # the letter needs its own step text
                self._set(key, step="writing_cover" if write_cover else "typesetting_cover")  # the step the page shows
            own_cover = self._own_pdf(job_id, "cover", lang, out_dir)  # the person's own letter, when they made one for this edition
            if own_cover:  # it is the letter: as it is
                shutil.copyfile(own_cover, out_dir / "cover.pdf")
                if (out_dir / "own_cover.docx").is_file():  # its Word file, when it came as one
                    shutil.copyfile(out_dir / "own_cover.docx", out_dir / "cover.docx")
                cover = {"state": "done", "own": True, "issues": [], "notes": ["own_file"],  # what the page reads of a letter
                         "pages": self._previews(out_dir / "cover.pdf", out_dir / "preview", "c", 110)}  # and its pages: the Cover letter tab draws only page pictures for a letter the person made
            else:
                cover = self._cover(job_id, lang, out_dir, write=write_cover) if with_cover else None  # the cover letter, when that module exists
        hashes = {f: file_hash(out_dir / f) for f in ("resume.pdf", "deck.pdf", "cover.pdf") if (out_dir / f).is_file()}  # what was checked: only these bytes go out (export)
        info = {"lang": lang, "theme": theme, **self.look(), "pages": pages, "slides": slides, "issues": issues, "notes": notes + left, "hashes": hashes,  # what the inspector and the canvas show
                "at": time.strftime("%Y-%m-%d %H:%M"), "profile": content_hash(self.ws.path("profile", "profile.json")),  # when, and from which profile's content (stale editions are marked)
                "own": self.own_stamp(job_id),  # and from which own edition or files, when the job has them
                "maxPages": max_pages, "cover": cover, "draft": self.draft_stamp(job_id)}  # what the panel shows; the draft it was made from
        if blind:  # a blind edition says so, and which table its bars came from (another table makes it stale)
            info.update(blind=True, blind_table=self.blind_stamp())
        if deck and from_source:  # its deck was written from the person's deck source: which one (another makes it stale)
            info["deck_src"] = self.deck_stamp()
        write_json(out_dir / "build.json", info)  # kept with the edition
        self._clean_engine(job_id, lang, out_dir)  # the edition has its own copies now
        if not blind and (self.ws.job_dir(job_id) / "interview" / "kit.json").is_file():  # a kit made before these PDFs (a blind deck's bars would hide its words from the kit)
            try:
                self.ensure_kit(job_id, lang)  # its question map follows the new deck
            except Exception:  # noqa: BLE001  the PDFs still stand
                log.exception("interview kit for %s not refreshed", job_id)  # the trace for the log
        desk = None  # the portfolio's name on the Desktop, when the setting keeps it there
        if job_id == "-general" and not blind:  # only the general edition's, never a blind one
            from . import delivery  # the portfolio kept on the Desktop
            try:
                desk = delivery.keep_portfolio(self, lang)  # copied when its checks passed and the person asked for it
            except OSError as exc:  # a Desktop that cannot be written: the build stands, the next one tries again
                log.warning("portfolio not kept on the Desktop: %s", exc)  # for the log only
        self._set(key, state="done", step="", result={"pages": pages, "slides": slides, "issues": len(issues), "blind": blind, "desk": desk})  # the task's result

    def short(self, job_id: str) -> str:
        """The name part of a job's files in the engine's folder: from the workspace and the job, so two panels that share one
        engine folder (a test run beside an open panel, two workspaces) never write or clean each other's files."""
        return hashlib.sha1(f"{self.ws.root.resolve()}|{job_id}".encode("utf-8")).hexdigest()[:8]

    def _clean_engine(self, job_id: str, lang: str, out_dir: Path) -> None:
        """A person's words do not stay in the engine's folder: its working copies of an edition go once the edition has its own, or failed."""
        short = self.short(job_id)  # the name part the edition's outputs share
        out = ROOT / "output"  # the engine's folder
        names = (f"owl_{short}_{lang}", f"owl_cover_{short}_{lang}")  # the resume and deck's name, the letter's name
        found = [f for n in names for pat in (f"{n}*", f"_figures/{n}_*", f"_inputs/{n}*") for f in out.glob(pat) if "_live" not in f.name]  # the PDFs, pictures and settings of this edition; a live page cleans up after itself
        found += out.glob("_fig/badge_*.png")  # a badge's file name holds the company's name in hex: a cache worth nothing next to that
        spec = self.style_spec()  # the person's rules, staged for the check
        if spec != "default":  # their staged copy goes too
            found.append(out / "_inputs" / (hashlib.sha1(str(Path(spec).resolve()).encode()).hexdigest()[:8] + "_" + Path(spec).name))  # named as resume.rel names it
        for f in (self.ws.path("profile", "photo.jpg"), self.ws.path("profile", "photo.png")):  # the photo's staged copy: a face does not stay in the engine's folder
            found.append(out / "_inputs" / (hashlib.sha1(str(f.resolve()).encode()).hexdigest()[:8] + "_" + f.name))  # named as resume.rel names it
        prof = read_json(out_dir / "profile.json", {})  # the logo pictures the profile names were staged beside it (resume.stage_logos)
        for h in [*(prof.get("roles") or []), *(prof.get("education") or []), *[p for r in prof.get("roles") or [] if isinstance(r, dict) for p in r.get("projects") or []]]:
            lg = h.get("logo") if isinstance(h, dict) else None
            if isinstance(lg, str) and lg and Path(lg).is_absolute():  # a picture outside the engine's folder: its staged copy goes
                found.append(out / "_inputs" / (hashlib.sha1(str(Path(lg).resolve()).encode()).hexdigest()[:8] + "_" + re.sub(r"[^\w가-힣.-]", "_", Path(lg).name)))
        for src in (out_dir / "profile.json", out_dir / "job.json", out_dir / "cover" / "cover.json", out_dir / "cover" / "plan.json", out_dir / "cover" / "job.json",  # the inputs staged for the container
                    self.ws.path("blind.json")):  # and the person's mask table, staged for a blind edition: their names do not stay there either
            found.append(out / "_inputs" / (hashlib.sha1(str(src.resolve()).encode()).hexdigest()[:8] + "_" + src.name))  # named by the hash of their path
        with self.render_lock:  # never under a build that is running: it would lose the files it is making
            d = self.deck_dir()  # the person's deck source was staged for the build
            if d is not None:  # its copy goes: the person's slides do not stay in the engine's folder
                shutil.rmtree(out / "_inputs" / (hashlib.sha1(str(d.resolve()).encode()).hexdigest()[:8] + "_deck"), ignore_errors=True)
            for f in found:  # each working copy
                try:
                    f.unlink(missing_ok=True)  # gone
                except OSError as exc:  # a file held open elsewhere: the next build tries again
                    log.info("working copy stays: %s", exc)  # for the log only

    def deck_live(self, job_id: str, lang: str, theme: str = "navy") -> dict:
        """The deck as it will print, as one page for the canvas's frame: {"html", "slides"}, or {"missing": code} when it cannot be
        drawn yet. It reads the same profile the PDFs read, writes nothing to the edition (a locked job stays as submitted), and
        leaves nothing in the engine's folder. The answer is kept until the profile, the draft or the colours change."""
        prof_now = self.facts_for(job_id).profile()  # the profile as kept: the job's own edition when it has one
        bad = problems(prof_now)  # what stops a resume stops its slides
        if bad:  # a name, an email or a job is missing
            return {"missing": bad[0]}  # the page names the first one
        spec = (prof_now.get("deck") or {}).get("pdf") if isinstance(prof_now.get("deck"), dict) else None  # the person's own portfolio
        if spec and (spec.get(lang) if isinstance(spec, dict) else spec) and self.deck_dir() is None:  # its pages are the deck: shown as printed, never redrawn from data
            return {"missing": "own_deck"}  # (a deck source, when there is one, writes the page instead)
        why = self.engine_ready()  # the engine's libraries, or a way to run them
        if why:  # no typesetting tools here
            return {"missing": why}  # the page offers the fix
        own = self.own_src(job_id, lang)  # the job's own edition, when the person brought one in
        if own == "own_lang":  # brought in without this language
            return {"missing": "own_lang"}
        src = own or (self.ws.path("profile", "profile.json") if lang == "ko" or self.profile_lang() == "en" else self.english_for(job_id))  # the profile of this language
        if src is None:  # no English profile of this profile yet
            return {"missing": "needs_translation"}  # the page offers to translate
        cfg = self.edition_cfg(job_id, lang, theme)  # what deck_slides.js reads, as the PDFs use it
        from . import drafts as D  # where a draft is kept
        _, owner = D.load(self, job_id)  # the job's own draft, else the general edition's
        mine = [src] + ([self.ws.job_dir(owner) / "draft.json"] if owner else [])  # the files the page is made from
        stamp = (json.dumps(cfg, sort_keys=True), *[file_hash(f) for f in mine], self.deck_stamp())  # the page is made again only when one of these changes (or the deck source)
        where = (job_id, lang, cfg["theme"])  # this document
        with self.live_lock:  # one at a time; a request that waited finds the page made
            old = self.live_decks.get(where)  # the page already made
            if old and old["stamp"] == stamp:  # nothing changed
                return old["page"]  # answered at once
            page = self._make_live_deck(job_id, lang, src, cfg)  # made now
            if "html" in page:  # only a finished page is kept
                self.live_decks[where] = {"stamp": stamp, "page": page}  # for the next request
            return page

    def _make_live_deck(self, job_id: str, lang: str, src: Path, cfg: dict) -> dict:
        """One live page, from a working folder that is gone again when this returns."""
        import resume  # src/resume.py: the pipeline
        short = self.short(job_id)  # the name part an edition's outputs share
        name = f"owl_{short}_{lang}_live"  # the printing edition's files keep their own names
        folder = self.ws.job_dir(job_id) / "live" / lang  # the working folder
        folder.mkdir(parents=True, exist_ok=True)  # made on first use
        write_json(folder / "job.json", {**cfg, "out": name})  # the settings under the live name
        self._edition_profile(job_id, src, lang, folder)  # the draft's sentences in the facts' profile, as the PDFs have them
        engine = ROOT / "output"  # the engine's folder
        inputs = [engine / "_inputs" / (hashlib.sha1(str((folder / f).resolve()).encode()).hexdigest()[:8] + "_" + f) for f in ("profile.json", "job.json")]  # the inputs staged for the engine
        try:
            env = self.blind_env(lang, False)  # words as they are: the live canvas is where they are edited
            env.pop("OFFEROWL_DECK_SOURCE", None)  # never one the server was started with
            src = self._stage_deck("deck_live")  # the person's own slides, in a copy of the live page's own
            if src:
                env["OFFEROWL_DECK_SOURCE"] = src
            page = resume.deck_page(str(folder / "profile.json"), str(folder / "job.json"), env)  # the HTML
            html = page.read_text(encoding="utf-8")  # as the browser would print it
            return {"html": live_html(html, (self.ws.root,)), "slides": html.count('<section class="slide')}  # for the frame
        except SystemExit as exc:  # the deck's writer stopped: bad data names its project
            text = str(exc)  # its output
            log.warning("live deck of %s failed: %s", job_id, text[-3000:])  # in full, for the log only
            return {"missing": "build_failed", "detail": clean_reason(text)}  # the cleaned reason, never a path
        finally:  # a person's words do not stay in the engine's folder
            for f in [*engine.glob(f"{name}*"), *engine.glob(f"_figures/{name}_*"), *engine.glob(f"_inputs/{name}*"), *inputs]:  # the working copies, by name
                try:
                    f.unlink(missing_ok=True)  # gone
                except OSError as exc:  # a file held open elsewhere: the next page tries again
                    log.info("working copy stays: %s", exc)  # for the log only
            shutil.rmtree(self.ws.job_dir(job_id) / "live", ignore_errors=True)  # and the working folder
            d = self.deck_dir()  # and the live page's copy of the deck source
            if d is not None:
                shutil.rmtree(engine / "_inputs" / (hashlib.sha1(str(d.resolve()).encode()).hexdigest()[:8] + "_deck_live"), ignore_errors=True)

    def resume_figures(self, job_id: str, lang: str, theme: str = "navy") -> dict:
        """The pictures the printed resume carries, for the live canvas: the overview timeline, the hierarchy figure and the
        logo tiles of the companies and schools, drawn by src/overview_figures.py from the same edition profile the PDFs read,
        so the canvas shows the figures the PDF prints. {"stamp": short hash, "files": {name: PNG bytes}} with names "timeline",
        "stack" and "logo_<id>"; no files when they cannot be drawn here (no Node.js or Pillow, or no profile yet). Kept in
        memory until the profile, the draft or the colours change; nothing stays on disk, in the engine's folder or the job's."""
        none = {"stamp": "", "files": {}}  # what the canvas gets when there is nothing to show
        if problems(self.facts_for(job_id).profile()):  # no name, email or role yet: no resume to draw from
            return none
        own = self.own_src(job_id, lang)  # the job's own edition, when the person brought one in
        if own == "own_lang":  # brought in without this language
            return none
        src = own or (self.ws.path("profile", "profile.json") if lang == "ko" or self.profile_lang() == "en" else self.english_for(job_id))  # the profile of this language
        if src is None or not Path(src).is_file() or not shutil.which("node"):  # no profile in this language, or no loader to read it
            return none
        cfg = self.edition_cfg(job_id, lang, theme)  # the edition's choices, as the PDFs use them
        from . import drafts as D  # where a draft is kept
        _, owner = D.load(self, job_id)  # the job's own draft, else the general edition's
        mine = [Path(src)] + ([self.ws.job_dir(owner) / "draft.json"] if owner else [])  # the files the figures are drawn from
        stamp = hashlib.sha1(repr((json.dumps(cfg, sort_keys=True), *[file_hash(f) for f in mine])).encode()).hexdigest()[:12]  # drawn again only when one changes
        where = (job_id, lang, cfg["theme"])  # this document
        with self.live_lock:  # one drawing at a time, as the live deck
            old = self.live_figures.get(where)  # drawn before
            if old and old["stamp"] == stamp:  # nothing changed
                return old
            files = self._draw_resume_figures(job_id, lang, Path(src), cfg)  # drawn now
            got = {"stamp": stamp, "files": files}
            if files:  # only a finished drawing is kept
                self.live_figures[where] = got
            return got

    def _draw_resume_figures(self, job_id: str, lang: str, src: Path, cfg: dict) -> dict:
        """One drawing of the resume's figures, read into memory from a working folder (the job's live/<lang>-figures) and
        working copies in the engine's folder that are all gone again when this returns."""
        import resume  # src/resume.py: the staging rule
        name = f"owl_{self.short(job_id)}_{lang}_livefig"  # its own name: the live deck and the PDFs keep theirs
        work = self.ws.job_dir(job_id) / "live" / f"{lang}-figures"  # the profile and settings it is drawn from, and the pictures
        work.mkdir(parents=True, exist_ok=True)
        write_json(work / "job.json", {**cfg, "out": name})  # the settings under the drawing's name
        self._edition_profile(job_id, src, lang, work)  # the profile as the PDFs have it (draft, pictures, lists)
        engine = ROOT / "output"  # the engine's folder
        staged = []  # the copies rel() puts in the engine's folder
        try:
            prof, job = resume.rel(str(work / "profile.json")), resume.rel(str(work / "job.json"))  # repository-relative, as the build passes them
            staged = [ROOT / prof, ROOT / job]
            env = resume.html_env(self.blind_env(lang, False), OFFEROWL_FIG_THEME=cfg.get("theme") or "navy")  # words as they are, in the edition's colours
            r = subprocess.run([sys.executable, "src/overview_figures.py", prof, name, lang, job], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:  # the canvas goes without its figures; the PDF build reports the same failure
                log.warning("resume figures of %s failed: %s", job_id, (r.stdout + r.stderr)[-2000:])
            suffix = "_en" if lang == "en" else ""  # the English edition's figures are named apart
            files = {}  # name -> the kept picture
            for kind in ("timeline", "stack"):  # the two figures the resume prints
                f = engine / "_figures" / f"{name}_{kind}{suffix}.png"
                if f.is_file():
                    files[kind] = f.read_bytes()
            for f in sorted((engine / "_figures").glob(f"{name}_logo_*.png")):  # one tile per company and school
                files[f.stem[len(name) + 1:]] = f.read_bytes()  # as logo_<id>
            return files
        except (OSError, subprocess.SubprocessError) as exc:  # no figures this time
            log.warning("resume figures of %s failed: %s", job_id, exc)
            return {}
        finally:  # a person's words and pictures do not stay in the engine's folder
            for f in [*engine.glob(f"_figures/{name}_*"), *staged, *engine.glob(f"_inputs/*_{name}*")]:
                try:
                    f.unlink(missing_ok=True)
                except OSError as exc:  # held open elsewhere: the next drawing tries again
                    log.info("working copy stays: %s", exc)
            shutil.rmtree(work, ignore_errors=True)  # and the working folder
            try:
                work.parent.rmdir()  # and live/ itself when nothing else is in it (the live deck empties it the same way)
            except OSError:  # the live deck's folder is there too
                pass

    def draft_stamp(self, job_id: str) -> str:
        """A short hash of the draft a job draws from ("" with none): PDFs made before a new draft are stale."""
        from . import drafts as D  # where a draft is kept
        owner = D.owner(self, job_id)  # the job's own, else the general edition's (decided without parsing them again)
        return file_hash(self.ws.job_dir(owner) / "draft.json") if owner else ""  # the file as it is now

    def _edition_profile(self, job_id: str, src: Path, lang: str, out_dir: Path, compact: int = 0, drop: int = 0) -> None:
        """The profile an edition is typeset from: the facts' profile, with the job's draft in it when there is one. A draft's
        slides are the chapter layout: dividers, and each printed project with its lede, cards and figures."""
        from . import drafts as D  # where a draft is kept
        d, owner = D.load(self, job_id)  # the job's own, else the general edition's (none for a job's own edition: it prints as written)
        if d and lang in ((d.get("_draft") or {}).get("langs") or []):  # written in this language
            prof = D.merged(read_json(src, {}), d)  # the draft's sentences, the facts' names and dates
            if owner == job_id and job_id and not job_id.startswith("-") and (d.get("_draft") or {}).get("posting"):  # written for this posting
                prof.pop("motivationTitle", None)  # its motivation is for this company: the form's own title (지원 동기), not the
                prof.pop("motivationSub", None)  # general edition's name for the person's goals
            cfg = read_json(out_dir / "job.json", {}) or {}  # the edition's settings
            write_json(out_dir / "job.json", {**cfg, "deck": "chapters"})  # the job.json the deck reads
        else:  # no draft
            prof = read_json(src, {})  # as it is
        import draft  # src/draft.py: the person's rules
        style = draft.style_pack(self.style_spec())  # the person's rules
        self._place_pictures(prof)  # pictures named from the workspace's profile/ folder, as the typesetting finds them
        write_json(out_dir / "profile.json", ledger_for_resume(prof, style, compact, drop))  # the lists as a resume prints them
        self._fit_plan_to_edition(out_dir, lang)  # the posting analysis names what this edition has: a draft may rename its competencies

    def _place_pictures(self, prof: dict) -> dict:
        """A profile's pictures named relative to the workspace's profile/ folder (a company's, a school's or a project's logo,
        the portfolio PDF), made absolute in the edition's copy: the typesetting finds them wherever the edition's folder is, and
        the workspace stays whole when it is moved (its pictures live inside it). A path that is absolute, or names no file
        there, is left as it is."""
        base = self.ws.path("profile")  # where a relative picture path starts
        place = lambda p: str((base / p).resolve()) if isinstance(p, str) and p and not Path(p).is_absolute() and (base / p).is_file() else p  # noqa: E731
        holders = list(prof.get("roles") or []) + list(prof.get("education") or [])  # companies and schools
        holders += [x for r in prof.get("roles") or [] if isinstance(r, dict) for x in r.get("projects") or []]  # and projects
        for h in holders:
            if isinstance(h, dict) and isinstance(h.get("logo"), str):
                h["logo"] = place(h["logo"])
        deck = prof.get("deck")  # the portfolio the person made, one for both languages or one each
        if isinstance(deck, dict) and deck.get("pdf"):
            deck["pdf"] = {k: place(v) for k, v in deck["pdf"].items()} if isinstance(deck["pdf"], dict) else place(deck["pdf"])
        return prof

    @staticmethod
    def _fit_plan_to_edition(out_dir: Path, lang: str) -> None:
        """The posting analysis names competencies and skill groups as the profile had them when it was made; a draft written
        after it may name them otherwise (the agent writes a job's own competencies). A name the edition no longer has is left
        out of its job.json: the form stops on an unknown name, which is right for a name a person typed in a job file and
        wrong for one an older analysis gave."""
        cfg = read_json(out_dir / "job.json", {}) or {}  # the edition's settings
        prof = read_json(out_dir / "profile.json", {}) or {}  # the profile it prints
        pick = lambda v: str((v.get(lang) or v.get("ko") or v.get("en") or "") if isinstance(v, dict) else (v or ""))  # noqa: E731  one language's words
        comps = prof.get("competencies") or []  # a list, or one per language
        comps = comps.get(lang) or [] if isinstance(comps, dict) else comps
        names = {pick(c.get("name")) if isinstance(c, dict) else pick(c[0]) if isinstance(c, (list, tuple)) and c else "" for c in comps}  # {name, text} or [name, text]
        cats = {pick(s.get("category")) for s in prof.get("skills") or [] if isinstance(s, dict) and s.get("lang") in (None, "", lang)}  # this edition's skill groups
        changed = False  # job.json is written again only when something went
        for key, have in (("competencyWeak", names), ("competencyDrop", names), ("skillsFocus", cats)):  # the names an analysis gives
            if isinstance(cfg.get(key), list) and any(x not in have for x in cfg[key]):  # one the edition does not have
                cfg[key] = [x for x in cfg[key] if x in have]  # left out
                changed = True
        if changed:
            write_json(out_dir / "job.json", cfg)  # the form reads this


    def _check(self, profile: str, pdf: Path, deck: Path | None, max_pages: int, env: dict | None = None) -> tuple[list, list]:
        """src/check_documents.py on the edition, in the engine's container: (defects, notes to polish). deck is None when a
        blind edition left it out; env is the build's own (a blind edition's check reads its table)."""
        import resume  # its sh() runs the tool where the typesetting runs
        spec = self.style_spec()  # "default" or the person's pack in the workspace
        r = resume.sh(["python3", "src/check_documents.py", resume.rel(profile), resume.rel(str(pdf)), *([resume.rel(str(deck))] if deck else []),  # the document checks, in the render container
                       "--style", spec if spec == "default" else resume.rel(spec), "--max-pages", str(max_pages)], env)  # the pack the documents were written with; a workspace file is staged where the container sees it
        out = (r.stdout or "") + (r.stderr or "")  # their report
        notes = [line.split(":", 1)[1].strip() for line in out.splitlines()  # warnings to polish, in either language
                 if re.match(r"\s*(다듬을 거리|to polish|polish)\s*:", line, re.I)]  # warnings, in either language
        issues = [line.strip()[2:] for line in out.splitlines() if line.strip().startswith("- ")]  # the defects
        if r.returncode != 0 and not issues:  # it failed without a list: say that the check did not run
            log.warning("check failed: %s", out[-2000:])  # the full report for the log
            issues = ["check_failed"]  # the page says the checks did not run
        return issues, notes  # defects and notes

    def _previews(self, pdf: Path, folder: Path, prefix: str, dpi: int, last: int | None = None) -> int:
        """One PNG per page (r-1.png, d-1.png ...) for the canvas's typeset view, up to page `last` when it is given (a job's
        long materials show their start). Returns the number of pages."""
        folder.mkdir(parents=True, exist_ok=True)  # the edition's preview folder
        for old in folder.glob(f"{prefix}-*.png"):  # the last edition's pages go
            old.unlink()  # pages of an older edition
        import pdftools  # the page pictures, with poppler or PDFium
        if pdftools.reader():  # either reader on this PC: no container needed
            pages = pdftools.render_png(pdf, folder / prefix, dpi=dpi, last=last)  # named <prefix>-1.png ...
        else:  # the engine's container has poppler
            import resume
            tmp = ROOT / "output" / "_panel_preview"  # inside the repository, which the container sees
            shutil.rmtree(tmp, ignore_errors=True)  # a clean folder the container can see
            tmp.mkdir(parents=True)  # inside the repository
            shutil.copyfile(pdf, tmp / "in.pdf")  # the PDF where the container finds it
            resume.sh(["pdftoppm", "-r", str(dpi), *(["-l", str(last)] if last else []), "-png",  # the page range, when there is one
                       resume.rel(str(tmp / "in.pdf")), resume.rel(str(tmp / prefix))])  # drawn by the container's poppler
            for f in tmp.glob(f"{prefix}-*.png"):  # the pictures it drew
                shutil.move(str(f), folder / f.name)  # into the edition's preview folder
            shutil.rmtree(tmp, ignore_errors=True)  # nothing left behind
            pages = sorted(folder.glob(f"{prefix}-*.png"), key=lambda p: int(re.search(r"-(\d+)\.png$", p.name).group(1)))  # in page order, not name order
            pages = [p.rename(folder / f"{prefix}-{i}.png") for i, p in enumerate(pages, 1)]  # pdftoppm pads the number by the page count (r-01.png): one name for all
        return len(pages)  # how many pages

    # ------------------------------------------------------------------ the cover letter and the interview kit

    @staticmethod
    def cover_available() -> bool:
        """The cover letter module (src/cover.py) is there."""
        return (ROOT / "src" / "cover.py").is_file()  # the module is optional: without it there is no cover letter step

    def _cover(self, job_id: str, lang: str, out_dir: Path, render: bool = True, write: bool = True) -> dict | None:
        """The cover letter of this edition, and nothing of it left in the engine's folder, whichever way it ends."""
        try:
            return self._write_cover(job_id, lang, out_dir, render, write)  # the letter
        finally:  # a tailoring that stops here has no typesetting after it to clean up
            self._clean_engine(job_id, lang, out_dir)  # a person's words do not stay there

    def _write_cover(self, job_id: str, lang: str, out_dir: Path, render: bool, write: bool) -> dict | None:
        """The cover letter of this edition through src/cover.py's own steps (plan and draft when write, then build and
        check when the typesetting can run), called in this process. Drafting needs the agent. write=False, and a PC
        with no agent, typeset the letter that is already there, so a letter the person reviewed is never replaced by
        making its PDF. A new letter is written beside the old one and takes its place only when it has sentences, so an
        agent that stops part way never costs the person the letter they had. Returns {state, pages, issues}, or None
        when src/cover.py is missing."""
        if not self.cover_available():  # no module: nothing to show
            return None  # no cover letter step without the module
        import cover  # src/cover.py
        cdir = out_dir / "cover"  # the letter's own files
        profile, posting = str(out_dir / "profile.json"), str(self.ws.job_dir(job_id) / "posting.md")  # its inputs
        with self.model_lock:  # drafting asks the model (cover.py reads the company and role from the posting itself)
            backend = self.backend() if write else "none"  # which agent; none when only the typesetting was asked for
            written = (cdir / "cover.json").is_file()  # a letter from an earlier tailoring
            if backend == "none" and not written:  # nothing to typeset and nobody to write it
                return {"state": "needs_agent" if self.card.chosen() == "none" else "not_written"}  # the page offers the agent, or tailoring
            job = {"out": "owl_cover_" + self.short(job_id) + "_" + lang, "lang": lang,  # its own output name, apart from the resume's
                   "theme": read_json(out_dir / "job.json", {}).get("theme", "navy")}  # the letter's render settings, this edition's theme
            if backend != "none":  # a new letter, written beside the old one
                work = out_dir / "cover.new"  # where the new letter is written
                shutil.rmtree(work, ignore_errors=True)  # a try that stopped before leaves nothing to mix in
                work.mkdir(parents=True)  # a fresh folder
                for st in (["plan", profile, posting, "-o", str(work / "plan.json"), "--backend", backend, "--lang", lang],  # the posting's duties to evidence
                           ["draft", profile, str(work / "plan.json"), "-o", str(work / "cover.json"), "--backend", backend]):  # paragraphs with evidence ids
                    if self._cover_step(cover, job_id, st) not in (0, 1):  # it stopped: the draft did not come out whole
                        break  # the draft cannot go on
                if not letter_sentences(work / "cover.json"):  # no sentence came back: the agent stopped, or answered nothing usable
                    shutil.rmtree(work, ignore_errors=True)  # the empty skeleton goes; the old letter stays as it was
                    return {"state": "failed", "error": "agent_stopped"}  # the page offers to try again
                shutil.rmtree(cdir, ignore_errors=True)  # the old letter goes now that a new one stands
                retried(work.rename, cdir)  # the new one takes its place
            cdir.mkdir(parents=True, exist_ok=True)  # the letter's folder
            write_json(cdir / "job.json", job)  # cover.py's build reads it
            steps = []  # the typesetting steps of this run
            for f in ("cover.pdf", "cover.docx", "check.json"):  # what an earlier typesetting left
                (cdir / f).unlink(missing_ok=True)  # a failed run must not show the old pages as new
            if render and not self.engine_ready():  # the typesetting can run here
                steps += [["build", profile, str(cdir / "cover.json"), "--job", str(cdir / "job.json")],  # DOCX and PDF
                          ["check", profile, str(cdir / "cover.json"), "--pdf", str(cdir / "cover.pdf"), "--json", str(cdir / "check.json")]]  # its checks
            for st in steps:  # in order, as cover.py's own run command does
                rc = self._cover_step(cover, job_id, st)  # one step
                if rc not in (0, 1) or (st[0] != "check" and rc == 2):  # the same rule as cover.py run
                    break  # later steps cannot go on
        if not (cdir / "cover.json").is_file():  # no draft came out
            return {"state": "failed"}  # the page says it was not made
        pdf = cdir / "cover.pdf"  # where its build writes
        if not pdf.is_file():  # drafted, not typeset (no typesetting here)
            return {"state": "drafted", "pages": 0, "issues": []}  # the canvas still shows the letter
        shutil.copyfile(pdf, out_dir / "cover.pdf")  # beside the resume
        if (cdir / "cover.docx").is_file():  # the Word copy, when one was written
            shutil.copyfile(cdir / "cover.docx", out_dir / "cover.docx")  # beside the PDF too
        n = self._previews(out_dir / "cover.pdf", out_dir / "preview", "c", 110)  # its pages
        chk = read_json(cdir / "check.json", {})  # {ok, checks: [{key, status, detail}]}
        issues = [f"{c.get('key')}: {c.get('detail') or ''}".strip(": ") for c in chk.get("checks") or [] if c.get("status") == "fail"]  # the checks that failed, as short lines
        if not (cdir / "check.json").is_file():  # typeset, but its checks never ran (a step stopped): never treated as passed
            issues = ["check_failed"]
        return {"state": "done", "pages": n, "issues": issues}  # shown under the resume's result

    @staticmethod
    def _cover_step(cover, job_id: str, argv: list) -> int:
        """One of src/cover.py's steps, in this process: its exit code, 2 when it stopped or broke."""
        try:
            return cover.main(argv)  # the command line's entry
        except SystemExit as exc:  # a step that stops with a message
            log.info("cover %s %s stopped: %s", job_id, argv[0], exc)  # for the log only
            return 2  # treated as a stop
        except Exception:  # a bug in a step: logged, the letter is not made
            log.exception("cover %s %s failed", job_id, argv[0])  # the trace for the log
            return 2  # treated as a stop

    # ------------------------------------------------------------------ tailoring, the interview kit, regeneration

    def edition_inputs(self, job_id: str, lang: str, theme: str = "navy", max_pages: int = 3) -> Path | str:
        """Write an edition's profile.json and job.json (what the typesetting and the cover letter read). Returns the
        edition's folder, or an error code: a name or email missing, or the English profile not made."""
        bad = problems(self.facts_for(job_id).profile())  # what stops a resume
        if bad:  # a name, an email or a job is missing
            return bad[0]  # the band names the first one
        own = self.own_src(job_id, lang)  # the job's own edition, when the person brought one in
        if own == "own_lang":  # brought in without this language
            return "own_lang"
        src = own or (self.ws.path("profile", "profile.json") if lang == "ko" or self.profile_lang() == "en" else self.english_for(job_id))  # the profile of this language
        if src is None:  # no English profile of this profile yet
            return "needs_translation"  # the band offers to translate
        out_dir = self.build_dir(job_id, lang)  # where this edition goes
        out_dir.mkdir(parents=True, exist_ok=True)  # jobs/<job>/resume/<lang>/
        name = "owl_" + self.short(job_id) + "_" + lang  # the engine's output name
        cfg = {"out": name, "maxPages": max_pages, **self.edition_cfg(job_id, lang, theme)}  # job.json: what resume_form.js and deck_slides.js read
        write_json(out_dir / "job.json", cfg)  # kept with the edition
        self._edition_profile(job_id, src, lang, out_dir)  # the profile it was made from (the lock freezes it too)
        return out_dir  # ready for the cover letter and the typesetting

    def tailor(self, job_id: str, lang: str, theme: str, max_pages: int, with_cover: bool = True, typeset: bool = False) -> bool:
        """One action for a job: the resume ordered for it, the cover letter drafted from the same plan, and the
        interview kit's question map (task "tailor:<job>"). `typeset` also makes the PDFs when the typesetting can run."""
        return self.start(f"tailor:{job_id}", self._tailor, job_id, lang, theme, max_pages, with_cover, typeset)  # one per job at a time

    def _tailor(self, job_id: str, lang: str, theme: str, max_pages: int, with_cover: bool, typeset: bool) -> None:
        key = f"tailor:{job_id}"  # this task
        parts = {"resume": "running", "cover": "waiting" if with_cover else "skipped", "interview": "waiting"}  # each document's state
        self._set(key, step="analysis", parts=dict(parts))  # the page shows the three parts
        self._analyze(job_id)  # the resume's order for this job (the agent, else the words); its own task record says how
        self._set(key, step="writing_resume", parts=dict(parts))  # the step the page shows
        wrote = self._write(job_id, lang)  # its sentences for this job, when an agent is on
        parts["resume"] = "failed" if wrote["state"] == "failed" else "done"  # with no agent the canvas still follows the plan
        out = self.edition_inputs(job_id, lang, theme, max_pages)  # the edition's inputs
        if isinstance(out, str):  # a name, an email or the translation is missing
            parts.update(cover="blocked" if with_cover else "skipped", interview="blocked")  # the other two need a resume
            self._set(key, state="error", step="", parts=parts, error={"code": out})  # the band names the fix
            return  # nothing else to do
        if typeset and not self.engine_ready():  # the PDFs too, where the typesetting can run
            self._set(key, step="typesetting_resume", parts=dict(parts))  # the step the page shows
            self._build(job_id, lang, theme, max_pages, with_cover, write_cover=True)  # the existing build (its own task record keeps the details)
            built = read_json(self.build_dir(job_id, lang) / "build.json", {})  # what it made
            parts["cover"] = ((built.get("cover") or {}).get("state") or "failed") if with_cover and not built.get("blind") else "skipped"  # the letter came with it; a blind edition has none
        elif with_cover:  # the letter drafted without typesetting
            self._set(key, step="writing_cover", parts=dict(parts))  # the step the page shows
            got = self._cover(job_id, lang, out, render=False)  # plan and draft (the agent writes it)
            parts["cover"] = (got or {}).get("state", "unavailable")  # drafted, needs_agent or failed
        self._set(key, step="interview_kit", parts=dict(parts))  # the step the page shows
        try:
            rows = self.ensure_kit(job_id, lang)  # the question map, without a model
            parts["interview"] = "done"  # the studio can open
            drafted, stopped = 0, False  # scenes the agent wrote, and whether it stopped
            if self.card.chosen() != "none" and rows:  # an agent is on: a few scripts for the likeliest questions
                drafted, stopped = self._draft_scenes(job_id)  # at most five, checked before anyone reads them
                rows = self.ensure_kit(job_id, lang)  # the map again: it now holds the agent's expected questions and sees its drafts
            result_iv = {"questions": len(rows), "drafted": drafted, "stopped": stopped}  # for the page
        except Exception:  # the kit could not be made: the rest still stands
            log.exception("interview kit for %s failed", job_id)  # the trace for the log
            parts["interview"], result_iv = "failed", {}  # the page says so
        stops = [k for k, v in parts.items() if v == "failed"] + (["scripts"] if result_iv.get("stopped") else [])  # what the agent did not finish
        self._set(key, state="done", step="", parts=parts, result={"interview": result_iv, "stopped": stops})  # all three answered, and what to try again

    REGEN_WAYS = {  # a direction the person picks with one press, never types: how the rewrite should change the sentence
        "shorter": "Make it clearly shorter: keep the action and the change, drop the rest.",
        "plainer": "Use plainer, everyday words a recruiter outside the field reads at once.",
        "result": "Lead with what changed as a result, then what was done to get there.",
    }

    def regen(self, sid: str, lang: str = "ko", job: str | None = None, way: str = "") -> bool:
        """New words for one sentence from its evidence alone (task "regen:<sentence>"), in a direction the person picked."""
        return self.start(f"regen:{sid}", self._regen, sid, lang, job, way if way in self.REGEN_WAYS else "")  # one per sentence at a time

    def _regen(self, sid: str, lang: str, job: str | None = None, way: str = "") -> None:
        import draft  # src/draft.py: the checks every suggestion passes
        import llm  # src/llm.py: the one door to a model
        from . import documents  # the resume model and the edit path
        key = f"regen:{sid}"  # this task
        R = documents.model(self, lang, job)  # the sentences now
        rec = R.sent.get(sid)  # this sentence
        if not rec:  # a stale page
            self._set(key, state="error", error={"code": "bad_request"})  # refused
            return  # nothing else to do
        if rec.get("locked"):  # a locked sentence keeps its words
            self._set(key, state="error", error={"code": "locked"})  # the page says to unlock it first
            return  # nothing else to do
        ev = R.evidence_text(sid) or "\n".join(e.get("quote", "") for e in rec.get("evidence") or [])  # what it may say
        if not ev.strip():  # nothing to write from
            self._set(key, state="error", error={"code": "no_evidence"})  # the page says so
            return  # nothing else to do
        words = "Korean" if lang == "ko" else "English"  # the sentence's language
        limit = max(40, int(len(rec["text"]) * 0.7)) if way == "shorter" else max(60, min(200, len(rec["text"]) + 40))  # shorter when asked, else about as long as it is now
        prompt = (f"Evidence:\n<<<\n{ev[:6000]}\n>>>\n\nRewrite this resume sentence in {words} using only facts from the evidence. "  # the task
                  f"One sentence, under {limit} characters, plain past tense, what was done and what changed. At most one short "
                  f"result phrase in ==double equals==. Never add numbers, tools, products, clients or results that are not in the evidence.\n"
                  + (f"{self.REGEN_WAYS[way]}\n" if way else "")  # the direction the person picked
                  + f"Sentence now: {rec['text']}\n"
                  'Return JSON: {"text": "..."}')  # the answer's shape
        with self.model_lock:  # one model task at a time
            backend = self.backend()  # which agent
            if backend == "none":  # no agent: said plainly
                self._set(key, state="error", error={"code": "agent_unavailable"})  # the band offers to turn the agent on
                return  # nothing else to do
            self._set(key, step="asking_agent")  # the step the page shows
            try:
                out = llm.run("panel-regenerate", prompt, system=draft.SYSTEM, want_json=True, required=("text",), backend=backend, timeout=180)  # one small call
            except llm.LLMUnavailable:  # the agent did not answer
                self._set(key, state="error", error={"code": "agent_unavailable"})  # the same band as with no agent
                return  # nothing else to do
            except ValueError:  # the answer never had the right form
                self._set(key, state="error", error={"code": "agent_stopped"})  # the page offers to try again
                return  # nothing else to do
        new = str((out or {}).get("text") or "").strip()  # the proposal
        why = draft.check_text(new, ev, style=draft.style_pack(self.style_spec()), max_len=limit + 20, highlight=(0, 1), lang=lang)  # numbers, names, style, length
        if why:  # it said something the evidence does not
            from .evidence import issue_codes  # the page's codes
            self._set(key, state="error", error={"code": "regen_rejected", "issues": issue_codes([w for w in why if ":" in w])})  # what stopped it
            return  # the sentence stays as it was
        documents.edit_sentence(self, sid, new, lang, job)  # saved as an edit: one undo step, and the evidence check runs again
        self._set(key, state="done", step="", result={"text": new})  # the page shows the new words

    # ------------------------------------------------------------------ export and lock
