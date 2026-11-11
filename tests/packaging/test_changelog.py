"""CHANGELOG.md holds each release's notes, which release.yml publishes (.github/release_notes.py): Keep a Changelog's
headings, the newest release is the package's own version, every release has its link, the script prints a section
whole and nothing of the next, and a version with no section stops the release before anything is built.

Run: python3 -m unittest discover -s tests/packaging
"""
import json  # package.json
import re  # the headings and the links
import subprocess  # the script, as release.yml runs it
import sys  # the interpreter
import tempfile  # a sample changelog
import unittest  # the runner
from pathlib import Path  # paths

from pkg_support import ROOT, package_version  # the repository and the one place the version is written

SCRIPT = ROOT / ".github" / "release_notes.py"  # what release.yml runs
TEXT = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")  # the changelog
RELEASES = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$", TEXT, re.M)  # every release, newest first
LINKS = dict(re.findall(r"^\[([^\]]+)\]: (\S+)$", TEXT, re.M))  # the link list at the end


def notes(version: str, path: Path | None = None) -> tuple[int, str, str]:
    """What release.yml's step prints for a tag: the exit code, the notes and the complaint."""
    done = subprocess.run([sys.executable, str(SCRIPT), version, *([str(path)] if path else [])], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8")  # the script on its own
    return done.returncode, done.stdout, done.stderr


class Changelog(unittest.TestCase):
    def test_it_says_its_format_and_its_versions(self):
        self.assertIn("[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)", TEXT)  # how it is written
        self.assertIn("[Semantic Versioning](https://semver.org/)", TEXT)  # how versions are counted
        self.assertIn("Each release's section here is its release notes.", TEXT)  # where the notes come from

    def test_security_comes_first_in_a_release(self):
        # a release's security fixes are the first thing its notes say, never under the long list of what was added
        for v, body in re.findall(r"^## \[([^\]]+)\][^\n]*\n(.*?)(?=^## \[|^\[[^\]\n]+\]: |\Z)", TEXT, re.S | re.M):  # every section
            kinds = re.findall(r"^### (.+)$", body, re.M)  # its kinds of change, in order
            if "Security" in kinds:  # a release with security fixes
                self.assertEqual("Security", kinds[0], v)  # says them first
        self.assertIn("Security\nfixes come first in a release.", TEXT)  # and the file says so at the top

    def test_every_heading_is_unreleased_or_a_dated_release_newest_first(self):
        heads = re.findall(r"^## (.+)$", TEXT, re.M)  # every section
        self.assertEqual("[Unreleased]", heads[0])  # what is not released yet comes first
        for h in heads[1:]:  # the rest are releases
            self.assertRegex(h, r"^\[\d+\.\d+\.\d+\] - \d{4}-\d{2}-\d{2}$")  # a version and its day
        order = [tuple(map(int, v.split("."))) for v, _ in RELEASES]  # as numbers
        self.assertEqual(sorted(order, reverse=True), order)  # newest first

    def test_the_newest_release_is_the_package_s_version(self):
        if RELEASES:  # a release went out: the code says the same number, so a tag cannot leave without its notes
            self.assertEqual(package_version(), RELEASES[0][0])
        else:  # before the first release, its notes wait under Unreleased
            code, out, err = notes(f"v{package_version()}-rc.1")  # a trial run's notes
            self.assertEqual(0, code, err)
            self.assertTrue(out.strip())  # there is something to show

    def test_every_release_has_its_link_and_unreleased_compares_from_the_newest(self):
        for v, _ in RELEASES:  # each release
            self.assertTrue(LINKS.get(v, "").startswith("https://github.com/kanggu12/offerowl/"), (v, LINKS.get(v)))
        want = f"/compare/v{RELEASES[0][0]}...HEAD" if RELEASES else "/commits/main"  # what has changed since
        self.assertTrue(LINKS.get("Unreleased", "").endswith(want), LINKS.get("Unreleased"))

    def test_package_json_names_the_same_version(self):
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))  # the engine's own package
        self.assertEqual(package_version(), pkg["version"])  # one number everywhere


class ReleaseNotes(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()  # a sample changelog
        self.addCleanup(self.dir.cleanup)
        self.sample = Path(self.dir.name) / "CHANGELOG.md"
        self.sample.write_text("# Changelog\n\n## [Unreleased]\n\n- Coming\n\n## [1.1.0] - 2026-12-01\n\n### Added\n\n- One\n\n"
                               "## [1.0.0] - 2026-11-01\n\n- Two\n\n[Unreleased]: https://x/compare/v1.1.0...HEAD\n"
                               "[1.1.0]: https://x/compare/v1.0.0...v1.1.0\n[1.0.0]: https://x/releases/tag/v1.0.0\n", encoding="utf-8")

    def test_a_section_ends_where_the_next_release_or_the_links_begin(self):
        code, out, _ = notes("v1.1.0", self.sample)                                   # a tag's name is taken as its number
        self.assertEqual((0, "### Added\n\n- One"), (code, out.strip()))             # its words, and nothing of the next release
        self.assertEqual("- Two", notes("1.0.0", self.sample)[1].strip())  # the last one stops at the links

    def test_a_pre_release_reads_its_version_or_what_is_not_released(self):
        self.assertEqual("### Added\n\n- One", notes("v1.1.0-rc.1", self.sample)[1].strip())  # its version's notes
        self.assertEqual("- Coming", notes("v1.2.0-rc.1", self.sample)[1].strip())  # none yet: Unreleased

    def test_a_version_with_no_section_or_an_empty_one_stops_the_release(self):
        code, out, err = notes("9.9.9", self.sample)  # never written
        self.assertEqual(1, code)
        self.assertEqual("", out)  # nothing for the release page
        self.assertIn("## [9.9.9]", err)  # and it says what to add
        self.sample.write_text("## [2.0.0] - 2026-12-01\n\n## [1.0.0] - 2026-11-01\n\n- Two\n", encoding="utf-8")  # a heading with no words
        self.assertEqual(1, notes("2.0.0", self.sample)[0])

    def test_release_yml_checks_the_notes_first_and_publishes_them(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")  # the workflow
        self.assertIn('python3 .github/release_notes.py "$TAG" > /dev/null', text)  # the checks of the tagged commit stop a release without notes
        self.assertIn("body_path: release-notes.md", text)  # the release page shows them
        self.assertNotIn("generate_release_notes", text)  # never a list made from commit titles


if __name__ == "__main__":
    unittest.main()
