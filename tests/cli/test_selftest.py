"""Tests of the self-test's own logic, with the container calls replaced by stand-ins: the verdict for each way it can go wrong,
the skip rule of --if-changed, and the Docker check. The real self-test (`./offerowl selftest`) is the slow one CI runs.

Run: python3 -m unittest discover -s tests/cli -v
"""
import contextlib  # capture what the self-test prints
import io  # the capture buffer
import json  # the stamp file
import os  # environment
import pathlib  # paths
import subprocess  # a stand-in for the result of a container call
import sys  # module search path
import tempfile  # a throwaway repository root
import unittest  # the test framework
from unittest import mock  # replace the container calls

from support import SRC

sys.path.insert(0, str(SRC))
import resume  # noqa: E402  the module under test


def done(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    """What a finished container call looks like"""
    return subprocess.CompletedProcess([], returncode, stdout, "")


class SelftestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        # The figures the typesetter is expected to have drawn, in the throwaway root.
        figs = self.root / "output" / "_figures"
        figs.mkdir(parents=True)
        for kind in ("timeline", "stack"):
            (figs / f"sample_ko_{kind}.png").write_bytes(b"png")
        self.resume_text = " ".join(resume.WANT) + "\f" * resume.RESUME_PAGES  # the words of the resume, one form feed per page
        self.deck_text = " ".join(resume.DECK_WANT) + "\f" * resume.DECK_SLIDES
        # A planted-defect check that behaves: it fails and says which project is missing.
        self.planted = done(f"x {resume.PLANTED_MARKER}", 1)
        self.ocr = done()

    def run_selftest(self, resume_text=None, deck_text=None, check_rc=0, planted=None, ocr=None, lang="en"):
        """Run resume.selftest() with every container call replaced; returns (exit code, printed text)"""
        resume_text = self.resume_text if resume_text is None else resume_text
        deck_text = self.deck_text if deck_text is None else deck_text

        def fake_sh(cmd, env=None):
            if cmd[0] == "pdftotext":  # the text layer of the resume or the deck
                return done(deck_text if "deck" in cmd[1] else resume_text)
            if "check_documents.py" in cmd[1]:  # the planted-defect check
                self.planted_env = env
                return planted or self.planted
            return ocr or self.ocr  # ocr_selfcheck.py

        out = io.StringIO()
        with mock.patch.object(resume, "ROOT", self.root), \
                mock.patch.object(resume, "build", return_value=self.root / "output" / "sample_ko.pdf"), \
                mock.patch.object(resume, "build_deck", return_value=self.root / "output" / "sample_ko_deck.pdf"), \
                mock.patch.object(resume, "check", return_value=check_rc), \
                mock.patch.object(resume, "sh", side_effect=fake_sh), \
                mock.patch.object(resume, "rel", side_effect=str), \
                mock.patch.dict(os.environ, {"OFFEROWL_LANG": lang}), \
                contextlib.redirect_stdout(out):
            rc = resume.selftest()
        return rc, out.getvalue()

    def test_everything_right_passes_with_the_counts_in_the_line(self):
        rc, text = self.run_selftest()
        self.assertEqual(rc, 0)
        self.assertEqual(text.strip(), "Self-test: example resume 2 pages, deck 6 slides, "
                                       f"{len(resume.WANT) + len(resume.DECK_WANT)} words checked, document check passed, planted defect caught, OCR  PASS")

    def test_the_pass_line_in_korean(self):
        rc, text = self.run_selftest(lang="ko")
        self.assertEqual(rc, 0)
        self.assertTrue(text.strip().startswith("자체 시험: 예제 이력서 2쪽, 덱 6장,"))
        self.assertTrue(text.strip().endswith("OCR  통과"))

    def test_a_wrong_page_count_fails(self):
        rc, text = self.run_selftest(resume_text=" ".join(resume.WANT) + "\f" * 3)
        self.assertEqual(rc, 1)
        self.assertIn("3 pages (expected 2)", text)
        self.assertTrue(text.strip().endswith("FAIL"))

    def test_a_missing_phrase_fails_and_is_named(self):
        rc, text = self.run_selftest(resume_text=" ".join(resume.WANT[1:]) + "\f" * resume.RESUME_PAGES)
        self.assertEqual(rc, 1)
        self.assertIn(resume.WANT[0], text)

    def test_a_missing_figure_fails(self):
        (self.root / "output" / "_figures" / "sample_ko_stack.png").unlink()
        rc, text = self.run_selftest()
        self.assertEqual(rc, 1)
        self.assertIn("sample_ko_stack.png", text)

    def test_a_wrong_slide_count_fails(self):
        rc, text = self.run_selftest(deck_text=" ".join(resume.DECK_WANT) + "\f" * 5)
        self.assertEqual(rc, 1)
        self.assertIn("5 slides (expected 6)", text)

    def test_a_failing_document_check_on_the_example_fails(self):
        rc, text = self.run_selftest(check_rc=1)
        self.assertEqual(rc, 1)
        self.assertIn("did not pass the document check", text)

    def test_a_planted_defect_that_is_not_caught_fails(self):
        rc, text = self.run_selftest(planted=done("all fine", 0))  # the check passed the planted profile: it is blind
        self.assertEqual(rc, 1)
        self.assertIn("missed a planted defect", text)

    def test_a_failure_for_another_reason_does_not_pass_for_the_catch(self):
        # A non-zero exit alone is not enough: a missing style pack also exits non-zero, and must not count.
        rc, _ = self.run_selftest(planted=done(f"{resume.PLANTED_MARKER}\n{resume.NO_STYLE_MARKER}", 1))
        self.assertEqual(rc, 1)
        rc, _ = self.run_selftest(planted=done("crashed with some other message", 1))
        self.assertEqual(rc, 1)

    def test_the_planted_check_runs_in_korean_so_that_its_message_stays_the_same(self):
        self.run_selftest(lang="en")
        self.assertEqual(self.planted_env["OFFEROWL_LANG"], "ko")

    def test_a_failing_ocr_check_fails(self):
        rc, text = self.run_selftest(ocr=done("tesseract is broken", 1))
        self.assertEqual(rc, 1)
        self.assertIn("OCR test failed", text)

    def test_the_planted_profile_is_removed_afterwards(self):
        self.run_selftest()
        self.assertFalse((self.root / "output" / "_selftest_planted.json").exists())


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mark = pathlib.Path(self.tmp.name) / "output" / ".selftest.json"  # the stamp, in a throwaway place
        patches = [mock.patch.object(resume, "SELFTEST_MARK", self.mark),
                   mock.patch.object(resume, "selftest_inputs_hash", return_value="abc123"),
                   mock.patch.object(resume, "docker_missing", return_value=False),
                   mock.patch.dict(os.environ, {"OFFEROWL_LANG": "en"})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def call(self, args, selftest_rc=0):
        """cmd_selftest with the real self-test replaced; returns (exit code, printed text, number of runs)"""
        out = io.StringIO()
        with mock.patch.object(resume, "selftest", return_value=selftest_rc) as run, contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(out):
            rc = resume.cmd_selftest(args)
        return rc, out.getvalue(), run.call_count

    def test_a_pass_writes_the_stamp_and_if_changed_then_skips(self):
        self.assertEqual(self.call([]), (0, "", 1))
        self.assertEqual(json.loads(self.mark.read_text(encoding="utf-8")), {"inputs": "abc123"})
        rc, text, runs = self.call(["--if-changed"])
        self.assertEqual((rc, runs), (0, 0))  # not run again
        self.assertIn("unchanged since the last pass, skipped", text)

    def test_if_changed_runs_when_the_inputs_changed(self):
        self.call([])
        with mock.patch.object(resume, "selftest_inputs_hash", return_value="different"):
            self.assertEqual(self.call(["--if-changed"])[2], 1)

    def test_a_failure_writes_no_stamp(self):
        self.assertEqual(self.call([], selftest_rc=1)[0], 1)
        self.assertFalse(self.mark.exists())  # so that the next run runs again

    def test_without_if_changed_it_always_runs(self):
        self.call([])
        self.assertEqual(self.call([])[2], 1)

    def test_unknown_options_are_a_usage_error(self):
        rc, text, runs = self.call(["--nope"])
        self.assertEqual((rc, runs), (2, 0))
        self.assertIn("Usage: offerowl selftest", text)

    def test_no_docker_gets_a_clear_message_before_any_work(self):
        with mock.patch.object(resume, "docker_missing", return_value=True):
            rc, text, runs = self.call([])
        self.assertEqual((rc, runs), (2, 0))
        self.assertIn("Docker was not found", text)


class InputsHashTest(unittest.TestCase):
    """The stamp that lets --if-changed skip a run must notice every change that could alter the result"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        for rel, text in (("src/a.js", "a"), ("src/sub/b.py", "b"), ("examples/e.json", "{}"), ("fonts/f.ttf", "f"),
                          ("render/Dockerfile", "FROM x"), ("render/run.sh", "#!/bin/sh"), ("package-lock.json", "{}")):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        # No Docker needed: the image id part of the fingerprint is simply empty.
        patches = [mock.patch.object(resume, "ROOT", self.root),
                   mock.patch.object(resume.subprocess, "run", return_value=done(""))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_same_files_give_the_same_hash(self):
        self.assertEqual(resume.selftest_inputs_hash(), resume.selftest_inputs_hash())

    def test_a_change_anywhere_under_src_changes_the_hash(self):
        before = resume.selftest_inputs_hash()
        (self.root / "src" / "sub" / "b.py").write_text("changed", encoding="utf-8")
        self.assertNotEqual(resume.selftest_inputs_hash(), before)

    def test_a_new_file_under_src_changes_the_hash(self):
        # A folder, unlike a list of file names, also covers files added later.
        before = resume.selftest_inputs_hash()
        (self.root / "src" / "new_module.js").write_text("x", encoding="utf-8")
        self.assertNotEqual(resume.selftest_inputs_hash(), before)

    def test_the_example_the_fonts_and_the_recipe_count(self):
        for rel in ("examples/e.json", "fonts/f.ttf", "render/Dockerfile", "render/run.sh", "package-lock.json"):
            before = resume.selftest_inputs_hash()
            (self.root / rel).write_text("changed " + rel, encoding="utf-8")
            self.assertNotEqual(resume.selftest_inputs_hash(), before, rel)

    def test_caches_do_not_change_the_hash(self):
        before = resume.selftest_inputs_hash()
        cache = self.root / "src" / "__pycache__"
        cache.mkdir()
        (cache / "a.cpython-310.pyc").write_bytes(b"\0\1")
        self.assertEqual(resume.selftest_inputs_hash(), before)

    def test_the_image_id_is_part_of_the_hash(self):
        before = resume.selftest_inputs_hash()
        with mock.patch.object(resume.subprocess, "run", return_value=done("sha256:rebuilt-image\n")):
            self.assertNotEqual(resume.selftest_inputs_hash(), before)

    def test_no_docker_is_not_an_error(self):
        with mock.patch.object(resume.subprocess, "run", side_effect=FileNotFoundError):
            self.assertTrue(resume.selftest_inputs_hash())


class BuildCommandTest(unittest.TestCase):
    def test_a_missing_profile_is_reported_before_anything_runs(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"OFFEROWL_LANG": "en"}), contextlib.redirect_stderr(err), \
                mock.patch.object(resume, "build") as build:
            rc = resume.cmd_build(["/nonexistent/profile.json"])
        self.assertEqual(rc, 2)
        self.assertIn("File not found: /nonexistent/profile.json", err.getvalue())
        build.assert_not_called()

    def test_wrong_arguments_print_the_usage(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"OFFEROWL_LANG": "en"}), contextlib.redirect_stderr(err):
            self.assertEqual(resume.cmd_build([]), 2)
            self.assertEqual(resume.cmd_build(["a.json", "b.json", "c.json"]), 2)
        self.assertIn("Usage: offerowl build", err.getvalue())


if __name__ == "__main__":
    unittest.main()
