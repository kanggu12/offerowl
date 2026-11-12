"""Tests that the lint pass (tests/cli/lint.py) really fails on a broken file and passes on a clean tree.
It runs a copy of lint.py inside a small temporary tree, so the verdict does not depend on the real repository.

Run: python3 -m unittest discover -s tests/cli -v
"""
import pathlib  # paths
import shutil  # copy lint.py, find tools
import subprocess  # run the copy
import sys  # the Python that runs the tests
import tempfile  # a throwaway tree
import unittest  # the test framework

from support import ROOT, clean_env


class LintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "tests" / "cli").mkdir(parents=True)
        # lint.py finds the repository root from its own location, so this copy lints the temporary tree.
        shutil.copy(ROOT / "tests" / "cli" / "lint.py", self.root / "tests" / "cli" / "lint.py")

    def write(self, rel: str, text: str) -> None:
        """Create a file in the temporary tree"""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def lint(self) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(self.root / "tests" / "cli" / "lint.py")], capture_output=True, text=True,
                              env=clean_env(), timeout=120)

    def line(self, r: subprocess.CompletedProcess, step: str) -> str:
        """The result line of one step"""
        return next(x for x in r.stdout.splitlines() if x.startswith(step))

    def test_a_clean_tree_passes(self):
        self.write("a.py", "print('ok')\n")
        self.write("a.json", '{"a": 1}\n')
        self.write("a.sh", "#!/bin/sh\necho ok\n")
        r = self.lint()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("lint: 5 steps, 0 failed", r.stdout)

    def test_a_comment_left_open_in_a_stylesheet_fails(self):  # it would swallow the rules under it, silently
        self.write("a.css", ".a { color: red; }   /* a note left open\n.b { color: blue; } /* the next note */\n")
        r = self.lint()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL", self.line(r, "css"))
        self.assertIn("a.css:1", r.stdout)  # where the comment opens
        self.write("a.css", ".a { color: red; }   /* a note */\n/* a note on two\n   lines */\n.b { color: blue; }\n")
        self.assertIn("OK", self.line(self.lint(), "css"))  # closed comments, long ones too, pass

    def test_a_python_syntax_error_fails(self):
        self.write("bad.py", "def broken(:\n    pass\n")
        r = self.lint()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL", self.line(r, "python"))
        self.assertIn("bad.py", r.stdout)

    def test_an_undefined_name_fails_when_flake8_is_installed(self):
        if subprocess.run([sys.executable, "-m", "flake8", "--version"], capture_output=True).returncode != 0:
            self.skipTest("flake8 is not installed")
        self.write("undefined.py", "print(a_name_that_does_not_exist)\n")
        r = self.lint()
        self.assertEqual(r.returncode, 1)
        self.assertIn("F821", r.stdout)

    def test_style_findings_do_not_fail(self):
        # The pass is for bugs. An unused import is style and must not break the build.
        self.write("style.py", "import os\nprint('x')\n")
        self.assertEqual(self.lint().returncode, 0)

    def test_broken_json_fails(self):
        self.write("bad.json", '{"a": ')
        r = self.lint()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL", self.line(r, "json"))

    def test_broken_javascript_fails_when_node_is_installed(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        self.write("bad.js", "function (\n")
        r = self.lint()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL", self.line(r, "node"))

    def test_broken_shell_fails(self):
        self.write("bad.sh", "#!/bin/sh\nif then\n")
        r = self.lint()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL", self.line(r, "shell"))

    def test_generated_folders_are_skipped(self):
        # node_modules and output hold files we do not own; a broken file there must not fail the pass.
        self.write("node_modules/pkg/bad.js", "function (\n")
        self.write("output/bad.json", '{"a": ')
        self.write("output/bad.py", "def broken(:\n")
        self.assertEqual(self.lint().returncode, 0)


if __name__ == "__main__":
    unittest.main()
