# -*- coding: utf-8 -*-
"""src/pdfmeta.py: a PDF's title and author written as an incremental update, read back by it and by the PC's readers.

Run: python3 -m unittest tests/render/test_pdfmeta.py -v
"""
import pathlib  # paths
import shutil  # is poppler here
import subprocess  # pdfinfo, when the PC has it
import sys  # the import path
import tempfile  # the PDFs
import unittest  # the test runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT / "src"))  # the module under test
sys.path.insert(0, str(ROOT / "tests" / "render"))  # the small PDF writer of the reader tests
import pdfmeta as M  # noqa: E402  the module under test
import pdftools as P  # noqa: E402  the page reader, to see that nothing printed changed
from test_pdftools import write_pdf  # noqa: E402  a two-page PDF with text


class Meta(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()  # the PDFs go here
        self.addCleanup(self.dir.cleanup)
        self.pdf = pathlib.Path(self.dir.name) / "owl_1a2b3c4d_ko.pdf"  # a build name, as a browser leaves it
        write_pdf(self.pdf, [[(72, 72, 12, "Gildong Hong"), (72, 90, 10, "Built the payment platform")], [(72, 72, 12, "Second page")]])

    def test_a_korean_title_and_name_are_written_and_read_back(self):
        self.assertEqual({"title": None, "author": None}, M.read(self.pdf))  # nothing said before
        self.assertTrue(M.stamp(self.pdf, "홍길동 이력서", "홍길동"))  # written
        self.assertEqual({"title": "홍길동 이력서", "author": "홍길동"}, M.read(self.pdf))  # and read back

    def test_stamping_again_replaces_the_first(self):
        M.stamp(self.pdf, "Gildong Hong Resume", "Gildong Hong")  # the English edition
        M.stamp(self.pdf, "Gildong (Han) Resume\\", "Gildong Hong")  # again, with characters a literal string escapes
        self.assertEqual({"title": "Gildong (Han) Resume\\", "author": "Gildong Hong"}, M.read(self.pdf))  # the newer one

    def test_the_pages_are_untouched(self):
        before = self.pdf.read_bytes()  # the file as printed
        M.stamp(self.pdf, "홍길동 이력서", "홍길동")
        after = self.pdf.read_bytes()
        self.assertTrue(after.startswith(before.rstrip(b"\n")))  # an update appended after it, nothing rewritten
        if P.reader():  # a reader on this PC sees the same pages and text
            self.assertEqual(2, P.info(self.pdf)["pages"])
            self.assertIn("Gildong Hong", P.text(self.pdf))

    @unittest.skipUnless(shutil.which("pdfinfo"), "poppler is not on this PC")
    def test_poppler_shows_the_new_title(self):
        M.stamp(self.pdf, "홍길동 포트폴리오", "홍길동")
        info = subprocess.run(["pdfinfo", str(self.pdf)], capture_output=True, text=True, encoding="utf-8").stdout  # as a reader shows it
        self.assertIn("홍길동 포트폴리오", info)
        self.assertRegex(info, r"Author:\s+홍길동")

    def test_an_encrypted_file_or_one_with_no_catalogue_is_left_as_it_was(self):
        raw = self.pdf.read_bytes()
        end = raw.rindex(b"/Root")  # the last trailer's catalogue
        for name, body in (("locked.pdf", raw[:end] + b"/Encrypt 9 0 R " + raw[end:]),  # a new trailer would drop its key
                           ("nocat.pdf", raw[:end] + b"/Rout" + raw[end + 5:])):  # a trailer that names no catalogue
            f = self.pdf.with_name(name)
            f.write_bytes(body)
            self.assertFalse(M.stamp(f, "x", "y"), name)  # refused
            self.assertEqual(body, f.read_bytes(), name)  # and untouched

    def test_a_file_it_cannot_update_is_left_as_it_was(self):
        odd = self.pdf.with_name("stream.pdf")  # no classic trailer at its end (a cross-reference stream)
        odd.write_bytes(b"%PDF-1.5\n1 0 obj\n<< /Type /Catalog >>\nendobj\nstartxref\n9\n%%EOF\n")
        before = odd.read_bytes()
        self.assertFalse(M.stamp(odd, "x", "y"))  # refused
        self.assertEqual(before, odd.read_bytes())  # and untouched


if __name__ == "__main__":
    unittest.main()
