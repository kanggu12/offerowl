"""Builds Offerowl as one file with its own Python, for people who do not install Python: Offerowl.exe on Windows
(Offerowl on macOS and Linux), with the panel and the engine inside. Run it on
the system it is for, from the repository's root:

    python -m pip install -r apps/desktop/requirements-build.txt
    python apps/desktop/build.py

It writes dist/Offerowl(.exe), then runs it with --check, which starts its server with a stand-in agent and reads one
file through the engine, and fails the build when something it needs was left out. In CI,
.github/workflows/desktop.yml does this on each system.

What is inside: apps/panel (the server and its page), src/ (the engine: ingest, review, drafts, the typesetting
scripts and their themes), examples/, fonts/, the icon and the wordmark, the license and the third-party notices. Documents need no Docker:
the app typesets with the PC's own Chrome or Edge (OFFEROWL_RENDERER=html) and carries what the DOCX and deck writers
need besides Python (apps/desktop/node/):

- Node.js, the release pinned in node/pins.json. The build downloads the official archive, refuses it unless its SHA-256
  is the pinned one, and packs the one program as runtime/node.xz. The app unpacks it once into the data folder.
- node_modules/, the production libraries of package.json installed with npm ci and pruned (node/prune.json).

`--no-runtime` leaves both out: a quicker build of an app that runs the panel but cannot make documents.
"""
from __future__ import annotations  # hints stay strings, so new hint syntax runs on older Pythons

import argparse  # --no-runtime
import ast  # the imports of the bundled sources
import os  # the separator of --add-data
import platform  # the machine name
import re  # the package's version
import shutil  # clean build folders
import subprocess  # PyInstaller and the check
import sys  # the running Python
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[2]  # the repository
DIST = ROOT / "dist"  # where the app goes
WORK = ROOT / "build"  # PyInstaller's scratch
WINDOWS = sys.platform == "win32"  # several choices below differ on Windows
SEP = os.pathsep  # --add-data takes "source<sep>destination"

# Files the app reads at run time, beside its code: (source, folder inside the app).
DATA = [
    ("apps/panel", "apps/panel"),  # the panel's server modules and its page (imported from here at run time)
    ("apps/api", "apps/api"),  # the API the panel is built on
    ("apps/mcp", "apps/mcp"),  # the agent's tools: the command bar starts apps/mcp/__main__.py with this program as its interpreter
    ("core", "core"),  # the data model: the JSON schemas the API validates with are read from files at run time
    ("src", "src"),  # the engine's modules and scripts
    ("examples", "examples"),  # the example profile
    ("fonts", "fonts"),  # Pretendard for the page and the documents
    ("docs/assets/icon.svg", "docs/assets"),  # the icon and the wordmark the panel serves: the only pictures it reads
    ("docs/assets/logo-light.svg", "docs/assets"),
    ("docs/assets/logo-dark.svg", "docs/assets"),
    ("deploy/python/offerowl/__init__.py", "deploy/python/offerowl"),  # the one place the version is written: the bar beside the wordmark reads it
    ("LICENSE", "."),  # the license, and the licenses of what the app carries (pystray among them, LGPL)
    ("docs/THIRD_PARTY_NOTICES.md", "docs"),
]
# Optional packages the app uses when they are there: the tray icon, and the drawing modules of the engine's figure scripts
# (src/overview_figures.py draws with ImageFont as well).
# pypdfium2 reads PDFs (src/pdftools.py), since a PC rarely has poppler.
HIDDEN = ["pystray", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "pypdfium2", "pypdfium2_raw"]
# pystray picks its backend at run time, out of PyInstaller's sight
HIDDEN += ["pystray._win32"] if WINDOWS else (["pystray._darwin"] if sys.platform == "darwin" else
                                              ["pystray._xorg", "pystray._appindicator", "pystray._gtk"])


def stdlib_imports(folders: list[Path]) -> list[str]:  # the panel's modules ship as data, so nothing traces them
    """Every standard-library module the bundled sources import. They are loaded from files at run time, so
    PyInstaller cannot see their imports, and a module only they use would be missing from the app."""
    names = set()  # top-level module names
    for folder in folders:  # apps/panel and src/, as main() passes them
        for f in folder.rglob("*.py"):  # every source file
            try:  # one bad file must not stop the build
                tree = ast.parse(f.read_text(encoding="utf-8"))  # parsed, never run
            except (SyntaxError, UnicodeDecodeError):  # not Python 3 syntax, or not UTF-8
                continue  # skipped, and the build goes on without its imports
            for node in ast.walk(tree):  # import x.y / from x.y import z
                if isinstance(node, ast.Import):  # plain imports: import a, b.c
                    names.update(a.name for a in node.names)  # full dotted names, so submodules are bundled too
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:  # relative imports point at bundled code, so skipped
                    names.add(node.module)  # the module the names come from
    std = set(sys.stdlib_module_names)  # Python 3.10+
    return sorted(n for n in names if n.split(".")[0] in std)  # local modules ship as data; sorted for a stable command


def icon(path: Path) -> Path:  # Windows wants an .ico for the exe
    """The app's icon at the sizes Windows asks an .ico for (the tray icon's drawing, large)."""
    sys.path.insert(0, str(ROOT / "apps"))  # makes desktop.app importable from the checkout
    from desktop.app import tray_image  # the same drawing
    img = tray_image(256)  # drawn at the largest size an .ico holds
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])  # each size Windows may pick
    return path  # main() passes it to --icon


def package_version() -> str:  # the version a macOS bundle carries
    """The version written in deploy/python/offerowl/__init__.py, the one place it is set (pyproject.toml reads it from there)."""
    text = (ROOT / "deploy" / "python" / "offerowl" / "__init__.py").read_text(encoding="utf-8")  # the package's own file
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)  # tests/packaging keeps every other copy equal to it


def minimum_macos(site: Path) -> str | None:  # the oldest macOS the bundle can start on
    """The highest macOS a bundled wheel was built for, read from the WHEEL files of the build's packages ("13.0"), or None
    when none names one. PyInstaller writes no LSMinimumSystemVersion, and an app started on an older system fails inside
    instead of Finder saying which macOS it needs (pypdfium2 5.14's wheels are macosx_13_0)."""
    best = None  # the highest (major, minor) so far
    for wheel in sorted(site.glob("*.dist-info/WHEEL")):  # one per installed package
        for tag in re.findall(r"^Tag: .*?macosx_(\d+)_(\d+)_", wheel.read_text(encoding="utf-8", errors="replace"), re.M):  # its platform tags
            v = (int(tag[0]), int(tag[1]))  # as numbers, so 10.15 sorts before 11.0
            best = v if best is None or v > best else best
    return None if best is None else f"{best[0]}.{best[1]}"


def mac_bundle(exe: Path, machine: str, version: str, out: Path, work: Path, minimum: str | None = None) -> Path:
    """The checked file as Offerowl.app in a zip, for macOS: a browser takes the execute bit off a bare file, so it could only
    start from Terminal, while a zip keeps it and Finder opens both with a double-click. Written with the standard library, so
    a test can read the result on any system. Returns the zip."""
    import plistlib  # the bundle's description
    import zipfile  # keeps the execute bit, in each entry's Unix mode
    root = work / "Offerowl.app"  # the bundle's folder
    shutil.rmtree(root, ignore_errors=True)  # a clean bundle
    (root / "Contents" / "MacOS").mkdir(parents=True)  # the program's place
    (root / "Contents" / "Resources").mkdir()  # the icon's place
    shutil.copy2(exe, root / "Contents" / "MacOS" / "Offerowl")  # the checked file itself
    (root / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleName": "Offerowl", "CFBundleDisplayName": "Offerowl", "CFBundleIdentifier": "io.github.kanggu12.offerowl",  # what Finder shows, and the system's key for it
        "CFBundleExecutable": "Offerowl", "CFBundlePackageType": "APPL", "CFBundleIconFile": "offerowl",  # what to start, and its picture
        "CFBundleShortVersionString": version, "CFBundleVersion": version, "NSHighResolutionCapable": True,  # the version Finder shows
        "LSUIElement": True,  # no Dock icon: like the other systems, the app lives in its icon by the clock
        **({"LSMinimumSystemVersion": minimum} if minimum else {}),  # Finder names the macOS it needs instead of the app failing inside
    }))
    try:  # the picture is a nicety: a bundle without it still starts
        sys.path.insert(0, str(ROOT / "apps"))  # makes desktop.app importable from the checkout
        from desktop.app import tray_image  # the same drawing as the Windows icon
        tray_image(512).save(root / "Contents" / "Resources" / "offerowl.icns")  # drawn large enough for Finder
    except (ImportError, OSError, ValueError) as exc:  # no Pillow
        print(f"no icon in the bundle: {exc}")  # said in the build's log
    if sys.platform == "darwin":  # the signature macOS on Apple silicon needs before it starts anything, with no developer account
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(root)], check=True)  # ad hoc, over the whole bundle
    named = out / f"Offerowl-macos-{machine}.zip"  # the file to hand out
    named.unlink(missing_ok=True)  # an old one must not pass for a new one
    with zipfile.ZipFile(named, "w", zipfile.ZIP_DEFLATED) as z:  # Finder's Archive Utility reads the modes back
        for f in sorted(p for p in root.rglob("*") if p.is_file()):  # every file, in a fixed order
            info = zipfile.ZipInfo(str(f.relative_to(work)), (1980, 1, 1, 0, 0, 0))  # a fixed date: the same bundle gives the same zip
            info.create_system = 3  # Unix: the mode below counts
            info.external_attr = (f.stat().st_mode & 0o777 | 0o100000) << 16  # with the execute bit of the program
            info.compress_type = zipfile.ZIP_DEFLATED  # small
            z.writestr(info, f.read_bytes())  # one entry
    return named  # the file to hand out


def main(argv: list[str] | None = None) -> int:  # one command builds the app and checks it
    ap = argparse.ArgumentParser(description="Build the one-file app and check it.")  # what --help says
    ap.add_argument("--no-runtime", action="store_true", help="leave Node.js and the libraries out: the app runs the panel but cannot make documents")  # quicker to build
    opts = ap.parse_args(argv)  # exits with a usage line on bad options
    for d in (DIST / "Offerowl", WORK / "pyinstaller"):  # folders an earlier build left behind
        shutil.rmtree(d, ignore_errors=True)  # a clean build
    WORK.mkdir(exist_ok=True)  # the .ico, the spec and the check's report go here
    runtime = None  # what the app carries of Node.js
    if not opts.no_runtime:  # the normal build
        sys.path.insert(0, str(ROOT / "apps"))  # makes desktop.node importable from the checkout
        from desktop.node import bundle  # fetches, verifies, packs and prunes
        runtime = bundle.build_runtime(ROOT, WORK)  # work/runtime (node.xz) and work/node-stage/node_modules, both checked
    # one file, no prompts, no stale cache
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", "Offerowl",
            "--distpath", str(DIST), "--workpath", str(WORK / "pyinstaller"), "--specpath", str(WORK),
            "--paths", str(ROOT / "apps"),  # desktop.app is found from here
            "--python-option", "X utf8"]  # UTF-8 for files and pipes on every system: Korean Windows would read Node.js's output as cp949
    for source, dest in DATA:  # each data folder from the list above
        args += ["--add-data", f"{ROOT / source}{SEP}{dest}"]  # copied into the app at the same path
    if runtime:  # Node.js and its libraries travel as data
        args += ["--add-data", f"{runtime['runtime']}{SEP}runtime"]  # manifest.json, node.xz and the licence: unpacked into the data folder at the first start
        args += ["--add-data", f"{runtime['node_modules']}{SEP}node_modules"]  # where src/ finds them: <engine folder>/node_modules
    for name in stdlib_imports([ROOT / "apps" / "panel", ROOT / "apps" / "api", ROOT / "core" / "schema", ROOT / "src"]) + HIDDEN:  # imports PyInstaller cannot trace, plus the tray
        args += ["--hidden-import", name]  # bundled even though no traced code imports it
    if WINDOWS:  # no console window: the icon and the panel are the program's face; problems show in a message box
        args += ["--windowed", "--icon", str(icon(WORK / "offerowl.ico"))]  # a windowed exe needs its own icon
    args.append(str(ROOT / "apps" / "desktop" / "__main__.py"))  # the entry point, last on the command line
    print(" ".join(args))  # the build log shows the exact command
    subprocess.run(args, check=True, cwd=str(ROOT))  # check=True stops the build on a PyInstaller error
    exe = DIST / ("Offerowl.exe" if WINDOWS else "Offerowl")  # PyInstaller adds .exe on Windows only
    print(f"checking {exe}")  # marks where the check's output starts
    log = WORK / "check.log"  # the check's report, since a windowed exe has no console
    log.unlink(missing_ok=True)  # an old report must not pass for a new one
    # a hung check fails the build after fifteen minutes (it unpacks Node.js and prints three documents)
    done = subprocess.run([str(exe), "--check"], timeout=900, env={**os.environ, "OFFEROWL_CHECK_LOG": str(log)})
    print(log.read_text(encoding="utf-8") if log.is_file() else "(the check wrote no report)")  # a crash before the report shows as missing
    if done.returncode:  # any non-zero exit is a failed check
        raise SystemExit(f"{exe} --check failed with exit {done.returncode}")  # a broken app is never handed out
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")  # system names people know, for the file name
    # one name per architecture, whatever the OS calls it
    machine = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    named = DIST / f"Offerowl-{system}-{machine}{'.exe' if WINDOWS else ''}"  # the file to hand out
    if system == "macos":  # a bundle a person can open from Finder
        import sysconfig  # where this build's packages are installed
        named = mac_bundle(exe, machine, package_version(), DIST, WORK, minimum_macos(Path(sysconfig.get_paths()["platlib"])))  # the zip, with the version and the oldest macOS
    else:  # the file itself
        shutil.copy2(exe, named)  # the checked file itself, under its release name; copy2 keeps its execute bit
    print(f"wrote {named} ({named.stat().st_size / 1e6:.1f} MB)")  # CI and the log show what was made, and how large
    return 0  # exit 0 tells CI the build passed


if __name__ == "__main__":  # runs only when started as a script
    raise SystemExit(main())  # the return value becomes the exit code
