"""The agent card: which AI backend Offerowl uses, whether it is signed in, and as whom.

- Claude Code: `claude auth status --json` (local state only) for the sign-in, the account and the plan.
- Codex: `codex login status`.
- A local OpenAI-compatible server, or none.

Each CLI answers for itself. Offerowl never opens a CLI's login files and never sees a token: a person signs in through the
CLI's own flow, and the CLI talks to its maker. One backend at a time (docs/ARCHITECTURE.md, decision 1). The card's data is
cached: the CLIs take a second or two to answer.
"""
from __future__ import annotations

import http.client  # a typed address that cannot be asked
import json  # CLI output
import os  # environment and home
import re  # plan tier names
import shutil  # is a CLI on PATH
import subprocess  # the CLIs
import sys  # Windows command files
import threading  # the cache lock
import time  # cache ages
import urllib.request  # the local server

STATUS_EVERY = 60  # seconds between two reads of the sign-in state
BACKENDS = ("auto", "claude-code", "codex", "openai-compat", "none")  # what the menu offers
INSTALL_URL = {"claude-code": "https://code.claude.com/docs/en/setup", "codex": "https://github.com/openai/codex"}  # install pages


def cli(name: str) -> str | None:
    """The full path of a CLI on PATH, or None."""
    return shutil.which(name)  # claude, claude.exe, claude.cmd


def run_cli(path: str, args: list, timeout: float = 20) -> tuple[int, str]:
    """Run a CLI and return (exit code, output). A Windows .cmd shim needs cmd.exe to start."""
    cmd = [path, *args]  # the command
    if sys.platform == "win32" and path.lower().endswith((".cmd", ".bat")):  # npm's shims on Windows
        cmd = ["cmd", "/c", *cmd]  # through the shell that runs them
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: no console flash from the windowless app
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, creationflags=flags)  # a hung or missing CLI must not hold a request
    except (OSError, subprocess.TimeoutExpired) as exc:  # missing, or it hung
        return 1, str(exc)
    return r.returncode, (r.stdout or "") + (r.stderr or "")  # both streams


def claude_status() -> dict:
    """Claude Code: installed, signed in, the account's address and the plan."""
    path = cli("claude")  # the CLI
    if not path:  # nothing to ask
        return {"installed": False, "signed_in": False}  # not on this PC
    code, out = run_cli(path, ["auth", "status", "--json"])  # local state, no network
    try:
        d = json.JSONDecoder().raw_decode(out[out.index("{"):])[0] if "{" in out else {}  # the JSON part, whatever a warning says after it
    except ValueError:  # not JSON: shown as signed out
        d = {}  # unreadable: shown as not signed in
    return {"installed": True, "signed_in": bool(d.get("loggedIn")), "email": str(d.get("email") or ""),
            "plan": str(d.get("subscriptionType") or "").capitalize(), "method": str(d.get("authMethod") or "")}  # what the card shows, as the CLI says it


def codex_status() -> dict:
    """Codex: installed and signed in, as its own status command says."""
    path = cli("codex")  # the CLI
    if not path:  # nothing to ask
        return {"installed": False, "signed_in": False}
    code, out = run_cli(path, ["login", "status"])  # 0 and "Logged in ..." when it is
    return {"installed": True, "signed_in": code == 0 and "not logged in" not in out.lower()}  # its exit code and its words both say it


def local_status(url: str, model: str) -> dict:
    """A local OpenAI-compatible server: does it answer its model list."""
    if not url:  # no address set: not usable
        return {"installed": False, "signed_in": False}  # no address set
    base = re.sub(r"/v1/?$", "", url.strip().rstrip("/"))  # as llm.py reads it
    base = base if re.match(r"https?://", base) else "http://" + base  # an address typed without its scheme
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # local: no proxy
        with opener.open(base + "/v1/models", timeout=3) as r:  # the cheapest request every such server answers
            ok = r.status == 200  # only a plain OK counts
    except (OSError, ValueError, http.client.HTTPException):  # refused, timed out, unreachable, or an address no request can be made of
        ok = False  # not answering
    return {"installed": True, "signed_in": ok, "plan": model}


def calls_summary(day_seconds: int = 86400, keep: int = 24, backend: str | None = None) -> dict:
    """What the agent did for Offerowl on this PC in the last day, from src/llm.py's call log (sizes, timings and error codes,
    never text): the answered calls, their median time, the tokens read and written, the model and effort last named, the
    average time to the first token and tokens a second while writing, the cost the CLI reported, the failed calls with the
    last one's code and time, and the last calls' times for the card's bars. Read from the log's tail, so a long log costs
    nothing. With backend, only that agent's calls count: the card is one agent's, and a local model or a test's stand-in
    server writes to the same log."""
    import llm  # src/llm.py: its log's place
    now = time.time()  # the day's end
    rows = []  # the day's calls
    try:
        with open(llm.LOG, "rb") as f:  # the log, one JSON object per line
            f.seek(0, os.SEEK_END)  # its end
            f.seek(max(0, f.tell() - 400_000))  # the last 400 kB: thousands of calls
            for line in f.read().decode("utf-8", "replace").splitlines():  # each call
                try:
                    r = json.loads(line)
                except ValueError:  # a line cut by the seek
                    continue
                if isinstance(r, dict) and now - float(r.get("t") or 0) <= day_seconds and (not backend or r.get("backend") == backend):  # this day, this agent
                    rows.append(r)
    except OSError:  # no log yet
        pass
    failed = [r for r in rows if r.get("error")]  # src/llm.py's error rows: a code, no answer
    rows = [r for r in rows if not r.get("error")]  # the answered calls: every figure below counts only these, as it always did
    secs = sorted(float(r.get("sec") or 0) for r in rows)  # their times
    model = next((r.get("model") for r in reversed(rows) if r.get("model")), "")  # the model last named
    effort = next((str(r.get("effort")) for r in reversed(rows) if r.get("effort")), "")  # the effort last named; empty when none was set

    def num(v):  # a figure from the log, or None for a missing or broken one
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None
    ttfts = [num(r.get("ttft")) for r in rows if num(r.get("ttft")) is not None]  # only calls whose CLI said its first token
    rates = []  # tokens a second while writing, per call
    for r in rows:
        sec, ttft, out = num(r.get("sec")) or 0.0, num(r.get("ttft")) or 0.0, int(num(r.get("tok_out")) or 0)  # one call's figures
        writing = sec - ttft if 0 < ttft < sec else sec  # its writing time, or the whole call when the first token is not known
        if out and writing > 0:  # a call that wrote something in measurable time
            rates.append(out / writing)
    costs = [num(r.get("cost")) for r in rows if num(r.get("cost")) is not None]  # the CLI's own figure, where it gave one
    last = failed[-1] if failed else None  # the latest failure
    bars = []  # the card's bars: each call's time, split at its first token when known
    for r in rows[-keep:]:
        sec, ttft = round(num(r.get("sec")) or 0.0, 1), num(r.get("ttft"))  # the call's time and its wait
        bars.append({"sec": sec, **({"ttft": round(min(ttft, sec), 1)} if ttft is not None else {})})  # the wait never longer than the call
    return {"calls": len(rows), "median": round(secs[len(secs) // 2], 1) if secs else None,  # how many, how long
            "tok_in": sum(int(r.get("tok_in") or 0) for r in rows), "tok_out": sum(int(r.get("tok_out") or 0) for r in rows),  # what they read and wrote
            "model": model, "recent": [round(float(r.get("sec") or 0), 1) for r in rows[-keep:]],  # the bars as before: the last calls' times
            "effort": effort,  # "high", or empty
            "ttft_avg": round(sum(ttfts) / len(ttfts), 2) if ttfts else None,  # seconds to the first token, over the calls that said it
            "tps_avg": round(sum(rates) / len(rates), 1) if rates else None,  # output tokens a second while writing
            "cost": round(sum(costs), 4) if costs else None,  # US dollars as the CLI reports them (on a subscription: what the API would charge)
            "errors": len(failed),  # failed calls, each try counted
            "last_error": {"code": str(last.get("error"))[:32], "t": int(num(last.get("t")) or 0)} if last else None,  # the latest failure's code and time
            "bars": bars}  # the bars with their split


class AgentCard:
    """The card's data, refreshed in the background so a request never waits for a CLI."""

    def __init__(self, settings_fn):
        self.settings_fn = settings_fn  # returns the current settings dict
        self.lock = threading.Lock()  # one refresh at a time
        self.cache: dict = {"checking": True}  # shown until the first check ends
        self.at = 0.0  # when the sign-in state was read
        self.asked = 0  # how many times the settings changed what the card must look at (look_again): a count, since two clock readings may be equal
        self.login_proc: subprocess.Popen | None = None  # a sign-in started from the panel

    def chosen(self, st: dict | None = None) -> str:
        """The backend in use: the setting, with "auto" resolved to Claude Code, else Codex, else none."""
        s = self.settings_fn()  # current settings
        want = s.get("backend") or "auto"  # the choice
        if os.environ.get("OFFEROWL_PANEL_AGENT") == "standin":  # the tests' and the app check's stand-in
            return "standin"
        if want != "auto":  # a choice in the menu wins
            return want
        st = st or self.cache  # last known states
        claude, codex = st.get("claude") or {}, st.get("codex") or {}  # the two CLIs as last seen
        if claude.get("installed") and (claude.get("signed_in") or not codex.get("installed")):  # Claude Code first, as llm.py's default order:
            return "claude-code"  # signed in, or with no Codex to fall back on (the card then offers its sign-in)
        if codex.get("installed"):  # then Codex, also when Claude Code is there but signed out, as llm.py does
            return "codex"
        return "none"

    def refresh(self, force: bool = False) -> dict:
        """Read the states again when they are old (or when forced) and return the card."""
        with self.lock:  # one refresh at a time
            now = time.time()  # one clock for both ages below
            if force or now - self.at > STATUS_EVERY or self.cache.get("checking"):  # only when the last look is old
                asked = self.asked  # the changes this look can see
                s = self.settings_fn()  # settings
                st = {"claude": claude_status(), "codex": codex_status(),  # every option, so the menu knows what this PC has
                      "local": local_status(s.get("llm_url", ""), s.get("llm_model", ""))}  # every option
                # kept; a change of settings made while this look ran (look_again) is not overwritten: it is looked at next
                self.cache, self.at = st, (now if self.asked == asked else 0.0)
            return self.card()

    def look_again(self) -> None:
        """The settings changed what the card shows (the backend, a local server's address or model): the next state looks
        again, even when a look already running read the settings before the change."""
        self.asked, self.at = self.asked + 1, 0.0  # one more change; a look that started before it leaves the card due

    def card(self) -> dict:
        """What the panel draws: the backend, its state and the account. It never waits for a CLI: when the last look is old, or a
        sign-in has just ended, a new look starts behind it and the next state shows the result."""
        if self.login_proc is not None and self.login_proc.poll() is not None:  # the sign-in started from the panel has ended
            self.login_proc = None  # done
            self.look_again()  # look again, even past a look that began before it ended
        if time.time() - self.at > STATUS_EVERY and not self.lock.locked():  # old, and nobody is looking yet
            threading.Thread(target=self.refresh, daemon=True, name="agent").start()  # behind this answer
        name = self.chosen(self.cache)  # the backend in use
        want = self.settings_fn().get("backend") or "auto"  # the choice behind it
        if name == "none" and want == "auto" and not self.cache.get("checking"):
            name = "claude-code"  # "auto" found no CLI: the default agent is shown as not installed, not as switched off
        st = {"claude-code": self.cache.get("claude"), "codex": self.cache.get("codex"),  # the chosen backend's own state
              "openai-compat": self.cache.get("local")}.get(name) or {}  # its state
        if name == "standin":  # the stand-in has nothing to sign in to
            state = "ready"  # the stand-in always answers
        elif name == "none" and want == "none":  # the person turned the agent off: known without a look
            state = "off"  # no agent
        elif self.cache.get("checking"):  # the first look has not ended: with "auto" nothing is found yet, which is not off
            state = "checking"  # the pill says so, and the page asks again soon
        elif name == "none":  # no other choice resolves to none; kept so the card always says something
            state = "off"
        elif not st.get("installed"):  # the CLI is not on this PC
            state = "missing"  # not on this PC
        else:
            state = "ready" if st.get("signed_in") else "signed_out"  # installed: signed in or not
        return {"backend": name, "state": state, "email": st.get("email", ""), "plan": st.get("plan", ""),
                "found": [k for k, v in (("claude-code", self.cache.get("claude")), ("codex", self.cache.get("codex")))  # the CLIs found, for the menu's choices
                          if (v or {}).get("installed")],  # what this PC has, for the menu
                "install": INSTALL_URL.get(name, ""), "signing_in": self.signing_in()}  # where to get it, and a sign-in in progress

    def signing_in(self) -> bool:
        """A sign-in started from the panel is still running."""
        return self.login_proc is not None and self.login_proc.poll() is None

    def start_login(self) -> bool:
        """Start the chosen CLI's own sign-in, which opens the browser. Returns False when there is no CLI to start."""
        name = self.chosen()  # which agent
        path = cli({"claude-code": "claude", "codex": "codex"}.get(name, "")) if name in ("claude-code", "codex") else None  # only the two CLIs have a sign-in
        if not path or self.signing_in():  # no CLI, or one sign-in is enough
            return bool(path)  # nothing to start, or one is running
        args = ["auth", "login"] if name == "claude-code" else ["login"]  # each CLI's sign-in
        cmd = ["cmd", "/c", path, *args] if sys.platform == "win32" and path.lower().endswith((".cmd", ".bat")) else [path, *args]  # npm's Windows shims need cmd.exe
        flags = 0x08000000 if sys.platform == "win32" else 0  # no console window
        self.login_proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,  # detached: the browser flow may take minutes
                                           creationflags=flags, start_new_session=sys.platform != "win32")  # runs on its own
        self.look_again()  # read the state again soon
        return True
