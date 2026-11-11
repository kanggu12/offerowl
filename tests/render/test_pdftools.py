# -*- coding: utf-8 -*-
"""src/pdftools.py with both readers, poppler and PDFium, on small PDFs written here. A reader this PC lacks is skipped.

Run: python3 -m unittest tests/render/test_pdftools.py -v
"""
import os  # the reader setting
import pathlib  # paths
import re  # the layout's boxes
import shutil  # is poppler here
import sys  # the import path
import tempfile  # the PDFs and pictures
import unittest  # the test runner
from unittest import mock  # the reader setting, for one test at a time

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
import check_render as CR  # noqa: E402  the line checks that read these boxes
import pdftools as P  # noqa: E402  the module under test

W, H = 595, 842  # A4 in points


def write_pdf(path: pathlib.Path, pages: list) -> None:
    """A small PDF: pages is a list of pages, a page a list of (x, y from the top, size, text). Helvetica, one of the fonts every
    PDF reader has, so a test needs no font file."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]  # 1 catalog, 2 page tree, 3 font
    kids = []  # the page objects
    for lines in pages:  # each page: its content stream, then the page that points at it
        stream = "BT " + " ".join(f"/F1 {s} Tf 1 0 0 1 {x} {H - y} Tm ({t}) Tj" for x, y, s, t in lines) + " ET"  # one text run per line
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Contents {len(objects)} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(len(objects))
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offsets = "%PDF-1.4\n", []  # the file, and where each object starts
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out)  # the table of offsets
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(out.encode("latin-1"))


READERS = {"poppler": bool(shutil.which("pdftotext") and shutil.which("pdftoppm") and shutil.which("pdfinfo")), "pdfium": P.have_pdfium()}  # which of the two are here


class BothReaders(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()  # the PDFs go here
        self.addCleanup(self.dir.cleanup)
        self.root = pathlib.Path(self.dir.name)
        self.pdf = self.root / "t.pdf"
        write_pdf(self.pdf, [[(72, 72, 12, "Gildong Hong"), (72, 90, 10, "Built the payment platform"), (400, 90, 10, "2023")], [(72, 72, 12, "Second page")]])

    def each(self):
        """(name, the setting for that reader) for each reader this PC has."""
        for name, here in READERS.items():
            if here:  # a reader that is not here is left out
                yield name, ({"OFFEROWL_PDF_READER": "pdfium"} if name == "pdfium" else {"OFFEROWL_PDF_READER": ""})

    def test_at_least_one_reader_is_here(self):  # otherwise every test below would pass by testing nothing
        if not any(READERS.values()):
            self.skipTest("neither poppler nor pypdfium2 is on this PC")

    def test_the_reader_setting_is_kept(self):
        for name, setting in self.each():
            with self.subTest(name), mock.patch.dict(os.environ, setting):
                self.assertEqual(P.reader(), name)

    def test_text_keeps_the_words_and_ends_each_page(self):
        for name, setting in self.each():
            with self.subTest(name), mock.patch.dict(os.environ, setting):
                text = P.text(self.pdf)
                self.assertIn("Gildong Hong", text)
                self.assertIn("Second page", text)
                self.assertEqual(text.count("\f"), 2)  # one form feed per page
                self.assertLess(text.index("Gildong"), text.index("Second"))

    def test_a_page_range(self):
        for name, setting in self.each():
            with self.subTest(name), mock.patch.dict(os.environ, setting):
                text = P.text(self.pdf, first=2, last=2)
                self.assertIn("Second page", text)
                self.assertNotIn("Gildong", text)

    def test_layout_keeps_columns_on_one_line(self):
        for name, setting in self.each():
            with self.subTest(name), mock.patch.dict(os.environ, setting):
                line = next(ln for ln in P.text(self.pdf, layout=True).splitlines() if "payment" in ln)
                self.assertIn("2023", line)  # the year stays beside the sentence it was printed next to

    def test_info(self):
        for name, setting in self.each():
            with self.subTest(name), mock.patch.dict(os.environ, setting):
                got = P.info(self.pdf)
                self.assertEqual(got["pages"], 2)
                self.assertAlmostEqual(got["width"], W, delta=1)
                self.assertAlmostEqual(got["height"], H, delta=1)

    def test_the_boxes_say_the_same_with_both_readers(self):
        found = {}  # reader to the boxes of its lines
        for name, setting in self.each():
            with self.subTest(name), mock.patch.dict(os.environ, setting):
                xml = P.bbox_layout(self.pdf)
                self.assertEqual(len(re.findall(r"<page ", xml)), 2)
                found[name] = sorted((float(m.group(2)), float(m.group(1))) for m in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)"', xml))
                self.assertIn("<word ", xml)
        if len(found) == 2:  # both here: the lines start within a point or two of each other
            self.assertEqual(len(found["poppler"]), len(found["pdfium"]))
            for a, b in zip(found["poppler"], found["pdfium"]):
                self.assertAlmostEqual(a[0], b[0], delta=3)
                self.assertAlmostEqual(a[1], b[1], delta=3)

    def test_page_pictures_are_named_by_page(self):
        for name, setting in self.each():
            with self.subTest(name), mock.patch.dict(os.environ, setting):
                out = self.root / name
                out.mkdir()
                files = P.render_png(self.pdf, out / "p", dpi=30, gray=True)
                self.assertEqual([f.name for f in files], ["p-1.png", "p-2.png"])
                self.assertEqual(files[0].read_bytes()[:4], b"\x89PNG")
                self.assertEqual([f.name for f in P.render_png(self.pdf, out / "q", dpi=30, first=2, last=2)], ["q-2.png"])

    def test_a_body_that_touches_the_page_number_is_caught_with_both_readers(self):
        touching = self.root / "touching.pdf"
        clear = self.root / "clear.pdf"
        body = "A wide line of body text that runs across most of the page and comes down low"  # wider than a footer group
        write_pdf(touching, [[(72, 72, 10, "Top line"), (72, 795, 10, body), (72, 800, 8, "Name"), (500, 800, 8, "1")]])
        write_pdf(clear, [[(72, 72, 10, "Top line"), (72, 700, 10, body), (72, 800, 8, "Name"), (500, 800, 8, "1")]])
        for name, setting in self.each():
            with self.subTest(name), mock.patch.dict(os.environ, setting):
                self.assertEqual(len(CR.footer_clearance(str(touching))), 1)  # the planted defect
                self.assertEqual(CR.footer_clearance(str(clear)), [])  # and no false alarm


class NoReader(unittest.TestCase):
    def test_it_says_so(self):
        with mock.patch.object(P, "have_poppler", lambda: False), mock.patch.dict(sys.modules, {"pypdfium2": None}):
            with self.assertRaises(P.PdfToolsMissing):
                P.text("nothing.pdf")


if __name__ == "__main__":
    unittest.main()
