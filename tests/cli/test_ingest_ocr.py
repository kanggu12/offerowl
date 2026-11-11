"""src/ingest.py's reading of pictures and scans: the copies it makes of a person's file never stay behind, two readings in the
typesetting image never share a folder, and a tool that hangs is given up on. No OCR tool is run.

Run: python3 -m unittest discover -s tests/cli -v
"""
import pathlib  # paths
import shutil  # the tools on PATH, made absent
import subprocess  # the shape of a finished command
import sys  # module search path
import tempfile  # throwaway folders, and the temporary folder the code uses
import unittest  # the test framework
from unittest import mock  # the tools made absent or made to answer

from support import SRC

sys.path.insert(0, str(SRC))  # ingest.py is a flat module in src/
import ingest  # noqa: E402  the module under test


try:  # the enlarging needs Pillow, which a bare Python lacks (ingest.py reads the picture as it is then)
    import PIL  # noqa: F401
except ImportError:
    PIL = None


class OcrCopies(unittest.TestCase):
    @unittest.skipIf(PIL is None, "Pillow is not installed: no enlarged copy is made")
    def test_a_screenshot_s_enlarged_copy_goes(self):
        from PIL import Image  # a small picture to stand for a form's screenshot
        with tempfile.TemporaryDirectory() as d:
            shot = pathlib.Path(d) / "form.png"  # the person's screenshot
            Image.new("RGB", (40, 20), "white").save(shot)
            scratch = pathlib.Path(d) / "tmp"  # where the code's temporary folders go during the test
            scratch.mkdir()
            with mock.patch.object(tempfile, "tempdir", str(scratch)), mock.patch.object(shutil, "which", return_value=None):  # no OCR tool here
                ingest.ocr(shot, block=True)  # enlarged, then nothing can read it
            self.assertEqual([], list(scratch.iterdir()))  # the enlarged copy went with its folder

    def test_two_readings_in_the_image_get_folders_of_their_own_and_a_time_limit(self):
        calls = []  # (the folder the script works in, the time limit)

        def run(cmd, **kw):  # the image answers at once
            calls.append((cmd[-1].split(" && ")[0], kw.get("timeout")))
            return subprocess.CompletedProcess(cmd, 0, "text", "")

        with tempfile.TemporaryDirectory() as d:
            scan = pathlib.Path(d) / "scan.pdf"  # a person's file
            scan.write_bytes(b"%PDF-1.4 fictional")
            with mock.patch.object(ingest.subprocess, "run", side_effect=run):
                self.assertEqual("text", ingest.in_container(scan, lambda n: f"pdftotext {n} -"))
                ingest.in_container(scan, lambda n: f"pdftotext {n} -")
        self.assertNotEqual(calls[0][0], calls[1][0])  # a folder of its own each time
        self.assertTrue(all(limit for _, limit in calls))  # never without a time limit
        self.assertEqual([], list((ingest.ROOT / "output" / "_ingest").glob("_ocr*")))  # nothing left behind

    def test_a_hung_tool_counts_as_no_text(self):
        def hang(cmd, **kw):  # the tool never answers
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

        with tempfile.TemporaryDirectory() as d:
            scan = pathlib.Path(d) / "scan.pdf"
            scan.write_bytes(b"%PDF-1.4 fictional")
            with mock.patch.object(ingest.subprocess, "run", side_effect=hang):
                self.assertEqual("", ingest.in_container(scan, lambda n: f"pdftotext {n} -"))  # read as a file without text
        self.assertEqual([], list((ingest.ROOT / "output" / "_ingest").glob("_ocr*")))  # and its copy is gone

class OfficeParts(unittest.TestCase):
    """A .docx or .pptx is a zip: a part that says it inflates far beyond any document's (a zip bomb) is left out, never
    inflated; zipfile holds the part to the size it says, so a part cannot claim less."""

    def docx(self, folder: pathlib.Path, body: str) -> pathlib.Path:
        import zipfile  # the document's own format
        f = folder / "letter.docx"
        with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>" + body + "</w:t></w:r></w:p></w:body></w:document>")
        return f

    def test_a_part_over_the_cap_is_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            f = self.docx(pathlib.Path(d), "Payment service rewrite " + "x" * 5000)
            self.assertIn("Payment service rewrite", ingest.to_text(f))  # read as usual
            with mock.patch.object(ingest, "MAX_PART", 1000):  # a cap below this part's size
                self.assertEqual("", ingest.to_text(f))  # not inflated: no text from it


if __name__ == "__main__":
    unittest.main()
