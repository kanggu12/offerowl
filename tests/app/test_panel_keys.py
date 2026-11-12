#!/usr/bin/env python3
"""The panel in a headless browser, for what the walk's pictures cannot show: where the keyboard and the page stay when the
panel draws itself again, typed words that must all be saved, a choice in a list kept across a redraw, the tabs of an
application, and a file dropped on the board. On the fictional example only; skipped where Playwright's Chromium is missing.

    python3 -m unittest tests/app/test_panel_keys.py -v
"""
import json  # the settings file
import os  # environment
import pathlib  # paths
import shutil  # the temporary folder
import subprocess  # the panel's server
import sys  # the interpreter
import tempfile  # a data folder of its own
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
POSTING = ROOT / "tests" / "app" / "fixtures" / "posting_ko.md"  # a fictional posting

try:  # the browser driver, when it is installed
    from playwright.sync_api import sync_playwright
except ImportError:  # no Playwright here
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class PanelKeys(unittest.TestCase):
    """One panel and one page for the class: the example, then each check in order (they share the page's state)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-keys-"))  # data, home, desktop
        (cls.tmp / "home").mkdir()
        data = cls.tmp / "data"
        data.mkdir()
        (data / "settings.json").write_text(json.dumps({"backend": "none"}), encoding="utf-8")  # no agent
        env = {**os.environ, "HOME": str(cls.tmp / "home"), "OFFEROWL_DESKTOP": str(cls.tmp / "Desktop"),
               "OFFEROWL_LLM_LOG": str(cls.tmp / "calls.jsonl"), "PYTHONDONTWRITEBYTECODE": "1"}  # nothing of this PC's
        for k in ("OFFEROWL_PANEL_AGENT", "OFFEROWL_PANEL_BACKEND", "OFFEROWL_LLM"):
            env.pop(k, None)
        cls.srv = subprocess.Popen([sys.executable, str(ROOT / "apps" / "panel" / "server.py"), "--port", "0", "--data", str(data)],
                                   env=env, stdout=subprocess.PIPE, text=True, encoding="utf-8")  # its first line is the address
        base = cls.srv.stdout.readline().strip()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()  # headless
        except Exception as exc:  # noqa: BLE001  Playwright without its browser
            cls.pw.stop()
            cls.srv.terminate()
            cls.srv.wait(timeout=20)  # a skipped class has no tearDownClass: the server is reaped here
            cls.srv.stdout.close()
            raise unittest.SkipTest(f"no Chromium for Playwright: {exc}")
        ctx = cls.browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR", bypass_csp=True)
        ctx.add_init_script("try { localStorage.setItem('offerowl-setup-seen', '1'); } catch (_) {}")  # the setup guide is not the subject here
        cls.page = ctx.new_page()
        cls.errors = []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.goto(base + "?lang=en")
        cls.page.wait_for_function("document.querySelector('[data-act=example]')", timeout=60000)
        cls.page.click("[data-act=example]")  # the fictional person's resume
        cls.page.wait_for_function("document.getElementById('canvas').dataset.ready === 'resume'", timeout=60000)
        cls.page.wait_for_timeout(600)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.srv.terminate()
        cls.srv.wait(timeout=20)
        cls.srv.stdout.close()  # the pipe its address came through goes with it
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_1_a_redraw_keeps_the_reader_s_place_and_the_sentence(self):
        p = self.page
        # every page of the resume laid out first: on a slow run the document was still 1,607 px tall and the scroll stopped at 707
        p.wait_for_function("document.documentElement.scrollHeight >= 1800 + window.innerHeight", timeout=30000)
        p.evaluate("window.scrollTo(0, 1800)")
        p.wait_for_timeout(300)
        self.assertEqual(1800, p.evaluate("Math.round(window.scrollY)"))  # the place the redraw must keep
        p.evaluate("$('canvas')._key = null; render()")  # the same document drawn again, as a state change does
        p.wait_for_timeout(700)
        self.assertEqual(1800, p.evaluate("Math.round(window.scrollY)"))  # not thrown back to the top
        sid = p.evaluate("document.querySelectorAll('.sheet .s[data-sid]')[6].dataset.sid")
        p.focus(f'.sheet .s[data-sid="{sid}"]')
        p.keyboard.press("Enter")  # its evidence, by the keyboard
        p.wait_for_timeout(800)
        self.assertEqual(sid, p.evaluate("document.activeElement.dataset.sid || ''"))  # the keyboard stays on it

    def test_2_escape_gives_the_keyboard_back(self):
        p = self.page
        p.evaluate("UI.sel = null; render()")
        p.focus("#more")
        p.keyboard.press("Enter")  # the settings menu
        p.wait_for_timeout(300)
        p.focus("#menu button.item")  # the keyboard inside it, on its first item
        p.keyboard.press("Escape")
        p.wait_for_timeout(300)
        self.assertEqual("more", p.evaluate("document.activeElement.id"))  # back on its key, not the top of the page
        p.click(".barchip")  # the agent's panel
        p.wait_for_timeout(300)
        p.focus(".barpop .pop button, .barpop .pop [role=switch]")  # a key inside it
        p.keyboard.press("Escape")
        p.wait_for_timeout(300)
        self.assertIn("barchip", p.evaluate("document.activeElement.className"))

    def test_3_a_fact_s_key_keeps_the_keyboard_on_that_fact(self):
        p = self.page
        p.evaluate("go('profile'); UI.filter = 'all'; render()")
        p.wait_for_timeout(700)
        keys = p.evaluate("[...document.querySelectorAll('[data-key^=\"fact-drop-\"]')].map(e => e.dataset.key)")
        target, first = keys[3], keys[0]
        p.focus(f'[data-key="{target}"]')
        p.keyboard.press("Enter")  # dropped: its key now reads otherwise
        p.wait_for_timeout(900)
        self.assertEqual(target, p.evaluate("document.activeElement.dataset.key"))  # still that fact's key, not the first "Drop"
        p.keyboard.press("Enter")  # pressed again: put back
        p.wait_for_timeout(900)
        self.assertEqual("false", p.evaluate(f"document.querySelector('[data-key=\"{first}\"]').getAttribute('aria-pressed')"))  # the first fact untouched

    def test_4_two_fields_typed_at_once_are_both_saved(self):
        p = self.page
        p.evaluate("UI.editDetails = true; render()")
        p.wait_for_timeout(500)
        p.fill('[data-key="d-name"]', "Gildong Hong")
        p.fill('[data-key="d-phone"]', "010-1111-2222")  # within the same pause, as autofill types
        p.wait_for_timeout(1600)
        self.assertEqual(["Gildong Hong", "010-1111-2222"], p.evaluate("[S.details.name, S.details.phone]"))

    def test_5_a_choice_in_a_list_survives_a_redraw(self):
        p = self.page
        p.evaluate("UI.editDetails = false; UI.factAdd = true; render()")
        p.wait_for_timeout(500)
        key = p.evaluate("document.querySelector('.add-fact select').dataset.key")
        last = p.evaluate("[...document.querySelectorAll('.add-fact select option')].map(o => o.value).pop()")
        p.select_option(f'[data-key="{key}"]', last)
        p.wait_for_timeout(200)
        p.evaluate("redrawAll()")  # as a resize or a state change draws it
        p.wait_for_timeout(400)
        self.assertEqual(last, p.evaluate(f"document.querySelector('[data-key=\"{key}\"]').value"))
        p.evaluate("UI.factAdd = false; forget('f-'); render()")

    def test_6_an_application_s_tabs_take_the_arrows(self):
        p = self.page
        p.evaluate("go('jobs')")
        p.wait_for_timeout(400)
        p.fill("[data-key=j-posting]", POSTING.read_text(encoding="utf-8"))
        p.click("form button[type=submit]")
        p.wait_for_function("S.jobs.length === 1 && fitOf(S.job) !== null", timeout=60000)
        p.evaluate("UI.jobTab = 'fit'; render()")
        p.wait_for_timeout(400)
        p.focus("#jtab-fit")
        p.keyboard.press("ArrowRight")
        p.wait_for_timeout(400)
        self.assertEqual(("docs", "jtab-docs"), (p.evaluate("UI.jobTab"), p.evaluate("document.activeElement.id")))
        self.assertEqual("-1,0,-1,-1,-1", p.evaluate("[...document.querySelectorAll('.jtabs [role=tab]')].map(b => b.tabIndex).join(',')"))  # one tab takes Tab

    def test_7_a_file_dropped_on_the_board_is_not_a_card(self):
        p = self.page
        p.evaluate("window.__calls = []; const a = api; api = (path, b) => { window.__calls.push(path); return a(path, b); }; 0")  # every request the page makes
        p.evaluate("UI.jobsMode = 'board'; render()")
        p.wait_for_timeout(500)
        p.evaluate("""() => { const col = document.querySelector('.board .col, .board [data-stage], .tcol'); const dt = new DataTransfer();
            dt.items.add(new File(['notes'], 'notes.txt', { type: 'text/plain' }));
            col.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); }""")
        p.wait_for_timeout(1200)
        self.assertNotIn("/api/v1/tracker/edit", p.evaluate("window.__calls"))  # no card moved with an empty name

    def test_7b_the_interview_tab_draws_its_parts_and_keeps_the_question_typed(self):
        # the contents, the search and the script cards (kit.js), the deck and practice (interview.js) are drawn by the panel:
        # no frame on the tab, and the view itself is kept through a document fetched for another view (Insights, three seconds
        # after the page), a window dragged narrower and a visit to another part, with the question typed into it
        p = self.page
        p.evaluate("UI.jobsMode = 'list'; render()")
        p.evaluate("act('/api/v1/interview/kit', { job: S.job, lang: 'ko' })")  # the question map and the kit's files, no model
        p.wait_for_function("boardOf(S.job) && boardOf(S.job).ready", timeout=60000)
        scripts = (ROOT / "examples" / "interview" / "jobs" / "gamma-platform" / "interview" / "qa.md").read_text(encoding="utf-8")  # the fictional example's scripts
        sent = p.evaluate("""async (text) => (await fetch('/api/v1/interview/scenes?job=' + encodeURIComponent(S.job), { method: 'POST', body: new Blob([text]),
            headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': 'qa.md' } })).status""", scripts)   # as the "Add scenes you wrote" key sends a file
        self.assertEqual(200, sent)
        p.evaluate("go('interview'); UI.ivPart = 'search'; render()")
        p.wait_for_selector("#canvas .kit .kit-q", timeout=120000)
        self.assertEqual(0, p.evaluate("document.querySelectorAll('#canvas iframe').length"))  # the panel's own parts, no page in a frame
        p.evaluate("document.querySelector('#canvas .kit').__mark = 'kept'")  # a view made again loses this
        p.fill("#canvas .kit .kit-q", "argo cd")
        p.wait_for_timeout(700)
        self.assertGreater(p.evaluate("document.querySelectorAll('#canvas .kit .kit-card').length"), 0)  # the answers on the board
        held = "() => [document.querySelector('#canvas .kit').__mark, document.querySelector('#canvas .kit .kit-q').value]"  # the view and its question
        p.evaluate("UI.docsVer++; render()")  # a document for another view arrived
        p.wait_for_timeout(500)
        self.assertEqual(["kept", "argo cd"], p.evaluate(held))
        p.set_viewport_size({"width": 1300, "height": 900})  # the window dragged narrower
        p.wait_for_timeout(700)
        self.assertEqual(["kept", "argo cd"], p.evaluate(held))
        p.set_viewport_size({"width": 1440, "height": 900})
        p.wait_for_timeout(700)
        p.evaluate("UI.ivPart = 'deck'; render()")  # the deck, drawn by the panel too
        p.wait_for_selector("#canvas .ivdeck .deck-scene", timeout=60000)
        self.assertEqual(0, p.evaluate("document.querySelectorAll('#canvas iframe').length"))
        p.evaluate("UI.ivPart = 'search'; render()")  # back to the scripts: the same view, the question still in its box
        p.wait_for_selector("#canvas .kit .kit-q", timeout=20000)
        self.assertEqual(["kept", "argo cd"], p.evaluate(held))
        p.evaluate("UI.ivPart = 'map'; render()")  # and a part with no view of its own draws on every change again
        p.wait_for_timeout(500)
        before = p.evaluate("$('canvas')._key")
        p.evaluate("UI.docsVer++; render()")
        self.assertNotEqual(before, p.evaluate("$('canvas')._key"))

    def test_8_no_page_errors(self):
        self.assertEqual([], self.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
