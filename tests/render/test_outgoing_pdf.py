#!/usr/bin/env python3
"""What a resume PDF carries when it leaves the PC, besides its words: page 1's contacts as links a recruiter can click
(LibreOffice drops a link inside a table cell, where the header keeps them), no tool's name in its properties, pictures
LibreOffice exported whole, and the competency figure's stepped arrow plates. The small PDFs are written here; one class
typesets the fictional example in the render container, as the panel's builds are.

  python3 -m unittest tests/render/test_outgoing_pdf.py -v
"""
import json  # the exporter's options, the example profile
import pathlib  # paths
import shutil  # the build's folder
import sys  # the import path
import tempfile  # a folder per test
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT / "src", ROOT / "tests" / "render"):  # the engine, the helpers beside this file
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import overview_figures as OF  # noqa: E402  the overview figures
import pdfmeta  # noqa: E402  the title and author written into a PDF
import resume  # noqa: E402  the typesetting, the contacts' links
from test_blind_figures import render_image  # noqa: E402  is the render container's image here
from test_pdftools import write_pdf  # noqa: E402  a small PDF with a text layer

try:
    import pikepdf  # a second reader of the files written here, where it is installed (qpdf underneath)
except ImportError:
    pikepdf = None

# a fictional person: an email field and the profile format's own list of links, one written without its address
PERSON = {"name": "홍길동", "email": "gildong@example.com",
          "links": [["GitHub", "github.com/example-gildong", "https://github.com/example-gildong"], ["Blog", "blog.example.org"]]}
WANT = {"mailto:gildong@example.com", "https://github.com/example-gildong", "https://blog.example.org"}  # what each opens


def links(pdf: pathlib.Path, page: int = 0) -> list:
    """The web and mail links of one page as pdfmeta reads them: [(address, (x0, y0, x1, y1) from the top left)]."""
    pages = pdfmeta.page_links(pdf)
    return [(k["uri"], (k["x0"], k["y0"], k["x1"], k["y1"])) for k in pages[page]["links"]] if page < len(pages) else []


def header_pdf(path: pathlib.Path) -> None:
    """Page 1 prints the contacts as a header does; page 2 repeats the email, which must stay plain there."""
    write_pdf(path, [[(72, 80, 10, "gildong@example.com"), (72, 100, 10, "github.com/example-gildong"), (72, 120, 10, "blog.example.org")],
                     [(72, 80, 10, "gildong@example.com")]])


class ContactLinksTests(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())  # the PDFs go here
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.pdf = self.dir / "resume.pdf"
        header_pdf(self.pdf)

    def test_each_contact_on_page_one_becomes_a_link_over_its_words(self):
        self.assertEqual(3, resume.contact_links(self.pdf, PERSON))
        got = links(self.pdf)
        self.assertEqual(WANT, {uri for uri, _ in got})
        for uri, (x0, y0, x1, y1) in got:  # over the words: from x 72, around their baseline, counted from the top
            self.assertAlmostEqual(72, x0, delta=1.5, msg=uri)
            self.assertGreater(x1 - x0, 50, uri)
            line = {"mailto:gildong@example.com": 80, "https://github.com/example-gildong": 100, "https://blog.example.org": 120}[uri]
            self.assertTrue(y0 - 3 <= line <= y1 + 3, (uri, y0, y1))
        self.assertEqual([], links(self.pdf, 1))  # page 2 repeats the email, as a footer would: no link there

    @unittest.skipUnless(pikepdf, "pikepdf is not installed")
    def test_another_reader_finds_the_file_whole(self):
        resume.contact_links(self.pdf, PERSON)
        with pikepdf.open(str(self.pdf)) as doc:  # qpdf reads the update as its own
            self.assertEqual([], (doc.check_pdf_syntax if hasattr(doc, "check_pdf_syntax") else doc.check)())
            annots = doc.pages[0].obj.get("/Annots", [])
            self.assertEqual(WANT, {str(a.A.URI) for a in annots})
            self.assertEqual(2, len(doc.pages))

    @unittest.skipUnless(shutil.which("pdfinfo"), "poppler is not installed")
    def test_poppler_reads_it_without_a_complaint(self):
        import subprocess  # poppler's reader, as a second opinion
        resume.contact_links(self.pdf, PERSON)
        r = subprocess.run(["pdfinfo", str(self.pdf)], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("Syntax", r.stderr)  # no repaired cross-reference, no broken object
        self.assertIn("Pages:           2", r.stdout)

    def test_a_page_with_links_of_its_own_keeps_them(self):
        resume.contact_links(self.pdf, {"name": "홍길동", "email": "gildong@example.com"})  # one link already on the page
        self.assertEqual(2, resume.contact_links(self.pdf, PERSON))  # the other two join it
        self.assertEqual(WANT, {uri for uri, _ in links(self.pdf)})

    def test_a_file_this_cannot_update_is_left_as_it_was(self):
        raw = self.pdf.read_bytes()
        cut = self.dir / "cut.pdf"  # no trailer at its end, as a file cut off in a download
        cut.write_bytes(raw[:raw.rindex(b"trailer")])
        self.assertEqual(0, resume.contact_links(cut, PERSON))
        self.assertEqual(raw[:raw.rindex(b"trailer")], cut.read_bytes())

    def test_a_second_pass_adds_none(self):
        resume.contact_links(self.pdf, PERSON)
        self.assertEqual(0, resume.contact_links(self.pdf, PERSON))
        self.assertEqual(3, len(links(self.pdf)))

    def test_an_address_the_page_does_not_show_gets_no_link(self):
        person = dict(PERSON, website="https://example.net/me")  # in the profile, not on the page
        self.assertEqual(3, resume.contact_links(self.pdf, person))
        self.assertNotIn("https://example.net/me", {uri for uri, _ in links(self.pdf)})

    def test_a_person_with_no_contacts_leaves_the_file_as_it_was(self):
        before = self.pdf.read_bytes()
        self.assertEqual(0, resume.contact_links(self.pdf, {"name": "홍길동"}))
        self.assertEqual(before, self.pdf.read_bytes())

    def test_the_title_still_goes_in_after_the_links(self):
        resume.contact_links(self.pdf, PERSON)
        self.assertTrue(pdfmeta.stamp(self.pdf, "홍길동 이력서", "홍길동", creator=""))  # an ordinary incremental update
        self.assertEqual({"title": "홍길동 이력서", "author": "홍길동"}, pdfmeta.read(self.pdf))
        self.assertEqual(3, len(links(self.pdf)))


@unittest.skipUnless(pikepdf, "pikepdf is not installed")
class NoToolNameTests(unittest.TestCase):
    def test_an_outgoing_pdf_names_the_person_and_no_program(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = pathlib.Path(d) / "resume.pdf"
            write_pdf(pdf, [[(72, 80, 10, "Gildong Hong")]])
            self.assertTrue(pdfmeta.stamp(pdf, "홍길동 이력서", "홍길동", creator=""))
            with pikepdf.open(str(pdf)) as doc:
                info = doc.docinfo
                self.assertEqual("홍길동", str(info.get("/Author")))
                self.assertEqual("", str(info.get("/Creator", "")))  # not "Offerowl"
                self.assertNotIn("/Producer", info)  # nor LibreOffice

    def test_every_resume_and_deck_stamp_names_no_creator(self):
        import inspect  # the source of the step that stamps every typeset PDF
        src = inspect.getsource(resume.stamp_meta)
        calls = src.count("pdfmeta.stamp(")
        self.assertGreater(calls, 0)
        self.assertEqual(calls, src.count('creator="")'), "a PDF that goes out would name a program")


class LosslessExportTests(unittest.TestCase):
    def test_the_export_keeps_every_picture_whole(self):
        kind, _, options = resume.PDF_EXPORT.partition(":writer_pdf_Export:")
        self.assertEqual("pdf", kind)
        opts = json.loads(options)
        self.assertEqual("false", opts["ReduceImageResolution"]["value"])  # LibreOffice's default resamples to 300 ppi
        self.assertEqual("true", opts["UseLosslessCompression"]["value"])  # and stores pictures as JPEG

    def test_every_conversion_uses_it(self):
        import inspect  # the two places a DOCX becomes a PDF
        for fn in (resume.build, resume.docx_to_pdf):
            src = inspect.getsource(fn)
            self.assertIn("PDF_EXPORT", src, fn.__name__)
            self.assertNotIn('--convert-to pdf ', src, fn.__name__)
            self.assertNotIn('"--convert-to", "pdf"', src, fn.__name__)


class SteppedStackTests(unittest.TestCase):
    """The competency figure: arrow plates that step out toward the bottom, darker as they go down, the pale boxes in one
    column with a clear gap past the longest tip."""

    LAYERS = [["AI 서비스", "모델 서빙, RAG", "결제 서비스"], ["운영", "Observability", "사내 SRE"], ["오케스트레이션", "Kubernetes", "배포 플랫폼"],
              ["네트워크", "InfiniBand", "학습 클러스터"], ["데이터센터", "전력, 냉방", "데이터센터 구축"]]

    @classmethod
    def setUpClass(cls):
        from PIL import Image  # the figure as drawn
        cls.dir = pathlib.Path(tempfile.mkdtemp())
        path = OF.stack({"summary": {"layers": cls.LAYERS}}, "ko", cls.dir / "stack.png", OF.NAVY)
        cls.im = Image.open(path).convert("RGB")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, True)

    def row(self, i: int, dy: int) -> list:
        """The pixels across the figure, dy below the top of plate i."""
        y = i * (38 + 4) * OF.S + dy
        return [self.im.getpixel((x, y)) for x in range(self.im.width)]

    @staticmethod
    def white(c) -> bool:
        return min(c) >= 248

    def test_each_plate_below_is_longer_by_one_step(self):
        ends = []
        for i in range(len(self.LAYERS)):
            px = self.row(i, 3)  # just inside the plate's top edge, above its name
            ends.append(next(x for x, c in enumerate(px) if self.white(c)))  # where the plate's body ends
        steps = [b - a for a, b in zip(ends, ends[1:])]
        for s in steps:
            self.assertAlmostEqual(6 * OF.S, s, delta=2, msg=steps)  # a staircase, never plates of one width

    def test_the_plates_darken_toward_the_bottom_and_keep_white_words_readable(self):
        def lum(c):  # relative luminance (WCAG)
            v = [x / 255 for x in c]
            v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
            return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
        fills = [self.row(i, 3)[2] for i in range(len(self.LAYERS))]
        ls = [lum(c) for c in fills]
        self.assertEqual(ls, sorted(ls, reverse=True), fills)  # lighter at the top
        self.assertEqual(len(set(fills)), len(fills), fills)  # each layer its own shade
        self.assertEqual(OF.NAVY, fills[-1])  # the theme's own navy at the bottom
        self.assertGreaterEqual((1.05) / (ls[0] + 0.05), 4.5, fills[0])  # white names on the lightest plate

    def test_the_pale_boxes_stand_in_one_column_clear_of_the_longest_tip(self):
        starts = []
        for i in range(len(self.LAYERS)):
            px = self.row(i, 3)
            end = next(x for x, c in enumerate(px) if self.white(c))
            starts.append(next(x for x in range(end, len(px)) if not self.white(px[x])))  # the pale box's left edge
        self.assertLessEqual(max(starts) - min(starts), 1, starts)
        last = len(self.LAYERS) - 1
        mid = self.row(last, 38 * OF.S // 2)  # through the bottom plate's tip
        tip = max(x for x in range(starts[last]) if sum(abs(a - b) for a, b in zip(mid[x], OF.NAVY)) < 60)
        self.assertGreaterEqual(starts[last] - tip, 6 * OF.S, (tip, starts[last]))  # a clear gap, never a hair's (2026-10-26)


@unittest.skipUnless(pikepdf, "pikepdf is not installed")
@unittest.skipUnless(render_image(), "the render container's image is not built here (render/run.sh builds it)")
@unittest.skipUnless((ROOT / "node_modules" / "docx").is_dir(), "the typesetting libraries are not installed (render/run.sh npm ci)")
class ExampleBuildTests(unittest.TestCase):
    """The fictional example typeset in the container, under a name of its own (another test may typeset the example)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="outgoing-", dir=str(ROOT / "output")))  # where the container sees it
        prof = cls.tmp / "outgoing_example.json"
        shutil.copyfile(resume.EXAMPLE, prof)
        cls.pdf = resume.build(str(prof))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        for f in (ROOT / "output").glob("outgoing_example*"):
            f.unlink(missing_ok=True)

    def test_page_one_links_the_contacts_it_prints(self):  # LibreOffice dropped them: they are in a table cell
        got = {uri for uri, _ in links(self.pdf)}
        self.assertLessEqual({"mailto:gildong@example.com", "https://github.com/example-gildong"}, got)
        with pikepdf.open(str(self.pdf)) as doc:  # LibreOffice's file with the links and the title written after it, read whole
            self.assertEqual([], (doc.check_pdf_syntax if hasattr(doc, "check_pdf_syntax") else doc.check)())

    def test_the_overview_figure_keeps_its_pixels(self):
        def images(res, out):  # the pictures a page draws, through any form it draws them in
            for _, x in (res.get("/XObject") or {}).items():
                if x.get("/Subtype") == "/Image":
                    out.append(x)
                elif x.get("/Subtype") == "/Form" and "/Resources" in x:
                    images(x.Resources, out)
            return out
        with pikepdf.open(str(self.pdf)) as doc:
            pics = images(doc.pages[0].obj.Resources, [])
            widths = [int(x.Width) for x in pics]
            self.assertGreaterEqual(max(widths), OF.W - 2, widths)  # drawn 694 px wide at 4x; 300 ppi would leave about 2170
            filters = {str(f) for x in pics for f in (x.get("/Filter") if isinstance(x.get("/Filter"), pikepdf.Array) else [x.get("/Filter")]) if f}
            self.assertNotIn("/DCTDecode", filters)  # no picture stored as JPEG

    def test_its_properties_name_the_person_only(self):
        with pikepdf.open(str(self.pdf)) as doc:
            self.assertEqual("", str(doc.docinfo.get("/Creator", "")))
            self.assertNotIn("/Producer", doc.docinfo)
            self.assertEqual("홍길동", str(doc.docinfo.get("/Author")))


if __name__ == "__main__":
    unittest.main()
