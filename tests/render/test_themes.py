# -*- coding: utf-8 -*-
"""The colour sets and the figures: crimson (a black base and a crimson accent) loads in the JavaScript and the Python loaders
with the tones it names for the figures, and the panel and the agents offer it; a built-in deck in it carries none of the navy
set's colours, in its slides or in its stylesheet; the resume's figures in it hold no navy pixel in their bars, boxes and tiles'
outline; the built-in navy keeps every colour it had. Fictional people only; the deck's page is written by Node.js, with no
browser.

Run: python3 -m unittest tests/render/test_themes.py -v
"""
import importlib.util  # is Pillow here
import json  # the loaders' answers, the job file
import os  # the theme the figures are drawn in
import pathlib  # paths
import shutil  # is node here, temporary folders
import subprocess  # the loaders, the figures' script and the deck's writer
import sys  # the import path
import tempfile  # pictures and job files
import unittest  # the runner
from unittest import mock  # the theme of one drawing

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src"):  # apps/ and the engine
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

HAVE_PIL = importlib.util.find_spec("PIL") is not None  # the figures are drawn with Pillow
HAVE_NODE = bool(shutil.which("node")) and (ROOT / "node_modules" / "opentype.js").is_dir()  # the deck's writer and its font metrics
# The navy set's own tones (src/portfolio/draw.js C: navy, blue, b1 to b5, n2, n3) and its dark panel (theme.css --deep)
NAVY_FAMILY = ("1B2E4B", "2F6EBA", "24599A", "6E9BD1", "A9C3E4", "D5E2F2", "E6EFF9", "3A5578", "5B7290", "14233A")
CRIMSON = json.loads((ROOT / "src" / "themes.json").read_text(encoding="utf-8")).get("crimson", {})  # the set as shipped


def node(code: str) -> str:
    """What a line of Node.js prints, run in the repository with no theme of the shell's."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_THEME")}  # the built-in sets only
    r = subprocess.run(["node", "-e", code], cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)
    if r.returncode:  # a failure says why
        raise AssertionError(r.stderr)
    return r.stdout


def blue_cast(im) -> int:
    """How many pixels of a picture lean to blue as the navy set's do (blue over red by more than 16 of 255): the navy set and its
    pale steps all do, a black, grey or crimson set's pixels never."""
    return sum(n for n, (r, g, b) in im.convert("RGB").getcolors(1 << 24) if b - r > 16)


class LoaderTests(unittest.TestCase):
    """Crimson as the loaders read it, and where it is offered."""

    def test_crimson_is_a_built_in_set_with_its_figure_tones(self):
        self.assertEqual(("18181B", "BE123C", "18181B"), (CRIMSON.get("nameFill"), CRIMSON.get("acc2"), CRIMSON.get("acc")))  # a black base, a crimson accent
        for k in ("deep", "paper", "n2", "n3", "b1", "b2", "b3", "b4", "b5", "hair", "label", "ink2"):  # the figures' tones it names itself
            self.assertRegex(CRIMSON.get(k, ""), r"^[0-9A-F]{6}$", k)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not on this PC")
    def test_the_javascript_loader_reads_it_whole(self):
        got = json.loads(node('console.log(JSON.stringify(require("./src/theme_load").theme("crimson")))'))  # as layout.js and deck.js read it
        self.assertEqual({k: v for k, v in CRIMSON.items() if not k.startswith("_")}, got)  # every key, the figures' tones too

    @unittest.skipUnless(HAVE_PIL, "Pillow is not installed: the figures' script cannot be loaded")
    def test_the_figures_read_its_colours(self):
        import overview_figures as OF  # src/overview_figures.py: the figures' colours
        with mock.patch.dict(os.environ, {"OFFEROWL_FIG_THEME": "crimson"}):  # as the build names the edition's set
            os.environ.pop("OFFEROWL_THEME", None)
            os.environ.pop("OFFEROWL_THEME_FILE", None)
            self.assertEqual((24, 24, 27), OF.theme_navy())  # the bars: its black
            self.assertEqual(((239, 239, 241), (212, 212, 216)), OF.theme_tones())  # the hierarchy's boxes: its band; the tiles' outline: its rule
        with mock.patch.dict(os.environ, {"OFFEROWL_FIG_THEME": "navy"}):  # the built-in navy keeps the figures' own colours
            os.environ.pop("OFFEROWL_THEME", None)
            os.environ.pop("OFFEROWL_THEME_FILE", None)
            self.assertEqual(OF.NAVY, OF.theme_navy())  # its bars as they were
            self.assertEqual((OF.TINT, OF.TILE_BORDER), OF.theme_tones())  # and its pale blue boxes and light outline

    def test_a_ramp_is_read_in_order_and_its_plates_carry_white_words(self):
        import overview_figures as OF  # src/overview_figures.py: the figures' colours
        old = {k: os.environ.get(k) for k in ("OFFEROWL_THEME", "OFFEROWL_THEME_FILE")}
        try:
            os.environ.pop("OFFEROWL_THEME_FILE", None)
            os.environ["OFFEROWL_THEME"] = "crimson"
            ramp = OF.theme_ramp()
            self.assertEqual(8, len(ramp))  # ramp1 to ramp8, light to dark
            self.assertEqual((253, 164, 175), ramp[0])
            self.assertEqual((76, 5, 25), ramp[-1])
            plates = OF.ramp_pick(ramp, 5)
            self.assertEqual([(225, 29, 72), (190, 18, 60), (159, 18, 57), (136, 19, 55), (76, 5, 25)], plates)  # lightest at the top
            self.assertTrue(all(OF.contrast_white(c) >= 4.5 for c in OF.ramp_pick(ramp, 7)))  # blended steps read too
            os.environ["OFFEROWL_THEME"] = "navy"
            self.assertIsNone(OF.theme_ramp())  # the built-in navy names none and keeps its own shades
            os.environ["OFFEROWL_THEME"] = "teal"
            self.assertIsNone(OF.theme_ramp())  # nor do the other sets
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_the_panel_and_the_agents_offer_it(self):
        from apps.api.tasks import THEMES  # what a build and the panel take
        self.assertIn("crimson", THEMES)
        server = (ROOT / "apps" / "mcp" / "server.py").read_text(encoding="utf-8")  # the agent's tools name the same packs
        self.assertIn('"crimson"', server)
        for f in ("edition.schema.json", "resume.schema.json"):  # the documents' schemas take it
            schema = json.loads((ROOT / "core" / "schema" / "documents" / f).read_text(encoding="utf-8"))
            self.assertIn("crimson", schema["properties"]["theme"]["enum"], f)
        side = (ROOT / "apps" / "panel" / "static" / "side.js").read_text(encoding="utf-8")  # the inspector's swatches
        self.assertIn('["crimson", "Black, crimson", "#18181B", "#BE123C"]', side)  # its black band, and its crimson at the chip's end


@unittest.skipUnless(HAVE_NODE, "Node.js or the typesetting libraries are not here: the deck cannot be written")
class DeckTests(unittest.TestCase):
    """The built-in deck in crimson: no navy anywhere on its page, the set's own tones where the navy ones were."""

    OUT = "owl_themetest_deck"  # an output name no edition uses

    def tearDown(self):
        for f in (ROOT / "output").glob(self.OUT + "*"):  # the page and its notes go again
            f.unlink()

    def page(self, theme=None, look=None) -> str:
        """The deck's page of the fictional English example in a colour set (None: none named) and a look."""
        with tempfile.TemporaryDirectory() as d:
            job = pathlib.Path(d) / "job.json"  # the edition's settings
            cfg = {"out": self.OUT, "lang": "en", "deck": "chapters", **({"theme": theme} if theme else {}), **({"deckStyle": look} if look else {})}
            job.write_text(json.dumps(cfg), encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_THEME") and k != "OFFEROWL_CORNERS"}  # the job file decides
            r = subprocess.run(["node", "src/deck_slides.js", "examples/sample_full_en.json", str(job)], cwd=ROOT, capture_output=True,
                               text=True, timeout=300, env=env)
            self.assertEqual(0, r.returncode, r.stderr)
        return (ROOT / "output" / f"{self.OUT}_deck.html").read_text(encoding="utf-8")

    def test_a_crimson_deck_carries_no_navy(self):
        for look in ("classic", "clean"):  # the dark panels and the light ones
            html = self.page("crimson", look).upper()  # the whole page: its stylesheet, its slides, its figures
            self.assertEqual([], [v for v in NAVY_FAMILY if v in html], look)  # none of the navy set's tones
            for k in ("acc2", "nameFill", "b2", "b4", "n3"):  # the set's own: its accent, its black, the figures' tones it names
                self.assertIn("#" + CRIMSON[k], html, (look, k))

    def test_the_stylesheet_carries_the_tones_the_set_names(self):
        html = self.page("crimson")
        for var, k in (("deep", "deep"), ("paper", "paper"), ("b2", "b2"), ("b3", "b3"), ("b4", "b4"), ("hair", "hair"), ("label", "label"), ("ink2", "ink2")):
            self.assertIn(f"--{var}:#{CRIMSON[k]};", html, var)  # the deck's variables, as the set names them

    def test_navy_keeps_its_colours(self):
        plain, navy = self.page(), self.page("navy")
        self.assertEqual(plain, navy)  # the built-in navy is the default, byte for byte
        self.assertTrue(all(v in navy.upper() for v in ("1B2E4B", "2F6EBA", "14233A")))  # its own tones
        self.assertNotIn("BE123C", navy.upper())  # and nothing of crimson


@unittest.skipUnless(HAVE_PIL and shutil.which("node"), "Pillow or Node.js is not here: the figures' script cannot run")
class FigureTests(unittest.TestCase):
    """The resume's figures drawn by the script in crimson, as a build draws them: no navy pixel in their bars and boxes."""

    OUT = "owl_themetest"  # an output name no edition uses

    def tearDown(self):
        for f in (ROOT / "output" / "_figures").glob(self.OUT + "_*"):  # its pictures go again
            f.unlink()

    def draw(self, theme):
        """The figures of the fictional English example in a colour set; {kind: picture}."""
        from PIL import Image  # read back
        env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_THEME") and k != "OFFEROWL_CORNERS"}  # the set named below
        r = subprocess.run([sys.executable, "src/overview_figures.py", "examples/sample_full_en.json", self.OUT, "en"], cwd=ROOT,
                           capture_output=True, text=True, timeout=300, env={**env, "OFFEROWL_FIG_THEME": theme})
        self.assertEqual(0, r.returncode, r.stderr)
        d = ROOT / "output" / "_figures"
        return {f.name[len(self.OUT) + 1:-4]: Image.open(f).convert("RGB") for f in sorted(d.glob(self.OUT + "_*.png")) if "_logo_" not in f.name}  # read whole, so no file stays open

    def test_crimson_figures_hold_no_navy(self):
        figs = self.draw("crimson")
        self.assertIn("timeline_en", figs)  # the resume's timeline, its hierarchy figure, the deck's and the chapters' timelines
        self.assertIn("stack_en", figs)
        for name, im in figs.items():
            self.assertEqual(0, blue_cast(im), name)  # bars, plates, boxes and words: black, greys and the set's band
        colours = {c for _, c in figs["stack_en"].convert("RGB").getcolors(1 << 24)}
        self.assertIn((239, 239, 241), colours)  # the boxes of the skills in its band
        self.assertIn((225, 29, 72), colours)  # the top plate in the lightest step of its ramp that carries white words (E11D48)
        self.assertIn((76, 5, 25), colours)  # the bottom plate in its darkest step (4C0519)
        timeline = {c for _, c in figs["timeline_en"].convert("RGB").getcolors(1 << 24)}
        self.assertIn((76, 5, 25), timeline)  # the newest career bar in the ramp's darkest step, not in grey
        self.assertIn((136, 19, 55), timeline)  # the one before it a step lighter (881337)

    def test_navy_figures_keep_their_navy(self):
        figs = self.draw("navy")
        self.assertGreater(blue_cast(figs["timeline_en"]), 1000)  # navy bars, as before
        self.assertIn((232, 238, 245), {c for _, c in figs["stack_en"].convert("RGB").getcolors(1 << 24)})  # the hierarchy's own pale blue


if __name__ == "__main__":
    unittest.main()
