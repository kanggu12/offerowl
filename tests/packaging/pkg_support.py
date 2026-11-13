"""Shared helpers for the packaging tests: where things are, a clean environment, tools that may be missing, and a copy of
the repository to build from.

No test here calls a model. Tests that need a tool (helm, docker, PyYAML, actionlint, kubeconform) skip when it is missing;
with OFFEROWL_REQUIRE_TOOLS=1 (CI sets it) a missing tool is a failure, so a check cannot disappear unnoticed.
The same holds for the hooks the packaging needs in the panel and the launcher (test_hooks.py): skipped while one is
missing, or failed with OFFEROWL_REQUIRE_HOOKS=1.
"""
import importlib.util  # load a module from a file path
import os  # environment
import pathlib  # paths
import shutil  # find tools, copy trees
import subprocess  # run tools and git
import sys  # the Python that runs the tests
import tempfile  # throwaway folders
import unittest  # skip and fail

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # repository root
SRC = ROOT / "src"  # the engine's flat modules
DEPLOY = ROOT / "deploy"  # what this suite tests
CHART = DEPLOY / "helm" / "offerowl"  # the Helm chart
DOCKER_DIR = DEPLOY / "docker"  # the app image's recipe, compose file and entrypoint
WORKFLOWS = ROOT / ".github" / "workflows"  # the CI and release workflows
REQUIRE_TOOLS = os.environ.get("OFFEROWL_REQUIRE_TOOLS") == "1"  # a missing tool is a failure, not a skip
REQUIRE_HOOKS = os.environ.get("OFFEROWL_REQUIRE_HOOKS") == "1"  # a missing hook in the panel or the launcher (test_hooks.py) is a failure, not a skip

try:  # PyYAML parses the workflows, the chart's output and the compose file
    import yaml
except ImportError:  # CI installs it; a developer may not have it
    yaml = None


def clean_env(**extra: str) -> dict:
    """The current environment without any OFFEROWL_ setting, plus `extra`.
    A developer's own shell settings must not change what a test sees"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # tests leave no .pyc files in the repository
    env["OFFEROWL_LANG"] = "en"  # messages in English unless a test asks for Korean
    env.update(extra)
    return env


def missing(test: unittest.TestCase, what: str) -> None:
    """Skip the test because `what` is not installed; fail instead when OFFEROWL_REQUIRE_TOOLS=1"""
    message = f"{what} is not installed"
    if REQUIRE_TOOLS:
        test.fail(message + " (OFFEROWL_REQUIRE_TOOLS=1)")
    test.skipTest(message)


def hook(test: unittest.TestCase, what: str) -> None:
    """Skip the test because a hook the packaging needs in the panel or the launcher is missing
    (tests/packaging/test_hooks.py lists them); fail instead when OFFEROWL_REQUIRE_HOOKS=1, which CI sets"""
    message = f"hook not applied: {what}"
    if REQUIRE_HOOKS:
        test.fail(message + " (OFFEROWL_REQUIRE_HOOKS=1)")
    test.skipTest(message)


def tool(test: unittest.TestCase, name: str) -> str:
    """The path of a program on PATH, or the test is skipped (failed under OFFEROWL_REQUIRE_TOOLS=1)"""
    path = shutil.which(name)
    if path is None:
        missing(test, name)
    return path


def need_yaml(test: unittest.TestCase) -> None:
    """Skip the test when PyYAML is missing"""
    if yaml is None:
        missing(test, "PyYAML")


def load_module(name: str, path: pathlib.Path):
    """A Python file as a module, without putting its folder on the module path for good"""
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    """Run a command and keep its output as text; a hung command fails the test after two minutes"""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    if kw.get("text"):  # Offerowl's commands print UTF-8 on every system: read it so, not in the system's code page (Windows: cp1252)
        kw.setdefault("encoding", "utf-8")
        kw.setdefault("errors", "replace")
    kw.setdefault("timeout", 120)
    kw.setdefault("env", clean_env())
    return subprocess.run(cmd, **kw)


def repo_files() -> list:
    """The files that would be committed: tracked and untracked ones that are not ignored, as paths relative to the root.
    Without git (an unpacked source archive) every file under the root except the usual generated folders"""
    r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return sorted(f for f in r.stdout.splitlines() if (ROOT / f).is_file())  # a file deleted in the working folder is still listed by git
    skip = {".git", "node_modules", "output", "build", "dist", "__pycache__", ".venv", "venv"}
    found = []
    for folder, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip and not d.endswith(".egg-info")]
        found += [str((pathlib.Path(folder) / n).relative_to(ROOT)) for n in names]
    return sorted(found)


def copy_repo(dest: pathlib.Path) -> pathlib.Path:
    """Copy the committed-or-committable files of the repository into `dest` (modes kept), so a build there leaves no
    build/ or egg-info folder in the real repository"""
    for rel in repo_files():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    return dest


def tmpdir(test: unittest.TestCase) -> pathlib.Path:
    """A throwaway folder that is removed when the test ends"""
    d = tempfile.TemporaryDirectory(prefix="offerowl-pkg-")
    test.addCleanup(d.cleanup)
    return pathlib.Path(d.name)


def package_version() -> str:
    """The version written in deploy/python/offerowl/__init__.py, the one place it is set"""
    import re
    text = (DEPLOY / "python" / "offerowl" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def py() -> str:
    """The Python that runs the tests"""
    return sys.executable
