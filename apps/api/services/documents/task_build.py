"""Tasks' part for the typeset documents (apps/api/tasks.py inherits it): the documents service's builds. Whether the
typesetting can run here and its libraries, an edition's PDFs made from its profile and settings (the resume, the deck and
the cover letter, a blind edition with its bars), the checks they are held to, their page pictures, and the live deck and
figures the canvas draws. Nothing of a person's words stays in the engine's folder.

The profile's own files are named by the profile (Facts.profile_file, english_file, photo_paths, blind_path), a job's
posting and plan by the applications (posting_file, plan_of), and whether a job has an interview kit by the interview.
"""
from __future__ import annotations

import base64  # the live deck's pictures
import hashlib  # build names and profile hashes
import html as htmlmod  # a picture's path, escaped in its attribute
import json  # files
import logging  # the panel's log
import mimetypes  # a picture's type, by its name
import os  # environment for the engine
import re  # parsing engine output
import shutil  # copies and tool lookup
import subprocess  # previews and the figures
import sys  # the engine on the import path
import threading  # the locks of the rendering and the live pages
import time  # when an edition was made
from pathlib import Path  # paths

from .. import applications, interview  # a job's posting and plan; whether it has an interview kit
from ...core.stamps import content_hash, file_hash  # noqa: E402  an edition's record of what it was made from
from ...core.workspace import read_json, retried, write_json  # noqa: E402  files
from ..profile import problems  # noqa: E402  what stops a resume (the profile's)

ROOT = Path(__file__).resolve().parents[4]  # the repository (or the app's bundle)
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules
log = logging.getLogger("offerowl.panel")  # the panel's log

THEMES = ("navy", "teal", "mono", "wine", "forest", "slate", "crimson")  # src/themes.json's packs

FORMS = ("detailed", "compact", "table")  # the resume's forms (src/resume_form.js)

DECK_STYLES = ("classic", "clean")  # the deck's looks (src/portfolio/style_clean.css)

LANGS = ("ko", "en")  # the editions

LIVE = "live"  # a job's working folder of the live canvas (jobs/<job>/live): made and emptied by each live page, so a backup leaves it out

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

def build_error(text: str, lang: str) -> dict:
    """A failed typesetting's error for the page. An English edition whose profile lacks a field's English (node names it:
    "summary.intro has no en text") is needs_translation, whose band offers the translation; anything else is build_failed.
    The detail is the tool's own reason without paths or commands, "" when none is left."""
    detail = clean_reason(text)  # node's thrown message, cleaned
    code = "needs_translation" if lang == "en" and re.search(r"언어|\ben\b", detail) else "build_failed"  # an English text missing, said as the band that fixes it
    return {"code": code, "detail": detail}  # what the page draws

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
    out = re.sub(r"<script\b[^>]*>.*?</script\b[^>]*>", "", out, flags=re.S | re.I)  # the frame runs nothing: scripts with their code,
    out = re.sub(r"<script\b[^>]*>", "", out, flags=re.I)  # and a script tag left open
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


class Builds:
    """An edition's typeset files and the canvas's live pages: the engine, the build, the checks, the pictures, the letter."""

    def __init__(self):
        super().__init__()  # the other parts' own
        self.render_lock = threading.RLock()  # one rendering at a time: it is the heavy part. Re-entrant: a failed build cleans up while it holds it
        self.live_lock = threading.Lock()  # one live deck at a time, which also makes a second request wait for the first one's answer
        self.live_decks: dict[tuple, dict] = {}  # (job, language, colours) -> the last live page and what it was made from
        self.live_figures: dict[tuple, dict] = {}  # (job, language, colours) -> the resume's figures for the canvas and what they were drawn from

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
        files = sorted(p for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")  # every file of it but
        # the bytecode Python leaves beside a deck's own tools when they run: a check run is no change to the slides (it marked
        # every edition's deck stale again after each run)
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

    def corners(self) -> str:
        """The corners the figures, the logo tiles and the built-in deck are drawn with: "square" when the person's setting
        `corners` says so, else "round", as the documents always had them."""
        return "square" if self.card.settings_fn().get("corners") == "square" else "round"  # absent or "round" alike

    def blind_env(self, lang: str, on: bool) -> dict:
        """The environment of one edition's typesetting: this process's without any blind switch it was started with, and for a
        blind edition its own (OFFEROWL_BLIND, its language, and the person's table staged where the typesetting reads it,
        OFFEROWL_BLIND_TABLE). OFFEROWL_CORNERS=square when the person's setting asks for square corners, and never from the
        server's own environment. Every build gets a copy of its own, so one edition's switches never reach another's and the
        server's own environment is never changed."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_BLIND") and k != "OFFEROWL_CORNERS"}  # no switch carried over from the start
        if self.corners() == "square":  # the setting, for every step that draws (src/corners.py and src/corners.js read it)
            env["OFFEROWL_CORNERS"] = "square"
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

    def look(self) -> dict:
        """The form and the deck's look chosen in the panel, as job.json names them."""
        s = self.card.settings_fn()  # the saved choices
        return {"form": s.get("form") if s.get("form") in FORMS else FORMS[0], "deckStyle": s.get("deck_style") if s.get("deck_style") in DECK_STYLES else DECK_STYLES[0]}  # the first of each is the default

    def edition_cfg(self, job_id: str | None, lang: str, theme: str) -> dict:
        """What resume_form.js and deck_slides.js read for an edition (its job.json, without the output name, the page limit
        and the photo). A job drafted from the profile takes the posting analysis's order and focus; a job's own edition
        keeps its own order and adds the layout choices it was made with."""
        own = self.own_dir(job_id) is not None  # the person's own edition prints as made
        plan = {} if own or not job_id else applications.plan_of(self.ws, job_id)  # the posting analysis, if any (the applications service's plan)
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
        src = own or self.facts.profile_file()  # the job's own, or the Korean profile
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
        # the inputs the edition's PDF was made from, as they are before this build writes its own: a build that fails puts
        # them back, so the PDF on screen never stands beside the profile of a build that did not happen (a page-fitting
        # loop leaves a shortened one), which the lock and the live deck read
        kept = {f: (out_dir / f).read_bytes() for f in ("profile.json", "job.json") if (out_dir / f).is_file()}
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
        with self.turn(key, self.render_lock):  # one rendering at a time, said on the page while it waits
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
                twin = None  # a blind edition's ordinary twin, for its layout check (task_compare.py)
                if blind and not mine:  # the resume Offerowl typeset with bars, and the deck it drew with them
                    twin_env = {**self.blind_env(lang, False), **({"OFFEROWL_DECK_SOURCE": deck_src} if deck_src else {})}  # no bars, the same deck source
                    self._set(key, step="checking")  # the step the page shows: the twin is made for the check
                    twin = self.blind_twin(out_dir, name, twin_env, deck is not None)
            except (SystemExit, Exception) as exc:  # resume.py stops with the tool's output; anything else (a file the system refused, a timeout) ends the build the same way
                text = str(exc)  # the tool's output, or the error's own words
                if isinstance(exc, SystemExit):  # the tool said why
                    log.warning("build %s failed: %s", job_id, text[-3000:])  # in full, for the log only
                else:  # a fault of its own: the trace for the log
                    log.exception("build %s failed", job_id)
                self._set(key, state="error", error=build_error(text, lang))  # the cleaned reason, never a path
                self._clean_engine(job_id, lang, out_dir)  # a failed build leaves nothing behind either (it reads the attempt's profile for the staged logos)
                self._restore_inputs(out_dir, kept)  # and the edition's inputs are the ones its PDF was made from again
                return  # nothing else to do
            self._set(key, step="checking")  # the step the page shows
            # the document checks; a resume the person made is theirs as it is: its pages are shown, not measured against the profile.
            # A resume the person wrote prints whole (it is never shortened to fit), so its own length is never over the limit: the
            # panel's limit (three by default) made a six-page edition brought in fail its checks when it was made again, and its
            # export was refused with nothing the person could change
            limit = max_pages if own is None else max(max_pages, pdfmeta.pages(pdf))
            issues, notes = ([], ["own_file"]) if mine else self._check(str(out_dir / "profile.json"), pdf, deck, limit, env)
            checks, polish = ([], []) if mine else self.read_checks(pdf)  # the same findings with their codes, for the panel's own words
            cross = None if mine else self.cross_checks(job_id, lang, out_dir, name, Path(pdf), Path(str(deck)) if deck else None, env, twin)  # its other language, its deck, its twin
            if cross:  # what they found joins the edition's own findings
                issues, notes, checks, polish = issues + cross["issues"], notes + cross["notes"], checks + cross["checks"], polish + cross["polish"]
            if deck and from_source and deck_src:  # a deck written from the person's source: the checks that source ships, on this deck
                more = self._deck_tools(Path(str(deck)), deck_src, env)
                issues += [x["text"] for x in more]  # the deck's issues: they keep the documents home as its own checks would
                checks += more  # with their codes, for the panel
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
                "at": time.strftime("%Y-%m-%d %H:%M"), "profile": content_hash(self.facts.profile_file()),  # when, and from which profile's content (stale editions are marked)
                "own": self.own_stamp(job_id),  # and from which own edition or files, when the job has them
                "maxPages": max_pages, "cover": cover, "draft": self.draft_stamp(job_id),  # what the panel shows; the draft it was made from
                "checks": checks, "polish": polish}  # the findings with their codes: the panel words them in the person's language
        changes = self.compare_baseline(job_id, lang, out_dir, hashes, blind)  # the pages changed since the copy that last went out (task_compare.py)
        if changes is not None:  # the edition has a baseline
            info["changes"] = changes
        from .task_compare import MATCHED  # beside the record, out of the state the panel polls
        if blind and cross and cross.get("matched") is not None:  # the patterns this blind edition's words took, for the next one's check
            write_json(out_dir / MATCHED, cross["matched"])
        else:  # an ordinary edition, or one whose twin was not checked, took none
            (out_dir / MATCHED).unlink(missing_ok=True)
        if blind:  # a blind edition says so, and which table its bars came from (another table makes it stale)
            info.update(blind=True, blind_table=self.blind_stamp())
        if deck and from_source:  # its deck was written from the person's deck source: which one (another makes it stale)
            info["deck_src"] = self.deck_stamp()
        write_json(out_dir / "build.json", info)  # kept with the edition
        self._clean_engine(job_id, lang, out_dir)  # the edition has its own copies now
        if not blind and interview.has_kit(self.ws, job_id):  # a kit made before these PDFs (a blind deck's bars would hide its words from the kit)
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

    @staticmethod
    def _restore_inputs(out_dir: Path, kept: dict) -> None:
        """An edition's profile.json and job.json put back as they were before a build that failed: written again from the
        bytes kept, or taken away when the edition had none (its first build failed)."""
        for f in ("profile.json", "job.json"):  # what a build writes before it typesets
            try:
                if f in kept:  # there before: its old bytes again
                    (out_dir / f).write_bytes(kept[f])
                else:  # this build wrote the first one: none again
                    (out_dir / f).unlink(missing_ok=True)
            except OSError as exc:  # a file held open elsewhere: the next build writes it again
                log.info("edition input not restored: %s", exc)  # for the log only

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
        for f in self.photo_paths():  # the photo's staged copy: a face does not stay in the engine's folder
            found.append(out / "_inputs" / (hashlib.sha1(str(f.resolve()).encode()).hexdigest()[:8] + "_" + f.name))  # named as resume.rel names it
        prof = read_json(out_dir / "profile.json", {})  # the logo pictures the profile names were staged beside it (resume.stage_logos)
        for h in [*(prof.get("roles") or []), *(prof.get("education") or []), *[p for r in prof.get("roles") or [] if isinstance(r, dict) for p in r.get("projects") or []]]:
            lg = h.get("logo") if isinstance(h, dict) else None
            if isinstance(lg, str) and lg and Path(lg).is_absolute():  # a picture outside the engine's folder: its staged copy goes
                found.append(out / "_inputs" / (hashlib.sha1(str(Path(lg).resolve()).encode()).hexdigest()[:8] + "_" + re.sub(r"[^\w가-힣.-]", "_", Path(lg).name)))
        for src in (out_dir / "profile.json", out_dir / "job.json", out_dir / "cover" / "cover.json", out_dir / "cover" / "plan.json", out_dir / "cover" / "job.json",  # the inputs staged for the container
                    self.blind_path()):  # and the person's mask table, staged for a blind edition: their names do not stay there either
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
        leaves nothing in the engine's folder. The answer is kept until the profile, the draft, the colours or the corners change."""
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
        src = own or (self.facts.profile_file() if lang == "ko" or self.profile_lang() == "en" else self.english_for(job_id))  # the profile of this language
        if src is None:  # no English profile of this profile yet
            return {"missing": "needs_translation"}  # the page offers to translate
        cfg = self.edition_cfg(job_id, lang, theme)  # what deck_slides.js reads, as the PDFs use it
        from . import drafts as D  # where a draft is kept
        _, owner = D.load(self, job_id)  # the job's own draft, else the general edition's
        mine = [src] + ([self.ws.job_dir(owner) / "draft.json"] if owner else [])  # the files the page is made from
        stamp = (json.dumps(cfg, sort_keys=True), *[file_hash(f) for f in mine], self.deck_stamp(), self.corners())  # the page is made again only when one of these changes (or the deck source, or the corners)
        where = (job_id, lang, cfg["theme"])  # this document
        with self.live_lock:  # one at a time; a request that waited finds the page made
            old = self.live_decks.get(where)  # the page already made
            if old and old["stamp"] == stamp:  # nothing changed
                return old["page"]  # answered at once
            page = self._make_live_deck(job_id, lang, src, cfg)  # made now
            if "html" in page:  # only a finished page is kept
                self.live_decks[where] = {"stamp": stamp, "page": page}  # for the next request
            return page

    def forget_live(self, job_id: str | None = None) -> None:
        """The live pages and pictures kept in memory, of one job (deleted for good) or of every job (a backup restored in
        the workspace's place)."""
        for memo in (self.live_decks, self.live_figures):  # the canvas's deck pages and the resume's pictures
            if job_id is None:  # every job's
                memo.clear()
            else:  # one job's, in every language and colour
                for k in [k for k in list(memo) if k[0] == job_id]:
                    memo.pop(k, None)

    def _make_live_deck(self, job_id: str, lang: str, src: Path, cfg: dict) -> dict:
        """One live page, from a working folder that is gone again when this returns."""
        import resume  # src/resume.py: the pipeline
        short = self.short(job_id)  # the name part an edition's outputs share
        name = f"owl_{short}_{lang}_live"  # the printing edition's files keep their own names
        folder = self.ws.job_dir(job_id) / LIVE / lang  # the working folder
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
            shutil.rmtree(self.ws.job_dir(job_id) / LIVE, ignore_errors=True)  # and the working folder
            d = self.deck_dir()  # and the live page's copy of the deck source
            if d is not None:
                shutil.rmtree(engine / "_inputs" / (hashlib.sha1(str(d.resolve()).encode()).hexdigest()[:8] + "_deck_live"), ignore_errors=True)

    def resume_figures(self, job_id: str, lang: str, theme: str = "navy") -> dict:
        """The pictures the printed resume carries, for the live canvas: the overview timeline, the hierarchy figure and the
        logo tiles of the companies and schools, drawn by src/overview_figures.py from the same edition profile the PDFs read,
        so the canvas shows the figures the PDF prints. {"stamp": short hash, "files": {name: PNG bytes}} with names "timeline",
        "stack" and "logo_<id>"; no files when they cannot be drawn here (no Node.js or Pillow, or no profile yet). Kept in
        memory until the profile, the draft, the colours or the corners change; nothing stays on disk, in the engine's folder or the job's."""
        none = {"stamp": "", "files": {}}  # what the canvas gets when there is nothing to show
        if problems(self.facts_for(job_id).profile()):  # no name, email or role yet: no resume to draw from
            return none
        own = self.own_src(job_id, lang)  # the job's own edition, when the person brought one in
        if own == "own_lang":  # brought in without this language
            return none
        src = own or (self.facts.profile_file() if lang == "ko" or self.profile_lang() == "en" else self.english_for(job_id))  # the profile of this language
        if src is None or not Path(src).is_file() or not shutil.which("node"):  # no profile in this language, or no loader to read it
            return none
        cfg = self.edition_cfg(job_id, lang, theme)  # the edition's choices, as the PDFs use them
        from . import drafts as D  # where a draft is kept
        _, owner = D.load(self, job_id)  # the job's own draft, else the general edition's
        mine = [Path(src)] + ([self.ws.job_dir(owner) / "draft.json"] if owner else [])  # the files the figures are drawn from
        stamp = hashlib.sha1(repr((json.dumps(cfg, sort_keys=True), *[file_hash(f) for f in mine], self.corners())).encode()).hexdigest()[:12]  # drawn again only when one changes, or the corners
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
        work = self.ws.job_dir(job_id) / LIVE / f"{lang}-figures"  # the profile and settings it is drawn from, and the pictures
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
        blind edition left it out; env is the build's own (a blind edition's check reads its table). The edition is the job whose
        folder holds the profile (jobs/<job>/resume/<lang>/): a general one (its id starts with a dash) is held to the shared
        phrases, an application's to the rules for one posting."""
        import resume  # its sh() runs the tool where the typesetting runs
        spec = self.style_spec()  # "default" or the person's pack in the workspace
        report = self.check_report(pdf)  # the defects with their codes, written beside the engine's PDF where the container writes too
        report.unlink(missing_ok=True)  # never an older build's
        ledger = self.stage_ledger(pdf)  # the person's profile, which the edition is held to (docs/WRITING.md "The edition against the profile")
        where = Path(profile).resolve().parent.parent  # jobs/<job>/resume, for an edition's own profile
        general = where.name != "resume" or where.parent.name.startswith("-")  # a general edition (the profile's own, or a named one), or none to say
        # its words in the edition's language: a line the panel cannot word from its code (a layout check, the measurement of a
        # slide) is shown as written, and the container's own locale would write it in English under a Korean edition
        env = {**(env or os.environ), "OFFEROWL_LANG": "en" if Path(str(pdf)).stem.endswith("_en") else "ko"}
        table = self.blind_file()  # the person's table: its never-shown names never go inside a highlight either
        if table:  # staged where the container reads it (resume.rel); _clean_engine takes the copy away with the others
            env["OFFEROWL_HIGHLIGHT_TABLE"] = resume.rel(str(table))
        try:
            r = resume.sh(["python3", "src/check_documents.py", resume.rel(profile), resume.rel(str(pdf)), *([resume.rel(str(deck))] if deck else []),  # the document checks, in the render container
                           "--style", spec if spec == "default" else resume.rel(spec), "--max-pages", str(max_pages), "--report", resume.rel(str(report)),  # the pack the documents were written with; a workspace file is staged where the container sees it
                           *(["--ledger", resume.rel(str(ledger))] if ledger else []), "--edition", "general" if general else "job"], env)  # the facts it is held to, and what kind of edition it is
        finally:  # the copy of the person's profile never stays in the engine's folder
            if ledger:
                ledger.unlink(missing_ok=True)
        out = (r.stdout or "") + (r.stderr or "")  # their report
        notes = [line.split(":", 1)[1].strip() for line in out.splitlines()  # warnings to polish, in either language
                 if re.match(r"\s*(다듬을 거리|to polish|polish)\s*:", line, re.I)]  # warnings, in either language
        issues = [line.strip()[2:] for line in out.splitlines() if line.strip().startswith("- ")]  # the defects
        if r.returncode != 0 and not issues:  # it failed without a list: say that the check did not run
            log.warning("check failed: %s", out[-2000:])  # the full report for the log
            issues = ["check_failed"]  # the page says the checks did not run
        return issues, notes  # defects and notes

    DECK_TOOLS = (("check_deck", "pdf"), ("check_align", "html"), ("check_density", "html"), ("check_contrast", "html"))  # a deck source's own checks, and what each reads

    def _deck_tools(self, deck: Path, deck_src: str, env: dict | None) -> list:
        """The checks a person's deck source ships in its tools/ folder (check_deck.py on the PDF and its .probe.json,
        check_align.py, check_density.py and check_contrast.py on the page), run on this build's deck before its working
        files are cleaned. Each one that fails gives its lines as the deck's issues; one that cannot run says so."""
        import resume  # its sh() runs a tool where the typesetting runs
        import check_documents as CD  # the findings worded as every other check's
        page = deck.with_suffix(".html")  # the page the deck was printed from, beside it
        out = []
        for tool, reads in self.DECK_TOOLS:
            script = ROOT / deck_src / "tools" / f"{tool}.py"  # in the staged copy of the source
            target = deck if reads == "pdf" else page
            if not script.is_file() or not target.is_file():  # the source ships no such check, or there is nothing for it to read
                continue
            r = resume.sh(["python3", f"{deck_src}/tools/{tool}.py", resume.rel(str(target))], env)  # where the typesetting ran
            if r.returncode == 0:  # passed
                continue
            text = (r.stdout or "") + (r.stderr or "")  # what it said
            unpathed = lambda s: re.sub(r"(/[\w.\-가-힣]+)+/?", "", s).strip()  # noqa: E731  a line without the paths it names
            if "Traceback (most recent call last)" in text:  # it broke: the deck was not checked, which is said as such
                last = ([ln.strip() for ln in text.splitlines() if ln.strip()][-1:] or [""])[0]
                out.append(CD.deck_tool_item(tool, unpathed(last)[:200], failed=True))
                continue
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            found = [ln.lstrip("-•*").strip() for ln in lines if re.match(r"\s*[-•*]\s", ln)] or lines[-3:]  # its list of problems, else its last words
            out += [CD.deck_tool_item(tool, unpathed(w)[:240]) for w in found[:20]]
        return out

    def stage_ledger(self, pdf: Path) -> Path | None:
        """The person's profile (and its English translation, when there is one) written where the container reads it, as
        {"profiles": [...]}: the ledger an edition's periods, numbers and lists are held to. Named after the engine's PDF, so the
        edition's clean-up takes it with its other working files if the check's own removal could not. None without a profile."""
        found = [read_json(f, None) for f in (self.facts.profile_file(), self.facts.english_file()) if f.is_file()]  # both languages, where the profile keeps them
        found = [p for p in found if isinstance(p, dict)]  # readable ones only
        if not found:  # no profile yet: the ledger rules are not read
            return None
        f = ROOT / "output" / "_inputs" / f"{Path(str(pdf)).stem}.ledger.json"  # beside the edition's other staged inputs
        f.parent.mkdir(parents=True, exist_ok=True)
        write_json(f, {"profiles": found})  # no schema at the top: it is never staged as a profile with its pictures
        return f

    @staticmethod
    def check_report(pdf: Path) -> Path:
        """Where src/check_documents.py writes an edition's defects with their codes: beside the engine's PDF, in the engine's
        folder the container sees (its clean-up takes it with the edition's other working files)."""
        return ROOT / "output" / f"{Path(str(pdf)).stem}.checks.json"

    def read_checks(self, pdf: Path) -> tuple[list, list]:
        """The defects and the notes to polish of the last check of a PDF, with their codes and values, for the panel to word
        in its own language (([], []) when the check wrote none: a stand-in, an older engine, or a check that did not run)."""
        f = self.check_report(pdf)  # beside it
        got = read_json(f, None) if f.is_file() else None  # what the check wrote
        f.unlink(missing_ok=True)  # read once
        well = lambda items: [x for x in items if isinstance(x, dict) and isinstance(x.get("text"), str)][:200] if isinstance(items, list) else []  # noqa: E731  well formed only
        return (well(got.get("defects")), well(got.get("polish"))) if isinstance(got, dict) else ([], [])

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
        profile, posting = str(out_dir / "profile.json"), str(applications.posting_file(self.ws, job_id))  # its inputs (the posting where the applications keep it)
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

    def edition_inputs(self, job_id: str, lang: str, theme: str = "navy", max_pages: int = 3) -> Path | str:
        """Write an edition's profile.json and job.json (what the typesetting and the cover letter read). Returns the
        edition's folder, or an error code: a name or email missing, or the English profile not made."""
        bad = problems(self.facts_for(job_id).profile())  # what stops a resume
        if bad:  # a name, an email or a job is missing
            return bad[0]  # the band names the first one
        own = self.own_src(job_id, lang)  # the job's own edition, when the person brought one in
        if own == "own_lang":  # brought in without this language
            return "own_lang"
        src = own or (self.facts.profile_file() if lang == "ko" or self.profile_lang() == "en" else self.english_for(job_id))  # the profile of this language
        if src is None:  # no English profile of this profile yet
            return "needs_translation"  # the band offers to translate
        out_dir = self.build_dir(job_id, lang)  # where this edition goes
        out_dir.mkdir(parents=True, exist_ok=True)  # jobs/<job>/resume/<lang>/
        name = "owl_" + self.short(job_id) + "_" + lang  # the engine's output name
        cfg = {"out": name, "maxPages": max_pages, **self.edition_cfg(job_id, lang, theme)}  # job.json: what resume_form.js and deck_slides.js read
        write_json(out_dir / "job.json", cfg)  # kept with the edition
        self._edition_profile(job_id, src, lang, out_dir)  # the profile it was made from (the lock freezes it too)
        return out_dir  # ready for the cover letter and the typesetting
