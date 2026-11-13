"""Shared helpers for the CLI tests: where things are, a clean environment, and a way to run the launcher.

No test here calls a model or needs Docker. Backends are stand-ins or `none`.
"""
import os  # environment
import pathlib  # paths
import subprocess  # run the launcher as a user would
import sys  # the Python that runs the tests also runs the launcher

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # repository root
LAUNCHER = ROOT / "offerowl"  # the command under test
SRC = ROOT / "src"  # the modules the launcher imports


def clean_env(**extra: str) -> dict:
    """The current environment without any OFFEROWL_ setting, plus `extra`.
    A developer's own shell settings must not change what a test sees"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # tests leave no .pyc files in the repository
    env.update(extra)
    return env


def run_launcher(*args: str, env: dict | None = None, cwd: pathlib.Path | None = None,
                 root: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    """Run `offerowl <args>` as a separate process. `root` lets a test point at a copy of the repository (a few files)"""
    launcher = (root or ROOT) / "offerowl"
    return subprocess.run([sys.executable, str(launcher), *args], capture_output=True, text=True, encoding="utf-8",  # the launcher prints UTF-8
                          env=env if env is not None else clean_env(), cwd=cwd, timeout=120)
