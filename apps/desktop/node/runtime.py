"""The run-time half of the one-file app's Node.js support (bundle.py is the half that runs at build time).

The app carries Node.js compressed (node.xz) beside a manifest.json that says what the program must look like once it is
unpacked. The first start unpacks it into the app's data folder, which is not a temporary folder, so later starts find it
there and do nothing:

    <data folder>/runtime/node-<version>-<system>/node         (node.exe on Windows)
                                                   LICENSE
                                                   runtime.json   written last: its presence says the unpack finished

`ensure()` is the one call apps/desktop/app.py makes. It returns a Runtime that puts the program on the PATH of the
server, which is how src/resume.py finds `node` (shutil.which), or None when this copy of the app carries no Node.js (a
checkout), in which case the engine uses the Node.js of the PC.

This file uses only the standard library and imports nothing from its package, so it also runs inside the frozen app.
"""
from __future__ import annotations  # hints stay strings, so new hint syntax runs on older Pythons

import hashlib  # the digest of the unpacked program
import json  # manifest.json and runtime.json
import lzma  # node.xz
import os  # environment, modes
import shutil  # copies and removals
import subprocess  # node --version
import sys  # platform, frozen or not
import time  # the stamp in runtime.json
from datetime import datetime, timezone  # an ISO time for the stamp
from pathlib import Path  # paths

FORMAT = 1  # the manifest layout this file reads; bundle.py writes the same number
MANIFEST = "manifest.json"  # beside node.xz, in the app's runtime/ folder
MARKER = "runtime.json"  # inside the unpacked folder, written last
CHUNK = 1 << 20  # one read or write when streaming the 120 MB program
CREATE_NO_WINDOW = 0x08000000  # a console program started from the windowless Windows app gets no window of its own


class UnpackError(RuntimeError):
    """The bundled Node.js could not be unpacked, or what came out is not what the manifest says."""


class Runtime:
    """A Node.js on this PC that the app can hand to the engine: where it is and what to put in an environment."""

    def __init__(self, folder: Path, program: Path, version: str, source: str):  # filled by find(), unpack() and external()
        self.folder, self.program, self.version, self.source = folder, program, version, source  # the folder the program is in, the program, its version, and "bundled" or "chosen"

    def apply(self, env: dict) -> dict:  # one place decides how the engine finds this program
        """A copy of `env` in which `node` is this program: its folder first on PATH (src/resume.py looks `node` up with
        shutil.which), and OFFEROWL_NODE naming the program for code that asks for it by name."""
        out = dict(env)  # the caller's environment stays as it is
        key = next((k for k in out if k.upper() == "PATH"), "PATH")  # Windows spells it Path; a second key would be ambiguous there
        out[key] = str(self.folder) + (os.pathsep + out[key] if out.get(key) else "")  # this folder wins over any other Node.js
        out["OFFEROWL_NODE"] = str(self.program)  # the program itself
        return out  # handed to the server


def bundle_dir(root: Path) -> Path | None:  # None for a checkout
    """The folder with node.xz and manifest.json inside the app (`root`/runtime), or None when this copy has none."""
    folder = Path(root) / "runtime"  # PyInstaller puts the bundled data here
    return folder if (folder / MANIFEST).is_file() else None  # a folder without a manifest is not ours


def read_manifest(bundle: Path) -> dict:  # what the unpacked program must look like
    """The `node` part of the bundle's manifest.json, checked for shape."""
    try:  # a damaged or foreign file
        doc = json.loads((bundle / MANIFEST).read_text(encoding="utf-8"))  # the manifest bundle.py wrote
        info = doc["node"]  # the one program in it
        ok = doc["format"] == FORMAT and all(k in info for k in ("version", "system", "program", "size", "sha256", "packed"))  # the fields used below
    except (OSError, ValueError, KeyError, TypeError) as exc:  # unreadable, not JSON, or the wrong shape
        raise UnpackError(f"the manifest of the bundled Node.js is unreadable: {exc}") from exc  # the app goes on without documents
    if not ok:  # a manifest of another layout
        raise UnpackError("the manifest of the bundled Node.js has a layout this app does not know")  # the same
    return info  # the program's description


def target_dir(data: Path, info: dict) -> Path:  # one folder per release and system, so a new release never mixes with an old one
    """Where the program of `info` is unpacked under the data folder."""
    return Path(data) / "runtime" / f"node-{info['version']}-{info['system']}"  # runtime/node-22.1.0-linux-x64


def find(data: Path, root: Path) -> Runtime | None:  # cheap enough to run at every start
    """The unpacked program of this app's bundle, when it is complete, else None. Checks the marker and the size of the
    program, not its digest (the digest was checked when it was unpacked)."""
    bundle = bundle_dir(root)  # the app's own copy
    if bundle is None:  # nothing is bundled
        return None  # a checkout
    info = read_manifest(bundle)  # what the program must be
    folder = target_dir(data, info)  # where it should be
    try:  # a missing marker or program raises
        marker = json.loads((folder / MARKER).read_text(encoding="utf-8"))  # written last by unpack()
        program = folder / info["program"]  # the program
        complete = marker.get("sha256") == info["sha256"] and marker.get("size") == info["size"] and program.stat().st_size == info["size"]  # the same release and the whole file
    except (OSError, ValueError):  # not unpacked, or half
        return None  # unpack() starts over
    return Runtime(folder, program, info["version"], "bundled") if complete else None  # found, or the folder is stale


def clean_env(env: dict) -> dict:  # for every program that is not part of the app
    """A copy of `env` for a program the app starts but does not contain (Node.js, the browser, poppler). PyInstaller's
    one-file start puts its own folder first on the library search path, and a program of the PC would load the app's
    copies of shared libraries instead of its own. PyInstaller keeps the value it replaced in <NAME>_ORIG."""
    out = dict(env)  # the caller's environment stays as it is
    for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "LIBPATH"):  # the search paths of Linux, macOS and AIX loaders
        saved = out.get(key + "_ORIG")  # what the person had before the app started
        if saved is not None:  # PyInstaller replaced the value
            out[key] = saved  # the person's own again
        elif key == "LD_LIBRARY_PATH" and getattr(sys, "frozen", False) and sys.platform.startswith("linux"):  # PyInstaller set it where there was none
            out.pop(key, None)  # and no program of the PC wants the app's folder
    return out  # handed to subprocess


def restore_process_env() -> None:  # called once by the server and the document check
    """Apply clean_env() to this process, so every program it starts later sees the PC's library search path. Libraries
    this process loads from now on are found as before: the loader reads the variable once, at start."""
    clean = clean_env(os.environ)  # what the environment should be
    for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "LIBPATH"):  # only these four are touched
        if key in clean:  # restored or untouched
            os.environ[key] = clean[key]  # the person's own value
        else:  # removed
            os.environ.pop(key, None)  # gone


def node_version(program: Path) -> str:  # the check that the unpacked program starts at all
    """What `program --version` prints (such as `v22.23.4`), or an empty string when it does not start."""
    flags = {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}  # no console window flashes up from the windowless app
    try:  # a program that cannot start (wrong system, noexec folder, quarantined by a virus scanner)
        r = subprocess.run([str(program), "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, env=clean_env(os.environ), **flags)  # a virus scanner can hold the first start for a while
    except (OSError, subprocess.SubprocessError):  # cannot be started, or hangs
        return ""  # the caller treats it as a failed unpack
    return r.stdout.strip() if r.returncode == 0 else ""  # only a clean exit counts


def unpack(data: Path, root: Path, say=None, version_of=node_version) -> Runtime:  # the slow step, once per release
    """Unpack the bundled program into the data folder and check it: its digest and size must be the manifest's, and it
    must print its version. Nothing is left behind when a step fails. `say(text)` reports progress; `version_of(path)`
    stands in for starting the program (the tests)."""
    say = say or (lambda _text: None)  # progress goes nowhere unless the caller wants it
    bundle = bundle_dir(root)  # the app's own copy
    if bundle is None:  # called on a copy without one
        raise UnpackError("this copy of the app carries no Node.js")  # nothing to unpack
    info = read_manifest(bundle)  # what the program must be
    folder = target_dir(data, info)  # its place
    shutil.rmtree(folder, ignore_errors=True)  # a half unpack of an earlier start goes
    try:  # whatever fails below, the folder must not stay half full
        folder.mkdir(parents=True, exist_ok=True)  # runtime/node-<version>-<system>
        say(f"unpacking Node.js {info['version']} into {folder} (this happens once)")  # the log shows the slow step
        program = folder / info["program"]  # the unpacked program
        h, size = hashlib.sha256(), 0  # digest and size of what comes out
        with lzma.open(bundle / info["packed"], "rb") as src, open(program, "wb") as dst:  # xz checks its own integrity while reading
            for block in iter(lambda: src.read(CHUNK), b""):  # one block at a time
                h.update(block)  # digest
                size += len(block)  # size
                dst.write(block)  # written
        if (h.hexdigest(), size) != (info["sha256"], info["size"]):  # not the program bundle.py packed
            raise UnpackError("the unpacked Node.js is not the one this app was built with")  # a damaged app file
        if os.name == "posix":  # a program needs its execute bits
            os.chmod(program, 0o755)  # owner may write; everyone may read and run
        licence = bundle / info.get("license", "")  # Node.js's licence file
        if info.get("license") and licence.is_file():  # carried beside the program
            shutil.copyfile(licence, folder / "LICENSE")  # and kept with it
        got = version_of(program)  # does it start?
        if got != "v" + info["version"]:  # no, or it is another release
            raise UnpackError(f"the unpacked Node.js does not start (it printed {got!r}, expected v{info['version']})")  # for example a folder mounted noexec
        marker = {"format": FORMAT, "version": info["version"], "system": info["system"], "sha256": info["sha256"], "size": info["size"],  # what find() compares
                  "unpacked": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}  # when
        (folder / MARKER).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")  # last: the folder is complete now
    except (OSError, lzma.LZMAError, EOFError) as exc:  # a full disk, a locked file, a damaged archive
        shutil.rmtree(folder, ignore_errors=True)  # nothing half stays
        raise UnpackError(f"could not unpack Node.js: {exc}") from exc  # the caller logs it
    except UnpackError:  # a check above failed
        shutil.rmtree(folder, ignore_errors=True)  # nothing half stays
        raise  # as it was
    for other in folder.parent.iterdir():  # older releases and leftovers
        if other != folder and other.name.startswith("node-") and other.is_dir():  # only what this file made
            shutil.rmtree(other, ignore_errors=True)  # an update does not leave 100 MB of the old release behind
    return Runtime(folder, program, info["version"], "bundled")  # ready


def chosen(env: dict | None = None) -> Runtime | None:  # a person's own Node.js beats the bundled one
    """The program named by OFFEROWL_NODE when it is a file, else None."""
    path = (env if env is not None else os.environ).get("OFFEROWL_NODE", "").strip()  # set by the person, or by an earlier start of this app
    if path and Path(path).is_file():  # it exists
        return Runtime(Path(path).parent, Path(path), "", "chosen")  # used as it is, with no version check
    return None  # nothing chosen


def ensure(data: Path, root: Path, say=None, version_of=node_version) -> Runtime | None:  # the one call app.py makes
    """The Node.js the engine should use: the one OFFEROWL_NODE names, else the bundled program (unpacked on the first
    start), else None for a copy of the app that carries none. `version_of` is passed on to unpack()."""
    pick = chosen()  # a person's choice
    if pick is not None:  # used as it is
        return pick  # nothing to unpack
    if bundle_dir(root) is None:  # a checkout
        return None  # the engine uses the PC's Node.js
    started = time.monotonic()  # to tell the log how long a first start took
    found = find(data, root)  # unpacked already?
    if found is not None:  # every start after the first
        return found  # no work
    out = unpack(data, root, say, version_of)  # the first start, or a damaged folder
    if say:  # the log
        say(f"Node.js is ready ({time.monotonic() - started:.1f} s)")  # how long the first start waited
    return out  # ready
