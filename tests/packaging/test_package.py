"""Tests of the Python package (pyproject.toml, deploy/python/offerowl): the version is written once and agrees everywhere,
every folder of the repository is either shipped or named as development-only, the wheel holds exactly the engine's files,
and the wheel installed in a clean virtual environment runs: offerowl --help, doctor, the panel and the app's own check.

Run: python3 -m unittest discover -s tests/packaging -v
"""
import json  # the doctor's JSON
import os  # environment, modes
import pathlib  # paths
import re  # parse small text files
import subprocess  # the panel as a child process
import tempfile  # a folder for the whole wheel class
import time  # wait for the panel
import unittest  # the test framework
import urllib.request  # ask the panel
import venv  # a clean virtual environment
import zipfile  # read the wheel

from pkg_support import CHART, DEPLOY, DOCKER_DIR, ROOT, clean_env, copy_repo, missing, need_yaml, package_version, py, repo_files, run, tmpdir, yaml

try:  # tomllib is in the standard library from Python 3.11
    import tomllib
except ImportError:  # 3.10: the third-party backport, or the copy pip carries
    try:
        import tomli as tomllib
    except ImportError:
        try:
            from pip._vendor import tomli as tomllib
        except ImportError:
            tomllib = None

# Top-level folders of the repository that go into the package and the app image (the engine's tree). docs/assets is the one
# part of docs/ that ships. Keep this list, pyproject.toml's package-data and deploy/docker/Dockerfile.dockerignore equal.
SHIPPED = {"apps", "core", "src", "examples", "fonts", "render"}
# Top-level folders that stay in the repository
DEVELOPMENT_ONLY = {".github", "deploy", "docs", "tests", "tools"}
# Files the package carries beside those folders (the launcher and the typesetting libraries' list), and from docs/ the three
# pictures the panel serves and the licenses. The app image and the desktop app carry the same.
ROOT_FILES = {"offerowl", "package.json", "package-lock.json"}
DOC_FILES = {"LICENSE", "docs/THIRD_PARTY_NOTICES.md", "docs/assets/icon.svg", "docs/assets/logo-light.svg", "docs/assets/logo-dark.svg"}


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def expected_engine_files(files) -> set:
    """The files (paths relative to the root) the wheel's engine folder must hold, by the policy in the comments above"""
    out = set()
    for rel in files:
        top = rel.split("/")[0]
        name = pathlib.PurePosixPath(rel)
        if "__pycache__" in rel or rel.endswith(".pyc") or rel.startswith("examples/interview/out/"):
            continue
        if rel in ROOT_FILES or rel in DOC_FILES:
            out.add(rel)
        elif top == "fonts":
            if name.suffix in (".ttf", ".txt") and len(name.parts) == 2:
                out.add(rel)
        elif top in SHIPPED:
            out.add(rel)
    return out


class VersionTest(unittest.TestCase):
    def test_the_version_is_written_once_and_the_chart_and_the_image_agree(self):
        need_yaml(self)
        version = package_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        chart = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))
        self.assertEqual(chart["version"], version)
        self.assertEqual(str(chart["appVersion"]), version)
        label = re.search(r'org\.opencontainers\.image\.version="([^"]+)"', (DOCKER_DIR / "Dockerfile").read_text(encoding="utf-8"))
        self.assertEqual(label.group(1), version)

    def test_the_commands_in_the_docs_name_the_version(self):
        # a release changes these by hand (CONTRIBUTING.md, "Release a version"): one left behind installs the old release
        pattern = r"(?:offerowl-app[:-]|--version |OFFEROWL_APP_TAG=|download/v|offerowl-|Release v)(\d+\.\d+\.\d+)"  # Release v: the badge's alt
        seen = 0  # how many it checked, so an empty match cannot pass
        for page in ("README.md", "docs/INSTALL.md", "docs/OFFLINE.md"):
            for found in re.findall(pattern, (ROOT / page).read_text(encoding="utf-8")):
                self.assertEqual(found, package_version(), page)
                seen += 1
        self.assertGreater(seen, 10)  # the README's wheel, and the image, chart and wheel commands of the two guides

    def test_the_readme_badge_names_the_version(self):
        badge = (ROOT / "docs" / "assets" / "badges" / "release.svg").read_text(encoding="utf-8")  # a fixed badge: GitHub's proxy breaks a live one
        self.assertIn(f'aria-label="release: v{package_version()}"', badge)  # a release changes it with the version
        self.assertIn(f">v{package_version()}<", badge)  # in what it shows, too

    def test_pyproject_reads_the_version_from_the_package(self):
        if tomllib is None:
            missing(self, "tomllib/tomli")
        data = pyproject()
        self.assertIn("version", data["project"]["dynamic"])
        self.assertNotIn("version", data["project"])
        self.assertEqual(data["tool"]["setuptools"]["dynamic"]["version"], {"attr": "offerowl.__version__"})


class PyprojectTest(unittest.TestCase):
    def setUp(self):
        if tomllib is None:
            missing(self, "tomllib/tomli")
        self.data = pyproject()

    def test_the_project_is_offerowl_with_the_two_commands_and_no_dependencies(self):
        p = self.data["project"]
        self.assertEqual(p["name"], "offerowl")
        self.assertEqual(p["requires-python"], ">=3.10")
        self.assertEqual(p["dependencies"], [])  # the engine and the panel use only the standard library
        self.assertEqual(p["scripts"], {"offerowl": "offerowl.cli:main"})
        self.assertEqual(p["gui-scripts"], {"offerowl-app": "offerowl.cli:app_main"})
        self.assertEqual(sorted(p["optional-dependencies"]), ["checks", "pdf", "tray"])

    def test_the_extras_pin_what_the_desktop_build_pins(self):
        def pin(line: str) -> tuple:  # "name==version; marker" -> ((name, marker), version), the marker's quotes made one kind
            spec, _, marker = line.partition(";")
            name, version = spec.split("==")
            return (name.strip(), marker.strip().replace("'", '"')), version.strip()
        pins = dict(pin(line) for line in (ROOT / "apps" / "desktop" / "requirements-build.txt").read_text(encoding="utf-8").splitlines()
                    if "==" in line and not line.startswith("#"))
        for extra in ("tray", "pdf"):  # the icon, and the PDF reader of a PC with no poppler
            for item in self.data["project"]["optional-dependencies"][extra]:
                key, version = pin(item)
                self.assertEqual(pins[key], version, (extra, key))

    def test_the_pdf_extra_draws_the_pages_too(self):
        # PDFium hands a page over as a Pillow picture (src/pdftools.py render_png): with pypdfium2 alone every preview was unreadable
        self.assertIn("pillow", [item.split("==")[0] for item in self.data["project"]["optional-dependencies"]["pdf"]])

    def test_the_license_is_stated_and_shipped(self):
        self.assertEqual(self.data["project"]["license"], {"text": "MIT"})
        self.assertIn("License :: OSI Approved :: MIT License", self.data["project"]["classifiers"])
        self.assertTrue((ROOT / "LICENSE").is_file())

    def test_no_author_or_address_is_written_into_the_metadata(self):
        for key in ("authors", "maintainers", "urls"):
            self.assertNotIn(key, self.data["project"])

    def test_the_package_files_compile(self):
        for name in ("__init__.py", "__main__.py", "cli.py"):
            compile((DEPLOY / "python" / "offerowl" / name).read_text(encoding="utf-8"), name, "exec")


class TreeTest(unittest.TestCase):
    def test_every_top_level_folder_is_shipped_or_named_as_development_only(self):
        tops = {f.split("/")[0] for f in repo_files() if "/" in f}
        unknown = tops - SHIPPED - DEVELOPMENT_ONLY
        self.assertFalse(unknown, f"new top-level folder(s) {sorted(unknown)}: add each to the package (pyproject.toml package-data "
                                  "and the fonts/docs rules here) and to the app image (deploy/docker/Dockerfile.dockerignore, a `!folder` "
                                  "line), or to DEVELOPMENT_ONLY in tests/packaging/test_package.py")
        self.assertFalse(SHIPPED - tops, f"{sorted(SHIPPED - tops)} is listed as shipped but does not exist")

    def test_the_package_and_the_image_ship_the_same_folders(self):
        if tomllib is None:
            missing(self, "tomllib/tomli")
        patterns = pyproject()["tool"]["setuptools"]["package-data"]["offerowl.engine"]
        ignore = [x.strip() for x in (DOCKER_DIR / "Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines()
                  if x.strip() and not x.startswith("#")]
        self.assertEqual(ignore[0], "*", "the image's build context must start from nothing and let folders in")
        allowed = {x[1:] for x in ignore if x.startswith("!")}
        for folder in SHIPPED:
            self.assertTrue([x for x in patterns if x.startswith(folder + "/")], f"{folder} is not in package-data")
            self.assertIn(folder, allowed, folder)
        for rel in ROOT_FILES | DOC_FILES | {"deploy/docker/entrypoint.py"}:
            self.assertIn(rel, allowed, rel)
        for rel in ROOT_FILES | DOC_FILES:
            self.assertIn(rel, patterns, rel)
        # and nothing else gets into the image: every line that lets something in names a shipped folder or a known file
        known = SHIPPED | ROOT_FILES | DOC_FILES | {"deploy/docker/entrypoint.py"}
        self.assertEqual(allowed - known, set(), "the image's build context lets in something the package does not ship")

    def test_what_the_image_lets_in_exists(self):
        for line in (DOCKER_DIR / "Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines():
            if line.startswith("!"):
                self.assertTrue((ROOT / line[1:]).exists(), line)


class WheelTest(unittest.TestCase):
    """Builds the wheel once from a copy of the repository, installs it in a clean virtual environment, and uses it."""

    @classmethod
    def setUpClass(cls):
        if tomllib is None:
            raise unittest.SkipTest("tomllib/tomli is not installed")
        try:
            import setuptools  # noqa: F401  the build backend, used without a network
        except ImportError:
            if os.environ.get("OFFEROWL_REQUIRE_TOOLS") == "1":
                raise AssertionError("setuptools is not installed (OFFEROWL_REQUIRE_TOOLS=1)")
            raise unittest.SkipTest("setuptools is not installed")
        cls.tmp_object = tempfile.TemporaryDirectory(prefix="offerowl-wheel-")
        cls.tmp = pathlib.Path(cls.tmp_object.name)
        source = copy_repo(cls.tmp / "source")
        cls.files = repo_files()
        # generated and private-looking files that a working folder may hold: the wheel must leave every one out
        for rel in ("src/__pycache__/junk.cpython-310.pyc", "apps/panel/__pycache__/junk.cpython-310.pyc",
                    "examples/interview/out/junk.json", "fonts/.uuid", "src/notes.pyc"):
            (source / rel).parent.mkdir(parents=True, exist_ok=True)
            (source / rel).write_bytes(b"junk")
        built = run([py(), "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-q", "-w", str(cls.tmp / "wheels")], cwd=source, timeout=600)
        assert built.returncode == 0, built.stdout + built.stderr
        cls.wheel = next((cls.tmp / "wheels").glob("offerowl-*.whl"))
        cls.zip = zipfile.ZipFile(cls.wheel)
        cls.names = cls.zip.namelist()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "zip"):
            cls.zip.close()
        if hasattr(cls, "tmp_object"):
            cls.tmp_object.cleanup()

    # --- what is inside

    def test_the_wheel_is_named_for_the_version_and_works_on_every_system(self):
        self.assertEqual(self.wheel.name, f"offerowl-{package_version()}-py3-none-any.whl")

    def test_the_engine_folder_holds_exactly_the_files_of_the_shipped_folders(self):
        prefix = "offerowl/engine/"
        got = {n[len(prefix):] for n in self.names if n.startswith(prefix)}
        want = expected_engine_files(self.files)
        self.assertFalse(want - got, f"missing from the wheel: {sorted(want - got)[:10]}")
        self.assertFalse(got - want, f"in the wheel but not meant to be: {sorted(got - want)[:10]}")

    def test_the_data_files_the_issue_names_are_in_it(self):
        engine = {n[len("offerowl/engine/"):] for n in self.names if n.startswith("offerowl/engine/")}
        for rel in ("src/prompts/cover_draft.md",  # prompts
                    "src/style/default.json", "src/interview/style_default.json",  # styles
                    "fonts/Pretendard-Regular.ttf", "fonts/Pretendard-SemiBold.ttf", "fonts/Pretendard-Bold.ttf",  # fonts
                    "src/interview/fonts/PretendardVariable.woff2",  # the interview view's font
                    "apps/panel/static/index.html", "docs/assets/icon.svg",  # page assets
                    "src/themes.json", "src/portfolio/deck.js", "src/interview/page.html",  # colour sets, the deck, the interview page
                    "examples/sample_ko.json",  # the example
                    "package-lock.json", "render/run.sh", "render/Dockerfile", "offerowl", "src/doctor.py"):
            self.assertIn(rel, engine, rel)

    def test_nothing_generated_or_private_is_in_it(self):
        for name in self.names:
            for bad in ("__pycache__", ".pyc", "node_modules/", "/output/", "/tests/", "/.git/", "examples/interview/out/", ".uuid"):
                self.assertNotIn(bad, name, name)

    def test_the_scripts_keep_their_executable_bit(self):
        for rel in ("offerowl/engine/render/run.sh", "offerowl/engine/offerowl"):
            self.assertTrue(self.zip.getinfo(rel).external_attr >> 16 & 0o111, rel)  # run.sh is started as a program by the engine

    def test_the_entry_points_are_the_two_commands(self):
        text = self.zip.read(f"offerowl-{package_version()}.dist-info/entry_points.txt").decode()
        self.assertIn("offerowl = offerowl.cli:main", text)
        self.assertIn("[gui_scripts]", text)
        self.assertIn("offerowl-app = offerowl.cli:app_main", text)

    def test_the_metadata_names_the_python_and_the_extras(self):
        meta = self.zip.read(f"offerowl-{package_version()}.dist-info/METADATA").decode()
        self.assertIn("Requires-Python: >=3.10", meta)
        self.assertIn("Provides-Extra: tray", meta)
        self.assertIn("Provides-Extra: checks", meta)
        for line in meta.splitlines():  # the package has no dependency of its own: only the extras name any
            if line.startswith("Requires-Dist:"):
                self.assertIn("extra ==", line)

    # --- installed in a clean virtual environment, then used

    def test_the_installed_package_runs(self):
        home = tmpdir(self)
        env_dir = home / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
        bindir = env_dir / ("Scripts" if os.name == "nt" else "bin")
        suffix = ".exe" if os.name == "nt" else ""
        python = bindir / f"python{suffix}"
        installed = run([str(python), "-m", "pip", "install", "--no-deps", "--no-index", "-q", str(self.wheel)])
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        env = clean_env(OFFEROWL_DATA_DIR=str(home / "data"))
        offerowl = str(bindir / f"offerowl{suffix}")

        helped = run([offerowl, "--help"], env=env, cwd=home)  # started from another folder: nothing may depend on the current one
        self.assertEqual(helped.returncode, 0, helped.stderr)
        for word in ("Usage: offerowl", "init", "build", "panel", "interview"):
            self.assertIn(word, helped.stdout)

        self.assertEqual(run([str(python), "-m", "offerowl", "--help"], env=env, cwd=home).returncode, 0)  # python -m offerowl

        llm = run([offerowl, "llm"], env=env, cwd=home)  # a launcher command that imports the engine's modules
        self.assertEqual(llm.returncode, 0, llm.stderr)
        self.assertIn("claude-code", llm.stdout)

        doctor = run([offerowl, "doctor", "--json"], env=env, cwd=home)  # 0, or 1 when the libraries or Docker are missing
        self.assertIn(doctor.returncode, (0, 1), doctor.stdout + doctor.stderr)
        report = json.loads(doctor.stdout)
        self.assertEqual({c["key"] for c in report["checks"]}, {"python", "data", "engine", "libs", "render", "browser", "ai", "fonts", "ports", "poppler"})
        self.assertEqual(report["version"], package_version())
        by_key = {c["key"]: c for c in report["checks"]}
        self.assertEqual(by_key["fonts"]["status"], "ok", by_key["fonts"])  # the fonts came with the wheel
        self.assertEqual(by_key["engine"]["status"], "ok", by_key["engine"])  # the engine folder is writable in a virtual environment
        if by_key["libs"]["status"] != "ok":  # the first run: the libraries are not there, and the fix names the installed run.sh
            self.assertIn(os.path.join("render", "run.sh") + " npm ci", by_key["libs"]["fix"])  # the installed starter, in render/

        broken = run([offerowl, "--help"], env=dict(env, OFFEROWL_ENGINE_ROOT=str(home / "nowhere")), cwd=home)
        self.assertEqual(broken.returncode, 3)
        self.assertIn("engine folder", broken.stderr)

        checked = run([str(bindir / f"offerowl-app{suffix}"), "--check"], env=env, cwd=home, timeout=240)  # the panel + engine smoke test
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

        self.panel_answers(offerowl, env, home)

    def panel_answers(self, offerowl: str, env: dict, home: pathlib.Path) -> None:
        """`offerowl panel` starts, answers /health on its own port, and stops when told to"""
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        child = subprocess.Popen([offerowl, "panel", "--port", str(port)], env=env, cwd=home, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(child.kill)
        answer = None
        for _ in range(60):
            if child.poll() is not None:
                break
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    answer = json.loads(r.read())
                break
            except OSError:
                time.sleep(0.5)
        child.terminate()
        output = child.communicate(timeout=30)[0]
        self.assertTrue(answer and answer.get("ok") is True and answer.get("app") == "offerowl", f"{answer} {output}")  # other fields (the API version) may be added


if __name__ == "__main__":
    unittest.main()
