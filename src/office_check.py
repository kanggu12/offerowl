# -*- coding: utf-8 -*-
"""Opening a finished Word or PowerPoint file in the Microsoft Office on this PC, as the person who receives it will.

Word lays out a DOCX by itself, and the same file can take more pages in Word than in the PDF that LibreOffice or the
browser printed from it: a resume whose PDF had six pages took seven in Word. So before a Word copy goes to the Desktop
the export asks Word how many pages it has, and before a PowerPoint copy goes, PowerPoint how many slides; a count that
differs from the PDF's keeps that one file home (apps/api/tasks.py, Tasks.export).

Office is reached on Windows, and from WSL through Windows' own PowerShell. On macOS, Linux and in a container
available() is False and nothing is asked; OFFEROWL_OFFICE=0 never asks either.

Each question starts the program through COM for that one file and never shows it: Word with Visible off, PowerPoint
with no window. It opens a copy, read-only and never saved, in a folder of its own with an ASCII name under Windows'
temporary folder (PowerShell 5.1 can garble a path with Korean in it). The program quits only when no other document is
open in it, so a PowerPoint the person has open stays as it was. A program this question started that is still there
after a failure or a time-out is ended by its own process id, never by its name.

    python3 src/office_check.py word file.docx         prints pages=N
    python3 src/office_check.py powerpoint file.pptx   prints slides=N
"""
import os  # the switch that turns the questions off
import pathlib  # the copies
import re  # the script's answers
import shutil  # finding PowerShell, copying the file
import subprocess  # PowerShell
import sys  # the system's name
import uuid  # a fresh folder name per question

# Each program: its COM name, its program file, what it answers, how long a question may take, and the lines of the
# script that are its own: opening the copy, counting, closing it, and how many documents it still has open
APPS = {
    "word": {"prog": "Word.Application", "exe": "WINWORD.EXE", "answer": "pages", "timeout": 180,
             # invisible, no alerts, read-only and not in the recent files; laid out again, then its pages (wdStatisticPages is 2)
             "open": "$app.Visible = $false; $app.DisplayAlerts = 0; $doc = $app.Documents.Open($In, $false, $true, $false); $doc.Repaginate()",
             "count": '"pages=" + $doc.ComputeStatistics(2)',
             "close": "$doc.Saved = $true; $doc.Close()",  # nothing to save: closed as it was opened
             "docs": "$app.Documents.Count"},
    "powerpoint": {"prog": "PowerPoint.Application", "exe": "POWERPNT.EXE", "answer": "slides", "timeout": 300,
                   # read-only, untitled no, no window (-1 is msoTrue, 0 msoFalse): one PowerPoint serves every window
                   "open": "$doc = $app.Presentations.Open($In, -1, 0, 0)",
                   "count": '"slides=" + $doc.Slides.Count',
                   "close": "$doc.Close()",
                   "docs": "$app.Presentations.Count"},
}

# One question. The processes the program started for this automation (their command line says -Embedding, which a
# program the person opened never has) are named first, so a question that hangs or fails can end them by id. The
# program quits only when no other document is open in it, and says which it did: quit=1, or kept=1 when it stays.
SCRIPT = r"""param([string]$In)
$ErrorActionPreference = 'Stop'
$filter = "Name='{exe}'"
$before = @(Get-CimInstance Win32_Process -Filter $filter | ForEach-Object { $_.ProcessId })
$app = New-Object -ComObject {prog}
"started=" + ((@(Get-CimInstance Win32_Process -Filter $filter | Where-Object { ($before -notcontains $_.ProcessId) -and ($_.CommandLine -match 'Embedding') } | ForEach-Object { $_.ProcessId })) -join ",")
[Console]::Out.Flush()
try {
  {open}
  {count}
  {close}
} finally {
  if ({docs} -eq 0) { $app.Quit(); "quit=1" } else { "kept=1" }
  [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
"""


def script(app: str) -> str:
    """The PowerShell script that asks this program about one file."""
    spec = APPS[app]  # its own lines
    out = SCRIPT  # the shared shape
    for key in ("exe", "prog", "open", "count", "close", "docs"):  # each place it fills
        out = out.replace("{" + key + "}", spec[key])
    return out

_AVAILABLE: dict = {}  # program -> True or False, asked once per process: Office is not installed while Offerowl runs
_TEMP: list = []  # Windows' temporary folder as (Windows path, path here), looked up once


class OfficeFailed(RuntimeError):
    """The program was there but did not open the file, or did not answer in time."""


from open_page import in_wsl  # noqa: E402  this process runs inside WSL on a Windows PC (src/open_page.py: the one test of it)


def powershell() -> str | None:
    """Windows' own PowerShell, as this system starts it: on Windows, and from WSL through interop. None elsewhere."""
    if sys.platform == "win32":  # a Windows PC
        found = shutil.which("powershell.exe") or shutil.which("powershell")  # on PATH, as it always is
        fixed = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")  # where Windows keeps it
        return found or (fixed if os.path.isfile(fixed) else None)
    if in_wsl():  # WSL: Windows' programs are on PATH unless the person turned that off
        fixed = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"  # the usual drive, when PATH leaves Windows out
        return shutil.which("powershell.exe") or (fixed if os.path.isfile(fixed) else None)
    return None  # macOS, Linux, a container: no Office to reach


def _ps(command: str, timeout: int = 60) -> str:
    """One PowerShell command's output, in UTF-8 ("" when PowerShell is missing, fails or hangs)."""
    exe = powershell()  # Windows' PowerShell, if this system reaches one
    if not exe:  # nothing to ask
        return ""
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command],  # UTF-8, or a piped answer comes in the console's code page
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):  # no interop, or it hung
        return ""
    return r.stdout.decode("utf-8", "replace").replace("\r", "")  # Windows line ends


def available(app: str) -> bool:
    """Is this program (word or powerpoint) installed where this PC can start it? Asked of Windows' registry once."""
    if os.environ.get("OFFEROWL_OFFICE", "").strip().lower() in ("0", "off", "no", "false"):  # never asked: the tests, or a person's choice
        return False
    if app not in _AVAILABLE:  # not asked yet in this process
        prog = APPS[app]["prog"]  # its COM name
        out = _ps(f"[bool](Get-ItemProperty 'Registry::HKEY_CLASSES_ROOT\\{prog}\\CLSID' -ErrorAction SilentlyContinue)") if powershell() else ""  # registered with COM
        _AVAILABLE[app] = "True" in out  # an answer of True, else not there
    return _AVAILABLE[app]


def _temp() -> tuple[str, pathlib.Path]:
    """Windows' temporary folder, as Windows writes it and as this process reaches it."""
    if not _TEMP:  # looked up once
        if sys.platform == "win32":  # the same folder either way
            import tempfile  # Windows' own TEMP
            win = tempfile.gettempdir()
            _TEMP.append((win, pathlib.Path(win)))
        else:  # WSL: Windows names it, wslpath turns it into a path here
            win = _ps("[IO.Path]::GetTempPath()").strip().splitlines()[-1:] or [""]  # the last line: a profile may print a greeting first
            win = win[0].strip()
            here = subprocess.run(["wslpath", "-u", win], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10).stdout.strip() if re.match(r"^[A-Za-z]:\\", win) else ""
            if not here or not pathlib.Path(here).is_dir():  # Windows did not answer
                raise OfficeFailed("Windows' temporary folder could not be found")
            _TEMP.append((win.rstrip("\\"), pathlib.Path(here)))
    return _TEMP[0]


def _end(pids: list[int], exe: str, wait: int = 15) -> None:
    """The processes this question started, once they have had `wait` seconds to quit by themselves, ended by id: only
    while they still are the program, started for automation. A program that quit cleanly is never ended."""
    if not pids:  # nothing to end
        return
    ids = ",".join(str(p) for p in pids)  # the ids, as PowerShell takes them
    _ps(f"Wait-Process -Id {ids} -Timeout {wait} -ErrorAction SilentlyContinue; "  # a program that quits takes a moment
        f"Get-CimInstance Win32_Process -Filter \"Name='{exe}'\" | Where-Object {{ (@({ids}) -contains $_.ProcessId) -and ($_.CommandLine -match 'Embedding') }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }", timeout=wait + 60)  # still there: ended


def count(app: str, path) -> int:
    """How many pages Word (app "word") or slides PowerPoint (app "powerpoint") gives the file. Raises OfficeFailed when the
    program was there but did not open it in time; call available() first."""
    spec = APPS[app]  # the program
    exe = powershell()  # Windows' PowerShell
    if not exe:  # this system reaches no Office
        raise OfficeFailed("PowerShell is not reachable")
    try:
        win_root, here_root = _temp()  # Windows' temporary folder, both ways
        name = "offerowl_" + app + "_" + uuid.uuid4().hex[:10]  # ASCII only, fresh each time
        work = here_root / name  # this question's folder
        work.mkdir(parents=True)
    except (OSError, subprocess.SubprocessError) as exc:  # Windows did not answer, or its folder cannot be written
        raise OfficeFailed(f"Windows' temporary folder cannot be used: {exc}") from exc
    try:
        src = pathlib.Path(path)  # the file asked about
        copy = "in" + src.suffix.lower()  # the copy's plain name
        shutil.copyfile(src, work / copy)  # a copy in this question's folder
        win_dir = win_root + "\\" + name  # the folder as Windows names it
        (work / "ask.ps1").write_text(script(app), encoding="utf-8-sig")  # with its byte-order mark, PowerShell 5.1 reads it as UTF-8
        argv = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", win_dir + "\\ask.ps1", "-In", win_dir + "\\" + copy]  # the script and the copy it opens
        timed_out = False  # until it runs over
        try:
            r = subprocess.run(argv, capture_output=True, stdin=subprocess.DEVNULL, timeout=spec["timeout"])  # one question
            out = (r.stdout or b"") + (r.stderr or b"")  # its answer, and why when it failed
        except subprocess.TimeoutExpired as exc:  # it hung: what it printed so far still names the process it started
            out, timed_out = (exc.stdout or b"") + (exc.stderr or b""), True
        except OSError as exc:  # PowerShell could not be started at all: nothing of it to end
            raise OfficeFailed(f"PowerShell did not start: {exc}") from exc
        text = out.decode("utf-8", "replace").replace("\r", "")  # Windows line ends
        line = re.search(r"^started=([\d,]*)\s*$", text, re.M)  # the processes it started
        started = [int(p) for p in line.group(1).split(",") if p] if line else []  # none: it reused a program already open
        if "kept=1" not in text:  # it quit, failed or hung: what it started must not stay behind, invisible
            _end(started, spec["exe"])
        got = re.search(r"^" + spec["answer"] + r"=(\d+)\s*$", text, re.M)  # pages=N or slides=N
        if timed_out or not got:  # it did not open the file, or never answered
            reason = "it did not answer in time" if timed_out else (text.strip().splitlines() or ["no answer"])[-1][:300]  # the last line says why
            raise OfficeFailed(f"{app} did not open the file: {reason}")
        return int(got.group(1))  # the count
    finally:
        shutil.rmtree(work, ignore_errors=True)  # nothing of the file stays in Windows' folder


def main(argv=None) -> int:
    """The command line: python3 src/office_check.py word|powerpoint FILE"""
    a = list(sys.argv[1:] if argv is None else argv)  # the arguments
    if len(a) != 2 or a[0] not in APPS:  # one program and one file
        print("usage: office_check.py word|powerpoint FILE")
        return 2
    if not available(a[0]):  # nothing to open it with here
        print(f"{a[0]} is not reachable from this PC")
        return 3
    print(f"{APPS[a[0]]['answer']}={count(a[0], a[1])}")  # pages=N or slides=N
    return 0


if __name__ == "__main__":
    sys.exit(main())
