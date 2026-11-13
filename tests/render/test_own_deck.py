# -*- coding: utf-8 -*-
"""src/resume.py own_deck and build_deck: a profile that names the person's own portfolio PDF gets that deck, page for
page, with its title and author; one that names a missing file stops; one that names none is drawn as before. And check():
a style pack named by its path is staged where the typesetting container sees it.

Run: python3 -m unittest tests/render/test_own_deck.py -v
"""
import json  # the profile and the settings
import pathlib  # paths
import sys  # the import path
import tempfile  # the profile and its PDF
import unittest  # the test runner
import unittest.mock  # the container call, for the style test

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
sys.path.insert(0, str(ROOT / "tests" / "render"))  # the small PDF writer of the reader tests
import pdfmeta  # noqa: E402  reads the title and author back
import pdftools  # noqa: E402  the page reader
import resume as R  # noqa: E402  the module under test
from test_pdftools import write_pdf  # noqa: E402  a PDF with text


class OwnDeck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()  # the profile, its PDF and the settings go here
        self.addCleanup(self.dir.cleanup)
        self.tmp = pathlib.Path(self.dir.name)  # that folder
        self.ko = self.tmp / "mine_ko.pdf"  # the person's Korean portfolio
        write_pdf(self.ko, [[(72, 72, 12, "Cover")], [(72, 72, 12, "Payments")], [(72, 72, 12, "End")]])  # three pages
        self.en = self.tmp / "mine_en.pdf"  # and the English one
        write_pdf(self.en, [[(72, 72, 12, "Cover EN")], [(72, 72, 12, "End EN")]])  # two pages

    def profile(self, deck):
        """A profile file naming the deck as given, with a ledger-style name."""
        p = self.tmp / "profile.json"  # where it is kept
        body = {"person": {"name": "홍 길 동 (Gildong Hong)", "email": "gildong@example.com"}}  # whose documents
        if deck is not None:  # a deck entry to try
            body["deck"] = deck
        p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")  # written
        return str(p)

    def cfg(self, lang):
        """The settings of one edition."""
        c = self.tmp / f"{lang}.json"  # one per language
        c.write_text(json.dumps({"lang": lang, "out": f"owl_owndeck_test_{lang}"}), encoding="utf-8")  # a name no real edition uses
        return str(c)

    def test_one_file_per_language_is_found_and_a_relative_path_reads_from_the_profile(self):
        prof = self.profile({"pdf": {"ko": "mine_ko.pdf", "en": str(self.en)}})  # relative for Korean, absolute for English
        self.assertEqual(self.ko.resolve(), R.own_deck(prof, self.cfg("ko")).resolve())  # beside the profile
        self.assertEqual(self.en, R.own_deck(prof, self.cfg("en")))  # as named

    def test_none_named_means_the_deck_is_drawn(self):
        self.assertIsNone(R.own_deck(self.profile(None), self.cfg("ko")))  # no deck entry
        self.assertIsNone(R.own_deck(self.profile({"pdf": {"en": str(self.en)}}), self.cfg("ko")))  # only the other language

    def test_a_named_file_that_is_gone_stops_the_build(self):
        prof = self.profile({"pdf": str(self.tmp / "gone.pdf")})  # one path for both, not there
        with self.assertRaises(SystemExit):  # never a quiet fallback to a lesser deck
            R.own_deck(prof, self.cfg("ko"))

    def test_the_build_copies_the_pages_and_names_the_person(self):
        prof = self.profile({"pdf": {"ko": str(self.ko), "en": str(self.en)}})  # both editions
        made = []  # the engine's files this test leaves, removed after
        self.addCleanup(lambda: [f.unlink() for f in made if f.exists()])
        for lang, src, n, want in (("ko", self.ko, 3, ("홍길동 포트폴리오", "홍길동")), ("en", self.en, 2, ("Gildong Hong Portfolio", "Gildong Hong"))):
            pdf = R.build_deck(prof, self.cfg(lang))  # the deck step
            made += [pdf, pdf.with_name(pdf.stem + ".probe.json"), ROOT / "output" / "_inputs" / f"owl_owndeck_test_{lang}.job.json"]
            self.assertEqual(n, pdftools.info(pdf)["pages"])  # page for page
            self.assertEqual(pdftools.text(src), pdftools.text(pdf))  # the same words
            self.assertEqual({"title": want[0], "author": want[1]}, pdfmeta.read(pdf))  # its title and the joined name
            probe = json.loads(pdf.with_name(pdf.stem + ".probe.json").read_text(encoding="utf-8"))  # what the checks read
            self.assertTrue(probe["own"])  # marked as the person's own
            self.assertEqual(n, len(probe["slides"]))  # one entry per page


class CheckStyle(unittest.TestCase):
    def test_a_style_pack_named_by_path_is_staged_for_the_container(self):
        with tempfile.TemporaryDirectory() as d:  # a pack outside the repository, as a workspace keeps one
            pack = pathlib.Path(d) / "mine.json"  # the person's own rules
            pack.write_text('{"banned_chars": ""}', encoding="utf-8")
            cfg = pathlib.Path(d) / "job.json"  # settings naming it by its full path
            cfg.write_text(json.dumps({"style": str(pack), "maxPages": 2}), encoding="utf-8")
            seen = []  # the commands the check would run
            fake = lambda cmd, *a, **k: seen.append(cmd) or R.subprocess.CompletedProcess(cmd, 0, "", "")  # nothing runs
            with unittest.mock.patch.object(R, "sh", side_effect=fake), \
                    unittest.mock.patch.object(R, "rel", side_effect=lambda p: "output/_inputs/" + pathlib.Path(p).name):  # staged, as rel() copies it
                R.check(str(cfg), str(cfg), pathlib.Path("x.pdf"), None)
            style = seen[0][seen[0].index("--style") + 1]  # what the check is told
            self.assertEqual("output/_inputs/mine.json", style)  # the copy the container sees, never the host path
            with unittest.mock.patch.object(R, "sh", side_effect=fake), unittest.mock.patch.object(R, "rel", side_effect=lambda p: p):
                cfg.write_text(json.dumps({"style": "default"}), encoding="utf-8")  # a shipped pack's name
                R.check(str(cfg), str(cfg), pathlib.Path("x.pdf"), None)
            self.assertEqual("default", seen[1][seen[1].index("--style") + 1])  # goes over as it is


if __name__ == "__main__":
    unittest.main()
