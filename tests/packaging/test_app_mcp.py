"""The desktop app as the agent's tools (apps/desktop/app.py roles): `<the app> mcp` runs apps/mcp/__main__.py, the file
the panel's command bar starts, with its requests on the caller's pipes (docs/MCP.md). Checked on this checkout with the
standard library: the server answers initialize and lists its tools with no panel running (a tool that reads the panel
fails only when it is called), and a crash of that role ends in exit 1 with no notice for a person to read."""
import importlib.util  # the app, by its file
import json  # the protocol's messages
import os  # the data folder
import pathlib  # paths
import subprocess  # the role, as an agent starts it
import sys  # this Python, which runs the checkout's app
import tempfile  # a data folder of the test's own
import unittest  # the runner
from unittest import mock  # the script and the notice, caught

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
APP_FILE = ROOT / "apps" / "desktop" / "app.py"  # what the one-file app runs
SPEC = importlib.util.spec_from_file_location("offerowl_desktop_app_mcp", APP_FILE)  # not on the import path
APP = importlib.util.module_from_spec(SPEC)  # the module
SPEC.loader.exec_module(APP)  # read once

HELLO = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",  # what an agent sends first
          "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
         {"jsonrpc": "2.0", "method": "notifications/initialized"},  # no reply
         {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]  # the tools the agent would get


class McpRoleTest(unittest.TestCase):
    def test_the_app_answers_as_the_agents_tools(self):
        env = {**os.environ, "OFFEROWL_LANG": "en"}  # the words to stderr in one language
        env.pop("OFFEROWL_VERSION", None)  # the version from src/version.py, as in the app
        done = subprocess.run([sys.executable, str(APP_FILE), "mcp", "--url", "http://127.0.0.1:9"],  # a port nothing answers on
                              input="\n".join(json.dumps(m) for m in HELLO) + "\n", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=120)  # stdin closes after the last line: it ends
        replies = {}  # each answer by its id
        for line in done.stdout.splitlines():  # stdout carries the protocol only
            replies[json.loads(line)["id"]] = json.loads(line)  # a line that is not JSON fails the test here
        self.assertEqual(done.returncode, 0, done.stderr[-600:])
        info = replies[1]["result"]["serverInfo"]  # who answered
        self.assertEqual(info["name"], "offerowl")
        sys.path.insert(0, str(ROOT))  # apps/, for the server's own reading of the version
        from apps.mcp.server import version  # the one line this copy writes, read as the server reads it
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "OFFEROWL_VERSION"}, clear=True):
            self.assertEqual(info["version"], version())  # the version it says is this copy's
        self.assertRegex(info["version"], r"^\d+\.\d+\.\d+$")  # a release's number, never "0"
        self.assertGreater(len(replies[2]["result"]["tools"]), 10)  # the tools the command bar has

    def test_a_crash_of_the_role_shows_no_notice(self):
        with tempfile.TemporaryDirectory() as data, \
                mock.patch.dict(os.environ, {"OFFEROWL_DATA_DIR": data}), \
                mock.patch.object(APP, "run_script", side_effect=RuntimeError("boom")) as script, \
                mock.patch.object(APP, "tell") as tell, \
                mock.patch("sys.stderr"):  # the report goes there; kept off the test's own output
            self.assertEqual(APP.main(["mcp", "--url", "http://127.0.0.1:9"]), 1)  # a failure, said by the exit code
        self.assertEqual(script.call_args[0][0][0], str(ROOT / "apps" / "mcp" / "__main__.py"))  # the file the command bar starts
        self.assertEqual(script.call_args[0][0][1:], ["--url", "http://127.0.0.1:9"])  # its options, as given
        tell.assert_not_called()  # an agent's helper: no page or box for a person who did not start it


if __name__ == "__main__":
    unittest.main()
