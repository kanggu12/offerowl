"""Tests of docs/INSTALL.md: each way to install is described with the steps, the requirements, how to update and how to
remove; every file and setting the guide names exists; the version, the file names of the desktop app and the rows of the
doctor agree with the code. Keeping the guide and the files in step is what these tests are for.

Run: python3 -m unittest discover -s tests/packaging -v
"""
import re  # parse the guide
import sys  # module path
import unittest  # the test framework

from pkg_support import ROOT, SRC, package_version, repo_files

sys.path.insert(0, str(SRC))
import doctor  # noqa: E402  its row names

GUIDE = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
SECTIONS = {
    "desktop": "## 1. The desktop app",
    "container": "## 2. A container (Docker Compose)",
    "chart": "## 3. A Kubernetes cluster (Helm)",
    "package": "## 4. The Python package",
    "doctor": "## 5. The doctor",
}


def section(title: str) -> str:
    """The text of one `##` section, up to the next one"""
    start = GUIDE.index(title)
    nxt = GUIDE.find("\n## ", start + 1)
    return GUIDE[start:nxt if nxt != -1 else len(GUIDE)]


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens"""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.lower()).strip())


class StructureTest(unittest.TestCase):
    def test_the_four_ways_and_the_doctor_each_have_a_section(self):
        for title in SECTIONS.values():
            self.assertIn("\n" + title + "\n", GUIDE, title)

    def test_each_way_says_how_to_update_and_how_to_remove(self):
        for key in ("desktop", "container", "chart", "package"):
            text = section(SECTIONS[key])
            self.assertIn("**Update.**", text, key)
            self.assertIn("**Uninstall.**", text, key)

    def test_removing_files_warns_that_it_deletes_the_profile_and_documents(self):
        for key in ("desktop", "container", "chart"):
            self.assertIn("for good", section(SECTIONS[key]), key)

    def test_the_requirements_are_stated(self):
        text = section("## What you need")
        for word in ("System", "Memory", "Disk", "Network", "Docker", "AI"):
            self.assertIn(word, text)

    def test_the_anchors_in_the_table_point_at_headings(self):
        headings = {slug(h) for h in re.findall(r"^#{1,3} (.+)$", GUIDE, re.M)}
        for anchor in re.findall(r"\]\(#([^)]+)\)", GUIDE):
            self.assertIn(anchor, headings, anchor)

    def test_no_placeholder_for_the_publishing_account_is_left(self):
        self.assertNotIn("OWNER", GUIDE)


class FilesTest(unittest.TestCase):
    def test_every_path_the_guide_names_exists(self):
        files = set(repo_files())
        known_dirs = {f.rsplit("/", 1)[0] for f in files if "/" in f}
        for path in set(re.findall(r"`((?:deploy|docs|src|tests|apps|examples|core)/[\w./-]*[\w/])`", GUIDE)):
            self.assertTrue(path in files or path in known_dirs or any(f.startswith(path + "/") for f in files), f"{path} does not exist")

    def test_every_setting_the_guide_names_is_used_somewhere_else_in_the_repository(self):
        wanted = set(re.findall(r"\bOFFEROWL_[A-Z_]+\b", GUIDE))
        self.assertGreater(len(wanted), 12)
        text = ""
        for rel in repo_files():
            if rel.endswith((".py", ".js", ".md", ".yaml", ".yml", ".sh", ".tpl", ".txt", ".toml")) and rel != "docs/INSTALL.md":
                text += (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for name in sorted(wanted):
            self.assertIn(name, text, f"{name} is named in docs/INSTALL.md and nowhere else")

    def test_the_commands_name_the_files_that_run_them(self):
        self.assertIn("docker compose -f deploy/docker/compose.yaml up -d --build", GUIDE)
        self.assertIn("helm install offerowl deploy/helm/offerowl", GUIDE)
        self.assertIn("docker build -f deploy/docker/Dockerfile", GUIDE)
        for rel in ("deploy/docker/compose.yaml", "deploy/helm/offerowl/Chart.yaml", "deploy/docker/Dockerfile"):
            self.assertTrue((ROOT / rel).is_file(), rel)


class AgreementTest(unittest.TestCase):
    def test_the_version_in_the_guide_is_the_packages(self):
        version = package_version()
        for found in re.findall(r"--version (\d+\.\d+\.\d+)|OFFEROWL_APP_TAG=(\d+\.\d+\.\d+)|offerowl-(\d+\.\d+\.\d+)-py3", GUIDE):
            self.assertEqual([x for x in found if x], [version], found)

    def test_the_desktop_files_are_the_ones_the_build_names(self):
        possible = {f"Offerowl-{system}-{machine}{ {'windows': '.exe', 'macos': '.zip'}.get(system, '') }"
                    for system in ("windows", "macos", "linux") for machine in ("x64", "arm64")}
        named = set(re.findall(r"`(Offerowl-[\w.-]+)`", section(SECTIONS["desktop"])))
        self.assertEqual(len(named), 4)
        self.assertLessEqual(named, possible)
        self.assertTrue({n for n in named if n.startswith("Offerowl-windows")} == {"Offerowl-windows-x64.exe"})

    def test_the_rows_of_the_doctor_table_are_the_rows_the_doctor_prints(self):
        table = section(SECTIONS["doctor"])
        rows = set(re.findall(r"^\| ([^|]+?) \|", table, re.M)) - {"Row", "---"}
        rows = {r for r in rows if not r.startswith("---")}
        self.assertEqual(rows, {doctor.MSG["en"]["t_" + key] for key in doctor.CHECKS})

    def test_the_check_names_the_guide_gives_to_only_are_checks_the_doctor_has(self):
        names = set(re.findall(r"--only ([\w,]+)", GUIDE))
        self.assertTrue(names)
        for group in names:
            for name in group.split(","):
                self.assertIn(name, doctor.CHECKS, name)

    def test_the_doctor_checks_the_port_the_guide_names(self):
        self.assertIn("8797", section(SECTIONS["doctor"]))
        self.assertNotIn("8796", section(SECTIONS["doctor"]))  # the interview kit is served by the panel, on its port
        self.assertEqual(doctor.PANEL_PORT, 8797)

    def test_the_data_folders_are_the_ones_of_docs_app(self):
        app = (ROOT / "docs" / "APP.md").read_text(encoding="utf-8")
        for folder in ("%LOCALAPPDATA%\\Offerowl", "~/Library/Application Support/Offerowl", "~/.local/share/offerowl"):
            self.assertIn(folder, GUIDE)
            self.assertIn(folder, app)


if __name__ == "__main__":
    unittest.main()
