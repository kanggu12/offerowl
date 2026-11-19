# -*- coding: utf-8 -*-
"""The overview timeline's gaps (summary.timeline.gaps): a stretch inside the axis squeezed behind a double wave like the
study-only lead-in, so a long run of one bar does not take the width the recent years need. The axis keeps its order and its
ends, a gap is as wide as the lead-in's squeeze, a profile without gaps draws the same pixels as before, and one with a gap
draws differently. Fictional people only.

Run: python3 -m unittest tests/render/test_timeline_gaps.py -v
"""
import importlib.util  # is Pillow here
import json  # the example profile
import os  # the figures' environment
import pathlib  # paths
import subprocess  # the figures' script
import sys  # the import path, the interpreter
import tempfile  # the edited profile
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src"):  # the engine
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

HAVE_PIL = importlib.util.find_spec("PIL") is not None  # the figures are drawn with Pillow


@unittest.skipUnless(HAVE_PIL, "Pillow is not here: the figures' module cannot load")
class AxisTests(unittest.TestCase):
    """axis_map: a fractional year to x, with a squeezed lead-in and squeezed gaps."""

    def setUp(self):
        import overview_figures as OF  # src/overview_figures.py
        self.OF = OF

    def test_without_gaps_the_axis_is_the_old_one(self):
        X = self.OF.axis_map(2008.0, 2021.9, 2010.0, [], 54.0, 686.0, 36.0)
        for t in (2008.0, 2009.2, 2010.0, 2014.5, 2021.9):
            old = 54.0 + (t - 2008.0) / 2.0 * 36.0 if t < 2010.0 else 54.0 + 36.0 + (t - 2010.0) / (2021.9 - 2010.0) * (686.0 - 54.0 - 36.0)
            self.assertEqual(old, X(t))  # the same arithmetic, so the same pixels

    def test_a_gap_is_squeezed_and_the_axis_keeps_its_order_and_ends(self):
        X = self.OF.axis_map(2008.0, 2021.9, 2010.0, [(2012.0, 2014.0)], 54.0, 686.0, 36.0)
        self.assertAlmostEqual(54.0, X(2008.0))
        self.assertAlmostEqual(686.0, X(2021.9))  # the right end stays where it was
        self.assertAlmostEqual(36.0, X(2014.0) - X(2012.0))  # two years in the gap's width
        xs = [X(2008.0 + i / 10) for i in range(140)]
        self.assertEqual(xs, sorted(xs))  # never backwards
        k = (X(2011.0) - X(2010.0))  # a plain year
        self.assertAlmostEqual(k, X(2015.0) - X(2014.0))  # the plain stretches share one scale
        self.assertGreater(k, (686.0 - 54.0 - 36.0) / (2021.9 - 2010.0))  # wider than with no gap: the room went to them

    def test_two_gaps_and_no_lead_in(self):
        X = self.OF.axis_map(2010.0, 2026.0, None, [(2012.0, 2014.0), (2018.0, 2020.0)], 0.0, 1000.0, 40.0)
        self.assertAlmostEqual(40.0, X(2014.0) - X(2012.0))
        self.assertAlmostEqual(40.0, X(2020.0) - X(2018.0))
        self.assertAlmostEqual(1000.0, X(2026.0))
        self.assertAlmostEqual(X(2011.0) - X(2010.0), X(2025.0) - X(2024.0))


@unittest.skipUnless(HAVE_PIL, "Pillow is not here: the figures' script cannot run")
class FigureTests(unittest.TestCase):
    """The timeline drawn from the fictional English example, with and without a gap."""

    OUT = "owl_gaptest"  # an output name no edition uses

    def tearDown(self):
        for f in (ROOT / "output" / "_figures").glob(self.OUT + "*"):  # its pictures go again
            f.unlink()

    def draw(self, gaps, tag):
        """The timeline's bytes for the example with summary.timeline.gaps set as given (None: the key absent)."""
        prof = json.loads((ROOT / "examples" / "sample_full_en.json").read_text(encoding="utf-8"))
        if gaps is not None:
            prof.setdefault("summary", {})["timeline"] = {"gaps": gaps}
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / "profile.json"
            src.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_THEME") and k not in ("OFFEROWL_FIG_THEME", "OFFEROWL_CORNERS")}
            r = subprocess.run([sys.executable, "src/overview_figures.py", str(src), self.OUT + tag, "en"], cwd=ROOT,
                               capture_output=True, text=True, timeout=300, env=env)
            self.assertEqual(0, r.returncode, r.stderr)
        return (ROOT / "output" / "_figures" / f"{self.OUT}{tag}_timeline_en.png").read_bytes()

    def test_no_gap_draws_as_before_and_a_gap_changes_the_picture(self):
        plain = self.draw(None, "a")
        self.assertEqual(plain, self.draw([], "b"))  # an empty list is no gap
        self.assertEqual(plain, self.draw([["2030.01", "2031.01"]], "c"))  # a gap outside the axis means nothing
        self.assertNotEqual(plain, self.draw([["2020.01", "2021.01"]], "d"))  # one inside squeezes that year


if __name__ == "__main__":
    unittest.main()
