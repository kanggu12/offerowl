"""What every way of running Offerowl ships: the version is written once (src/version.py) and agrees everywhere, every
folder of the repository is either shipped or named as development-only, and the app image lets in exactly the shipped
folders and files.

Run: python3 -m unittest discover -s tests/packaging -v
"""
import re  # parse small text files
import unittest  # the test framework

from pkg_support import CHART, DOCKER_DIR, ROOT, need_yaml, package_version, repo_files, yaml

# Top-level folders of the repository that a checkout, the app image and the desktop app run: the engine's tree
SHIPPED = {"apps", "core", "src", "examples", "fonts", "render"}
# Top-level folders that stay in the repository
DEVELOPMENT_ONLY = {".github", "deploy", "docs", "tests", "tools"}
# Files the image carries beside those folders (the launcher and the typesetting libraries' list), and from docs/ the three
# pictures the panel serves and the licenses. The desktop app carries the same (apps/desktop/build.py DATA).
ROOT_FILES = {"offerowl", "package.json", "package-lock.json"}
DOC_FILES = {"LICENSE", "docs/THIRD_PARTY_NOTICES.md", "docs/assets/icon.svg", "docs/assets/logo-light.svg", "docs/assets/logo-dark.svg"}
ENTRY = "deploy/docker/entrypoint.py"  # the one file of deploy/ the image runs


class VersionTest(unittest.TestCase):
    def test_the_version_is_written_once_and_the_chart_and_the_image_agree(self):
        need_yaml(self)
        version = package_version()  # src/version.py
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        chart = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))
        self.assertEqual(chart["version"], version)
        self.assertEqual(str(chart["appVersion"]), version)
        label = re.search(r'org\.opencontainers\.image\.version="([^"]+)"', (DOCKER_DIR / "Dockerfile").read_text(encoding="utf-8"))
        self.assertEqual(label.group(1), version)

    def test_no_other_file_writes_a_version_line(self):
        # src/version.py is the one place: a second __version__ would be a copy that a release forgets
        others = [f for f in repo_files() if f.endswith(".py") and f != "src/version.py"
                  and re.search(r"^__version__\s*=", (ROOT / f).read_text(encoding="utf-8", errors="replace"), re.M)]
        self.assertEqual(others, [])

    def test_the_commands_in_the_docs_name_the_version(self):
        # a release changes these by hand (CONTRIBUTING.md, "Release a version"): one left behind installs the old release
        pattern = r"(?:offerowl-app[:-]|--version |OFFEROWL_APP_TAG=|download/v|--branch v|offerowl-|Release v)(\d+\.\d+\.\d+)"  # Release v: the badge's alt
        seen = 0  # how many it checked, so an empty match cannot pass
        for page in ("README.md", "docs/INSTALL.md", "docs/OFFLINE.md"):
            for found in re.findall(pattern, (ROOT / page).read_text(encoding="utf-8")):
                self.assertEqual(found, package_version(), page)
                seen += 1
        self.assertGreater(seen, 10)  # the README's downloads and clone, and the image, chart and source commands of the two guides

    def test_the_readme_badge_names_the_version(self):
        badge = (ROOT / "docs" / "assets" / "badges" / "release.svg").read_text(encoding="utf-8")  # a fixed badge: GitHub's proxy breaks a live one
        self.assertIn(f'aria-label="release: v{package_version()}"', badge)  # a release changes it with the version
        self.assertIn(f">v{package_version()}<", badge)  # in what it shows, too


class TreeTest(unittest.TestCase):
    def test_every_top_level_folder_is_shipped_or_named_as_development_only(self):
        tops = {f.split("/")[0] for f in repo_files() if "/" in f}
        unknown = tops - SHIPPED - DEVELOPMENT_ONLY
        self.assertFalse(unknown, f"new top-level folder(s) {sorted(unknown)}: add each to the app image "
                                  "(deploy/docker/Dockerfile.dockerignore, a `!folder` line) and to the desktop app (apps/desktop/build.py "
                                  "DATA), or to DEVELOPMENT_ONLY in tests/packaging/test_version_and_tree.py")
        self.assertFalse(SHIPPED - tops, f"{sorted(SHIPPED - tops)} is listed as shipped but does not exist")

    def test_the_image_lets_in_the_engine_and_nothing_else(self):
        ignore = [x.strip() for x in (DOCKER_DIR / "Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines()
                  if x.strip() and not x.startswith("#")]
        self.assertEqual(ignore[0], "*", "the image's build context must start from nothing and let folders in")
        allowed = {x[1:] for x in ignore if x.startswith("!")}  # what each `!` line lets in
        for rel in SHIPPED | ROOT_FILES | DOC_FILES | {ENTRY}:
            self.assertIn(rel, allowed, rel)
        # and nothing else gets into the image: every line that lets something in names a shipped folder or a known file
        self.assertEqual(allowed - (SHIPPED | ROOT_FILES | DOC_FILES | {ENTRY}), set(), "the image's build context lets in something that is not the engine's")

    def test_what_the_image_lets_in_exists(self):
        for line in (DOCKER_DIR / "Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines():
            if line.startswith("!"):
                self.assertTrue((ROOT / line[1:]).exists(), line)


if __name__ == "__main__":
    unittest.main()
