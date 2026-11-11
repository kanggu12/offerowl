"""The hooks the packaging needs in the panel and the launcher. The container, the chart and the install guide promise
things that only work when the panel and the launcher do their part; each test below is one such hook, with the reason.
A test is skipped while its hook is missing, and fails with OFFEROWL_REQUIRE_HOOKS=1 (CI sets it), so the promise
cannot ship without the hook.

Run: python3 -m unittest discover -s tests/packaging -v
"""
import ast  # read the desktop build's list of data folders
import importlib.machinery  # load the launcher, a file without .py
import importlib.util  # build a module from that file
import json  # the panel's answer
import re  # search the code
import socket  # a free port
import subprocess  # the panel as a child process
import time  # wait for it
import unittest  # the test framework
import urllib.error  # an error status is an answer
import urllib.request  # ask the panel

from pkg_support import ROOT, clean_env, hook, py


def code_mentions(name: str) -> bool:
    """True when a Python file under apps/ or src/ names the setting (reads it, or passes it on)"""
    for folder in ("apps", "src"):
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" not in str(path) and name in path.read_text(encoding="utf-8", errors="replace"):
                return True
    return False


def launcher():
    """./offerowl as a module"""
    loader = importlib.machinery.SourceFileLoader("offerowl_launcher_hooks", str(ROOT / "offerowl"))
    spec = importlib.util.spec_from_file_location("offerowl_launcher_hooks", str(ROOT / "offerowl"), loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HookTest(unittest.TestCase):
    def test_the_panel_reads_its_port_from_the_environment(self):
        # compose.yaml, the chart and the guide set it; a setting the code ignores would be a lie
        for name in ("OFFEROWL_PANEL_PORT",):
            if not code_mentions(name):
                hook(self, f"{name} is not read anywhere under apps/ or src/")

    def test_the_desktop_build_carries_every_folder_the_app_reads_at_run_time(self):
        # the one-file app unpacks to a temporary folder and reads these folders from files there. A folder that is not in
        # build.py's DATA is missing from the app: core/ holds the schemas that /api/v1/profile validates with, and the app
        # answered 500 there (FileNotFoundError on core/schema/profile.schema.json) until it was listed
        tree = ast.parse((ROOT / "apps" / "desktop" / "build.py").read_text(encoding="utf-8"))
        data = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DATA"][0]
        listed = {e.elts[0].value for e in data.elts}  # the source folders and files
        # the folders, the three pictures the panel serves, and the licenses: what the package and the app image carry too
        needed = {"core", "src", "examples", "fonts", "docs/assets/icon.svg", "docs/assets/logo-light.svg", "docs/assets/logo-dark.svg",
                  "LICENSE", "docs/THIRD_PARTY_NOTICES.md",
                  "deploy/python/offerowl/__init__.py"} | {  # the version the bar beside the wordmark shows ("0" without it)
            f"apps/{d.name}" for d in (ROOT / "apps").iterdir() if d.is_dir() and d.name != "desktop" and (d / "__init__.py").is_file()}
        if needed - listed:
            hook(self, f"apps/desktop/build.py: DATA lacks {sorted(needed - listed)}")

    def test_the_launcher_lists_the_doctor(self):
        # `offerowl doctor` works from the package and the container without this; ./offerowl doctor in a checkout needs
        # the launcher's COMPONENTS to name src/doctor.py (and ORDER and the help text)
        if "doctor" not in getattr(launcher(), "COMPONENTS", {}):
            hook(self, "./offerowl does not list `doctor` (offerowl: COMPONENTS, ORDER and the cmd_doctor messages)")
        r = subprocess.run([py(), str(ROOT / "offerowl"), "doctor", "--only", "python"], capture_output=True, text=True, env=clean_env(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_panel_answers_the_host_names_it_is_told(self):
        # behind an Ingress the Host header is the Ingress' name; the panel refuses every name it does not know
        if not code_mentions("OFFEROWL_ALLOWED_HOSTS"):
            hook(self, "OFFEROWL_ALLOWED_HOSTS is not read where the panel builds its Host and Origin lists (apps/api/web.py: Handler.bind)")
        port = free_port()
        data = ROOT / "output" / f"_hooks_{port}"  # a folder of its own, removed below
        env = clean_env(OFFEROWL_DATA_DIR=str(data), OFFEROWL_ALLOWED_HOSTS="panel.example.invalid,other.example.invalid")
        child = subprocess.Popen([py(), str(ROOT / "apps" / "panel" / "server.py"), "--port", str(port)], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: __import__("shutil").rmtree(data, ignore_errors=True))
        self.addCleanup(child.kill)

        def ask(host: str, path: str = "/health", origin: str = "") -> int:
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": host, **({"Origin": origin} if origin else {})})
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code
            except OSError:
                return 0
        for _ in range(60):
            if ask(f"127.0.0.1:{port}") == 200:
                break
            time.sleep(0.5)
        self.assertEqual(ask(f"127.0.0.1:{port}"), 200)
        self.assertEqual(ask("panel.example.invalid"), 200)  # an Ingress sends its own name, with no port
        self.assertEqual(ask("other.example.invalid"), 200)
        self.assertEqual(ask("evil.example.invalid"), 403)  # a name nobody listed is still refused
        # a write from the Ingress' page carries its Origin
        body = json.dumps({"lang": "ko"}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/settings", data=body, method="POST",
                                     headers={"Host": "panel.example.invalid", "Content-Type": "application/json", "Origin": "https://panel.example.invalid"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5) as r:
            self.assertEqual(r.status, 200)
        self.assertTrue(re.search(r"ko", (data / "settings.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
