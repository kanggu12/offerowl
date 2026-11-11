#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find a Chromium-family browser on this PC and print a page to PDF with it.

The renderer needs no Docker and no LibreOffice: Edge ships with Windows, Chrome is on most PCs, and either prints HTML to
PDF headless. The search order is:
  1. OFFEROWL_BROWSER, a path the person chose;
  2. Edge, Chrome and Chromium in the places their installers use on Windows, macOS and Linux, and on PATH;
  3. the Chromium that Playwright downloads (`python -m playwright install chromium`), as a fallback.

  python3 src/render_html/browser.py --list            every browser found, the one in use first
  python3 src/render_html/browser.py <page.html> <out.pdf>
"""
import glob  # Playwright's versioned folders
import json  # the result the page reports
import os  # environment, temporary folders
import pathlib  # paths
import re  # version folder names on Windows
import shutil  # PATH lookups, removing the profile folder
import subprocess  # the browser
import sys  # platform, command line
import tempfile  # a throwaway profile per run
import time  # how long a print took

# Places the installers use, per system. Edge first on Windows: it is always there.
WINDOWS = [
    r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
    r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
    r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
    r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Chromium\Application\chrome.exe",
]
MACOS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
LINUX_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable"]
# Playwright keeps its browsers here unless PLAYWRIGHT_BROWSERS_PATH says otherwise.
PLAYWRIGHT_DIRS = {"win32": r"%LOCALAPPDATA%\ms-playwright", "darwin": "~/Library/Caches/ms-playwright", "linux": "~/.cache/ms-playwright"}
# Its headless shell comes first: it is built for printing without a window (measured on Linux: it printed a page in
# 0.3s, where Playwright's full Chromium 151 never finished the same print). The full Chromium follows as a last resort.
PLAYWRIGHT_EXES = {
    "win32": ["chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",
              "chromium_headless_shell-*/chrome-win/headless_shell.exe",
              "chromium-*/chrome-win64/chrome.exe", "chromium-*/chrome-win/chrome.exe"],
    "darwin": ["chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell",
               "chromium_headless_shell-*/chrome-headless-shell-mac-x64/chrome-headless-shell",
               "chromium_headless_shell-*/chrome-mac/headless_shell",
               "chromium-*/chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium",
               "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"],
    "linux": ["chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
              "chromium_headless_shell-*/chrome-linux/headless_shell",
              "chromium-*/chrome-linux64/chrome", "chromium-*/chrome-linux/chrome"],
}


def _platform(name: str | None = None) -> str:
    """win32, darwin or linux"""
    p = name or sys.platform
    return "win32" if p.startswith("win") else "darwin" if p == "darwin" else "linux"


def _expand(p: str, env: dict) -> str:
    """Expand %VAR% (Windows style), $VAR and ~ in a path"""
    for k, v in env.items():
        p = p.replace("%" + k + "%", v).replace("%" + k.upper() + "%", v)
    return os.path.expanduser(os.path.expandvars(p))


def candidates(platform: str | None = None, env: dict | None = None, which=shutil.which, exists=os.path.isfile) -> list[dict]:
    """Every browser found, in the order they are tried: [{"path", "kind"}]. The arguments let the tests stand in for
    another system: a platform name, an environment, and the functions that look up PATH and files"""
    plat, env = _platform(platform), dict(os.environ if env is None else env)
    out, seen = [], set()

    def add(path, kind):
        if path and path not in seen and exists(path):
            seen.add(path)
            out.append({"path": path, "kind": kind})
    if env.get("OFFEROWL_BROWSER"):  # the person's choice comes first, whatever it is
        add(_expand(env["OFFEROWL_BROWSER"], env), "chosen")
    if plat == "win32":
        for p in WINDOWS:
            add(_expand(p, env), "edge" if "Edge" in p else "chrome")
        for name in ("msedge", "chrome"):
            add(which(name), "edge" if name == "msedge" else "chrome")
    elif plat == "darwin":
        for p in MACOS:
            add(_expand(p, env), "edge" if "Edge" in p else "chrome")
    else:
        for name in LINUX_NAMES:
            add(which(name), "edge" if "edge" in name else "chrome")
    base = env.get("PLAYWRIGHT_BROWSERS_PATH") or _expand(PLAYWRIGHT_DIRS[plat], env)  # the fallback
    for pat in PLAYWRIGHT_EXES[plat]:  # the headless shells first, then the full builds
        for p in sorted(glob.glob(os.path.join(base, pat)), reverse=True):  # the newest build of each kind first
            add(p, "playwright")
    return out


def find() -> dict | None:
    """The browser to use, or None"""
    c = candidates()
    return c[0] if c else None


def version(path: str, platform: str | None = None) -> str:
    """The browser's version. On Windows the program is never started for it: there `chrome.exe --version` and
    `msedge.exe --version` open a browser window instead of printing, so the version comes from the folder named after
    it next to the program (Application\\151.0.7922.75). Elsewhere the browser prints it"""
    if _platform(platform) == "win32":
        folder = pathlib.Path(path).parent
        try:
            names = [d.name for d in folder.iterdir() if d.is_dir() and re.fullmatch(r"\d+(\.\d+){3}", d.name)]
        except OSError:  # the folder cannot be read
            return ""
        return max(names, key=lambda n: [int(x) for x in n.split(".")]) if names else ""
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


# Flags for a quiet headless browser that prints the page as its CSS asks (@page size, no header or footer line).
# --font-render-hinting=none keeps glyph widths unhinted, so lines break where they break in other renderers.
# --generate-pdf-document-outline turns the <h1> section titles into PDF bookmarks, as the container's LibreOffice does.
FLAGS = ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
         "--disable-dev-shm-usage", "--hide-scrollbars", "--mute-audio", "--font-render-hinting=none",
         "--allow-file-access-from-files", "--no-pdf-header-footer", "--generate-pdf-document-outline",
         "--disable-background-networking", "--disable-component-update", "--disable-sync"]


def _sandbox() -> list[str]:
    """Chromium's sandbox needs user namespaces, which containers and root shells lack; elsewhere it stays on"""
    if pathlib.Path("/.dockerenv").exists() or (hasattr(os, "geteuid") and os.geteuid() == 0):
        return ["--no-sandbox"]
    return []


def _uri(path: str | pathlib.Path) -> str:
    """A file URL for a path, on every system"""
    return pathlib.Path(path).resolve().as_uri()


def _flags(exe: str) -> list[str]:
    """The flags for one browser: a headless shell is headless already and takes no --headless switch"""
    shell = "headless_shell" in exe or "headless-shell" in exe
    return [f for f in FLAGS if not (shell and f.startswith("--headless"))]


def _print_with(exe: str, page, pdf: pathlib.Path, budget_ms: int, timeout: int) -> str:
    """One print with one browser; returns an empty string when a PDF came out, else what went wrong"""
    pdf.unlink(missing_ok=True)  # an old file must not pass for a new one
    prof = tempfile.mkdtemp(prefix="offerowl-browser-")  # a profile of its own: never the person's browser profile
    try:
        cmd = [exe, *_flags(exe), *_sandbox(), "--user-data-dir=" + prof, "--virtual-time-budget=%d" % budget_ms,
               "--print-to-pdf=" + str(pdf.resolve()), _uri(page)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        why = (r.stderr or r.stdout)[-800:]
    except subprocess.TimeoutExpired:  # a browser that never finishes is skipped, not waited for
        why = "no PDF after %d seconds" % timeout
    except OSError as e:  # not startable
        why = str(e)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return "" if pdf.exists() and pdf.stat().st_size > 0 else (why or "no PDF")


def print_pdf(page: str | pathlib.Path, pdf: str | pathlib.Path, browser: str | None = None, budget_ms: int = 30000,
              timeout: int = 90) -> dict:
    """Print one HTML page to PDF. Returns {"pdf", "browser", "seconds"}; raises RuntimeError when no PDF came out.
    The virtual time budget lets the page's own layout script (fonts, tabs, pages) finish before the print. Without a
    browser named by the caller, each browser found is tried in turn until one prints"""
    exes = [browser] if browser else [c["path"] for c in candidates()]
    if not exes:
        raise RuntimeError("no browser")
    pdf = pathlib.Path(pdf)
    t0 = time.time()
    errors = []
    for exe in exes:
        why = _print_with(exe, page, pdf, budget_ms, timeout)
        if not why:
            return {"pdf": str(pdf), "browser": exe, "seconds": round(time.time() - t0, 2)}
        errors.append(exe + ": " + why)
    raise RuntimeError("the browser made no PDF: " + " | ".join(errors)[-1200:])


def dump_dom(page: str | pathlib.Path, browser: str | None = None, budget_ms: int = 30000, width: int = 1400,
             height: int = 900, timeout: int = 180) -> str:
    """The page's DOM after its scripts ran (the deck's overflow probe reads it)"""
    exe = browser or (find() or {}).get("path")
    if not exe:
        raise RuntimeError("no browser")
    prof = tempfile.mkdtemp(prefix="offerowl-browser-")
    try:
        cmd = [exe, *_flags(exe), *_sandbox(), "--user-data-dir=" + prof, "--virtual-time-budget=%d" % budget_ms,
               "--window-size=%d,%d" % (width, height), "--dump-dom", _uri(page)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return r.stdout


def page_result(dom: str) -> dict:
    """What a page made by docx2html.py reported about itself (data-owl-result on <html>), from a DOM dump"""
    import html as _h  # attribute values are escaped in the dump
    import re as _re
    m = _re.search(r'data-owl-result="([^"]*)"', dom)
    return json.loads(_h.unescape(m.group(1))) if m else {}


def main(argv: list[str]) -> int:
    if argv[:1] == ["--list"]:
        found = candidates()
        for i, c in enumerate(found):
            print(("* " if i == 0 else "  ") + c["kind"].ljust(10) + " " + c["path"] + "  " + version(c["path"]))
        if not found:
            print("no browser found")
        return 0 if found else 1
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    print(json.dumps(print_pdf(argv[0], argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
