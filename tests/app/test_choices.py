#!/usr/bin/env python3
"""What the panel may send and overwrite: the backend named when starting, adding a job, making PDFs, a redirect and the deck in the question map."""
import http.server  # a page that redirects
import importlib.util  # the desktop app's module, by its file
import os  # the environment Tasks.backend writes
import pathlib  # paths
import shutil  # temporary folders
import sys  # the import path
import tempfile  # a data folder per test
import threading  # the page in the background
import time  # a shell's time limit
import unittest
import urllib.parse  # a job's id in an address  # the runner
from unittest import mock  # stand-ins for the CLIs and the steps of the letter

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "src"))  # so is cover.py
from apps.api import agent as agentmod  # noqa: E402  the sign-in states
from apps.api import app as appmod  # noqa: E402  the settings
from apps.api import postings  # noqa: E402  the link fetch
from apps.api.workspace import read_json, write_json  # noqa: E402  the files of a job
import cover as covermod  # noqa: E402  the letter's steps

LOCAL = {"backend": "openai-compat", "llm_url": "http://127.0.0.1:9", "llm_model": "small"}  # a local model named when starting
INSTALLED = {"installed": True, "signed_in": True}  # an agent found on this PC


class Base(unittest.TestCase):
    """One data folder per test, with Claude Code found on this PC and nothing real called."""

    def make(self, start=None, saved=None):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-choice-"))  # the data folder
        self.addCleanup(shutil.rmtree, self.tmp, True)  # gone afterwards
        if saved:  # an earlier run's settings
            write_json(self.tmp / "settings.json", saved)
        for p in (mock.patch.object(appmod, "START", start or {}), mock.patch.object(agentmod, "claude_status", return_value=INSTALLED),  # the patches the whole test needs
                  mock.patch.object(agentmod, "codex_status", return_value={"installed": False}), mock.patch.object(agentmod, "local_status", return_value={"installed": False}),
                  mock.patch.dict(os.environ, {})):  # Tasks.backend writes the environment, which goes back afterwards
            p.start()
            self.addCleanup(p.stop)
        for k in ("OFFEROWL_PANEL_AGENT", "OFFEROWL_PANEL_BACKEND", "OFFEROWL_LLM_URL", "OFFEROWL_LLM_MODEL"):  # a class run earlier must not count (the stand-in leaves its address and name)
            os.environ.pop(k, None)
        api = appmod.Api(self.tmp)  # the object the routes call
        self.addCleanup(self.settle)  # runs before the folder goes (cleanups run last first): no late write makes it again
        api.card.refresh(force=True)  # looked up now, so the test does not race the first look
        return api

    @staticmethod
    def settle(limit: float = 10.0) -> None:
        """Wait for what an API started in the background (its tasks, its first look at the agent, the letters' pages) to end,
        so the test's folder is removed after its last write: a reading that ended after the removal made the folder again and
        left it in the system's temporary folder."""
        end = time.time() + limit  # a stuck thread never holds the run
        while time.time() < end:
            if not [t for t in threading.enumerate() if t.name in ("agent", "letters") or t.name.startswith("task-")]:  # all done
                return
            time.sleep(0.05)


class EngineReadyTests(Base):
    """Can the typesetting run here, as Make and the setup guide say it: on Windows Docker does not count."""

    @unittest.skipUnless((ROOT / "node_modules" / "docx").is_dir(), "the typesetting libraries are not installed (npm ci)")
    def test_on_windows_the_browser_typesets_even_with_docker(self):
        # render/run.sh starts the container, and Windows cannot run a shell script: a PC with Docker Desktop was told the
        # typesetting was ready, and every build stopped with OSError
        a = self.make()
        import resume  # src/resume.py: the renderer's own report
        with mock.patch.object(sys, "platform", "win32"), mock.patch("shutil.which", return_value="C:/Program Files/Docker/docker.exe"), \
                mock.patch.dict(os.environ, {}):
            with mock.patch.object(resume, "renderers", return_value={"html": {"ok": True}}):
                self.assertEqual("", a.tasks.engine_ready())  # ready, through the browser
                self.assertEqual("html", os.environ.get("OFFEROWL_RENDERER"))  # and the builds use it
            with mock.patch.object(resume, "renderers", return_value={"html": {"ok": False, "needs": ["node"]}}):
                self.assertEqual("browser_missing", a.tasks.engine_ready())  # not "get Docker": Docker cannot help there
                self.assertEqual(["node"], a.tasks.engine_needs)  # and the page names what the browser lacks
                self.assertEqual(["node"], a.state()["engine_needs"])
                self.assertEqual("html", a.state()["renderer"])  # and the guide says the browser makes them, not Docker

    def test_on_windows_the_install_starts_npm_by_its_path_and_never_run_sh(self):
        # npm is npm.cmd on Windows: a command list without a shell never finds "npm", and run.sh (a shell script) cannot start
        a = self.make()
        seen = []

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return mock.Mock(returncode=0, stdout="", stderr="")
        which = {"npm": "C:/Program Files/nodejs/npm.cmd", "docker": "C:/Program Files/Docker/docker.exe"}
        with mock.patch.object(sys, "platform", "win32"), mock.patch("shutil.which", side_effect=lambda n: which.get(n)), \
                mock.patch("subprocess.run", side_effect=fake_run):
            a.tasks._setup()
        self.assertEqual([["C:/Program Files/nodejs/npm.cmd", "ci"]], seen)  # by its path, with Docker there too
        seen.clear()
        with mock.patch.object(sys, "platform", "win32"), mock.patch("shutil.which", return_value=None), mock.patch("subprocess.run", side_effect=fake_run):
            a.tasks._setup()
        self.assertEqual([], seen)  # nothing to start
        self.assertEqual({"code": "setup_failed", "detail": "npm"}, a.tasks.state()["setup"]["error"])  # said, with its retry


class MoveTests(unittest.TestCase):
    """A state file written while the page reads it: on Windows the file being open refuses the swap for a moment, and the
    write waits for the reader instead of failing its task (a reading of the example stopped with "Access is denied")."""

    def test_on_windows_a_move_refused_for_a_moment_is_tried_again(self):
        from apps.api import workspace as W  # where every state file is written
        with tempfile.TemporaryDirectory() as d:
            target, real, tries = pathlib.Path(d) / "state.json", os.replace, []

            def held_twice(a, b):  # the page's read holds the file for the first two tries
                tries.append(b)
                if len(tries) <= 2:
                    raise PermissionError(13, "Access is denied")
                return real(a, b)
            with mock.patch.object(W.sys, "platform", "win32"), mock.patch.object(W.os, "replace", held_twice), mock.patch.object(W.time, "sleep"):
                write_json(target, {"kept": 1})  # does not raise
            self.assertEqual({"kept": 1}, read_json(target, None))  # the new content is there
            self.assertEqual(3, len(tries))  # after two refusals

    def test_elsewhere_a_refusal_stands_at_once(self):
        from apps.api import workspace as W
        with tempfile.TemporaryDirectory() as d:
            tries = []

            def refused(a, b):  # a folder the person may not write
                tries.append(b)
                raise PermissionError(13, "Permission denied")
            with mock.patch.object(W.sys, "platform", "linux"), mock.patch.object(W.os, "replace", refused):
                with self.assertRaises(PermissionError):
                    write_json(pathlib.Path(d) / "state.json", {})
            self.assertEqual(1, len(tries))  # no waiting where an open file never stops a move


class StateOrderTests(Base):
    """One answer of /api/v1/state never says a task has ended while it shows what was there before the task ran."""

    def test_an_analysis_that_ends_while_the_state_is_read_is_not_ended_with_its_old_plan(self):
        # macOS CI, once: the poll read the job's plan (the words'), the agent's analysis wrote its own and ended, then the
        # poll read the tasks: "done" beside the old plan, and the test of the analysis saw "words"
        import draft  # src/draft.py: the agent's analysis
        a = self.make()
        os.environ["OFFEROWL_PANEL_AGENT"] = "standin"  # the agent answers: the stand-in
        a.add_example("ko")  # the fictional person
        for _ in range(400):  # read
            if (a.tasks.state().get("ingest") or {}).get("state") not in (None, "running"):
                break
            time.sleep(0.05)
        a.keep_all()  # its facts kept
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})
        key = f"analyze:{jid}"  # the analysis' task
        self.assertTrue(a.tasks.analyze(jid, agent=False))  # first by words, as adding a job does
        for _ in range(400):
            if a.tasks.state()[key]["state"] == "done":
                break
            time.sleep(0.05)
        read, real_jobs, real_jd = threading.Event(), a.jobs_view, draft.task_jd

        def jobs_then_the_end():  # the plans as they are, and then the agent's analysis ends before the rest is read
            out = real_jobs()
            read.set()  # the analysis may answer now
            for _ in range(500):  # and it ends
                if a.tasks.state()[key]["state"] == "done":
                    break
                time.sleep(0.01)
            return out

        def jd_after_the_read(prof, posting):  # the agent answers once the plans were read
            read.wait(10)
            return real_jd(prof, posting)
        with mock.patch.object(a, "jobs_view", jobs_then_the_end), mock.patch.object(draft, "task_jd", jd_after_the_read):
            self.assertTrue(a.tasks.analyze(jid))  # the agent's turn
            st = a.state()  # read while it ends
        seen = (st["tasks"][key]["state"], next(j for j in st["jobs"] if j["id"] == jid)["plan"]["by"])
        self.assertIn(seen, [("running", "words"), ("done", "agent")])  # never "done" beside the words' plan
        for _ in range(400):  # the end
            if a.tasks.state()[key]["state"] == "done":
                break
            time.sleep(0.05)
        st = a.state()
        self.assertEqual(("done", "agent"), (st["tasks"][key]["state"], next(j for j in st["jobs"] if j["id"] == jid)["plan"]["by"]))


class StartChoiceTests(Base):
    """A local model named when starting is what gets used, even with an agent on the PC."""

    def test_the_named_backend_wins_over_the_agent_found(self):
        a = self.make(LOCAL)  # Claude Code is installed too
        self.assertEqual("openai-compat", a.card.chosen())  # never replaced
        self.assertEqual("openai-compat", a.tasks.backend())  # the name llm.py gets
        self.assertEqual(LOCAL["llm_url"], os.environ["OFFEROWL_LLM_URL"])  # the address is kept, not blanked
        self.assertEqual("small", os.environ["OFFEROWL_LLM_MODEL"])  # and the model

    def test_it_wins_over_a_saved_choice(self):
        a = self.make(LOCAL, saved={"backend": "auto"})  # saved before the person named a local model
        self.assertEqual("openai-compat", a.card.chosen())  # the name given at this start

    def test_the_switch_brings_it_back(self):
        a = self.make(LOCAL)  # a local model
        a.set_settings({"agent": "off"})  # off
        self.assertEqual("none", a.card.chosen())  # nothing is called
        a.set_settings({"agent": "off"})  # off again must not forget it
        a.set_settings({"agent": "on"})  # on
        self.assertEqual("openai-compat", a.card.chosen())  # the local model, not the agent found

    def test_a_choice_in_the_menu_wins_afterwards(self):
        a = self.make(LOCAL)  # a local model
        a.set_settings({"backend": "claude-code"})  # the person changed it
        self.assertEqual("claude-code", a.card.chosen())  # as chosen
        a.set_settings({"llm_url": "http://127.0.0.1:10"})  # and the address
        self.assertEqual("http://127.0.0.1:10", a.settings()["llm_url"])  # as typed

    def test_a_new_address_is_looked_at_again(self):
        a = self.make({"backend": "openai-compat"})  # a local model with no address yet
        self.assertEqual("missing", a.card.card()["state"])  # no address: the card says so
        with mock.patch.object(agentmod, "local_status", return_value={"installed": True, "signed_in": False}):  # an address where nothing answers
            a.set_settings({"llm_url": "http://127.0.0.1:9"})  # typed in the menu or the setup guide
            a.card.refresh()  # the next look, not forced: due because the address changed
            self.assertEqual("signed_out", a.card.card()["state"])  # said now, not after the minute between two looks

    def test_a_change_during_a_look_is_looked_at_next(self):
        a = self.make({"backend": "openai-compat"})  # a local model with no address yet
        started, release = threading.Event(), threading.Event()  # a look that has read the settings, and the end of its wait

        def slow(url, model):  # the local server asked with the settings read when the look began
            started.set()
            release.wait(5)
            return {"installed": bool(url), "signed_in": False}  # set and answering nothing, or not set

        with mock.patch.object(agentmod, "local_status", side_effect=slow):
            look = threading.Thread(target=a.card.refresh, kwargs={"force": True})  # a look already running
            look.start()
            self.assertTrue(started.wait(5))  # it has read the settings: no address
            a.set_settings({"llm_url": "http://127.0.0.1:9"})  # typed while it runs
            release.set()
            look.join(5)
            self.assertEqual(0.0, a.card.at)  # still due: the look that ended read the old address
            a.card.refresh()  # the next look, not forced
            self.assertEqual("signed_out", a.card.card()["state"])  # the new address, said now

    def test_the_first_look_reads_checking_not_off(self):
        self.make()  # the patches and a clean environment
        card = agentmod.AgentCard(lambda: {"backend": "auto"})  # before its first look
        with card.lock:  # no look starts behind this answer
            self.assertEqual("checking", card.card()["state"])  # nothing found yet is not known, which is not off
        off = agentmod.AgentCard(lambda: {"backend": "none"})  # switched off
        with off.lock:
            self.assertEqual("off", off.card()["state"])  # known without a look

    def test_no_agent_from_the_list_is_remembered_by_the_switch(self):
        a = self.make(LOCAL)  # a local model
        a.set_settings({"backend": "none"})  # "No agent" picked from the list
        a.set_settings({"agent": "on"})  # the setup guide's "Turn it on", or the switch
        self.assertEqual("openai-compat", a.card.chosen())  # the agent just used, not whatever "auto" finds

    def test_a_local_model_s_name_is_not_handed_to_codex(self):
        a = self.make(LOCAL)  # a local model in use
        self.assertEqual("openai-compat", a.tasks.backend())  # its address and name are set for llm.py
        self.assertEqual("small", os.environ.get("OFFEROWL_LLM_MODEL"))
        a.set_settings({"backend": "codex"})  # then Codex is chosen
        self.assertEqual("codex", a.tasks.backend())
        self.assertIsNone(os.environ.get("OFFEROWL_LLM_MODEL"))  # codex gets no -m of the local model's
        self.assertIsNone(os.environ.get("OFFEROWL_LLM_URL"))  # nor its address

    def test_a_signed_out_claude_code_gives_way_to_codex(self):
        a = self.make()  # nothing named
        with mock.patch.object(agentmod, "claude_status", return_value={"installed": True, "signed_in": False}), \
                mock.patch.object(agentmod, "codex_status", return_value={"installed": True, "signed_in": True}):
            a.card.refresh(force=True)  # looked at again with these two
            self.assertEqual("codex", a.card.chosen())  # as llm.py's own default order picks: the tasks would fail on the signed-out one
        with mock.patch.object(agentmod, "claude_status", return_value={"installed": True, "signed_in": False}):
            a.card.refresh(force=True)  # no Codex this time
            self.assertEqual("claude-code", a.card.chosen())  # the card offers its sign-in

    def test_with_nothing_named_it_looks_for_an_agent(self):
        a = self.make()  # nothing named
        self.assertEqual("claude-code", a.card.chosen())  # the agent found
        a.set_settings({"agent": "off"})  # off
        self.assertEqual("none", a.card.chosen())  # off
        a.set_settings({"agent": "on"})  # on
        self.assertEqual("claude-code", a.card.chosen())  # found again

    def test_an_unknown_name_is_ignored(self):
        a = self.make({"backend": "gpt-whatever"})  # not a backend
        self.assertEqual("claude-code", a.card.chosen())  # as if unset


class CoverStepTests(Base):
    """Making PDFs typesets the letter that is there; only tailoring asks for a new one."""

    def letter(self, a, backend="claude-code", written=True):
        """A job's edition folder, with a reviewed letter when written, and the steps stood in for."""
        out = a.tasks.build_dir("job", "ko")  # the edition
        (out / "cover").mkdir(parents=True)  # the letter's folder
        write_json(out / "job.json", {"theme": "navy"})  # the edition's theme
        (a.ws.job_dir("job")).mkdir(parents=True, exist_ok=True)  # the job
        if written:  # a letter the person reviewed
            write_json(out / "cover" / "cover.json", {"reviewed": True, "paragraphs": [{"sentences": [{"text": "Old words."}]}]})
        self.steps, self.stop = [], False  # what ran; whether the agent stops in the draft

        def main(argv):  # cover.py's entry: writes what each step writes, where its arguments say
            self.steps.append(argv[0])  # in order
            target = pathlib.Path(argv[argv.index("-o") + 1]) if "-o" in argv else None  # the file a plan or a draft writes
            if argv[0] == "plan":  # the posting's duties
                write_json(target, {"plan": True})
            if argv[0] == "draft":  # a new letter, or the empty skeleton an agent that stopped leaves
                write_json(target, {"reviewed": False, "paragraphs": [] if self.stop else [{"sentences": [{"text": "New words."}]}]})
                return 2 if self.stop else 0  # the model stopped, or answered
            if argv[0] == "build":  # typeset beside the letter it was given
                d = pathlib.Path(argv[2]).parent  # the letter's folder
                (d / "cover.pdf").write_bytes(b"%PDF")
                (d / "cover.docx").write_bytes(b"PK")
            return 0  # passed

        for p in (mock.patch.object(covermod, "main", main), mock.patch.object(a.tasks, "backend", return_value=backend), mock.patch.object(a.tasks, "engine_ready", return_value=""),
                  mock.patch.object(a.tasks, "_previews", return_value=1), mock.patch.object(a.card, "chosen", return_value=backend)):  # no model and no typesetting really run
            p.start()
            self.addCleanup(p.stop)
        return out

    def test_making_pdfs_keeps_a_reviewed_letter(self):
        a = self.make()  # the agent is on
        out = self.letter(a)  # a reviewed letter
        got = a.tasks._cover("job", "ko", out, write=False)  # as Make PDFs calls it
        self.assertEqual(["build", "check"], self.steps)  # the agent was not asked
        self.assertTrue(read_json(out / "cover" / "cover.json", {})["reviewed"])  # the letter is the same one
        self.assertEqual("done", got["state"])  # and it has its PDF
        self.assertTrue((out / "cover.pdf").is_file() and (out / "cover.docx").is_file())  # both beside the resume

    def test_tailoring_writes_a_new_letter(self):
        a = self.make()  # the agent is on
        out = self.letter(a)  # an older letter
        a.tasks._cover("job", "ko", out)  # as tailoring calls it
        self.assertEqual(["plan", "draft", "build", "check"], self.steps)  # all four steps
        self.assertFalse(read_json(out / "cover" / "cover.json", {})["reviewed"])  # a new letter

    def test_an_agent_that_stops_leaves_the_old_letter(self):
        a = self.make()  # the agent is on
        out = self.letter(a)  # a reviewed letter
        self.stop = True  # the model stops in the draft, as an overloaded service may
        got = a.tasks._cover("job", "ko", out)  # as tailoring calls it
        self.assertEqual({"state": "failed", "error": "agent_stopped"}, got)  # the page offers to try again
        self.assertTrue(read_json(out / "cover" / "cover.json", {})["reviewed"])  # the old letter is untouched
        self.assertFalse((out / "cover.new").exists())  # the empty skeleton is gone
        self.assertEqual(["plan", "draft"], self.steps)  # nothing was typeset from an empty letter

    def test_with_no_agent_the_written_letter_is_still_typeset(self):
        a = self.make()  # the PC
        out = self.letter(a, backend="none")  # the agent is off, and a letter was written earlier
        self.assertEqual("done", a.tasks._cover("job", "ko", out)["state"])  # its PDF is made
        self.assertEqual(["build", "check"], self.steps)  # nothing was asked

    def test_no_letter_says_why(self):
        a = self.make()  # the PC
        out = self.letter(a, written=False)  # nothing written, the agent on
        self.assertEqual("not_written", a.tasks._cover("job", "ko", out, write=False)["state"])  # tailoring writes it
        self.assertEqual([], self.steps)  # nothing ran
        a.card.chosen.return_value = "none"  # the agent off
        a.tasks.backend.return_value = "none"
        self.assertEqual("needs_agent", a.tasks._cover("job", "ko", out)["state"])  # the page offers to turn it on

    def test_a_failed_typesetting_shows_no_old_pages(self):
        a = self.make()  # the agent on
        out = self.letter(a)  # a reviewed letter with old pages
        (out / "cover" / "cover.pdf").write_bytes(b"old")  # an earlier typesetting
        with mock.patch.object(covermod, "main", return_value=2):  # the build fails
            got = a.tasks._cover("job", "ko", out, write=False)  # as Make PDFs calls it
        self.assertEqual("drafted", got["state"])  # the letter stands, without pages
        self.assertFalse((out / "cover" / "cover.pdf").exists())  # the old pages are not shown as new


class RedirectTests(unittest.TestCase):
    """A public page cannot lead the link fetch to this PC or its network."""

    def setUp(self):
        class Page(http.server.BaseHTTPRequestHandler):  # a page that redirects, then a page
            def do_GET(self):
                if self.path == "/go":  # the first hop
                    self.send_response(302)
                    self.send_header("Location", f"http://localhost:{self.server.server_address[1]}/inside")  # a name the patch below calls private
                    self.end_headers()
                    return
                type(self).reached = True  # the fetch got here
                body = b"<html><title>t</title><body>" + b"word " * 50 + b"</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):  # quiet
                pass

        Page.reached = False  # nothing fetched yet
        self.page = Page  # for the test's check
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)  # a free port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()  # it answers while the test runs
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/go"  # the link

    def test_a_redirect_to_a_private_host_is_refused(self):
        with mock.patch.object(postings, "public_host", lambda host, addrs=None: host == "127.0.0.1"), mock.patch.dict(os.environ, {"no_proxy": "*"}):  # the first host counts as public, the next as private
            with self.assertRaises(ValueError) as e:
                postings.fetch(self.url)  # the way a pasted link goes
        self.assertEqual("bad_link", str(e.exception))  # the code the page words
        self.assertFalse(self.page.reached)  # nothing was sent there

    def test_a_redirect_to_a_public_host_is_followed(self):
        with mock.patch.object(postings, "public_host", lambda host, addrs=None: True), mock.patch.dict(os.environ, {"no_proxy": "*"}):  # both count as public
            got = postings.fetch(self.url)  # followed
        self.assertTrue(self.page.reached)  # the page was read
        self.assertIn("word", got["text"])  # its text


class AddressTests(unittest.TestCase):
    """Which addresses a posting's link may reach, and that the fetch connects to the very address it checked."""

    def test_only_public_addresses(self):
        for addr in ("127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "100.100.100.200",
                     "0.0.0.0", "224.0.0.1", "192.0.2.1", "198.18.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1"):
            self.assertFalse(postings.public_address(addr), addr)  # this PC, its network, a carrier's shared range, a cloud's metadata, tests
        for addr in ("93.184.215.14", "8.8.8.8", "2606:4700:4700::1111"):
            self.assertTrue(postings.public_address(addr), addr)

    def test_the_connection_goes_to_the_address_that_was_checked(self):
        # a name that answers a public address for the check and this PC's for the connection (DNS rebinding) gets nowhere:
        # the name is asked once, and the connection goes to that answer
        went = []  # where the fetch connected

        def connect(addr, *a, **k):  # no network in the test: say where it went, then fail as an unreachable host would
            went.append(addr)
            raise ConnectionRefusedError("test")

        def lookup(*a, **k):  # a second lookup would be the rebinding gap
            raise AssertionError("the name was asked again")

        with mock.patch.object(postings, "addresses", lambda host: ["93.184.215.14"]), mock.patch.object(postings.socket, "create_connection", connect), \
                mock.patch.object(postings.socket, "getaddrinfo", lookup), mock.patch.dict(os.environ, {"no_proxy": "*"}):
            with self.assertRaises(ValueError) as e:
                postings.fetch("http://rebind.example/job")
        self.assertEqual("unreachable", str(e.exception))
        self.assertEqual([("93.184.215.14", 80)], went)

    def test_a_name_whose_first_address_does_not_answer_is_reached_through_the_next(self):
        # a name that answers IPv6 first, on a PC with no IPv6 route (GitHub's runners say ::1 first for localhost, and the
        # page here listens on 127.0.0.1 only): every checked address is tried in the system's order, as a connection always was
        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><title>t</title><body>" + b"word " * 50 + b"</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):  # quiet
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)  # IPv4 only
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with mock.patch.object(postings, "addresses", lambda host: ["::1", "127.0.0.1"]), mock.patch.dict(os.environ, {"no_proxy": "*"}):
            got = postings.fetch(f"http://dual.example:{srv.server_address[1]}/job", allow_local=True)  # ::1 refuses (or is not there)
        self.assertIn("word", got["text"])  # read through 127.0.0.1

    def test_a_page_that_drips_is_cut_at_the_deadline(self):
        class Drip(http.server.BaseHTTPRequestHandler):  # headers, then one byte at a time, each in time for a read's own wait
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                for _ in range(100):
                    try:
                        self.wfile.write(b"x")
                        self.wfile.flush()
                    except OSError:  # the fetch gave up
                        return
                    time.sleep(0.2)

            def log_message(self, *a):  # quiet
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Drip)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        t0 = time.monotonic()
        with mock.patch.object(postings, "TIMEOUT", 1.0), mock.patch.dict(os.environ, {"no_proxy": "*"}):
            with self.assertRaises(ValueError) as e:
                postings.fetch(f"http://127.0.0.1:{srv.server_address[1]}/job", allow_local=True)
        self.assertEqual("unreachable", str(e.exception))
        self.assertLess(time.monotonic() - t0, 3)  # the whole fetch, not each read


class CharsetTests(unittest.TestCase):
    """A posting page that names a charset Python does not know is still read."""

    def test_an_unknown_charset_is_read_as_utf8(self):
        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = "<html><title>공고</title><body>".encode() + "백엔드 엔지니어를 찾습니다. ".encode() * 5 + b"</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=x-made-up")  # a name no codec has
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):  # quiet
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with mock.patch.object(postings, "public_host", lambda host, addrs=None: True), mock.patch.dict(os.environ, {"no_proxy": "*"}):
            got = postings.fetch(f"http://127.0.0.1:{srv.server_address[1]}/job")  # not a 500
        self.assertIn("백엔드 엔지니어", got["text"])  # read as UTF-8


class KitDeckTests(Base):
    """The question map asks about the deck's pages once its PDF is made."""

    def test_the_map_has_the_deck_pages(self):
        a = self.make()  # the PC
        a.add_example("ko")  # the fictional person
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a job
        none = a.tasks.ensure_kit(jid, "ko")  # no PDFs yet
        self.assertEqual([], [r for r in none if r["kind"] == "portfolio"])  # no pages to ask about
        deck = a.tasks.build_dir(jid, "ko") / "deck.pdf"  # the edition's deck
        deck.parent.mkdir(parents=True, exist_ok=True)  # its folder
        deck.write_bytes(b"%PDF")  # the reader below stands in
        with mock.patch("pdftools.text", return_value="Order platform\nMoved the order service from one large program to smaller services.\n\fLatency work\nFound the slow queries behind the checkout page and rewrote them.\n\f"):
            rows = a.tasks.ensure_kit(jid, "ko")  # with the PDFs
        pages = [r for r in rows if r["kind"] == "portfolio"]  # the deck's questions
        self.assertEqual(2, len(pages))  # one per page
        self.assertEqual("Order platform", pages[0]["text"])  # named by its title
        deck.unlink()  # the PDFs were made again without a deck
        self.assertEqual([], [r for r in a.tasks.ensure_kit(jid, "ko") if r["kind"] == "portfolio"])  # the old name does not stay


class DraftedScenesTests(Base):
    """A question a draft answers says so on the board, and the drafts are counted as scenes, not files."""

    def test_the_board_marks_what_a_draft_answers(self):
        from apps.api import studio  # the board
        from interview.job import Job  # the kit's folders
        a = self.make()  # the PC
        a.add_example("ko")  # the fictional person
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a job
        rows = a.tasks.ensure_kit(jid, "ko")  # the map, no model
        before = studio.board(a.tasks, jid)["counts"]  # before any draft
        open_q = [r["id"] for r in rows if r.get("coverage") == "none"][:2]  # two questions no scene answers
        drafts = Job(a.ws.job_dir(jid)).out_dir() / "drafts"  # where the agent's drafts go
        drafts.mkdir(parents=True, exist_ok=True)  # made
        scene = "### N{n}. A question / 질문\n\n**면접관** A question?\n**나** An answer.\n- **근거**: {q} (posting.md:1)\n\n"  # the shape src/interview/draft.py writes
        (drafts / "drafts-1.md").write_text("# drafts\n\n## N. 초안\n\n" + "".join(scene.format(n=i + 1, q=q) for i, q in enumerate(open_q)), encoding="utf-8")  # two scenes in one file
        b = studio.board(a.tasks, jid)  # the board now
        marked = {q["id"]: q["coverage"] for c in b["categories"] for q in c["questions"]}  # each question's lamp
        self.assertEqual(["draft", "draft"], [marked[q] for q in open_q])  # both say a draft answers them
        self.assertEqual(2, b["counts"]["drafted"])  # counted
        self.assertEqual(before["uncovered"] - 2, b["counts"]["uncovered"])  # and no longer counted as without a script

    def test_a_job_without_a_kit_never_asks_the_kits_port(self):
        from apps.api import studio  # the board
        a = self.make()  # the PC
        a.add_example("ko")  # the fictional person
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a job, no kit made
        with mock.patch.object(studio, "health") as health, mock.patch.object(a.tasks, "kit_url") as start:  # the looks at a kit's server
            b = studio.board(a.tasks, jid)  # the board of a job with no kit
        self.assertFalse(b["ready"])  # the page offers to make one
        self.assertEqual(0, health.call_count + start.call_count)  # and nothing waited on, or started, a server with no kit to search
        self.assertEqual("/kit/" + urllib.parse.quote(jid, safe="") + "/", b["search"]["url"])  # the kit's address is the panel's own (web.py kit_proxy)


class OwnEditionTests(Base):
    """A resume the person already wrote for one job, brought in whole: that job's documents print it as written, with its
    own headline, while the profile and the general edition stay as they were."""

    def test_a_job_prints_the_resume_brought_in_for_it(self):
        import json  # the edition, as a file would give it
        from apps.api import documents  # the canvas's model
        from apps.api.routes import Router  # the table the page and the tools call
        a = self.make()  # the PC
        a.add_example("ko")  # the fictional person, as the profile
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a job
        own = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the same person's resume
        own["summary"]["headline"] = "감마의 배포 플랫폼에 맞춘 머리 문장"  # written for this job
        own["roles"][0]["projects"][0]["summary"] = "감마 지원판에만 있는 문장이다."  # and an item rewritten for it
        status, body, _ = Router(a).handle("POST", "/api/v1/jobs/own", None, {"job": jid, "profile": own, "langs": ["ko"], "name": "감마판"})
        self.assertEqual(200, status, body)  # brought in
        words = lambda m: " ".join(s["text"] for s in m["sentences"].values())  # every sentence of a model
        mine, general = documents.resume(a.tasks, "ko", "navy", jid), documents.resume(a.tasks, "ko", "navy", None)
        self.assertIn("감마의 배포 플랫폼에 맞춘 머리 문장", words(mine))  # the job's own headline
        self.assertIn("감마 지원판에만 있는 문장이다", words(mine))  # and its own item
        self.assertNotIn("감마 지원판에만 있는 문장이다", words(general))  # the general edition is the profile's
        self.assertNotIn("감마의 배포 플랫폼에 맞춘 머리 문장", words(general))
        self.assertIn("결제 백엔드와 사내 배포 플랫폼을 설계하고 운영", words(general))  # the profile's own headline: the general edition is not empty
        self.assertEqual(0, mine["counts"].get("unsupported", 0))  # the person's own words are their own evidence: nothing blocks the export
        self.assertEqual(["ko"], next(j for j in a.jobs_view() if j["id"] == jid)["own"])  # the page knows
        self.assertEqual(["needs_translation"], documents.resume(a.tasks, "en", "navy", jid)["missing"])  # no English brought in
        self.assertEqual(a.facts.details().get("email"), a.tasks.facts_for(jid).details().get("email"))  # the person is the same
        self.assertEqual(a.facts.details()["_src"]["email"], a.tasks.facts_for(jid).details()["_src"]["email"])  # and where it came from

    def test_an_edition_keeps_its_own_words_and_borrows_the_persons(self):
        """A save to an application's own edition: the person's fields go to the profile with their sources, its own words stay
        in its folder, and its folder gets no copy of the person's new ones."""
        import json  # the edition, as a file would give it
        from apps.api.routes import Router  # the table the page and the tools call
        a = self.make()
        a.add_example("ko")  # the profile: the fictional person
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})
        own = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the same person's resume for the job
        status, body, _ = Router(a).handle("POST", "/api/v1/jobs/own", None, {"job": jid, "profile": own, "langs": ["ko"], "name": "감마판"})
        self.assertEqual(200, status, body)
        ed = a.tasks.facts_for(jid)  # the edition's facts
        before = json.loads(ed.ws.path("profile", "details.json").read_text(encoding="utf-8"))  # the edition's own file, as brought in
        ed.set_details({"phone": "010-9999-0000", "headline": "감마판 머리 문장"}, {"phone": {"file": "notes.md", "material": "m1", "quote": "010-9999-0000"}})
        self.assertEqual("010-9999-0000", a.facts.details()["phone"])  # the person's phone, in the profile
        self.assertEqual("notes.md", a.facts.details()["_src"]["phone"]["file"])  # with the file a run found it in
        self.assertEqual("010-9999-0000", ed.details()["phone"])  # the edition reads it from there
        self.assertEqual("notes.md", ed.details()["_src"]["phone"]["file"])  # with its source
        self.assertEqual({"typed": True}, ed.details()["_src"]["headline"])  # the edition's own words, typed
        kept = json.loads(ed.ws.path("profile", "details.json").read_text(encoding="utf-8"))  # the edition's own file after the save
        self.assertEqual(before.get("phone"), kept.get("phone"))  # no copy of the person's new phone
        self.assertEqual(before["_src"].get("phone"), kept["_src"].get("phone"))  # nor of its source
        self.assertEqual("감마판 머리 문장", kept["headline"])  # its own words, kept there


class OwnFormTests(Base):
    """The layout choices an own edition was made with (own/form.json) reach its job.json, the posting's order does not, and
    only the keys the form reads are kept."""

    def test_an_own_edition_keeps_its_choices_and_its_order(self):
        import json  # the edition, as a file would give it
        from apps.api.routes import Router  # the table the page and the tools call
        a = self.make()  # the PC
        a.add_example("ko")  # the fictional person, as the profile
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a job
        (a.ws.job_dir(jid) / "plan.json").write_text(json.dumps({"projectOrder": ["x-1"], "skillsFocus": ["Languages"]}), encoding="utf-8")  # a posting analysis
        own = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the same person's resume
        form = {"ko": {"plain": True, "footerLabel": "경력기술서", "competencyFigure": False, "photo": False, "titleView": "full", "script": "x"}}
        status, body, _ = Router(a).handle("POST", "/api/v1/jobs/own", None, {"job": jid, "profile": own, "langs": ["ko"], "name": "감마판", "form": form})
        self.assertEqual(200, status, body)  # brought in
        cfg = a.tasks.edition_cfg(jid, "ko", "navy")  # what the build writes to job.json
        self.assertTrue(cfg["plain"])  # the plain look
        self.assertEqual("경력기술서", cfg["footerLabel"])  # the older footer
        self.assertIs(False, cfg["competencyFigure"])  # no hierarchy figure
        self.assertEqual("full", cfg["titleView"])  # the long role labels on the timeline
        self.assertNotIn("projectOrder", cfg)  # the posting's order is not the person's
        self.assertNotIn("script", a.tasks.own_form(jid, "ko"))  # only what the form reads
        self.assertIs(False, a.tasks.own_form(jid, "ko")["photo"])  # made without a photo
        other = a.add_job({"company": "델타", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a job drafted from the profile
        (a.ws.job_dir(other) / "plan.json").write_text(json.dumps({"projectOrder": ["x-1"]}), encoding="utf-8")
        self.assertEqual(["x-1"], a.tasks.edition_cfg(other, "ko", "navy")["projectOrder"])  # it takes the posting's order
        self.assertEqual("own_lang", a.tasks.own_src(jid, "en"))  # no English brought in
        stamp = a.tasks.own_stamp(jid)  # what the own edition is now
        self.assertTrue(stamp)  # it has one
        self.assertFalse(a.stale(jid, {"profile": "an older profile", "own": stamp}))  # the profile changing does not make it stale
        self.assertTrue(a.stale(jid, {"profile": a.profile_hash(), "own": "an older own edition"}))  # its own edition changing does
        self.assertFalse(a.stale(jid, {"profile": "an older profile"}))  # a build from before the stamp counts as current
        self.assertEqual("", a.tasks.own_stamp(other))  # a job drafted from the profile has none


class PicturePathTests(Base):
    """A profile may name its pictures relative to the workspace's profile/ folder, so the workspace can be moved whole: the
    edition's copy names them in full, where the typesetting finds them."""

    def test_relative_pictures_are_found_from_the_workspace(self):
        a = self.make()  # the PC
        logos = a.ws.path("profile", "logos")  # inside the workspace
        logos.mkdir(parents=True, exist_ok=True)
        (logos / "tile_gamma.png").write_bytes(b"\x89PNG fictional")  # a logo the person keeps there
        prof = {"roles": [{"logo": "logos/tile_gamma.png", "projects": [{"logo": "logos/none.png"}]}],  # one there, one not
                "education": [{"logo": "/elsewhere/tile.png"}], "deck": {"pdf": {"ko": "logos/tile_gamma.png", "en": ""}}}
        got = a.tasks._place_pictures(prof)
        full = str((logos / "tile_gamma.png").resolve())  # its full path
        self.assertEqual(full, got["roles"][0]["logo"])  # found from the workspace
        self.assertEqual("logos/none.png", got["roles"][0]["projects"][0]["logo"])  # no such file: as written
        self.assertEqual("/elsewhere/tile.png", got["education"][0]["logo"])  # an absolute path: as written
        self.assertEqual({"ko": full, "en": ""}, got["deck"]["pdf"])  # the portfolio PDF the same way


class NamedEditionTests(Base):
    """Named general editions: off the board, in the state's own list, picked like a job, and able to take an own edition."""

    def test_a_named_edition_is_kept_apart_from_the_board(self):
        import json  # the edition, as a file would give it
        from apps.api.routes import Router  # the table the page and the tools call
        a = self.make()  # the PC
        a.add_example("ko")  # the fictional person
        r = Router(a)  # the routes
        status, body, _ = r.handle("POST", "/api/v1/editions", None, {"name": "헤드헌터용 플랫폼 엔지니어"})
        self.assertEqual(200, status, body)  # made
        eid = body["job"]  # its id
        self.assertTrue(eid.startswith("-"))  # apart from any company's folder
        self.assertEqual([], a.jobs_view())  # not on the board
        st = a.state()  # what the page draws
        self.assertEqual(["헤드헌터용 플랫폼 엔지니어"], [e["name"] for e in st["editions"]])  # in its own list
        self.assertEqual(200, r.handle("POST", "/api/v1/jobs/select", None, {"job": eid})[0])  # picked in Documents
        self.assertEqual(eid, a.state()["job"])  # and it stays in view
        own = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # a resume for it
        status, body, _ = r.handle("POST", "/api/v1/jobs/own", None, {"job": eid, "profile": own, "langs": ["ko"], "name": "헤드헌터용"})
        self.assertEqual(200, status, body)  # a named edition takes an own edition
        self.assertEqual(["ko"], a.state()["editions"][0]["own"])  # the page knows
        self.assertEqual(400, r.handle("POST", "/api/v1/editions", None, {"name": "  "})[0])  # a name is needed
        self.assertEqual(400, r.handle("POST", "/api/v1/jobs/own", None, {"job": appmod.GENERAL, "profile": own, "langs": ["ko"]})[0])  # the general edition is the profile itself


class OwnFileTests(Base):
    """A document the person made, kept for an edition as it is, and the files that went out with an application kept as its
    submitted copies, byte for byte."""

    PDF = b"%PDF-1.4\n% a fictional one-page file\n%%EOF\n"  # enough to pass the type check

    def test_a_word_file_leaves_nothing_in_the_engine(self):
        """The Word file's staged copy and the PDF LibreOffice wrote go once the edition has its own (stood in for here)."""
        import resume  # src/resume.py: the conversion
        a = self.make()
        a.add_example("ko")
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})
        a.own_file(jid, "ko", "resume", "새판.docx", b"PK\x03\x04 a fictional zip")  # the person's Word file
        out_dir = a.tasks.build_dir(jid, "ko")
        out_dir.mkdir(parents=True, exist_ok=True)
        left = []  # what the conversion put in the engine's folder

        def convert(f):  # as docx_to_pdf does: the file staged by resume.rel, the PDF written beside the outputs
            staged = pathlib.Path(ROOT / resume.rel(str(f)))
            made = ROOT / "output" / (staged.stem + ".pdf")
            made.write_bytes(b"%PDF-1.4 fictional")
            left.extend([staged, made])
            return made
        with mock.patch.object(resume, "docx_to_pdf", side_effect=convert), mock.patch("pdfmeta.read", return_value={"title": "t", "author": "a"}):
            got = a.tasks._own_pdf(jid, "resume", "ko", out_dir)
        self.assertTrue(got.is_file() and (out_dir / "own_resume.docx").is_file())  # the edition has its own copies
        self.assertEqual([], [str(f) for f in left if f.exists()])  # and the engine's folder has none

    def test_own_files_and_sent_copies(self):
        import hashlib  # byte for byte
        a = self.make()  # the PC
        a.add_example("ko")  # the fictional person
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a job
        got = a.own_file(jid, "ko", "resume", "감마_이력서.pdf", self.PDF)  # the person's own resume
        self.assertEqual("resume_ko.pdf", got["file"])  # one per kind and language
        self.assertEqual(a.tasks.own_file(jid, "resume", "ko").read_bytes(), self.PDF)  # kept as it came
        a.own_file(jid, "ko", "resume", "새판.docx", b"PK\x03\x04 a fictional zip")  # a Word file replaces it
        self.assertEqual(".docx", a.tasks.own_file(jid, "resume", "ko").suffix)  # one per kind and language
        with self.assertRaises(ValueError):  # a portfolio is a PDF
            a.own_file(jid, "ko", "deck", "deck.docx", b"PK\x03\x04")
        with self.assertRaises(ValueError):  # bytes that are not what the name says
            a.own_file(jid, "ko", "cover", "letter.pdf", b"not a pdf")
        with self.assertRaises(ValueError):  # three kinds only
            a.own_file(jid, "ko", "photo", "x.pdf", self.PDF)
        sent = a.sent_file(jid, "ko", "resume", "감마_낸판.pdf", self.PDF)  # what went out
        a.sent_file(jid, "ko", "deck", "감마_포트폴리오.pdf", self.PDF + b" ")  # with its portfolio
        st = a.ws.job(jid)  # the card
        self.assertEqual("submitted", st["stage"])  # sent: it moved on
        self.assertTrue(st["locked"]["brought"])  # kept as brought in
        self.assertEqual({"resume.pdf", "deck.pdf"}, set(st["locked"]["files"]))  # one folder for the language
        kept = a.ws.job_dir(jid) / "submitted" / sent["folder"] / "resume.pdf"
        self.assertEqual(hashlib.sha256(self.PDF).hexdigest(), hashlib.sha256(kept.read_bytes()).hexdigest())  # byte for byte
        desk = pathlib.Path(tempfile.mkdtemp())  # a Desktop of its own
        old = os.environ.get("OFFEROWL_DESKTOP")
        os.environ["OFFEROWL_DESKTOP"] = str(desk)
        try:
            names = a.tasks.export(jid, "ko")  # a submitted application gives what went out
            self.assertEqual(2, len(names))  # the resume and the portfolio
            self.assertIn(self.PDF, [(desk / n).read_bytes() for n in names])  # as sent, not stamped or made again
            self.assertTrue(all("감마" in n for n in names))  # under the job's readable names
        finally:
            os.environ.pop("OFFEROWL_DESKTOP") if old is None else os.environ.__setitem__("OFFEROWL_DESKTOP", old)
            shutil.rmtree(desk, ignore_errors=True)


class AgentCallsTests(unittest.TestCase):
    """The agent's card counts its own agent's calls: a local model or a test's stand-in server writes to the same log."""

    def test_only_the_cards_agent_counts(self):
        import json  # the log's lines
        import llm  # src/llm.py: the log's place
        from apps.api.agent import calls_summary  # the card's figures
        old = llm.LOG  # put back at the end
        tmp = pathlib.Path(tempfile.mkdtemp())  # a log of its own
        try:
            llm.LOG = tmp / "calls.jsonl"
            now = int(time.time())  # this day
            llm.LOG.write_text("".join(json.dumps({"t": now, "backend": b, "task": "x", "sec": 1.0}) + "\n"
                                       for b in ("claude-code", "openai-compat", "openai-compat")), encoding="utf-8")
            self.assertEqual(1, calls_summary(backend="claude-code")["calls"])  # the card's agent
            self.assertEqual(3, calls_summary()["calls"])  # every call, when no agent is named
        finally:
            llm.LOG = old
            shutil.rmtree(tmp, ignore_errors=True)


class SameProfileTests(Base):
    """A profile written again with the same content (a rebuild that changed nothing, another tool's spacing) keeps its
    English translation and its editions current."""

    def test_the_same_content_is_the_same_profile(self):
        import json  # the files
        from apps.api.tasks import content_hash  # the content's hash
        a = self.make()  # the PC
        a.add_example("ko")  # the fictional person
        src = a.ws.path("profile", "profile.json")  # the profile
        if not src.is_file():  # written when the facts are kept
            a.keep_all()
        data = json.loads(src.read_text(encoding="utf-8"))  # its content
        a.tasks.profile_lang = lambda: "ko"  # a Korean profile, whatever the example's share of Hangul
        en = a.ws.path("profile", "profile.en.json")  # a translation of it
        en.write_text(json.dumps({**data, "_from": content_hash(src)}, ensure_ascii=False), encoding="utf-8")
        recorded = content_hash(src)  # what an edition records
        src.write_text(json.dumps(data, ensure_ascii=False, indent=4, sort_keys=True), encoding="utf-8")  # the same content, spaced otherwise
        self.assertEqual(en, a.tasks.english_profile())  # still its translation
        self.assertTrue(a.same_profile(recorded))  # and the edition is current
        data["summary"]["headline"] = "다른 머리 문장"  # a real change
        src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertIsNone(a.tasks.english_profile())  # asks to translate again
        self.assertFalse(a.same_profile(recorded))  # and the edition is stale


class PlanFitTests(unittest.TestCase):
    """A posting analysis names competencies and skill groups as the profile had them; a draft may rename them. The edition's
    job.json keeps only the names its profile has, so the form does not stop on one an older analysis gave."""

    def test_names_the_edition_lacks_are_left_out(self):
        import json  # the files
        from apps.api.tasks import Tasks  # the step under test
        d = pathlib.Path(tempfile.mkdtemp())  # an edition's folder
        try:
            (d / "job.json").write_text(json.dumps({"competencyWeak": ["옛 역량", "새 역량"], "competencyDrop": ["옛 역량"], "skillsFocus": ["Data", "Gone"],
                                                    "projectOrder": ["x-1"]}, ensure_ascii=False), encoding="utf-8")
            (d / "profile.json").write_text(json.dumps({"competencies": {"ko": [{"name": "새 역량", "text": "t"}], "en": [{"name": "New", "text": "t"}]},
                                                        "skills": [{"category": "Data", "items": ["SQL"]}]}, ensure_ascii=False), encoding="utf-8")
            Tasks._fit_plan_to_edition(d, "ko")  # the job.json the form reads
            cfg = json.loads((d / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(["새 역량"], cfg["competencyWeak"])  # the name the draft kept
            self.assertEqual([], cfg["competencyDrop"])  # the renamed one left out
            self.assertEqual(["Data"], cfg["skillsFocus"])  # a group the edition has
            self.assertEqual(["x-1"], cfg["projectOrder"])  # the order is untouched (an unknown id is skipped by the form)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class EnglishAnswerTests(unittest.TestCase):
    """An English answer is not held word by word against Korean facts: only its numbers and organisations are."""

    def test_plain_english_words_pass_and_numbers_still_count(self):
        from apps.api import answers as A  # the checks
        q = {"text": "Why do you want to join us?", "limit": 200, "unit": "words"}  # an English question
        facts = {"f1": "감마 · 플랫폼 개발: 결제 백엔드를 설계하고 운영했다"}  # a Korean fact
        ok = A.problems(q, "I designed and ran a payment backend, and I would like to build the same care into your platform.", [], facts, {})
        self.assertFalse([x for x in ok if x.startswith("unsupported")])  # ordinary words are not names
        bad = A.problems(q, "I designed a payment backend that served 40 million users.", [], facts, {})
        self.assertTrue([x for x in bad if x.startswith("unsupported")])  # a number the facts do not hold still stops it

    def test_the_postings_names_are_the_companys(self):
        from apps.api import answers as A  # the checks
        q = {"text": "왜 지원했나요?", "limit": 300, "unit": "chars"}  # a Korean question
        facts = {"f1": "감마 · 플랫폼 개발: 결제 백엔드를 설계하고 운영했다"}  # a Korean fact
        answer = "결제 백엔드를 운영한 경험으로 델타의 Nimbus 플랫폼을 함께 만들고 싶습니다."  # the company's product, named
        self.assertTrue([x for x in A.problems(q, answer, [], facts, {}) if x.startswith("unsupported")])  # with no posting, a name the facts lack
        posting = "델타 플랫폼 엔지니어. Nimbus 플랫폼을 함께 만들 분을 찾습니다. 경력 5년 이상."  # the posting names it
        self.assertFalse([x for x in A.problems(q, answer, [], facts, {}, posting) if x.startswith("unsupported")])  # the company's own name
        said = "결제 백엔드를 5년 운영했습니다."  # a number only the posting has
        self.assertTrue([x for x in A.problems(q, said, [], facts, {}, posting) if x.startswith("unsupported")])  # numbers are the person's facts only

    def test_markdown_marks_are_said(self):
        from apps.api import answers as A  # the checks
        q = {"text": "Tell us about a project.", "limit": 60, "unit": "words"}
        facts = {"f1": "감마 · 플랫폼 개발: 결제 백엔드를 설계하고 운영했다"}
        self.assertIn("markup", A.problems(q, "**Payment backend**\n\nI designed and ran a payment backend for the team.", [], facts, {}))   # bold marks a form shows as they are
        self.assertIn("markup", A.problems(q, "# Payment backend\nI designed and ran a payment backend for the team.", [], facts, {}))   # a heading
        self.assertNotIn("markup", A.problems(q, "I designed and ran a payment backend, a 2*3 grid of services.", [], facts, {}))   # one star is a star
        self.assertNotIn("markup", A.problems(q, "I designed and ran a payment backend; its __init__ ran ____ checks.", [], facts, {}))   # Python's names and a blank are no marks


class GeneralInViewTests(Base):
    """The general edition, once picked in Documents, stays in view while jobs exist; a job that is gone gives way to the newest."""

    def test_the_general_edition_stays_in_view(self):
        from apps.api.routes import Router  # the table the page calls
        a = self.make()  # the PC
        a.add_example("ko")  # the fictional person
        jid = a.add_job({"company": "감마", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a job
        self.assertEqual(jid, a.state()["job"])  # a new job comes into view
        status, _, _ = Router(a).handle("POST", "/api/v1/jobs/select", None, {"job": appmod.GENERAL})  # the general edition picked, as the bar's choice sends it
        self.assertEqual(200, status)  # taken
        self.assertEqual(appmod.GENERAL, a.state()["job"])  # and it stays in view, not the newest job
        a.ws.set_prefs(job="gone")  # a job that is no longer there
        self.assertEqual(jid, a.state()["job"])  # the newest job instead


class LongFormTests(Base):
    """A profile in the ledger form keeps its text sections through the panel."""

    def test_a_text_section_stays_and_can_be_dropped(self):
        from apps.api.client import Client  # the API, as the page calls it
        a = self.make()  # the PC
        c = Client.__new__(Client)  # the same object behind the client
        c.api = a  # no second first look
        from apps.api.routes import Router  # the table
        c.router = Router(a)  # the routes
        fixture = ROOT / "tests" / "parts" / "fixtures" / "export_shape.json"  # a fictional long-form profile
        rec = c.post("/api/v1/materials/file", {"path": str(fixture)})["material"]  # a profile file
        c.post("/api/v1/materials/read", {"ids": [rec["id"]]})  # read
        c.wait("ingest")  # as a profile file: no agent
        c.post("/api/v1/facts/keep-all", {})  # every fact kept
        prof = a.facts.profile()  # what the generators read
        self.assertEqual(1, len(prof["sections"]))  # the section is there
        self.assertIn("가상 자격 1급", prof["sections"][0]["body_md"])  # with its text
        m = c.get("/api/v1/documents/resume", lang="ko")  # the canvas
        lines = [k for k in m["sentences"] if k.startswith("sections.0.body.")]  # its lines
        self.assertTrue(lines)  # drawn
        self.assertTrue(all(m["sentences"][k]["evidence"] for k in lines))  # each rests on the section's card
        self.assertNotIn("옮기지 않는다", " ".join(m["sentences"][k]["text"] for k in lines))  # the comment in it stays out
        card = next(r for r in c.get("/api/v1/facts")["rows"] if r.get("title") == "자격증")  # its one card
        c.post("/api/v1/facts/decide", {"cid": card["cid"], "action": "drop"})  # dropped
        self.assertEqual([], a.facts.profile()["sections"])  # the section goes with it


class AgentCardTests(unittest.TestCase):
    """The card follows a sign-in made from the panel without a restart, and a warning or an odd address does not stop it."""

    def test_a_finished_sign_in_is_seen(self):
        state = {"signed_in": False}  # as the CLI answers
        with mock.patch.object(agentmod, "claude_status", side_effect=lambda: {"installed": True, "signed_in": state["signed_in"], "email": "a@example.com"}), \
                mock.patch.object(agentmod, "codex_status", return_value={"installed": False}), mock.patch.object(agentmod, "local_status", return_value={"installed": False}):  # no real CLI
            card = agentmod.AgentCard(lambda: {"backend": "claude-code"})  # the card
            card.refresh(force=True)  # the first look
            self.assertEqual("signed_out", card.card()["state"])  # not yet
            card.login_proc = mock.Mock()  # a sign-in started from the panel
            card.login_proc.poll.return_value = None  # still in the browser
            self.assertTrue(card.card()["signing_in"])  # the page polls fast meanwhile
            state["signed_in"] = True  # the person finishes it
            card.login_proc.poll.return_value = 0  # and the CLI ends
            card.card()  # the page's next poll starts a new look
            end = time.time() + 5  # it runs behind the answer
            while time.time() < end and card.card()["state"] != "ready":  # as the page polls
                time.sleep(0.05)  # a moment
            self.assertEqual("ready", card.card()["state"])  # no restart needed

    def test_a_warning_after_the_answer_still_reads(self):
        with mock.patch.object(agentmod, "cli", return_value="/x/claude"), mock.patch.object(agentmod, "run_cli", return_value=(0, 'note: new version\n{"loggedIn": true, "email": "a@example.com"}\nwarning: slow disk {x}')):  # as a CLI may print
            self.assertTrue(agentmod.claude_status()["signed_in"])  # signed in

    def test_a_typed_address_that_cannot_be_asked_is_not_answering(self):
        self.assertFalse(agentmod.local_status("http://127.0.0.1:notaport", "m")["signed_in"])  # no exception that would leave the card checking


def desktop_app(name: str):
    """The desktop app's module, loaded from its file and not started."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "apps" / "desktop" / "app.py")  # not on the import path
    module = importlib.util.module_from_spec(spec)  # its namespace
    spec.loader.exec_module(module)  # loaded
    return module


class DesktopServerLifeTests(unittest.TestCase):
    """The server ends with the app that started it, even when the app is killed: a POSIX child in a session of its own lives
    on otherwise, and macOS has no PR_SET_PDEATHSIG."""

    def server_after_the_app_is_killed(self, watched: bool):
        import subprocess  # real processes: the app and its server
        if sys.platform == "win32":  # Windows ends the server with a job instead
            self.skipTest("Windows ties the server to the app with a job object")
        app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # stands in for the app
        self.addCleanup(app.kill)
        code = ("import importlib.util, time; "
                f"spec = importlib.util.spec_from_file_location('a', {str(ROOT / 'apps' / 'desktop' / 'app.py')!r}); "
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); m.watch_parent(); time.sleep(60)")
        env = {k: v for k, v in os.environ.items() if k != "OFFEROWL_APP_PARENT"}  # a server started by hand has no app
        if watched:  # as server_env() starts it
            env["OFFEROWL_APP_PARENT"] = str(app.pid)
        server = subprocess.Popen([sys.executable, "-c", code], env=env, start_new_session=True)  # a session of its own, as Child starts it
        self.addCleanup(lambda: server.poll() is None and server.kill())
        time.sleep(2)  # the module loaded and the watch running
        app.kill()  # the app killed: it gets no chance to stop its server
        app.wait()  # and its parent has seen it end
        return server

    def test_the_server_stops_itself_once_the_app_is_gone(self):
        import subprocess  # for the wait's time limit
        server = self.server_after_the_app_is_killed(watched=True)
        try:  # a second's watch, with room
            code = server.wait(10)
        except subprocess.TimeoutExpired:  # the defect this guards against
            self.fail("the server outlived the app that started it")
        self.assertEqual(-15, code)  # its own SIGTERM: the clean stop

    def test_without_the_watch_the_server_would_outlive_the_app(self):  # the control: what the watch prevents
        server = self.server_after_the_app_is_killed(watched=False)
        time.sleep(3)  # longer than the watch takes
        self.assertIsNone(server.poll())  # still running, an orphan


class DesktopTrayTests(unittest.TestCase):
    """The tray's stop is never lost, and on macOS what touches the icon goes through AppKit's queue."""

    @staticmethod
    def fake_pystray():
        import types  # a module made in place
        mod = types.ModuleType("pystray")  # just what make_tray uses

        class Icon:  # records what was done to it
            def __init__(self, *args):
                self.visible, self.stopped, self.notes = False, 0, []

            def stop(self):
                self.stopped += 1

            def notify(self, *args):
                self.notes.append(args)
        mod.Icon, mod.Menu, mod.MenuItem = Icon, (lambda *a: a), (lambda *a, **k: a)
        return mod

    def test_a_stop_asked_for_before_the_icon_shows_is_kept(self):
        app = desktop_app("offerowl_desktop_tray")
        stop = threading.Event()
        stop.set()  # the server given up on before the icon's loop ran: a direct icon.stop() then would do nothing
        with mock.patch.dict(sys.modules, {"pystray": self.fake_pystray()}), mock.patch.object(app, "tray_image", return_value=None), \
                mock.patch.object(app.sys, "platform", "linux"):
            icon, ready = app.make_tray("http://127.0.0.1:1/", pathlib.Path("."), stop, None)  # the icon and its setup
            ready(icon)  # what pystray runs once its loop is up
        self.assertTrue(icon.visible)  # shown, as pystray does when no setup is given
        self.assertEqual(1, icon.stopped)  # and stopped, once

    def test_on_macos_a_call_on_the_icon_goes_through_appkit(self):
        import types  # PyObjC's helper, made in place
        app = desktop_app("offerowl_desktop_tray_mac")
        queued = []  # what was handed to AppKit's queue
        helper = types.ModuleType("PyObjCTools.AppHelper")
        helper.callAfter = lambda fn, *args: queued.append((fn, args))
        tools = types.ModuleType("PyObjCTools")
        tools.AppHelper = helper
        called = []  # what ran at once
        with mock.patch.dict(sys.modules, {"PyObjCTools": tools, "PyObjCTools.AppHelper": helper}), mock.patch.object(app.sys, "platform", "darwin"):
            app.on_icon_loop(called.append, "stop")
        self.assertEqual([], called)  # never from this thread
        self.assertEqual([(called.append, ("stop",))], queued)  # queued for the main thread instead


class DesktopDataFolderTests(unittest.TestCase):
    """The server starts in the app's own folder, so a relative data folder must reach it as a full path."""

    def test_a_relative_folder_reaches_the_server_in_full(self):
        spec = importlib.util.spec_from_file_location("offerowl_desktop_app", ROOT / "apps" / "desktop" / "app.py")  # the app's module, not started
        app = importlib.util.module_from_spec(spec)  # its namespace
        spec.loader.exec_module(app)  # loaded
        with mock.patch.dict(os.environ, {"OFFEROWL_DATA_DIR": "some/relative/folder"}):  # as a person might set it
            data = app.data_dir()  # the app's own reading
            env = app.server_env({k: v for k, v in os.environ.items() if k != "OFFEROWL_LLM_LOG"}, data, 8797)  # what the server is given (a test run's own call log left out)
        self.assertTrue(pathlib.Path(env["OFFEROWL_DATA_DIR"]).is_absolute())  # never relative to the server's working folder
        self.assertEqual(str(data), env["OFFEROWL_DATA_DIR"])  # the same folder the app's logs use
        self.assertEqual(str(data / "logs" / "calls.jsonl"), env["OFFEROWL_LLM_LOG"])  # the agent's call log with them, kept across starts

    def test_on_macos_the_folders_are_the_mac_ones_and_finder_opens_them(self):
        """The macOS branches, run here with the system's name changed: the app and the server agree on Application Support,
        the PDFs go to ~/Desktop, and Finder is asked with `open`."""
        spec = importlib.util.spec_from_file_location("offerowl_desktop_app_mac", ROOT / "apps" / "desktop" / "app.py")  # the app's module, not started
        app = importlib.util.module_from_spec(spec)  # its namespace
        spec.loader.exec_module(app)  # loaded
        from apps.api import delivery as tasksmod  # the Desktop and the file manager of the server (apps/api/delivery.py)
        env = {k: v for k, v in os.environ.items() if k not in ("OFFEROWL_DATA_DIR", "OFFEROWL_DESKTOP")}  # the usual places, not a test's
        mac = pathlib.Path.home() / "Library" / "Application Support" / "Offerowl"  # where Mac apps keep their data
        with mock.patch.object(sys, "platform", "darwin"), mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(tasksmod, "in_wsl", return_value=False):  # a Mac, not this PC's WSL
            self.assertEqual(mac, app.data_dir())  # the app's logs and settings
            self.assertEqual(mac, appmod.data_dir())  # the same folder for the server
            self.assertEqual(pathlib.Path.home() / "Desktop", tasksmod.desktop_dir())  # where the PDFs land
            with mock.patch.object(tasksmod.subprocess, "Popen") as popen:  # nothing is opened here
                tasksmod.open_in_files(pathlib.Path("/tmp/x"))  # the server's 'show in folder'
            self.assertEqual(["open", str(pathlib.Path("/tmp/x"))], popen.call_args[0][0])  # Finder, given the path as this system writes it
            with mock.patch.object(app.subprocess, "Popen") as popen:
                app.open_folder(pathlib.Path("/tmp/x"))  # the menu bar icon's data folder item
            self.assertEqual(["open", str(pathlib.Path("/tmp/x"))], popen.call_args[0][0])  # Finder, given the path as this system writes it too

    def test_quitting_stops_the_server_and_what_it_started(self):
        """A one-file build's server is a launcher with the server under it: quitting must stop both, so no orphan holds the port."""
        if sys.platform == "win32":  # taskkill /T takes the tree there
            self.skipTest("Windows ends the whole tree with taskkill")
        spec = importlib.util.spec_from_file_location("offerowl_desktop_app3", ROOT / "apps" / "desktop" / "app.py")  # the app's module, not started
        app = importlib.util.module_from_spec(spec)  # its namespace
        spec.loader.exec_module(app)  # loaded
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = pathlib.Path(tmp) / "inner.pid"  # where the inner process says who it is
            # the launcher ignores SIGTERM and starts an inner server that ignores it too, as a stuck one-file child would
            script = f"trap '' TERM; sh -c 'trap \"\" TERM; echo $$ > {pidfile}; while true; do sleep 1; done' & wait"
            child = app.Child("server", ["sh", "-c", script], dict(os.environ), app.CappedLog(pathlib.Path(tmp) / "c.log"))
            child.start()  # in a session of its own, as the app starts it
            for _ in range(50):  # the inner process has written its pid
                if pidfile.is_file() and pidfile.read_text(encoding="utf-8").strip():
                    break
                time.sleep(0.1)
            inner = int(pidfile.read_text(encoding="utf-8").strip())  # the server under the launcher
            child.stop(timeout=1)  # what quitting does
            time.sleep(0.3)  # the signal lands
            with self.assertRaises(ProcessLookupError):  # gone too, not orphaned
                os.kill(inner, 0)

    def test_a_double_click_still_finds_the_agent(self):  # Finder and a desktop menu start programs with a short PATH
        if sys.platform == "win32":  # a double-click there has the whole PATH
            self.skipTest("Windows keeps the person's PATH")
        spec = importlib.util.spec_from_file_location("offerowl_desktop_app2", ROOT / "apps" / "desktop" / "app.py")  # the app's module, not started
        app = importlib.util.module_from_spec(spec)  # its namespace
        spec.loader.exec_module(app)  # loaded
        with tempfile.TemporaryDirectory() as tmp:  # a person's folder
            home = pathlib.Path(tmp)  # the folder
            (home / ".local" / "bin").mkdir(parents=True)  # where an agent's installer writes
            (home / "tools").mkdir()  # a folder only the person's shell knows
            shell = home / "shell"  # a stand-in for the login shell, chatty as real ones are
            shell.write_text(f'#!/bin/sh\necho "welcome back"\nexport PATH="{home}/tools:$PATH"\nshift\nexec /bin/sh -c "$@"\n', encoding="utf-8")  # it adds a folder
            shell.chmod(0o755)  # a program
            env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "SHELL": str(shell)}  # what Finder hands over
            with mock.patch.object(app.sys, "stdin", None):  # no terminal, as from Finder
                path = app.widen_path(env).split(os.pathsep)  # widened
            self.assertEqual(["/usr/bin", "/bin"], path[:2])  # what this start was given stays first
            self.assertIn(str(home / "tools"), path)  # the login shell's folder, past its greeting
            self.assertIn(str(home / ".local" / "bin"), path)  # the installer's folder
            self.assertNotIn(str(home / ".bun" / "bin"), path)  # a folder that is not there is not added
            quiet = {"HOME": str(home), "PATH": "/usr/bin", "SHELL": str(home / "no-such-shell")}  # a shell that cannot start
            with mock.patch.object(app.sys, "stdin", None):  # no terminal, as from Finder
                self.assertIn(str(home / ".local" / "bin"), app.widen_path(quiet).split(os.pathsep))  # the usual folders still count
            slow = home / "slow"  # a shell whose start-up files never end, and leave a job holding its output
            slow.write_text("#!/bin/sh\n(sleep 30) &\nsleep 30\n", encoding="utf-8")  # as a broken rc file does
            slow.chmod(0o755)  # a program
            started = time.time()  # the limit is five seconds
            self.assertEqual("", app.login_path({"HOME": str(home), "PATH": "/usr/bin:/bin", "SHELL": str(slow)}))  # no answer
            self.assertLess(time.time() - started, 8)  # and the app starts anyway
            tty = mock.Mock()  # a terminal on stdin: PATH is the shell's already
            tty.isatty.return_value = True  # as when started from a terminal
            with mock.patch.object(app.sys, "stdin", tty), mock.patch.object(app, "login_path", side_effect=AssertionError("asked")):  # no shell is started
                app.widen_path({"HOME": str(home), "PATH": "/usr/bin"})  # an interactive shell there could stop this program


if __name__ == "__main__":  # run as a script
    unittest.main()
