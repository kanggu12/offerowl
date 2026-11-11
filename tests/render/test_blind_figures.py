# -*- coding: utf-8 -*-
"""The blind edition's figures and strings: src/overview_figures.py draws a covered name as a bar of its own width in the
table's mask_fill, in the hierarchy figure and the timeline, and nothing of the words under it; pdfmeta.strings reads the title
of every revision of a PDF, which the export check reads besides the text layer. The last class makes the fictional example as
a blind edition with the real render container, end to end, and is skipped when the container's image is not built.
Fictional names only.

Run: python3 -m unittest tests/render/test_blind_figures.py -v
"""
import hashlib  # the render image's tag
import importlib.util  # is Pillow here
import json  # the table
import os  # the Desktop of a test
import pathlib  # paths
import shutil  # is docker here, temporary folders
import subprocess  # docker image inspect
import sys  # the import path
import tempfile  # pictures and PDFs
import time  # the reading of the example
import unittest  # the runner
from unittest import mock  # the table of one drawing

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
sys.path.insert(0, str(ROOT / "tests" / "render"))  # the small PDF writer
import blind as B  # noqa: E402  src/blind.py
import pdfmeta  # noqa: E402  the strings a PDF keeps besides its text
from test_pdftools import write_pdf  # noqa: E402  a small PDF

HAVE_PIL = importlib.util.find_spec("PIL") is not None  # the figures are drawn with Pillow
TABLE = B.merged({"mask": ["Alphapay", "Betacommerce"]})  # two invented companies
RED = (0x8B, 0x1A, 0x1A)  # the shipped mask_fill


def pixels(im):
    """A picture's pixels in order: get_flattened_data where Pillow has it (12.1 and later, where getdata is deprecated and
    goes in 14), getdata on an older one."""
    flat = getattr(im, "get_flattened_data", None)
    return flat() if flat else im.getdata()


def reds(im, box=None) -> int:
    """How many pixels of a picture (or of a box of it) are the bars' red."""
    part = im.convert("RGB").crop(box) if box else im.convert("RGB")
    return sum(1 for px in pixels(part) if px == RED)


@unittest.skipUnless(HAVE_PIL, "Pillow is not installed: the figures cannot be drawn here")
class FigureTests(unittest.TestCase):
    """The same figure drawn as an ordinary and as a blind edition: they differ only where a covered name is, and there the blind
    one holds a solid bar as wide as the name and none of its letters."""

    def setUp(self):
        import overview_figures as OF  # imported here: it needs Pillow
        self.OF = OF
        self.dir = pathlib.Path(tempfile.mkdtemp())  # the pictures
        self.addCleanup(shutil.rmtree, self.dir, True)

    def draw(self, kind, prof, table):
        """One figure as drawn with this table (None for an ordinary edition)."""
        from PIL import Image  # read back
        with mock.patch.object(self.OF, "BT", table):  # the table the run would have read from OFFEROWL_BLIND_TABLE
            f = getattr(self.OF, kind)(prof, "en", self.dir / f"{kind}_{'b' if table else 'o'}.png", self.OF.NAVY)
        return Image.open(f).convert("RGB")

    def test_a_logo_is_read_in_a_logo_s_kinds_only(self):
        """A logo file is decoded as a PNG, JPEG, WebP, GIF, BMP or ICO; a file of another kind Pillow knows (a TGA here)
        reaches no decoder and the tile is not drawn (the run notes it and leaves that logo out)."""
        from PIL import Image, UnidentifiedImageError  # the files and the refusal
        for kind, suffix in (("PNG", ".png"), ("GIF", ".gif")):  # usual logo files
            f = self.dir / ("logo" + suffix)
            Image.new("RGBA", (64, 64), (20, 40, 80, 255)).save(f, kind)
            self.OF.logo_tile({"file": str(f)}, self.dir / f"tile_{kind}.png", self.OF.NAVY)
            self.assertTrue((self.dir / f"tile_{kind}.png").is_file(), kind)  # drawn
        tga = self.dir / "logo.png"  # named as a PNG, a TGA inside
        Image.new("RGBA", (64, 64), (20, 40, 80, 255)).save(tga, "TGA")
        with self.assertRaises(UnidentifiedImageError):
            self.OF.logo_tile({"file": str(tga)}, self.dir / "tile_tga.png", self.OF.NAVY)
        self.assertFalse((self.dir / "tile_tga.png").exists())  # nothing drawn from it

    def test_the_hierarchy_figure_covers_a_name_with_a_bar_of_its_width(self):
        from PIL import ImageChops  # where two pictures differ
        prof = {"summary": {"layers": [["Payments", "Kafka, Redis", "Alphapay checkout, order events"], ["Platform", "Kubernetes", "internal tools"]]}}
        plain, blind = self.draw("stack", prof, None), self.draw("stack", prof, TABLE)
        self.assertEqual(0, reds(plain))  # an ordinary figure has no bar
        box = ImageChops.difference(plain, blind).getbbox()  # where they differ
        S, lw = self.OF.S, int(self.OF.W * 0.27)  # the drawing scale and the layer names' column
        self.assertIsNotNone(box)
        self.assertGreaterEqual(box[0], lw)  # not in the layer names
        self.assertLess(box[3], 38 * S)  # only in the first row, which names the company
        want = self.OF.font(10.5).getlength("Alphapay")  # the covered name's width in the face it is drawn in
        mid = (box[1] + box[3]) // 2  # a line through the bar
        row = [blind.getpixel((x, mid)) == RED for x in range(blind.width)]  # the bar's pixels on that line
        width = sum(row)
        self.assertLess(abs(width - want), 3, (width, want))  # as wide as the name, to a pixel or two
        x0 = row.index(True)  # where the bar starts
        col = [blind.getpixel((x0 + width // 2, y)) == RED for y in range(blind.height)]  # the bar's pixels down its middle
        y0, y1 = col.index(True), len(col) - col[::-1].index(True)  # its top and bottom
        bar = (x0 + 2, y0 + 1, x0 + width - 2, y1 - 1)  # inside its edges
        self.assertGreater(reds(blind, bar), 0.95 * (bar[2] - bar[0]) * (bar[3] - bar[1]))  # solid
        grey = lambda px: max(px) - min(px) < 12 and max(px) < 200  # noqa: E731  a pixel of the grey words (the bar is red, the cell pale blue)
        span = (x0, box[1], x0 + width, box[3])  # where the name was, its letters' full height
        self.assertGreater(sum(1 for px in pixels(plain.crop(span)) if grey(px)), 50)  # the ordinary figure has its letters there
        self.assertEqual(0, sum(1 for px in pixels(blind.crop(span)) if grey(px)))  # the blind one has none of them, not even under the bar
        self.assertEqual(plain.crop((x0 + width + 2, 0, plain.width, plain.height)).tobytes(),
                         blind.crop((x0 + width + 2, 0, blind.width, blind.height)).tobytes())  # the words after it are the same as before

    def test_the_timeline_covers_a_company_in_its_bar(self):
        from PIL import ImageChops  # where two pictures differ
        prof = {"roles": [{"org": "Alphapay", "key": "a", "start": "2019.03", "end": "2022.02", "chart": "Backend engineer"},
                          {"org": "Omegasoft", "key": "b", "start": "2022.03", "end": None, "chart": "Platform engineer"}],
                "education": [{"school": "Fictional University", "degree": "BSc", "key": "e", "start": "2015.03", "end": "2019.02"}]}
        plain, blind = self.draw("timeline", prof, None), self.draw("timeline", prof, TABLE)
        self.assertEqual(plain.size, blind.size)  # the layout is the same
        self.assertEqual(0, reds(plain))
        self.assertGreater(reds(blind), 200)  # the bar where the company's name was
        box = ImageChops.difference(plain, blind).getbbox()  # only there
        self.assertLess(box[3], blind.height // 2)  # in the career row, above the study row and the axis
        both = self.draw("timeline", prof, B.merged({"mask": ["Omegasoft", "Alphapay"]}))  # both companies covered
        self.assertGreater(reds(both), reds(blind))  # a second bar


class StringTests(unittest.TestCase):
    """pdfmeta.strings reads every revision's title and author: an update leaves the older ones in the file."""

    def test_every_revision_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "t.pdf"
            write_pdf(f, [[(72, 72, 12, "Built the checkout")]])
            pdfmeta.stamp(f, "Alphapay Resume", "Gildong Hong")  # a first title with a covered name
            pdfmeta.stamp(f, "Resume (Blind version)", "Gildong Hong")  # then a clean one over it
            self.assertEqual("Resume (Blind version)", pdfmeta.read(f)["title"])  # what a reader shows
            self.assertIn("Alphapay Resume", pdfmeta.strings(f))  # what the file still holds
            self.assertEqual(["Alphapay"], B.leaks("\n".join(pdfmeta.strings(f)), TABLE))  # which the check finds


def render_image() -> str:
    """The render container's image as render/run.sh names it, or "" when Docker or the image is not here."""
    if not shutil.which("docker"):
        return ""
    tag = hashlib.md5((ROOT / "render" / "Dockerfile").read_bytes()).hexdigest()[:12]  # run.sh's rule
    r = subprocess.run(["docker", "image", "inspect", f"offerowl-render:{tag}"], capture_output=True)
    return f"offerowl-render:{tag}" if r.returncode == 0 else ""


@unittest.skipUnless(os.environ.get("OFFEROWL_TEST_RENDER") != "0" and render_image(), "the render container's image is not built here (render/run.sh builds it)")
@unittest.skipUnless((ROOT / "node_modules" / "docx").is_dir(), "the typesetting libraries are not installed (render/run.sh npm ci)")
class RealRenderTests(unittest.TestCase):
    """The fictional example made as a blind edition through the panel's API, typeset in the real container: no covered word in
    its text, titles or links; bars in its figure; a red band; the export under blind names; an ordinary edition after it."""

    def test_the_example_as_a_blind_edition(self):
        import pdftools  # the text layer
        from apps.api import app as appmod  # the panel's API
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-blind-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.dict(os.environ, {"OFFEROWL_PANEL_BACKEND": "none", "OFFEROWL_DESKTOP": str(tmp / "Desktop"), "OFFEROWL_RENDERER": "container"}):
            a = appmod.Api(tmp)
            a.add_example("ko")  # the fictional person
            for _ in range(400):
                if a.tasks.state().get("ingest", {}).get("state") != "running":
                    break
                time.sleep(0.05)
            a.keep_all()
            a.set_blind({"table": {"mask": ["알파페이", "베타커머스", r"gildong@example\.com", "010-0000-0000", r"github\.com/example-gildong"],
                                   "mask_whole": [r"gildong@example\.com", "010-0000-0000", r"github\.com/example-gildong"]}})
            a.tasks._build("-general", "ko", "navy", 3, False, False, True)  # a blind edition
            self.assertEqual("done", a.tasks.state()["build:-general"]["state"], a.tasks.state()["build:-general"])
            out = a.tasks.build_dir("-general", "ko")
            rec = json.loads((out / "build.json").read_text(encoding="utf-8"))
            self.assertEqual(([], True), (rec["issues"], rec["blind"]))  # the checks pass on a blind edition
            for f in ("resume.pdf", "deck.pdf"):  # its text, titles and links
                text = pdftools.text(out / f) + "\n".join(pdfmeta.strings(out / f))
                for word in ("알파페이", "베타커머스", "gildong@example.com", "010-0000-0000", "example-gildong"):
                    self.assertNotIn(word, text, f)
                self.assertIn("■", pdftools.text(out / f))  # the bars' squares stand where the words were
            from PIL import Image  # the first page as the panel shows it
            page = Image.open(out / "preview" / "r-1.png").convert("RGB")
            near = lambda px: all(abs(c - r) < 40 for c, r in zip(px, RED))  # noqa: E731  the red of the bars and the band, through the page's scaling
            top = sum(1 for x in range(page.width) for y in range(0, 12) if near(page.getpixel((x, y))))  # the band across the top
            self.assertGreater(top, page.width * 3)
            names = a.tasks.export("-general", "ko")  # the export reads them and lets them go
            self.assertEqual(["홍길동 블라인드 이력서.pdf", "홍길동 블라인드 포트폴리오.pdf"], names)
            a.tasks._build("-general", "ko", "navy", 3, False, False, False)  # the same edition made ordinary again
            self.assertNotIn("blind", json.loads((out / "build.json").read_text(encoding="utf-8")))
            self.assertIn("알파페이", pdftools.text(out / "resume.pdf"))  # the words are back
            self.assertTrue((out / "resume.txt").is_file())  # and its plain words
        left = [p.name for p in (ROOT / "output").rglob("*") if p.is_file() and p.name.startswith(f"owl_{a.tasks.short('-general')}")]
        self.assertEqual([], left)  # nothing of the person's stays in the engine's folder


def browser_renderer_ok() -> bool:
    """Can the browser renderer (OFFEROWL_RENDERER=html) typeset on this PC: a browser, Node.js, Pillow and the fonts?"""
    if os.environ.get("OFFEROWL_TEST_BROWSER") == "0" or not (ROOT / "node_modules" / "docx").is_dir():
        return False
    try:
        import resume  # src/resume.py: its report of the two renderers
        return bool(resume.renderers()["html"]["ok"])
    except Exception:  # noqa: BLE001  a PC where the report itself cannot run cannot typeset either
        return False


@unittest.skipUnless(browser_renderer_ok(), "the browser renderer cannot typeset here (a browser, Node.js, Pillow and the fonts)")
class BrowserRenderTests(unittest.TestCase):
    """The same blind resume typeset by the PC's browser (the panel's renderer where there is no Docker): the band across the very top
    of page one, as LibreOffice places it, and each bar as wide as its words."""

    def test_the_band_and_the_bars_with_the_browser(self):
        import pdftools  # the text and the page pictures
        import resume  # the pipeline
        from PIL import Image  # the page
        out = "owl_blindtest_ko"  # a name no edition uses
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-blind-html-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for f in [*(ROOT / "output").glob(out + "*"), *(ROOT / "output" / "_figures").glob(out + "_*")]:  # nothing of an earlier run
            f.unlink()
        self.addCleanup(lambda: [f.unlink() for f in [*(ROOT / "output").glob(out + "*"), *(ROOT / "output" / "_figures").glob(out + "_*"),
                                                     *(ROOT / "output" / "_inputs").glob(out + "*")] if f.is_file()])
        table = tmp / "table.json"  # the phone number covered whole: one bar of a width the metrics know
        table.write_text(json.dumps({"mask": ["010-0000-0000", "알파페이"], "mask_whole": ["010-0000-0000"]}), encoding="utf-8")
        cfg = tmp / "job.json"
        cfg.write_text(json.dumps({"lang": "ko", "out": out, "theme": "navy"}), encoding="utf-8")
        env = {**os.environ, "OFFEROWL_BLIND": "1", "OFFEROWL_BLIND_LANG": "ko", "OFFEROWL_BLIND_TABLE": str(table)}  # this build's own
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "html"}):  # the browser, not the container
            pdf = resume.build(str(ROOT / "examples" / "sample_ko.json"), str(cfg), env)
        text = pdftools.text(pdf)
        self.assertNotIn("010-0000-0000", text)  # covered
        self.assertNotIn("알파페이", text)
        page = Image.open(pdftools.render_png(pdf, tmp / "p", dpi=72, first=1, last=1)[0]).convert("RGB")  # 1 px is 1 pt
        red = lambda px: px[0] > 110 and px[1] < 70 and px[2] < 70  # noqa: E731  the band's and the bars' dark red
        top = [sum(1 for x in range(page.width) if red(page.getpixel((x, y)))) for y in range(0, 14)]  # the band's rows
        self.assertGreater(min(top[1:12]), page.width * 0.6, top)  # across the very top of the page, not over the text below it
        metrics = json.loads((ROOT / "src" / "blind_metrics.json").read_text(encoding="utf-8"))["regular"]
        want = sum(metrics["ascii"][c] for c in "010-0000-0000") * 8  # the number's width at the contacts' 8pt
        rows = [[x for x in range(page.width // 2, page.width) if red(page.getpixel((x, y)))] for y in range(16, 120)]  # the contacts' column, row by row
        bars = sorted({r[-1] - r[0] + 1 for r in rows if r})  # the width of the bar on each row that crosses one
        self.assertTrue(any(abs(b - want) <= 3 for b in bars), (bars, want))  # the phone's bar as wide as the number, to a few points (one square was 7)


if __name__ == "__main__":
    unittest.main()
