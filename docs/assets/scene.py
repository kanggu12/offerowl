"""The panel in one moment of one workspace, for the pictures that show a whole run: the README's four views and the user
guide's pictures of Make. The walk (tests/app/walk.py) moves through fifty states and fails a run on purpose to show the fix,
so its pictures of Make come from different moments; this scene is a person's first good run, from start to end:

    python3 docs/assets/scene.py DIR [--guide docs/assets]   # DIR: the four views for docs/assets/screens.py
    python3 docs/assets/screens.py DIR                        # docs/assets/screens-*.png, banner.png

1. A new workspace with the agent signed in (the stand-in behind a fictional Claude Code account, as the walk uses it).
2. Make before any run (guide-make, guide-phone), once the setup guide that opens by itself is closed.
3. The example person's file and a fictional posting dropped together: one run, caught while it makes the PDFs (guide-make-run).
4. Make while the run makes the PDFs, then, once it has ended, the profile, a sentence and its evidence, and the application's
   fit: the README's four views, in English at 1440 x 900, light and dark, named as the walk names its pictures.

The stand-in writes placeholder English ("Worked on this as the record describes"), so the English edition of this run does
not pass every check a real agent's would; the run must end with every step done and the Korean edition passing its checks.

Nothing leaves the PC: the stand-in answers, the PDFs go to a temporary Desktop.
"""
import argparse  # the folders
import json  # the settings file
import os  # the environment
import pathlib  # paths
import shutil  # the temporary folder
import subprocess  # the panel's server
import sys  # the interpreter
import tempfile  # the workspace, home and Desktop of this scene

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT / "tests" / "app"))  # the walk's helpers: the stand-in's home, the fixtures, the settle rule
import walk  # noqa: E402  fake_home, SAMPLE, POSTING, SETTLED

from playwright.sync_api import sync_playwright  # noqa: E402  the browser

GUIDE = {"guide-make": (1600, 1000), "guide-phone": (390, 844)}  # Make before a run: the guide's two sizes
RUN = (1600, 1000)  # the run in progress, as the guide shows it
VIEW = (1440, 900)  # the README's four views


def look(page, theme: str, w: int, h: int) -> None:
    """The page in English, in one theme, at one size, drawn again and come to rest."""
    page.set_viewport_size({"width": w, "height": h})  # the window
    page.evaluate("(t) => { setLang('en'); localStorage.setItem('offerowl-theme', t); applyTheme(t); redrawAll(); }", theme)  # the page's own switches
    page.wait_for_timeout(450)  # its layout settles
    page.evaluate(walk.SETTLED)  # what moves has come to rest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scene.py", description="The panel in one run, for the README's views and the guide's Make.")
    ap.add_argument("out", type=pathlib.Path, help="where the four views go (then: screens.py OUT)")
    ap.add_argument("--guide", type=pathlib.Path, default=None, help="also write guide-make, guide-phone and guide-make-run here")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)  # a new folder is fine
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-scene-"))  # data, home, Desktop
    home, bin_ = walk.fake_home(tmp)  # a fictional sign-in and a `claude` that is the stand-in
    data = tmp / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"backend": "auto"}), encoding="utf-8")  # the agent found, as on a person's PC
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "OFFEROWL_DESKTOP": str(tmp / "Desktop"),
           "OFFEROWL_LLM_LOG": str(tmp / "calls.jsonl"), "PYTHONDONTWRITEBYTECODE": "1"}
    for k in ("OFFEROWL_PANEL_AGENT", "OFFEROWL_PANEL_BACKEND", "OFFEROWL_LLM", "OFFEROWL_LLM_URL", "OFFEROWL_LLM_MODEL"):
        env.pop(k, None)  # nothing from the caller's shell
    srv = subprocess.Popen([sys.executable, str(ROOT / "apps" / "panel" / "server.py"), "--port", "0", "--data", str(data)],
                           env=env, stdout=subprocess.PIPE, text=True)  # its first line is the address
    base = srv.stdout.readline().strip()
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()  # headless
            page = b.new_context(viewport={"width": VIEW[0], "height": VIEW[1]}, locale="en-US", bypass_csp=True).new_page()
            page.goto(base + "?lang=en")
            page.wait_for_function("document.querySelector('#setup:not([hidden]) .setup')", timeout=60000)  # it opens by itself on a new workspace
            page.wait_for_function("S.agent.state === 'ready'", timeout=60000)  # the stand-in signed in
            page.click("#setup .setup-close")  # closed as most people close it
            page.wait_for_function("document.getElementById('setup').hidden")
            page.evaluate("document.activeElement.blur()")  # no ring on the key it went back to
            page.mouse.move(VIEW[0] - 2, VIEW[1] - 2)  # the pointer off the views: left where the close key was, it hovered Make's chain
            if a.guide:  # Make before any run
                for name, (w, h) in GUIDE.items():
                    for theme in ("light", "dark"):
                        look(page, theme, w, h)
                        page.screenshot(path=str(a.guide / f"{name}-{theme}.png"))
            look(page, "light", *VIEW)
            page.fill("[data-key=mk-posting]", walk.POSTING.read_text(encoding="utf-8"))  # the posting first, so the run makes this job's documents
            page.set_input_files("#filepick", str(walk.SAMPLE))  # the example's file, as if dropped: the one action
            page.wait_for_function("S.tasks.autopilot && (S.tasks.autopilot.steps || []).some((s) => s.id === 'typeset' && s.state === 'running')",
                                   timeout=600000, polling=100)  # caught at the PDFs
            for theme in ("light", "dark"):  # the README's Make: the band following the files, the steps lighting up
                look(page, theme, *VIEW)
                page.screenshot(path=str(a.out / f"01_make_run_en_{theme}_{VIEW[0]}x{VIEW[1]}.png"))
            if a.guide:  # the run in progress, at the guide's width and as tall as its columns: the run's card stands under the agent's
                look(page, "light", *RUN)  # laid out at that width
                tall = page.evaluate("() => Math.ceil(Math.max(...[...document.querySelectorAll('#canvas .flow-col .card')].map((e) => e.getBoundingClientRect().bottom + window.scrollY)) + 24)")
                for theme in ("light", "dark"):
                    look(page, theme, RUN[0], max(RUN[1], tall))  # the head, the band, the notes and every card of the run in one picture
                    page.screenshot(path=str(a.guide / f"guide-make-run-{theme}.png"))
            if not page.evaluate("(S.tasks.autopilot.steps || []).some((s) => s.id === 'typeset' && s.state === 'running')"):  # the four pictures one moment
                raise SystemExit("the PDFs were made before the run's pictures were taken: run it again")
            page.wait_for_function("S.tasks.autopilot.state !== 'running'", timeout=900000, polling=300)  # it ends
            steps = page.evaluate("Object.fromEntries((S.tasks.autopilot.steps || []).map((s) => [s.id, s.state]))")
            print("run:", page.evaluate("S.tasks.autopilot.state"), json.dumps(steps), flush=True)
            checks = page.evaluate("Object.fromEntries(Object.entries(((S.jobs || []).find((j) => j.id === S.job) || {}).builds || {}).map(([l, b]) => [l, [...(b.issues || []), ...(((b.cover || {}).issues) || [])]]))")
            print("checks:", json.dumps(checks, ensure_ascii=False), flush=True)  # each edition's failed checks (the English one holds the stand-in's placeholder)
            if any(v not in ("done", "skipped") for v in steps.values()) or checks.get("ko"):  # a step that did not work, or a Korean edition that failed
                raise SystemExit("the run did not end well: " + json.dumps(steps))
            # the names screens.py reads. The resume shown is the general edition, in the profile's own sentences: the job's
            # edition holds the stand-in's draft, which repeats its evidence's words and is no picture of a real one
            views = [("profile_facts", "go('profile'); UI.filter = 'kept'; render()"),
                     ("jobs_fit", "go('jobs'); UI.jobTab = 'fit'; render()"),
                     ("evidence_selected", "act('/api/v1/jobs/select', { job: '-general' }).then(() => { UI.doc = 'resume'; UI.mode = 'live'; go('documents'); })")]
            for n, (state, js) in enumerate(views, 2):
                page.evaluate(js)
                page.wait_for_timeout(600)
                if state == "evidence_selected":  # a sentence clicked, its passages beside it
                    page.wait_for_function("document.getElementById('canvas').dataset.ready === 'resume'", timeout=60000)
                    page.locator(".sheet .s[data-sid]").nth(4).click()
                    page.wait_for_timeout(500)
                for theme in ("light", "dark"):
                    look(page, theme, *VIEW)
                    page.screenshot(path=str(a.out / f"{n:02d}_{state}_en_{theme}_{VIEW[0]}x{VIEW[1]}.png"))
                print("view:", state, flush=True)
            page.evaluate("go('make')")
            page.wait_for_timeout(500)
            print("band:", page.evaluate("[S.materials.length, S.facts.counts.kept]"), flush=True)  # the Make view's numbers, for the banner's chain
            b.close()
    finally:
        srv.terminate()
        srv.wait(timeout=20)
        shutil.rmtree(tmp, ignore_errors=True)  # the workspace, its PDFs and its Desktop go
    return 0


if __name__ == "__main__":
    sys.exit(main())
