# -*- coding: utf-8 -*-
"""Open a page of Offerowl in the person's browser from the command line (`offerowl open`, `offerowl panel --open`).

Python's webbrowser takes a terminal browser (w3m, lynx) where no desktop one is registered, as under WSL or on a server,
and waits for it to exit: the terminal is taken, and a panel that has not started serving yet never answers it. So under
WSL the page opens in Windows' own browser, a terminal browser is never started, and a computer without a screen is left
with the address the caller printed.
"""
import os  # the variables that say a screen is there
import platform  # the kernel's name, which says WSL
import shutil  # is Windows' explorer.exe reachable
import subprocess  # starts Windows' opener without waiting
import sys  # the system's name
import webbrowser  # the desktop's default browser

CONSOLE = {"www-browser", "w3m", "lynx", "links", "elinks", "browsh"}  # browsers that run inside the terminal


def in_wsl() -> bool:
    """True under WSL, where the person's browser is the Windows one."""
    return sys.platform.startswith("linux") and "microsoft" in platform.uname().release.lower()  # WSL kernels say so in their release


def open_page(url: str) -> bool:
    """Open url in the person's browser and return at once. False when there is no browser to open it in: the address the
    caller printed is then the way in."""
    if in_wsl() and shutil.which("explorer.exe"):  # WSL: Windows' default browser reaches the same 127.0.0.1
        subprocess.Popen(["explorer.exe", url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,  # never waited on
                         stderr=subprocess.DEVNULL)  # explorer.exe reports nothing useful
        return True  # handed to Windows
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):  # no screen
        return False  # a server, or a terminal over SSH
    try:  # the desktop's default
        browser = webbrowser.get()  # what the system registered
    except webbrowser.Error:  # none at all
        return False  # the printed address
    if getattr(browser, "name", "") in CONSOLE:  # it would take the terminal and wait
        return False  # the printed address
    return bool(browser.open(url))  # Windows, macOS and desktop Linux return as soon as the browser has it
