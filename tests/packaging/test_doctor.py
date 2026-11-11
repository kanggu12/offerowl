"""Tests of `offerowl doctor` (src/doctor.py): each check against a PC that is set up on purpose (fake programs on a
PATH of its own, a stub server, a read-only folder), the messages in both languages, the exit codes, and that the doctor
changes nothing and prints no secret.

Run: python3 -m unittest discover -s tests/packaging -v
"""
import ast  # find the message keys the code asks for
import http.server  # a stub model server and a stub panel
import json  # the doctor's --json
import os  # environment, modes
import pathlib  # paths
import re  # placeholders
import socket  # a taken port
import stat  # executable bits
import sys  # module path
import threading  # stub servers
import unittest  # the test framework
from unittest import mock  # patch the environment and the doctor's helpers

from pkg_support import ROOT, SRC, clean_env, load_module, py, run, tmpdir

sys.path.insert(0, str(SRC))
import doctor  # noqa: E402  the program under test
import llm  # noqa: E402  its settings and messages

REAL_RENDERER_REPORT = doctor.renderer_report  # the tests patch the name; this keeps the real, cached function


def fake_bin(folder: pathlib.Path, **programs: str) -> pathlib.Path:
    """A folder of small shell programs (name -> script body) to use as the whole PATH of a test"""
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in programs.items():
        path = folder / name
        path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return folder


def env_with(path: pathlib.Path, **extra: str):
    """Patch the environment: no OFFEROWL_ settings, PATH is only `path`, the data folder is a throwaway one"""
    base = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_")}
    base.update(PATH=str(path), OFFEROWL_LANG="en", **extra)
    return mock.patch.dict(os.environ, base, clear=True)


@unittest.skipUnless(os.name == "posix", "the fake programs are shell scripts")
class ChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.bin = self.tmp / "bin"
        self.data = self.tmp / "data"
        # no browser renderer unless a test brings one: the real report starts node and the browser of this PC
        patcher = mock.patch.object(doctor, "renderer_report", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    # --- python, data folder, engine folders, libraries

    def test_python_is_ok_here_and_fails_when_too_old(self):
        self.assertEqual(doctor.check_python().status, "ok")
        with mock.patch.object(doctor, "MIN_PYTHON", (99, 0)):
            r = doctor.check_python()
        self.assertEqual(r.status, "fail")
        self.assertIn("99.0", r.fix)

    def test_data_folder_ok_when_writable_and_nothing_is_created(self):
        target = self.tmp / "not" / "made" / "yet"
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(target)):
            r = doctor.check_data()
        self.assertEqual(r.status, "ok", r.detail)
        self.assertFalse((self.tmp / "not").exists(), "the doctor must not create the data folder")

    def test_data_folder_fails_when_it_cannot_be_written(self):
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.data)), mock.patch.object(doctor, "writable_dir", return_value=False):
            r = doctor.check_data()
        self.assertEqual(r.status, "fail")
        self.assertIn("OFFEROWL_DATA_DIR", r.fix)

    def test_data_folder_warns_when_the_disk_is_nearly_full(self):
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.tmp)), mock.patch.object(doctor, "free_gb", return_value=0.2):
            r = doctor.check_data()
        self.assertEqual(r.status, "warn")
        self.assertIn("0.2", r.detail)

    def test_writable_dir_tells_a_file_in_the_way_from_a_free_place(self):
        (self.tmp / "afile").write_text("x")
        self.assertTrue(doctor.writable_dir(self.tmp))
        self.assertFalse(doctor.writable_dir(self.tmp / "afile" / "sub"))  # nothing can be created under a file
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["afile"], "the probe file must be removed")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write anywhere")
    def test_writable_dir_is_false_for_a_read_only_folder(self):
        locked = self.tmp / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        self.addCleanup(locked.chmod, 0o700)
        self.assertFalse(doctor.writable_dir(locked))
        self.assertFalse(doctor.writable_dir(locked / "new"))

    def test_data_folder_rule_is_the_one_of_the_desktop_app(self):
        app = load_module("offerowl_desktop_app", ROOT / "apps" / "desktop" / "app.py")
        home = str(self.tmp / "home")
        for env in ({"OFFEROWL_DATA_DIR": str(self.data)}, {"XDG_DATA_HOME": str(self.tmp / "xdg")}, {"HOME": home}):
            with mock.patch.dict(os.environ, {"HOME": home, **env}, clear=True):
                self.assertEqual(doctor.data_dir(), app.data_dir(), env)

    def test_libs_are_reported_with_the_exact_command_that_installs_them(self):
        tree = self.tmp / "tree"
        (tree / "node_modules" / "docx").mkdir(parents=True)
        with mock.patch.object(doctor, "ROOT", tree):
            self.assertEqual(doctor.check_libs().status, "ok")
        (tree / "node_modules" / "docx").rmdir()
        with mock.patch.object(doctor, "ROOT", tree), mock.patch.object(doctor, "in_container", return_value=False):
            r = doctor.check_libs()
        self.assertEqual(r.status, "fail")
        self.assertIn(f"OFFEROWL_NET=1 {tree / 'render' / 'run.sh'} npm ci", r.fix)
        with mock.patch.object(doctor, "ROOT", tree), mock.patch.object(doctor, "in_container", return_value=True):
            self.assertIn("Dockerfile", doctor.check_libs().fix)  # inside the image the fix is another image

    def test_engine_folder_fails_when_its_output_cannot_be_written(self):
        with mock.patch.object(doctor, "writable_dir", return_value=False):
            r = doctor.check_engine()
        self.assertEqual(r.status, "fail")
        self.assertIn("pip install .", r.fix)  # a place the person owns: there is no package to install by name

    # --- typesetting (docker, or the tools inside the container)

    def test_render_fails_without_docker_and_names_the_install_page(self):
        fake_bin(self.bin)
        with env_with(self.bin), mock.patch.object(doctor, "in_container", return_value=False):
            r = doctor.check_render()
        self.assertEqual(r.status, "fail")
        self.assertIn("Docker", r.fix)
        self.assertIn("docs.docker.com", r.fix)

    def test_render_fails_when_docker_is_installed_but_its_engine_is_off(self):
        fake_bin(self.bin, docker="echo 'Cannot connect to the Docker daemon' >&2; exit 1", bash="exit 0")
        with env_with(self.bin), mock.patch.object(doctor, "in_container", return_value=False):
            r = doctor.check_render()
        self.assertEqual(r.status, "fail")
        self.assertIn("does not answer", r.detail)

    def test_render_ok_with_a_working_docker_and_says_when_the_image_is_not_built(self):
        script = 'case "$1" in version) echo 27.1.0;; image) exit 1;; esac'
        fake_bin(self.bin, docker=script, bash="exit 0")
        with env_with(self.bin), mock.patch.object(doctor, "in_container", return_value=False):
            r = doctor.check_render()
        self.assertEqual(r.status, "ok", r.detail)
        self.assertIn("27.1.0", r.detail)
        self.assertIn("first build", r.detail)
        fake_bin(self.bin, docker='case "$1" in version) echo 27.1.0;; image) exit 0;; esac')
        with env_with(self.bin), mock.patch.object(doctor, "in_container", return_value=False):
            self.assertIn("image is built", doctor.check_render().detail)

    def test_render_named_container_on_windows_fails_as_the_build_does(self):
        # the build refuses the container on Windows (render/run.sh is a shell script); doctor said "ok" with Docker and bash there
        script = 'case "$1" in version) echo 27.1.0;; image) exit 0;; esac'
        fake_bin(self.bin, docker=script, bash="exit 0")
        with env_with(self.bin, OFFEROWL_RENDERER="container"), mock.patch.object(doctor, "in_container", return_value=False), \
                mock.patch.object(doctor.sys, "platform", "win32"):
            r = doctor.check_render()
        self.assertEqual(r.status, "fail")
        self.assertIn("cannot start", r.detail)  # the reason, not a missing Docker (which("docker") on Windows looks for docker.exe)
        self.assertIn("html", r.fix)  # and the two ways that work
        self.assertIn("WSL", r.fix)

    def test_render_needs_bash_because_run_sh_is_a_bash_script(self):
        fake_bin(self.bin, docker='case "$1" in version) echo 27.1.0;; esac')
        with env_with(self.bin), mock.patch.object(doctor, "in_container", return_value=False):
            r = doctor.check_render()
        self.assertEqual(r.status, "fail")
        self.assertIn("bash", r.detail)

    def test_render_inside_the_container_checks_its_own_tools(self):
        fake_bin(self.bin, **{name: "exit 0" for name in doctor.CONTAINER_TOOLS})
        with env_with(self.bin), mock.patch.object(doctor, "in_container", return_value=True):
            self.assertEqual(doctor.check_render().status, "ok")
        (self.bin / "soffice").unlink()
        with env_with(self.bin), mock.patch.object(doctor, "in_container", return_value=True):
            r = doctor.check_render()
        self.assertEqual(r.status, "fail")
        self.assertIn("soffice", r.detail)

    # --- typesetting with the PC's own browser (OFFEROWL_RENDERER=html)

    def report(self, html_needs=(), browser="/usr/bin/google-chrome", kind="chrome", node="v22.1.0"):
        """What src/render_html/render.py doctor prints, for a PC set up on purpose"""
        return {"html": {"ok": not html_needs, "needs": list(html_needs),
                         "found": {"browser": browser, "kind": kind, "node": "/usr/bin/node", "node_version": node,
                                   "pillow": True, "browsers": [browser]}},
                "container": {"ok": True, "needs": [], "found": {"docker": "/usr/bin/docker", "inside": False}}}

    def html(self, report, **env):
        fake_bin(self.bin)
        with env_with(self.bin, OFFEROWL_RENDERER="html", **env), mock.patch.object(doctor, "in_container", return_value=False), \
                mock.patch.object(doctor, "renderer_report", return_value=report):
            return doctor.check_render()

    def test_html_renderer_ready_names_the_browser_and_node(self):
        r = self.html(self.report())
        self.assertEqual(r.status, "ok", r.detail)
        self.assertIn("google-chrome", r.detail)
        self.assertIn("22.1.0", r.detail)

    def test_html_renderer_missing_parts_are_named_with_a_fix_each(self):
        r = self.html(self.report(["browser", "node", "pillow", "fonts:Pretendard"], browser=None))
        self.assertEqual(r.status, "fail")
        for word in ("a browser", "Node.js", "Pillow", "Pretendard"):
            self.assertIn(word, r.detail)
        for word in ("Edge", "nodejs.org", "pip install pillow", "Reinstall"):
            self.assertIn(word, r.fix)

    def test_html_renderer_leaves_the_libraries_to_their_own_row(self):
        self.assertEqual(self.html(self.report(["node_modules"])).status, "ok")  # the libraries row says how to install them
        tree = self.tmp / "tree"
        tree.mkdir()
        fake_bin(self.bin)
        with env_with(self.bin, OFFEROWL_RENDERER="html"), mock.patch.object(doctor, "ROOT", tree), mock.patch.object(doctor, "in_container", return_value=False):
            r = doctor.check_libs()
        self.assertEqual(r.status, "fail")
        self.assertIn(f"cd {tree} && npm ci", r.fix)  # no container, so npm runs on this PC
        self.assertNotIn("run.sh", r.fix)

    def test_html_renderer_without_a_browser_renderer_in_this_copy(self):
        r = self.html(None)
        self.assertEqual(r.status, "fail")
        self.assertIn("no browser renderer", r.detail)

    def test_a_renderer_that_does_not_exist_is_refused_not_guessed(self):
        fake_bin(self.bin)
        with env_with(self.bin, OFFEROWL_RENDERER="libre"), mock.patch.object(doctor, "in_container", return_value=False):
            r = doctor.check_render()
        self.assertEqual(r.status, "fail")
        self.assertIn("libre", r.detail)
        self.assertIn("container", r.fix)

    def test_without_docker_the_fix_names_the_browser_renderer_when_it_would_work(self):
        fake_bin(self.bin)
        for ready, expected in ((self.report(), True), (self.report(["browser"], browser=None), False)):
            with env_with(self.bin), mock.patch.object(doctor, "in_container", return_value=False), \
                    mock.patch.object(doctor, "renderer_report", return_value=ready):
                r = doctor.check_render()
            self.assertEqual(r.status, "fail")
            self.assertEqual("OFFEROWL_RENDERER=html" in r.fix, expected, r.fix)

    def test_the_renderers_own_report_is_read_when_this_copy_has_one(self):
        # the contract with src/render_html/render.py: `doctor` prints {"html": {ok, needs, found}, "container": {...}}
        if not (ROOT / "src" / "render_html" / "render.py").is_file():
            self.skipTest("this copy has no browser renderer")
        data = REAL_RENDERER_REPORT.__wrapped__()  # past the cache, and past the patch of setUp
        self.assertIsNotNone(data, "the browser renderer's doctor command printed no usable JSON")
        self.assertEqual(sorted(data), ["container", "html"])
        for key in ("ok", "needs", "found"):
            self.assertIn(key, data["html"])
        self.assertIsInstance(data["html"]["needs"], list)

    # --- browsers

    def test_browsers_are_listed_once_per_file(self):
        real = fake_bin(self.bin, **{"google-chrome-stable": "exit 0"})
        (real / "google-chrome").symlink_to(real / "google-chrome-stable")  # a link to the same file
        with env_with(self.bin):
            names = [n for n, _ in doctor.browser_paths()]
        self.assertEqual(len(names), 1, names)

    def test_browsers_warn_when_there_is_no_browser_and_no_playwright(self):
        fake_bin(self.bin)
        with env_with(self.bin), mock.patch("importlib.util.find_spec", return_value=None), \
                mock.patch.object(doctor.webbrowser, "get", side_effect=doctor.webbrowser.Error("none")):
            r = doctor.check_browser()
        self.assertEqual(r.status, "warn")
        self.assertIn("Chromium", r.fix)

    def test_browsers_warn_when_there_is_nothing_to_open_the_panel_with(self):
        fake_bin(self.bin, chromium="exit 0")
        with env_with(self.bin), mock.patch.object(doctor.webbrowser, "get", side_effect=doctor.webbrowser.Error("none")):
            r = doctor.check_browser()
        self.assertEqual(r.status, "warn")
        self.assertIn("http://127.0.0.1:8797", r.fix)

    def test_a_container_needs_no_default_browser(self):
        fake_bin(self.bin, chromium="exit 0")
        with env_with(self.bin), mock.patch.object(doctor, "in_container", return_value=True), \
                mock.patch.object(doctor.webbrowser, "get", side_effect=doctor.webbrowser.Error("none")):
            r = doctor.check_browser()
        self.assertEqual(r.status, "ok", r.detail)  # nothing to open a page on, and nothing to warn about

    # --- the AI backends

    def claude(self, logged_in: bool) -> None:
        fake_bin(self.bin, claude=f'[ "$1 $2" = "auth status" ] && echo \'{{"loggedIn": {str(logged_in).lower()}, "email": "someone@example.invalid"}}\'')

    def test_ai_ok_with_a_signed_in_claude_code_and_never_prints_the_account(self):
        self.claude(True)
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.data)):
            r = doctor.check_ai()
        self.assertEqual(r.status, "ok", r.detail)
        self.assertIn("claude-code", r.detail)
        self.assertNotIn("someone@example.invalid", json.dumps(r.__dict__))

    def test_ai_warns_with_the_sign_in_command_when_claude_code_is_signed_out(self):
        self.claude(False)
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.data), OFFEROWL_LLM="claude-code"):
            r = doctor.check_ai()
        self.assertEqual(r.status, "warn")
        self.assertIn("claude auth login", r.fix)

    def test_ai_warns_when_nothing_is_set_up_and_says_how_to_start(self):
        fake_bin(self.bin)
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.data)):
            r = doctor.check_ai()
        self.assertEqual(r.status, "warn")
        for word in ("claude auth login", "codex login", "OFFEROWL_LLM_URL"):
            self.assertIn(word, r.fix)

    def test_ai_none_chosen_on_purpose_is_ok(self):
        fake_bin(self.bin)
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.data), OFFEROWL_LLM="none"):
            self.assertEqual(doctor.check_ai().status, "ok")

    def test_ai_local_server_up_and_down(self):
        class Models(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Models)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        fake_bin(self.bin)
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.data), OFFEROWL_LLM="openai-compat", OFFEROWL_LLM_URL=url):
            up = doctor.check_ai()
        self.assertEqual(up.status, "ok", up.detail)
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.data), OFFEROWL_LLM="openai-compat", OFFEROWL_LLM_URL="http://127.0.0.1:9"):
            down = doctor.check_ai()
        self.assertEqual(down.status, "warn")
        self.assertIn("OFFEROWL_LLM_URL", down.fix)

    def test_ai_reads_the_panels_saved_choice(self):
        self.data.mkdir()
        (self.data / "settings.json").write_text(json.dumps({"backend": "none"}))
        fake_bin(self.bin)
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.data)):
            r = doctor.check_ai()
        self.assertEqual(r.status, "ok")  # the panel's choice stands in for the default order

    def test_ai_warns_when_an_address_is_named_but_the_backend_is_not(self):
        fake_bin(self.bin)
        with env_with(self.bin, OFFEROWL_DATA_DIR=str(self.data), OFFEROWL_LLM_URL="http://127.0.0.1:9"):
            r = doctor.check_ai()
        self.assertEqual(r.status, "warn")
        self.assertIn("OFFEROWL_LLM=openai-compat", r.fix)

    def test_the_password_of_a_model_server_address_is_never_printed(self):
        self.assertEqual(doctor.hide_password("http://user:secret@host:11434/v1"), "http://host:11434/v1")
        self.assertEqual(doctor.hide_password("localhost:11434"), "localhost:11434")

    # --- fonts, ports, poppler

    def test_fonts_fail_when_a_file_is_missing(self):
        tree = self.tmp / "tree"
        (tree / "fonts").mkdir(parents=True)
        for name in doctor.FONT_FILES[:2]:
            (tree / "fonts" / name).write_bytes(b"x")
        with mock.patch.object(doctor, "ROOT", tree):
            r = doctor.check_fonts()
        self.assertEqual(r.status, "fail")
        self.assertIn(doctor.FONT_FILES[2], r.detail)
        (tree / "fonts" / doctor.FONT_FILES[2]).write_bytes(b"x")
        with mock.patch.object(doctor, "ROOT", tree):
            self.assertEqual(doctor.check_fonts().status, "ok")

    def listener(self, handler=None):
        """A listening socket on a free port; with a handler class, an HTTP server on it"""
        if handler is None:
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            s.listen()
            self.addCleanup(s.close)
            return s.getsockname()[1]
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_ports_free_busy_and_offerowl_itself(self):
        class Health(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b'{"ok": true, "app": "offerowl"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        with socket.socket() as s:  # a port nobody holds
            s.bind(("127.0.0.1", 0))
            free = s.getsockname()[1]
        self.assertEqual(doctor.port_state(free), "free")
        self.assertEqual(doctor.port_state(self.listener()), "busy")  # a socket that is not HTTP at all
        self.assertEqual(doctor.port_state(self.listener(Health)), "mine")
        with mock.patch.object(doctor, "panel_port", return_value=self.listener()):  # the panel's port, held by another program
            r = doctor.check_ports()
        self.assertEqual(r.status, "warn")
        self.assertIn("another program", r.detail)
        self.assertIn("offerowl panel --port", r.fix)

    def test_the_ports_follow_the_settings_the_panel_reads(self):
        with env_with(self.bin):
            self.assertEqual(doctor.panel_port(), 8797)
        with env_with(self.bin, OFFEROWL_PANEL_PORT="18797"):
            self.assertEqual(doctor.panel_port(), 18797)
        with env_with(self.bin, OFFEROWL_PANEL_PORT="not a number"):
            self.assertEqual(doctor.panel_port(), 8797)  # a typo does not stop the doctor

    def test_a_missing_pdf_reader_warns_with_a_fix_for_the_system(self):
        import pdftools  # the module the row asks
        fake_bin(self.bin)
        with env_with(self.bin), mock.patch.object(pdftools, "have_pdfium", lambda: False):
            r = doctor.check_poppler()
        self.assertEqual(r.status, "warn")
        self.assertTrue(r.fix)
        with env_with(self.bin), mock.patch.object(pdftools, "have_pdfium", lambda: True):  # PDFium alone is enough
            self.assertEqual(doctor.check_poppler().status, "ok")
        fake_bin(self.bin, pdftotext="exit 0", pdftoppm="exit 0", pdfinfo="exit 0")  # and so is poppler alone
        with env_with(self.bin), mock.patch.object(pdftools, "have_pdfium", lambda: False):
            self.assertEqual(doctor.check_poppler().status, "ok")


class MessagesTest(unittest.TestCase):
    def test_both_languages_have_the_same_keys_and_placeholders(self):
        self.assertEqual(sorted(doctor.MSG["en"]), sorted(doctor.MSG["ko"]))
        for key, text in doctor.MSG["en"].items():
            self.assertEqual(set(re.findall(r"\{(\w+)\}", text)), set(re.findall(r"\{(\w+)\}", doctor.MSG["ko"][key])), key)
            self.assertTrue(doctor.MSG["ko"][key].strip(), key)

    def test_every_t_call_names_a_message_that_exists(self):
        def keys(node):  # the message keys an expression can evaluate to: a string, or either branch of "a if x else b"
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return {node.value}  # a prefix such as "mark_" (t("mark_" + status)) is a BinOp, which is skipped
            if isinstance(node, ast.IfExp):
                return keys(node.body) | keys(node.orelse)
            return set()
        used = set()
        for node in ast.walk(ast.parse((SRC / "doctor.py").read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("t", "row") and node.args:
                used |= keys(node.args[0])
        self.assertGreater(len(used), 40)  # the walk found the calls
        for key in used:
            # row("python", ...) names a check, whose title is the message t_python
            self.assertIn("t_" + key if key in doctor.CHECKS else key, doctor.MSG["en"], key)

    def test_every_check_has_a_title_in_both_languages(self):
        for key in doctor.CHECKS:
            for lang in ("en", "ko"):
                self.assertIn("t_" + key, doctor.MSG[lang], key)

    def test_the_fix_messages_for_every_system_exist(self):
        for prefix in ("render_nodocker_fix_", "poppler_fix_"):
            for kind in ("linux", "mac", "win"):
                self.assertIn(prefix + kind, doctor.MSG["en"])


class VersionTest(unittest.TestCase):
    def test_the_image_the_installed_package_and_a_folder_each_say_their_own_version(self):
        import importlib.metadata
        env = {k: v for k, v in os.environ.items() if k != "OFFEROWL_VERSION"}
        with mock.patch.dict(os.environ, {**env, "OFFEROWL_VERSION": "9.9.9"}, clear=True):
            self.assertEqual(doctor.version(), "9.9.9")  # the app image
        written = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "deploy" / "python" / "offerowl" / "__init__.py").read_text(encoding="utf-8")).group(1)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(importlib.metadata, "version", return_value="0.0.1"):
            self.assertEqual(doctor.version(), written)  # a checkout says the version its one line writes: a build's old egg-info beside it never wins
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(importlib.metadata, "version", return_value="1.2.3"):
            self.assertEqual(doctor.version(places=()), "1.2.3")  # installed with pip, where only the metadata says it
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(importlib.metadata, "version", side_effect=importlib.metadata.PackageNotFoundError):
            self.assertEqual(doctor.version(places=()), "checkout")  # neither: a folder of source files


class CommandTest(unittest.TestCase):
    def doctor(self, *args: str, env=None, source=None):
        return run([py(), str(source or SRC / "doctor.py"), *args], env=env or clean_env())

    def test_json_has_every_check_with_its_status(self):
        r = self.doctor("--json", "--only", "python,fonts")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual([c["key"] for c in data["checks"]], ["python", "fonts"])
        self.assertEqual(data["summary"], {"warn": 0, "fail": 0})
        for c in data["checks"]:
            self.assertEqual(sorted(c), ["detail", "fix", "key", "status", "title"])

    def test_the_text_report_ends_with_a_result_line_and_korean_works(self):
        for lang, marker in (("en", "Result:"), ("ko", "결과:")):
            r = self.doctor("--only", "python", env=clean_env(OFFEROWL_LANG=lang))
            self.assertEqual(r.returncode, 0)
            self.assertIn(marker, r.stdout)

    def test_a_wrong_check_name_is_a_usage_error_not_a_pass(self):
        r = self.doctor("--only", "nonsense")
        self.assertEqual(r.returncode, 2)
        self.assertIn("nonsense", r.stderr)

    def test_exit_code_is_1_when_a_check_fails(self):
        tree = tmpdir(self)  # a copy of the doctor in a tree that has no fonts
        (tree / "src").mkdir()
        for name in ("doctor.py", "llm.py"):
            (tree / "src" / name).write_text((SRC / name).read_text(encoding="utf-8"), encoding="utf-8")
        r = self.doctor("--only", "fonts", source=tree / "src" / "doctor.py")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAIL", r.stdout)
        self.assertIn("Fix:", r.stdout)

    def test_korean_columns_line_up_by_display_width(self):
        rows = [doctor.Check("a", "ok", "데이터 폴더", "|"), doctor.Check("b", "warn", "Python", "|", "fix"),
                doctor.Check("c", "fail", "조판", "|")]
        with mock.patch.dict(os.environ, {"OFFEROWL_LANG": "ko"}):
            lines = [x for x in doctor.render(rows).splitlines() if "|" in x]
        self.assertEqual(len(lines), 3)
        self.assertEqual(len({doctor.cells(x[:x.index("|")]) for x in lines}), 1, lines)  # the detail starts at one terminal column
        self.assertEqual(doctor.cells("조판"), 4)
        self.assertEqual(doctor.pad("조판", 6), "조판  ")

    def test_the_doctor_changes_nothing_and_prints_no_secret(self):
        data = tmpdir(self) / "never" / "made"
        secret = "s3cr3t-key-value"
        env = clean_env(OFFEROWL_DATA_DIR=str(data), OFFEROWL_LLM="openai-compat", OFFEROWL_LLM_KEY=secret,
                        OFFEROWL_LLM_URL="http://someone:hunter2@127.0.0.1:9")
        r = self.doctor("--json", env=env)
        self.assertNotIn(secret, r.stdout + r.stderr)
        self.assertNotIn("hunter2", r.stdout + r.stderr)
        self.assertFalse(data.exists(), "the doctor must not create the data folder")


if __name__ == "__main__":
    unittest.main()
