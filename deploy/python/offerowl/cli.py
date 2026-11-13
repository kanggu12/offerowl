"""The console scripts of the package: `offerowl` and `offerowl-app`.

pyproject.toml installs the repository's engine as data in the folder `engine/` beside this file. The engine is not a
Python package with a public interface: it is the repository itself (the launcher `offerowl`, the flat modules of
src/, the panel in apps/, the typesetting scripts and their data), and it finds its own files from the place it sits
in. So these scripts do not import it; they run the launcher from that folder, exactly as `./offerowl` does in a
checkout, and pass the arguments and the exit code through.

Two commands are started here and not by the launcher:
- `doctor` runs src/doctor.py directly, so it works with every version of the launcher;
- `offerowl-app` runs apps/desktop/app.py (the panel with an icon in the notification area; pip install
  pystray and Pillow add the icon's libraries).

OFFEROWL_ENGINE_ROOT names another engine folder (a checkout); it is how a developer tries a change with the installed
command. An editable install (pip install -e .) needs no setting: the engine is then the checkout the package sits in.
"""
from __future__ import annotations  # hints stay strings, so new hint syntax runs on older Pythons

import os  # the environment setting above
import runpy  # run the launcher and the programs inside this process, as if they had been started directly
import sys  # arguments and the exit code
from pathlib import Path  # paths

HERE = Path(__file__).resolve().parent  # the installed package's folder
MESSAGES = {  # the one message of this file, in both languages; the engine's own messages are in the launcher
    "en": {"missing": "offerowl: the engine folder {path} is missing or incomplete. Install the release's wheel again: pipx install --force <its address> (docs/INSTALL.md, \"4. The Python package\")"},
    "ko": {"missing": "offerowl: 엔진 폴더 {path}이(가) 없거나 덜 설치되었다. 릴리스의 wheel을 다시 설치한다: pipx install --force <그 주소> (docs/INSTALL.md, \"4. The Python package\")"},
}


def engine_root() -> Path:
    """The folder that holds the launcher, src/ and apps/"""
    chosen = os.environ.get("OFFEROWL_ENGINE_ROOT")  # a developer's checkout
    if chosen:
        return Path(chosen).expanduser().resolve()
    packed = HERE / "engine"  # where a built wheel puts the engine
    if packed.is_dir():
        return packed
    return HERE.parents[2]  # an editable install: this file is deploy/python/offerowl/cli.py of a checkout


def say(key: str, **kw) -> str:
    """A message of this file in the person's language: Korean when OFFEROWL_LANG or the locale says so"""
    lang = os.environ.get("OFFEROWL_LANG", "").strip().lower()[:2]  # an explicit choice first
    if lang not in MESSAGES:  # otherwise the first locale variable that is set decides, as the engine does it
        locale = next((os.environ[v] for v in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(v)), "")
        lang = "ko" if locale.lower().startswith("ko") else "en"
    return MESSAGES[lang][key].format(**kw)


def run_file(path: Path, args: list[str]) -> int:
    """Run a Python file as a program with `args`, the way `python path args` would, and return its exit code"""
    sys.argv = [str(path), *args]  # what the program sees as its command line
    try:
        runpy.run_path(str(path), run_name="__main__")  # the file's own folder comes first on the module path, as when python starts a script
    except SystemExit as exit_:  # the programs end with sys.exit(main())
        code = exit_.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)  # a message, as Python itself would print it
        return 1
    return 0  # it returned instead of exiting


def checked_root() -> Path | None:
    """The engine folder, or None (after saying so) when it lacks the launcher"""
    root = engine_root()
    if not (root / "offerowl").is_file() or not (root / "src").is_dir():
        print(say("missing", path=root), file=sys.stderr)
        return None
    return root


def main(argv: list[str] | None = None) -> int:
    """The `offerowl` command"""
    args = list(sys.argv[1:] if argv is None else argv)  # tests pass their own list
    root = checked_root()
    if root is None:
        return 3
    if args[:1] == ["doctor"]:  # run directly, so it works with every version of the launcher
        return run_file(root / "src" / "doctor.py", args[1:])
    return run_file(root / "offerowl", args)  # everything else is the launcher's


def app_main(argv: list[str] | None = None) -> int:
    """The `offerowl-app` command: the panel with an icon in the notification area"""
    args = list(sys.argv[1:] if argv is None else argv)
    root = checked_root()
    if root is None:
        return 3
    app = root / "apps" / "desktop" / "app.py"
    if not app.is_file():
        print(say("missing", path=root), file=sys.stderr)
        return 3
    return run_file(app, args)
