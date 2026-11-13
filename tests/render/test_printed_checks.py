#!/usr/bin/env python3
"""The printed-word rules and the line checks on a real typeset resume: the fictional example passes them (its one-word last
lines are notes to polish, never a reason to keep it home), and an example with seeded defects fails on each of them. The
example is typeset in the render container, as the panel's builds are.
  python3 -m unittest tests/render/test_printed_checks.py -v
"""
import json  # profiles, packs and reports
import os  # the checks' language
import pathlib  # paths
import shutil  # the seeded copy's folder
import sys  # the import path
import tempfile  # a folder for the seeded copy
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT / "src", ROOT / "tests" / "render"):  # the engine, the helpers beside this file
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from test_blind_figures import render_image  # noqa: E402  is the render container's image here
import resume  # noqa: E402  the typesetting

# every rule for printed words on, the line checks as defects, and a name that never goes inside a highlight
STRICT = {"banned_chars": "", "banned_patterns": [], "printed": {"comma_after_endings": True, "instead": True, "not_a_but_b": 0, "latin_and": True,
                                                                 "repeated_words": True, "lines": "fail", "highlight_names": ["KOTRA"]}}


def check(profile: pathlib.Path, pdf: pathlib.Path, style: str) -> tuple[int, dict]:
    """src/check_documents.py on a resume as the panel runs it (in the container, with --report): its exit code and report."""
    rep = ROOT / "output" / f"{pdf.stem}.test.checks.json"
    rep.unlink(missing_ok=True)
    r = resume.sh(["python3", "src/check_documents.py", resume.rel(str(profile)), resume.rel(str(pdf)), "--style", style, "--max-pages", "3",
                   "--report", resume.rel(str(rep))], dict(os.environ, OFFEROWL_LANG="ko"))
    got = json.loads(rep.read_text(encoding="utf-8")) if rep.is_file() else {}
    rep.unlink(missing_ok=True)
    return r.returncode, got


@unittest.skipUnless(os.environ.get("OFFEROWL_TEST_RENDER") != "0" and render_image(), "the render container's image is not built here (render/run.sh builds it)")
@unittest.skipUnless((ROOT / "node_modules" / "docx").is_dir(), "the typesetting libraries are not installed (render/run.sh npm ci)")
class PrintedChecksTests(unittest.TestCase):
    """The example passes; an example with seeded defects fails on each new rule."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="printed-", dir=str(ROOT / "output")))  # where the container sees it
        cls.pack = cls.tmp / "strict.json"
        cls.pack.write_text(json.dumps(STRICT, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_example_passes_with_notes_to_polish_only(self):
        pdf = resume.build(str(resume.EXAMPLE))  # typeset in the container
        side = json.loads(pdf.with_suffix(".highlights.json").read_text(encoding="utf-8"))  # what the typesetting set
        self.assertTrue(side["highlights"] and side["paras"], side)  # the line checks have something to measure
        code, rep = check(resume.EXAMPLE, pdf, "default")
        self.assertEqual(0, code, rep)  # passed
        self.assertEqual([], rep.get("defects"), rep)
        self.assertTrue({x["code"] for x in rep.get("polish") or []} <= {"last_word"}, rep)  # a one-word last line is a note

    def test_seeded_defects_fail(self):
        prof = json.loads(resume.EXAMPLE.read_text(encoding="utf-8"))
        prof["summary"]["intro"] = {"ko": prof["summary"]["intro"]["ko"] + " ==KOTRA 와 함께 수출 상담 창구를 처음 열어 대기 시간을 줄였다=="}   # a name in a long highlight
        first = prof["roles"][0]["projects"][0]
        first["summary"] = first["summary"] + " TODO 숫자 넣기."  # an editing note left in
        seeded = self.tmp / "seeded.json"
        seeded.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
        pdf = resume.build(str(seeded))
        code, rep = check(seeded, pdf, resume.rel(str(self.pack)))
        found = {x["code"] for x in rep.get("defects") or []}
        self.assertEqual(1, code, rep)  # failed
        for want in ("editing_note", "hl_name", "hl_size", "comma_ending", "latin_and"):
            self.assertIn(want, found, rep)
        code, rep = check(seeded, pdf, "default")  # the default pack still names the note left in
        self.assertIn("editing_note", {x["code"] for x in rep.get("defects") or []}, rep)


if __name__ == "__main__":
    unittest.main()
