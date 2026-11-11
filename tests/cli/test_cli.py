"""Smoke tests of the `offerowl` command: help, the llm listing, init (dry and real), and the separate programs.

Run: python3 -m unittest discover -s tests/cli -v
"""
import json  # read job.json
import os  # file modes
import pathlib  # paths
import re  # find command names at the start of help lines
import shutil  # copy a few repository files into a temp tree
import subprocess  # run the launcher through its shebang once
import tempfile  # throwaway folders
import unittest  # the test framework (standard library, nothing to install)

from support import LAUNCHER, ROOT, clean_env, run_launcher

COMMANDS = ["init", "ingest", "draft", "build", "cover", "interview", "panel", "open", "api", "mcp", "import", "export", "selftest", "llm", "doctor"]  # what --help must list


def help_names(text: str) -> list:
    """The command names listed in a help text: the first word of every two-space-indented line of the command list"""
    return re.findall(r"^  ([a-z]+) ", text, re.M)


class HelpTest(unittest.TestCase):
    def test_launcher_is_executable_and_runs_through_its_shebang(self):
        # `./offerowl` is the documented way to start it, so the file mode and the first line must be right.
        self.assertTrue(os.access(LAUNCHER, os.X_OK), "offerowl must be executable")
        self.assertEqual(LAUNCHER.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env python3")
        r = subprocess.run([str(LAUNCHER), "--help"], capture_output=True, text=True, env=clean_env(OFFEROWL_LANG="en"), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_help_lists_every_command_in_english(self):
        r = run_launcher("--help", env=clean_env(OFFEROWL_LANG="en"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(help_names(r.stdout), COMMANDS)  # all nine, in the order of a first application
        self.assertIn("Usage: offerowl <command>", r.stdout)
        self.assertIn("OFFEROWL_LLM", r.stdout)  # the settings are named right in the help

    def test_help_lists_every_command_in_korean(self):
        r = run_launcher("--help", env=clean_env(OFFEROWL_LANG="ko"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(help_names(r.stdout), COMMANDS)
        self.assertIn("쓰는 법: offerowl", r.stdout)

    def test_language_follows_the_locale_when_offerowl_lang_is_not_set(self):
        # LANG=ko_KR.UTF-8 reads as Korean; C.UTF-8 and anything else as English.
        ko = run_launcher("--help", env=clean_env(LANG="ko_KR.UTF-8", LC_ALL="", LC_MESSAGES=""))
        en = run_launcher("--help", env=clean_env(LANG="C.UTF-8", LC_ALL="", LC_MESSAGES=""))
        self.assertIn("쓰는 법", ko.stdout)
        self.assertIn("Usage", en.stdout)

    def test_no_arguments_prints_the_same_help(self):
        env = clean_env(OFFEROWL_LANG="en")
        self.assertEqual(run_launcher(env=env).stdout, run_launcher("--help", env=env).stdout)

    def test_help_for_one_command(self):
        for form in (["init", "--help"], ["help", "init"]):  # both spellings
            r = run_launcher(*form, env=clean_env(OFFEROWL_LANG="en"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Usage: offerowl init <folder> [--force] [--dry-run]", r.stdout)

    def test_each_command_s_help_names_the_launcher(self):
        for cmd, usage in (("ingest", "offerowl ingest"), ("draft", "offerowl draft write"), ("import", "offerowl import"),
                           ("export", "offerowl export"), ("cover", "offerowl cover")):
            r = run_launcher(cmd, "--help", env=clean_env(OFFEROWL_LANG="en"))
            self.assertIn(usage, r.stdout, cmd)  # the way a person runs it
            self.assertNotIn("python3 src/", r.stdout, cmd)  # never a script's path to type
            self.assertNotRegex(r.stdout, r"usage: \S+\.py", cmd)  # nor a script's name as the command

    def test_an_unknown_command_gets_a_suggestion_and_exit_code_2(self):
        r = run_launcher("biuld", env=clean_env(OFFEROWL_LANG="en"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("`build`", r.stderr)  # did you mean


class LlmCommandTest(unittest.TestCase):
    def rows(self, text: str) -> list:
        """The four backend rows of the llm listing: (marked, name)"""
        return re.findall(r"^([* ]) (claude-code|codex|openai-compat|none) ", text, re.M)

    def test_llm_lists_the_four_backends_and_marks_the_one_in_use(self):
        # OFFEROWL_LLM=none makes the answer independent of what is installed on this machine.
        r = run_launcher("llm", env=clean_env(OFFEROWL_LLM="none", OFFEROWL_LANG="en"))
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self.rows(r.stdout)
        self.assertEqual([name for _, name in rows], ["claude-code", "codex", "openai-compat", "none"])
        self.assertEqual([name for mark, name in rows if mark == "*"], ["none"])  # exactly one mark, on none
        self.assertIn("In use: none (set by OFFEROWL_LLM)", r.stdout)

    def test_llm_without_any_setting_still_names_a_backend(self):
        # Whatever this machine has, one row is marked and the reason is the default order.
        r = run_launcher("llm", env=clean_env(OFFEROWL_LANG="en"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([m for m, _ in self.rows(r.stdout) if m == "*"]), 1)
        self.assertIn("default order", r.stdout)

    def test_llm_in_korean(self):
        r = run_launcher("llm", env=clean_env(OFFEROWL_LLM="none", OFFEROWL_LANG="ko"))
        self.assertIn("쓰는 것: none (OFFEROWL_LLM 설정)", r.stdout)


class InitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()  # one throwaway folder per test
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name) / "workspace"  # does not exist yet: init must create it
        self.env = clean_env(OFFEROWL_LANG="en")

    def test_dry_run_lists_the_files_and_writes_nothing(self):
        r = run_launcher("init", str(self.dir), "--dry-run", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nothing was written", r.stdout)
        self.assertIn("profile.json", r.stdout)
        self.assertIn("job.json", r.stdout)
        self.assertFalse(self.dir.exists(), "a dry run must not even create the folder")

    def test_init_copies_the_example_and_writes_settings(self):
        r = run_launcher("init", str(self.dir), env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        # The profile is the example, byte for byte; the settings parse and name an output.
        self.assertEqual((self.dir / "profile.json").read_bytes(), (ROOT / "examples" / "sample_ko.json").read_bytes())
        job = json.loads((self.dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["out"], "my_resume")
        self.assertIn(job["lang"], ("ko", "en"))
        self.assertIn("offerowl build", r.stdout)  # the next step is named

    def test_init_keeps_existing_files_unless_forced(self):
        run_launcher("init", str(self.dir), env=self.env)
        mine = self.dir / "profile.json"
        mine.write_text('{"edited": true}', encoding="utf-8")  # the user's work
        r = run_launcher("init", str(self.dir), env=self.env)
        self.assertEqual(r.returncode, 1)  # refused
        self.assertIn("--force", r.stderr)
        self.assertEqual(mine.read_text(encoding="utf-8"), '{"edited": true}')  # untouched
        r = run_launcher("init", str(self.dir), "--force", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(mine.read_bytes(), (ROOT / "examples" / "sample_ko.json").read_bytes())  # restored on request

    def test_init_without_a_folder_is_a_usage_error(self):
        r = run_launcher("init", env=self.env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Usage: offerowl init", r.stderr)


class LaterPhaseProgramsTest(unittest.TestCase):
    """cover, interview and panel are separate programs that the launcher starts. These tests use a small copy of the
    repository, so the result does not depend on which of those programs exist in the real one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        # The launcher and the two modules it imports: enough to run every command that does not need the example.
        shutil.copy(LAUNCHER, self.root / "offerowl")
        (self.root / "src").mkdir()
        for name in ("resume.py", "llm.py"):
            shutil.copy(ROOT / "src" / name, self.root / "src" / name)

    def write(self, rel: str, text: str) -> None:
        """Create a stand-in program in the copy"""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_missing_programs_say_not_installed(self):
        for name, path in (("cover", "src/cover.py"), ("interview", "src/interview/cli.py"), ("panel", "apps/panel/server.py")):
            for lang, words in (("en", "not installed"), ("ko", "설치되지 않았다")):
                r = run_launcher(name, env=clean_env(OFFEROWL_LANG=lang), root=self.root)
                self.assertEqual(r.returncode, 3, (name, r.stderr))  # the code for "not there yet"
                self.assertIn(words, r.stderr)
                self.assertIn(path, r.stderr)  # says which file is missing

    def test_help_marks_the_missing_programs(self):
        r = run_launcher("--help", env=clean_env(OFFEROWL_LANG="en"), root=self.root)
        marked = [line.split()[0] for line in r.stdout.splitlines() if "(not installed)" in line]
        self.assertEqual(marked, ["cover", "interview", "panel", "api", "mcp", "doctor"])  # the copy holds none of the component programs

    def test_installed_programs_get_their_arguments_cwd_and_exit_code(self):
        # A plain script: arguments arrive as typed, the working folder is the user's, the exit code comes back.
        self.write("src/cover.py", "import json, os, sys\nprint(json.dumps([sys.argv[1:], os.getcwd()]))\nsys.exit(7)\n")
        here = self.root / "elsewhere"
        here.mkdir()
        r = run_launcher("cover", "jobs/x", "--flag", env=clean_env(), cwd=here, root=self.root)
        self.assertEqual(r.returncode, 7)
        args, cwd = json.loads(r.stdout)
        self.assertEqual(args, ["jobs/x", "--flag"])
        self.assertEqual(pathlib.Path(cwd).resolve(), here.resolve())  # not the repository root

    def test_a_package_module_runs_as_a_module_so_relative_imports_work(self):
        self.write("apps/panel/__init__.py", "")
        self.write("apps/panel/helper.py", "VALUE = 'imported'\n")
        self.write("apps/panel/server.py", "from . import helper\nprint('panel', helper.VALUE)\n")
        r = run_launcher("panel", env=clean_env(), root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("panel imported", r.stdout)

    def test_a_script_can_import_the_modules_in_src(self):
        # The interview program imports `llm`; src/ must be on its module path wherever the script itself sits.
        self.write("src/interview/cli.py", "import llm\nprint('lang', llm.lang())\n")
        r = run_launcher("interview", env=clean_env(OFFEROWL_LANG="ko"), root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lang ko", r.stdout)


if __name__ == "__main__":
    unittest.main()
