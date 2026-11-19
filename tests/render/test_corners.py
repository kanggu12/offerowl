# -*- coding: utf-8 -*-
"""The corners setting (OFFEROWL_CORNERS=square, the person's setting `corners`): the timeline's bars, the hierarchy figure's
boxes, the logo tiles, a blind edition's bars and the built-in deck's boxes with square corners; with the switch unset or
"round", every corner as it was. A finished rounded tile brought in as a logo is squared around its logo, which stays pixel for
pixel, and a picture that is no plate keeps its shape. The panel's setting takes "round", "square" or null, and each build, the
live figures and the live deck get OFFEROWL_CORNERS=square only when it says so. Fictional people and pictures only; the deck's
page is written by Node.js, with no browser.

Run: python3 -m unittest tests/render/test_corners.py -v
"""
import importlib.util  # is Pillow here
import io  # a live tile's bytes as a picture
import json  # the deck's job file
import os  # the switch
import pathlib  # paths
import re  # the deck page's boxes and the stylesheets' rules
import shutil  # is node here, temporary folders
import subprocess  # the figures' script and the deck's writer
import sys  # the import path
import tempfile  # pictures
import unittest  # the runner
from unittest import mock  # the switch for one drawing, the typesetting stood in for

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src", ROOT / "tests" / "app", ROOT / "tests" / "render"):  # apps/, the engine, the helpers of the panel's tests
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import blind as B  # noqa: E402  src/blind.py: a blind edition's bars
import resume  # noqa: E402  src/resume.py: the typesetting steps a build calls
from test_blind import Builds  # noqa: E402  the fictional person, and builds with the typesetting stood in for

HAVE_PIL = importlib.util.find_spec("PIL") is not None  # the figures are drawn with Pillow
HAVE_NODE = bool(shutil.which("node")) and (ROOT / "node_modules" / "opentype.js").is_dir()  # the deck's writer and its font metrics
RED = (0x8B, 0x1A, 0x1A)  # the shipped mask_fill: a blind edition's bars
SQUARE_CSS = (ROOT / "src" / "portfolio" / "style_square.css").read_text(encoding="utf-8")  # what the deck adds under square corners


def switch(value):
    """This process's environment with OFFEROWL_CORNERS set to value, or without it (None), for the time of a with block."""
    env = {k: v for k, v in os.environ.items() if k != "OFFEROWL_CORNERS"}  # the rest as it is
    if value is not None:  # the switch as a build would get it
        env["OFFEROWL_CORNERS"] = value
    return mock.patch.dict(os.environ, env, clear=True)


def rounded_boxes(html: str) -> list:
    """The SVG boxes of a page whose corners are rounded, but the dots (a square box rounded by half its side or more)."""
    out = []  # what is rounded
    for b in re.findall(r"<rect\b[^>]*>", html):  # every box of the figures and the simple templates
        w, h, rx = (float((re.search(rf' {k}="([^"]*)"', b) or [0, 0])[1]) for k in ("width", "height", "rx"))  # its size and its corner
        if rx and not (w == h and rx >= w / 2):  # rounded, and no dot
            out.append(b)
    return out


def box_corners(im, colour, area=None):
    """The four corner pixels of the box that one colour fills in a picture, or in an area of it."""
    from PIL import Image, ImageChops  # the mask of that colour
    part = im.convert("RGB").crop(area) if area else im.convert("RGB")  # where to look
    r, g, b = ImageChops.difference(part, Image.new("RGB", part.size, colour)).split()  # how far each channel is from it
    mask = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v == 0 else 0)  # exactly that colour
    x0, y0, x1, y1 = mask.getbbox()  # the box it fills
    return [part.getpixel(c) for c in ((x0, y0), (x1 - 1, y0), (x0, y1 - 1), (x1 - 1, y1 - 1))]  # its outermost pixels


@unittest.skipUnless(HAVE_PIL, "Pillow is not installed: the figures cannot be drawn here")
class FigureTests(unittest.TestCase):
    """The timeline's bars, the hierarchy figure's boxes and the logo tiles: square corners when asked, else as they were."""

    MODES = ((None, False), ("round", False), ("square", True))  # the switch, and whether it asks for square corners
    PROFILE = {"roles": [{"org": "Alphapay", "key": "a", "start": "2019.03", "end": "2022.02", "chart": "Backend engineer"}],  # one role: its bar is the navy itself
               "summary": {"layers": [["Payments", "Kafka, Redis", "checkout"], ["Platform", "Kubernetes", "internal tools"]]}}  # two layers

    def setUp(self):
        import overview_figures as OF  # imported here: it needs Pillow
        self.OF = OF
        self.dir = pathlib.Path(tempfile.mkdtemp())  # the pictures
        self.addCleanup(shutil.rmtree, self.dir, True)

    def open(self, f):
        from PIL import Image  # read back
        return Image.open(f).convert("RGBA")

    def test_a_timeline_bar_is_square_only_when_asked(self):
        for value, square in self.MODES:
            with switch(value):
                im = self.open(self.OF.timeline(self.PROFILE, "en", self.dir / f"t_{value}.png", self.OF.NAVY))
            ends = box_corners(im, self.OF.NAVY, (54 * self.OF.S, 0, im.width, im.height))  # the newest role's bar is the navy itself, right of the row names
            self.assertEqual(square, all(c == self.OF.NAVY for c in ends), (value, ends))  # its corners filled, or cut round to the white

    def test_the_hierarchy_figure_s_boxes_are_square_only_when_asked(self):
        for value, square in self.MODES:
            with switch(value):
                im = self.open(self.OF.stack(self.PROFILE, "en", self.dir / f"s_{value}.png", self.OF.NAVY))
            ends = box_corners(im, self.OF.TINT)  # the pale boxes of the skills: the first one's top, the last one's bottom
            self.assertEqual(square, all(c == self.OF.TINT for c in ends), (value, ends))

    def test_the_tiles_are_square_only_when_asked(self):
        from PIL import Image, ImageDraw  # an opaque logo on a near-white ground
        logo = self.dir / "logo.png"
        im = Image.new("RGB", (120, 60), "white")
        ImageDraw.Draw(im).rectangle([20, 20, 100, 40], fill=(170, 40, 40))
        im.save(logo)
        T = self.OF.TILE - 1  # the last pixel of a tile
        for value, square in self.MODES:
            with switch(value):
                mono = self.open(self.OF.logo_tile({"monogram": "AP", "color": "#2F6EBA"}, self.dir / f"m_{value}.png", self.OF.NAVY))
                tile = self.open(self.OF.logo_tile({"file": str(logo)}, self.dir / f"i_{value}.png", self.OF.NAVY))
            for c in ((0, 0), (T, 0), (0, T), (T, T)):  # each corner of the picture
                if square:  # filled: the monogram's colour, the image tile's outline
                    self.assertEqual(((47, 110, 186, 255), self.OF.TILE_BORDER + (255,)), (mono.getpixel(c), tile.getpixel(c)), (value, c))
                else:  # cut round: the clear ground
                    self.assertEqual((0, 0), (mono.getpixel(c)[3], tile.getpixel(c)[3]), (value, c))
            self.assertEqual(self.OF.TILE_BORDER + (255,), tile.getpixel((self.OF.TILE // 2, 3)))  # the outline along the edge either way
            self.assertEqual((170, 40, 40, 255), tile.getpixel((self.OF.TILE // 2, self.OF.TILE // 2)))  # and the logo in the middle

    def finished(self, size=512, logo=None):
        """A finished rounded tile, as a design tool exports one: a white plate with a light outline on a clear ground, a round
        logo inside it (or the shape given)."""
        from PIL import Image, ImageDraw  # drawn here
        k = size / 512  # its scale against Offerowl's own tiles
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))  # the clear ground
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([1, 1, size - 2, size - 2], radius=round(88 * k), fill=(255, 255, 255, 255), outline=self.OF.TILE_BORDER, width=round(6 * k))
        if logo:  # a shape of the test's own
            logo(d, k)
        else:  # an orange disc in the middle
            d.ellipse([round(150 * k)] * 2 + [round(362 * k)] * 2, fill=(169, 86, 27, 255))
        f = self.dir / f"finished_{size}_{len(list(self.dir.iterdir()))}.png"  # a name of its own
        im.save(f)
        return f

    def both(self, src):
        """The tile drawn from a picture with rounded corners and with square ones."""
        with switch(None):  # as before
            rounded = self.open(self.OF.logo_tile({"file": str(src)}, self.dir / "r.png", self.OF.NAVY))
        with switch("square"):  # square corners
            square = self.open(self.OF.logo_tile({"file": str(src)}, self.dir / "s.png", self.OF.NAVY))
        return rounded, square

    def test_a_finished_rounded_tile_is_squared_around_its_logo(self):
        T, inside = self.OF.TILE - 1, (self.OF.INSET, self.OF.INSET, self.OF.TILE - self.OF.INSET, self.OF.TILE - self.OF.INSET)  # the last pixel; the plate's inside
        for size in (512, 1024):  # Offerowl's own size, and a larger one scaled down to it
            rounded, square = self.both(self.finished(size))
            self.assertEqual(0, rounded.getpixel((0, 0))[3], size)  # kept as it came: its corner is the clear ground
            for c in ((0, 0), (T, 0), (0, T), (T, T)):  # square: the outline runs into each corner, in its colour as scaled (a level off at most)
                px = square.getpixel(c)
                self.assertTrue(px[3] == 255 and max(abs(a - b) for a, b in zip(px, self.OF.TILE_BORDER)) <= 2, (size, c, px))
            self.assertEqual((255, 255, 255, 255), square.getpixel((14, 14)), size)  # past the outline, the plate fills the corner
            self.assertEqual(rounded.crop(inside).tobytes(), square.crop(inside).tobytes(), size)  # the logo and the plate around it, pixel for pixel
            self.assertEqual((169, 86, 27, 255), square.getpixel((self.OF.TILE // 2, self.OF.TILE // 2)), size)  # the centre as it was

    def test_a_picture_that_is_no_plate_keeps_its_shape(self):
        from PIL import Image, ImageDraw  # an emblem
        emblem = self.dir / "emblem.png"  # a round mark on a clear square ground: square, its corners clear, but no plate
        im = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse([0, 0, 239, 239], fill=(47, 110, 186, 255))
        im.save(emblem)
        wide = self.finished(logo=lambda d, k: d.rectangle([12, 236, 500, 276], fill=(30, 30, 30, 255)))  # a tile whose logo reaches its edge
        for src in (emblem, wide):  # neither is squared: the mark keeps its shape, and the logo keeps every pixel
            with mock.patch.object(self.OF, "WARN", []):  # the note a command line run prints
                rounded, square = self.both(src)
                self.assertTrue(any("kept as it is" in w for w in self.OF.WARN), self.OF.WARN)
            self.assertEqual(rounded.tobytes(), square.tobytes(), src.name)


@unittest.skipUnless(HAVE_PIL, "Pillow is not installed: the bars cannot be drawn here")
class BlindBarTests(unittest.TestCase):
    """A blind edition's bars in a figure: square under square corners, slightly rounded otherwise."""

    def test_a_bar_is_square_only_when_asked(self):
        from PIL import Image, ImageDraw, ImageFont  # a line of text with a covered name
        font = ImageFont.truetype(str(ROOT / "fonts" / "Pretendard-Bold.ttf"), 48)  # large, so the rounding is a few pixels
        table = B.merged({"mask": ["Alphapay"]})  # a fictional company covered
        for value, square in ((None, False), ("round", False), ("square", True)):
            im = Image.new("RGB", (640, 120), "white")
            with switch(value):
                B.draw(ImageDraw.Draw(im), (20, 20), "Alphapay checkout", font, (60, 60, 60), table)
            ends = box_corners(im, RED)  # the bar's corners
            self.assertEqual(square, all(c == RED for c in ends), (value, ends))


@unittest.skipUnless(HAVE_PIL and shutil.which("node"), "Pillow or Node.js is not here: the figures' script cannot run")
class ScriptTests(unittest.TestCase):
    """src/overview_figures.py run as the build runs it reads the switch from its environment."""

    OUT = "owl_cornerstest"  # an output name no edition uses

    def tearDown(self):
        for f in (ROOT / "output" / "_figures").glob(self.OUT + "_*"):  # its pictures go again
            f.unlink()

    def test_the_script_reads_the_switch(self):
        from PIL import Image  # the tile it drew
        for value, square in ((None, False), ("square", True)):
            with switch(value):
                r = subprocess.run([sys.executable, "src/overview_figures.py", "examples/sample_full_en.json", self.OUT, "en"], cwd=ROOT,
                                   capture_output=True, text=True, timeout=300)  # the fictional example, its monogram tiles
            self.assertEqual(0, r.returncode, r.stderr)
            tile = Image.open(ROOT / "output" / "_figures" / f"{self.OUT}_logo_role_alpha.png").convert("RGBA")  # the first company's tile
            self.assertEqual(255 if square else 0, tile.getpixel((0, 0))[3], value)  # its corner: the square's fill, or the clear ground


def node(code: str, value=None) -> str:
    """What a line of Node.js prints, run in the repository with the switch set to value (None: unset)."""
    with switch(value):
        r = subprocess.run(["node", "-e", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if r.returncode:  # a failure says why
        raise AssertionError(r.stderr)
    return r.stdout


@unittest.skipUnless(HAVE_NODE, "Node.js or the typesetting libraries are not here: the deck cannot be written")
class DeckTests(unittest.TestCase):
    """The built-in deck: every box square under square corners but a dot, its stylesheet's boxes too; the same page as before
    without the switch."""

    OUT = "owl_cornerstest_deck"  # an output name no edition uses

    def tearDown(self):
        for f in (ROOT / "output").glob(self.OUT + "*"):  # the page and its notes go again
            f.unlink()

    def page(self, value) -> str:
        """The deck's page of the fictional English example, written with the switch set to value."""
        with tempfile.TemporaryDirectory() as d:
            job = pathlib.Path(d) / "job.json"  # the edition's settings: its own output name
            job.write_text(json.dumps({"out": self.OUT, "lang": "en", "deck": "chapters"}), encoding="utf-8")
            with switch(value):
                r = subprocess.run(["node", "src/deck_slides.js", "examples/sample_full_en.json", str(job)], cwd=ROOT,
                                   capture_output=True, text=True, timeout=300)
            self.assertEqual(0, r.returncode, r.stderr)
        return (ROOT / "output" / f"{self.OUT}_deck.html").read_text(encoding="utf-8")

    def test_a_box_of_the_figures_takes_the_setting(self):
        code = ('const { P } = require("./src/portfolio/draw");'  # the box every figure draws with
                'console.log(JSON.stringify([[40, 20, 4], [6, 6, 3], [20, 20, 4], [18, 18, 9]].map(([w, h, r]) => P.rect(0, 0, w, h, { r }).match(/rx="([^"]*)"/)[1])))')
        self.assertEqual(["4", "3", "4", "9"], json.loads(node(code)))  # as asked
        self.assertEqual(["4", "3", "4", "9"], json.loads(node(code, "round")))
        self.assertEqual(["0", "3", "0", "9"], json.loads(node(code, "square")))  # square, but the dots: a 6 px box rounded by 3, an 18 px one by 9

    def test_the_page_changes_its_corners_and_nothing_else(self):
        plain, rounded, square = self.page(None), self.page("round"), self.page("square")
        self.assertEqual(plain, rounded)  # "round" is the default, byte for byte
        self.assertNotIn(SQUARE_CSS, plain)  # no square stylesheet by default
        self.assertIn(SQUARE_CSS, square)  # the last one under square corners
        self.assertGreater(len(re.findall(r"<rect\b[^>]*>", square)), 40)  # the figures' and the simple templates' boxes
        self.assertEqual([], rounded_boxes(square))  # every one square, but a dot
        self.assertTrue(rounded_boxes(plain))  # by default the page has rounded boxes
        self.assertIn("border-radius:0px", square)  # the boxes written into the slides
        strip = lambda s: re.sub(r"border-radius:\s*[^;\"]*", "border-radius:", re.sub(r' rx="[^"]*"', "", s.replace(SQUARE_CSS, "")))  # noqa: E731  the page without its corners
        self.assertEqual(strip(plain), strip(square))  # nothing but the corners changes

    def test_every_rounded_box_of_the_deck_s_styles_is_squared(self):
        """Each rule of the deck's stylesheets that rounds a box has its square one in style_square.css; a dot is left round.
        A new rounded box left out of style_square.css fails here."""
        def rules(text):  # (selectors, declarations) of a stylesheet, comments and template slots taken out
            text = re.sub(r"\$\{[^}]*\}", "X", re.sub(r"/\*.*?\*/", "", text, flags=re.S))
            return [([" ".join(s.split()) for s in sel.split(",")], body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text)]

        def radius(body):  # the corner radii a rule sets, or none
            m = re.search(r"border-radius:\s*([^;]+)", body)
            return [float(v) for v in re.findall(r"[\d.]+", m.group(1))] if m else []

        squared = {s for sels, body in rules(SQUARE_CSS) if radius(body) == [0.0] for s in sels}  # what the square stylesheet squares
        deck_js = (ROOT / "src" / "portfolio" / "deck.js").read_text(encoding="utf-8")
        sheets = [(ROOT / "src" / "portfolio" / f).read_text(encoding="utf-8") for f in ("theme.css", "style_clean.css", "theme_en.css")]
        sheets.append(re.search(r"const BLIND_CSS = lang => `([\s\S]*?)`;", deck_js).group(1))  # the blind edition's own styles
        checked = 0  # the rounded rules found
        for text in sheets:
            for sels, body in rules(text):
                r = radius(body)
                if not any(r):  # no rounding
                    continue
                size = [float(m.group(1)) for k in ("width", "height") for m in [re.search(rf"(?<![-\w]){k}:\s*([\d.]+)px", body)] if m]
                if len(size) == 2 and size[0] == size[1] and min(r) >= size[0] / 2:  # a dot stays round
                    continue
                checked += 1
                for s in sels:
                    self.assertIn(s, squared, f"{s} rounds a box that square corners leave round")
        self.assertGreater(checked, 8)  # the deck's rounded boxes were found


class SettingTests(Builds):
    """The person's setting `corners`: what it takes, and what each build, the live figures and the live deck get from it."""

    def test_it_takes_round_square_or_nothing(self):
        a = self.person()
        self.assertNotIn("corners", a.settings())  # absent by default: the corners as they always were
        self.assertEqual("round", a.tasks.corners())
        a.set_settings({"corners": "square"})
        self.assertEqual(("square", "square"), (a.settings()["corners"], a.tasks.corners()))
        for bad in ("Square", "rounded", "", 1, True, ["square"], {"corners": "square"}):  # another word, a case, a number, a list
            a.set_settings({"corners": bad})
            self.assertEqual("square", a.settings()["corners"], bad)  # refused: the setting stays as it was
        a.set_settings({"corners": "round"})
        self.assertEqual(("round", "round"), (a.settings()["corners"], a.tasks.corners()))
        a.set_settings({"corners": None})  # cleared
        self.assertNotIn("corners", a.settings())
        a.set_settings({"form": "compact"})  # a request that names no corners leaves them alone
        self.assertNotIn("corners", a.settings())

    def envs(self) -> list:
        """The environment each typesetting step of the stood-in build was given (the resume, the deck, a blind edition's twin)."""
        calls = resume.build.call_args_list + resume.build_deck.call_args_list  # the stand-ins record their calls
        return [c.args[2] if len(c.args) > 2 else c.kwargs.get("env") for c in calls]

    def test_a_build_gets_the_switch_only_when_the_setting_says_square(self):
        a = self.person()
        self.stand_in(a)
        with mock.patch.dict(os.environ, {"OFFEROWL_CORNERS": "square"}):  # the server's own environment never counts
            a.tasks._build("-general", "ko", "navy", 3, False, False, False)
        self.assertTrue(self.envs())
        self.assertFalse([e for e in self.envs() if "OFFEROWL_CORNERS" in e])  # no step got it
        resume.build.reset_mock()
        resume.build_deck.reset_mock()
        a.set_settings({"corners": "square"})
        a.tasks._build("-general", "ko", "navy", 3, False, False, True)  # a blind edition, with its ordinary twin
        self.assertGreaterEqual(len(self.envs()), 4)  # the resume, the deck and the twin's two
        self.assertEqual({"square"}, {e.get("OFFEROWL_CORNERS") for e in self.envs()})  # every step drew square
        self.assertNotIn("OFFEROWL_CORNERS", os.environ)  # the server's own environment is never changed
        resume.build.reset_mock()
        resume.build_deck.reset_mock()
        a.set_settings({"corners": "round"})
        a.tasks._build("-general", "ko", "navy", 3, False, False, False)
        self.assertFalse([e for e in self.envs() if "OFFEROWL_CORNERS" in e])  # round: none, as before the setting existed

    @unittest.skipUnless(HAVE_PIL and HAVE_NODE, "Pillow, Node.js or the typesetting libraries are not here: nothing can be drawn")
    def test_the_live_figures_and_deck_follow_the_setting(self):
        from PIL import Image  # the tiles the canvas shows
        a = self.person()
        prof = a.ws.path("profile", "profile.json")  # the first company gets a monogram tile, as a profile file may give it
        data = json.loads(prof.read_text(encoding="utf-8"))
        data["roles"][0]["logo"] = {"text": "AP", "color": "#2F6EBA"}
        prof.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(a.tasks, "engine_ready", return_value=""):  # the libraries are there
            figs, deck = a.tasks.resume_figures("-general", "ko"), a.tasks.deck_live("-general", "ko")  # as the canvas asks
            a.set_settings({"corners": "square"})
            figs2, deck2 = a.tasks.resume_figures("-general", "ko"), a.tasks.deck_live("-general", "ko")  # drawn again, not the kept ones
        self.assertNotEqual(figs["stamp"], figs2["stamp"])  # new pictures, under a new address
        tile = next(k for k in sorted(figs["files"]) if k.startswith("logo_"))  # a company's tile
        self.assertEqual(0, Image.open(io.BytesIO(figs["files"][tile])).convert("RGBA").getpixel((0, 0))[3])  # rounded: a clear corner
        self.assertEqual(255, Image.open(io.BytesIO(figs2["files"][tile])).convert("RGBA").getpixel((0, 0))[3])  # square: a filled one
        self.assertNotIn(SQUARE_CSS, deck.get("html", ""), deck)  # the live deck as before
        self.assertTrue(rounded_boxes(deck["html"]))  # with its rounded boxes
        self.assertIn(SQUARE_CSS, deck2.get("html", ""), deck2)  # then square
        self.assertEqual([], rounded_boxes(deck2["html"]))  # every box of its figures, but a dot


if __name__ == "__main__":
    unittest.main()
