# -*- coding: utf-8 -*-
"""`offerowl open` and `offerowl panel --open`: the panel shown in the browser without a terminal browser and without a
wait, its address printed, and a clear exit when no Offerowl panel answers.

Run: python3 -m unittest discover -s tests/cli
"""
import contextlib  # the launcher's printed lines
import http.server  # a stand-in panel
import importlib.machinery  # the launcher has no .py name
import importlib.util  # a module from a spec
import io  # captured output
import json  # the health answer
import os  # the environment
import socket  # a free port
import sys  # the import path
import threading  # servers in the background
import time  # how long the panel takes to answer
import unittest  # the runner
import urllib.request  # asks the panel
from unittest import mock  # the browser and the system

from support import LAUNCHER, ROOT  # the launcher and the repository

sys.path.insert(0, str(ROOT / "src"))  # src/open_page.py
sys.path.insert(0, str(ROOT))  # apps/ for the panel
import open_page  # noqa: E402  the module under test

DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # a proxy setting must not carry a local address away


def free_port() -> int:
    """A port nothing listens on."""
    with socket.socket() as s:  # bound and released at once
        s.bind(("127.0.0.1", 0))  # the system picks one
        return s.getsockname()[1]


def stand_in(answer: dict):
    """A server on a free port whose /health says `answer`; returns (server, port)."""
    body = json.dumps(answer).encode()  # the same answer every time

    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802  the name http.server calls
            self.send_response(200)  # always answers
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # quiet
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Health)  # a free port
    threading.Thread(target=srv.serve_forever, daemon=True).start()  # answers in the background
    return srv, srv.server_address[1]


def launcher():
    """The launcher as a module, not started. It has no .py suffix, so the loader is named by hand; the module is made from a
    spec and run with exec_module (load_module() warned from 3.4 and is gone in 3.15)."""
    loader = importlib.machinery.SourceFileLoader("offerowl_launcher_open", str(LAUNCHER))
    spec = importlib.util.spec_from_file_location("offerowl_launcher_open", str(LAUNCHER), loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class OpenPage(unittest.TestCase):
    def test_under_wsl_windows_opens_it_and_nothing_waits(self):
        with mock.patch.object(open_page, "in_wsl", return_value=True), \
                mock.patch.object(open_page.shutil, "which", return_value="/mnt/c/WINDOWS/explorer.exe"), \
                mock.patch.object(open_page.subprocess, "Popen") as popen, mock.patch.object(open_page.webbrowser, "get") as get:
            self.assertTrue(open_page.open_page("http://127.0.0.1:8797/"))  # handed over
        self.assertEqual(["explorer.exe", "http://127.0.0.1:8797/"], popen.call_args[0][0])  # Windows' default browser
        get.assert_not_called()  # no Linux browser is asked

    def test_without_a_screen_no_browser_starts(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}  # a server, or SSH
        with mock.patch.object(open_page, "in_wsl", return_value=False), mock.patch.object(open_page.sys, "platform", "linux"), \
                mock.patch.dict(os.environ, env, clear=True), mock.patch.object(open_page.webbrowser, "get") as get:
            self.assertFalse(open_page.open_page("http://127.0.0.1:8797/"))  # the printed address is the way in
        get.assert_not_called()  # w3m or lynx would take the terminal and wait

    def test_a_terminal_browser_is_never_started(self):
        w3m = mock.Mock()  # what webbrowser registers for www-browser
        w3m.name = "www-browser"
        with mock.patch.object(open_page, "in_wsl", return_value=False), mock.patch.dict(os.environ, {"DISPLAY": ":0"}), \
                mock.patch.object(open_page.webbrowser, "get", return_value=w3m):
            self.assertFalse(open_page.open_page("http://127.0.0.1:8797/"))
        w3m.open.assert_not_called()  # it waits until it is closed

    def test_a_desktop_browser_opens_it(self):
        desk = mock.Mock()  # a desktop's default, such as xdg-open, Safari or Edge
        desk.name = "xdg-open"
        desk.open.return_value = True
        with mock.patch.object(open_page, "in_wsl", return_value=False), mock.patch.dict(os.environ, {"DISPLAY": ":0"}), \
                mock.patch.object(open_page.webbrowser, "get", return_value=desk):
            self.assertTrue(open_page.open_page("http://127.0.0.1:8797/"))
        desk.open.assert_called_once_with("http://127.0.0.1:8797/")


class OpenCommand(unittest.TestCase):
    def run_open(self, port: int):
        """`offerowl open --port port` in this process: (exit code, stdout, stderr, the page the browser was given)."""
        L = launcher()  # the launcher's functions
        out, err = io.StringIO(), io.StringIO()  # what it prints
        with mock.patch.dict(os.environ, {"OFFEROWL_LANG": "en"}), mock.patch.object(open_page, "open_page") as shown, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = L.main(["open", "--port", str(port)])
        return code, out.getvalue(), err.getvalue(), shown

    def test_the_running_panel_is_shown_and_its_address_printed(self):
        srv, port = stand_in({"ok": True, "app": "offerowl", "api": 1})  # an Offerowl panel
        self.addCleanup(srv.server_close)  # cleanups run last first: its socket closes after it stops
        self.addCleanup(srv.shutdown)
        code, out, err, shown = self.run_open(port)
        self.assertEqual(0, code, err)
        self.assertIn(f"http://127.0.0.1:{port}/", out)  # the way in, also with no screen
        shown.assert_called_once_with(f"http://127.0.0.1:{port}/")  # and the browser asked for it

    def test_another_program_on_the_port_is_not_taken_for_the_panel(self):
        srv, port = stand_in({"ok": True, "app": "something-else"})  # not ours
        self.addCleanup(srv.server_close)  # cleanups run last first: its socket closes after it stops
        self.addCleanup(srv.shutdown)
        code, out, err, shown = self.run_open(port)
        self.assertEqual(1, code)
        self.assertIn(f"port {port}", err)  # says where it looked
        shown.assert_not_called()

    def test_no_panel_says_how_to_start_one(self):
        code, out, err, shown = self.run_open(free_port())  # nothing listens
        self.assertEqual(1, code)
        self.assertIn("offerowl panel --open", err)  # what to do
        self.assertEqual("", out)  # stdout stays empty for scripts
        shown.assert_not_called()


class PanelOpen(unittest.TestCase):
    def test_the_panel_serves_while_the_browser_is_still_being_asked(self):
        """Before, `panel --open` asked the browser first and served after: a terminal browser (w3m under WSL) waited for a
        page that could not answer yet. A browser call that never returns must not stop the panel from answering."""
        from apps.panel import server  # the panel's command line
        import tempfile  # a data folder for this test
        data = tempfile.TemporaryDirectory()  # nothing of a real workspace
        self.addCleanup(data.cleanup)
        port = free_port()  # where it will listen
        made, asked, release = [], [], threading.Event()  # the server, the browser's calls, and the end of its wait

        def keep(*a, **k):  # the real server, kept so the test can stop it
            made.append(real_serve(*a, **k))
            return made[-1]

        def stuck(url):  # a browser that does not return until the test ends, as w3m waits for its page
            asked.append(url)
            release.wait()

        real_serve = server.serve  # wrapped, not replaced
        with mock.patch.object(server, "serve", side_effect=keep), mock.patch.object(open_page, "open_page", side_effect=stuck), \
                contextlib.redirect_stdout(io.StringIO()):
            runner = threading.Thread(target=server.main, args=(["--open", "--port", str(port), "--data", data.name],), daemon=True)
            runner.start()  # serves until shut down
            try:
                answered, deadline = None, time.monotonic() + 3  # the first health answer, within three seconds
                while answered is None and time.monotonic() < deadline:  # bound, then serving
                    try:
                        with DIRECT.open(f"http://127.0.0.1:{port}/health", timeout=0.5) as r:
                            answered = json.load(r)
                    except OSError:  # not bound yet, or bound and not serving
                        time.sleep(0.1)
                self.assertEqual("offerowl", (answered or {}).get("app"))  # it answers while the browser call is still stuck
                for _ in range(20):  # the browser is asked a moment after serving starts
                    if asked:
                        break
                    time.sleep(0.1)
                self.assertEqual([f"http://127.0.0.1:{port}/"], asked)  # with the panel's address
            finally:
                release.set()  # the stuck call returns
                if made:
                    made[0].shutdown()  # serve_forever returns
                    made[0].server_close()  # the port is free again
                runner.join(5)


if __name__ == "__main__":
    unittest.main()
