#!/usr/bin/env python3
"""The checks across documents on real typeset documents (0.10.0): the fictional example typeset in the render container, as
the panel's builds are.

  - a blind edition and its ordinary twin stand alike word for word, resume and deck, and the table's patterns that the
    example prints are found in the twin's words; an edition whose words moved is caught;
  - the example made twice changes no page, and a period changed in one project changes the page that prints it;
  - the Korean and the English example agree, the check running where the documents' checks run.

  python3 -m unittest tests/render/test_compare_render.py -v
"""
import json  # profiles, tables, reports
import os  # the builds' environment
import pathlib  # paths
import shutil  # the folder of this test
import sys  # the import path
import tempfile  # a folder the container sees
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT / "src", ROOT / "tests" / "render"):  # the engine, the helpers beside this file
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from test_blind_figures import render_image  # noqa: E402  is the render container's image here
import baseline as BL  # noqa: E402  src/baseline.py
import pdftools  # noqa: E402  the pages drawn on this PC
import resume  # noqa: E402  the typesetting

EX = ROOT / "examples"  # the fictional example
# a fictional table: the example's two companies in Korean, its mail address, its phone, and a name no edition prints
TABLE = {"mask": ["알파페이", "베타커머스", r"gildong@example\.com", "010-0000-0000", "Deltasoft"], "mask_whole": [r"gildong@example\.com", "010-0000-0000"],
         "leak": [], "mask_keep": []}


@unittest.skipUnless(os.environ.get("OFFEROWL_TEST_RENDER") != "0" and render_image(), "the render container's image is not built here (render/run.sh builds it)")
@unittest.skipUnless((ROOT / "node_modules" / "docx").is_dir(), "the typesetting libraries are not installed (render/run.sh npm ci)")
@unittest.skipUnless(pdftools.reader(), "no PDF reader on this PC")
class CompareRenderTests(unittest.TestCase):
    """The example passes each check across documents; a seeded difference fails it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="compare-", dir=str(ROOT / "output")))  # where the container sees it
        cls.table = cls.tmp / "table.json"
        cls.table.write_text(json.dumps(TABLE, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        for pat in ("cmp_*", "_figures/cmp_*", "_inputs/cmp_*"):  # the builds' own files in the engine's folder
            for f in (ROOT / "output").glob(pat):
                f.unlink(missing_ok=True)

    def job(self, out: str, lang: str = "ko") -> pathlib.Path:
        """The example's job settings under an output name of this test's."""
        cfg = json.loads((EX / f"job_full_{lang}.json").read_text(encoding="utf-8"))
        cfg["out"] = out
        f = self.tmp / f"{out}.job.json"
        f.write_text(json.dumps(cfg), encoding="utf-8")
        return f

    def env(self, blind: bool) -> dict:
        """A build's own environment: ordinary, or blind with the fictional table."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_BLIND")}
        if blind:
            env.update(OFFEROWL_BLIND="1", OFFEROWL_BLIND_LANG="ko", OFFEROWL_BLIND_TABLE=resume.rel(str(self.table)))
        return env

    def layout(self, ordinary, blind_pdf, *extra) -> dict:
        """src/check_blind.py on two editions, in the container, with its report."""
        rep = self.tmp / "layout.json"
        rep.unlink(missing_ok=True)
        r = resume.sh(["python3", "src/check_blind.py", "layout", resume.rel(str(ordinary)), resume.rel(str(blind_pdf)), *extra, "--report", resume.rel(str(rep))])
        self.assertTrue(rep.is_file(), r.stdout + r.stderr)
        return json.loads(rep.read_text(encoding="utf-8"))

    def test_a_blind_edition_stands_where_its_twin_does(self):
        profile = str(EX / "sample_full_ko.json")
        twin, twin_deck = resume.build(profile, str(self.job("cmp_twin_ko")), self.env(False)), resume.build_deck(profile, str(self.job("cmp_twin_ko")), self.env(False))
        blind, blind_deck = resume.build(profile, str(self.job("cmp_blind_ko")), self.env(True)), resume.build_deck(profile, str(self.job("cmp_blind_ko")), self.env(True))
        rep = self.layout(twin, blind, resume.rel(str(twin_deck)), resume.rel(str(blind_deck)), "--table", resume.rel(str(self.table)), "--files",
                          resume.rel(str(twin.with_suffix(".docx"))), resume.rel(str(twin_deck)[:-4] + ".html"))
        self.assertEqual([], rep["defects"], rep)  # every word the bars leave stands where the twin has it, resume and deck
        self.assertEqual(TABLE["mask"][:4], rep["matched"])  # the example prints the four; the fifth matches nothing
        prof = json.loads((EX / "sample_full_ko.json").read_text(encoding="utf-8"))
        first = prof["roles"][0]["projects"][0]
        first["summary"] = "새로 " + first["summary"]  # one word more early in a paragraph: the words after it move, as a bar of the wrong width moves them
        seeded = self.tmp / "seeded.json"
        seeded.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
        moved = resume.build(str(seeded), str(self.job("cmp_moved_ko")), self.env(True))
        codes = {x["code"] for x in self.layout(twin, moved)["defects"]}
        self.assertTrue(codes & {"blind_moved", "blind_pushed", "blind_pages"}, codes)  # caught

    def test_a_build_made_again_changes_no_page_and_a_changed_period_its_page(self):
        profile = str(EX / "sample_full_ko.json")
        a = resume.build(profile, str(self.job("cmp_base_ko")))
        b = resume.build(profile, str(self.job("cmp_again_ko")))
        self.assertEqual([], BL.compare_pdfs(str(a), str(b))["resume"]["pages"])  # the same words: the same pages, pixel for pixel
        prof = json.loads((EX / "sample_full_ko.json").read_text(encoding="utf-8"))
        prof["roles"][1]["projects"][1]["period"] = "2021.05 ~ 2021.08"  # one month earlier, in the middle of the document
        seeded = self.tmp / "period.json"
        seeded.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
        c = resume.build(str(seeded), str(self.job("cmp_period_ko")))
        found = BL.compare_pdfs(str(a), str(c), str(self.tmp / "changes.png"))["resume"]
        pages = pdftools.text(str(c)).split("\f")
        want = [i for i, t in enumerate(pages, 1) if "2021.05 ~ 2021.08" in t]  # the page that prints the new period
        self.assertTrue(want and set(want) <= set(found["pages"]), (want, found))
        self.assertTrue((self.tmp / "changes.png").is_file())  # with its picture

    def test_the_two_languages_of_the_example_agree_where_the_checks_run(self):
        rep = self.tmp / "langs.json"
        r = resume.sh(["python3", "src/check_parity.py", "langs", "examples/sample_full_ko.json", "examples/job_full_ko.json",
                       "examples/sample_full_en.json", "examples/job_full_en.json", "--report", resume.rel(str(rep))])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)  # no defect: node and the loader run there
        self.assertEqual([], json.loads(rep.read_text(encoding="utf-8"))["defects"])


if __name__ == "__main__":
    unittest.main()
