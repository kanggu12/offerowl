"""A person's own deck source (the workspace's deck/ folder with its build.js): every edition's deck is written from it, in
the container, with the PC's browser and on the live page; a blind edition keeps it; a changed source makes the editions it
wrote stale; nothing of it stays in the engine's folder. Fictional data only."""
import json  # settings and records
import os  # the environment a build gets
import pathlib  # paths
import shutil  # is node here
import sys  # the import path
import unittest  # the runner
from unittest import mock  # stand-ins for the typesetting

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src", ROOT / "tests" / "app", ROOT / "tests" / "render"):  # apps/, the engine, the helpers beside this file
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from test_blind import TABLE, Builds  # noqa: E402  a person, and builds with the typesetting stood in for
import resume  # noqa: E402  src/resume.py: the deck's writer

# A deck source as small as one can be: build.js writes the page Offerowl names, one slide that says which language and
# whether the blind switch was on, and the measurement element the checks read
BUILD_JS = """const fs = require("fs"), path = require("path");
const [, , profile, jobFile, page] = process.argv;
const cfg = JSON.parse(fs.readFileSync(jobFile, "utf8"));
const blind = process.env.OFFEROWL_BLIND === "1" ? " blind" : "";
fs.writeFileSync(path.join(process.cwd(), "output", page + ".html"),
  `<!doctype html><html><body><section class="slide">Own deck ${cfg.lang || "ko"}${blind}</section><pre id="probe-out">{"slides": []}</pre></body></html>`);
"""


class DeckSourceTests(Builds):
    """The workspace's deck/ folder writes every edition's deck."""

    def source(self, a, words=BUILD_JS):
        """The person's deck source in the workspace."""
        d = a.ws.path("deck")  # beside the profile and the jobs
        d.mkdir(exist_ok=True)
        (d / "build.js").write_text(words, encoding="utf-8")
        (d / "slides.txt").write_text("the person's slides", encoding="utf-8")  # a file of their own, copied with it
        return d

    def test_every_build_stages_the_source_and_cleans_it_away(self):
        a = self.person()
        self.stand_in(a)  # the typesetting stood in for: it records the environment it was given
        seen = []  # the deck source each deck step was given
        real = resume.build_deck  # the stand-in Builds set up

        def deck(profile, cfg=None, env=None):
            src = (env or {}).get("OFFEROWL_DECK_SOURCE")  # what the build named
            seen.append((src, bool(src) and (ROOT / src / "build.js").is_file() and (ROOT / src / "slides.txt").is_file()))
            return real(profile, cfg, env)
        with mock.patch.object(resume, "build_deck", side_effect=deck):
            with mock.patch.dict(os.environ, {"OFFEROWL_DECK_SOURCE": "output"}):  # one the server was started with never counts
                a.tasks._build("-general", "ko", "navy", 3, False, False)  # no source yet: the deck is drawn
            self.source(a)
            a.tasks._build("-general", "ko", "navy", 3, False, False)  # with the person's source
        self.assertEqual((None, False), seen[0])  # none named without a source
        src, whole = seen[1]
        self.assertTrue(src and whole, seen[1])  # the folder was there, whole, while the deck was written
        self.assertFalse((ROOT / src).exists())  # and gone again: the person's slides do not stay in the engine's folder
        rec = self.record(a, "-general")  # what the edition says it was made from
        self.assertEqual(a.tasks.deck_stamp(), rec["deck_src"])  # the source, by its stamp
        self.assertFalse(a.stale("-general", rec))  # current
        pyc = a.ws.path("deck") / "tools" / "__pycache__" / "check.cpython-310.pyc"  # a run of the deck's own checks leaves bytecode
        pyc.parent.mkdir(parents=True, exist_ok=True)
        pyc.write_bytes(b"\x00bytecode")
        self.assertFalse(a.stale("-general", rec))  # no change to the slides: still current
        (a.ws.path("deck") / "slides.txt").write_text("a slide changed", encoding="utf-8")  # the person edits their slides
        self.assertTrue(a.stale("-general", rec))  # the deck it wrote is stale now
        self.assertFalse(a.stale("-general", {k: v for k, v in rec.items() if k != "deck_src"}))  # one made before there was a source stays as it was

    def test_a_blind_edition_keeps_a_deck_from_the_source(self):
        a = self.person()
        a.set_blind({"table": TABLE})  # the person's table
        self.stand_in(a)
        prof = a.ws.path("profile", "profile.json")  # the profile names a portfolio PDF: a blind edition would leave it out
        data = json.loads(prof.read_text(encoding="utf-8"))
        (self.tmp / "made.pdf").write_bytes(b"%PDF-1.4")
        data["deck"] = {"pdf": str(self.tmp / "made.pdf")}
        prof.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        env = {"OFFEROWL_BLIND": "1"}  # a blind build
        self.assertTrue(resume.blind_leaves_deck(str(prof), None, env))  # a PDF cannot be covered
        self.source(a)
        staged = a.tasks._stage_deck()  # as a build stages it
        self.addCleanup(shutil.rmtree, ROOT / staged, True)
        self.assertFalse(resume.blind_leaves_deck(str(prof), None, {**env, "OFFEROWL_DECK_SOURCE": staged}))  # the source covers its own words

    def test_only_a_source_inside_the_engine_is_run(self):
        self.assertIsNone(resume.deck_source({"OFFEROWL_DECK_SOURCE": "/etc"}))  # an absolute path
        self.assertIsNone(resume.deck_source({"OFFEROWL_DECK_SOURCE": "../elsewhere"}))  # out of the repository
        self.assertIsNone(resume.deck_source({"OFFEROWL_DECK_SOURCE": "output/_inputs/none_deck"}))  # no build.js there
        self.assertIsNone(resume.deck_source({}))  # none named

    @unittest.skipUnless(shutil.which("node"), "Node.js is not on this PC")
    def test_the_live_page_is_the_sources(self):
        a = self.person()
        self.source(a)
        with mock.patch.object(a.tasks, "engine_ready", return_value=""):  # the libraries are there
            page = a.tasks.deck_live("-general", "ko")  # the canvas's deck
        self.assertIn("Own deck ko", page.get("html", ""), page)  # written by the person's build.js
        self.assertEqual(1, page["slides"])
        self.assertFalse(list((ROOT / "output" / "_inputs").glob("*_deck_live")))  # its copy is gone again


if __name__ == "__main__":
    unittest.main()
