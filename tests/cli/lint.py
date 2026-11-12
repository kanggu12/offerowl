#!/usr/bin/env python3
"""The syntax and lint pass. CI runs it, and so can you:

    python3 tests/cli/lint.py                  skip a step whose tool is not installed, and say so
    python3 tests/cli/lint.py --require-tools  fail instead (CI uses this, so a missing tool cannot hide)

It reads the files on disk, so no git is needed, and it skips node_modules, output, build, .git and caches.
One line per step. The exit code is 1 when any step fails.

  python  every .py file and the offerowl launcher parse; flake8, when installed, finds no syntax error, undefined name or
          wrong comparison (E9, F63, F7, F82). Those are the findings that are bugs and not matters of style
  json    every .json file parses
  node    `node --check` on every .js file
  shell   `bash -n` on every .sh file, and shellcheck on them
  css     every .css file's comments close, and none holds a rule: a comment left open after a rule runs over the rules
          under it, and the page loses them without a word (no browser or test says so)
"""
import ast  # parse Python without running it
import json  # parse JSON files
import os  # walk the tree, find executables
import pathlib  # paths
import shutil  # is a tool installed
import subprocess  # run the tools
import sys  # arguments, exit code, this Python

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # repository root
SKIP_DIRS = {".git", "node_modules", "output", "build", "__pycache__", ".venv", "venv"}  # generated or not ours
FLAKE8_SELECT = "E9,F63,F7,F82"  # syntax errors, wrong comparisons, syntax errors in doctests and undefined names
REQUIRE_TOOLS = "--require-tools" in sys.argv  # a missing tool is a failure, not a skip


def walk() -> list:
    """Every file under the root, except the skipped folders, as sorted paths"""
    found = []
    for folder, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)  # prune in place so os.walk never enters them
        found += [pathlib.Path(folder) / n for n in sorted(names)]
    return found


def tool_missing(step: str, tool: str) -> tuple:
    """The result of a step that cannot run because `tool` is not installed"""
    return (not REQUIRE_TOOLS, f"{tool} is not installed" + ("" if not REQUIRE_TOOLS else " (required)"))


def check_python(files: list) -> tuple:
    """(ok, detail) for the Python files and the launcher"""
    py = [f for f in files if f.suffix == ".py" or f == ROOT / "offerowl"]
    for f in py:  # a syntax error here is the cheapest bug to catch
        try:
            ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as e:
            return False, f"{f.relative_to(ROOT)}:{e.lineno}: {e.msg}"
    detail = f"{len(py)} files"
    r = subprocess.run([sys.executable, "-m", "flake8", "--version"], capture_output=True, text=True)
    if r.returncode != 0:  # flake8 is not installed for this Python
        ok, why = tool_missing("python", "flake8")
        return ok, f"{detail}; flake8 skipped: {why}"
    r = subprocess.run([sys.executable, "-m", "flake8", f"--select={FLAKE8_SELECT}", *map(str, py)], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        return False, "flake8:\n" + r.stdout.strip()
    return True, f"{detail}; flake8 {FLAKE8_SELECT} clean"


def check_json(files: list) -> tuple:
    """(ok, detail) for the JSON files"""
    js = [f for f in files if f.suffix == ".json"]
    for f in js:
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:  # json.JSONDecodeError and UnicodeDecodeError are both ValueError
            return False, f"{f.relative_to(ROOT)}: {e}"
    return True, f"{len(js)} files"


def check_node(files: list) -> tuple:
    """(ok, detail) for the JavaScript files: parse only, nothing runs"""
    js = [f for f in files if f.suffix == ".js"]
    if not shutil.which("node"):
        ok, why = tool_missing("node", "node")
        return ok, f"{len(js)} files; {why}"
    for f in js:
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        if r.returncode != 0:
            return False, f"{f.relative_to(ROOT)}:\n" + r.stderr.strip()
    return True, f"{len(js)} files"


def check_shell(files: list) -> tuple:
    """(ok, detail) for the shell scripts"""
    sh = [f for f in files if f.suffix == ".sh"]
    if not sh:  # shellcheck with no file names prints its usage and fails
        return True, "0 files"
    for f in sh:
        r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)  # parse only
        if r.returncode != 0:
            return False, f"{f.relative_to(ROOT)}:\n" + r.stderr.strip()
    if not shutil.which("shellcheck"):
        ok, why = tool_missing("shell", "shellcheck")
        return ok, f"{len(sh)} files; bash -n only: {why}"
    r = subprocess.run(["shellcheck", *map(str, sh)], capture_output=True, text=True)
    if r.returncode != 0:
        return False, "shellcheck:\n" + r.stdout.strip()
    return True, f"{len(sh)} files; shellcheck clean"


def check_css(files: list) -> tuple:
    """(ok, detail) for the stylesheets: each /* has its */, no */ stands alone, and no comment holds a brace (the rules it
    would have swallowed)"""
    css = [f for f in files if f.suffix == ".css"]
    for f in css:
        text = f.read_text(encoding="utf-8")
        at, outside = 0, []  # where the scan is, and the text between the comments
        while True:
            start = text.find("/*", at)  # the next comment
            if start < 0:  # none left
                outside.append(text[at:])
                break
            end = text.find("*/", start + 2)  # its close
            line = text.count("\n", 0, start) + 1  # where it opens, for the message
            if end < 0:  # never closed: everything after it is lost
                return False, f"{f.relative_to(ROOT)}:{line}: a comment is never closed"
            if "{" in text[start + 2:end] or "}" in text[start + 2:end]:  # a rule inside: one left open further up swallowed it
                return False, f"{f.relative_to(ROOT)}:{line}: a comment holds a rule (a comment left open swallows the rules after it)"
            outside.append(text[at:start])
            at = end + 2
        if any("*/" in part for part in outside):  # a close with no comment open
            return False, f"{f.relative_to(ROOT)}: a */ closes no comment"
    return True, f"{len(css)} files"


def main() -> int:
    files = walk()
    steps = [("python", check_python), ("json", check_json), ("node", check_node), ("shell", check_shell), ("css", check_css)]
    failed = 0
    for name, step in steps:
        ok, detail = step(files)
        failed += not ok
        print(f"{name:7}{'OK  ' if ok else 'FAIL'} {detail}")
    print(f"lint: {len(steps)} steps, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
