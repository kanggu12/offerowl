#!/usr/bin/env python3
"""The live canvas against the typeset PDF, on the fictional examples: the canvas's model holds what src/resume_form.js prints
(read through src/profile_loader.js, the PDF's own reader), and the example person's live pages break where its PDF's pages
break. The page check draws the canvas in headless Chromium as it comes (on Linux it hints glyphs, which the canvas's own
text-rendering setting undoes, so each line holds the PDF's words); it is skipped where Node.js or Playwright's Chromium is missing.

    python3 -m unittest tests/app/test_canvas_print.py -v
"""
import json  # the loader's answer
import os  # environment
import pathlib  # paths
import shutil  # the temporary folder, and whether Node.js is here
import subprocess  # the loader and the panel's server
import sys  # the interpreter and the import path
import tempfile  # a data folder of its own
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules (resume.py)

try:  # the browser driver, when it is installed
    from playwright.sync_api import sync_playwright
except ImportError:  # no Playwright here
    sync_playwright = None

FULL = ROOT / "examples" / "sample_full_ko.json"  # a fictional person with every part the detailed form prints
# The section headings on each page of the example person's PDF and how far down the page each starts, in CSS px (pdftotext's
# top of the heading's line: examples/sample_ko.json made by the panel in the render container, 2026-11-09). The page count
# itself is the self-test's RESUME_PAGES, which ./offerowl selftest checks against the PDF it makes.
PDF_SECTIONS = [[("개요", 181.7), ("경력요약", 650.1), ("학력사항", 790.6), ("핵심역량", 879.0)],
                [("보유기술", 116.1), ("상세경력사항", 289.8), ("자격증", 558.3), ("자기소개", 620.1), ("지원 동기", 789.7)]]
# The same person in the other two forms (src/resume_form.js FORMS), from the PDFs the panel made in each (2026-11-09): the
# one-column form on one page, the table form on two
FORM_SECTIONS = {"compact": [[("상세경력사항", 169.8), ("보유기술", 372.3), ("학력사항", 508.7), ("자격증", 571.3)]],
                 "table": [[("학력사항", 162.1), ("경력요약", 250.5), ("자격증", 391.0), ("보유기술", 452.7), ("상세경력사항", 626.6), ("자기소개", 895.0)],
                           [("지원 동기", 22.7)]]}
FORM_MARK = {"compact": ".r-pname", "table": ".r-title"}  # what only that form's first page draws: its head
NEAR = 2.0  # px: the canvas sets each line where the PDF does to a fraction of a pixel; a drifted spacing moves a heading further


def loaded(profile: pathlib.Path, lang: str = "ko") -> dict:
    """The profile as src/resume_form.js reads it before it prints (src/profile_loader.js load)."""
    js = "const G = require(process.argv[1]); console.log(JSON.stringify(G.load(process.argv[2], process.argv[3], {})));"  # the PDF's reader, nothing else
    r = subprocess.run(["node", "-e", js, str(ROOT / "src" / "profile_loader.js"), str(profile), lang], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(r.stdout)  # roles, education, sections, summary as printed


@unittest.skipIf(not shutil.which("node"), "Node.js is not installed")
class ModelPrintsWhatThePdfPrints(unittest.TestCase):
    """The canvas's model (apps/api/evidence.py) gives each part the words, dates and lines the PDF prints them with. It is
    built in Python from the profile, so each field that the loader reads its own way is checked against the loader."""

    @classmethod
    def setUpClass(cls):
        from apps.api import evidence as E  # the canvas's model
        prof = json.loads(FULL.read_text(encoding="utf-8"))  # the fictional person as written
        cls.m = E.Resume(prof, "ko", "navy", evmap={}, cands=[], base=None, edits={}, locks={}, details={}).build()  # the model the canvas draws
        cls.p = loaded(FULL)  # what the PDF is printed from

    def block(self, kind):  # the model's blocks of one kind
        return [b for b in self.m["blocks"] if b["type"] == kind]

    def text(self, sid):  # a sentence's words as the canvas shows them
        return self.m["sentences"][sid]["text"]

    def test_the_career_table_has_the_printed_cells_and_the_total(self):
        rows = self.block("career")[0]["rows"]  # the table's rows, newest first
        want = [[r["period"], r["org"], ", ".join(x for x in (r["place"], r["note"]) if x), r["dept"], r["title"], r["tenure"]] for r in self.p["roles"]]  # as printed
        got = [[r["period"], self.text(r["sid"]), r["sub"], r["department"], r["role"], r["tenure"]] for r in rows]  # as the canvas draws them
        self.assertEqual(want, got)  # the name alone is the sentence; the place is the grey line under it; "2년", not "2년 0개월"
        head = next(b for b in self.m["blocks"] if b["type"] == "section" and b.get("key") == "career")  # its heading
        self.assertEqual(f"(총경력 {self.p['total']})", head["note"])  # the total beside the title, as printed

    def test_the_education_dates_read_as_printed(self):
        rows = self.block("education")[0]["rows"]  # the schools
        self.assertEqual([[e["period"], e["school"], e["sub"], e["major"], e["degree"], e["note"]] for e in self.p["education"]],
                         [[r["period"], self.text(r["sid"]), r["sub"], r["major"], r["degree"], r["note"]] for r in rows])

    def test_each_company_band_has_its_place_dates_line_and_projects_as_printed(self):
        roles = self.block("role")  # the bands, newest first
        want = [[r["org"], r["place"], r["period"], r["tenure"], r.get("sub") or " / ".join(x for x in (r["dept"], r["title"]) if x), r["desc"], r["badge"],
                 [[x["title"], x["period"]] for x in r["projects"] if x.get("resume") is not False]] for r in self.p["roles"]]  # resume_form.js's band, sub line and bullets
        got = [[b["org"], b["place"], b["period"], b["tenure"], b["sub"], b["desc"], b["badge"], [[x["title"], x["period"]] for x in b["projects"]]] for b in roles]
        self.assertEqual(want, got)

    def test_a_key_project_row_prints_its_second_element_only(self):
        items = self.block("highlights")[0]["items"]  # the cards
        self.assertEqual([[r[1] for r in h["rows"]] for h in self.p["summary"]["highlights"]],  # layout.js fhighlights reads [label, text]
                         [[self.text(r["sid"]) for r in c["rows"]] for c in items])

    def test_a_list_keeps_its_captions_dated_lines_table_and_note(self):
        sec = next(s for s in self.p["sections"] if s["resume"])  # the printed list
        groups = self.block("list")[0]["groups"]  # as the canvas draws it
        self.assertEqual([g["title"] for g in sec["groups"]], [g["caption"] for g in groups])  # each group under its caption
        for g, want in zip(groups, sec["groups"]):  # each group's body
            self.assertEqual([[str(x or "") for x in (ln + ["", "", ""])[:3]] for ln in want.get("lines") or []],
                             [[ln["main"], ln["org"], ln["date"]] for ln in g["lines"]])  # main words, organization, date at the right
            if want.get("rows"):  # a table: its head, its cells and the note under it
                self.assertEqual(want["head"], g["table"]["head"])
                self.assertEqual([[c if isinstance(c, str) else c["t"] for c in r] for r in want["rows"]], [[c["t"] for c in r] for r in g["table"]["rows"]])
                self.assertEqual(sum(g["table"]["widths"]), 10406)  # the columns fill the text's width, as layout.js requires
                self.assertEqual(want["note"], g["note"])


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class LivePagesBreakAsThePdf(unittest.TestCase):
    """The example person's live canvas has the PDF's pages: as many, and each starting the same sections."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-print-"))  # data, home, desktop
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
        try:  # headless, with no switch of its own: the canvas sets its glyphs at the font's widths itself
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001  Playwright without its browser
            cls.pw.stop()
            cls.srv.terminate()
            raise unittest.SkipTest(f"no Chromium for Playwright: {exc}")
        ctx = cls.browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR", bypass_csp=True)
        ctx.add_init_script("try { localStorage.setItem('offerowl-setup-seen', '1'); } catch (_) {}")  # the setup guide is not the subject here
        cls.page = ctx.new_page()
        cls.errors = []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.goto(base + "?lang=ko")  # the Korean example, as its PDF was made
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
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def headings(self) -> list:
        """Each page's section headings and where they start, in the page's own px."""
        return self.page.evaluate("""[...document.querySelectorAll('.pages .sheet')].map((s) => {
          const zoom = parseFloat(getComputedStyle(s).zoom) || 1, top = s.getBoundingClientRect().top;   // the page, drawn at its zoom
          return [...s.querySelectorAll('.r-sec')].map((e) => [e.querySelector('h2').firstChild.textContent.trim(), (e.getBoundingClientRect().top - top) / zoom]);
        })""")

    def assert_pages(self, want: list, pages: list) -> None:
        """The PDF's pages: each starting the sections the PDF's does, each heading where the PDF has it."""
        self.assertEqual([[t for t, _ in pg] for pg in want], [[t for t, _ in pg] for pg in pages])  # as many pages, the same sections on each
        for wpg, gpg in zip(want, pages):
            for (title, y), (_, live) in zip(wpg, gpg):
                self.assertLessEqual(abs(live - y), NEAR, f"{title}: the PDF's at {y} px, the canvas's at {live:.1f} px")

    def test_the_example_has_its_pdf_s_pages_and_their_sections(self):
        import resume  # src/resume.py: the example's page count the self-test checks on its PDF
        pages = self.headings()  # what the canvas laid out
        self.assertEqual(resume.RESUME_PAGES, len(pages))  # as many pages as the PDF
        self.assert_pages(PDF_SECTIONS, pages)  # and the same sections on each, where the PDF has them
        feet = self.page.evaluate("[...document.querySelectorAll('.pages .sheet .r-foot')].map((f) => f.textContent)")  # the name and the page on every foot
        self.assertEqual([f"홍길동  Gildong Hong{i} / {len(pages)}" for i in range(1, len(pages) + 1)], feet)
        self.assertEqual([], self.errors)  # and the page raised nothing

    def test_the_other_forms_have_their_pdf_s_pages_and_sections(self):
        # the one-column and the table forms draw their own parts (a line per company, a key table, a service table): the same
        # check on each, switched as the person switches it, and the detailed form back for the other tests
        try:
            for form, want in FORM_SECTIONS.items():
                with self.subTest(form=form):
                    self.page.evaluate("(f) => api('/api/v1/settings', { form: f }).then(schedule)", form)  # the page's own call
                    self.page.wait_for_function(f"document.querySelector('.pages .sheet {FORM_MARK[form]}')", timeout=60000)  # drawn in that form
                    self.page.wait_for_timeout(600)
                    self.assert_pages(want, self.headings())
        finally:
            self.page.evaluate("api('/api/v1/settings', { form: 'detailed' }).then(schedule)")  # as it was
            self.page.wait_for_function("document.querySelector('.pages .sheet .r-head')", timeout=60000)
            self.page.wait_for_timeout(600)
        self.assertEqual([], self.errors)  # and the page raised nothing

    def test_a_number_never_takes_room_in_a_line(self):
        # the sources' numbers sit after a sentence or in the right margin, laid over the page: a line breaks where the PDF breaks it
        inline = self.page.evaluate("[...document.querySelectorAll('.pages .sheet .s > .cite')].filter((c) => getComputedStyle(c).display !== 'none').length")
        placed = self.page.evaluate("[...document.querySelectorAll('.pages .sheet .cite.over')].length")
        self.assertEqual(0, inline)  # none in the flow of a line
        self.assertGreater(placed, 0)  # and they are there, beside their sentences


if __name__ == "__main__":
    unittest.main()
