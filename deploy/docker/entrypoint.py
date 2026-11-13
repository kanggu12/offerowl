#!/usr/bin/env python3
"""The app container's entrypoint (deploy/docker/Dockerfile): it gets the data folder ready, writes the AI backend from
the environment into the panel's settings, and then becomes the program the command asks for.

    panel [options]       the panel on 0.0.0.0:$OFFEROWL_PANEL_PORT (the default command)
    doctor [options]      the checks of `offerowl doctor`, run inside the container
    <offerowl command>    init, ingest, draft, build, cover, interview, selftest, llm: the command line
    <anything else>       started as it is (bash, python3, node ...), for looking around

It is started by tini (process 1), so a stop signal reaches the program it starts and not this script: the script
replaces itself with that program (exec) and stays out of the way.
"""
from __future__ import annotations  # hints stay strings, so new hint syntax runs on older Pythons

import json  # the panel's settings file
import os  # environment, exec
import shutil  # is a program on PATH
import sys  # arguments, the module path
import tempfile  # a safe write of the settings file
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[2]  # /work in the image, the repository in a checkout
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules: llm gives the messages their language
import llm  # noqa: E402  settings and message lookup (needs the line above)

# The commands of ./offerowl that exist as programs. Anything not named here and not found on PATH is passed to the
# launcher too, which then says it does not know the command.
LAUNCHER_COMMANDS = {"init", "ingest", "draft", "build", "cover", "interview", "selftest", "llm", "help", "--help", "-h"}
BACKENDS = ("none", "openai-compat", "claude-code", "codex")  # what OFFEROWL_LLM may name (the panel's menu has these and "auto")
SUBFOLDERS = ("workspace", "logs", "export")  # inside the data folder: the person's files, the logs, "Export to Desktop"

# What this script says, in both languages (tests/packaging checks that the keys and the placeholders match).
MSG = {
    "en": {
        "not_writable": ("The folder {path} cannot be written by user {uid}:{gid}. Give that user write access to it, "
                         "or start the container as the folder's owner (compose: OFFEROWL_UID and OFFEROWL_GID)."),
        "bad_backend": "OFFEROWL_LLM={value} is not a backend to preset (choices: {choices}); it is ignored.",
        "settings_unreadable": "{path} is not valid JSON, so the AI settings from the environment were not written to it.",
    },
    "ko": {
        "not_writable": ("{path} 폴더에 사용자 {uid}:{gid}가 쓸 수 없다. 그 사용자에게 쓰기 권한을 주거나, "
                         "폴더 주인의 id로 컨테이너를 시작한다(compose: OFFEROWL_UID, OFFEROWL_GID)."),
        "bad_backend": "OFFEROWL_LLM={value}은 미리 정할 수 있는 백엔드가 아니다(선택지: {choices}). 무시한다.",
        "settings_unreadable": "{path}이(가) 올바른 JSON이 아니어서 환경 변수의 AI 설정을 쓰지 않았다.",
    },
}


def t(key: str, **kw) -> str:  # every message goes through this one call
    """A message of this script in the current language"""
    return llm.message(MSG, key, **kw)


def data_dir() -> Path:  # the same variable the panel reads
    """The data folder (OFFEROWL_DATA_DIR, /data in the image)"""
    return Path(os.environ.get("OFFEROWL_DATA_DIR") or "/data")


def writable(folder: Path) -> bool:  # asked by trying, because permission bits alone miss read-only mounts
    """True when a file can be created and removed in `folder`"""
    try:  # any failure to write means "no"
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".probe-"):  # created and deleted when the block ends
            return True  # the folder takes files
    except OSError:  # permission denied, read-only file system, no space
        return False  # the caller explains it


def prepare_folders() -> bool:  # run on every start, so a bind mount that begins empty gets its folders
    """Make the data folder's subfolders and check the folders the app writes to. False (with the reason printed) when
    one of them cannot be written."""
    data = data_dir()  # the data folder
    for name in SUBFOLDERS:  # each subfolder
        try:  # a volume may belong to another user
            (data / name).mkdir(parents=True, exist_ok=True)  # created when missing
        except OSError:  # cannot create it: the check below reports the folder
            pass  # reported once, below, not once per subfolder
    ok = True  # the folders that must take files
    for folder in (data, ROOT / "output"):  # the data volume, and the engine's scratch folder
        if not writable(folder):  # not writable by this user
            print("offerowl: " + t("not_writable", path=folder, uid=os.getuid(), gid=os.getgid()), file=sys.stderr)  # says how to fix it
            ok = False  # the container cannot work
    return ok  # False stops the start


def seed_settings(env=None) -> dict:  # the panel keeps these three in settings.json
    """Write the AI backend from the environment into the panel's settings file, and return what was written. Only
    values that are set (not empty) are written, and they win at every start, so `helm upgrade` or a new compose
    environment takes effect. With nothing set, a first start gets backend "none": this image carries no agent CLI, so
    the panel's own default ("auto" looks for Claude Code) would show an agent that cannot be installed here. A choice
    made in the panel's menu stays until the environment names another."""
    env = os.environ if env is None else env  # tests pass their own environment
    path = data_dir() / "settings.json"  # the file the panel reads
    try:  # a missing file is an empty start; a broken one is left alone
        saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}  # what the panel saved
        if not isinstance(saved, dict):  # a list or a number is not a settings file
            raise ValueError("shape")  # handled with the broken-file case
    except (OSError, ValueError):  # unreadable or not JSON
        print("offerowl: " + t("settings_unreadable", path=path), file=sys.stderr)  # the person decides what to do with it
        return {}  # nothing written
    want: dict = {}  # the keys this start sets
    backend = (env.get("OFFEROWL_LLM") or "").strip()  # the engine's own variable names the backend
    url = (env.get("OFFEROWL_LLM_URL") or "").strip()  # the local OpenAI-compatible server
    model = (env.get("OFFEROWL_LLM_MODEL") or "").strip()  # its model name
    if backend and backend not in BACKENDS:  # a typo must not switch the agent off silently
        print("offerowl: " + t("bad_backend", value=backend, choices=", ".join(BACKENDS)), file=sys.stderr)  # said once
        backend = ""  # ignored
    if backend:  # named by the person
        want["backend"] = backend  # the agent the tasks will call
    elif url:  # an address with no backend named can only mean the local server
        want["backend"] = "openai-compat"  # the image has no other backend that takes an address
    elif "backend" not in saved:  # first start, nothing asked
        want["backend"] = "none"  # no agent CLI in this image
    if url:  # the address and the model are the panel's llm_url and llm_model
        want["llm_url"] = url[:300]  # the panel bounds them the same way
    if model:  # a model name
        want["llm_model"] = model[:300]  # bounded like the address
    merged = {**saved, **want}  # the environment wins over what was saved
    if merged != saved:  # write only on a change, so a restart does not touch the file
        data_dir().mkdir(parents=True, exist_ok=True)  # the data folder may be new
        tmp = path.with_name(path.name + ".tmp")  # written beside the target, then renamed over it
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # complete before it replaces
        os.replace(tmp, path)  # atomic: the panel never reads half a file
    return want  # tests read what was applied


def command_for(args: list[str]) -> list[str]:  # decides what the container becomes
    """The program (and its arguments) that `args` stand for."""
    args = args or ["panel"]  # no command: the panel
    head, rest = args[0], args[1:]  # the command and its options
    if head == "panel":  # the server, listening on every interface of the container; compose publishes it on the host's loopback only
        port = os.environ.get("OFFEROWL_PANEL_PORT") or "8797"  # must equal the published port
        return [sys.executable, str(ROOT / "apps" / "panel" / "server.py"), "--host", "0.0.0.0", "--port", port, *rest]  # noqa: S104
    if head == "doctor":  # the checks, as `offerowl doctor` runs them
        return [sys.executable, str(ROOT / "src" / "doctor.py"), *rest]  # src/doctor.py itself, the program `offerowl doctor` runs
    if head in LAUNCHER_COMMANDS or shutil.which(head) is None:  # an offerowl command, or something unknown the launcher can name
        return [sys.executable, str(ROOT / "offerowl"), *args]  # the command line
    return args  # an ordinary program, started as it is


def main(argv: list[str] | None = None) -> int:  # the entry
    args = list(sys.argv[1:] if argv is None else argv)  # a copy, so a caller's list is never changed
    if not prepare_folders():  # nothing can run without a place to write
        return 1  # the reason is printed
    seed_settings()  # the AI backend from the environment
    cmd = command_for(args)  # what to become
    os.execvp(cmd[0], cmd)  # replaces this process: tini's signals reach the program itself
    return 0  # not reached; execvp does not return


if __name__ == "__main__":  # run as the container's entrypoint
    raise SystemExit(main())  # main only returns on a failed start
