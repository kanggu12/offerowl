"""Tests of the settings in src/llm.py: OFFEROWL_ names, one backend at a time,
the default order, and each backend through a stand-in. No real model is called and nothing leaves this machine.

Run: python3 -m unittest discover -s tests/cli -v
"""
import http.server  # a local stand-in for an OpenAI-compatible server
import json  # requests and answers
import os  # environment and file modes
import pathlib  # paths
import subprocess  # the shape of a finished command
import sys  # module search path
import tempfile  # throwaway folders
import threading  # the stand-in server runs beside the test
import unittest  # the test framework
from unittest import mock  # patch the environment and the log path

from support import SRC

sys.path.insert(0, str(SRC))  # llm.py is a flat module in src/
import llm  # noqa: E402  the module under test

# Every setting the code reads, without its prefix.
SETTINGS = ["LLM", "LLM_MODEL", "LLM_URL", "LLM_KEY", "LLM_REASONING", "CODEX_CMD", "CODEX_PROFILE", "CODEX_OSS"]


def env(**values: str):
    """Replace the whole environment for the length of a `with` block, so nothing from the machine leaks in"""
    return mock.patch.dict(os.environ, values, clear=True)


def make_cli(folder: pathlib.Path, name: str, body: str) -> None:
    """Write an executable shell script. The scripts use only shell built-ins, so they run with a PATH that holds only their folder"""
    path = folder / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


# A stand-in for the claude CLI. `claude auth status --json` answers with AUTH (and exits with AUTH_RC); any other call is a
# question: it records its arguments and its standard input, then answers with a JSON object.
CLAUDE = """
if [ "$1" = "auth" ]; then
  echo '@AUTH@'
  exit @AUTH_RC@
fi
echo "$@" > "$STANDIN_ARGS"
while IFS= read -r line || [ -n "$line" ]; do echo "$line"; done > "$STANDIN_STDIN"
echo '{"ok": true}'
"""

# A stand-in for the codex CLI: it records its arguments, finds the file named after -o and writes its answer there.
CODEX = """
echo "$@" > "$STANDIN_ARGS"
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; fi
  shift
done
echo '{"ok": true}' > "$out"
"""


def claude_cli(folder: pathlib.Path, signed_in: bool | None = True) -> None:
    """Install the claude stand-in. signed_in None makes `auth status` fail, like an older CLI that has no such command"""
    if signed_in is None:
        body = CLAUDE.replace("@AUTH@", "").replace("@AUTH_RC@", "1")
    else:
        body = CLAUDE.replace("@AUTH@", '{"loggedIn": %s}' % ("true" if signed_in else "false")).replace("@AUTH_RC@", "0")
    make_cli(folder, "claude", body)


class WindowsCommandTest(unittest.TestCase):
    """How a CLI is started on Windows, tested anywhere: npm installs a .cmd file there, which only cmd.exe can start."""

    def test_a_cmd_file_goes_through_cmd_exe(self):
        with mock.patch.object(llm, "WINDOWS", True), mock.patch.object(llm.shutil, "which", lambda _: r"C:\npm\claude.CMD"):
            self.assertEqual(llm._argv(["claude", "-p"]), ["cmd", "/c", r"C:\npm\claude.CMD", "-p"])
            self.assertTrue(llm._is_shim("claude"))

    def test_an_exe_is_started_by_its_full_path(self):
        with mock.patch.object(llm, "WINDOWS", True), mock.patch.object(llm.shutil, "which", lambda _: r"C:\bin\claude.exe"):
            self.assertEqual(llm._argv(["claude", "-p"]), [r"C:\bin\claude.exe", "-p"])
            self.assertFalse(llm._is_shim("claude"))

    def test_elsewhere_the_command_stays_as_it_is(self):
        with mock.patch.object(llm, "WINDOWS", False):
            self.assertEqual(llm._argv(["claude", "-p"]), ["claude", "-p"])
            self.assertFalse(llm._is_shim("claude"))

    def test_the_instruction_goes_in_a_file_through_a_cmd_file(self):
        seen = {}  # what the CLI would be started with

        def fake_run(cmd, text_in, timeout, cwd=None):
            seen["cmd"] = cmd
            seen["instruction"] = pathlib.Path(cmd[cmd.index("--system-prompt-file") + 1]).read_text(encoding="utf-8")  # read while the file exists
            return subprocess.CompletedProcess(cmd, 0, "answer", "")
        with mock.patch.object(llm, "_is_shim", lambda _: True), mock.patch.object(llm, "_run", fake_run):
            self.assertEqual(llm._claude("q", 'say "a & b"', 10), "answer")
        self.assertEqual(seen["instruction"], 'say "a & b"')  # cmd.exe never sees these characters
        self.assertNotIn("--system-prompt", seen["cmd"])


class LocalServerProxyTest(unittest.TestCase):
    """A model server on this PC is asked directly: a web proxy set in the environment never receives the prompts."""

    def serve(self, answer: bytes) -> tuple[int, list]:
        """A server on a free port that answers every POST with `answer`; returns its port and the paths it was asked."""
        asked = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # the chat request, or a proxied one
                asked.append(self.path)  # what reached this server
                self.rfile.read(int(self.headers.get("Content-Length") or 0))  # the body, read so the client is not cut off
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(answer)

            def log_message(self, *a):  # quiet
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1], asked

    def test_a_local_server_is_not_reached_through_the_proxy(self):
        model, model_asked = self.serve(b'{"choices": [{"message": {"content": "ok"}}]}')  # the model on this PC
        proxy, proxy_asked = self.serve(b"{}")  # a web proxy that would see the prompt
        env = {"OFFEROWL_LLM_URL": f"http://127.0.0.1:{model}", "OFFEROWL_LLM_MODEL": "m", "OFFEROWL_LLM_REASONING": "",
               "http_proxy": f"http://127.0.0.1:{proxy}", "HTTP_PROXY": f"http://127.0.0.1:{proxy}", "no_proxy": "", "NO_PROXY": ""}
        with mock.patch.dict(os.environ, env):
            self.assertEqual("ok", llm._openai_compat("a sentence from a resume", None, 10))
        self.assertEqual(["/v1/chat/completions"], model_asked)  # asked directly
        self.assertEqual([], proxy_asked)  # the proxy saw nothing

    def test_which_addresses_count_as_local(self):
        for url in ("http://127.0.0.1:11434", "http://localhost:8000/v1", "http://[::1]:8080", "http://192.168.0.5:1234",
                    "http://10.1.2.3", "http://ollama.local:11434"):
            self.assertTrue(llm.is_local(url), url)  # this PC or its network
        for url in ("https://api.example.com/v1", "http://8.8.8.8"):
            self.assertFalse(llm.is_local(url), url)  # elsewhere: the proxy may be the way out


class CallLogTest(unittest.TestCase):
    def test_a_log_that_cannot_be_written_never_fails_the_call(self):
        with mock.patch.object(llm, "LOG", pathlib.Path("/dev/null/offerowl/calls.jsonl")):  # a folder that can never exist
            llm._log({"t": 0, "backend": "none", "task": "test", "sec": 0})  # skipped, not raised


class SettingNamesTest(unittest.TestCase):
    def test_a_setting_is_read_and_its_source_named(self):
        for name in SETTINGS:
            with env(**{"OFFEROWL_" + name: "value"}):
                self.assertEqual(llm.setting(name), "value", name)
                self.assertEqual(llm.setting_source(name), "OFFEROWL_" + name)

    def test_unset_gives_the_default(self):
        with env():
            self.assertEqual(llm.setting("LLM_MODEL", "fallback"), "fallback")
            self.assertEqual(llm.setting_source("LLM_MODEL"), "")

    def test_an_empty_setting_counts_as_set(self):
        with env(OFFEROWL_LLM=""):
            self.assertEqual(llm.setting("LLM", "fallback"), "")

    def test_language_setting(self):
        with env(OFFEROWL_LANG="ko"):
            self.assertEqual(llm.lang(), "ko")
        with env(OFFEROWL_LANG="ko", LANG="C.UTF-8"):  # the explicit setting beats the locale
            self.assertEqual(llm.lang(), "ko")
        with env(OFFEROWL_LANG="fr", LANG="ko_KR.UTF-8"):  # an unsupported value falls back to the locale
            self.assertEqual(llm.lang(), "ko")
        with env(LC_ALL="C", LANG="ko_KR.UTF-8"):  # POSIX: LC_ALL decides before LANG
            self.assertEqual(llm.lang(), "en")
        with env():
            self.assertEqual(llm.lang(), "en")


class DefaultOrderTest(unittest.TestCase):
    """Claude Code if it is installed and signed in, else Codex if it is installed, else none"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = pathlib.Path(self.tmp.name)  # the only folder on PATH, so the real machine's CLIs stay out of sight

    def test_nothing_installed_means_none(self):
        with env(PATH=str(self.bin)):
            self.assertEqual(llm.default_backend(), "none")
            self.assertEqual(llm.chosen(), ("none", "default"))

    def test_signed_in_claude_code_comes_first(self):
        claude_cli(self.bin, signed_in=True)
        make_cli(self.bin, "codex", "exit 0\n")  # Codex is there too, and still loses
        with env(PATH=str(self.bin)):
            self.assertEqual(llm.default_backend(), "claude-code")

    def test_signed_out_claude_code_gives_way_to_codex(self):
        claude_cli(self.bin, signed_in=False)
        make_cli(self.bin, "codex", "exit 0\n")
        with env(PATH=str(self.bin)):
            self.assertEqual(llm.default_backend(), "codex")

    def test_signed_out_claude_code_and_no_codex_means_none(self):
        claude_cli(self.bin, signed_in=False)
        with env(PATH=str(self.bin)):
            self.assertEqual(llm.default_backend(), "none")

    def test_an_unreadable_sign_in_state_still_counts_as_usable(self):
        # An older CLI without `auth status`: the sign-in state cannot be read, so the CLI counts as usable.
        claude_cli(self.bin, signed_in=None)
        with env(PATH=str(self.bin)):
            self.assertIsNone(llm.claude_signed_in())
            self.assertEqual(llm.default_backend(), "claude-code")

    def test_codex_alone(self):
        make_cli(self.bin, "codex", "exit 0\n")
        with env(PATH=str(self.bin)):
            self.assertEqual(llm.default_backend(), "codex")

    def test_codex_command_setting_counts_as_installed(self):
        # OFFEROWL_CODEX_CMD can start Codex through any program on PATH (npx in real life).
        make_cli(self.bin, "npx", "exit 0\n")
        with env(PATH=str(self.bin), OFFEROWL_CODEX_CMD="npx -y @openai/codex"):
            self.assertEqual(llm.codex_cmd(), ["npx", "-y", "@openai/codex"])
            self.assertEqual(llm.default_backend(), "codex")

    def test_the_setting_beats_the_default_order(self):
        claude_cli(self.bin, signed_in=True)
        with env(PATH=str(self.bin), OFFEROWL_LLM="none"):
            self.assertEqual(llm.chosen(), ("none", "OFFEROWL_LLM"))
        with env(PATH=str(self.bin), OFFEROWL_LLM="none"):  # the caller's argument beats the setting
            self.assertEqual(llm.chosen("codex"), ("codex", "argument"))


class ClaudeJsonResultTest(unittest.TestCase):
    """Claude Code answers with its JSON result: the text is the answer, and the tokens and the model go to the call log."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        log = mock.patch.object(llm, "LOG", pathlib.Path(self.tmp.name) / "calls.jsonl")  # tests must not write into the real output/
        log.start()
        self.addCleanup(log.stop)

    def result(self, payload: dict):
        """A _run stand-in that prints the CLI's result object."""
        return lambda cmd, text_in, timeout, cwd=None: subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    def test_the_answer_and_its_usage(self):
        payload = {"type": "result", "is_error": False, "result": " the answer ", "total_cost_usd": 0.02,
                   "usage": {"input_tokens": 2, "cache_read_input_tokens": 3396, "cache_creation_input_tokens": 10, "output_tokens": 4},
                   "modelUsage": {"claude-opus-5-5": {}}}  # the shape of a real result (claude -p --output-format json)
        with mock.patch.object(llm, "_is_shim", lambda _: False), mock.patch.object(llm, "_run", self.result(payload)):
            self.assertEqual("the answer", llm._claude("q", None, 10))  # the text alone
        self.assertEqual({"tok_in": 3408, "tok_out": 4, "model": "claude-opus-5-5", "cost": 0.02}, llm.USAGE.last)  # everything it read, what it wrote, its model

    def test_an_error_result_is_a_failed_call(self):
        payload = {"type": "result", "is_error": True, "result": "usage limit reached"}  # a limit, said in the result
        with mock.patch.object(llm, "_is_shim", lambda _: False), mock.patch.object(llm, "_run", self.result(payload)):
            with self.assertRaises(llm.CallFailed) as cm:
                llm._claude("q", None, 10)
        self.assertIn("usage limit reached", str(cm.exception))

    def test_verbose_settings_print_every_message_and_the_result_is_read(self):
        """With verbose on in the person's own Claude Code settings, --output-format json prints every message: the
        result is the last one, and its text is the answer."""
        msgs = [{"type": "system", "subtype": "init", "model": "claude-opus-5-5"},  # the session's start
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "the answer"}]}},  # the reply as a message
                {"type": "result", "is_error": False, "result": "the answer", "usage": {"input_tokens": 5, "output_tokens": 2},
                 "modelUsage": {"claude-opus-5-5": {}}}]  # and the result, last
        with mock.patch.object(llm, "_is_shim", lambda _: False), mock.patch.object(llm, "_run", self.result(msgs)):
            self.assertEqual("the answer", llm._claude("q", None, 10))  # the text alone, not the array
        self.assertEqual((5, 2), (llm.USAGE.last["tok_in"], llm.USAGE.last["tok_out"]))  # its usage is logged too

    def test_an_error_result_with_no_text_is_a_failed_call(self):
        payload = {"type": "result", "subtype": "error_during_execution", "is_error": True}  # a run that failed, with no result text
        with mock.patch.object(llm, "_is_shim", lambda _: False), mock.patch.object(llm, "_run", self.result(payload)):
            with self.assertRaises(llm.CallFailed) as cm:  # never passed on as the answer
                llm._claude("q", None, 10)
        self.assertIn("error_during_execution", str(cm.exception))

    def test_a_cli_that_prints_text_still_works(self):
        plain = lambda cmd, text_in, timeout, cwd=None: subprocess.CompletedProcess(cmd, 0, "plain words\n", "")  # noqa: E731  an older CLI
        with mock.patch.object(llm, "_is_shim", lambda _: False), mock.patch.object(llm, "_run", plain):
            self.assertEqual("plain words", llm._claude("q", None, 10))
        self.assertEqual({}, llm.USAGE.last)  # nothing to log beyond sizes


class OneBackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)
        log = mock.patch.object(llm, "LOG", self.dir / "calls.jsonl")  # tests must not write into the real output/
        log.start()
        self.addCleanup(log.stop)

    def test_none_never_calls_anything(self):
        with env(PATH=str(self.dir), OFFEROWL_LLM="none"):
            with self.assertRaises(llm.LLMUnavailable):
                llm.run("t", "prompt")

    def test_an_unknown_backend_name_is_an_error_that_lists_the_choices(self):
        with env(OFFEROWL_LLM="gpt-whatever"):
            with self.assertRaises(llm.LLMUnavailable) as cm:
                llm.run("t", "prompt")
        self.assertIn("claude-code, codex, openai-compat, none", str(cm.exception))

    def test_a_missing_backend_does_not_fall_through_to_another(self):
        # Codex is chosen but absent; a signed-in Claude stand-in is present and must not be used instead.
        claude_cli(self.dir, signed_in=True)
        with env(PATH=str(self.dir), OFFEROWL_LLM="codex", STANDIN_ARGS=str(self.dir / "args"), STANDIN_STDIN=str(self.dir / "stdin")):
            with self.assertRaises(llm.LLMUnavailable):
                llm.run("t", "prompt")
        self.assertFalse((self.dir / "args").exists(), "claude was called although codex was chosen")


class ClaudeStandInTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)
        claude_cli(self.dir, signed_in=True)
        log = mock.patch.object(llm, "LOG", self.dir / "calls.jsonl")
        log.start()
        self.addCleanup(log.stop)

    def test_the_prompt_goes_through_stdin_and_the_answer_comes_back_as_json(self):
        with env(PATH=str(self.dir), OFFEROWL_LLM="claude-code", STANDIN_ARGS=str(self.dir / "args"), STANDIN_STDIN=str(self.dir / "stdin")):
            answer = llm.run("probe", "first line\nsecond line", system="be brief", want_json=True, required=("ok",))
        self.assertEqual(answer, {"ok": True})
        self.assertEqual((self.dir / "stdin").read_text(encoding="utf-8"), "first line\nsecond line\n")
        args = (self.dir / "args").read_text(encoding="utf-8")
        self.assertIn("-p", args)
        self.assertIn("--system-prompt be brief", args)

    def test_the_call_log_holds_sizes_and_no_text(self):
        with env(PATH=str(self.dir), OFFEROWL_LLM="claude-code", STANDIN_ARGS=str(self.dir / "args"), STANDIN_STDIN=str(self.dir / "stdin")):
            llm.run("probe", "a secret sentence", want_json=True, required=("ok",))
        text = (self.dir / "calls.jsonl").read_text(encoding="utf-8")
        record = json.loads(text.splitlines()[-1])
        self.assertEqual(record["backend"], "claude-code")
        self.assertEqual(record["task"], "probe")
        self.assertEqual(record["in_chars"], len("a secret sentence"))
        self.assertNotIn("secret", text)  # the prompt text is never logged

    def test_a_failed_call_is_asked_once_more(self):
        # the CLI fails once with its reason on stdout, as an overloaded service does, then answers
        make_cli(self.dir, "claude", 'if [ ! -f "$STANDIN_ARGS.failed" ]; then : > "$STANDIN_ARGS.failed"; echo "API Error: 529 overloaded"; exit 1; fi\n' + CLAUDE.replace("@AUTH@", "{}").replace("@AUTH_RC@", "0"))
        with env(PATH=str(self.dir), OFFEROWL_LLM="claude-code", STANDIN_ARGS=str(self.dir / "args"), STANDIN_STDIN=str(self.dir / "stdin")), \
                mock.patch.object(llm, "RETRY_PAUSE", 0):  # no wait in a test
            answer = llm.run("probe", "q", want_json=True, required=("ok",))
        self.assertEqual(answer, {"ok": True})  # the second ask answered

    def test_a_call_that_keeps_failing_says_why(self):
        make_cli(self.dir, "claude", 'echo "API Error: 529 overloaded"\nexit 1\n')  # fails every time, its reason on stdout
        with env(PATH=str(self.dir), OFFEROWL_LLM="claude-code"), mock.patch.object(llm, "RETRY_PAUSE", 0):
            with self.assertRaises(llm.LLMUnavailable) as cm:
                llm.run("probe", "q", want_json=True, required=("ok",))
        self.assertIn("529 overloaded", str(cm.exception))  # the reason reaches the person, not an empty message

    def test_a_missing_key_is_asked_again_once_and_then_given_up(self):
        with env(PATH=str(self.dir), OFFEROWL_LLM="claude-code", STANDIN_ARGS=str(self.dir / "args"), STANDIN_STDIN=str(self.dir / "stdin")):
            with self.assertRaises(ValueError):
                llm.run("probe", "q", want_json=True, required=("absent_key",), retries=1)
        self.assertEqual(len((self.dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()), 2)  # asked twice


class CodexStandInTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)
        make_cli(self.dir, "codex", CODEX)
        log = mock.patch.object(llm, "LOG", self.dir / "calls.jsonl")
        log.start()
        self.addCleanup(log.stop)

    def ask(self, **settings: str) -> str:
        """Run one codex question with the given settings and return the arguments the stand-in saw"""
        with env(PATH=str(self.dir), STANDIN_ARGS=str(self.dir / "args"), **settings):
            self.assertEqual(llm.run("t", "q", want_json=True, required=("ok",), backend="codex"), {"ok": True})
        return (self.dir / "args").read_text(encoding="utf-8")

    def test_the_model_setting_reaches_codex(self):
        self.assertIn("-m new-model", self.ask(OFFEROWL_LLM_MODEL="new-model"))
        self.assertNotIn("-m ", self.ask())  # no setting, no flag

    def test_profile_and_local_provider_settings(self):
        args = self.ask(OFFEROWL_CODEX_PROFILE="work", OFFEROWL_CODEX_OSS="ollama")
        self.assertIn("-p work", args)
        self.assertIn("--oss --local-provider ollama", args)

    def test_codex_runs_read_only_and_leaves_no_session(self):
        args = self.ask()
        for flag in ("exec", "--skip-git-repo-check", "--ephemeral", "-s read-only"):
            self.assertIn(flag, args)

    def test_the_start_command_setting_is_split_like_a_shell_would(self):
        make_cli(self.dir, "mycodex", CODEX)
        args = self.ask(OFFEROWL_CODEX_CMD="mycodex --extra 'two words'")
        self.assertTrue(args.startswith("--extra two words exec"), args)


class OpenAiCompatibleTest(unittest.TestCase):
    """The request that goes to an OpenAI-compatible server, against a stand-in on 127.0.0.1"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        log = mock.patch.object(llm, "LOG", pathlib.Path(self.tmp.name) / "calls.jsonl")
        log.start()
        self.addCleanup(log.stop)
        self.requests = []  # what the stand-in received
        self.reject_reasoning = False  # answer 400 to requests that carry reasoning_effort, like a server that does not know it
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # the only method the client uses
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                if outer.reject_reasoning and "reasoning_effort" in body:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error": "unknown field"}')
                    return
                data = json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # keep the test output clean
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def ask(self, **settings: str) -> dict:
        """One question through the stand-in; returns the request body the stand-in saw"""
        with env(**settings):
            self.assertEqual(llm.run("t", "q", system="s", want_json=True, required=("ok",), backend="openai-compat"), {"ok": True})
        return self.requests[-1]["body"]

    def test_url_and_model_settings(self):
        body = self.ask(OFFEROWL_LLM_URL=self.url, OFFEROWL_LLM_MODEL="new-model")
        self.assertEqual(self.requests[-1]["path"], "/v1/chat/completions")
        self.assertEqual(body["model"], "new-model")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "s"})
        self.assertEqual(body["response_format"], {"type": "json_object"})  # JSON mode is on for JSON questions
        self.assertEqual(body["temperature"], 0)

    def test_the_address_may_omit_the_scheme_or_end_in_v1(self):
        host = self.url.split("//")[1]
        self.ask(OFFEROWL_LLM_URL=host)  # no scheme
        self.ask(OFFEROWL_LLM_URL=self.url + "/v1/")  # the OpenAI SDK way
        self.assertEqual([r["path"] for r in self.requests], ["/v1/chat/completions"] * 2)

    def test_reasoning_effort_defaults_to_none_and_can_be_changed_or_dropped(self):
        self.assertEqual(self.ask(OFFEROWL_LLM_URL=self.url)["reasoning_effort"], "none")
        self.assertEqual(self.ask(OFFEROWL_LLM_URL=self.url, OFFEROWL_LLM_REASONING="low")["reasoning_effort"], "low")
        self.assertNotIn("reasoning_effort", self.ask(OFFEROWL_LLM_URL=self.url, OFFEROWL_LLM_REASONING=""))

    def test_a_server_that_rejects_reasoning_effort_is_asked_again_without_it(self):
        self.reject_reasoning = True
        body = self.ask(OFFEROWL_LLM_URL=self.url)
        self.assertEqual(len(self.requests), 2)  # the refused one and the accepted one
        self.assertIn("reasoning_effort", self.requests[0]["body"])
        self.assertNotIn("reasoning_effort", body)

    def test_the_key_is_sent_only_when_set(self):
        self.ask(OFFEROWL_LLM_URL=self.url)
        self.assertIsNone(self.requests[-1]["auth"])
        self.ask(OFFEROWL_LLM_URL=self.url, OFFEROWL_LLM_KEY="test-key-not-real")
        self.assertEqual(self.requests[-1]["auth"], "Bearer test-key-not-real")

    def test_no_url_means_unavailable(self):
        with env():
            with self.assertRaises(llm.LLMUnavailable):
                llm.run("t", "q", backend="openai-compat")


if __name__ == "__main__":
    unittest.main()
