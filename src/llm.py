#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The one place where Offerowl talks to an AI model.

Extraction, posting analysis, drafting and translation all ask their questions through run() below. Typesetting and
the checks never call a model, and every suggestion still goes through the rule-based fact check. One backend is used
at a time, and the settings choose which.

Settings are environment variables.

  OFFEROWL_LLM=claude-code    the Claude Code CLI you are signed in to (`claude -p`); no API key
  OFFEROWL_LLM=codex          the Codex CLI (`codex exec`, after `codex login`)
  OFFEROWL_LLM=openai-compat  an OpenAI-compatible address: Ollama, vLLM, LM Studio
  OFFEROWL_LLM=none           no model: run() raises LLMUnavailable, so the caller falls back to a person typing the facts
  (not set)                   default order: Claude Code if it is installed and signed in, else Codex if it is installed, else none

  OFFEROWL_LLM_MODEL          model name (codex -m; "model" of the OpenAI-compatible request)
  OFFEROWL_LLM_URL            address of the OpenAI-compatible server
  OFFEROWL_LLM_KEY            bearer key, only for servers that ask for one
  OFFEROWL_LLM_REASONING      reasoning_effort sent to openai-compat (default none; an empty value sends nothing)
  OFFEROWL_CODEX_CMD          how to start Codex when it is not installed, for example "npx -y @openai/codex"
  OFFEROWL_CODEX_PROFILE      a profile from the Codex config file
  OFFEROWL_CODEX_OSS          ollama or lmstudio: let Codex talk to a local model
  OFFEROWL_LANG               ko or en: the language of messages (default: from the locale, else English)

The CLIs live on the host, so this module runs on the host. The render container has its network closed.

  python3 src/llm.py --list               the backends, which one is in use and why
  python3 src/llm.py --probe claude-code  one tiny test call (costs a little; run it only when you mean to)

Every call appends one line to output/_llm/calls.jsonl: backend, task, seconds and character counts. The text itself
is never written. The file is rotated once at 1 MB.
"""
import http.client  # a connection that drops in the middle of an answer
import json  # model output, the call log and the OpenAI-compatible request
import os  # environment variables and process groups
import pathlib  # paths
import re  # find the JSON block inside an answer, read CLI status text
import shlex  # split OFFEROWL_CODEX_CMD the way a shell would
import shutil  # is a CLI installed
import signal  # end a whole process group on timeout
import subprocess  # start the CLIs
import sys  # command line
import tempfile  # scratch folder for Codex's answer file
import threading  # one usage record per calling thread
import time  # how long a call took
import urllib.error  # HTTP errors from the OpenAI-compatible server
import urllib.parse  # the host of the OpenAI-compatible server
import urllib.request  # the OpenAI-compatible request itself

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
LOG = pathlib.Path(os.environ.get("OFFEROWL_LLM_LOG") or ROOT / "output" / "_llm" / "calls.jsonl")  # one line per call (a test or a demo may point it elsewhere)
LOG_MAX = 1_000_000  # bytes; past this the log is rotated to calls.jsonl.1 and a new one starts
BACKENDS = ("claude-code", "codex", "openai-compat", "none")  # the names a user can choose
WINDOWS = sys.platform == "win32"  # starting and stopping a CLI differ there
SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}  # no console window from the app; elsewhere its own session, so the group can be killed as one
LANGS = ("en", "ko")  # languages of the messages below; English is the fallback


# ---------------------------------------------------------------- settings and language

def setting(name: str, default: str = "") -> str:
    """Value of setting NAME: OFFEROWL_<NAME> if it is set, else the default. "Set" counts even when the value is empty."""
    return os.environ.get("OFFEROWL_" + name, default)  # present, even if empty, beats the default


def setting_source(name: str) -> str:
    """The environment variable that supplies setting NAME, or an empty string when it comes from the default"""
    return "OFFEROWL_" + name if "OFFEROWL_" + name in os.environ else ""  # the same test as setting()


def lang() -> str:
    """Language of the messages: OFFEROWL_LANG (ko or en), else the locale, else English"""
    value = os.environ.get("OFFEROWL_LANG", "").strip().lower()[:2]  # "ko_KR" and "ko" both mean Korean
    if value in LANGS:  # an explicit choice beats the locale
        return value
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):  # POSIX order: the first one that is set decides
        locale_name = os.environ.get(var, "")
        if locale_name:
            return "ko" if locale_name.lower().startswith("ko") else "en"  # C, POSIX and everything else read as English
    return "en"  # nothing set at all


# Every message a person can read. Placeholders are {names}; keep both languages in step (tests/cli checks that).
MSG = {
    "en": {
        "claude_missing": "claude CLI not found",
        "codex_missing": "codex CLI not found (OFFEROWL_CODEX_CMD can point to npx)",
        "url_missing": "OFFEROWL_LLM_URL is not set",
        "none_desc": "no model; a person fills in the facts",
        "unknown_backend": "unknown backend {name} (choices: {choices})",
        "cannot_start": "could not start {cmd}: {err}",
        "timed_out": "{cmd} did not answer within {sec} seconds",
        "claude_failed": "claude failed ({code}): {err}",
        "codex_failed": "codex failed ({code}): {err}",
        "codex_login_needed": "codex failed ({code}); run `codex login` first: {err}",
        "openai_failed": "openai-compat failed ({code}): {err}",
        "openai_no_answer": "openai-compat: no answer",
        "json_missing": "no JSON in the answer",
        "json_not_object": "the JSON is not an object",
        "json_missing_keys": "missing keys: {keys}",
        "json_gave_up": "{task}: asked {tries} times but the JSON format was never right",
        "codex_status_none": "codex CLI not found",
        "codex_status_in": "logged in",
        "codex_status_out": "login needed (codex login)",
        "codex_status_unknown": "status unreadable: {why}",
        "claude_signed_in": "signed in",
        "claude_signed_out": "not signed in (start claude once and sign in)",
        "claude_sign_unknown": "sign-in state unknown",
        "available": "available",
        "missing": "missing",
        "in_use": "In use: {name} ({how})",
        "how_env": "set by {var}",
        "how_arg": "chosen by the caller",
        "how_default": "default order: signed-in Claude Code, else Codex, else none",
        "probe_usage": "Usage: offerowl llm --probe <backend>  ({choices})",
        "probe_failed": "test call failed: {why}",
        "usage": ("Usage: offerowl llm [--list | --probe <backend>]\n"
                  "  --list             show the backends, which one is in use and why (default)\n"
                  "  --probe <backend>  make one tiny test call (costs a little)\n"
                  "Backends: {choices}"),
    },
    "ko": {
        "claude_missing": "claude CLI 없음",
        "codex_missing": "codex CLI 없음(OFFEROWL_CODEX_CMD로 npx도 된다)",
        "url_missing": "OFFEROWL_LLM_URL 없음",
        "none_desc": "모델 없이(사람이 채움)",
        "unknown_backend": "모르는 백엔드 {name} (고를 수 있는 것: {choices})",
        "cannot_start": "실행하지 못했다({cmd}): {err}",
        "timed_out": "{sec}초 안에 답하지 않았다({cmd})",
        "claude_failed": "claude 실패({code}): {err}",
        "codex_failed": "codex 실패({code}): {err}",
        "codex_login_needed": "codex 실패({code}) (codex login이 필요하다): {err}",
        "openai_failed": "openai-compat 실패({code}): {err}",
        "openai_no_answer": "openai-compat: 응답 없음",
        "json_missing": "응답에 JSON이 없다",
        "json_not_object": "JSON 객체가 아니다",
        "json_missing_keys": "빠진 키: {keys}",
        "json_gave_up": "{task}: {tries}번 물었지만 JSON 형식을 맞추지 못했다",
        "codex_status_none": "codex CLI 없음",
        "codex_status_in": "로그인됨",
        "codex_status_out": "로그인 필요(codex login)",
        "codex_status_unknown": "상태를 못 읽음: {why}",
        "claude_signed_in": "로그인됨",
        "claude_signed_out": "로그인 안 됨(claude를 한 번 실행해 로그인한다)",
        "claude_sign_unknown": "로그인 상태를 모름",
        "available": "쓸 수 있음",
        "missing": "없음",
        "in_use": "쓰는 것: {name} ({how})",
        "how_env": "{var} 설정",
        "how_arg": "부른 쪽이 정함",
        "how_default": "기본 순서: 로그인한 Claude Code, 없으면 Codex, 둘 다 없으면 none",
        "probe_usage": "쓰는 법: offerowl llm --probe <백엔드>  ({choices})",
        "probe_failed": "시험 호출 실패: {why}",
        "usage": ("쓰는 법: offerowl llm [--list | --probe <백엔드>]\n"
                  "  --list             쓸 수 있는 백엔드와 지금 쓰이는 것, 그 이유를 보인다(기본)\n"
                  "  --probe <백엔드>   아주 작은 시험 호출을 한 번 한다(작은 비용이 든다)\n"
                  "백엔드: {choices}"),
    },
}


def message(table: dict, key: str, **kw) -> str:
    """Message KEY from a {"en": {...}, "ko": {...}} table in the current language, with {placeholders} filled from kw.
    A language that lacks the key falls back to English, never to a bare key. Other modules keep their own tables and
    use this one function, so the rule lives in one place"""
    text = table.get(lang(), table["en"]).get(key) or table["en"][key]
    return text.format(**kw) if kw else text  # no kw: leave the text alone (it may hold literal braces)


def t(key: str, **kw) -> str:
    """A message of this module"""
    return message(MSG, key, **kw)


# ---------------------------------------------------------------- which backend

class LLMUnavailable(RuntimeError):
    """The backend is missing or switched off. The caller moves on to the path where a person fills in the facts"""

    def __init__(self, message: str = "", code: str = ""):
        super().__init__(message)  # the words a person reads, as before
        self.code = code  # a short code for the call log ("timeout", "exit 1", "http 429"): the agent card shows the last one, never the words


class CallFailed(LLMUnavailable):
    """The backend was there and answered with an error: an overloaded service, a dropped connection on its side, a refusal.
    run() asks once more after a pause, since such an error often passes; a second failure is reported like any other"""


RETRY_PAUSE = 10.0  # seconds before a failed call is asked again


def claude_signed_in():
    """True or False from `claude auth status --json`; None when the CLI cannot tell (older CLI, timeout, odd output).
    Only the loggedIn flag is read: the same JSON carries an e-mail address, which must never be printed or logged"""
    exe = shutil.which("claude")  # no CLI, nothing to ask
    if not exe:
        return None
    try:
        r = _run([exe, "auth", "status", "--json"], None, 20)  # local and fast (about 0.2 s); no model is called
        data = json.loads(r.stdout)
    except (LLMUnavailable, ValueError):  # could not run it, or the output was not JSON
        return None
    return bool(data["loggedIn"]) if isinstance(data, dict) and "loggedIn" in data else None  # anything else: cannot tell


def default_backend() -> str:
    """The backend when nothing is set: Claude Code if it is installed and not known to be signed out, else Codex, else none"""
    if shutil.which("claude") and claude_signed_in() is not False:  # None (cannot tell) still counts as usable
        return "claude-code"
    if codex_cmd():  # installed is enough here: `codex login status` can be slow when Codex starts through npx
        return "codex"
    return "none"


def chosen(backend: str | None = None) -> tuple:
    """(name, source) of the backend run() would use. source is the environment variable that chose it,
    "argument" when the caller passed one, or "default" for the default order"""
    if backend:  # an argument from the caller beats every setting
        return backend, "argument"
    value = setting("LLM").strip()  # empty counts as not set: the default order applies
    if value:
        return value, setting_source("LLM")
    return default_backend(), "default"


def available() -> dict:
    """For each backend: (usable now, a short reason a person can read). Presence only; sign-in is shown by list_backends()"""
    url = setting("LLM_URL")  # address of the OpenAI-compatible server
    claude = shutil.which("claude")
    return {
        "claude-code": (bool(claude), claude or t("claude_missing")),
        "codex": (bool(codex_cmd()), " ".join(codex_cmd()) or t("codex_missing")),
        "openai-compat": (bool(url), url or t("url_missing")),
        "none": (True, t("none_desc")),
    }


def codex_cmd() -> list:
    """Command that starts Codex: OFFEROWL_CODEX_CMD (for example "npx -y @openai/codex") if set, else codex on PATH.
    An empty list means it cannot be started"""
    env = setting("CODEX_CMD").strip()
    if env:
        try:
            cmd = shlex.split(env)  # split like a shell, so quoted paths survive
        except ValueError:  # unbalanced quotes: treat as unusable (the caller reports it as unavailable)
            return []
        return cmd if cmd and shutil.which(cmd[0]) else []  # the first word must be a program we can find
    return ["codex"] if shutil.which("codex") else []


def codex_login_status(timeout: int = 60) -> str:
    """Read `codex login status`: logged in, login needed, or the reason it could not be read"""
    cmd = codex_cmd()
    if not cmd:
        return t("codex_status_none")
    try:
        r = _run(cmd + ["login", "status"], None, timeout)
    except LLMUnavailable as e:
        return t("codex_status_unknown", why=e)
    out = (r.stdout + r.stderr).strip()
    if re.search(r"not logged in", out, re.I):  # test the negative first: "not logged in" also contains "logged in"
        return t("codex_status_out")
    return t("codex_status_in") if re.search(r"logged in", out, re.I) else t("codex_status_unknown", why=out[:80])


# ---------------------------------------------------------------- running the CLIs

def _is_shim(program: str) -> bool:
    """Is this CLI a Windows .cmd or .bat file? npm installs them that way, and only cmd.exe can start them."""
    return WINDOWS and (shutil.which(program) or program).lower().endswith((".cmd", ".bat"))


def _argv(cmd: list) -> list:
    """The command as this system can start it: on Windows the program's full path, through cmd.exe for a .cmd or .bat file."""
    if not WINDOWS:  # elsewhere the system finds the program on PATH by itself
        return cmd
    program = shutil.which(cmd[0]) or cmd[0]  # CreateProcess alone would look for an .exe only
    return (["cmd", "/c", program] if _is_shim(cmd[0]) else [program]) + cmd[1:]


def _kill_tree(p: subprocess.Popen) -> None:
    """End a CLI and everything it started: npx starts npm, which starts sh, which starts the real program, and killing
    only the top one left the rest running to the end."""
    if WINDOWS:  # Windows has no process groups to signal
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        return
    try:
        os.killpg(p.pid, signal.SIGKILL)  # the group of its own session
    except ProcessLookupError:  # it ended between the timeout and the kill
        pass


def _run(cmd: list, text_in: str | None, timeout: int, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run one command, and on timeout end it with everything it started."""
    try:
        p = subprocess.Popen(_argv(cmd),
                             stdin=subprocess.PIPE if text_in is not None else subprocess.DEVNULL,  # a CLI that reads stdin must not wait on the terminal
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", cwd=cwd,  # UTF-8 whatever the system's locale says
                             **SPAWN)
    except OSError as e:  # not executable, vanished since which() looked
        raise LLMUnavailable(t("cannot_start", cmd=cmd[0], err=e), code="no_start")
    try:
        out, err = p.communicate(text_in, timeout=timeout)  # send the prompt, wait for the answer
    except subprocess.TimeoutExpired:
        _kill_tree(p)  # the CLI and what it started
        p.communicate()  # reap it and close the pipes
        raise LLMUnavailable(t("timed_out", cmd=cmd[0], sec=timeout), code="timeout")
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def _log(rec: dict) -> None:
    """Append one call to the log and rotate it once when it grows past the limit. A log that cannot be written (an engine
    folder installed read-only) is skipped: the answer the call got still counts."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)  # the log folder
        if LOG.exists() and LOG.stat().st_size > LOG_MAX:  # too big
            LOG.replace(LOG.with_suffix(".jsonl.1"))  # keep exactly one older file
        with LOG.open("a", encoding="utf-8") as f:  # append, one JSON object per line
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:  # no place to keep it: the figures of this call are not counted
        pass


def _log_error(backend: str, task: str, t0: float, attempt: int, code: str) -> None:
    """One failed call in the log: when, how long it ran and a short code. Never the error's words, which may quote the CLI's
    output. calls_summary (apps/api/agent.py) counts these apart from the answered calls."""
    _log({"t": int(t0), "backend": backend, "task": task, "sec": round(time.time() - t0, 1), "attempt": attempt, "error": code})


def claude_effort() -> str:
    """The effort Claude Code runs at when the person set it in the environment (CLAUDE_CODE_EFFORT_LEVEL). Empty otherwise:
    Offerowl never opens the CLI's own files, and its settings file can hold keys (env, apiKeyHelper), so an effort set
    there is not read (the model's default then, which nothing names)."""
    return os.environ.get("CLAUDE_CODE_EFFORT_LEVEL", "").strip()[:16]  # a word such as "high"; a long value is not one


USAGE = threading.local()  # what the last call of this thread reported: tokens, the model, the cost (run() logs it)


def _claude(prompt: str, system: str | None, timeout: int) -> str:
    """Ask the signed-in Claude Code CLI once. Its tools are switched off: we only want text back. The answer comes as the
    CLI's JSON result, so the call's tokens and model can be logged; an older CLI that prints plain text still works"""
    USAGE.last = {}  # nothing reported yet
    cmd = ["claude", "-p", "--output-format", "json", "--tools", "", "--no-session-persistence"]  # ask once, keep no session
    with tempfile.TemporaryDirectory() as tmp:  # holds the instruction when it cannot go on the command line
        if system and _is_shim("claude"):  # cmd.exe would read the instruction's quotes and ampersands as its own
            instruction = pathlib.Path(tmp) / "system.txt"
            instruction.write_text(system, encoding="utf-8")
            cmd += ["--system-prompt-file", str(instruction)]
        elif system:  # a per-task system instruction
            cmd += ["--system-prompt", system]
        r = _run(cmd, prompt, timeout)  # the prompt goes through stdin, so its length is not limited by the command line
    if r.returncode != 0:  # for example a sign-in that expired
        raise CallFailed(t("claude_failed", code=r.returncode, err=(r.stderr.strip() or r.stdout.strip())[:200]), code=f"exit {r.returncode}")  # the CLI prints some refusals on stdout
    try:
        ev = json.loads(r.stdout)  # the result object
    except ValueError:  # plain text, from a CLI without the JSON form
        return r.stdout.strip()
    if isinstance(ev, list):  # verbose on (a flag, or the person's own settings): every message, the result last
        ev = next((m for m in reversed(ev) if isinstance(m, dict) and m.get("type") == "result"), None)  # the result object
        if ev is None:  # a list with no result in it
            raise CallFailed(t("claude_failed", code=r.returncode, err="no result in the answer"), code="no_result")
    if not isinstance(ev, dict):  # not the result object
        return r.stdout.strip()
    if ev.get("is_error"):  # a refusal, a limit or a run that failed, said in the result (which may have no text)
        sub = str(ev.get("subtype") or "")  # "error_max_turns" and the like; a limit comes as "success" with is_error set
        raise CallFailed(t("claude_failed", code=r.returncode, err=str(ev.get("result") or sub)[:200]),
                         code=sub[:32] if sub and sub != "success" else "is_error")  # the kind only: the result's words may quote the prompt
    if "result" not in ev:  # some other object
        return r.stdout.strip()
    u = ev.get("usage") if isinstance(ev.get("usage"), dict) else {}  # tokens of this call
    models = list((ev.get("modelUsage") or {}).keys()) if isinstance(ev.get("modelUsage"), dict) else []  # the model or models it ran on
    ttft = ev.get("ttft_ms")  # time to the first token, which newer CLIs put in the result; older ones leave it out
    effort = claude_effort()  # the effort the CLI runs at, when the person set one
    USAGE.last = {**({"ttft": round(ttft / 1000, 2)} if isinstance(ttft, (int, float)) and ttft >= 0 else {}),  # so the card can split waiting from writing
                  **({"effort": effort} if effort else {}),  # shown beside the model
                  "tok_in": int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0),  # everything it read
                  "tok_out": int(u.get("output_tokens") or 0), "model": models[0] if models else "", "cost": ev.get("total_cost_usd")}  # what it wrote, on which model
    return str(ev.get("result") or "").strip()  # the answer's text


def _codex(prompt: str, system: str | None, timeout: int, schema: dict | None = None) -> str:
    """Ask the Codex CLI once. The flags follow `codex exec --help` (codex-cli 0.166): --skip-git-repo-check so that it
    runs outside a git repository, --ephemeral so that no session file is left, -s read-only so that it cannot run
    commands, and -o to read only the last answer (standard output is mixed with progress notes). The prompt is read
    from stdin through "-". With a schema, --output-schema forces the shape of the answer; if Codex rejects the schema
    the question is asked once more without it (not verified against a signed-in Codex). Before login it fails with 401"""
    text = (system + "\n\n" + prompt) if system else prompt  # exec has no system-instruction slot, so put it first
    base = codex_cmd()
    if not base:
        raise LLMUnavailable(t("codex_missing"), code="missing")
    with tempfile.TemporaryDirectory() as tmp:  # holds the answer file and the schema file
        last = pathlib.Path(tmp) / "last.txt"
        cmd = base + ["exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-o", str(last)]
        if setting("LLM_MODEL"):  # only when a model is chosen
            cmd += ["-m", setting("LLM_MODEL")]
        if setting("CODEX_PROFILE"):  # a profile from the Codex config file
            cmd += ["-p", setting("CODEX_PROFILE")]
        if setting("CODEX_OSS"):  # Codex talking to a local model (ollama, lmstudio)
            cmd += ["--oss", "--local-provider", setting("CODEX_OSS")]
        tries = [True, False] if schema else [False]  # with the schema first, then without if it is refused
        for with_schema in tries:
            extra = []
            if with_schema:
                sf = pathlib.Path(tmp) / "schema.json"
                sf.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
                extra = ["--output-schema", str(sf)]
            last.unlink(missing_ok=True)  # an answer left by the first try must not pass for the second
            r = _run(cmd + extra + ["-"], text, timeout, cwd=tmp)  # cwd is the scratch folder: Codex must not roam the repository
            if r.returncode == 0 and last.exists():
                return last.read_text(encoding="utf-8").strip()
            err = (r.stderr or r.stdout).strip()
            if re.search(r"\b401\b|Unauthorized|not logged in", err, re.I):  # asking again will not fix a login ("401" must be a whole word, so "14012 tokens" does not match)
                raise LLMUnavailable(t("codex_login_needed", code=r.returncode, err=err[-200:]), code="login")
        raise CallFailed(t("codex_failed", code=r.returncode, err=err[-200:]), code=f"exit {r.returncode}")  # a login problem was raised above, and is not asked again


def _openai_compat(prompt: str, system: str | None, timeout: int, json_mode: bool = False) -> str:
    """Ask an OpenAI-compatible /v1/chat/completions endpoint once (local Ollama, vLLM and so on).
    A thinking model can spend all its time in the reasoning field and send an empty answer: a 26B local model took
    189 s and 50k characters of thinking for one translation batch, and 7.7 s with reasoning_effort none. So thinking
    is off by default (OFFEROWL_LLM_REASONING changes it; empty sends nothing). A server that does not know the
    option answers 400, and then the question is asked again without it"""
    base = setting("LLM_URL").strip().rstrip("/")
    if not re.match(r"https?://", base):  # "localhost:11434" without a scheme
        base = "http://" + base
    base = re.sub(r"/v1$", "", base)  # an address written the OpenAI SDK way, ending in /v1
    url = base + "/v1/chat/completions"
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]  # the conversation
    req = {"model": setting("LLM_MODEL", "default"), "messages": msgs, "temperature": 0}  # temperature 0: repeatable answers
    if json_mode:  # JSON mode (Ollama and vLLM accept it); a local 26B model broke the format twice on one fragment without it
        req["response_format"] = {"type": "json_object"}
    effort = setting("LLM_REASONING", "none")
    headers = {"Content-Type": "application/json"}
    if setting("LLM_KEY"):  # only servers that ask for a key
        headers["Authorization"] = "Bearer " + setting("LLM_KEY")
    # a server on this PC or the local network is asked directly: a proxy set for the web (http_proxy, HTTPS_PROXY) would
    # otherwise receive the prompts, the person's files among them, on their way to a model that never leaves the PC
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if is_local(url) else urllib.request.build_opener()
    for with_effort in ([True, False] if effort else [False]):  # with the option first, then without
        body = dict(req, **({"reasoning_effort": effort} if with_effort else {}))
        r = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        try:
            with opener.open(r, timeout=timeout) as resp:  # send and wait
                answer = (json.loads(resp.read())["choices"][0]["message"].get("content") or "").strip()  # the text
            USAGE.last = {"effort": effort} if with_effort else {}  # the reasoning effort the server took, for the agent card
            return answer
        except urllib.error.HTTPError as e:
            if e.code in (400, 422) and with_effort:  # the server does not know reasoning_effort: ask again without it
                continue
            fail = CallFailed if e.code == 429 or e.code >= 500 else LLMUnavailable  # busy or broken for a moment, or a request it will refuse again
            raise fail(t("openai_failed", code=e.code, err=repr(e.read()[:200])), code=f"http {e.code}")
    raise LLMUnavailable(t("openai_no_answer"), code="no_answer")


def is_local(url: str) -> bool:
    """True for a server on this PC or the local network: localhost, a loopback or private address, a .local name."""
    import ipaddress  # only here
    host = (urllib.parse.urlsplit(url).hostname or "").lower()  # without the port and brackets
    if host in ("localhost", "host.docker.internal") or host.endswith((".localhost", ".local")):  # names that stay on this PC or network
        return True
    try:
        ip = ipaddress.ip_address(host)  # a literal address
    except ValueError:  # a name: it may be anywhere
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local  # 127.0.0.1, ::1, 10/8, 172.16/12, 192.168/16, fe80::/10


def extract_json(text: str):
    """Pull the JSON out of an answer: inside a code fence if there is one, else the first thing that parses, trying
    every opening bracket in turn (so a preamble such as "[note]" does not hide the real JSON after it)"""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)  # a fenced block
    if fence:
        text = fence.group(1)
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":  # a possible start
            try:
                return dec.raw_decode(text[i:])[0]  # raw_decode reads one value and ignores what follows
            except json.JSONDecodeError:
                continue
    raise ValueError(t("json_missing"))


def run(task: str, prompt: str, *, system: str | None = None, want_json: bool = False, required: tuple = (),
        backend: str | None = None, timeout: int = 300, retries: int = 1, schema: dict | None = None):
    """Ask the model once. With want_json the answer is parsed as JSON and checked for the required keys; a wrong shape
    is asked again up to `retries` times. schema (JSON Schema) is only handed to backends that take one (Codex
    --output-schema); the others get the same shape from the prompt and from JSON mode"""
    name, _source = chosen(backend)  # explicit argument, then the settings, then the default order
    if name not in BACKENDS:  # a settings mistake is not a format failure (a caller must not read it as a bad answer and carry on)
        raise LLMUnavailable(t("unknown_backend", name=name, choices=", ".join(BACKENDS)))
    ok, why = available()[name]  # can it be used right now
    if name == "none" or not ok:  # the path without a model
        raise LLMUnavailable(f"{name}: {why}")
    call = {"claude-code": _claude, "codex": _codex, "openai-compat": _openai_compat}[name]  # the function for this backend
    for attempt in range(retries + 1):  # the first ask, then the retries
        t0 = time.time()
        for again in (False, True):  # a failed call is asked once more
            USAGE.last = {}  # nothing reported by this try yet: a failed try before it must not lend it its figures
            try:
                if name == "openai-compat":  # takes the JSON-mode switch
                    out = call(prompt, system, timeout, want_json)
                elif name == "codex":  # takes the output schema
                    out = call(prompt, system, timeout, schema if want_json else None)
                else:
                    out = call(prompt, system, timeout)
                break  # answered
            except CallFailed as e:  # the backend answered with an error, which often passes
                _log_error(name, task, t0, attempt, e.code or "failed")  # counted on the agent card, retried or not
                if again:  # the second failure stands
                    raise
                time.sleep(RETRY_PAUSE)  # a moment for an overloaded service
                t0 = time.time()  # the call's time starts again
            except LLMUnavailable as e:  # a timeout, a CLI that would not start, a sign-in it needs
                _log_error(name, task, t0, attempt, e.code or "unavailable")  # the card's last error
                raise
            except (OSError, http.client.HTTPException, json.JSONDecodeError, KeyError, IndexError) as e:  # refused connection, dropped connection, timeout, damaged answer
                _log_error(name, task, t0, attempt, type(e).__name__[:32])  # the kind of failure, not its words
                raise LLMUnavailable(f"{name}: {type(e).__name__}: {e}", code=type(e).__name__[:32])
        _log({"t": int(t0), "backend": name, "task": task, "sec": round(time.time() - t0, 1),
              "in_chars": len(prompt), "out_chars": len(out), "attempt": attempt,  # no text, only sizes
              **(getattr(USAGE, "last", None) or {})})  # tokens and the model, when the backend said them
        USAGE.last = {}  # spent
        if not want_json:  # plain text: done
            return out
        try:
            data = extract_json(out)
            if required and not isinstance(data, dict):  # keys were required but the JSON is a list or a scalar
                raise ValueError(t("json_not_object"))
            if isinstance(data, dict) and not all(k in data for k in required):  # some required key is absent
                raise ValueError(t("json_missing_keys", keys=", ".join(k for k in required if k not in data)))
            return data
        except ValueError as e:  # wrong shape (json.JSONDecodeError is a ValueError too): ask again and say what was wrong
            prompt = prompt + f"\n\nYour previous answer had the wrong format ({e}). Reply with the JSON only."  # a prompt for the model, so it stays English
    raise ValueError(t("json_gave_up", task=task, tries=retries + 1))


# ---------------------------------------------------------------- the llm command

def claude_state() -> str:
    """One bracketed word for the claude-code row of the list: signed in, signed out, or unknown"""
    state = claude_signed_in()
    return t("claude_signed_in" if state else "claude_signed_out" if state is False else "claude_sign_unknown")


def list_backends() -> None:
    """Print every backend with its state, mark the one in use, and say why it is the one in use"""
    name, source = chosen()  # what run() would use right now
    for backend, (ok, why) in available().items():
        extra = ""
        if backend == "claude-code" and ok:  # show the sign-in state next to the CLI path
            extra = f"  [{claude_state()}]"
        elif backend == "codex" and ok:  # `codex login status`; slow through npx, so only when listing
            extra = f"  [{codex_login_status()}]"
        print(f"{'*' if backend == name else ' '} {backend:14} {t('available') if ok else t('missing'):10} {why}{extra}")
    if name not in BACKENDS:  # a mistyped setting: say so instead of leaving every row unmarked
        print(t("unknown_backend", name=name, choices=", ".join(BACKENDS)))
    if source == "default":
        how = t("how_default")
    elif source == "argument":
        how = t("how_arg")
    else:  # an environment variable chose it; say which
        how = t("how_env", var=source)
    print()
    print(t("in_use", name=name, how=how))


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)  # the launcher passes its own list
    if "--help" in args or "-h" in args:
        print(t("usage", choices=", ".join(BACKENDS)))
        return 0
    if "--probe" in args:  # one tiny test call; the only thing here that can cost money
        i = args.index("--probe")
        if i + 1 >= len(args):
            print(t("probe_usage", choices=", ".join(BACKENDS)))
            return 1
        try:
            print(run("probe", 'Reply with exactly this JSON: {"ok": true}', want_json=True, required=("ok",), backend=args[i + 1], timeout=120))
        except (LLMUnavailable, ValueError) as e:
            print(t("probe_failed", why=e))
            return 2
        return 0
    list_backends()  # --list, or no arguments at all
    return 0


if __name__ == "__main__":
    sys.exit(main())
