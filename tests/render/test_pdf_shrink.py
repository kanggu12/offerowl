# -*- coding: utf-8 -*-
"""src/pdf_shrink.py: a deck made smaller with no visible change, for an upload limit. The deck is written here as Chrome
prints one, in small (16:9 pages under a px-to-pt matrix, coordinates of seven decimals, words placed by Td moves, a logo
of few colours with a transparency mask, a gradient of many, a link, a title and an author), so no typesetting runs. The
tests that read pixels or text need pikepdf and a PDF reader; the ones that do not need neither.

Run: python3 -m unittest tests/render/test_pdf_shrink.py -v
"""
import json  # the command line's result
import pathlib  # paths
import re  # the text, spaces aside
import shutil  # the test's folders
import sys  # the import path
import tempfile  # a folder per test
import unittest  # the runner
import zlib  # the images' bytes, packed as Chrome packs them
from decimal import Decimal  # the operands pikepdf reads
from unittest import mock  # a Python with no pikepdf, stood in for

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT / "src"))  # the module under test
import pdf_shrink as S  # noqa: E402  the module under test
import pdftools  # noqa: E402  the pages as text and as pictures

try:
    import pikepdf  # writes the deck, and does the shrinking
    from PIL import Image, ImageChops  # the pixels compared
except ImportError:  # a Python without them: those tests are skipped
    pikepdf = None
READER = bool(pdftools.reader())  # poppler or PDFium, for the text and the pictures
WORDS = ["Payment authorization service redesign", "Settlement reads one event stream", "Gildong Hong Portfolio"]  # the fictional person's slides


def logo_pixels(size: int = 240) -> tuple:
    """A logo of six colours in bands (RGB bytes) and its round transparency mask (grey bytes)."""
    colours = [(27, 46, 75), (242, 199, 68), (255, 255, 255), (42, 74, 120), (29, 28, 29), (233, 238, 246)]  # the brand's own
    rgb = bytes(v for y in range(size) for x in range(size) for v in colours[(x // 40 + y // 40) % len(colours)])
    alpha = bytes(255 if (x - size / 2) ** 2 + (y - size / 2) ** 2 < (size / 2) ** 2 else 0 for y in range(size) for x in range(size))
    return rgb, alpha


def gradient_pixels(w: int = 160, h: int = 80) -> bytes:
    """A figure's shading: red across, green down, so it holds far more than 256 colours."""
    return bytes(v for y in range(h) for x in range(w) for v in (x * 255 // (w - 1), y * 255 // (h - 1), 140))


def glyphs(line: str, size: int = 30) -> list:
    """A line of words as Chrome writes it: each glyph shown, then a move of its advance (seven decimals) to the next. The
    font's widths are all 600, so the advance is the glyph's own and a space is a gap of one glyph."""
    out = []  # the instructions
    for i, ch in enumerate(line):  # glyph by glyph
        if ch != " ":  # a space is drawn as the gap alone
            out.append(f"({ch}) Tj")
        out.append(f"{0.6 * size + (i % 7) * 1e-7:.7f} 0 Td")  # the advance, written the way a browser rounds it
    return out


def fat_deck(path: pathlib.Path, words: list = WORDS, title: str = "Gildong Hong Portfolio") -> pathlib.Path:
    """The deck, one page per line of words, written with pikepdf in the classic form a browser writes (src/pdfmeta.py
    reads its title)."""
    import random  # shapes in places of no pattern, as a page's figures are
    rng = random.Random(7)  # the same deck every time
    pdf = pikepdf.new()
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica,
                                                FirstChar=32, LastChar=126, Widths=[600] * 95))  # one width for every glyph
    rgb, alpha = logo_pixels()
    mask = pdf.make_stream(zlib.compress(alpha), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=240, Height=240,
                           ColorSpace=pikepdf.Name.DeviceGray, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode)  # the logo's round edge
    logo = pdf.make_stream(zlib.compress(rgb), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=240, Height=240,
                           ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode, SMask=mask)
    grad = pdf.make_stream(zlib.compress(gradient_pixels()), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=160, Height=80,
                           ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode)
    for n, line in enumerate(words):
        ops = ["0.75 0 0 -0.75 0 540 cm"]  # px to pt, y down: Chrome's own matrix for a 1280 x 720 slide
        for _ in range(500):  # a figure's curves, every coordinate with seven decimals, as Chrome writes them
            x, y = rng.uniform(40, 1000), rng.uniform(260, 700)  # where it starts
            ops.append(" ".join(f"{v:.7f}" for v in (x, y)) + " m " + " ".join(f"{x + rng.uniform(5, 60):.7f} {y + rng.uniform(-20, 20):.7f}" for _ in range(3)) + " c S")
        ops.append("BT /F1 30 Tf 1 0 0 -1 48.0000004 90.0000002 Tm")  # a line of words, glyph by glyph
        ops += glyphs(line)
        ops += ["ET", "q 180 0 0 -180 1040 230 cm /Logo Do Q", "q 240 0 0 -120 1000 700 cm /Grad Do Q"]  # the logo and the figure, upright
        page = pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, 960, 540], Contents=pdf.make_stream("\n".join(ops).encode()),
                                  Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font), XObject=pikepdf.Dictionary(Logo=logo, Grad=grad)))
        if n == 0:  # a link on the cover, as the contacts have
            link = pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[36, 400, 300, 430],
                                      A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String("https://example.com/gildong")))  # a web address
            page.Annots = pdf.make_indirect(pikepdf.Array([link]))
        pdf.pages.append(pikepdf.Page(page))
    pdf.docinfo["/Title"], pdf.docinfo["/Author"] = title, "Gildong Hong"  # what a reader's title bar shows
    pdf.save(path, compress_streams=True)  # the classic form, as a browser writes it
    return path


def bare(text: str) -> str:
    """Text with no spaces or line ends: the words and their order, however an extractor spaced them."""
    return re.sub(r"\s+", "", text)


class Rounding(unittest.TestCase):
    """The numbers a page is drawn with: as many decimals as its scale needs, and no drift along a line. No pikepdf."""

    def test_the_decimals_follow_the_scale(self):
        self.assertEqual(1, S.digits_for(0.75, S.PATH_PT))  # Chrome's px: a tenth of a px is 0.075 pt, half of it under 0.04
        self.assertEqual(2, S.digits_for(0.75, S.TEXT_PT))  # a text position keeps two
        self.assertEqual(3, S.digits_for(100 * 0.75, S.PATH_PT))  # a shape drawn a hundred times larger keeps two more
        self.assertIsNone(S.digits_for(0, S.PATH_PT))  # a matrix that draws nothing: left as written
        self.assertAlmostEqual(3.0, S.stretch((0, 3, -1, 0, 5, 5)))  # turned and stretched: its longest stretch

    def test_paths_and_text_rounded_under_their_matrix_and_an_inline_image_kept(self):
        inline = object()  # stands for an instruction this never rounds
        ops = [([Decimal("0.75"), 0, 0, Decimal("-0.75"), 0, 540], "cm"), ([Decimal("39.999996"), Decimal("15882.2998")], "m"),  # Chrome's matrix, a move
               ([], "q"), ([100, 0, 0, 100, 0, 0], "cm"), ([Decimal("1.23456789"), Decimal("2.5")], "l"), ([], "Q"),  # a shape drawn a hundred times larger
               ([], "BT"), ([1, 0, 0, -1, Decimal("48.004"), Decimal("43.9999")], "Tm"), ([Decimal("9.2535095"), 0], "Td"), ([], "ET"),  # a word
               ([inline], "INLINE IMAGE")]  # an inline image, as pikepdf gives one
        got = S.round_content(ops)
        self.assertEqual([Decimal("40"), Decimal("15882.3")], [Decimal(str(v)) for v in got[1][0]])  # one decimal at 0.75
        self.assertEqual(["1.235", "2.5"], [str(v) for v in got[4][0]])  # three under a matrix a hundred times larger
        self.assertEqual([1, 0, 0, -1], got[7][0][:4])  # a text matrix keeps its scale and turn
        self.assertEqual(["48", "44"], [str(v) for v in got[7][0][4:]])  # and its place takes two decimals
        self.assertIs(ops[-1], got[-1])  # an instruction it does not round goes back as it came
        self.assertEqual(ops[1][0], [Decimal("39.999996"), Decimal("15882.2998")])  # the instructions given are not changed
        kept = S.round_content(ops[:10], text_too=False)  # the first step: the text left as it is
        self.assertIs(ops[7], kept[7])
        self.assertIs(ops[8], kept[8])

    def test_a_line_of_glyphs_never_drifts(self):
        moves = [([Decimal("9.2535095"), 0], "Td")] * 400  # the same advance four hundred times: each rounding alone would add up
        got = S.round_content([([Decimal("0.75"), 0, 0, Decimal("-0.75"), 0, 540], "cm"), ([], "BT")] + moves)  # under Chrome's matrix: two decimals
        exact, written = Decimal(0), Decimal(0)  # where the glyphs should be, and where they are
        for (before, _), (after, _) in zip(moves, got[2:]):
            exact += before[0]
            written += Decimal(str(after[0]))
            self.assertLessEqual(abs(exact - written), Decimal("0.005"))  # never more than half the last decimal
        self.assertNotEqual(Decimal(str(got[2][0][0])), Decimal(str(got[3][0][0])))  # the moves alternate to stay on course

    def test_without_pikepdf_it_says_so(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="shrink-none-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        src = tmp / "in.pdf"
        src.write_bytes(b"%PDF-1.4\n% not a real one\n")
        with mock.patch.object(S, "_pikepdf", side_effect=S.Unavailable("pikepdf")):  # the desktop app's Python
            with self.assertRaises(S.Unavailable):
                S.shrink(src, tmp / "out.pdf")
            self.assertEqual(3, S.main([str(src), str(tmp / "out.pdf")]))  # the command line's own code for it
        self.assertEqual(2, S.main([str(src)]))  # one file: the usage line
        self.assertEqual(2, S.main([str(src), str(tmp / "out.pdf"), "--max-mb", "0"]))  # no size to fit
        self.assertEqual({"before": src.stat().st_size, "after": src.stat().st_size, "text": False, "colors": None, "fits": True, "changed": False},
                         S.shrink(src, tmp / "same.pdf", 10 * S.MB))  # under the size already: no pikepdf needed
        self.assertEqual(src.read_bytes(), (tmp / "same.pdf").read_bytes())  # copied as it is


@unittest.skipUnless(pikepdf and READER, "pikepdf, Pillow or a PDF reader is not here")
class Shrinking(unittest.TestCase):
    """The deck made smaller: its pages, words, links and title kept, its pixels within a hair of the original."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="shrink-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = fat_deck(self.tmp / "deck.pdf")

    def pixels_moved(self, a: pathlib.Path, b: pathlib.Path) -> float:
        """The largest share, over the pages, of pixels where a colour channel moved by more than 32 of 255."""
        pa = pdftools.render_png(a, self.tmp / f"{a.stem}-png", dpi=110)  # each page at the panel's preview size
        pb = pdftools.render_png(b, self.tmp / f"{b.stem}-png", dpi=110)
        self.assertEqual(len(pa), len(pb))  # as many pages
        worst = 0.0
        for x, y in zip(pa, pb):
            with Image.open(x) as ia, Image.open(y) as ib:
                diff = ImageChops.difference(ia.convert("RGB"), ib.convert("RGB")).split()  # each channel's change
                most = ImageChops.lighter(ImageChops.lighter(diff[0], diff[1]), diff[2])  # the largest of the three
                moved = most.point(lambda v: 255 if v > 32 else 0).histogram()[255]  # pixels that moved further than 32
                worst = max(worst, moved / (ia.width * ia.height))
        return worst

    def image_kinds(self, pdf_path: pathlib.Path) -> list:
        """Each image's colour space kind and filter, by its width: what the palette step made of it."""
        with pikepdf.open(pdf_path) as pdf:
            return sorted((int(x.Width), str(x.ColorSpace[0]) if isinstance(x.get("/ColorSpace"), pikepdf.Array) else str(x.get("/ColorSpace")),
                           str(x.get("/Filter"))) for x in pdf.objects if isinstance(x, pikepdf.Stream) and x.get("/Subtype") == "/Image")

    def test_the_safe_steps_keep_every_page_word_link_and_the_title(self):
        out = self.tmp / "small.pdf"
        got = S.shrink(self.src, out)  # no size asked: the steps with no visible change
        self.assertLess(got["after"], got["before"] * 0.8)  # a fifth smaller at least
        self.assertEqual((True, None, None, True), (got["text"], got["colors"], got["fits"], got["changed"]))
        self.assertEqual(out.stat().st_size, got["after"])
        self.assertEqual(pdftools.info(self.src)["pages"], pdftools.info(out)["pages"])  # every page
        self.assertEqual(bare(pdftools.text(self.src)), bare(pdftools.text(out)))  # every word, in its order
        self.assertLess(self.pixels_moved(self.src, out), 0.005)  # under half a percent of a page's pixels, at glyph edges
        with pikepdf.open(out) as pdf:  # the title, the author and the link, as a reader reads them
            self.assertEqual(("Gildong Hong Portfolio", "Gildong Hong"), (str(pdf.docinfo["/Title"]), str(pdf.docinfo["/Author"])))
            self.assertEqual("https://example.com/gildong", str(pdf.pages[0].Annots[0].A.URI))
        self.assertEqual([(160, "/DeviceRGB", "/FlateDecode"), (240, "/DeviceGray", "/FlateDecode"), (240, "/Indexed", "/FlateDecode")],
                         self.image_kinds(out))  # the gradient and the logo's mask as they were, the logo as a palette of its six colours
        with pikepdf.open(self.src) as a, pikepdf.open(out) as b:  # the logo's pixels exactly as they were
            logo = lambda pdf: next(x for x in pdf.objects if isinstance(x, pikepdf.Stream) and x.get("/SMask") is not None)  # noqa: E731
            self.assertEqual(pikepdf.PdfImage(logo(a)).as_pil_image().convert("RGB").tobytes(), pikepdf.PdfImage(logo(b)).as_pil_image().convert("RGB").tobytes())

    def test_the_first_step_leaves_the_text_layer_as_it_is(self):
        out, first = self.tmp / "first.pdf", self.tmp / "probe.pdf"
        S.shrink(self.src, out)  # both safe steps, for the sizes
        size = S.attempt(pikepdf, self.src.read_bytes(), {}, False, None)  # the first step alone
        got = S.shrink(self.src, first, len(size))  # a size the first step meets
        self.assertEqual((False, None, True), (got["text"], got["colors"], got["fits"]))
        self.assertEqual(pdftools.text(self.src), pdftools.text(first))  # the text layer read the same, space for space

    def test_colours_only_while_over_the_size_and_never_below_128_or_jpeg(self):
        safe = S.shrink(self.src, self.tmp / "safe.pdf")["after"]  # the size with no visible change
        fewer = S.attempt(pikepdf, self.src.read_bytes(), {}, True, 256)  # at 256 colours
        self.assertLess(len(fewer), safe)  # the gradient packs smaller as a palette
        got = S.shrink(self.src, self.tmp / "fit.pdf", len(fewer))  # a size only fewer colours meet
        self.assertEqual((256, True), (got["colors"], got["fits"]))  # the first palette that fits, no fewer
        self.assertIn((160, "/Indexed", "/FlateDecode"), self.image_kinds(self.tmp / "fit.pdf"))  # the gradient as a palette now
        self.assertLess(self.pixels_moved(self.src, self.tmp / "fit.pdf"), 0.02)  # the gradient's bands differ by little
        tiny = S.shrink(self.src, self.tmp / "tiny.pdf", 1000)  # a size no deck meets
        self.assertEqual((True, False), (tiny["colors"] in S.PALETTES, tiny["fits"]))  # every palette tried, none under 128, said not to fit
        self.assertEqual((self.tmp / "tiny.pdf").stat().st_size, tiny["after"])  # and the smallest file written
        for f in ("fit.pdf", "tiny.pdf"):  # never a JPEG
            self.assertNotIn("/DCTDecode", {k[2] for k in self.image_kinds(self.tmp / f)})

    def test_a_deck_under_the_size_is_copied_as_it_is(self):
        got = S.shrink(self.src, self.tmp / "copy.pdf", self.src.stat().st_size)
        self.assertEqual((False, True), (got["changed"], got["fits"]))
        self.assertEqual(self.src.read_bytes(), (self.tmp / "copy.pdf").read_bytes())

    def test_the_command_line(self):
        out, rep = self.tmp / "cli.pdf", self.tmp / "cli.json"
        self.assertEqual(0, S.main([str(self.src), str(out), "--max-mb", "5", "--json", str(rep)]))  # under 5 MB already
        self.assertEqual(self.src.read_bytes(), out.read_bytes())
        self.assertEqual(0, S.main([str(self.src), str(out), "--json", str(rep)]))  # made smaller
        self.assertEqual(out.stat().st_size, json.loads(rep.read_text(encoding="utf-8"))["after"])
        self.assertEqual(1, S.main([str(self.src), str(out), "--max-mb", "0.001"]))  # a size it cannot meet: said with the exit code
        self.assertEqual(1, S.main([str(self.tmp / "none.pdf"), str(out)]))  # a file that is not there
        (self.tmp / "text.pdf").write_text("not a PDF", encoding="utf-8")
        self.assertEqual(1, S.main([str(self.tmp / "text.pdf"), str(out)]))  # nor one that is not a PDF


if __name__ == "__main__":
    unittest.main()
