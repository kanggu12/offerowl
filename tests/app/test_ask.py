"""The command bar (apps/api/ask.py): the route keeps every ask with its answer; with no agent that can act through
tools it says so plainly; empty words are refused; Claude Code's stream is read for its answer and the tools it ran.
No real model is called.

    python3 -m unittest tests/app/test_ask.py -v
"""
import json  # the stream lines
import pathlib  # paths
import sys  # the import path
import time  # waiting for the task
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "app"))
from apps.api import ask as A  # noqa: E402
from test_panel import PanelCase  # noqa: E402


class TestReading(unittest.TestCase):
    def test_claude_stream(self):
        lines = [{"type": "system"}, {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__offerowl__list_jobs"}]}},
                 {"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}},
                 {"type": "result", "result": "Two applications are at the interview.", "is_error": False}]
        answer, tools, failed = A.read_claude("\n".join(json.dumps(x) for x in lines))
        self.assertEqual("Two applications are at the interview.", answer)
        self.assertEqual(["list_jobs"], tools)   # the server's prefix taken off
        self.assertFalse(failed)

    def test_claude_command_keeps_to_offerowl(self):
        class Api: port = 8123
        with __import__("tempfile").TemporaryDirectory() as d:
            cmd = A.claude_command(Api(), pathlib.Path(d))
            cfg = json.loads((pathlib.Path(d) / "mcp.json").read_text())
        self.assertIn("--strict-mcp-config", cmd)   # none of the person's own servers
        self.assertEqual("", cmd[cmd.index("--tools") + 1])   # no built-in tools: no shell, no files, no web
        self.assertEqual("mcp__offerowl", cmd[cmd.index("--allowedTools") + 1])
        self.assertIn("http://127.0.0.1:8123", cfg["mcpServers"]["offerowl"]["args"])   # this panel

    def test_the_agent_fetches_only_the_links_the_person_wrote(self):
        # a posting the agent reads can carry instructions; a link written there could carry what the agent read out in its
        # query, so the MCP server of an ask fetches only the links in the person's own words (and none when there are none)
        class Api: port = 8123
        words = "이 공고 https://jobs.example.com/view?id=12에 맞춰 줘. 그리고 (https://example.org/p)."
        self.assertEqual(["https://jobs.example.com/view?id=12", "https://example.org/p"], A.links_in(words))  # a Korean word or a bracket ends a link
        with __import__("tempfile").TemporaryDirectory() as d:
            A.claude_command(Api(), pathlib.Path(d), words)
            env = json.loads((pathlib.Path(d) / "mcp.json").read_text())["mcpServers"]["offerowl"]["env"]
        self.assertEqual(["https://example.org/p", "https://jobs.example.com/view?id=12"], json.loads(env["OFFEROWL_MCP_LINKS"]))
        with __import__("tempfile").TemporaryDirectory() as d:
            A.claude_command(Api(), pathlib.Path(d), "내 이력서 다듬어 줘")  # no link: the agent may fetch none
            env = json.loads((pathlib.Path(d) / "mcp.json").read_text())["mcpServers"]["offerowl"]["env"]
        self.assertEqual([], json.loads(env["OFFEROWL_MCP_LINKS"]))
        from unittest import mock  # Codex's command, with a stand-in for the installed CLI
        from src import llm
        with mock.patch.object(llm, "codex_cmd", return_value=["codex"]), __import__("tempfile").TemporaryDirectory() as d:
            cmd = A.codex_command(Api(), pathlib.Path(d), words)
        table = cmd[cmd.index("-c") + 1]  # mcp_servers={...}, a TOML inline table
        self.assertIn('OFFEROWL_MCP_LINKS="[\\"https://example.org/p\\", \\"https://jobs.example.com/view?id=12\\"]"', table)


class TestCounted(unittest.TestCase):
    """An ask the agent ran is one call on the agent's card, in the same log as every other call (sizes only, never the
    words), and a failed one is counted apart by its code. Claude Code's run is stood in for; nothing real is called."""

    def run_ask(self, stdout, code=0):  # one ask through ask.run with the CLI stood in; the lines it logged
        from types import SimpleNamespace  # a stand-in for the CLI's finished process
        from unittest import mock  # the stand-ins
        from src import llm  # where the call is run and logged
        logged, kept = [], []  # the log's lines, the history's records
        tasks = SimpleNamespace(backend=lambda: "claude-code", _set=lambda *a, **k: None)  # the panel's tasks, as far as run() uses them
        api = SimpleNamespace(port=8123, tasks=tasks)  # a panel on a port
        with mock.patch.object(llm, "_run", return_value=SimpleNamespace(stdout=stdout, stderr="", returncode=code)), \
                mock.patch.object(llm, "_log", side_effect=logged.append), mock.patch.object(A, "keep", side_effect=lambda _api, rec: kept.append(rec)):
            A.run(api, "Which applications are at the interview?")
        return logged, kept

    def test_an_answered_ask_is_one_call(self):
        out = "\n".join(json.dumps(x) for x in [{"type": "result", "result": "Two of them.", "is_error": False}])
        logged, kept = self.run_ask(out)
        self.assertEqual(1, len(logged))  # one line
        line = logged[0]
        self.assertEqual(("claude-code", "ask", 1), (line["backend"], line["task"], line["attempt"]))
        self.assertEqual(len("Which applications are at the interview?"), line["in_chars"])  # sizes, not the words
        self.assertNotIn("error", line)
        self.assertNotIn("Which", json.dumps(line))  # the ask's words never reach the log
        self.assertTrue(kept and kept[0]["ok"])

    def test_a_failed_ask_is_counted_apart(self):
        logged, kept = self.run_ask("", code=1)  # no answer
        self.assertEqual("ask_failed", logged[0]["error"])  # by its code
        self.assertFalse(kept[0]["ok"])


class TestRoute(PanelCase):
    def test_no_tool_agent_says_so(self):
        self.post("/api/v1/settings", {"backend": "none"})
        self.post("/api/v1/ask", {"text": "감마클라우드 통화 끝났어, 적어 줘"})
        end = time.time() + 20
        while time.time() < end and self.get("/api/v1/ask")["running"]:
            time.sleep(0.2)
        last = self.get("/api/v1/ask")["history"][-1]
        self.assertEqual("needs_tool_agent", last["answer"])   # said, not pretended
        self.assertEqual("감마클라우드 통화 끝났어, 적어 줘", last["text"])

    def test_empty_is_refused(self):
        self.post("/api/v1/ask", {"text": "   "}, expect=400)


if __name__ == "__main__":
    unittest.main()
