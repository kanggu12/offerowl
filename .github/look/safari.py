"""The panel as Safari itself draws it, on the look workflow's macOS runner, driven by Safari's own WebDriver: the views
whose page slides under the sticky top bar (a fact being edited and the new-fact form on the profile), at a laptop's size
and a wide screen's, light and dark, in Korean and English, scrolled the way the walk scrolls (all at once) and the way a
person does (in small steps). Each is measured with the walk's own audit (tests/app/audit.js: words on words, words cut,
contrast, ...) and kept as Safari draws it. The same views again with each candidate rule appended to skin.css before the
panel starts (a rule added after the page has drawn redraws it and proves nothing). look.json holds the counts.

    python .github/look/safari.py <out folder>
"""
import json  # the report
import os  # environment
import subprocess  # the panel's server
import sys  # arguments
import tempfile  # the workspace
import time  # waiting
from pathlib import Path  # paths

if os.environ.get("GITHUB_ACTIONS") != "true":                # it drives Safari's own windows: a runner's only
    sys.exit(".github/look/safari.py drives Safari's windows: it runs on a CI runner only")
ROOT = Path(__file__).resolve().parents[2]                     # the repository: this file is in .github/look/
OUT = Path(sys.argv[1]).resolve()                              # the pictures and look.json
OUT.mkdir(parents=True, exist_ok=True)
AUDIT = (ROOT / "tests" / "app" / "audit.js").read_text(encoding="utf-8")   # the walk's own measure
SKIN = ROOT / "apps" / "panel" / "static" / "skin.css"          # the rules a candidate is appended to
BASE_SKIN = SKIN.read_text(encoding="utf-8")                   # as the repository has it
NAMES = ["sample_ko.json", "sample_en.json"]                   # the example's file names, allowed on screen
KINDS = ("overflow", "truncated", "overlap", "markup", "paths", "contrast", "align", "center")
VARIANTS = {                                                   # the panel as it is, then each candidate from the start
    "as-is": "",
    "canvas-isolated": "#canvas { isolation: isolate; }",
    "canvas-z0": "#canvas { position: relative; z-index: 0; }",
}
from selenium import webdriver  # noqa: E402


def serve():
    """The panel on a free port with a workspace of its own and no agent. Returns the process and its address."""
    tmp = Path(tempfile.mkdtemp(prefix="offerowl-look-"))
    (tmp / "home").mkdir()
    data = tmp / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"backend": "none"}), encoding="utf-8")
    env = {**os.environ, "HOME": str(tmp / "home"), "OFFEROWL_DESKTOP": str(tmp / "Desktop"), "OFFEROWL_PANEL_BACKEND": "none",
           "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.Popen([sys.executable, str(ROOT / "apps" / "panel" / "server.py"), "--port", "0", "--data", str(data)],
                         env=env, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    return p, p.stdout.readline().strip()


d = webdriver.Safari()
report = {"safari": d.capabilities.get("browserVersion"), "platform": d.capabilities.get("platformName"), "rows": []}


def js(expr, *args):
    return d.execute_script(expr, *args)


def wait(cond, seconds=60):
    """Until a condition on the page holds."""
    end = time.time() + seconds
    while time.time() < end:
        try:
            if js("return !!(" + cond + ")"):
                return True
        except Exception:  # noqa: BLE001  the page between two documents
            pass
        time.sleep(0.2)
    raise TimeoutError(cond)


def size(width, height):
    """The window made as large as a page `width` by `height` shows: its frame's own size taken off first."""
    d.set_window_rect(x=0, y=0, width=width + 40, height=height + 120)
    inner = js("return [innerWidth, innerHeight]")
    d.set_window_rect(x=0, y=0, width=width + 40 + (width - inner[0]), height=height + 120 + (height - inner[1]))
    time.sleep(0.4)
    return js("return [innerWidth, innerHeight]")


def click(selector, index=0):
    """A click in the page itself: a node found from here can be redrawn away before the click reaches it."""
    for _ in range(20):
        if js("const e = document.querySelectorAll(arguments[0])[arguments[1]]; if (!e) return false; e.click(); return true;", selector, index):
            return
        time.sleep(0.25)
    raise TimeoutError(selector)


def view(lang, theme):
    js("setLang(arguments[0]); localStorage.setItem('offerowl-theme', arguments[1]); applyTheme(arguments[1]); redrawAll();", lang, theme)
    time.sleep(0.6)


def measure(name):
    """The audit's counts, the bar's state, and the picture."""
    found = js("return (" + AUDIT + ")(arguments[0]);", NAMES)
    bar = js("const t = document.getElementById('top'); return { y: Math.round(scrollY), under: t.classList.contains('under') };")
    d.save_screenshot(str(OUT / f"{name}.png"))
    row = {"view": name, **bar, **{k: len(found[k]) for k in KINDS}, "details": {k: found[k][:4] for k in KINDS if found[k]}}
    report["rows"].append(row)
    print(name, {k: row[k] for k in ("y", "under", *KINDS) if row[k]}, flush=True)


def scrolled(selector, name):
    """The part scrolled to the top of the window all at once (as the walk does), then from the top in small steps (as a
    person's wheel does), each measured once the page has come to rest."""
    js("document.querySelector(arguments[0]).scrollIntoView({ block: 'start' });", selector)
    time.sleep(1.2)
    measure(name + "_jump")
    js("window.scrollTo(0, 0);")
    time.sleep(0.6)
    for _ in range(80):  # 60 px a step, a frame or two apart, until the part reaches the top
        if js("return document.querySelector(arguments[0]).getBoundingClientRect().top <= 0;", selector):
            break
        js("window.scrollBy(0, 60);")
        time.sleep(0.05)
    time.sleep(1.2)
    measure(name + "_steps")


try:
    for variant, rule in VARIANTS.items():
        SKIN.write_text(BASE_SKIN + ("\n" + rule + "\n" if rule else ""), encoding="utf-8")   # before the panel starts
        srv, base = serve()
        try:
            d.get(base + "?lang=ko")
            js("try { localStorage.setItem('offerowl-setup-seen', '1'); } catch (_) {}")   # the setup guide is not the subject
            d.get(base + "?lang=ko")
            wait("typeof S !== 'undefined' && S && S.agent && S.agent.state !== 'checking' && document.querySelector('.make-in .drop')", 120)
            click("[data-act=example]")                                                  # the fictional person, as the walk loads it
            wait("document.getElementById('canvas').dataset.ready === 'resume'", 180)  # its resume drawn: its facts kept
            js("go('profile'); UI.filter = 'kept'; render();")
            wait("document.querySelectorAll('.fact .acts button').length > 1", 120)
            for w, h in ((1440, 900), (2560, 1440)):
                size(w, h)
                for lang in ("ko", "en"):
                    for theme in ("light", "dark"):
                        view(lang, theme)
                        js("UI.factAdd = false; UI.factEdit = null; go('profile'); UI.filter = 'kept'; render();")
                        time.sleep(0.6)
                        click(".fact .acts button", 1)                                       # edit one fact
                        time.sleep(0.6)
                        scrolled(".fact", f"{variant}_editing_{lang}_{theme}_{w}")
                        js("window.scrollTo(0, 0); UI.factEdit = null; forget('f-'); UI.factAdd = true; render();")   # the new-fact form
                        time.sleep(0.8)
                        scrolled(".add-fact", f"{variant}_adding_{lang}_{theme}_{w}")
        except Exception:
            d.save_screenshot(str(OUT / f"{variant}_failed.png"))                       # what Safari showed when it stopped
            (OUT / f"{variant}_failed.txt").write_text(str(js("return location.href + '\\n' + document.body.innerText.slice(0, 4000);")), encoding="utf-8")
            raise
        finally:
            srv.terminate()
            srv.wait(timeout=20)
finally:
    SKIN.write_text(BASE_SKIN, encoding="utf-8")                                      # the repository as it was
    d.quit()
    (OUT / "look.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
bad = [r["view"] for r in report["rows"] if any(r[k] for k in KINDS)]
print(f"Safari {report['safari']}: {len(report['rows'])} views, {len(bad)} with a finding: {', '.join(bad) or 'none'}")
