# -*- coding: utf-8 -*-
"""The colour sets and the figures: crimson (a black base and a crimson accent) loads in the JavaScript and the Python loaders
with the tones it names for the figures, and the panel and the agents offer it; a built-in deck in it carries none of the navy
set's colours, in its slides or in its stylesheet, and its dark panels (the cover's name panel, the chapters' panels, the last
slide) take the tones it names for them, none of its pale pinks; the category tints follow a set that names its own; a set
that names none of these keeps the deck's old tones; the resume's figures in it hold no navy pixel in their bars, boxes and
tiles' outline; the built-in navy keeps every colour it had. Fictional people only; the deck's page is written by Node.js, with
no browser, and the colour that wins on a part is read from the page's stylesheet.

Run: python3 -m unittest tests/render/test_themes.py -v
"""
import importlib.util  # is Pillow here
import json  # the loaders' answers, the job file
import math  # the distance of two colours
import os  # the theme the figures are drawn in
import pathlib  # paths
import re  # the page's stylesheet, rule by rule
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
# The keys a set may name for the deck's dark panels and its category tints; a set that names none keeps the old tones
DARK_KEYS, TINT_KEYS = ("deepMark", "deepEyebrow", "deepLabel"), ("a3", "a4", "t3", "t4")
# The parts of the dark panels that theme.css colours with the accent's b2 and b3: (selector, property, the key that colours it)
DARK_PARTS = ((".chapter .cl .no", "color", "deepMark"), (".eod .top::before", "background", "deepMark"),
              (".eod .cc .ic", "background", "deepMark"), (".rail.dark .here", "border-left-color", "deepMark"),
              (".cover .name .kind", "color", "deepEyebrow"), (".chapter .cl .kind", "color", "deepEyebrow"), (".eod .top", "color", "deepEyebrow"),
              (".cover .name h1 small", "color", "deepLabel"), (".chapter .cl .enm", "color", "deepLabel"),
              (".chapter .cl .meta b", "color", "deepLabel"), (".eod h1 small", "color", "deepLabel"), (".eod .cc b", "color", "deepLabel"))
# The category colours' words and pale steps as the figures draw them (src/portfolio/draw.js C)
AMBER, TEAL, OWN_TINTS = "A9561B", "137A63", {"a3": "F2C9A2", "a4": "FBEEE2", "t3": "A3DCC8", "t4": "E1F3EC"}


def without_keys(name: str) -> dict:
    """A theme file's sets: crimson as shipped without the keys of the dark panels and the tints, under a fictional name."""
    return {name: {k: v for k, v in CRIMSON.items() if not k.startswith("_") and k not in DARK_KEYS + TINT_KEYS}}


def light(hex6: str) -> float:
    """A colour's relative luminance (WCAG)"""
    c = [int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    """The contrast of two colours, as the deck's probe measures it"""
    la, lb = light(a), light(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def oklab_gap(a: str, b: str) -> float:
    """How far apart two colours look: their distance in OKLab, times 100"""
    def lab(h):
        r, g, b_ = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))]
        l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b_) ** (1 / 3)
        m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b_) ** (1 / 3)
        s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b_) ** (1 / 3)
        return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_, 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
                0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)
    return 100 * math.dist(lab(a), lab(b))


def winning(html: str, selector: str, prop: str) -> str:
    """The colour a part of the deck takes: the last rule of the page's stylesheet that names the selector and sets the property
    (the parts read here share one specificity, so the last one wins), with a var() read from the last :root that sets it"""
    css = re.sub(r"/\*.*?\*/", "", re.search(r"<style>(.*?)</style>", html, re.S).group(1), flags=re.S)  # the stylesheet, no comments

    def last(sel, name):
        got = None
        for sels, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):  # rule by rule, in order
            if sel in [s.strip() for s in sels.split(",")]:
                for decl in body.split(";"):
                    k, _, v = decl.partition(":")
                    if k.strip() == name:
                        got = v.strip()
        return got
    value = last(selector, prop)
    m = re.fullmatch(r"var\((--[\w-]+)\)", value or "")
    return (last(":root", m.group(1)) if m else value or "").upper()


def node(code: str, *args: str) -> str:
    """What a line of Node.js prints, run in the repository with no theme of the shell's; args are its process.argv[1:]."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_THEME")}  # the built-in sets only
    r = subprocess.run(["node", "-e", code, *args], cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)
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

    def test_crimson_names_its_dark_panels_and_its_tints(self):
        for k in DARK_KEYS + ("a3", "a4", "t4"):  # its dark panels' tones and its own category tints (t3 stays the figures' own)
            self.assertRegex(CRIMSON.get(k, ""), r"^[0-9A-F]{6}$", k)
        deep = CRIMSON["deep"]  # the dark panels' ground
        self.assertGreaterEqual(contrast(CRIMSON["deepEyebrow"], deep), 4.5)  # the small eyebrows read on it
        self.assertGreaterEqual(contrast(CRIMSON["deepLabel"], deep), 4.5)  # and the labels
        self.assertGreaterEqual(contrast(CRIMSON["deepMark"], deep), 3)  # the chapter's number, as large text
        self.assertLess(oklab_gap(CRIMSON["b5"], OWN_TINTS["a4"]), 3)  # why it names its tints: the figures' pale amber was near its pale crimson
        for a, b in (("b5", "a4"), ("b4", "a4"), ("a4", "t4"), ("b5", "t4")):  # grounds that may stand side by side in one figure
            self.assertGreaterEqual(oklab_gap(CRIMSON[a], CRIMSON[b]), 4, (a, b))
        self.assertGreaterEqual(contrast(AMBER, CRIMSON["a4"]), 4.5)  # amber words on its amber ground
        self.assertGreaterEqual(contrast(TEAL, CRIMSON["t4"]), 4.5)  # teal words on its teal ground
        self.assertGreaterEqual(contrast(CRIMSON["nameFill"], CRIMSON["a3"]), 4.5)  # its dark words on its amber fill

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

    def page(self, theme=None, look=None, sets=None) -> str:
        """The deck's page of the fictional English example in a colour set (None: none named) and a look; sets: the sets of a
        theme file (OFFEROWL_THEME_FILE), for a set that is not built in."""
        with tempfile.TemporaryDirectory() as d:
            job = pathlib.Path(d) / "job.json"  # the edition's settings
            cfg = {"out": self.OUT, "lang": "en", "deck": "chapters", **({"theme": theme} if theme else {}), **({"deckStyle": look} if look else {})}
            job.write_text(json.dumps(cfg), encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_THEME") and k != "OFFEROWL_CORNERS"}  # the job file decides
            if sets:  # a theme file beside the job file
                (pathlib.Path(d) / "themes.json").write_text(json.dumps(sets), encoding="utf-8")
                env["OFFEROWL_THEME_FILE"] = str(pathlib.Path(d) / "themes.json")
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
        for sel, prop, key in DARK_PARTS:  # its dark panels in theme.css's own b2 and b3
            self.assertEqual("#6E9BD1" if key == "deepMark" else "#A9C3E4", winning(navy, sel, prop), sel)

    def test_crimson_dark_panels_take_the_tones_it_names(self):
        html = self.page("crimson")  # the classic look: the cover's name panel, the chapters' panels and the last slide are dark
        pinks = ("#" + CRIMSON["b2"], "#" + CRIMSON["b3"])  # FB7185 and FECDD3, which read as pink on its black
        for sel, prop, key in DARK_PARTS:
            got = winning(html, sel, prop)
            self.assertEqual("#" + CRIMSON[key], got, sel)  # each part in the tone the set names for it
            self.assertNotIn(got, pinks, sel)
        self.assertEqual("#FFFFFF", winning(html, ".eod .tag", "color"))  # the last slide's tagline white, as the cover's is

    def test_a_set_without_the_keys_keeps_the_old_tones(self):
        html = self.page("owl_plain", sets=without_keys("owl_plain"))  # crimson without the new keys, from a theme file
        for sel, prop, key in DARK_PARTS:  # theme.css's b2 and b3, as every set had them
            self.assertEqual("#" + CRIMSON["b2" if key == "deepMark" else "b3"], winning(html, sel, prop), sel)
        self.assertEqual("#" + CRIMSON["b3"], winning(html, ".eod .tag", "color"))  # the tagline too
        self.assertIn("#" + OWN_TINTS["a4"], html.upper())  # the data box in the figures' own pale amber
        self.assertNotIn("#" + CRIMSON["a4"], html.upper())

    def test_the_light_look_keeps_its_panels(self):
        named, plain = self.page("crimson", "clean"), self.page("owl_plain", "clean", sets=without_keys("owl_plain"))
        for sel, prop, _ in DARK_PARTS + ((".eod .tag", "color", None),):  # paper panels: style_clean.css's colours, keys or none
            self.assertEqual(winning(plain, sel, prop), winning(named, sel, prop), sel)
        self.assertIn("#" + CRIMSON["a4"], named.upper())  # its figures take its tints in either look

    def test_the_category_tints_follow_a_set_that_names_them(self):
        page = ROOT / "output" / f"{self.OUT}_tints.html"  # one slide holding the four pale steps as the figures draw them
        code = ('const { Deck } = require("./src/portfolio/deck"), { C } = require("./src/portfolio/draw");'
                'const d = new Deck({ title: "Tints", footer: "Tints", theme: process.argv[1], lang: "en" });'
                'd.add({}, `<svg>${["a3", "a4", "t3", "t4"].map(k => `<rect fill="${C[k]}"/>`).join("")}</svg>`); d.render(process.argv[2]);')

        def fills(theme):  # the four fills as the page holds them in a set
            node(code, theme, str(page))
            return re.findall(r'<rect fill="#([0-9A-F]{6})"/>', page.read_text(encoding="utf-8"))
        self.assertEqual([CRIMSON["a3"], CRIMSON["a4"], OWN_TINTS["t3"], CRIMSON["t4"]], fills("crimson"))  # t3, which it leaves out, stays
        self.assertEqual([OWN_TINTS[k] for k in TINT_KEYS], fills("teal"))  # a set that names none keeps the figures' own

    def test_the_cover_path_takes_the_ramp_steps(self):
        """The cover's career path in a set with a ramp: each station in the step its role's bar takes in the overview figures, the
        darkest for the newest role and one lighter for each role before it, and the line toward a station in that station's step."""
        for look in ("classic", "clean"):  # the strip sits on the cover's light half in either look
            html = self.page("crimson", look)
            steps = "".join(f"--ramp{k}:#{CRIMSON[f'ramp{k}']};" for k in range(1, 9))  # the set's eight steps, light to dark
            self.assertIn(":root{" + steps + "}", html, look)  # its stylesheet names them
            path = html[html.index('<div class="journey"'):]  # the strip, from its start
            dots = re.findall(r"border-radius:7px; background:([^;]+);", path)[:3]  # the example's three roles, the oldest first
            self.assertEqual(["var(--ramp6)", "var(--ramp7)", "var(--ramp8)"], dots, look)
            self.assertIn("background:linear-gradient(90deg, var(--ramp7) 0% 50%, var(--ramp8) 50% 100%)", path, look)  # each gap in the step it leads to

    def test_a_set_without_a_ramp_keeps_the_pale_to_dark_path(self):
        for name in ("teal", None):  # a built-in set that names none, and no set at all
            html = self.page(name)
            self.assertNotIn("--ramp", html, name)  # no steps written and none asked for
            path = html[html.index('<div class="journey"'):]
            self.assertIn("background:linear-gradient(90deg, var(--b3), var(--navy))", path, name)  # the line as it always ran
            self.assertIn("background:color-mix(in srgb, var(--navy) 0%, var(--b3))", path, name)  # and the oldest station's pale step

    def test_the_deck_counts_a_ramp_as_the_figures_do(self):
        """Steps are read in order up to the first missing one, and fewer than three make no ramp, in the deck (deck.js rampSteps) as in
        the overview figures (overview_figures.py theme_ramp), so the cover's path and the bars take the same steps."""
        import overview_figures as OF  # src/overview_figures.py: the figures' colours
        base = {k: v for k, v in CRIMSON.items() if not k.startswith("_") and not k.startswith("ramp")}  # crimson without its ramp
        r = {f"ramp{k}": CRIMSON[f"ramp{k}"] for k in range(1, 9)}  # and its steps, to take some of
        sets = {"owl_two": {**base, "ramp1": r["ramp1"], "ramp2": r["ramp2"]},  # two steps: no ramp
                "owl_gap": {**base, **{k: r[k] for k in ("ramp1", "ramp2", "ramp3", "ramp5")}},  # ramp4 missing: three steps
                "owl_eight": {**base, **r}}  # all eight
        with tempfile.TemporaryDirectory() as d:
            tf = pathlib.Path(d) / "themes.json"  # a theme file of fictional sets
            tf.write_text(json.dumps(sets), encoding="utf-8")
            env = {**{k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_THEME")}, "OFFEROWL_THEME_FILE": str(tf)}
            code = 'console.log(JSON.stringify(process.argv.slice(1).map(n => require("./src/portfolio/deck").rampSteps(n))))'
            got = subprocess.run(["node", "-e", code, *sets], cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)
            self.assertEqual(0, got.returncode, got.stderr)
            self.assertEqual([0, 3, 8], json.loads(got.stdout))  # the deck's count for each set
            with mock.patch.dict(os.environ, {"OFFEROWL_THEME_FILE": str(tf)}):
                for name, want in zip(sets, (0, 3, 8)):
                    with mock.patch.dict(os.environ, {"OFFEROWL_THEME": name}):
                        self.assertEqual(want, len(OF.theme_ramp() or []), name)  # the figures' count, the same


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
