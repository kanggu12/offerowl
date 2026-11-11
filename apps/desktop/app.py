"""Offerowl as one program on one PC: it starts the panel's server as a child, opens the panel in the browser, puts
an icon in the notification area, and starts the server again if it stops. The one-file app (build.py) runs this; so
does `python3 apps/desktop/app.py` from a checkout.

    Offerowl.exe                  start the panel and open it (when it is already running: open it)
    Offerowl.exe --no-browser     the same, without opening the panel
    Offerowl.exe --no-tray        without the notification-area icon (Ctrl+C or the system stops it)
    Offerowl.exe --check          start the server with a stand-in agent on a free port, read one file through it, stop;
                                  a copy that carries Node.js also makes the example resume, deck and cover letter
    Offerowl.exe script.py [...]  run an engine script the way `python script.py` does (see run_script)
    python3 apps/desktop/app.py [...]   the same from a checkout

The data folder holds the settings, the workspace, the logs and the Node.js the app carries:

    Windows   %LOCALAPPDATA%\\Offerowl
    macOS     ~/Library/Application Support/Offerowl
    Linux     $XDG_DATA_HOME/offerowl, or ~/.local/share/offerowl

The logs, each capped in size with one older file kept, are in its logs/: what this program did (app.log), what the
server printed (server-console.log), and the panel's own log (panel.log). OFFEROWL_DATA_DIR names another folder.
The one-file app typesets with the PC's own Chrome or Edge and the Node.js it carries (apps/desktop/node/), unpacked
into runtime/ of the data folder at the first start, so it needs no Docker.
"""
from __future__ import annotations  # hints stay strings, so new hint syntax runs on older Pythons

import argparse  # the command line
import json  # the server's answers
import os  # environment
import runpy  # engine scripts run by this program as the interpreter
import shutil  # which CLI is on PATH
import signal  # the server child's group is told to stop (POSIX)
import socket  # free ports
import subprocess  # the server child
import sys  # frozen or not
import tempfile  # the check's own data folder
import threading  # log pumps and the watch loop
import time  # waiting
import traceback  # a report instead of the bootloader's dialog
import urllib.request  # asking the server
import webbrowser  # opening the panel
import zipfile  # the DOCX the check reads
from pathlib import Path  # paths

FROZEN = bool(getattr(sys, "frozen", False))  # the one-file app
ROOT = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parents[2]  # where apps/ and src/ are
PORT = 8797  # the panel's port (docs/APP.md)
LOG_CAP = 2 * 1024 * 1024  # bytes a log reaches before it is rotated; one older file is kept
RESTARTS = (5, 600)  # a server started this many times within this many seconds is given up on
CREATE_NO_WINDOW = 0x08000000  # a console program started from a windowless one gets no window of its own


def data_dir() -> Path:  # one place decides the folder on every system
    """Where the settings, the workspace and the logs go (OFFEROWL_DATA_DIR overrides it)."""
    if os.environ.get("OFFEROWL_DATA_DIR"):  # a chosen folder (tests, a portable copy) wins
        return Path(os.environ["OFFEROWL_DATA_DIR"]).expanduser().resolve()  # a ~ means the home folder; a relative path must not follow the server's working folder
    if sys.platform == "win32":  # Windows keeps per-user app data under LOCALAPPDATA
        # the usual path stands in when LOCALAPPDATA is unset
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Offerowl"
    if sys.platform == "darwin":  # macOS has its own place for app data
        return Path.home() / "Library" / "Application Support" / "Offerowl"  # the folder Mac apps keep their data in
    # Linux and the rest: the XDG data folder or its default
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "offerowl"


def node_runtime():  # imported late: the tests load this file by its path, with apps/ off the module path
    """apps/desktop/node/runtime.py, which finds and unpacks the Node.js that comes with the app."""
    try:  # the one-file app and `python -m desktop` import this file as desktop.app
        from desktop.node import runtime  # the module next to this file
    except ImportError:  # started as a script: only apps/desktop is on the module path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/, where the desktop package is
        from desktop.node import runtime  # now found
    return runtime  # the module


def server_env(base: dict, data: Path, port: int, runtime=None) -> dict:  # one recipe for both the real start and the check
    """The server's environment: `base` with the app's defaults where it has none. `runtime` is the Node.js to hand to
    the engine (runtime.Runtime), when there is one."""
    env = dict(base)  # a copy
    env["OFFEROWL_DATA_DIR"] = str(data)  # the folder as this process resolved it: the server starts in another working folder, and a relative path would land in the bundle and go with it
    defaults = {  # what the app sets unless the caller already did
        "OFFEROWL_PANEL_PORT": str(port),  # the port it listens on
        "PYTHONUTF8": "1",  # the children print Korean and English; a Windows console code page fails on either
        "PYTHONIOENCODING": "utf-8",  # stdio stays UTF-8 even if UTF-8 mode is switched off
        "OFFEROWL_LLM_LOG": str(Path(data) / "logs" / "calls.jsonl"),  # the agent's call log with the data: the app's own folder is unpacked anew each start
    }
    for key, value in defaults.items():  # each default is weighed against the caller's own values
        env.setdefault(key, value)  # a value already set wins
    env["OFFEROWL_APP_PARENT"] = str(os.getpid())  # this process: the server ends itself once it is gone (watch_parent)
    if FROZEN:  # the one-file app has no render container inside it (render/, its starter and recipe, is not bundled)
        env["OFFEROWL_RENDERER"] = "html"  # so the PC's own Chrome or Edge typesets, whatever the person's shell says
    if runtime is not None:  # a Node.js to use: the one this app unpacked, or the one the person named
        env = runtime.apply(env)  # first on PATH, where src/resume.py looks for `node`, and named in OFFEROWL_NODE
    return env  # handed to Child as the server's whole environment


def role_cmd(*args: str) -> list[str]:  # the server is this same program, not a second file
    """The command that runs this program again in another role (--serve)."""
    if FROZEN:  # a one-file app has no script path to pass
        return [sys.executable, *args]  # the app itself
    return [sys.executable, str(Path(__file__).resolve()), *args]  # this file from a checkout


def hide_child_consoles() -> None:  # Windows only
    """The Windows app has no console, so every console program the engine starts (Node.js, poppler) would open a black
    window of its own. This makes every subprocess that this process starts later run without one."""
    if sys.platform != "win32":  # no other system opens a window for a console program
        return  # nothing to do
    original = subprocess.Popen.__init__  # the constructor every subprocess call goes through
    if getattr(original, "hides_consoles", False):  # an earlier call already replaced it
        return  # once is enough

    def init(self, *args, **kwargs):  # the same call with one more flag
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW  # the child's console window is never shown
        original(self, *args, **kwargs)  # the real constructor
    init.hides_consoles = True  # the mark the check above looks for
    subprocess.Popen.__init__ = init  # from now on


def as_engine_process() -> None:  # the first thing every role that runs the engine does
    """Set up this process to start other programs: they see the PC's library search path and open no console window."""
    node_runtime().restore_process_env()  # PyInstaller's own folder must not be first on the search path of Node.js, the browser or poppler
    hide_child_consoles()  # no black window per program on Windows


def prepare_runtime(data: Path, log: "CappedLog | None"):  # a failure here must not keep the panel from starting
    """The Node.js the engine will use, unpacked into the data folder at the first start; None when this copy of the
    app carries none (a checkout) or when it could not be unpacked, which the log says. The panel works without it, and
    "Make PDFs" then says that typesetting is missing."""
    rt = node_runtime()  # the module
    try:  # the unpack reads the app's own files and writes about 120 MB
        found = rt.ensure(data, ROOT, say=lambda text: say(text, log))  # a few seconds the first time, none after
    except rt.UnpackError as exc:  # a full disk, a damaged app file, a folder the system will not run programs from
        say(f"the document tools could not be set up: {exc}", log)  # for the log; the panel keeps working
        return None  # no Node.js: documents are not made
    if found is not None:  # something to use
        say(f"Node.js {found.version or '(chosen by OFFEROWL_NODE)'} is ready ({found.source})", log)  # which one, in the log
    return found  # handed to server_env


def run_script(argv: list[str]) -> int:  # the engine starts its helper scripts with sys.executable
    """Run a Python script the way `python script.py args` does. src/resume.py starts its helper scripts (the figures,
    the checks) with sys.executable, which in the one-file app is this program and not a Python, so this program must
    be able to act as the interpreter for them. Nothing else is accepted: no options, no modules."""
    script = Path(argv[0])  # relative to the working folder, as python reads it
    if not script.is_file():  # nothing to run
        print(f"offerowl-app: no such script: {argv[0]}", file=sys.stderr)  # where the caller's pipe reads it
        return 2  # what python itself exits with for a missing file
    as_engine_process()  # the scripts start programs too
    sys.argv = [str(script), *argv[1:]]  # what the script sees as its own command line
    sys.path.insert(0, str(script.resolve().parent))  # the script's folder first, as python puts it
    runpy.run_path(str(script), run_name="__main__")  # a SystemExit raised by the script passes through with its code
    return 0  # the script ended without raising (main() turns an exception into a report and exit 1)


class CappedLog:  # a PC left running for weeks must not fill its disk
    """Text appended to `path` until it reaches `cap` bytes; it then becomes `path`.1 (replacing the older one) and a
    new file starts, so a log never holds more than twice the cap on disk."""

    def __init__(self, path: Path, cap: int = LOG_CAP):  # the default cap suits every log here
        self.path, self.cap = path, cap  # where and how much
        path.parent.mkdir(parents=True, exist_ok=True)  # logs/
        self.lock = threading.Lock()  # one writer at a time
        self.f = open(path, "ab")  # appended

    def write(self, data: bytes) -> None:  # called from the pump threads and from say()
        with self.lock:  # pump threads and say() may write at the same time
            if self.f.closed:  # a pump can still write after the log was closed
                return  # dropped quietly rather than raising inside a thread
            self.f.write(data)  # the bytes exactly as the child printed them
            self.f.flush()  # on disk now, so a crash keeps the last lines
            if self.f.tell() < self.cap:  # still under the cap
                return  # nothing more to do until the cap is reached
            self.f.close()  # full: rotate
            try:  # renaming can fail on Windows file locks
                os.replace(self.path, self.path.with_name(self.path.name + ".1"))  # the older file
                self.f = open(self.path, "ab")  # a fresh file under the original name
            except OSError:  # the older file is open elsewhere (an editor on Windows): start over
                self.f = open(self.path, "wb")  # truncated in place, so writing goes on

    def close(self) -> None:  # called once, at shutdown
        with self.lock:  # never closes in the middle of a write
            self.f.close()  # later writes see it closed and are dropped


def ui_lang() -> str:  # the message boxes speak the person's language
    """The language of the app's own message boxes: OFFEROWL_LANG, else Korean on a Korean Windows or locale, else English."""
    fixed = os.environ.get("OFFEROWL_LANG", "").strip().lower()[:2]  # an explicit choice
    if fixed in ("en", "ko"):  # only the two languages the boxes have words for
        return fixed  # an explicit choice beats any guess
    if sys.platform == "win32":  # the display language is surer than a locale variable here
        try:  # ctypes or the call may be missing
            import ctypes  # Windows' display language
            return "ko" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x12 else "en"  # 0x12 is the primary language id of Korean
        except (AttributeError, OSError):  # no windll, or the call failed
            return "en"  # English when the language cannot be read
    # the first locale variable set, in POSIX precedence order
    locale = next((os.environ[k] for k in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(k)), "")
    return "ko" if locale.lower().startswith("ko") else "en"  # ko_KR and plain ko both count as Korean


# The message boxes in Korean, keyed by their English (the logs stay English)
KO = {
    "Offerowl stopped because of an error. The details are in the logs folder of {path}.":
        "오류로 Offerowl이 멈췄습니다. 자세한 내용은 {path}의 logs 폴더에 있습니다.",
    # shown when another program holds the port
    "Another program is using the port Offerowl needs ({port}). Close that program, then start Offerowl again.":
        "다른 프로그램이 Offerowl이 쓰는 포트({port})를 쓰고 있습니다. 그 프로그램을 끈 뒤 Offerowl을 다시 켜세요.",
    "The Offerowl server did not start. The end of its log:": "Offerowl 서버가 시작하지 못했습니다. 기록의 끝:",  # shown when the first start fails
    "Offerowl's server keeps stopping. The end of its log:": "Offerowl 서버가 계속 멈춥니다. 기록의 끝:",  # shown when the restart limit is reached
    "Open Offerowl": "Offerowl 열기",  # the tray's default item, the panel
    "Open the data folder": "데이터 폴더 열기",  # the tray menu item for the logs and settings
    "Quit": "끝내기",  # the tray menu item that ends the app
}


def t(text: str, **values) -> str:  # every person-facing string goes through this one call
    """A message box's words in the app's language."""
    out = KO.get(text, text) if ui_lang() == "ko" else text  # unknown strings fall back to their English
    return out.format(**values) if values else out  # no values, no format: a stray brace cannot raise


def say(text: str, log: CappedLog | None = None) -> None:  # one stamped format for the console and the log
    """A line of this program's own, to its log and, when it has one, to its console."""
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + text  # stamped
    if log is not None:  # callers without a log still get console output
        log.write((line + "\n").encode("utf-8", "replace"))  # replace keeps one bad character from losing the line
    if sys.stdout is not None:  # a windowless app may have no stdout at all
        print(line, flush=True)  # flushed so a terminal or a pipe sees it at once


def tell(text: str, log: CappedLog | None = None) -> None:  # for problems the person has to act on
    """A problem the person has to know about. The Windows app has no console, so it is shown in a message box."""
    say(text, log)  # kept in the log too, for reading later
    if sys.platform == "win32" and FROZEN:  # only the windowless Windows app needs a box
        import ctypes  # Windows only, so imported here
        MB_ICONWARNING, MB_TOPMOST = 0x30, 0x40000  # a warning icon, and the box stays above the browser
        ctypes.windll.user32.MessageBoxW(None, text, "Offerowl", MB_ICONWARNING | MB_TOPMOST)  # blocks until the person closes it


def _windows_job():  # a crash or a Task Manager kill must not orphan the server
    """A Windows job object that ends every process in it when this program ends, however it ends: the server and what
    it started (the agent's CLI) do not outlive the app. None elsewhere, or when it cannot be made."""
    if sys.platform != "win32":  # job objects exist on Windows only
        return None  # callers read None as no job to join
    import ctypes  # Windows only, so imported here
    from ctypes import wintypes  # the Win32 handle and DWORD types

    class IoCounters(ctypes.Structure):  # IO_COUNTERS, needed only to lay out the struct below
        # six 64-bit counters, in Win32 order
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                      "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BasicLimits(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION, which holds LimitFlags
        # Win32 field order and sizes, or the call fails
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION, the form kill-on-close needs
        # the basic limits first, as Win32 lays it out
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 0x2000, 9  # the flag and the info class, as winnt.h numbers them
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # a private copy, so these argtypes touch nothing else
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE  # the default int return would cut a 64-bit handle
    # pointers and sizes passed at their real width
    kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)  # both handles passed at their full width
    job = kernel32.CreateJobObjectW(None, None)  # an unnamed job with default security
    if not job:  # no job: the app runs on without one
        return None  # the app still works; children may just outlive it
    info = ExtendedLimits()  # all zero except the flag set below
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE  # closing the last handle to the job ends every process in it
    # the job only helps once the flag is set on it
    if not kernel32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
        return None  # a job without the flag would not help
    return lambda proc: kernel32.AssignProcessToJobObject(job, int(proc._handle))  # _handle is the Popen's process handle on Windows


_JOIN_JOB = None  # set by run(): puts a new child into the job above


class Child:  # the same start, log and stop for run() and check()
    """One child process, its output written to a CappedLog. `starts` keeps when it was started, so one that keeps
    stopping is given up on instead of started for ever."""

    def __init__(self, name: str, cmd: list[str], env: dict, log: CappedLog):  # nothing starts until start() is called
        self.name, self.cmd, self.env, self.log = name, cmd, env, log  # what it is
        self.proc: subprocess.Popen | None = None  # the running process
        self.starts: list[float] = []  # when it was started

    def start(self) -> None:  # also called again by watch() after a stop
        # A group of its own: Ctrl+C reaches this program alone, which then stops the child in order.
        group = {"creationflags": CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" \
            else {"start_new_session": True}
        # output piped to the log; no stdin to block on
        self.proc = subprocess.Popen(self.cmd, cwd=str(ROOT), env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **group)
        if _JOIN_JOB is not None:  # Windows with a job: tie the child to this program
            _JOIN_JOB(self.proc)  # it now ends whenever this program ends
        self.starts.append(time.monotonic())  # counted by given_up() against the restart limit
        # a daemon, so a stuck pipe never blocks exit
        threading.Thread(target=self._pump, args=(self.proc,), name=f"{self.name}-log", daemon=True).start()

    def _pump(self, proc: subprocess.Popen) -> None:  # drains the pipe so a full buffer never stalls the child
        try:
            for line in iter(proc.stdout.readline, b""):  # every line it prints
                self.log.write(line)  # capped, so a chatty server cannot fill the disk
        finally:  # its output ended (or reading failed): each restart's pipe goes now, not whenever its process object is collected
            proc.stdout.close()

    def exited(self) -> int | None:  # polled by watch() and by the start-up waits
        """The exit code once it has ended; None while it runs (or before it was started)."""
        return None if self.proc is None else self.proc.poll()  # poll() never blocks, so watchers can call it freely

    def given_up(self) -> bool:  # stops a crash loop from restarting for ever
        count, within = RESTARTS  # the limit, kept in one place at the top
        now = time.monotonic()  # monotonic, so a clock change cannot skew the window
        return sum(1 for s in self.starts if now - s < within) >= count  # too many starts in the window means give up

    def stop(self, timeout: float = 10) -> None:  # used at quit and at the end of the check
        proc = self.proc  # a local copy, in case watch() restarts it meanwhile
        if proc is None or proc.poll() is not None:  # never started or already gone: nothing to stop
            return  # so a second stop is harmless
        if sys.platform == "win32":  # no SIGTERM, and ending one process leaves its children: the whole tree goes
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,  # /T takes the whole tree, /F does not wait
                           stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        else:  # POSIX: a signal the server can shut down on, to its whole group (its own session, start())
            self._signal(proc, signal.SIGTERM)  # a one-file build is a launcher and the server under it: both must hear it
        try:  # time to close down cleanly first
            proc.wait(timeout)  # waits for its own clean shutdown
        except subprocess.TimeoutExpired:  # it ignored the request or hung
            self._signal(proc, signal.SIGKILL)  # SIGKILL, which it cannot ignore
            proc.wait(5)  # reaped, so no zombie is left behind
        if sys.platform != "win32":  # what the launcher left of the group when it ended first
            self._signal(proc, signal.SIGKILL)  # nothing may keep the port after the app is gone

    @staticmethod
    def _signal(proc: subprocess.Popen, sig) -> None:  # the child's process group, or the child alone when the group is gone
        try:
            os.killpg(proc.pid, sig)  # the child leads its own group: the launcher and the server it started
        except (ProcessLookupError, PermissionError):  # the group has ended already
            try:
                proc.send_signal(sig)  # the launcher alone, if it is still there
            except ProcessLookupError:  # already gone
                pass


def _open(url: str, data=None, timeout: float = 3):  # every request to the local server goes through here
    """GET or POST one address on this PC, with no proxy (a manual proxy on Windows is not bypassed for 127.0.0.1)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # an empty ProxyHandler turns every proxy off
    return opener.open(url if data is None else data, timeout=timeout)  # a URL for a GET, a Request object for a POST


def health(port: int) -> dict | None:  # tells a running Offerowl apart from any other server
    """The panel's /health on this port, or None when nothing (or something that is not Offerowl) answers."""
    try:  # nothing listening raises, which means not running
        with _open(f"http://127.0.0.1:{port}/health", timeout=1.5) as r:  # a short timeout, since it is polled often
            body = json.loads(r.read() or b"{}")  # an empty body is read as an empty object
    except (OSError, ValueError):  # refused, timed out, or not JSON
        return None  # treated as no Offerowl here
    # only Offerowl's own answer counts
    return body if isinstance(body, dict) and body.get("ok") is True and body.get("app") == "offerowl" else None


def port_free(port: int) -> bool:  # asked before starting, so a clash can be explained
    """Nothing listens on the port (asked by connecting, so connections a stopped server left behind do not count)."""
    try:  # a refused connection means the port is free
        with socket.create_connection(("127.0.0.1", port), timeout=1):  # a connect, so stale TIME_WAIT entries do not count
            return False  # something answered, so the port is taken
    except OSError:  # refused or timed out: no listener
        return True  # safe to start the server on it


def free_port() -> int:  # the check must not collide with a running panel
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # closed again at once, which frees the port
        s.bind(("127.0.0.1", 0))  # port 0 lets the system pick an unused one
        return s.getsockname()[1]  # the server binds it once this socket closes


def wait_for(ready, timeout: float, every: float = 0.4) -> bool:  # polling, since the server sends no ready signal
    end = time.monotonic() + timeout  # monotonic, so a clock change cannot cut the wait
    while time.monotonic() < end:  # a slow PC gets the whole timeout
        if ready():  # checked first, so a fast start costs no sleep
            return True  # no need to wait out the timeout
        time.sleep(every)  # a short pause so polling stays cheap
    return bool(ready())  # one last look at the deadline itself


def tail(path: Path, lines: int = 12) -> str:  # the last lines go into the error box
    try:  # the log may not exist yet
        # bad bytes replaced so a broken line still shows
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:  # a missing or unreadable log
        return ""  # the box then just has no log part


def only_one(data: Path):  # two copies would fight over the port and the data
    """The lock that makes this the one copy of the app running on this PC: an open file the system releases when the
    process ends, however it ends. None when another copy holds it."""
    data.mkdir(parents=True, exist_ok=True)  # the first run has no data folder yet
    f = open(data / "app.lock", "a+", encoding="utf-8")  # a+ creates the file and never empties it
    try:  # a lock held elsewhere raises OSError
        if sys.platform == "win32":  # Windows has no flock
            import msvcrt  # Windows only, so imported here
            f.seek(0)  # msvcrt locks from the current position: byte 0 every time
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)  # a non-blocking lock on one byte
        else:  # macOS and Linux use flock
            import fcntl  # POSIX only, so imported here
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # exclusive and non-blocking, so it fails at once if held
    except OSError:  # another copy holds the lock
        f.close()  # no handle kept that cannot be used
        return None  # the caller then waits for the other copy
    return f  # kept open for the app's whole life


def _stop_on_signals() -> None:  # a logout or a kill must still stop the server
    """SIGTERM and SIGHUP end this program the way Ctrl+C does: through the cleanup in run(), which stops the server."""
    if sys.platform == "win32":  # Windows has neither signal
        return  # the job object covers Windows instead
    import signal  # only needed off Windows

    def stop(*_):  # a signal handler is given (signum, frame)
        raise KeyboardInterrupt  # reuses run()'s Ctrl+C path and its finally block
    signal.signal(signal.SIGTERM, stop)  # sent by kill and by service managers
    signal.signal(signal.SIGHUP, stop)  # sent when the terminal closes or the session ends


def open_folder(path: Path) -> None:  # for the tray's data folder item
    """Show a folder in the system's file manager."""
    if sys.platform == "win32":  # Explorer opens it through the file association
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":  # macOS opens folders in Finder
        subprocess.Popen(["open", str(path)])  # not waited on, so the menu never freezes
    elif shutil.which("xdg-open"):  # Linux desktops, when the opener is installed
        subprocess.Popen(["xdg-open", str(path)])  # not waited on, so the menu never freezes


def tray_image(size: int = 64):  # drawn in code, so no image file has to ship
    """The app's mark of docs/assets/icon.svg, drawn at `size` pixels: an envelope (the offer) whose flap is an owl's brow,
    two ear tufts and two amber eyes. Used by the icon by the clock and, large, by the Windows and macOS app icons."""
    from PIL import Image, ImageDraw  # only with the tray
    navy, paper, amber = (27, 46, 75, 255), (255, 255, 255, 255), (242, 199, 68, 255)  # owl navy, paper and lamp amber, as icon.svg has them
    big = max(256, size * 4)  # drawn large, shrunk smooth
    u = big / 64.0  # one unit of the 64-unit mark
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))  # transparent, so only the mark's shape shows
    d = ImageDraw.Draw(img)  # draws onto the image in place
    P = lambda pts: [(x * u, y * u) for x, y in pts]  # noqa: E731  the mark's units to pixels
    d.polygon(P([(9.5, 17.5), (13.2, 4.8), (23.5, 13)]), fill=navy)  # the left ear tuft
    d.polygon(P([(54.5, 17.5), (50.8, 4.8), (40.5, 13)]), fill=navy)  # the right one
    d.rounded_rectangle([7 * u, 11 * u, 57 * u, 57 * u], radius=10.5 * u, fill=navy)  # the envelope's body, the owl's head
    brow = P([(13.5, 19), (29.4, 29.6), (32, 31), (34.6, 29.6), (50.5, 19)])  # the flap: the brow, softened at its point
    w = 4.2 * u  # its stroke
    d.line(brow, fill=paper, width=int(round(w)), joint="curve")  # drawn as one line
    for x, y in (brow[0], brow[-1]):  # round ends, as the SVG's stroke-linecap
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=paper)
    for cx in (20.6, 43.4):  # the eyes
        d.ellipse([(cx - 7.6) * u, 31 * u, (cx + 7.6) * u, 46.2 * u], fill=amber)  # lamp amber
    for cx in (21.8, 42.2):  # the pupils, looking a little up and in
        d.ellipse([(cx - 3) * u, 34.6 * u, (cx + 3) * u, 40.6 * u], fill=navy)
    return img.resize((size, size), Image.LANCZOS)  # LANCZOS keeps the edges smooth


# Where the agents' installers and the usual version managers put their programs, for a login shell that gives no answer
AGENT_FOLDERS = (".local/bin", ".claude/local", ".npm-global/bin", ".bun/bin", ".volta/bin", ".cargo/bin", ".nix-profile/bin")


def login_path(env: dict | None = None) -> str:
    """The PATH of the person's own login shell, or an empty text. Finder and a desktop menu start a program with a short PATH
    that lacks the folders the person's shell adds, so Claude Code and Codex would look absent. Asked once, with a time limit, in a
    session of its own, so an interactive shell cannot take a terminal or stop this program, and writing to a file, so a job its
    start-up files leave running cannot hold the answer."""
    env = os.environ if env is None else env  # tests pass their own
    shell = env.get("SHELL") or ("/bin/zsh" if sys.platform == "darwin" else "/bin/bash")  # the shell each system starts for a new user
    mark = "__offerowl_path__"  # what a shell's own greeting cannot be taken for
    try:  # -i reads the files people put their PATH in, -l the login ones
        with tempfile.TemporaryFile() as out:  # read back once the shell has ended
            proc = subprocess.Popen([shell, "-ilc", f'printf "%s%s" "{mark}" "$PATH"'], env=dict(env), stdin=subprocess.DEVNULL, stdout=out,  # nothing to read from
                                    stderr=subprocess.DEVNULL, start_new_session=True)  # no terminal
            try:
                proc.wait(timeout=5)  # a slow start-up file costs this much at most
            except subprocess.TimeoutExpired:  # it never answers
                os.killpg(proc.pid, 9)  # the shell and what it started
                proc.wait()  # gone
                return ""  # the short PATH and the usual folders are what there is
            out.seek(0)  # from the start
            got = out.read().decode("utf-8", "replace")  # what it wrote
    except (OSError, ValueError):  # no such shell
        return ""  # the same
    return got.rpartition(mark)[2].strip() if mark in got else ""  # the words after the mark


def widen_path(env: dict | None = None) -> str:
    """Add to PATH the folders of the login shell and the usual folders of an agent's installer that exist, after what PATH
    already holds. Windows keeps the person's PATH for a double-click, so it is left alone. Returns the new PATH."""
    env = os.environ if env is None else env  # tests pass their own
    if sys.platform == "win32":  # a double-click there has the whole PATH
        return env.get("PATH", "")  # as it is
    home = Path(env.get("HOME") or Path.home())  # the person's folder
    have = [p for p in env.get("PATH", "").split(os.pathsep) if p]  # what this start was given, first
    started_in_a_terminal = bool(sys.stdin and sys.stdin.isatty())  # then PATH is the shell's already
    more = ([] if started_in_a_terminal else login_path(env).split(os.pathsep)) + [str(home / f) for f in AGENT_FOLDERS] + ["/opt/homebrew/bin", "/usr/local/bin"]  # the shell's, then the usual ones
    for p in more:  # in that order
        if p and p not in have and os.path.isdir(p):  # new, and there
            have.append(p)  # after what was there, so a program this start chose stays first
    env["PATH"] = os.pathsep.join(have)  # the agents' cards and the engine look here
    return env["PATH"]  # for the tests and the log


def run(args) -> int:  # the normal start, from a double-click
    """Start the server, open the panel, show the icon, and start the server again when it stops."""
    global _JOIN_JOB  # Child.start() reads it at module level
    widen_path()  # before anything looks for an agent
    _JOIN_JOB = _windows_job()  # made first, before any child exists
    _stop_on_signals()  # before the server starts, so no signal is missed
    data = data_dir()  # the data folder
    log = CappedLog(data / "logs" / "app.log")  # this program's log
    port = args.port  # --port or OFFEROWL_PANEL_PORT, else the default
    url = f"http://127.0.0.1:{port}/"  # the address the browser is sent to
    if health(port):  # already running (a second start): open the panel and leave it at that
        if not args.no_browser:  # --no-browser is kept on a second start too
            webbrowser.open(url)  # brings the running panel up for the person
        log.close()  # nothing more for this copy to log
        return 0  # a second start is not an error
    lock = only_one(data)  # taken before the port check, so two starts cannot race
    if lock is None:  # another copy is starting: its panel opens when its server is up
        say("Offerowl is already starting; waiting for it", log)  # logged, so a slow start can be explained
        if wait_for(lambda: health(port) is not None, timeout=120) and not args.no_browser:  # the first copy may still be starting its server
            webbrowser.open(url)  # opens the other copy's panel once it is up
        log.close()  # nothing more for this copy to log
        return 0  # the other copy does the work
    if not port_free(port):  # a foreign program on the port: say so, do not guess
        # the person has to free the port; the box says how
        tell(t("Another program is using the port Offerowl needs ({port}). Close that program, then start Offerowl again.", port=port), log)
        log.close()  # nothing more to log
        return 1  # a start that did not happen
    runtime = prepare_runtime(data, log)  # Node.js for the documents: unpacked now at the first start, found at every later one
    env = server_env(os.environ, data, port, runtime)  # the server's environment
    # the server's console output goes to its own capped log
    server = Child("server", role_cmd("--serve", "--port", str(port)), env, CappedLog(data / "logs" / "server-console.log"))
    stop = threading.Event()  # set by the icon's Quit, or when the server is given up on
    code = {"exit": 0}  # this program's exit code
    try:  # whatever happens below, finally stops the server
        server.start()  # the panel's server, as a child process
        say(f"starting the server on {url}", log)  # the log shows which port was used
        # up, or exited early: either one ends the wait
        if not wait_for(lambda: health(port) is not None or server.exited() is not None, timeout=60) or health(port) is None:
            tell(t("The Offerowl server did not start. The end of its log:") + "\n\n" + tail(server.log.path), log)  # the log tail tells why
            return 1  # finally still stops whatever started
        say("the server is up", log)  # marks a good start in the log
        if not args.no_browser:  # --no-browser leaves the browser alone
            webbrowser.open(url)  # the panel is ready to use now
        # a daemon, so it never holds up the exit
        watcher = threading.Thread(target=watch, args=(server, log, stop, code), name="watch", daemon=True)
        watcher.start()  # restarts the server when it stops
        tray = None if args.no_tray else make_tray(url, data, stop, log)  # the notification-area icon and what runs once it shows
        if tray is not None:  # this system has a tray
            icon, ready = tray  # the icon, and its watch on the stop
            icon.run(setup=ready)  # its loop takes this thread until Quit (it must be the main thread on macOS)
        else:  # no tray: keep the process alive another way
            while not stop.wait(1):  # no icon: wait for Ctrl+C or a stop
                pass  # the wait itself is the work
        return code["exit"]  # 1 when watch() gave up on the server
    except KeyboardInterrupt:  # Ctrl+C, or SIGTERM and SIGHUP turned into it
        return 0  # a requested stop is a clean exit
    finally:  # runs on every way out
        stop.set()  # ends the watcher, so it does not restart the server
        server.stop()  # the server does not outlive the app
        say("stopped", log)  # the log shows a clean end
        log.close()  # last, after the final line is written


def on_icon_loop(fn, *args) -> None:  # every call that touches the icon from another thread
    """Run fn(*args) where the icon can take it: on macOS in AppKit's own queue, since pystray's loop there is the main thread's
    and a call from another thread may do nothing; elsewhere at once."""
    if sys.platform == "darwin":  # pystray runs NSApplication on the main thread
        try:  # PyObjC comes with pystray on macOS
            from PyObjCTools import AppHelper  # the main thread's queue
            AppHelper.callAfter(fn, *args)  # runs once the loop takes it
            return
        except ImportError:  # no PyObjC: the direct call below is all there is
            pass
    fn(*args)


def make_tray(url: str, data: Path, stop: threading.Event, log: CappedLog):  # kept apart so run() works with no tray at all
    """The notification-area icon with Open, the data folder and Quit, and the function its loop runs once the icon is up
    (pystray's setup): (icon, ready). None where there is no tray (no pystray, no display)."""
    try:  # pystray, Pillow or a display may be missing
        import pystray  # optional: the app is still whole without it
        image = tray_image()  # Pillow may be missing too
    except Exception as exc:  # no package, or no display to put an icon on
        say(f"no tray icon: {type(exc).__name__}", log)  # logged, so a missing icon can be explained
        return None  # run() then waits without an icon

    def quit_app(icon, _item=None):  # what the Quit item does
        stop.set()  # the watcher ends
        icon.stop()  # the loop ends, run() cleans up
    # default: a click on the icon opens the panel
    menu = pystray.Menu(pystray.MenuItem(t("Open Offerowl"), lambda: webbrowser.open(url), default=True),
                        pystray.MenuItem(t("Open the data folder"), lambda: open_folder(data)),
                        pystray.MenuItem(t("Quit"), quit_app))
    icon = pystray.Icon("offerowl", image, "Offerowl", menu)  # shows the owl, with the app's name on hover

    def ready(icon):  # pystray calls this in a thread of its own once the loop runs, so a stop asked for before that is not lost
        icon.visible = True  # what pystray does when no setup is given
        stop.wait()  # until Quit, or the server given up on
        try:  # the icon may already be stopped
            on_icon_loop(icon.stop)  # makes icon.run() return in run()
        except Exception:  # stopping twice must not crash the thread
            pass  # nothing is left to do

    def remind():  # reminders the tracker says are due, shown even when the browser is closed
        shown = set()  # (job, reminder) pairs already shown, so each appears once per run
        while not stop.wait(60):  # once a minute until the app stops
            try:  # the server may be restarting, or the answer unreadable
                with _open(url.rstrip("/") + "/api/v1/reminders/due") as r:  # the API's list of due reminders
                    due = json.loads(r.read().decode("utf-8")) or []  # a list of {job, id, name, text}
                for d in due:  # each due reminder
                    key = (d.get("job"), d.get("id"))  # what makes it the same reminder
                    if key in shown:  # already shown in this run
                        continue  # once is enough
                    shown.add(key)  # remembered before showing, so a failing notify is not retried every minute
                    on_icon_loop(icon.notify, f"{d.get('name', '')}: {d.get('text', '')}", "Offerowl")  # the system notification
            except Exception:  # a missed minute is harmless; the next one tries again
                pass  # nothing to do until then
    threading.Thread(target=remind, daemon=True, name="reminders").start()  # a daemon, like the watcher
    return icon, ready  # run() starts the loop on the main thread, with ready as its setup


def watch(server: Child, log: CappedLog, stop: threading.Event, code: dict) -> None:  # keeps the panel up when the server crashes
    """Start the server again when it stops, until the app is quit or the server keeps stopping."""
    while not stop.wait(1):  # checks once a second, ends as soon as stop is set
        if server.exited() is None:  # polled, so the loop never blocks on it
            continue  # running
        if server.given_up():  # too many restarts: stop instead of looping
            tell(t("Offerowl's server keeps stopping. The end of its log:") + "\n\n" + tail(server.log.path), log)  # the log tail tells why
            code["exit"] = 1  # the app's exit code reports the failure
            stop.set()  # ends the tray loop and run()
            return  # this thread is done
        say(f"the server stopped (exit {server.exited()}); starting it again", log)  # each restart leaves a line with its exit code
        server.start()  # counted in starts for the next given_up()


def watch_parent() -> threading.Thread | None:  # the server never outlives the app, however the app ended
    """A POSIX child in a session of its own lives on when the app is killed, and macOS has no PR_SET_PDEATHSIG to end it.
    So once a second the server asks whether the app that started it (OFFEROWL_APP_PARENT) still runs, and stops itself
    with its own clean SIGTERM when it does not. Windows ties the server to the app with a job instead (run()). Returns the
    watching thread, or None when there is nothing to watch."""
    parent = os.environ.get("OFFEROWL_APP_PARENT", "")  # the app's process id, from server_env()
    if sys.platform == "win32" or not parent.isdigit():  # Windows has its job; a server started by hand has no app
        return None

    def watch() -> None:  # a daemon: it ends with the server
        while True:  # until the app is gone
            time.sleep(1)  # a second is soon enough, and costs nothing
            try:  # signal 0 asks whether the process is there without touching it
                os.kill(int(parent), 0)
            except ProcessLookupError:  # the app is gone
                os.kill(os.getpid(), signal.SIGTERM)  # the server's own clean stop, as a container's stop would ask
                return
            except PermissionError:  # there, under another user: alive
                pass
    thread = threading.Thread(target=watch, name="app-parent", daemon=True)  # beside the server's own threads
    thread.start()
    return thread


def serve(port: int) -> int:  # the child role, so one file holds both programs
    """The panel's server itself, in this process (the --serve role)."""
    watch_parent()  # it stops when the app that started it is gone
    as_engine_process()  # the server starts Node.js, the browser and poppler: they must see the PC's libraries, with no console window
    sys.path.insert(0, str(ROOT))  # apps/ is found from here
    from apps.panel import server as panel  # noqa: E402
    return panel.main(["--port", str(port)])  # the panel's own exit code becomes this one


def smoke() -> int:  # the --smoke role, started by check() with the server's environment
    """Make the example resume, deck and cover letter with the Node.js and the libraries this program carries, the way the
    panel's "Make PDFs" does, and print one line for each step: `ok ...`, `skip ...` or `FAIL ...`. Exit 1 on a FAIL.
    OFFEROWL_CHECK_DOCUMENTS=required makes a missing browser a failure instead of a skip."""
    as_engine_process()  # the same set-up as the server's engine processes
    sys.path.insert(0, str(ROOT / "src"))  # the engine's modules import as top-level names
    failed = []  # steps that failed

    def out(kind: str, text: str) -> None:  # one line per step, flushed so a hang leaves what was done
        print(f"{kind} {text}", flush=True)  # check() reads these lines
        if kind == "FAIL":  # counted
            failed.append(text)  # for the exit code

    def run(cmd: list, **kw) -> subprocess.CompletedProcess:  # every program here has a time limit
        return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, **kw)  # output kept for the message
    try:  # the engine's build commands
        import resume  # src/resume.py, as the panel's tasks use it
        node = resume.node()  # the Node.js the engine will start
        r = run([node, "--version"])  # does it start?
        chosen = os.environ.get("OFFEROWL_NODE", "")  # the program this app handed over
        ours = not chosen or (os.path.exists(node) and os.path.samefile(node, chosen))  # the engine found that one and not another on the PC
        out("ok" if r.returncode == 0 and ours else "FAIL", f"documents: the engine runs Node.js {r.stdout.strip()}" + ("" if ours else ", not the one the app unpacked"))  # the version
        r = run([node, "-e", "for (const n of ['docx', 'jszip', 'opentype.js']) require(n)"])  # the writers' libraries, from the engine's folder
        out("ok" if r.returncode == 0 else "FAIL", "documents: docx, jszip and opentype.js load" if r.returncode == 0 else f"documents: a library does not load: {(r.stderr or r.stdout)[-400:]}")  # node's own error
        leak = str(ROOT) in run([node, "-p", "process.env.LD_LIBRARY_PATH || ''"]).stdout  # what a program of the PC inherits from this one
        out("FAIL" if leak else "ok", "documents: programs the engine starts " + ("inherit the app's library folder" if leak else "do not inherit the app's library folder"))  # PyInstaller's search path must not leak
        missing = resume.html_missing()  # what the browser renderer lacks on this PC
        if missing == ["browser"] and os.environ.get("OFFEROWL_CHECK_DOCUMENTS") != "required":  # no Chrome, Edge or Chromium here
            out("skip", "documents: no Chrome, Edge or Chromium on this PC, so no PDF was printed")  # the writers above still ran
        elif missing:  # a part the app should have brought
            out("FAIL", "documents: the browser renderer lacks " + resume.missing_words(missing))  # named in plain words
        else:  # everything is there: print
            R = resume.html_renderer()  # src/render_html/render.py, for the page count of a PDF
            example = str(resume.EXAMPLE)  # the fictional person
            pdf = resume.build(example)  # the resume: figures, DOCX, PDF
            pages, deck = R.pdf_pages(pdf), resume.build_deck(example)  # its pages, and the deck
            with zipfile.ZipFile(pdf.with_suffix(".docx")) as z:  # the Word file that came with it
                named = resume.WANT[0] in z.read("word/document.xml").decode("utf-8")  # the person's name is in it
            out("ok" if pages == resume.RESUME_PAGES and named else "FAIL", f"documents: resume of {pages} pages (expected {resume.RESUME_PAGES}), DOCX holds the name: {named}")  # the engine's own expectations
            slides = R.pdf_pages(deck)  # the deck's pages
            out("ok" if slides == resume.DECK_SLIDES else "FAIL", f"documents: deck of {slides} slides (expected {resume.DECK_SLIDES})")  # likewise
            import cover  # src/cover.py, which builds the letter through the same switch
            letter = cover.build(example, str(ROOT / "examples" / "cover" / "cover_ko.json"))  # the example letter, typeset
            out("ok" if letter["pages"] == 1 else "FAIL", f"documents: cover letter of {letter['pages']} pages (expected 1)")  # a letter is one page
    except SystemExit as exc:  # the engine stops with the tool's own message
        out("FAIL", f"documents: the engine stopped: {str(exc)[-500:]}")  # for the build log
    except Exception as exc:  # a missing program, a timeout, a missing module
        out("FAIL", f"documents: {type(exc).__name__}: {str(exc)[-500:]}")  # the same
    return 1 if failed else 0  # check() reads the lines, build.py the exit code


def mcp_check(port: int) -> tuple[list[str], int]:  # run by check() against its own server
    """The agent's tools, started the way the command bar starts them (apps/api/ask.py mcp_server: this program as the
    interpreter of apps/mcp/__main__.py, with the requests on its stdin): it must answer initialize and list its tools.
    (the problems found, [] when there are none; the number of tools it listed)."""
    import types  # an object with the one attribute mcp_server reads
    sys.path.insert(0, str(ROOT))  # apps/, from the bundle or the checkout
    from apps.api import ask  # the command bar's own way of starting it
    cmd, args, extra = ask.mcp_server(types.SimpleNamespace(port=port))  # pointed at this check's server
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                            "clientInfo": {"name": "offerowl-check", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},  # no reply
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]  # the tools the agent would get
    try:  # a server that never answers must fail the check, not hang it
        done = subprocess.run([cmd, *args], input="\n".join(json.dumps(m) for m in msgs) + "\n", env={**os.environ, **extra},
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)  # stdin closes after the last line: it ends
    except subprocess.TimeoutExpired:  # no end in two minutes
        return ["the agent's tools (MCP) did not end in 2 minutes"], 0
    replies = {}  # each answer by its id
    for line in done.stdout.splitlines():  # one JSON message per line
        try:
            msg = json.loads(line)
        except ValueError:  # not protocol: the check says what came instead below
            continue
        replies[msg.get("id")] = msg
    tools = (((replies.get(2) or {}).get("result") or {}).get("tools")) or []  # the list the agent would read
    if not (replies.get(1) or {}).get("result") or not tools:  # no handshake, or no tools
        return [f"the agent's tools (MCP) did not answer: exit {done.returncode}: " + ((done.stderr or "") + (done.stdout or ""))[-600:]], 0
    return [], len(tools)  # it answered with its tools


def check() -> int:  # run by build.py on the built file
    """Start the server with the stand-in agent on a free port, fetch its health and its page, add a small text file,
    let the stand-in read it through src/ingest.py and src/llm.py, and stop. A copy of the app that carries Node.js
    also unpacks it and makes the example resume, deck and cover letter (see smoke). Exit 0 when all of it worked."""
    problems = []  # what failed
    notes = []  # lines that are not failures: what was skipped
    for name in ("ingest", "review", "draft", "llm", "factcheck", "resume"):  # the engine modules the panel imports
        try:  # one failure must not hide the others
            sys.path.insert(0, str(ROOT / "src"))  # the engine's modules import as top-level names
            __import__(name)  # a real import, as the panel would do it
        except Exception as exc:  # a module the build left out shows up here, not at the first click
            problems.append(f"import {name}: {type(exc).__name__}: {exc}")  # recorded, and the check goes on
    port = free_port()  # never the panel's own port
    # throwaway data, so the person's own is never touched; Windows may still hold the unpacked program when the folder goes
    with tempfile.TemporaryDirectory(prefix="offerowl-check-", ignore_cleanup_errors=True) as d:
        rtm = node_runtime()  # the module that unpacks Node.js
        try:  # this is the first start in a data folder that is empty, so the unpack is tested too
            runtime = rtm.ensure(Path(d), ROOT)  # None for a copy that carries no Node.js
        except rtm.UnpackError as exc:  # a damaged app file, a full disk, a folder the system will not run programs from
            runtime = None  # no documents without it
            problems.append(f"Node.js could not be unpacked: {exc}")  # the check fails: this app could not make documents
        env = server_env(os.environ, Path(d), port, runtime)  # the same environment the real start uses
        env.update(OFFEROWL_PANEL_AGENT="standin")  # the stand-in agent
        log = CappedLog(Path(d) / "server.log")  # inside the temp folder, removed along with it
        server = Child("server", role_cmd("--serve", "--port", str(port)), env, log)  # the same --serve role the app uses
        server.start()  # the real server code, not a mock
        # up, or exited early: health then decides
        up = wait_for(lambda: health(port) is not None or server.exited() is not None, timeout=60) and health(port)
        base = f"http://127.0.0.1:{port}"  # every request below goes to this server
        if not up:  # no server, so no API checks
            problems.append("the server did not answer /health:\n" + tail(Path(d) / "server.log", 30))  # the log tail tells why
        else:  # the server answered: try the page and the API
            try:  # any failure below becomes one problem line
                with _open(base + "/", timeout=10) as r:  # the page the browser would load
                    if "<html" not in r.read().decode("utf-8", "replace").lower():  # a page, not an error body
                        problems.append("GET / did not return the panel")  # recorded, and the API checks still run
                # a small project line the stand-in can find a fact in
                note = "Project: Example Co | 2023.01 ~ 2023.06 | Payment service rewrite | Split the payment path from the order service\n"
                # sent as a raw file, as the panel's file picker does
                req = urllib.request.Request(base + "/api/v1/materials", data=note.encode("utf-8"), method="POST",
                                             headers={"Content-Type": "application/octet-stream", "X-File-Name": "check.txt"})
                with _open(req, timeout=10) as r:  # the upload must succeed to go on
                    mid = json.loads(r.read())["material"]["id"]  # the material's id
                # asks the engine to read the uploaded file
                req = urllib.request.Request(base + "/api/v1/materials/read", data=json.dumps({"ids": [mid]}).encode(), method="POST",
                                             headers={"Content-Type": "application/json"})
                _open(req, timeout=10).close()  # the stand-in reads it

                def facts_found():  # ingest runs in the background, so its state is polled
                    with _open(base + "/api/v1/state", timeout=10) as r:  # the panel's whole state, tasks included
                        st = json.loads(r.read())  # parsed once per poll
                    return st if (st["tasks"].get("ingest") or {}).get("state") in ("done", "error") else None  # finished either way ends the wait
                st = None  # no result until the poll below
                wait_for(lambda: (facts_found() or None) is not None, timeout=60)  # up to a minute for ingest to finish
                st = facts_found()  # the final state, read once more after the wait
                if not st or st["facts"]["counts"]["found"] < 1:  # ended in error, or the stand-in found nothing
                    # the tasks show what failed
                    problems.append("the stand-in found no fact in the check's file: " + json.dumps((st or {}).get("tasks")))
                if (st or {}).get("version") in (None, "", "0"):  # the bar beside the wordmark would say v0: the version file is not in the app
                    problems.append("the panel does not know its version: " + repr((st or {}).get("version")))
                else:  # said, so a passing check shows what it saw
                    notes.append("ok the panel's version: " + str(st["version"]))
                bad, tools = mcp_check(port)  # the command bar's tools
                problems += bad
                if not bad:
                    notes.append(f"ok the agent's tools (MCP): {tools} tools, started as the command bar starts them")
            except Exception as exc:  # a broken API must fail the check, not crash it
                problems.append(f"the panel's API: {type(exc).__name__}: {exc}")  # names the exception so the cause is visible
        mode = os.environ.get("OFFEROWL_CHECK_DOCUMENTS", "auto").strip().lower()  # auto: when the app carries Node.js; required: always, and a missing browser fails; off: never
        if mode == "off" or (mode == "auto" and runtime is None):  # nothing to test
            notes.append("skip documents: " + ("switched off" if mode == "off" else "this copy of the app carries no Node.js"))  # said, not hidden
        elif runtime is None:  # required, and the unpack failed above
            problems.append("documents: required, but there is no Node.js")  # the failure above has the reason
        else:  # make the example documents with the Node.js that was just unpacked
            try:  # a hung browser must fail the check, not hang the build
                done = subprocess.run(role_cmd("--smoke"), env={**env, "OFFEROWL_CHECK_DOCUMENTS": mode}, cwd=str(ROOT), capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=600)  # the same environment as the server's engine
                lines = [ln.strip() for ln in done.stdout.splitlines() if ln.startswith(("ok ", "skip ", "FAIL "))]  # the steps it reported
                problems += [ln[5:] for ln in lines if ln.startswith("FAIL ")]  # failed steps
                notes += [ln for ln in lines if not ln.startswith("FAIL ")]  # passed and skipped steps
                if done.returncode != 0 and not any(ln.startswith("FAIL ") for ln in lines):  # it died before it could say why
                    problems.append("documents: the document check stopped with exit " + str(done.returncode) + ": " + (done.stderr or "")[-600:])  # its last words
            except subprocess.TimeoutExpired:  # no answer in ten minutes
                problems.append("documents: the document check did not finish in 10 minutes")  # a hung print
        server.stop()  # before the temp folder is removed under it
        log.close()  # Windows cannot delete a file that is still open
    report = [f"FAIL {p}" for p in problems] + notes + ["ok" if not problems else f"{len(problems)} problem(s)"]  # one FAIL line each, the steps that passed or were skipped, then a summary line
    print("\n".join(report))  # for a --check run from a console
    if os.environ.get("OFFEROWL_CHECK_LOG"):  # the Windows app has no console: build.py reads the file
        Path(os.environ["OFFEROWL_CHECK_LOG"]).write_text("\n".join(report) + "\n", encoding="utf-8")  # the report build.py prints
    return 1 if problems else 0  # build.py fails the build on a non-zero exit


def main(argv: list[str] | None = None) -> int:  # the one entry for the app and a checkout
    """Run the role the command line names. An exception ends in a report and exit 1: the windowless app would otherwise stop
    at PyInstaller's own dialog and wait for a click, which for a helper process nobody can see means forever."""
    argv = list(sys.argv[1:] if argv is None else argv)  # a copy, so a caller's own list is never changed
    try:  # every role below
        return roles(argv)  # its exit code
    except Exception:  # noqa: BLE001  whatever it was, it is reported and not left to the bootloader
        report = traceback.format_exc()  # what happened
        print(report, file=sys.stderr)  # for the program that started this one
        helper = bool(argv) and (argv[0].lower().endswith(".py") or argv[0] in ("--serve", "--smoke", "--check"))  # a process with no person at its screen
        try:  # the person's log, when the data folder can be written
            log = CappedLog(data_dir() / "logs" / "app.log")
            log.write(report.encode("utf-8"))
            log.close()
        except OSError:  # no log then: the exit code still says it failed
            pass
        if not helper:  # the app a person started: it says so once
            tell(t("Offerowl stopped because of an error. The details are in the logs folder of {path}.", path=data_dir()))
        return 1  # a failure, with no dialog of the bootloader's


def roles(argv: list[str]) -> int:  # one process plays one of these
    """The script interpreter, the server, the document check, the app's own check, or the app itself."""
    script = bool(argv) and not argv[0].startswith("-") and argv[0].lower().endswith(".py")  # started as `Offerowl script.py ...` by the engine
    for name, fd in (("stdout", 1), ("stderr", 2)):  # the two output streams
        if getattr(sys, name) is None:  # the Windows app is built with no console
            stream = None  # nothing yet
            if script:  # a script's output belongs to the engine that started it, which may have given this process pipes
                try:  # the pipe is file descriptor 1 or 2 if there is one
                    stream = open(fd, "w", encoding="utf-8", errors="replace", closefd=False)  # not closed with the stream: it is the process's own
                except OSError:  # the process has no such descriptor
                    stream = None  # the null device below
            setattr(sys, name, stream or open(os.devnull, "w", encoding="utf-8"))  # code that writes to the stream directly would raise without one
    if script and sys.stdin is None:  # the Windows app has no console: a script reads what its caller pipes in (the agent's MCP server reads its requests there)
        try:  # the caller's pipe is file descriptor 0 if there is one
            sys.stdin = open(0, "r", encoding="utf-8", errors="replace", closefd=False)  # not closed with the stream: it is the process's own
        except OSError:  # no such descriptor: reads end at once
            sys.stdin = open(os.devnull, "r", encoding="utf-8")
    if script:  # the engine uses this program as its Python
        return run_script(argv)  # the script's own exit code
    # prog names the app in usage and error lines
    ap = argparse.ArgumentParser(prog="offerowl-app", description="Start Offerowl's panel on this PC and open it.")
    # the panel's own variable moves the app's port too
    ap.add_argument("--port", type=int, default=int(os.environ.get("OFFEROWL_PANEL_PORT") or PORT), help=f"the panel's port (default {PORT})")
    ap.add_argument("--no-browser", action="store_true", help="do not open the panel")  # for starts from a script or a service
    ap.add_argument("--no-tray", action="store_true", help="no icon in the notification area")  # for systems with no tray, or a headless run
    ap.add_argument("--check", action="store_true", help="start with a stand-in agent on a free port, read one file, stop")  # build.py's smoke test
    ap.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)  # the server's own role
    ap.add_argument("--smoke", action="store_true", help=argparse.SUPPRESS)  # the document check's own role
    args = ap.parse_args(argv)  # exits with a usage line on bad options
    if args.serve:  # the child role first: it must not start another app
        return serve(args.port)  # the server's exit code is the child's
    if args.smoke:  # started by --check
        return smoke()  # 1 when a step failed
    if args.check:  # the check needs no tray, lock or browser
        return check()  # 0 when all of it worked
    return run(args)  # no role flag: the normal start


if __name__ == "__main__":  # run as a script from a checkout
    raise SystemExit(main())  # the return value becomes the process exit code
