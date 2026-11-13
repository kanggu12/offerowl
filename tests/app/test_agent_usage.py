#!/usr/bin/env python3
"""The agent card's figures from Offerowl's own call log (a made-up one), and the line Offerowl keeps: it never opens a CLI's
login files and never reads a token, so the card has no meters of the plan's limits (Anthropic's terms for third-party
tools: docs/README.md, the privacy part). No real account or log of this PC is read."""
import json  # the log
import os  # the environment the CLI run looks at
import pathlib  # paths
import re  # the source's words
import shutil  # temporary folders
import subprocess  # the CLI's answer, made up
import sys  # the import path
import tempfile  # a log per test
import time  # the log's day
import unittest  # the runner
from unittest import mock  # the CLI's run

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "src"))  # so is llm.py
from apps.api import agent as agentmod  # noqa: E402  the card
import llm  # noqa: E402  the call log


class NoLoginTests(unittest.TestCase):
    """The card reads what the CLIs say about themselves, and nothing of their logins."""

    def test_the_card_never_reads_a_login_file_or_a_token(self):
        src = (ROOT / "apps" / "api" / "agent.py").read_text(encoding="utf-8")  # the card's code
        for word in (".credentials.json", "accessToken", "oauth/usage", "claudeAiOauth", "auth.json"):  # what reading a login would take
            self.assertNotIn(word, src, word)
        self.assertFalse(hasattr(agentmod, "read_plan_usage"))  # no reader of the plan's meters

    def test_the_card_has_no_meters(self):
        with mock.patch.object(agentmod, "claude_status", return_value={"state": "ready", "email": "a@example.com", "plan": "Max", "method": "claude.ai"}):
            card = agentmod.AgentCard(lambda: {"backend": "claude-code"})  # the card as the panel makes it
            got = card.card()
        self.assertNotIn("usage", got)  # what is shown is what the CLI says


class CallsTests(unittest.TestCase):
    """calls_summary over a made-up log, and what src/llm.py writes into it."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-calls-"))  # a log of its own
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old = llm.LOG  # put back at the end
        llm.LOG = self.tmp / "calls.jsonl"
        self.addCleanup(setattr, llm, "LOG", self.old)

    def write(self, rows):
        llm.LOG.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")  # one object per line

    def test_the_figures(self):
        now = int(time.time())  # this day
        self.write([{"t": now - 90000, "backend": "claude-code", "task": "x", "sec": 99.0},  # yesterday: not counted
                    {"t": now, "backend": "claude-code", "task": "x", "sec": 4.0, "ttft": 1.0, "tok_in": 100, "tok_out": 300, "cost": 0.01, "model": "m-1", "effort": "high"},
                    {"t": now, "backend": "claude-code", "task": "x", "sec": 2.0, "tok_in": 50, "tok_out": 100, "cost": 0.0025, "model": "m-2"},  # an older CLI: no ttft
                    {"t": now + 1, "backend": "claude-code", "task": "x", "sec": 0.5, "attempt": 0, "error": "exit 1"},
                    {"t": now + 2, "backend": "claude-code", "task": "x", "sec": 30.0, "attempt": 0, "error": "timeout"},
                    {"t": now, "backend": "openai-compat", "task": "x", "sec": 7.0}])  # another agent's
        s = agentmod.calls_summary(backend="claude-code")
        self.assertEqual({"calls": 2, "median": 4.0, "tok_in": 150, "tok_out": 400, "model": "m-2", "recent": [4.0, 2.0]},
                         {k: s[k] for k in ("calls", "median", "tok_in", "tok_out", "model", "recent")})  # the old keys, answered calls only
        self.assertEqual("high", s["effort"])  # the last effort named
        self.assertEqual(1.0, s["ttft_avg"])  # over the calls that said it
        self.assertEqual(75.0, s["tps_avg"])  # (300 / 3 s + 100 / 2 s) / 2
        self.assertEqual(0.0125, s["cost"])
        self.assertEqual(2, s["errors"])
        self.assertEqual({"code": "timeout", "t": now + 2}, s["last_error"])  # the latest
        self.assertEqual([{"sec": 4.0, "ttft": 1.0}, {"sec": 2.0}], s["bars"])  # split where known

    def test_an_empty_log(self):
        s = agentmod.calls_summary(backend="claude-code")  # no log yet
        self.assertEqual((0, None, None, None, None, 0, None, [], ""), (s["calls"], s["median"], s["ttft_avg"], s["tps_avg"], s["cost"], s["errors"], s["last_error"], s["bars"], s["effort"]))

    def answer(self, stdout, code=0):
        """The CLI's run, made up: what `claude -p --output-format json` printed."""
        return mock.patch.object(llm, "_run", return_value=subprocess.CompletedProcess(["claude"], code, stdout, ""))

    def ready(self):
        """Claude Code chosen and usable, with no wait between two tries."""
        for p in (mock.patch.object(llm, "chosen", return_value=("claude-code", "test")), mock.patch.object(llm, "available", return_value={"claude-code": (True, "")}),
                  mock.patch.object(llm, "RETRY_PAUSE", 0), mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp), "CLAUDE_CODE_EFFORT_LEVEL": ""})):
            p.start()
            self.addCleanup(p.stop)

    def rows(self):
        return [json.loads(x) for x in llm.LOG.read_text(encoding="utf-8").splitlines()]  # what the log holds

    def test_llm_logs_the_first_token_the_cost_and_the_effort(self):
        self.ready()
        (self.tmp / "settings.json").write_text(json.dumps({"effortLevel": "medium", "env": {"ANTHROPIC_API_KEY": "sk-fake"}}), encoding="utf-8")  # the CLI's own file, never opened
        os.environ["CLAUDE_CODE_EFFORT_LEVEL"] = "medium"  # the effort the person set for the CLI
        result = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 3000, "ttft_ms": 1250, "result": "hello",
                  "total_cost_usd": 0.02, "usage": {"input_tokens": 10, "output_tokens": 20}, "modelUsage": {"m-1": {}}}  # the result's own keys
        with self.answer(json.dumps(result)):
            self.assertEqual("hello", llm.run("x", "a prompt"))
        row = self.rows()[-1]
        self.assertEqual((1.25, 0.02, "medium", "m-1", 20), (row["ttft"], row["cost"], row["effort"], row["model"], row["tok_out"]))
        os.environ["CLAUDE_CODE_EFFORT_LEVEL"] = "low"  # the environment wins, as in the CLI
        with self.answer(json.dumps({**result, "ttft_ms": None})):  # a CLI that does not say its first token
            llm.run("x", "a prompt")
        row = self.rows()[-1]
        self.assertEqual("low", row["effort"])
        self.assertNotIn("ttft", row)  # total only

    def test_the_clis_settings_file_is_never_opened(self):
        # Claude Code's settings file can hold keys (env, apiKeyHelper): an effort set only there is not read
        self.ready()
        (self.tmp / "settings.json").write_text(json.dumps({"effortLevel": "high"}), encoding="utf-8")
        opened = []
        real = pathlib.Path.read_text

        def watch(path, *a, **k):  # every file read during the call
            opened.append(str(path))
            return real(path, *a, **k)

        result = {"type": "result", "subtype": "success", "is_error": False, "result": "hello", "usage": {}, "modelUsage": {}}
        with self.answer(json.dumps(result)), mock.patch.object(pathlib.Path, "read_text", watch):
            llm.run("x", "a prompt")
        self.assertNotIn(str(self.tmp / "settings.json"), opened)
        self.assertNotIn("effort", self.rows()[-1])  # none named

    def test_llm_logs_failures_by_code_only(self):
        self.ready()
        with self.answer("Error: secret words from the CLI", code=1), self.assertRaises(llm.CallFailed):
            llm.run("x", "a prompt")  # fails, is asked again, fails again
        rows = self.rows()
        self.assertEqual(["exit 1", "exit 1"], [r["error"] for r in rows])  # both tries counted
        self.assertNotIn("secret", llm.LOG.read_text(encoding="utf-8"))  # the CLI's words stay out of the log
        refused = {"type": "result", "subtype": "success", "is_error": True, "result": "limit reached", "usage": {}}  # a limit: is_error on a success
        with self.answer(json.dumps(refused)), self.assertRaises(llm.CallFailed):
            llm.run("x", "a prompt")
        self.assertEqual("is_error", self.rows()[-1]["error"])
        s = agentmod.calls_summary(backend="claude-code")
        self.assertEqual((0, 4, "is_error"), (s["calls"], s["errors"], s["last_error"]["code"]))  # no answered call, four failed tries


if __name__ == "__main__":
    unittest.main()
