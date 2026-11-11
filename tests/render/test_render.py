#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests of the browser renderer (src/render_html, docs/ARCHITECTURE.md).

  python3 -m unittest tests/render/test_render.py -v

Most tests need nothing but Python: they read a small DOCX written here, the repository's fonts, and a stand-in file
system for the browser search. One test prints that DOCX with a real browser and is skipped when none is found
(or when OFFEROWL_TEST_BROWSER=0); a second one compares the result with itself through poppler, skipped without it.
"""
import contextlib  # stdout capture
import io  # stdout capture
import os  # environment
import pathlib  # paths
import re  # reading the HTML
import shutil  # temporary folders, poppler lookup
import sys  # module path
import tempfile  # temporary folders
import unittest  # the framework
import zipfile  # writing a DOCX
from unittest import mock  # stand-ins

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository root
sys.path.insert(0, str(ROOT / "src" / "render_html"))  # the renderer's modules
sys.path.insert(0, str(ROOT / "src"))  # resume.py and its siblings
sys.path.insert(0, str(ROOT / "tests" / "render"))  # compare.py
import browser  # noqa: E402
import docx2html  # noqa: E402
import fonts  # noqa: E402
import render  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
RUN = '<w:r><w:rPr><w:rFonts w:ascii="Pretendard" w:hAnsi="Pretendard" w:eastAsia="Pretendard"/><w:sz w:val="18"/></w:rPr>' \
      '<w:t xml:space="preserve">%s</w:t></w:r>'


def write_docx(path: pathlib.Path, body: str, footer: str | None = None) -> pathlib.Path:
    """A minimal DOCX: one body, A4 with layout.js's margins, an optional footer"""
    sect = ('<w:sectPr>%s<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="340" w:right="750" w:bottom="1080" '
            'w:left="750" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>') % (
        '<w:footerReference w:type="default" r:id="rIdF"/>' if footer else "")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document %s><w:body>%s%s</w:body></w:document>' % (W, body, sect))
        z.writestr("word/styles.xml", '<?xml version="1.0"?><w:styles %s><w:docDefaults><w:rPrDefault><w:rPr>'
                   '<w:rFonts w:ascii="Pretendard" w:hAnsi="Pretendard" w:eastAsia="Pretendard"/><w:sz w:val="18"/>'
                   '</w:rPr></w:rPrDefault></w:docDefaults></w:styles>' % W)
        rels = '<Relationship Id="rIdF" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>' if footer else ""
        z.writestr("word/_rels/document.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % rels)
        if footer:
            z.writestr("word/footer1.xml", '<?xml version="1.0"?><w:ftr %s>%s</w:ftr>' % (W, footer))
    return path


def para(text: str, ppr: str = "") -> str:
    """One paragraph with one 9pt Pretendard run"""
    return "<w:p><w:pPr>%s</w:pPr>%s</w:p>" % (ppr, RUN % text)


class ConverterTest(unittest.TestCase):
    """docx2html.py turns the OOXML that layout.js writes into a page with LibreOffice's rules"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def page(self, body: str, footer: str | None = None) -> str:
        return docx2html.convert(write_docx(self.tmp / "t.docx", body, footer))

    def test_a_line_without_a_rule_is_an_exact_height_as_libreoffice_reads_it(self):
        html = self.page(para("가나다", '<w:spacing w:after="0" w:line="264"/>'))
        k = docx2html.SCALE
        self.assertIn('data-lh="%g"' % (13.2 * k), html)  # 264 twips are 13.2pt, at the layout scale
        self.assertIn('data-lr="exact"', html)

    def test_a_widened_bar_takes_the_width_libreoffice_gives_it(self):
        # the blind edition's bar (src/save.js): one square glyph at a horizontal scale, on its mask colour; the extra advance of
        # the square at that scale is added after it, so the run's background spans the scaled width
        bar = ('<w:p><w:r><w:rPr><w:color w:val="8B1A1A"/><w:w w:val="300"/><w:sz w:val="18"/><w:shd w:val="clear" w:color="auto" '
               'w:fill="8B1A1A"/></w:rPr><w:t xml:space="preserve">■</w:t></w:r></w:p>')
        html = self.page(bar)
        want = docx2html.fmt((3 - 1) * docx2html.BAR_EM["regular"] * 9)  # two more squares' advance at 9pt
        self.assertIn("background:#8B1A1A;letter-spacing:" + want, html)
        self.assertNotIn("letter-spacing", self.page(para("가나다")))  # a run with no scale keeps its glyphs as drawn

    def test_no_line_attribute_is_single_spacing(self):
        html = self.page(para("가나다"))
        self.assertIn('data-lr="auto"', html)
        self.assertIn('data-lh="1"', html)

    def test_a_tab_character_in_the_text_is_a_tab_stop(self):
        html = self.page(para("label\tvalue", '<w:tabs><w:tab w:val="right" w:pos="10366"/></w:tabs>'))
        self.assertEqual(html.count('class="tab"'), 1)
        self.assertIn('data-tabs="[[&quot;right&quot;, %g]]"' % (518.3 * docx2html.SCALE), html)

    def test_hangul_next_to_latin_gets_libreoffices_gap_and_a_word_joiner_stops_it(self):
        self.assertIn('class="as"', self.page(para("가상API")))
        self.assertNotIn('class="as"', self.page(para("가상\u2060API")))

    def test_a_word_joiner_never_reaches_the_pdfs_text(self):  # a resume's text must stay searchable for the systems that read it
        self.assertNotIn("\u2060", self.page(para("총경력 7\u2060년 5\u2060개월")))

    def test_a_non_breaking_hyphen_is_a_plain_hyphen_in_a_word_that_stays_whole(self):
        html = self.page(para("run multi\u2011node jobs"))
        self.assertIn('class="nb"', html)  # the word cannot break
        self.assertNotIn("\u2011", html)  # and the PDF's text holds '-'

    def test_a_left_border_sits_outside_the_indent(self):
        ppr = '<w:pBdr><w:left w:val="single" w:sz="36" w:space="6" w:color="1B2E4B"/></w:pBdr><w:ind w:left="140"/>'
        html = self.page(para("개요", ppr))
        k = docx2html.SCALE
        # 7pt indent less 6pt space less 4.5pt bar: the bar starts 3.5pt left of the margin, the text stays at 7pt
        self.assertIn("margin:0pt 0pt 0pt %gpt" % (-3.5 * k), html)
        self.assertIn("padding:0pt 0pt 0pt %gpt" % (6 * k), html)

    def test_cells_take_the_rows_largest_vertical_margins_and_horizontal_ones_from_the_grid_line(self):
        def tc(top, w):
            return ('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/><w:tcMar><w:top w:w="%d" w:type="dxa"/><w:left w:w="160" w:type="dxa"/>'
                    '<w:bottom w:w="%d" w:type="dxa"/><w:right w:w="160" w:type="dxa"/></w:tcMar></w:tcPr>%s</w:tc>') % (w, top, top, para("x"))
        border = '<w:tblBorders><w:insideV w:val="single" w:sz="36" w:color="FFFFFF"/></w:tblBorders>'
        body = ('<w:tbl><w:tblPr>%s</w:tblPr><w:tblGrid><w:gridCol w:w="5203"/><w:gridCol w:w="5203"/></w:tblGrid>'
                '<w:tr>%s%s</w:tr></w:tbl>') % (border, tc(160, 5203), tc(100, 5203))
        html = self.page(body)
        k = docx2html.SCALE
        pads = re.findall(r"<td[^>]*padding:([\d.]+)pt ([\d.]+)pt ([\d.]+)pt ([\d.]+)pt", html.split("<table")[1])  # the cells only
        self.assertEqual(float(pads[1][0]), 8 * k)  # the second cell's 5pt became the row's 8pt
        self.assertEqual(float(pads[0][1]), (8 - 2.25) * k)  # right of the first cell: its 8pt less half the 4.5pt rule

    def test_the_empty_paragraph_word_needs_after_a_nested_table_is_dropped(self):
        inner = '<w:tbl><w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid><w:tr><w:tc>%s</w:tc></w:tr></w:tbl>' % para("in")
        cell = '<w:tc>%s<w:p><w:pPr><w:spacing w:after="0" w:line="20" w:lineRule="exact"/></w:pPr></w:p></w:tc>' % inner
        html = self.page('<w:tbl><w:tblGrid><w:gridCol w:w="10406"/></w:tblGrid><w:tr>%s</w:tr></w:tbl>' % cell)
        self.assertNotIn('data-lh="%g"' % (1 * docx2html.SCALE), html)

    def test_a_level_one_outline_paragraph_becomes_a_bookmark_heading(self):
        self.assertIn('<h1 class="p"', self.page(para("개요", '<w:outlineLvl w:val="0"/>')))

    def test_page_fields_become_placeholders_and_the_cached_result_is_not_shown(self):
        fld = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>PAGE</w:instrText></w:r>'
               '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>9</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
        html = self.page(para("본문"), footer=fld)
        self.assertIn('data-f="page"', html)
        self.assertNotIn(">9<", html)

    def test_fonts_are_embedded_from_the_repository_with_libreoffices_metrics(self):
        html = self.page(para("가나다"))
        self.assertIn("@font-face", html)
        self.assertIn((ROOT / "fonts" / "Pretendard-Regular.ttf").resolve().as_uri(), html)
        self.assertIn("ascent-override: 95.1660%", html)  # 1949 of 2048 units, the typographic ascent


class FontsTest(unittest.TestCase):
    def test_pretendard_uses_the_typographic_metrics(self):
        info = fonts.read_font(ROOT / "fonts" / "Pretendard-Regular.ttf")
        self.assertEqual((info["family"], info["upm"], info["asc"], info["desc"]), ("Pretendard", 2048, 1949, 494))

    def test_the_page_uses_its_own_family_name_first(self):
        fam = fonts.css_family("Pretendard", "Pretendard")
        self.assertTrue(fam.startswith("'owl-pretendard'"))


class BrowserSearchTest(unittest.TestCase):
    """The search order on each system, with a stand-in file system"""

    def test_windows_finds_edge_first(self):
        env = {"PROGRAMFILES(X86)": r"C:\Program Files (x86)", "PROGRAMFILES": r"C:\Program Files", "LOCALAPPDATA": r"C:\Users\a\AppData\Local"}
        files = {r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"}
        found = browser.candidates("win32", env, which=lambda n: None, exists=lambda p: p in files)
        self.assertEqual([c["kind"] for c in found], ["edge", "chrome"])

    def test_macos_finds_chrome_in_applications(self):
        files = {"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
        found = browser.candidates("darwin", {}, which=lambda n: None, exists=lambda p: p in files)
        self.assertEqual(found[0]["path"], "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    def test_linux_finds_chromium_on_path(self):
        found = browser.candidates("linux", {}, which=lambda n: "/usr/bin/chromium" if n == "chromium" else None, exists=lambda p: True)
        self.assertEqual(found[0], {"path": "/usr/bin/chromium", "kind": "chrome"})

    def test_the_persons_choice_comes_first(self):
        found = browser.candidates("linux", {"OFFEROWL_BROWSER": "/opt/b/chrome"}, which=lambda n: "/usr/bin/" + n, exists=lambda p: True)
        self.assertEqual(found[0], {"path": "/opt/b/chrome", "kind": "chosen"})

    def test_playwrights_chromium_is_the_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            exe = pathlib.Path(d) / "chromium-1234" / "chrome-linux64" / "chrome"
            exe.parent.mkdir(parents=True)
            exe.write_text("")
            found = browser.candidates("linux", {"PLAYWRIGHT_BROWSERS_PATH": d}, which=lambda n: None)
            self.assertEqual(found, [{"path": str(exe), "kind": "playwright"}])

    def test_playwrights_headless_shell_comes_before_its_full_build(self):
        with tempfile.TemporaryDirectory() as d:
            full = pathlib.Path(d) / "chromium-1234" / "chrome-linux64" / "chrome"
            shell = pathlib.Path(d) / "chromium_headless_shell-1234" / "chrome-headless-shell-linux64" / "chrome-headless-shell"
            for exe in (full, shell):
                exe.parent.mkdir(parents=True)
                exe.write_text("")
            found = browser.candidates("linux", {"PLAYWRIGHT_BROWSERS_PATH": d}, which=lambda n: None)
            self.assertEqual([c["path"] for c in found], [str(shell), str(full)])
            self.assertNotIn("--headless=new", browser._flags(str(shell)))  # a headless shell takes no headless switch

    def test_on_windows_the_version_comes_from_the_folder_and_the_browser_is_not_started(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("150.0.7871.12", "151.0.7922.75", "Locales"):
                (pathlib.Path(d) / name).mkdir()
            exe = pathlib.Path(d) / "msedge.exe"
            with mock.patch.object(browser.subprocess, "run", side_effect=AssertionError("started")):
                self.assertEqual(browser.version(str(exe), "win32"), "151.0.7922.75")

    def test_nothing_found_is_an_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(browser.candidates("linux", {"PLAYWRIGHT_BROWSERS_PATH": d}, which=lambda n: None, exists=lambda p: False), [])


class SwitchTest(unittest.TestCase):
    """OFFEROWL_RENDERER in src/resume.py"""

    def setUp(self):
        import resume
        self.resume = resume

    def test_the_default_is_the_container(self):
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(self.resume.sys, "platform", "linux"):  # Linux or macOS
            os.environ.pop("OFFEROWL_RENDERER", None)
            os.environ.pop("OFFEROWL_RENDERER", None)
            with mock.patch.object(self.resume.shutil, "which", return_value="/usr/bin/docker"):  # Docker is here
                self.assertEqual(self.resume.renderer(), "container")  # nothing changes for someone who has it
            with mock.patch.object(self.resume, "in_container", return_value=False), mock.patch.object(self.resume.shutil, "which", return_value=None):  # no Docker
                doctor = self.resume.html_renderer().doctor  # the real report's function
                with mock.patch.object(self.resume.html_renderer(), "doctor", return_value={"html": {"ok": True, "needs": []}}) as seen, mock.patch.object(self.resume, "_BROWSER_OK", []):  # a browser that can typeset
                    self.assertEqual(self.resume.renderer(), "html")  # just works
                    self.assertEqual(self.resume.html_missing(), [])  # and asking what it lacks does not ask the choice again in a circle
                    self.assertEqual(self.resume.renderer(), "html")  # the same answer
                    self.assertEqual(1, seen.call_count - 1)  # the search for a browser ran once for the choice, once for what it lacks
                with mock.patch.object(self.resume.html_renderer(), "doctor", return_value={"html": {"ok": False, "needs": ["a browser"]}}), mock.patch.object(self.resume, "_BROWSER_OK", []):  # neither
                    self.assertEqual(self.resume.renderer(), "container")  # the message about Docker says what to do
                self.assertTrue(callable(doctor))  # the real function stays in place

    def test_html_is_chosen_by_the_setting(self):
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "html"}):
            self.assertEqual(self.resume.renderer(), "html")
            self.assertFalse(self.resume.docker_missing())  # the html renderer needs no Docker

    def test_an_unknown_renderer_stops_with_a_message(self):
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "libre", "OFFEROWL_LANG": "en"}):
            with self.assertRaises(SystemExit) as e:
                self.resume.renderer()
            self.assertIn("html or container", str(e.exception))

    def test_tools_run_here_with_this_python_under_html(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "html"}), mock.patch.object(self.resume.subprocess, "run", side_effect=fake_run):
            self.resume.sh(["python3", "src/check_documents.py", "a.json"])
        self.assertEqual(seen["cmd"][0], sys.executable)  # not render/run.sh, and not a python3 that Windows lacks

    def test_the_container_still_goes_through_run_sh(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "container"}), \
                mock.patch.object(self.resume.sys, "platform", "linux"), mock.patch.object(self.resume, "in_container", return_value=False), \
                mock.patch.object(self.resume.subprocess, "run", side_effect=fake_run):
            self.resume.sh(["pdftotext", "a.pdf", "-"])
        self.assertTrue(seen["cmd"][0].endswith(os.path.join("render", "run.sh")), seen["cmd"][0])  # the starter in render/, not a stale root copy

    def test_windows_typesets_with_the_browser_even_with_docker(self):
        # the container is started by render/run.sh, a shell script Windows cannot run: with Docker Desktop installed the
        # package went to the container and every PDF stopped with OSError
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(self.resume.sys, "platform", "win32"), \
                mock.patch.object(self.resume, "in_container", return_value=False), \
                mock.patch.object(self.resume.shutil, "which", return_value="C:/Program Files/Docker/docker.exe"):
            os.environ.pop("OFFEROWL_RENDERER", None)
            self.assertEqual(self.resume.renderer(), "html")  # the browser, and its own message when it lacks something
            self.assertFalse(self.resume.docker_missing())  # nothing asks for Docker

    def test_the_cover_letter_says_the_same_on_windows(self):
        import cover  # src/cover.py runs its own render tools
        with mock.patch.dict(os.environ, {"OFFEROWL_LANG": "en"}), mock.patch.object(cover.sys, "platform", "win32"), \
                mock.patch.object(cover, "in_container", return_value=False), mock.patch.object(cover.subprocess, "run") as run:
            with self.assertRaises(SystemExit) as e:
                cover.sh(["soffice", "--version"])
        self.assertIn("WSL", str(e.exception))  # not an OSError from starting a shell script
        run.assert_not_called()

    def test_the_container_named_on_windows_says_what_to_do(self):
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "container", "OFFEROWL_LANG": "en"}), \
                mock.patch.object(self.resume.sys, "platform", "win32"), mock.patch.object(self.resume, "in_container", return_value=False), \
                mock.patch.object(self.resume.subprocess, "run") as run:
            with self.assertRaises(SystemExit) as e:
                self.resume.sh(["pdftotext", "a.pdf", "-"])
        self.assertIn("WSL", str(e.exception))  # the two ways that work
        run.assert_not_called()  # no shell script started

    def test_the_report_names_both_renderers(self):
        report = self.resume.renderers()
        self.assertEqual(set(report) - {"in_use"}, {"html", "container"})
        self.assertIn("needs", report["html"])


class PrintTest(unittest.TestCase):
    """One real print, when this PC has a browser"""

    @unittest.skipIf(os.environ.get("OFFEROWL_TEST_BROWSER") == "0" or not browser.find(), "no browser on this PC")
    def test_a_docx_prints_to_one_a4_page_and_compares_equal_to_itself(self):
        with tempfile.TemporaryDirectory() as d:
            docx = write_docx(pathlib.Path(d) / "t.docx", para("가나다 라마바 사아자 Lorem ipsum", '<w:spacing w:after="60"/>'))
            res = render.docx_to_pdf(docx, pathlib.Path(d) / "t.pdf")
            self.assertEqual(res["pages"], 1)
            raw = (pathlib.Path(d) / "t.pdf").read_bytes()
            box = re.search(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)", raw)
            self.assertAlmostEqual(float(box.group(1)), 595.3, delta=1.0)  # A4 from the DOCX's page size
            if shutil.which("pdftotext") and shutil.which("pdftoppm"):  # the comparison needs poppler
                import compare
                r = compare.compare(res["pdf"], res["pdf"])
                self.assertEqual(r["pages"][0]["pixels"], 0.0)
                self.assertIn("가나다", "".join(w["t"] for ln in compare.text_pages(res["pdf"])[0] for w in ln["words"]))


class PageCountTest(unittest.TestCase):
    def test_the_page_tree_count_is_read_without_poppler(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "x.pdf"
            f.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /Pages /Kids [2 0 R 3 0 R 4 0 R] /Count 3 >> endobj\n")
            self.assertEqual(render.pdf_pages(f), 3)


if __name__ == "__main__":
    unittest.main()
