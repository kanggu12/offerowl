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
        base = cls.base = cls.srv.stdout.readline().strip()  # kept for the tests that open a second window
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()  # headless
        except Exception as exc:  # noqa: BLE001  Playwright without its browser
            cls.pw.stop()
            cls.srv.terminate()
            cls.srv.wait(timeout=20)  # a skipped class has no tearDownClass: the server is reaped here
            cls.srv.stdout.close()
            raise unittest.SkipTest(f"no Chromium for Playwright: {exc}")
        cls.errors = []
        try:  # a class whose start fails gets no tearDownClass: without this its server and browser outlived the run
            ctx = cls.browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR", bypass_csp=True)
            ctx.add_init_script("try { localStorage.setItem('offerowl-setup-seen', '1'); } catch (_) {}")  # the setup guide is not the subject here
            cls.page = ctx.new_page()
            cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
            cls.page.goto(base + "?lang=en")
            cls.page.wait_for_function("document.querySelector('[data-act=example]')", timeout=60000)
            cls.page.click("[data-act=example]")  # the fictional person's resume
            cls.page.wait_for_function("document.getElementById('canvas').dataset.ready === 'resume'", timeout=60000)
            cls.page.wait_for_timeout(600)
        except BaseException:
            sys.stderr.write(f"the page did not start: errors {cls.errors[:5]}\n")  # what the page raised, for the reader of the log
            cls.tearDownClass()  # the browser, the server and the folder go as at the end
            raise

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
        p.wait_for_selector("#canvas .ivdeck .deck-page > *", timeout=60000)  # its first tab drawn (the posting's table, or the first part)
        self.assertEqual(0, p.evaluate("document.querySelectorAll('#canvas iframe').length"))
        p.evaluate("UI.ivPart = 'search'; render()")  # back to the scripts: the same view, the question still in its box
        p.wait_for_selector("#canvas .kit .kit-q", timeout=20000)
        self.assertEqual(["kept", "argo cd"], p.evaluate(held))
        p.evaluate("UI.ivPart = 'map'; render()")  # and a part with no view of its own draws on every change again
        p.wait_for_timeout(500)
        before = p.evaluate("$('canvas')._key")
        p.evaluate("UI.docsVer++; render()")
        self.assertNotEqual(before, p.evaluate("$('canvas')._key"))

    def test_7c_a_large_kit_s_contents_fit_one_screen_and_name_a_split_section_again(self):
        # a kit of some 180 scripts at 1920 x 1080 and 2560 x 1300: the contents fold their largest groups until they fit the
        # view with no scroll, and a section that runs on into another column says its name again at that column's top. The
        # section keys' row above them is never squeezed while they are fitted (a tall contents took 21 px of its height, so
        # the folding was measured in a room the view did not have, and the contents scrolled)
        p = self.page
        words = ["로그 확인", "배포 되돌리기", "노드 교체", "알림 정리", "디스크 부족", "인증서 만료", "메모리 누수", "느린 질의",
                 "캐시 무효화", "권한 요청", "작업 대기열", "백업 복구"]  # fictional script titles
        parts = []
        for k, letter in enumerate("BCFGHIJLMNPSTVW"):  # letters the example kit does not use
            parts.append(f"## {letter}. 묶음 {letter}: {words[k % len(words)]}와 그 밖의 상황\n")
            for n in range(1, 9 + (k * 5) % 9):  # 8 to 16 scripts a section
                t = words[(k + n) % len(words)]
                parts.append(f"### {letter}{n}. {t}, 그리고 {words[(k * n) % len(words)]}이 겹칠 때 / When {n} things meet\n"
                             f"**면접관** What would you do first?\n**해석** 무엇부터 하겠어요?\n**나** I would read the logs.\n**해석** 로그부터 읽겠습니다.\n")
        sent = p.evaluate("""async (text) => (await fetch('/api/v1/interview/scenes?job=' + encodeURIComponent(S.job), { method: 'POST', body: new Blob([text]),
            headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': 'more.md' } })).status""", "\n".join(parts))
        self.assertEqual(200, sent)
        state = """() => { const el = document.querySelector('#canvas .kit-cards'), toc = el && el.querySelector('.kit-toc'); if (!toc) return null;
            const menu = document.querySelector('#canvas .kit-menu'), key = menu.querySelector('.btn');
            const runs = [...toc.querySelectorAll('.kit-tg')].reduce((n, b) => n + Math.max(0, b.getClientRects().length - 1), 0);
            return { fits: toc.offsetHeight <= el.clientHeight - 4, scroll: el.style.overflowY || '', runs, named: toc.querySelectorAll('.kit-cont').length,
                     squeezed: Math.round(menu.getBoundingClientRect().height) < Math.round(key.getBoundingClientRect().height) }; }"""
        try:
            for w, h in ((1920, 1080), (2560, 1300)):
                p.set_viewport_size({"width": w, "height": h})
                p.evaluate("go('interview'); UI.ivPart = 'map'; render()")  # away, so the scripts' part is drawn anew with the new file
                p.wait_for_timeout(300)
                p.evaluate("go('interview'); UI.ivPart = 'search'; render()")
                p.wait_for_selector("#canvas .kit .kit-home", timeout=60000)
                p.evaluate("document.querySelector('#canvas .kit .kit-home').click()")  # the contents
                p.wait_for_function("!!document.querySelector('#canvas .kit-toc') && !!document.querySelector('#canvas .kit-menu [data-g^=\"W.\"]')", timeout=60000)   # the new file's sections are in
                p.wait_for_timeout(900)  # fitted again once the fonts are in
                got = p.evaluate(state)
                self.assertEqual(got["scroll"], "", (w, h, got))  # one screen, no scroll
                self.assertTrue(got["fits"], (w, h, got))
                self.assertFalse(got["squeezed"], (w, h, got))  # the keys' row keeps its height
                self.assertEqual(got["runs"], got["named"], (w, h, got))  # every run into another column names its section there
        finally:
            p.set_viewport_size({"width": 1440, "height": 900})

    def test_7d_a_round_s_length_comes_from_its_notes(self):
        # the "today's interview" line ends a round when its length has passed: read from its notes as people write them
        got = self.page.evaluate("""() => ["15:00~15:30, a call", "1시간 30분 기술 면접", "90분", "2h panel", "45 min",
            "10분 전 입장, 60분", "10분 전 입장", ""].map((notes) => roundMinutes({ notes }))""")
        self.assertEqual([30, 90, 90, 120, 45, 60, 60, 60], got)  # "10분 전 입장" is when to be there, not how long; none: an hour

    def test_7e_a_draw_asked_for_inside_another_waits_for_it(self):
        # a board card's next-step box has the keyboard when the page draws again (a poll, a change of look): taking the box
        # away blurs it, and its blur asks for a draw inside that draw; the page stopped half drawn with an error before
        p = self.page
        p.evaluate("UI.jobsMode = 'board'; go('jobs')")
        p.wait_for_timeout(500)
        p.evaluate("editNext(S.jobs[0].id)")  # the box open, as the card's key or its words open it
        p.wait_for_function("document.activeElement && document.activeElement.classList.contains('tnext')", timeout=5000)
        p.evaluate("redrawAll()")  # the whole page drawn again while the box has the keyboard (raised NotFoundError here)
        p.wait_for_timeout(300)
        self.assertEqual(1, p.locator(".tcard input.tnext").count())  # a redraw keeps the box open, the keyboard in it: typing goes on
        self.assertTrue(p.evaluate("document.activeElement && document.activeElement.classList.contains('tnext')"))
        p.evaluate("document.activeElement.blur()")  # the person leaves it
        p.wait_for_timeout(300)
        self.assertEqual(0, p.locator(".tcard input.tnext").count())  # then it closes
        p.evaluate("UI.jobsMode = 'list'; render()")

    def test_7f_a_window_opened_on_an_application_keeps_it_and_the_others_keep_theirs(self):
        # the Interview tab's "Open in a window" (/?job=<id>&show=scripts) and an old kit link (/kit/<id>/#practice, ?q=): the
        # window shows that application without choosing it for the whole server, so the first window stays on its own
        # application through its polls (it was switched within 6 s, its question emptied); an old link's part and question
        # are read (#practice was left in the address over the search, ?q= was dropped)
        p = self.page
        p.evaluate("UI.jobsMode = 'list'; go('interview'); UI.ivPart = 'search'; render()")
        first = p.evaluate("S.job")  # the application of test 6, whose kit test 7b made
        other = p.evaluate("""async (text) => (await act('/api/v1/jobs', { company: 'Delta Payments', role: 'SRE', posting: text })).job""", POSTING.read_text(encoding="utf-8"))
        p.evaluate("(jid) => openApplication(jid, 'interview')", first)  # the new job was put in view: the first one again, as the person had it
        p.wait_for_function("(jid) => S.job === jid", arg=first, timeout=10000)
        second = p.context.new_page()
        try:
            second.goto(self.base.rstrip("/") + f"/?job={other}&show=scripts&lang=en#practice")
            second.wait_for_function("(jid) => typeof S !== 'undefined' && S && S.job === jid && UI.view === 'jobs'", arg=other, timeout=30000)
            self.assertEqual(["practice", ""], second.evaluate("[UI.ivPart, location.hash]"))  # the part the old link named, and the address read
            p.evaluate("refresh()")  # the first window's poll
            p.wait_for_timeout(800)
            self.assertEqual(first, p.evaluate("S.job"))  # still its own application
            second.evaluate("refresh()")  # and the second window's poll keeps its own
            second.wait_for_timeout(800)
            self.assertEqual(other, second.evaluate("S.job"))
            second.goto(self.base.rstrip("/") + f"/kit/{first}/?q=kubernetes")  # an old search link of the first application's kit
            second.wait_for_function("() => !!document.querySelector('#canvas .kit .kit-q')", timeout=60000)
            second.wait_for_timeout(600)
            self.assertEqual("kubernetes", second.evaluate("document.querySelector('#canvas .kit .kit-q').value"))   # asked in its scripts
            self.assertEqual("", second.evaluate("location.search.includes('q=') ? location.search : ''"))  # and read once
            second.evaluate("(jid) => openApplication(jid, 'fit')", other)  # an application chosen in that window: the server's choice from now on
            second.wait_for_function("(jid) => S.job === jid && !UI.ownJob", arg=other, timeout=10000)
        finally:
            second.close()
        p.evaluate("(jid) => openApplication(jid, 'interview')", first)  # as the later tests expect it
        p.wait_for_function("(jid) => S.job === jid", arg=first, timeout=10000)

    def test_7o_an_email_that_is_no_address_waits_marked_and_is_never_sent(self):
        # it was saved as typed and printed on the resumes (A4-03); its note pushed the name beside it 10 px down (A4-02); Esc
        # pressed on the page left the form open (A4-11)
        p = self.page
        p.evaluate("go('profile'); UI.factAdd = false; UI.editDetails = true; render()")
        p.wait_for_timeout(500)
        before = p.evaluate("S.details.email || ''")  # what the resumes print now
        p.fill('[data-key="d-email"]', "gildong.example")  # no @: no address
        p.locator('[data-key="d-email"]').blur()  # the person leaves the field
        p.wait_for_timeout(1600)  # past the save's pause
        self.assertEqual(before, p.evaluate("S.details.email || ''"))  # never sent
        self.assertEqual("true", p.evaluate("document.querySelector('[data-key=d-email]').getAttribute('aria-invalid')"))  # marked, its words under it
        tops = p.evaluate("['d-name', 'd-email'].map((k) => Math.round(document.querySelector(`[data-key=${k}]`).getBoundingClientRect().top))")
        self.assertEqual(tops[0], tops[1], tops)  # the first row lined up with the note under the email
        p.fill('[data-key="d-phone"]', "010-3333-4444")  # another field saved: the state comes back and the form is drawn again
        p.wait_for_timeout(1600)
        self.assertEqual(["gildong.example", "true"], p.evaluate("['value', 'aria-invalid'].map((a) => a === 'value' ? document.querySelector('[data-key=d-email]').value : document.querySelector('[data-key=d-email]').getAttribute(a))"))   # the typed words and their mark kept
        p.evaluate("document.activeElement && document.activeElement.blur()")  # the keyboard on the page, not in the form
        p.keyboard.press("Escape")
        p.wait_for_timeout(400)
        self.assertEqual(0, p.locator('[data-key="d-email"]').count())  # closed as from inside
        p.evaluate("UI.editDetails = true; render()")
        p.wait_for_timeout(400)
        self.assertEqual("gildong.example", p.evaluate("document.querySelector('[data-key=d-email]').value"))  # opened again: the words still wait, marked
        p.fill('[data-key="d-email"]', "hong.gildong@example.org")  # an address
        p.wait_for_timeout(1600)
        self.assertEqual("hong.gildong@example.org", p.evaluate("S.details.email"))  # saved
        p.evaluate("UI.editDetails = false; render()")

    def test_7p_a_note_never_lies_over_the_bar_s_keys(self):
        # a long note took the room of the agent's chip, or of all the views, and hid them while it showed; on a phone every
        # note covered the wordmark and the keys (A4-07, D4-13)
        p = self.page
        words = "Kept the fact: " + "a sentence long enough to need more than the bar's room " * 3
        try:
            for w, hgt in ((1440, 900), (1280, 800), (861, 700), (390, 844)):
                p.set_viewport_size({"width": w, "height": hgt})
                p.wait_for_timeout(500)
                p.evaluate("(t) => toast(t, { words: 'Undo', run: () => {} }, 'done')", words)
                p.wait_for_timeout(450)
                got = p.evaluate("""() => { const t = document.getElementById('toast').getBoundingClientRect();
                  const keys = [...document.querySelectorAll('#top .brand, #top .views button, #top .barchip, #top .actions > .btn')].filter((x) => x.getBoundingClientRect().width);
                  const over = keys.filter((x) => { const r = x.getBoundingClientRect(); return r.right > t.left && r.left < t.right && r.bottom > t.top && r.top < t.bottom; });
                  return { hidden: keys.filter((x) => x.closest('.under-toast')).length, over: over.length, below: t.top >= document.getElementById('top').getBoundingClientRect().bottom - 1 || t.bottom <= 60 }; }""")
                self.assertEqual({"hidden": 0, "over": 0, "below": True}, got, w)  # in the bar's free room, or along its foot
                p.evaluate("document.getElementById('toast').classList.remove('show')")
        finally:
            p.set_viewport_size({"width": 1440, "height": 900})
            p.wait_for_timeout(400)

    def test_7q_a_server_gone_is_said_once(self):
        # the bar's band said the server was not answering and a write's note said it again beside it (D4-13)
        p = self.page
        p.evaluate("go('make'); window.scrollTo(0, 0); document.getElementById('toast').classList.remove('show')")
        p.route("**/api/v1/**", lambda route: route.abort())  # every request of this page fails, as with the server gone
        try:
            p.evaluate("refresh()")
            p.wait_for_function("UI.offline === true", timeout=5000)
            p.evaluate("act('/api/v1/details', { fields: {} }, 'Saved')")  # a write, lost
            p.wait_for_timeout(500)
            self.assertEqual([True, False], p.evaluate("[!!document.querySelector('#top .bar-off .band'), document.getElementById('toast').classList.contains('show')]"))   # the band alone says it
        finally:
            p.unroute("**/api/v1/**")
            p.evaluate("refresh()")
            p.wait_for_function("UI.offline === false", timeout=10000)

    def test_7g_a_long_kit_action_is_one_request_and_one_step(self):
        # C4-01, C4-05, C4-13: the map made again, a kit carried and a pick of scene files take seconds. Their key says it is
        # working from the click (disabled, its words), stays so through a poll's redraw, and more clicks send nothing: three
        # clicks on the map's key sent three requests and made three undo steps. The files of one pick are one undo step, with
        # Undo on the note whatever their number.
        p, sent = self.page, []
        watch = lambda r: r.method == "POST" and "/api/v1/interview/" in r.url and sent.append(r.url.split("/api/v1/interview/")[1].split("?")[0])  # noqa: E731
        steps = lambda: p.evaluate("async () => (await (await fetch('/api/v1/history')).json()).steps.map((s) => s.id)")  # noqa: E731  the undo steps, newest first
        key = "(sel) => { const k = document.querySelector(sel); return k ? [k.disabled, k.getAttribute('aria-busy'), k.textContent.trim()] : null; }"
        first = p.evaluate("S.job")  # the application whose kit tests 7b and 7c made
        other = p.evaluate("S.jobs.find((j) => j.company === 'Delta Payments').id")  # test 7f's, with no kit
        p.on("request", watch)
        try:
            p.evaluate("UI.jobsMode = 'list'; go('jobs'); openApplication(S.job, 'interview'); UI.ivPart = 'map'; render()")
            p.wait_for_selector("[data-key=iv-remake]", timeout=30000)
            before = steps()
            p.click("[data-key=iv-remake]")
            self.assertEqual([True, "true", "Making the question map…"], p.evaluate(key, "[data-key=iv-remake]"))  # at once
            p.evaluate("render()")  # a poll draws the tab again meanwhile
            self.assertEqual([True, "true", "Making the question map…"], p.evaluate(key, "[data-key=iv-remake]"))
            self.assertTrue(p.evaluate(key, "[data-key=iv-scenes]")[0])  # the application's other kit keys wait with it
            for _ in range(2):  # more clicks while it works
                p.click("[data-key=iv-remake]", force=True)
            p.wait_for_function("!kitBusy(S.job)", timeout=60000)
            self.assertEqual(["kit"], sent)  # one request
            made = [s for s in steps() if s not in before]
            self.assertLessEqual(len(made), 1)  # and at most one step (none when the map came out the same)
            for s in made:
                p.evaluate("(id) => api('/api/v1/undo', { only: id })", s)
            sent.clear()
            p.evaluate("(jid) => { openApplication(jid, 'interview'); UI.ivPart = 'map'; render(); }", other)  # a carry into the application with no kit
            p.wait_for_selector("[data-key=iv-carry-from]", state="attached", timeout=30000)
            p.evaluate("(jid) => { const s = document.querySelector('[data-key=iv-carry-from]'); s.value = jid; s.dispatchEvent(new Event('change')); }", first)
            before = steps()
            p.click("[data-key=iv-carry]")
            self.assertEqual([True, "true", "Bringing its scripts…"], p.evaluate(key, "[data-key=iv-carry]"))
            p.evaluate("render()")
            self.assertEqual([True, "true", "Bringing its scripts…"], p.evaluate(key, "[data-key=iv-carry]"))
            p.click("[data-key=iv-carry]", force=True)
            p.wait_for_function("!kitBusy(S.job)", timeout=120000)
            self.assertEqual(["carry"], sent)
            made = [s for s in steps() if s not in before]
            self.assertEqual(1, len(made))
            p.evaluate("(id) => api('/api/v1/undo', { only: id })", made[0])
            sent.clear()
            folder = self.tmp / "picked"  # two scene files picked at once
            folder.mkdir(exist_ok=True)
            (folder / "one.md").write_text("### X1. 첫 장면 / First\n\n**면접관** Hi?\n**해석** 안녕하세요?\n**나** Hello.\n**해석** 안녕하세요.\n", encoding="utf-8")
            (folder / "two.txt").write_text("### X2. 둘째 장면 / Second\n\n**면접관** Why?\n**해석** 왜요?\n**나** Because.\n**해석** 그래서요.\n", encoding="utf-8")
            p.evaluate("(jid) => { openApplication(jid, 'interview'); UI.ivPart = 'map'; UI.scenesFor = jid; render(); }", first)
            before = steps()
            p.set_input_files("#scenepick", [str(folder / "one.md"), str(folder / "two.txt")])
            p.wait_for_function("!kitBusy(S.job) && document.getElementById('toast').textContent.includes('scenes added')", timeout=120000)
            self.assertEqual(["scenes", "scenes"], sent)  # a request a file
            made = [s for s in steps() if s not in before]
            self.assertEqual(1, len(made))  # one step for the pick
            self.assertEqual(1, p.locator("#toast .toast-key").count())  # its Undo on the note
            p.click("#toast .toast-key")
            p.wait_for_function("(id) => !document.getElementById('toast').textContent.includes('scenes added')", arg=made[0], timeout=30000)
            self.assertEqual(before, steps())  # both files taken back
        finally:
            p.remove_listener("request", watch)
        p.evaluate("(jid) => openApplication(jid, 'interview')", first)  # as the later tests expect it
        p.wait_for_function("(jid) => S.job === jid", arg=first, timeout=10000)

    def test_7h_a_question_nothing_is_close_to_shows_its_best_three_and_a_row(self):
        # C4-07: a question no script is close to (one word of three in any script) gets the warning on its best card, its best
        # three cards and one row that opens the rest; the board drew 24 unrelated cards over 13 screens
        p = self.page
        p.evaluate("go('interview'); UI.ivPart = 'search'; render()")
        p.wait_for_selector("#canvas .kit .kit-q", timeout=60000)
        p.wait_for_function("UI.kit && UI.kit.stamp === (ivKitData(openJob()) || {}).stamp", timeout=60000)  # the view made from the scripts as they are now
        p.wait_for_timeout(800)
        p.fill("#canvas .kit .kit-q", "로그 없는단어 xyzqq")  # "로그" is in many of test 7c's scripts, the rest in none
        p.press("#canvas .kit .kit-q", "Enter")
        p.wait_for_function("document.querySelectorAll('#canvas .kit-cards .kit-card').length > 0", timeout=20000)
        p.wait_for_timeout(1200)  # the board's later screens placed
        got = p.evaluate("""() => ({ cards: document.querySelectorAll('#canvas .kit-cards .kit-card').length, weak: !!document.querySelector('#canvas .kit-card.best .kit-weak'),
            more: ((document.querySelector('#canvas .kit-rank [data-more=weak]') || {}).textContent || '').trim() })""")
        self.assertEqual(3, got["cards"], got)
        self.assertTrue(got["weak"], got)  # said on the best card
        self.assertRegex(got["more"], r"^\d+ more scripts?$")  # the one row that holds the rest
        p.click("#canvas .kit-rank [data-more=weak]")
        p.wait_for_timeout(700)
        self.assertGreater(p.evaluate("document.querySelectorAll('#canvas .kit-cards .kit-card').length"), 3)  # the rest on the board, as for any question
        self.assertEqual(0, p.locator("#canvas .kit-rank [data-more=weak]").count())
        p.evaluate("document.querySelector('#canvas .kit .kit-home').click()")  # the contents again

    def test_7i_a_board_card_s_day_is_never_cut(self):
        # a card's foot holds its day, the "+" of a next step and the move key: from 900 to 1300 px the board's columns are
        # 145 to 245 px inside, and the day gave way to the keys ("Since 11-…", B4-01) while English keys left the card
        p = self.page
        foot = """() => [...document.querySelectorAll('.board .tcard .tfoot')].filter((f) => f.offsetParent).map((f) => {
            const day = f.querySelector('.when'), card = f.closest('.tcard').getBoundingClientRect();
            return { cut: !!day.textContent && day.scrollWidth > day.clientWidth + 0.5,
                     out: [...f.querySelectorAll('button')].some((k) => k.getBoundingClientRect().right > card.right + 0.5) }; })"""
        try:
            p.evaluate("UI.jobsMode = 'board'; go('jobs')")
            for w in (900, 1000, 1100, 1300, 1440):
                p.set_viewport_size({"width": w, "height": 900})
                p.wait_for_timeout(400)
                feet = p.evaluate(foot)
                self.assertTrue(feet, w)  # the cards are on the board
                self.assertEqual([], [f for f in feet if f["cut"] or f["out"]], w)  # every day whole, every key inside its card
        finally:
            p.set_viewport_size({"width": 1440, "height": 900})
            p.evaluate("UI.jobsMode = 'list'; render()")

    def test_7j_a_refused_day_keeps_its_note_through_a_redraw(self):
        # the timeline's days table: a day typed wrong is said under its field; the first poll's redraw took the note away and
        # left the words (B4-05). The note stays with the words until a new try, with the keyboard in the field or not
        p = self.page
        note = "(k) => { const box = document.querySelector(`[data-key=\"${k}\"]`), n = box && box.closest('.dt-cell').querySelector('.fnote'); return [box ? box.value : null, n ? n.textContent : ''] }"
        try:
            p.evaluate("UI.jobsMode = 'timeline'; UI.editDays = true; go('jobs')")
            p.wait_for_selector(".daystable input[data-key^='dt-']", timeout=10000)
            key = p.evaluate("document.querySelector(\".daystable input[data-key^='dt-']\").dataset.key")
            p.fill(f'[data-key="{key}"]', "2026-13-01")  # no such day
            p.press(f'[data-key="{key}"]', "Tab")  # read as it is left
            p.wait_for_timeout(300)
            said = p.evaluate(note, key)
            self.assertEqual("2026-13-01", said[0])
            self.assertTrue(said[1])  # the note under it
            p.evaluate("redrawAll()")  # a poll's redraw, the keyboard still in the field
            p.wait_for_timeout(400)
            self.assertEqual(said, p.evaluate(note, key))
            p.evaluate("document.activeElement.blur(); redrawAll()")  # and with the keyboard elsewhere
            p.wait_for_timeout(400)
            self.assertEqual(said, p.evaluate(note, key))
            p.fill(f'[data-key="{key}"]', "2026-11-02")  # a new try takes the note away
            p.press(f'[data-key="{key}"]', "Tab")
            p.wait_for_timeout(600)
            self.assertEqual(["2026-11-02", ""], p.evaluate(note, key))
        finally:
            p.evaluate("UI.editDays = false; forget('dt-'); UI.jobsMode = 'list'; render()")

    def test_7k_the_documents_head_keeps_its_words_and_its_keys(self):
        # the Documents head from 1400 px cut its subtitle to one line with an ellipsis (B4-02) and kept its keys on one row
        # that ran past the head, the page sliding sideways in English (B4-03); at 700 px the lock left its export group
        p = self.page
        jid = p.evaluate("S.job")
        role = p.evaluate("(jid) => S.jobs.find((j) => j.id === jid).role || ''", jid)
        head = """() => { const d = document.getElementById('dochead'), r = d.getBoundingClientRect(), s = d.querySelector('.viewhead > .sub');
            const keys = [...d.querySelectorAll('.viewhead button, .viewhead .toggle')].filter((k) => k.getBoundingClientRect().width > 0);
            return { cut: s.scrollWidth > s.clientWidth + 1 || s.scrollHeight > s.clientHeight + 1, whole: s.title === s.textContent,
                     out: keys.filter((k) => k.getBoundingClientRect().right > r.right + 0.5).map((k) => k.textContent),
                     wide: document.documentElement.scrollWidth - document.documentElement.clientWidth }; }"""
        try:
            p.evaluate("(jid) => act('/api/v1/tracker/edit', { job: jid, role: 'Senior Platform Engineer, Deployment and Reliability' })", jid)   # a role as long as postings have
            p.evaluate("go('documents')")
            for w in (700, 1000, 1400, 1440, 1600):
                p.set_viewport_size({"width": w, "height": 900})
                for doc in ("resume", "cover", "deck"):
                    p.evaluate(f"UI.doc = '{doc}'; UI.sel = null; render()")
                    p.wait_for_timeout(350)
                    got = p.evaluate(head)
                    self.assertEqual({"cut": False, "whole": True, "out": [], "wide": 0}, got, (w, doc))  # its words whole, every key inside, no sideways scroll
        finally:
            p.set_viewport_size({"width": 1440, "height": 900})
            p.evaluate("([jid, role]) => act('/api/v1/tracker/edit', { job: jid, role })", [jid, role])
            p.evaluate("UI.doc = 'resume'; go('jobs')")

    def test_7l_a_round_changed_in_another_window_is_never_written_over(self):
        # two windows edit one round's notes: the first saves, the second (its form opened before that save, a poll since
        # drawing the first one's notes under the words it then types) saved over them and said "Round kept." (D4-06). Now the
        # second is refused in words and its form is drawn again from the round as it is
        p = self.page
        jid = p.evaluate("S.job")
        p.evaluate("(jid) => act('/api/v1/tracker/round', { job: jid, kind: 'first', at: '2026-11-20' })", jid)
        rid = p.evaluate("(jid) => S.jobs.find((j) => j.id === jid).rounds.slice(-1)[0].id", jid)
        notes = f'[data-key="i-{jid}-{rid}-notes"]'
        second = p.context.new_page()
        try:
            second.goto(self.base.rstrip("/") + "/?lang=en")
            second.wait_for_function("typeof S !== 'undefined' && S && S.jobs !== undefined", timeout=30000)
            for w in (p, second):  # both windows open the round's form
                w.evaluate("(jid) => { go('jobs'); openApplication(jid, 'progress'); }", jid)
                w.wait_for_selector(".round .round-h button.btn", timeout=10000)
                w.click(".round .round-h button.btn")
                w.wait_for_selector(notes, timeout=5000)
            p.fill(notes, "words of the first window")
            p.click(".round-form button[type=submit]")
            p.wait_for_function("(jid) => !UI.roundEdit", arg=jid, timeout=10000)  # kept, the form closed
            second.evaluate("refresh()")  # the second window's poll: its form now shows the first window's notes
            second.wait_for_timeout(600)
            second.fill(notes, "words of the second window")
            second.click(".round-form button[type=submit]")
            second.wait_for_timeout(1200)
            self.assertIn("This round was changed in another window", second.evaluate("document.getElementById('toast').textContent"))
            self.assertEqual("words of the first window", second.evaluate(f"document.querySelector('{notes}').value"))  # drawn again from the round as it is
            kept = p.evaluate("async ([jid, rid]) => (await (await fetch('/api/v1/state')).json()).jobs.find((j) => j.id === jid).rounds.find((r) => r.id === rid).notes", [jid, rid])
            self.assertEqual("words of the first window", kept)  # nothing written over them
        finally:
            second.close()
            p.evaluate("([jid, rid]) => act('/api/v1/tracker/round', { job: jid, id: rid, remove: true })", [jid, rid])
            p.evaluate("UI.roundEdit = null; forget('i-'); go('jobs')")

    def test_7m_one_day_s_applications_are_listed_the_newest_first(self):
        # the applications added on one day stood oldest first in the list (the day alone was compared), so a job just added
        # landed under the ones before it (B4-13); test 6's and test 7f's were added on this run's day
        p = self.page
        p.evaluate("UI.jobsMode = 'list'; go('jobs')")
        p.wait_for_selector(".joblist .jobrow", timeout=10000)
        got = p.evaluate("""() => { const open = S.jobs.filter((j) => j.stage !== 'result');
            const day = (j) => [j.stage, j.created].join();
            const same = open.filter((j) => open.some((k) => k !== j && day(k) === day(j)));   // the ones sharing a stage and a day with another
            const rows = [...document.querySelectorAll('.joblist .jobrow')].map((r) => r.textContent);
            const at = (j) => rows.findIndex((w) => w.includes(j.company || j.role));
            return { n: same.length, listed: [...same].sort((a, b) => at(a) - at(b)).map((j) => j.seq), newest: [...same].sort((a, b) => b.seq - a.seq).map((j) => j.seq) }; }""")
        self.assertGreaterEqual(got["n"], 2)  # two of one day to order
        self.assertEqual(got["newest"], got["listed"])  # listed by when they were added, the newest first

    def test_7n_the_applications_list_is_one_tab_stop(self):
        # every row of the list took Tab, so the keyboard crossed 29 of them before the open application's tabs (B4-17); now
        # the list is one stop, as the tabs are: the arrows move along it and Enter opens a row
        p = self.page
        opened = p.evaluate("S.job")
        extra = None if p.evaluate("S.jobs.length") > 1 else p.evaluate("async (text) => (await act('/api/v1/jobs', { company: 'Delta Labs', role: 'SRE', posting: text })).job", POSTING.read_text(encoding="utf-8"))   # two rows at least
        if extra:
            p.evaluate("(jid) => openApplication(jid, 'fit')", opened)  # the first one in view again
        p.evaluate("UI.jobsMode = 'list'; go('jobs')")
        p.wait_for_function("() => document.querySelectorAll('.joblist .jobrow').length > 1", timeout=10000)
        self.assertEqual(1, p.evaluate("[...document.querySelectorAll('.joblist .jobrow')].filter((r) => r.tabIndex === 0).length"))  # one row takes Tab
        p.focus('.joblist .jobrow[tabindex="0"]')
        start = p.evaluate("document.activeElement.dataset.key")
        p.keyboard.press("Home")  # the first row
        first = p.evaluate("document.activeElement.dataset.key")
        p.keyboard.press("ArrowDown")  # the next one
        nxt = p.evaluate("document.activeElement.dataset.key")
        self.assertNotEqual(first, nxt)  # the keyboard moved along the list
        self.assertTrue(first.startswith("jl-") and nxt.startswith("jl-"), (start, first, nxt))
        self.assertEqual(opened, p.evaluate("S.job"))  # moving opens nothing
        p.keyboard.press("Enter")  # this one opens
        p.wait_for_function("(k) => S.job === k.slice(3)", arg=nxt, timeout=10000)
        p.evaluate("(jid) => openApplication(jid, 'fit')", opened)  # as the tests before had it
        p.wait_for_function("(jid) => S.job === jid", arg=opened, timeout=10000)
        if extra:  # the row this test added goes
            p.evaluate("(jid) => act('/api/v1/jobs/remove', { job: jid })", extra)

    def test_8_no_page_errors(self):
        self.assertEqual([], self.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
