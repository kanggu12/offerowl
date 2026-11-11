"""A browser walk through the panel on the fictional example: the make view and the example person (timed to the first resume), the workspace
with the evidence of a sentence, an edit the evidence does not cover, the profile, a job with its fit, tailoring, the
interview studio, the job's own materials and its presentation, the tracker with reminders, every inspector tab and the menu, then the agent's own states through
the stand-in, the agent's panel, the command bar open with a day's asks, the setup guide (its four steps the first time, and again from the menu), and a whole automatic
run from a dropped file to the PDFs. Every state is measured (tests/app/audit.js) at 2560x1440, 1440x900 and a 390-pixel phone, light and
dark, Korean and English, and kept as a screenshot.

    python3 tests/app/walk.py --out DIR [--render] [--keep] [--only STATE,...] [--guide DIR] [--engine NAME[=ws://HOST:PORT/]]

--engine walks in another browser engine: firefox, webkit, or chromium (the default). NAME=ws://... connects to a
Playwright server instead of starting the browser here (WebKit needs libraries a plain Linux often lacks; its container
has them: CONTRIBUTING.md). The page keeps the panel's own Content-Security-Policy in every engine: the waits ask their
conditions from here, so a script or style the policy refuses is a console error and fails the walk.

--guide DIR also keeps the user guide's screenshots (docs/assets/guide-*.png), in
English, as the guide is written, at 1600 x 1000, from the states named in GUIDE. The pictures of Make (before a run, during
one, on a phone) come from docs/assets/scene.py, which runs one good run: this walk fails one on purpose to show the fix.

The panel runs on a free port with a workspace of its own in a temporary folder, a fake home whose `claude` is the
stand-in (apps/api/standin.py) with a fictional account, the agent off (backend none) until the walk turns it on, and
no network. --render also makes the typeset PDFs (the heavy part: it renders in the container).
The last lines are the first-run time and the verdict:
  "first run: N s from the page to the example's resume (backend none)"
  "walk: N states x 12 views, overflow 0, truncated 0, overlap 0, markup 0, paths 0, contrast 0, align 0, center 0"
Exit 0 when every measure is zero and the page raised no error.
"""
import argparse  # the command line
import json  # the report
import os  # environment
import pathlib  # paths
import shutil  # the temporary folder
import subprocess  # the panel's server
import sys  # the interpreter
import tempfile  # the temporary folder
import time  # waiting and timing
from playwright.sync_api import sync_playwright  # the browser

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here

AUDIT = (ROOT / "tests" / "app" / "audit.js").read_text(encoding="utf-8")  # the in-page measure
SAMPLE = ROOT / "examples" / "sample_ko.json"  # the fictional example
POSTING = ROOT / "tests" / "app" / "fixtures" / "posting_ko.md"  # a fictional posting
NOTES = ROOT / "tests" / "app" / "fixtures" / "notes_ko.txt"  # fictional notes
KIT = ROOT / "examples" / "interview" / "jobs" / "gamma-platform" / "interview"  # a fictional interview kit with scripts
NOTE = ("# 감마클라우드 면접 준비\n\n가상의 회사 **감마클라우드**의 결제 플랫폼을 공부한 노트.\n\n## 질문\n\n- 승인 경로를 나눈 이유\n  - 배포 시간을 줄이려고\n"
        "1. 장애 대응 순서\n\n| 주제 | 준비 |\n|---|---|\n| 정산 | 끝냄 |\n\n> 숫자는 근거에 있는 것만 말한다.\n\n```python\nif total == expected:\n    print('ok')\n```\n")  # a fictional study note: every block a preview draws
VIEWS = [(2560, 1440), (1440, 900), (390, 844)]  # the window sizes measured: a wide screen, a laptop, a phone
THEMES = ("light", "dark")  # both looks are measured
LANGS = ("ko", "en")  # both languages are measured
NAMES = [SAMPLE.name, NOTES.name]  # the person's own file names, allowed on screen
KINDS = ("overflow", "truncated", "overlap", "markup", "paths", "contrast", "align", "center")  # what the audit counts
# the user guide's screenshots: a state of the walk -> (file, window, themes, the part to keep or None for the window).
# One theme writes FILE.png, two write FILE-light.png and FILE-dark.png (a <picture> picks one by the reader's theme).
GUIDE = {"profile_facts": [("guide-profile", (1600, 1000), ("light", "dark"), None)],
         "jobs_fit": [("guide-job-fit", (1600, 1000), ("light", "dark"), None)],
         "evidence_selected": [("guide-documents", (1600, 1000), ("light", "dark"), None)],   # the documents with a sentence's evidence
         "inspector_theme": [("guide-inspector-theme", (1600, 1000), ("light", "dark"), None)],
         "interview_board": [("guide-interview-board", (1600, 1000), ("light", "dark"), None)],
         "tracker_board": [("guide-tracker", (1600, 1000), ("light", "dark"), None)],
         "agent_panel": [("guide-agent", (1600, 1000), ("light", "dark"), ".pop")],
         "setup_agent_ready": [("guide-setup", (1600, 1000), ("light", "dark"), ".setup")],
         "insights": [("guide-insights", (1600, 1000), ("light", "dark"), None)],   # the whole search on one screen
         "library": [("guide-library", (1600, 1000), ("light", "dark"), None)],   # every file in and out
         "library_trash": [("guide-trash", (1600, 1000), ("light", "dark"), None)]}   # what was removed, to put back or delete for good
# the page's motion (apps/panel/static/motion.js) ends before anything is measured: cards that rise in turn are not yet in place
SETTLED = ("() => Promise.race([Promise.all(document.getAnimations().filter((a) => a.effect && a.effect.getComputedTiming().endTime !== Infinity)"
           ".map((a) => a.finished.catch(() => null))).then(() => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)))),"  # and two frames: what the last animation left is drawn
           " new Promise((ok) => setTimeout(ok, 3000))])")
# the bar wears its glass once the page has slid under it, and takes it from the page's own scroll event (app.js): true when the
# bar's look matches where the page now is, or when the page has no bar
LANDED = "(() => { const t = document.getElementById('top'); return !t || t.classList.contains('under') === (window.scrollY > 4); })()"


def fake_home(tmp: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """A home with a fictional Claude Code login and a `claude` that is the stand-in. Returns (home, bin folder)."""
    home, bin_ = tmp / "home", tmp / "bin"  # a HOME and a PATH folder of the walk's own
    home.mkdir()  # the person's folder
    bin_.mkdir()  # the fake CLI goes here
    script = bin_ / "claude"  # the stand-in CLI
    # a shell script that hands every call to standin.py
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{ROOT / "apps" / "api" / "standin.py"}" claude "$@"\n', encoding="utf-8")
    script.chmod(0o755)  # PATH lookups need it executable
    return home, bin_  # for the panel's environment


PLANTED = """<!doctype html><meta charset=utf-8><body style="margin:0;font:13px sans-serif;background:#fff">
<div style="width:80px;overflow:hidden;white-space:nowrap">a line far too long for its narrow box</div>
<div style="width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">an ellipsis cuts this one short</div>
<div style="position:relative;height:30px"><span style="position:absolute;left:0">overlapping words</span><span style="position:absolute;left:10px">here too</span></div>
<p>a raw ==mark== left in</p><p>saved in /root/secret/folder by python3 tool.py</p>
<p style="color:#bbbbbb">pale grey words on white</p>
<div style="display:flex;gap:8px;align-items:flex-start"><button style="height:30px">one</button><button style="height:40px">two</button></div>
<div class="tiles" style="display:grid;grid-template-columns:1fr 1fr;align-items:start"><div class="tile" style="height:50px">a</div><div class="tile" style="height:80px">b</div></div>
<div class="flow" style="display:grid;grid-template-columns:1fr 1fr;align-items:start"><div><div style="height:20px">h</div><div style="height:40px">a</div></div><div><div style="height:60px">h</div><div style="height:40px">b</div></div></div>
<button style="display:inline-flex;align-items:center;justify-content:center;height:36px;padding:8px 12px 0;border:1px solid #888;background:#eee;font:14px sans-serif">off its middle</button>
<div style="position:fixed;left:0;right:0;bottom:0;height:40px;background:#fff">a bar at the foot</div></body>"""  # one defect of each kind, and a bar that must not count


def audit_selftest(page) -> dict:
    """The audit on a page with one planted defect of each kind: every count must be above zero."""
    page.set_content(PLANTED)  # the planted page (no panel, no CSP)
    found = page.evaluate(AUDIT, [])  # no file names allowed here
    return {k: len(found[k]) for k in KINDS}  # one count per kind


class Walk:
    """The browser and the panel, and what was measured."""

    def __init__(self, page, out: pathlib.Path, only: set, guide: pathlib.Path | None = None):  # what every step of the walk needs
        self.page, self.out, self.only, self.guide = page, out, only, guide  # the tab, the screenshots' folder, the states to measure (empty: all), the guide's folder
        self.report = []  # one entry per state and view
        self.n = 0  # the state counter

    def state(self):
        """The panel's state, as the page has it."""
        return self.page.evaluate("S")  # the page's own copy, as last drawn

    def wait(self, cond_js: str, timeout: float = 60):
        """Wait until a condition on the page holds, asked from here every 0.2 s: Playwright's own polled wait compiles
        the words inside the page, which the panel's policy (no eval) refuses."""
        end = time.time() + timeout  # when to give up
        while True:  # until it holds
            try:  # a page between two documents has no context to ask
                if self.page.evaluate(cond_js):  # through the protocol: no eval in the page
                    return
            except Exception as e:  # asked while the page was being replaced: asked again
                if "context was destroyed" not in str(e) and "navigat" not in str(e).lower():  # anything else is the condition's own error
                    raise
            if time.time() > end:  # it never held
                raise TimeoutError(f"wait: {cond_js[:160]}")
            time.sleep(0.2)  # the next look

    def settle(self, ms: int = 450):
        """Time for the answer, the redraw and the pages' layout."""
        self.page.wait_for_timeout(ms)  # transitions are short

    def landed(self):
        """Wait until a scroll's event has reached the page. A scroll made from here is in place at once, but its event is
        not: WebKit delivers it up to a third of a second later, and until then the bar is still clear over the words that
        slid under it, which the measure would count as words on words. Two seconds at most, then the measure says what it sees."""
        end = time.time() + 2  # longer than any engine took
        while not self.page.evaluate(LANDED) and time.time() < end:  # asked through the protocol, as wait() does
            time.sleep(0.05)  # the event is a few frames away

    def view(self, lang: str, theme: str, w: int, h: int, drawer: bool):
        """Switch the page to one language, theme and size without reloading (as a person would)."""
        self.page.set_viewport_size({"width": w, "height": h})  # the window size
        self.page.evaluate("([l, t, d]) => { setLang(l); localStorage.setItem('offerowl-theme', t); applyTheme(t);"  # the page's own switches
                           " UI.drawer = d && window.innerWidth < 1280; document.getElementById('toast').classList.remove('show'); redrawAll(); }",
                           [lang, theme, drawer])  # the drawer opens on narrow windows when the state is about the inspector
        self.page.wait_for_timeout(420)  # layout and the pages' pagination settle

    def shoot(self, name: str, drawer: bool = False, scroll: str | None = None, prep: str | None = None):
        """Measure and keep a screenshot of the state in every view. prep: JavaScript run after each switch of language, theme
        and size, for what a redraw does not bring back (the panel's question, a note with a key): drawn anew in that language."""
        self.n += 1  # the state's number in the file names
        if self.only and name not in self.only:  # a partial walk
            return  # not measured
        for lang in LANGS:  # every language
            for theme in THEMES:  # every look
                for w, h in VIEWS:  # every window size
                    self.view(lang, theme, w, h, drawer)  # the page as that person would see it
                    if prep:  # what the switch took away, drawn again in this language
                        self.page.evaluate(prep)
                        self.page.wait_for_timeout(250)  # drawn
                    if scroll:  # a part of the page to bring into view
                        self.page.evaluate("(s) => { const e = document.querySelector(s); if (e) e.scrollIntoView({ block: 'start' }); }", scroll)
                    self.landed()  # the scroll's event has reached the page (a resized window moves a scrolled page too)
                    self.page.evaluate(SETTLED)  # what moves has come to rest
                    found = self.page.evaluate(AUDIT, NAMES)  # the in-page measure
                    file = self.out / f"{self.n:02d}_{name}_{lang}_{theme}_{w}x{h}.png"  # numbered, so the files sort in walk order
                    self.page.screenshot(path=str(file))  # kept for the eye's check
                    counts = {k: len(found[k]) for k in KINDS}  # one number per kind
                    self.report.append({"state": name, "lang": lang, "theme": theme, "size": f"{w}x{h}", "texts": found["texts"], "keys": found["keys"],  # one row per view
                                        **counts, "details": {k: found[k][:6] for k in counts if found[k]}})  # a few examples of each
                    bad = {k: v for k, v in counts.items() if v}  # only the kinds found
                    print(f"{self.n:02d} {name:24} {lang} {theme:5} {w}x{h}  texts {found['texts']:4}  keys {found['keys']:3}  " +  # one line per view as it runs
                          (" ".join(f"{k} {v}" for k, v in bad.items()) or "clean"), flush=True)
        self.guide_shots(name, drawer, scroll)  # the guide's pictures of this state, when asked for
        self.view("ko", "light", 1440, 900, False)  # back to the walk's own view

    def guide_shots(self, name: str, drawer: bool, scroll: str | None):
        """The user guide's screenshots of a state (GUIDE), in English as the guide is, into the guide's folder."""
        if not self.guide or name not in GUIDE:  # not asked for, or not one of the guide's states
            return
        for file, (w, h), themes, part in GUIDE[name]:  # each picture of this state
            for theme in themes:  # one per look
                self.view("en", theme, w, h, drawer)  # as the guide's reader sees it: its words name these keys
                if scroll:  # the same part in view as the walk's own picture
                    self.page.evaluate("(s) => { const e = document.querySelector(s); if (e) e.scrollIntoView({ block: 'start' }); }", scroll)
                self.landed()  # the scroll's event has reached the page
                self.page.evaluate(SETTLED)  # what moves has come to rest
                target = self.guide / (f"{file}.png" if len(themes) == 1 else f"{file}-{theme}.png")  # its name in docs/assets
                box = self.page.locator(part).first.bounding_box() if part else None  # the part kept, when one is named
                if box:  # the part with a margin of the page around it
                    m = 24  # room around it, as the panel shows it
                    clip = {"x": max(0, box["x"] - m), "y": max(0, box["y"] - m), "width": box["width"] + 2 * m, "height": box["height"] + 2 * m}
                    self.page.screenshot(path=str(target), clip=clip)  # the part alone
                else:  # the whole window
                    self.page.screenshot(path=str(target))
                print(f"guide: {target.name}", flush=True)  # for the log

    def click(self, selector: str, ms: int = 450):
        """A click, then time for the redraw."""
        self.page.click(selector)  # as a person clicks
        self.settle(ms)  # the answer arrives and the page redraws

    def api(self, path: str, body: dict | None = None):
        """A write as the page makes it (through the page's own api(), so the state and the panes follow)."""
        self.page.evaluate("([p, b]) => api(p, b).then(schedule)", [path, body or {}])  # through the page
        self.settle(600)  # the redraw


def main() -> int:  # 0 only when nothing was found
    ap = argparse.ArgumentParser()  # the options of the docstring
    ap.add_argument("--out", required=True, type=pathlib.Path, help="where the screenshots and report.json go")  # always named
    ap.add_argument("--render", action="store_true", help="also make the typeset PDFs (heavy)")  # off by default
    ap.add_argument("--keep", action="store_true", help="keep the temporary workspace")  # for looking into a failed walk
    ap.add_argument("--only", default="", help="measure only these states (comma separated)")  # a quick look at a few
    ap.add_argument("--guide", type=pathlib.Path, default=None, help="also keep the user guide's screenshots in this folder")  # docs/assets/guide-*.png
    ap.add_argument("--engine", default="chromium", help="chromium, firefox or webkit; NAME=ws://HOST:PORT/ connects to a Playwright server")  # the walk in another engine
    a = ap.parse_args()  # the options
    a.out.mkdir(parents=True, exist_ok=True)  # a new folder is fine
    for old in a.out.glob("*.png"):  # pictures from an earlier walk
        old.unlink()  # the last walk's pictures
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-walk-"))  # data, home, desktop
    home, bin_ = fake_home(tmp)  # the fictional login and the stand-in CLI
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",  # the fake claude is found first
           "OFFEROWL_DESKTOP": str(tmp / "Desktop"),  # exports
           "OFFEROWL_LLM_LOG": str(tmp / "calls.jsonl"),  # the agent's panel counts this walk's calls only
           "OFFEROWL_CPUS": os.environ.get("OFFEROWL_CPUS", "4"), "PYTHONDONTWRITEBYTECODE": "1"}  # the panel's world
    env.pop("OFFEROWL_PANEL_AGENT", None)  # the agent goes through the fake claude, not the shortcut
    env.pop("OFFEROWL_PANEL_BACKEND", None)  # the walk chooses the backend through the settings, as a person does
    data = tmp / "data"  # the panel's data folder
    data.mkdir(parents=True)  # made before the server starts, so the setting below is read
    (data / "settings.json").write_text(json.dumps({"backend": "none"}), encoding="utf-8")  # the agent off: the first run with backend none
    # the panel as its own process, on a free port
    srv = subprocess.Popen([sys.executable, str(ROOT / "apps" / "panel" / "server.py"), "--port", "0", "--data", str(data)],
                           env=env, stdout=subprocess.PIPE, text=True, encoding="utf-8")  # its first printed line is the address
    base = srv.stdout.readline().strip()  # its address
    started = time.time()  # for the report's seconds
    errors, first_run = [], None  # script errors; the first run's seconds
    w = None  # the measuring helper, once the browser runs
    try:  # the panel and the stand-in stop whatever happens
        with sync_playwright() as pw:  # the browser driver
            name, _, remote = a.engine.partition("=")  # an engine, or an engine at a Playwright server's address
            if name not in ("chromium", "firefox", "webkit"):  # a name Playwright has no browser for
                raise SystemExit(f"--engine: chromium, firefox or webkit, not {name!r}")
            browser = getattr(pw, name).connect(remote) if remote else getattr(pw, name).launch()  # headless: no window on the desktop
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR", accept_downloads=False)  # a Korean browser, the panel's own policy in force
            page = ctx.new_page()  # one tab for the whole walk
            page.on("pageerror", lambda e: errors.append(str(e)))  # uncaught exceptions
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)  # console.error lines
            page.on("dialog", lambda d: (errors.append("a browser dialog, not the panel's own: " + d.message), d.dismiss()))  # the panel asks on its own sheet (core.js askFirst)
            planted = audit_selftest(page)  # the measure finds what it measures
            print("audit self-test on planted defects:", planted, flush=True)  # the counts, for the log
            if not all(planted.values()):  # a kind it failed to find
                raise SystemExit("the audit missed a planted defect: " + json.dumps(planted))  # a blind measure proves nothing
            if a.guide:  # the guide's folder is made before the first picture
                a.guide.mkdir(parents=True, exist_ok=True)
            w = Walk(page, a.out, {x for x in a.only.split(",") if x}, a.guide)  # the measuring helper

            # ---- the make view before anything is added
            page.goto(base + "?lang=ko")  # the panel, in Korean first
            w.wait("typeof S !== 'undefined' && S && S.agent && S.agent.state !== 'checking' && document.querySelector('.make-in .drop')")  # the make view
            # ---- the setup guide: by itself over a workspace that holds nothing, its four steps, then its close key (which changes nothing)
            w.wait("document.querySelector('#setup:not([hidden]) .setup')")  # it opened by itself
            w.shoot("setup_agent")  # the agent: off here (backend none)
            for i, name in ((1, "setup_typeset"), (2, "setup_look"), (3, "setup_start")):  # the other steps, by their tabs
                page.locator("#setup .setup-step").nth(i).click(); w.settle(); w.shoot(name)
            page.click("#setup .setup-close"); w.settle()  # closed as most people close it, with the pointer
            w.wait("document.getElementById('setup').hidden")  # and gone
            w.shoot("make_start")  # nothing added yet

            # ---- the first look, timed: the make view, then the example person's resume (no AI)
            t0 = time.time()  # the clock starts at the page's load
            page.goto(base + "?lang=ko")  # the panel again, so the clock counts a fresh load
            w.wait("typeof S !== 'undefined' && S && S.agent && S.agent.state !== 'checking' && document.querySelector('.make-in .drop')")  # the make view
            page.click("[data-act=example]")  # Try an example
            w.wait("document.getElementById('canvas').dataset.ready === 'resume'", 60)  # the example's resume, in view
            first_run = time.time() - t0  # seconds from the page to the resume
            print(f"first run: {first_run:.1f} s to the example's resume", flush=True)  # for the log
            page.evaluate("go('make')"); w.settle(600)  # back to making, with the example's facts kept
            w.shoot("make_with_example")  # the three columns before any run
            page.evaluate("go('documents')"); w.wait("document.getElementById('canvas').dataset.ready === 'resume'")  # the resume again
            w.shoot("documents_resume")  # the workspace with the live resume

            # ---- evidence on click, an edit outside the evidence, undo
            page.locator(".sheet .s[data-sid]").nth(4).click(); w.settle()  # a sentence clicked
            w.shoot("evidence_selected", drawer=True)  # its evidence in the inspector
            sid = page.evaluate("Object.keys(resumeModel().sentences).find((k) => k.startsWith('roles.0.projects.0.summary'))")  # a project sentence
            page.evaluate("(sid) => select(sid)", sid); w.settle()  # selected
            page.click("#ipanel button:has-text('고치기')"); w.settle()  # Edit
            page.fill("[data-key=sentence-edit]", "승인 기능을 분리해 배포 시간을 40% 줄였다.")  # a number the evidence does not have
            w.shoot("evidence_editing", drawer=True)  # the edit form
            page.click("#ipanel button[type=submit]"); w.settle(900)  # saved: the check marks it
            w.wait("resumeModel() && resumeModel().counts.unsupported === 1")  # one sentence without evidence
            w.shoot("evidence_unsupported", drawer=True)  # marked red, export blocked, the band
            page.click("#undo"); w.settle(900)  # undo
            w.wait("resumeModel() && resumeModel().counts.unsupported === 0")  # all with evidence again
            page.evaluate("UI.sel = null; render()")  # nothing selected

            # ---- the profile
            page.evaluate("go('profile'); UI.filter = 'kept'; render()"); w.settle()  # the facts kept
            w.shoot("profile_facts")  # details, files, facts
            page.locator(".fact .acts button").nth(1).click(); w.settle()  # Edit one fact
            w.shoot("profile_fact_editing", scroll=".fact")  # its form
            page.evaluate("UI.factEdit = null; forget('f-'); render()")  # closed
            page.evaluate("UI.factAdd = true; render()"); w.settle()  # the typed-fact form
            page.fill("[data-key=f-add-title]", "사내 장애 대응 교육")  # a fact of the person's own
            page.fill("[data-key=f-add-statement]", "신규 입사자에게 장애 대응 절차를 가르쳤다")  # in their words
            w.shoot("profile_add_fact", scroll=".add-fact")  # the form filled in
            page.click(".add-fact button[type=submit]"); w.settle(800)  # added and kept
            w.wait("S.facts.counts.found === 32")  # one more fact
            page.click("#undo"); w.settle(800)  # taken back: the example stays whole for the job
            w.wait("S.facts.counts.found === 31")  # back to the example

            # ---- a job: the form, the fit, tailoring
            page.evaluate("go('jobs')"); w.settle()  # the jobs
            page.fill("[data-key=j-posting]", POSTING.read_text(encoding="utf-8"))  # the posting, pasted
            w.shoot("jobs_form")  # the form filled in
            page.click("form button[type=submit]"); w.settle(900)  # added
            w.wait("S.jobs.length === 1 && S.tasks['analyze:' + S.job] && S.tasks['analyze:' + S.job].state === 'done'")  # ordered by the words
            w.wait("fitOf(S.job) !== null")  # the fit arrived
            w.shoot("jobs_fit")  # the fit line by line
            page.click("[data-act=job-make]"); w.settle()  # the job's documents, by one run followed on Make
            w.wait("S.tasks.autopilot && S.tasks.autopilot.state !== 'running'", 300)  # it ends (the writing needs the agent)
            page.evaluate("go('jobs'); UI.jobTab = 'docs'; render()"); w.settle(600); w.shoot("jobs_tailored")  # the three parts' states, on the job's Documents tab
            page.evaluate("UI.jobTab = 'fit'; UI.lineOpen = S.job + '|0'; render()"); w.settle(); w.shoot("jobs_line_open")  # a line of the posting opened on its evidence
            page.evaluate("UI.lineOpen = null; render()")  # closed
            page.evaluate("UI.doc = 'resume'; go('documents')"); w.wait("document.getElementById('canvas').dataset.ready === 'resume'")  # the resume for the job
            w.shoot("documents_for_job")  # ordered for the job
            page.evaluate("UI.doc = 'cover'; render()"); w.settle(800)  # the cover letter's tab
            w.shoot("documents_cover_needs_agent")  # it needs the agent
            page.evaluate("UI.doc = 'resume'; UI.mode = 'typeset'; render()"); w.settle()  # the typeset view before any PDF
            w.shoot("documents_typeset_none")  # no PDF yet, with the reason
            page.evaluate("UI.mode = 'live'; render()")  # back to the live canvas

            # ---- a named general edition with a resume the person wrote for it: the picker's groups and the "as you wrote it" mark
            own = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the fictional person's resume
            own["summary"]["headline"] = "헤드헌터에게 보내는 판의 머리 문장"  # written for that edition
            eid = page.evaluate("api('/api/v1/editions', {name: '헤드헌터용 플랫폼 엔지니어'}).then(r => r.job)")  # made through the page's own api()
            page.evaluate("([j, p]) => api('/api/v1/jobs/own', {job: j, profile: p, langs: ['ko'], name: '헤드헌터용'})", [eid, own])  # brought in
            w.api("/api/v1/jobs/select", {"job": eid})  # in view, as the bar's picker sends it
            page.evaluate("UI.doc = 'resume'; go('documents')"); w.wait("document.getElementById('canvas').dataset.ready === 'resume'")  # its resume
            w.shoot("documents_named_edition")  # the edition's name, the mark, no offer to write it
            w.api("/api/v1/jobs/select", {"job": page.evaluate("S.jobs[0].id")})  # back to the job

            # ---- the application's interview tab: the board, then scripts from the fictional kit
            page.evaluate("go('interview'); UI.ivPart = 'map'; render()"); w.wait("boardOf(S.job) && boardOf(S.job).ready")  # the board, on the application's Interview tab (its map part: the walk has no kit server for the search view's frame)
            w.shoot("interview_board")  # questions by category, no scripts yet
            jid = w.state()["job"]  # the job's folder name
            ivdir = data / "workspace" / "jobs" / jid / "interview"  # its kit folder
            for f in ("qa.md", "deep.md", "terms.md"):  # the fictional example's scene files
                shutil.copyfile(KIT / f, ivdir / f)  # as if the agent had drafted them and they were accepted
            w.api("/api/v1/interview/kit", {"job": jid, "lang": "ko"})  # the map again, now covered by the scenes
            w.wait("boardOf(S.job) && boardOf(S.job).scripts.length > 0")  # scripts on the board
            w.shoot("interview_scripts", scroll=".scripts")  # the script cards
            page.evaluate("""async ([jid, text]) => { await fetch(`/api/v1/jobs/materials?job=${encodeURIComponent(jid)}`, { method: 'POST', body: new Blob([text]),
                headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent('면접 준비 노트.md') } }); }""", [jid, NOTE])  # a note of the person's own, sent as the page sends a file
            page.evaluate("refresh()"); w.wait("job() && (job().materials || []).length === 1")  # listed with the job
            page.evaluate("UI.matOpen = S.job + '|' + job().materials[0].id; render()")  # opened on its preview
            w.wait("document.querySelector('.mats .mat-doc')")  # drawn as text: headings, lists, a table, a quote, code
            w.shoot("interview_materials", scroll=".mt.open")  # the application's own materials, one open
            # ---- the presentation interview: its brief, then the talk made from the documents alone (the agent is off at this point of the walk)
            page.evaluate("UI.matOpen = null; UI.ivPart = 'talk'; render()"); w.wait("document.querySelector('.talk-brief')")  # the brief's form
            w.shoot("interview_talk_brief")  # what the interviewers asked for: topics, minutes, day, format
            w.api("/api/v1/interview/talk/brief", {"job": jid, "brief": {"topics": [{"title": "소개와 핵심 역량"}, {"title": "업무로 배운 경험과 기술"},
                  {"title": "가장 도전적이었던 문제"}, {"title": "지원 계기와 커리어 계획"}], "minutes": 30, "when": "2026-11-20 14:00", "format": "발표와 질의응답"}})  # a fictional brief
            w.api("/api/v1/interview/talk", {"job": jid, "lang": "ko"})  # made: the portfolio's pages and the talk's own slides, then its script
            w.wait("(S.tasks['talk:' + S.job] || {}).state === 'done'", timeout=600)  # drawn and printed
            page.evaluate("UI.talkDraft = {}; refresh()"); w.wait("document.querySelector('.talk iframe.ivframe')", timeout=120)  # the script in the kit's frame
            w.settle(1500)  # the frame's page loaded
            w.shoot("interview_talk")  # the talk's keys, its script and the brief under it
            errors += [] if (data / "workspace" / "out" / "interview" / jid / "talk" / "deck.pdf").is_file() else ["the talk made no deck"]  # the deck itself, not only the page

            # ---- the application's progress, then every application by stage and by date
            page.evaluate("go('jobs'); UI.jobsMode = 'list'; UI.jobTab = 'progress'; render()"); w.settle()  # its stage, next step and reminders
            page.fill("[data-key=r-text]", "서류 결과 확인")  # a reminder
            page.click(".remind button[type=submit]"); w.settle(800)  # kept (today: due now)
            w.shoot("jobs_progress")  # the stage, the reminder that is due
            page.evaluate("go('tracker')"); w.settle()  # every application by stage
            page.click(".tcard button.btn.small"); w.settle(800)  # moved to submitted
            w.shoot("tracker_board")  # the board, a due reminder
            page.evaluate("UI.jobsMode = 'timeline'; render()"); w.settle()  # the timeline
            w.shoot("tracker_timeline")  # every dated step
            # a result in the person's own words, as the API takes it: short on the lamp, whole in the timeline and the progress
            page.evaluate("act('/api/v1/tracker/edit', { job: S.job, stage: 'result', result: '2026-10-28 탈락(서류 합격, 1차 면접 뒤)' })"); w.settle(800)
            w.shoot("tracker_timeline_result")  # the result's own words in the timeline
            page.evaluate("UI.jobsMode = 'list'; UI.jobTab = 'progress'; go('jobs')"); w.settle()  # the application, on its progress
            w.shoot("jobs_result_words")  # the lamp's short words, and all of them under the result's keys
            page.evaluate("act('/api/v1/tracker/edit', { job: S.job, stage: 'submitted', result: '' })"); w.settle(800)  # back where it was, for the rest of the walk
            page.evaluate("go('insights')"); w.wait("document.querySelector('.ins-kpi:not(.ghost)') !== null"); w.settle(700)   # the numbers counted
            w.shoot("insights")  # the persona, the numbers and every figure of the search
            page.evaluate("UI.libGroup = 'all'; UI.libQuery = ''; go('library')"); w.wait("document.querySelector('.lib-table') !== null"); w.settle(500)
            w.shoot("library")  # every file brought in or made, with its keys
            page.evaluate("UI.libGroup = 'made'; render()"); w.settle(400)
            w.shoot("library_made")  # one kind of file

            # ---- the Trash: the named edition and the application's note removed, and a folder a restore kept aside; the panel's
            # question before deleting for good, and the note that holds Undo. Then one put back and one deleted, through the keys
            aside = data / "workspace-before-restore-20261101-093000"  # beside the workspace, named as a restore names it
            (aside / "profile").mkdir(parents=True)  # a workspace's shape
            (aside / "profile" / "profile.json").write_text("{}", encoding="utf-8")
            mid = page.evaluate("(S.jobs.find((j) => (j.materials || []).length) || {materials: [{}]}).materials[0].id")  # the note sent above
            w.api("/api/v1/jobs/materials/remove", {"job": jid, "id": mid})  # the note, off the application's list
            w.api("/api/v1/jobs/remove", {"job": eid})  # the named edition, off the editions
            page.evaluate("UI.libGroup = 'trash'; UI.libQuery = ''; UI.libPage = 0; go('library')"); w.wait("document.querySelector('.trash-row') !== null"); w.settle(500)
            w.shoot("library_trash")  # what was removed, with the day it went, and the folder kept aside
            ask = "(k) => { const no = document.querySelector('[data-key=confirm-no]'); if (no) no.click(); document.querySelector(`[data-key=\"${k}\"]`).click(); }"
            w.shoot("trash_confirm", prep=f"({ask})('delete-job:{eid}')")  # the question before deleting for good: what goes, what stays
            page.keyboard.press("Escape"); w.settle(300)  # no: nothing was deleted
            if page.evaluate("document.getElementById('confirm').hidden && !document.getElementById('work').inert") is not True:  # the sheet gone, the page back
                errors.append("the panel's question did not close on Esc")
            w.shoot("toast_undo", prep="toast(t('Removed {name}.', { name: '면접 준비 노트.md' }), { words: t('Undo'), run: () => {} })")  # a removal's note, its Undo key
            page.click(f'[data-key="put-back-material:{jid}:{mid}"]'); w.settle(800)  # the note back on its application's list
            page.click(f'[data-key="delete-job:{eid}"]'); w.wait("!document.getElementById('confirm').hidden")  # the question
            page.click('[data-key="confirm-yes"]'); w.settle(1000)  # yes: deleted for good
            if page.evaluate("[S.removed.all, (job() && (job().materials || []).length) || 0, S.editions.length]") != [0, 1, 0]:  # the trash empty, the note back, the edition gone
                errors.append("the Trash's keys did not put back and delete: " + json.dumps(page.evaluate("[S.removed, S.editions.length]")))
            page.evaluate("UI.libGroup = 'all'; render()")  # back to every file

            # ---- the inspector's tabs and the menu
            page.evaluate("go('documents'); UI.tab = 'fit'; render()"); w.wait("document.getElementById('canvas').dataset.ready === 'resume'")
            w.shoot("inspector_fit", drawer=True)  # the fit to the job in view
            page.evaluate("UI.tab = 'style'; render()"); w.shoot("inspector_style", drawer=True)  # style
            w.api("/api/v1/blind", {"table": {"mask": ["알파페이", "베타커머스", r"gildong@example\.com", "010-0000-0000", r"github\.com/example-gildong"],  # a fictional table
                                              "mask_whole": [r"gildong@example\.com", "010-0000-0000", r"github\.com/example-gildong"], "leak": ["감마클라우드"]}})
            page.evaluate("UI.tab = 'style'; render()"); w.settle(); w.shoot("inspector_blind_table", drawer=True)  # the blind edition's table, the person's own
            page.evaluate("UI.tab = 'theme'; UI.theme = 'teal'; render()"); w.settle(800); w.shoot("inspector_theme", drawer=True)  # theme, teal on the page
            page.evaluate("UI.theme = 'navy'; UI.tab = 'history'; render()"); w.settle(800); w.shoot("inspector_history", drawer=True)  # the history
            page.evaluate("UI.tab = 'evidence'; UI.menu = true; render()"); w.shoot("menu_open")  # the settings menu
            page.evaluate("UI.menu = false; render()")  # closed

            # ---- typeset PDFs (heavy, only with --render)
            if a.render:  # the container renders the resume and the deck
                page.evaluate("makePdfs()"); w.settle()  # started
                w.wait("S.tasks['build:' + S.job] && S.tasks['build:' + S.job].state !== 'running'", 900)  # typesetting takes minutes
                page.evaluate("UI.mode = 'typeset'; render()"); w.settle(1200)  # the typeset pages
                w.shoot("documents_typeset")  # the PDF's own pages
                page.evaluate("makeBlind(true)"); w.settle()  # the blind edition's switch
                w.wait("S.tasks['build:' + S.job] && S.tasks['build:' + S.job].state !== 'running'", 900)  # made again with the bars
                w.settle(1200)  # its pages
                w.shoot("documents_blind")  # the typeset pages with their bars and band, and what they are
                page.evaluate("UI.mode = 'live'; render()"); w.settle(800)  # the live canvas of a blind edition
                w.shoot("documents_blind_live")  # the words as they are, and where the bars are
                page.evaluate("makeBlind(false)"); w.settle()  # back to the ordinary edition
                w.wait("S.tasks['build:' + S.job] && S.tasks['build:' + S.job].state !== 'running'", 900)  # made again without the bars
                page.evaluate("UI.mode = 'live'; render()"); w.settle()  # the live canvas, as the rest of the walk expects

            # ---- the agent on: the stand-in reads notes; the card shows the fictional account
            w.api("/api/v1/settings", {"agent": "on"})  # on, as the switch does
            w.api("/api/v1/agent/refresh", {})  # looked up now
            w.wait("S.agent.state === 'ready'", 30)  # signed in
            page.evaluate("go('profile')"); w.settle()  # the profile
            mid = page.evaluate("""async (text) => { const r = await fetch('/api/v1/materials', { method: 'POST', body: new Blob([text]),
                headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent('notes_ko.txt') } }); return (await r.json()).material.id; }""",
                                NOTES.read_text(encoding="utf-8"))  # notes for the agent to read, sent as the page sends a file
            w.api("/api/v1/materials/read", {"ids": [mid]})  # read alone: a whole run (the file picker's) would take the example out first, and the walk goes on with it
            w.wait("S.tasks.ingest && S.tasks.ingest.state === 'done' && S.materials.length === 2", 60)  # both materials read
            page.evaluate("UI.filter = 'todo'; render()"); w.settle()  # the new facts to confirm
            w.shoot("agent_on_notes_read")  # facts the agent found, the card ready

            # ---- the resume written by the agent: the offer, then the draft with a sentence selected
            page.evaluate("UI.filter = 'all'; go('documents'); UI.doc = 'resume'; UI.mode = 'live'; UI.sel = null; render()"); w.settle()  # the facts' own sentences
            w.shoot("documents_write_offer")  # the band that offers to write it, and says what it sends
            page.evaluate("writeResume(edition().id)"); w.settle()  # started
            w.wait("task('write:' + edition().id).state && task('write:' + edition().id).state !== 'running'", 60)  # the stand-in answers at once
            w.settle(800)  # the new sentences are laid out
            page.evaluate("const m = resumeModel(); select(Object.keys(m.sentences).find((k) => m.sentences[k].drafted && k.includes('.projects.')))"); w.settle()  # a sentence it wrote
            w.shoot("documents_drafted")  # the draft, with who wrote the sentence and what it cites
            page.evaluate("editInPlace(UI.sel)"); w.settle()  # the same sentence, typed over on the page
            w.shoot("documents_edit_in_place")  # the words with their marks, where they stand
            page.keyboard.press("Escape"); w.settle()  # put back
            page.evaluate("editInPlace(UI.sel)"); w.settle()  # again, this time to save
            page.keyboard.type("Moved the service and cut 97% of the wait")  # typed over the selected words
            page.keyboard.press("Enter")  # saved
            w.wait("((sentenceOf(UI.sel) || {}).text || '').startsWith('Moved the service and cut 97%') && sentenceOf(UI.sel).state === 'unsupported'", 20)  # checked: the evidence has no such number
            w.api("/api/v1/undo", {})  # back
            w.wait("(sentenceOf(UI.sel) || {}).state === 'ok'", 20)  # one undo step

            # ---- the deck: the offer to draw its figures, then the drawing
            page.evaluate("UI.sel = null; UI.doc = 'deck'; UI.mode = 'live'; render()"); w.wait("document.querySelector('.deckframe iframe')", 30); w.settle(800)  # the deck's tab, with its slides
            live = page.evaluate("(() => { const d = document.querySelector('.deckframe iframe').contentDocument; return { slides: d.querySelectorAll('section.slide').length, scripts: d.scripts.length, fonts: [...d.fonts].filter((f) => f.status === 'error').length }; })()")  # the deck's own page in its frame
            assert live["slides"] > 3 and not live["scripts"] and not live["fonts"], live  # its slides, nothing running, and every font found
            w.shoot("documents_deck_offer")  # the band that offers the figures, and says what it sends
            page.evaluate("drawFigures(edition().id)"); w.settle()  # started
            w.wait("task('figures:' + edition().id).state && task('figures:' + edition().id).state !== 'running'", 90)  # the stand-in answers at once
            w.settle(800)  # the band goes
            w.shoot("documents_deck_drawn")  # the deck's tab once its figures are in the draft

            # ---- the choices of form, look and colour, in the inspector's tab
            w.api("/api/v1/settings", {"deck_style": "clean"})  # the light deck
            page.evaluate("UI.tab = 'theme'; render()"); w.wait("document.querySelector('.deckframe iframe')", 30); w.settle(800)  # its slides, and the tab
            w.shoot("theme_light_deck", drawer=True)  # six colours, three forms, two looks
            w.api("/api/v1/settings", {"form": "compact", "deck_style": "classic"})  # one column
            page.evaluate("UI.doc = 'resume'; UI.mode = 'live'; render()"); w.wait("document.getElementById('canvas').dataset.ready === 'resume'", 30); w.settle(800)  # the canvas in that form
            w.shoot("resume_one_column", drawer=True)  # its head and its parts
            w.api("/api/v1/settings", {"form": "table"})  # tables
            page.evaluate("render()"); w.settle(1200)  # drawn again
            w.shoot("resume_tables", drawer=True)  # its head and its parts
            w.api("/api/v1/settings", {"form": "detailed"})  # as it was

            # ---- the person's own rules, the resume's photo, and an application's questions answered
            w.api("/api/v1/style", {"name": "mine", "pack": {"banned_chars": "—", "resume": {"numbers": "forbid", "competencies": [4, 6]}}})  # a rules file, checked and chosen
            page.evaluate("UI.tab = 'style'; render()"); w.settle()  # the Style tab lists it
            w.shoot("inspector_my_rules", drawer=True)  # the writing rules, theirs chosen
            page.evaluate("""async () => { const png = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAB4AAAAoCAIAAABmcd1FAAAAS0lEQVR4nGN0iOlhoA1gopG5o0aPGk0QsOCXXlZohEc2qv8cHtmhGSCjRo8aPWr0CDCaQMmHv2zDD4ZmgIwaPWr0qNGjRo8aTUUAACp9BjNSoTzqAAAAAElFTkSuQmCC'), (c) => c.charCodeAt(0));
                await fetch('/api/v1/photo', { method: 'POST', body: png, headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': 'photo.png' } }); }""")  # a small 3:4 picture (a plain figure drawn by the walk, no one's face)
            page.evaluate("go('profile'); refresh()"); w.wait("S.photo && S.photo.on", 20); w.settle(600)  # the details card shows it
            w.shoot("profile_photo")  # the photo beside the fields
            w.api("/api/v1/jobs/questions", {"job": page.evaluate("S.job"), "questions": [{"text": "지원 동기와 입사 후 하고 싶은 일을 쓰세요.", "limit": 300, "unit": "chars"},
                                                                                       {"text": "Describe a system you built and what it changed.", "limit": 80, "unit": "words"}]})  # two questions
            w.api("/api/v1/jobs/questions/write", {"job": page.evaluate("S.job")})  # answered by the stand-in
            w.wait("task('answers:' + S.job).state && task('answers:' + S.job).state !== 'running'", 60)  # written
            page.evaluate("go('jobs'); UI.jobsMode = 'list'; UI.jobTab = 'questions'; refresh()"); w.settle(800)  # the job's questions tab, in the list
            w.shoot("jobs_questions", scroll=".qcard")  # the questions, their answers, lengths and facts
            w.api("/api/v1/settings", {"style": "default"})  # the shipped rules again for the rest of the walk

            # ---- the agent's panel from the bar, then a whole run from a dropped file
            page.evaluate("go('make'); UI.agentPop = false; render()"); w.settle()  # the make view
            page.click(".barchip"); w.settle()  # the agent's lamp opens its panel
            w.shoot("agent_panel")  # who, the model, what it takes on, the day's calls
            page.keyboard.press("Escape"); w.settle()  # closed
            # ---- the command bar: its key opens the bar in its place, with two asks of a fictional day and their answers, written
            # the way apps/api/ask.py keeps them (a list, a table, the tools that ran)
            asked = [{"at": "2026-11-09 18:40", "text": "감마클라우드 1차 면접 끝났어. 결과는 다음 주에 알려 준대. 기록해 줘", "backend": "claude-code",
                      "answer": "감마클라우드 지원을 **1차 면접**으로 옮기고 오늘 회차를 남겼습니다.\n\n- 다음 단계: 결과 기다리기\n- 알림: 2026-11-16 결과 확인",
                      "tools": ["list_jobs", "move_job", "log_round", "reminder"], "ok": True, "seconds": 24.6},
                     {"at": "2026-11-10 09:12", "text": "지금 진행 중인 지원 정리해 줘", "backend": "claude-code",
                      "answer": "진행 중인 지원은 1건입니다.\n\n| 회사 | 직무 | 단계 | 다음 |\n|---|---|---|---|\n| 감마클라우드 | 백엔드 플랫폼 엔지니어 | 1차 면접 | 2026-11-16 결과 |",
                      "tools": ["list_jobs", "tracker"], "ok": True, "seconds": 11.2}]
            (data / "workspace" / "ask").mkdir(parents=True, exist_ok=True)  # the history's folder, as the first ask makes it
            (data / "workspace" / "ask" / "history.json").write_text(json.dumps(asked, ensure_ascii=False), encoding="utf-8")
            page.evaluate("for (const k of Object.keys(UI.docs)) if (k.startsWith('ask|')) delete UI.docs[k]; UI.askKey = null; drawAsk()")  # read again on the next open
            page.click(".ask-fab")  # opened from its key, as a person does: Escape gives the focus back to the key that stands again
            w.wait("document.querySelectorAll('#askpanel .ask-item').length === 2")  # both asks drawn
            w.shoot("ask_open")  # the bar where its key was: the agent, its lamp, the asks, the box
            page.keyboard.press("Escape"); w.settle()  # closed back into its key, which takes the focus
            w.wait("document.activeElement && document.activeElement.classList.contains('ask-fab')")  # the keyboard is where the bar was
            page.evaluate("document.activeElement.blur()")  # no ring in the next pictures
            # ---- the setup guide again, from the settings menu: the agent now signed in through the stand-in
            page.evaluate("UI.menu = true; render()"); w.settle()  # the menu
            page.click("#menu .item:has-text('설치 마법사')"); w.settle()  # its first item
            w.wait("document.querySelector('#setup:not([hidden]) .setup')")  # open
            w.shoot("setup_agent_ready")  # the agent's step, ready
            page.keyboard.press("Escape"); w.settle()  # closed by the keyboard, which goes back to the settings key
            page.evaluate("document.activeElement.blur()")  # or the keyboard's ring on that key stays in the next pictures
            page.set_input_files("#filepick", str(NOTES))  # notes, as if dropped: the run starts
            w.wait("S.tasks.autopilot && ((S.tasks.autopilot.steps || []).some((s) => s.id === 'typeset' && s.state === 'running') || S.tasks.autopilot.state !== 'running')", 300)  # at the PDFs
            w.shoot("make_running")  # the steps as they go
            w.wait("S.tasks.autopilot && S.tasks.autopilot.state !== 'running'", 900)  # the run ended
            w.settle(1200); w.shoot("make_done")  # notes hold no name: the PDFs wait, and the card asks for it
            made = page.evaluate("(S.runs || []).filter((x) => x.state === 'done').length")  # the runs so far
            page.fill('[data-key="mk-fix-name_missing"]', "홍길동")  # the fictional person's name, as a person types it
            if page.locator('[data-key="mk-fix-email_missing"]').count():  # an email asked for too
                page.fill('[data-key="mk-fix-email_missing"]', "gildong@example.com")  # a reserved example address
            page.click(".fixform button[type=submit]")  # the PDFs again
            w.wait(f"(S.runs || []).filter((x) => x.state === 'done').length > {made}", 900)  # that run ended
            w.settle(1500); w.shoot("make_fixed")  # the documents with their first pages
            browser.close()  # the browser ends before the panel
    finally:  # always, even after a failure
        srv.terminate()  # the panel stops
        srv.wait(10)  # and is gone before its folder goes
        if not a.keep:  # --keep leaves it for a look
            shutil.rmtree(tmp, ignore_errors=True)  # the temporary workspace goes
    report = w.report if w else []  # what was measured
    totals = {k: sum(r[k] for r in report) for k in KINDS}  # over every view
    (a.out / "report.json").write_text(json.dumps({"totals": totals, "errors": errors, "seconds": round(time.time() - started),  # the full report
                                                    "first_run_seconds": round(first_run, 1) if first_run else None,
                                                    "views": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    if errors:  # script errors on the page
        print("page errors:", errors[:5])  # the first few, for a look
    states = len({r["state"] for r in report})  # each state once
    if first_run is not None:  # the timed path ran
        print(f"first run: {first_run:.1f} s from the page to the example's resume (backend none)")  # the timed first run
    # the verdict line the docstring promises
    print(f"walk: {states} states x {len(LANGS) * len(THEMES) * len(VIEWS)} views, " + ", ".join(f"{k} {v}" for k, v in totals.items()) +
          (f", page errors {len(errors)}" if errors else ""))  # named only when there were any
    return 0 if not any(totals.values()) and not errors and first_run is not None else 1  # 0 only when every count is zero


if __name__ == "__main__":  # run as a script
    raise SystemExit(main())  # main's answer is the exit code
