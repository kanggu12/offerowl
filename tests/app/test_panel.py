"""The panel's API without a browser, on the fictional example: the first run, the resume with each sentence's
evidence, an edit the evidence does not cover (marked, export refused, undone), locks and the history; a job with its
fit, tailoring all three documents and the interview board; the tracker with reminders; the agent's steps through the
stand-in (reading notes, the posting analysis, regenerating a sentence); the safety rules; the schemas; the
in-process client; and the Korean table. No model is called: the agent is off, or the stand-in of apps/api/standin.py.

    python3 -m unittest tests/app/test_panel.py -v
"""
import http.client  # requests with a made-up Host header
import http.server  # a page to fetch a posting from
import io  # a backup in memory
import json  # requests and answers
import os  # environment for the stand-in
import pathlib  # paths
import re  # the i18n scan
import shutil  # clean temporary folders
import sys  # the import path
import tempfile  # a workspace per test class
import threading  # the server in the background
import time  # waiting for tasks
import unittest  # the runner
import urllib.error  # refused requests
import urllib.parse  # upload names
import urllib.request  # requests
import zipfile  # a backup's entries
from unittest import mock  # an environment for one check

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ and core/ are found from here
from apps.panel import server  # noqa: E402  the panel (the page and the API)
from apps.api.standin import facts as standin_facts  # noqa: E402  the stand-in's rules
from core.schema import validate  # noqa: E402  the data model

if not os.environ.get("OFFEROWL_LLM_LOG"):  # the stand-in agent's calls go to a log of this run, not the engine's own output/_llm (pytest: tests/conftest.py)
    _log_dir = tempfile.mkdtemp(prefix="offerowl-tests-log-")  # this run's
    __import__("atexit").register(shutil.rmtree, _log_dir, True)  # gone afterwards
    os.environ["OFFEROWL_LLM_LOG"] = os.path.join(_log_dir, "calls.jsonl")  # read by src/llm.py when it is first imported
    if "llm" in sys.modules:  # imported already: pointed there too
        sys.modules["llm"].LOG = pathlib.Path(os.environ["OFFEROWL_LLM_LOG"])
SAMPLE = ROOT / "examples" / "sample_ko.json"  # the fictional example
POSTING = ROOT / "tests" / "app" / "fixtures" / "posting_ko.md"  # a fictional posting
NOTES = ROOT / "tests" / "app" / "fixtures" / "notes_ko.txt"  # fictional notes for the stand-in
STATIC = ROOT / "apps" / "panel" / "static"  # the page's files


def q(s: str) -> str:
    """A job id in a path (Hangul is percent-encoded)."""
    return urllib.parse.quote(s)  # as the page's encodeURIComponent


class PanelCase(unittest.TestCase):
    """One server and one workspace per test class."""

    agent = "none"  # the backend the class runs with

    @classmethod  # once per class, so the tests share one workspace
    def setUpClass(cls):  # a fresh data folder and server for the class
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-test-"))  # data folder
        os.environ["OFFEROWL_DESKTOP"] = str(cls.tmp / "Desktop")  # exports land here
        if cls.agent == "standin":  # the class wants the stand-in agent
            os.environ["OFFEROWL_PANEL_AGENT"] = "standin"  # the card and the tasks use the stand-in
            os.environ.pop("OFFEROWL_PANEL_BACKEND", None)  # a class run earlier must not leak in
        else:  # the agent stays off
            os.environ.pop("OFFEROWL_PANEL_AGENT", None)  # a stand-in class run earlier must not leak in
            os.environ["OFFEROWL_PANEL_BACKEND"] = "none"  # no real CLI on this PC is called
        cls.srv = server.serve(0, data=cls.tmp / "data")  # a free port
        cls.port = cls.srv.server_address[1]  # the port it got
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()  # it answers while the tests run

    @classmethod  # once per class, after its last test
    def tearDownClass(cls):  # the server stopped and every trace removed
        cls.srv.shutdown()  # serve_forever returns
        cls.srv.server_close()  # the port is free again
        for k in ("OFFEROWL_PANEL_AGENT", "OFFEROWL_PANEL_BACKEND", "OFFEROWL_DESKTOP", "OFFEROWL_ALLOW_LOCAL_LINKS"):  # the class's own settings
            os.environ.pop(k, None)  # the next class starts clean
        shutil.rmtree(cls.tmp, ignore_errors=True)  # the temporary workspace goes

    def get(self, path):  # a read as the page makes it, answer parsed
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=20) as r:  # a hung server fails the test
            return json.loads(r.read())  # every API answer is JSON

    def raw_get(self, path):  # a read whose body is not JSON (a calendar file)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=20) as r:  # a hung server fails the test
            return r.headers.get("Content-Type"), r.read()  # its type and bytes

    def post(self, path, body, expect=200):  # a write as the page makes it, its status checked
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",  # as the page writes
                                     headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.port}"})
        try:  # a refused write raises HTTPError
            with urllib.request.urlopen(req, timeout=60) as r:  # a write also builds the new state
                out = json.loads(r.read())  # the answer with the new state
                self.assertEqual(expect, r.status)  # a 200 where a refusal was expected fails
                return out  # the caller reads its state
        except urllib.error.HTTPError as e:  # 4xx and 5xx answers land here
            body = e.read()  # read once: a second read is empty
            self.assertEqual(expect, e.code, body[:300])  # the answer is shown when the code is wrong
            return json.loads(body or b"{}")  # the error's own JSON

    def upload(self, path: pathlib.Path):  # a picked file, sent as the page sends it
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/materials", data=path.read_bytes(), method="POST",  # the raw file is the body
                                     headers={"Content-Type": "application/octet-stream", "X-File-Name": urllib.parse.quote(path.name)})
        with urllib.request.urlopen(req, timeout=20) as r:  # a hung server fails the test
            return json.loads(r.read())["material"]  # its record: id, kind, name

    def wait_task(self, key, timeout=90):  # tasks run in threads: poll until one ends
        end = time.time() + timeout  # give up after this
        while time.time() < end:  # until the deadline
            st = self.get("/api/v1/state")  # as the page polls it
            if (st["tasks"].get(key) or {}).get("state") in ("done", "error"):  # ended, either way
                return st  # the state at its end, for the asserts
            time.sleep(0.2)  # not a busy loop
        self.fail(f"task {key} did not end")  # a hung task fails instead of hanging the run

    def resume(self, lang="ko", job=""):  # the canvas's resume model
        return self.get(f"/api/v1/documents/resume?lang={lang}" + (f"&job={q(job)}" if job else ""))  # blocks and sentences

    def start_profile(self):  # the example read and kept, as the first run's main path does
        m = self.post("/api/v1/example", {})["material"]  # "Try with an example person"
        self.assertEqual("profile", m["kind"])  # recognized as an Offerowl profile
        st = self.wait_task("ingest")  # read without an agent
        self.post("/api/v1/facts/keep-all", {})  # "Keep all and show my resume"
        return st  # the state after reading


class TestFirstRun(PanelCase):
    """The first run with the agent off, then the canvas: evidence, edits, locks, history."""

    def test_1_onboarding_and_example(self):  # numbered: unittest runs them in name order
        st = self.get("/api/v1/state")  # a new workspace
        self.assertEqual({"done": False, "step": "welcome"}, {k: st["onboarding"][k] for k in ("done", "step")})  # the tour starts at the welcome
        self.post("/api/v1/onboarding", {"step": "files"})  # the steps are kept with the workspace
        self.assertEqual("files", self.get("/api/v1/state")["onboarding"]["step"])  # resumed there after a reload
        st = self.start_profile()  # the example read
        c = st["facts"]["counts"]  # what was found
        self.assertEqual(31, c["found"])  # every item of the example
        self.assertEqual(31, c["to_confirm"])  # nothing is kept before the person says so
        self.assertNotIn(str(self.tmp), json.dumps(st, ensure_ascii=False))  # no path of this PC in what the page gets
        self.post("/api/v1/onboarding", {"step": "preview", "done": True})  # the first resume is on screen
        self.assertTrue(self.get("/api/v1/state")["onboarding"]["done"])  # the workspace opens from now on

    def test_2_resume_model_and_evidence(self):  # the canvas's resume
        m = self.resume()  # the model
        self.assertEqual([], validate.check("resume", m))  # it fits its schema
        self.assertEqual([], m["missing"])  # nothing stops a resume
        self.assertEqual(0, m["counts"]["unsupported"])  # every sentence has evidence
        self.assertGreaterEqual(m["counts"]["sentences"], 30)  # every part of the example is drawn
        types = [b["type"] for b in m["blocks"]]  # the blocks in print order
        self.assertEqual(["headline", "intro"], types[:2])  # as src/resume_form.js prints them
        for want in ("cards", "highlights", "career", "education", "competencies", "skills", "role", "about", "motivation"):  # every part
            self.assertIn(want, types)  # drawn
        sid = next(k for k in m["sentences"] if k.startswith("roles.0.projects.0.summary"))  # a project's sentence
        rec = m["sentences"][sid]  # its record
        self.assertEqual("ok", rec["state"])  # as the evidence says
        self.assertEqual("sample_ko.json", rec["evidence"][0]["file"])  # the file it was read from, by name
        self.assertIn("승인 기능을 분리해", rec["evidence"][0]["quote"])  # the source's own words
        self.assertEqual("typed", m["sentences"]["summary.headline"]["state"])  # the headline is the person's own words
        prof = self.get("/api/v1/profile")  # the profile and its checks
        self.assertEqual([], prof["schema"])  # the built profile fits the profile schema
        self.assertEqual(json.loads(SAMPLE.read_text(encoding="utf-8"))["roles"], prof["profile"]["roles"])  # kept whole: the build gets exactly the example

    def test_3_edit_outside_the_evidence(self):  # an edit adds a number the evidence does not have
        m = self.resume()  # the model now
        sid = next(k for k in m["sentences"] if k.startswith("roles.0.projects.0.summary"))  # a project's sentence
        out = self.post("/api/v1/sentences/edit", {"sid": sid, "text": "승인 기능을 분리해 배포 시간을 40% 줄였다."})  # a new number
        self.assertEqual("unsupported", out["sentence"]["state"])  # marked
        self.assertEqual([{"code": "number", "words": "40%"}], out["sentence"]["issues"])  # and why
        jid = self.post("/api/v1/jobs", {"company": "감마클라우드", "posting": POSTING.read_text(encoding="utf-8")})["job"]  # a job to export for
        self.wait_task(f"analyze:{jid}")  # its analysis is one more undo step
        r = self.post("/api/v1/jobs/export", {"job": jid, "lang": "ko"}, expect=400)  # never exported
        self.assertEqual("unsupported:1", r["what"])  # one sentence without evidence
        steps = [s["label"]["code"] for s in self.get("/api/v1/history")["steps"][:3]]  # the newest three changes
        self.assertEqual(["undo_analysis", "undo_add_job", "undo_sentence"], steps)  # the analysis, the job, the edit
        self.post("/api/v1/history/undo", {"steps": 3})  # all three taken back at once
        self.assertEqual(0, self.resume()["counts"]["unsupported"])  # every sentence has evidence again
        out = self.post("/api/v1/sentences/edit", {"sid": sid, "text": "단일 애플리케이션에서 승인 기능을 떼어 내 ==승인 경로를 독립 배포 단위로== 만들었다."})  # reworded within the evidence
        self.assertEqual("edited", out["sentence"]["state"])  # changed, still covered
        self.post("/api/v1/undo", {})  # the example stays whole for the later tests

    def test_4_lock_and_history(self):  # a locked sentence keeps its words
        m = self.resume()  # the model now
        sid = next(k for k in m["sentences"] if k.startswith("competencies."))  # a strength
        self.post("/api/v1/sentences/lock", {"sid": sid, "locked": True})  # locked
        self.assertTrue(self.resume()["sentences"][sid]["locked"])  # shown as locked
        r = self.post("/api/v1/sentences/edit", {"sid": sid, "text": "다른 말"}, expect=400)  # an edit of a locked sentence
        self.assertEqual("locked", r["what"])  # refused, with the reason
        other = next(k for k in m["sentences"] if k.startswith("summary.cards."))  # a second sentence
        self.post("/api/v1/sentences/lock", {"sid": other, "locked": True})  # locked too
        steps = self.get("/api/v1/history")["steps"]  # the history, newest first
        self.assertEqual(["undo_lock_sentence", "undo_lock_sentence"], [s["label"]["code"] for s in steps[:2]])  # the two locks are the newest changes
        before = len(steps)  # how many steps
        out = self.post("/api/v1/history/undo", {"steps": 2, "newest": steps[1]["id"]})  # a page that listed the history before the second lock
        self.assertTrue(out.get("moved"))  # a later change came first
        self.assertEqual([], out["undone"])  # so nothing is taken back: two steps would now mean another two
        self.assertEqual(before, len(self.get("/api/v1/history")["steps"]))  # the history as it was
        out = self.post("/api/v1/history/undo", {"steps": 2, "newest": steps[0]["id"]})  # back two steps at once, from the list as it is
        self.assertEqual(2, len(out["undone"]))  # both taken back
        self.assertEqual(before - 2, len(self.get("/api/v1/history")["steps"]))  # gone from the history
        after = self.resume()["sentences"]  # the sentences now
        self.assertFalse(after[sid]["locked"] or after[other]["locked"])  # both locks went with them

    def test_5_unknown_sentence(self):  # a stale page's sentence id
        r = self.post("/api/v1/sentences/edit", {"sid": "roles.9.projects.9.summary.s0", "text": "x"}, expect=400)  # not in this resume
        self.assertEqual("sentence", r["what"])  # refused by name
        self.post("/api/v1/sentences/edit", {"sid": "../../x", "text": "x"}, expect=400)  # not an id at all

    def test_6_regenerate_needs_the_agent(self):  # the agent is off
        sid = next(k for k in self.resume()["sentences"] if k.startswith("roles.1.projects.0.summary"))  # a project's sentence
        r = self.post("/api/v1/sentences/regenerate", {"sid": sid})  # asked
        st = self.wait_task(r["task"])  # it ends at once
        self.assertEqual("agent_unavailable", st["tasks"][r["task"]]["error"]["code"])  # said plainly, with a fix on the page


class TestJobs(PanelCase):
    """A job with the agent off: the fit, tailoring all three documents, the interview board, a link."""

    def test_1_fit(self):  # a pasted posting
        self.start_profile()  # the example kept
        st = self.post("/api/v1/jobs", {"company": "감마클라우드", "role": "백엔드 플랫폼 엔지니어", "posting": POSTING.read_text(encoding="utf-8")})["state"]  # pasted
        jid = st["job"]  # in view
        folder = self.tmp / "data" / "workspace" / "jobs" / jid  # its folder
        self.assertTrue((folder / "posting.md").is_file())  # the posting is kept as pasted
        self.assertEqual([], validate.check_file("job", folder / "status.json"))  # its card fits the job schema
        st = self.wait_task(f"analyze:{jid}")  # ordered without an agent
        task = st["tasks"][f"analyze:{jid}"]  # the analysis
        self.assertEqual("done", task["state"])  # the words order the resume when no agent is on
        self.assertEqual("words", task["result"]["by"])  # and say so
        self.assertEqual(["Platform", "Data", "Observability"], task["result"]["skillsFocus"])  # the groups the covered lines cite
        self.assertEqual([], validate.check_file("plan", folder / "plan.json"))  # the plan fits its schema
        f = self.get(f"/api/v1/jobs/{q(jid)}/fit")  # the fit, line by line
        self.assertEqual([], validate.check("fit", f))  # it fits its schema
        self.assertEqual(8, len(f["lines"]))  # every duty, requirement and preferred line of the posting: 3, 3 and 2
        self.assertEqual(sum(f["counts"].values()), len(f["lines"]))  # each line rated once
        self.assertTrue(0 < f["score"] < 100)  # a score between the ends
        self.assertIn("백엔드 개발 경력 3년 이상", f["gaps"])  # the line no evidence covers is a gap
        strong = [x for x in f["lines"] if x["rating"] == "strong"]  # covered lines
        self.assertTrue(strong and all(x["evidence"] for x in strong))  # each with its evidence
        from apps.api import fit as F  # the fit itself, worked out with and without the profile's shared units
        api = type(self).srv.RequestHandlerClass.panel  # the panel's API
        prof, posting = api.facts.profile(), POSTING.read_text(encoding="utf-8")
        alone = F.compute(prof, posting, evmap=api.facts.evidence(), cands=api.facts.candidates())  # units made for this call
        shared = [F.compute(prof, posting, evmap=api.facts.evidence(), cands=api.facts.candidates(), profile_key="test-profile") for _ in range(2)]  # made once, then shared
        self.assertEqual([alone, alone], shared)  # the same fit, line by line, whichever way
        self.assertIn(("test-profile", alone["lang"]), F.PREPARED)  # kept for the next job's fit
        m = self.resume(job=jid)  # the resume for the job
        skills = next(b for b in m["blocks"] if b["type"] == "skills")["rows"]  # its skills table
        self.assertEqual(["Platform", "Data", "Observability"], [r["category"] for r in skills[:3]])  # the job's groups lead
        self.assertTrue(all(r["focus"] for r in skills[:3]))  # marked as the job's focus

    def test_2_tailor(self):  # one action for all three documents
        jid = self.get("/api/v1/state")["job"]  # the job above
        r = self.post("/api/v1/jobs/tailor", {"job": jid, "lang": "ko"})  # tailored
        st = self.wait_task(r["task"], 120)  # ends
        t = st["tasks"][r["task"]]  # its record
        self.assertEqual({"resume": "done", "cover": "needs_agent", "interview": "done"}, t["parts"])  # the letter needs the agent
        b = self.get(f"/api/v1/jobs/{q(jid)}/interview")  # the studio's board
        self.assertEqual([], validate.check("interview", b))  # it fits its schema
        self.assertTrue(b["ready"])  # the kit folder exists
        kinds = [c["kind"] for c in b["categories"]]  # the question map's categories
        for want in ("posting", "resume", "behavioral", "company", "opening"):  # the kinds a job always has
            self.assertIn(want, kinds)  # on the board
        self.assertEqual(b["counts"]["questions"], sum(len(c["questions"]) for c in b["categories"]))  # every question on it
        self.assertTrue(b["practice"]["url"].endswith("#practice"))  # practice opens at the kit's own anchor
        c = self.get(f"/api/v1/documents/cover?job={q(jid)}&lang=ko")  # the cover letter
        self.assertEqual("none", c["state"])  # not drafted without the agent

    def test_3_link(self):  # a posting from a link
        page = POSTING.read_text(encoding="utf-8").splitlines()  # the fictional posting as a web page
        body = ("<html><head><title>채용</title><script>var x = 1;</script></head><body><nav>메뉴</nav><h1>" + page[0] + "</h1><ul>" +
                "".join(f"<li>{ln[2:]}</li>" for ln in page if ln.startswith("- ")) + "</ul></body></html>").encode("utf-8")  # list items stay list items

        class Page(http.server.BaseHTTPRequestHandler):  # one page
            def do_GET(self):  # noqa: N802  the page
                self.send_response(200)  # found
                self.send_header("Content-Type", "text/html; charset=utf-8")  # a web page
                self.end_headers()  # the body follows
                self.wfile.write(body)  # the posting

            def log_message(self, *_):  # quiet
                pass  # no request lines

        web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)  # a local site
        threading.Thread(target=web.serve_forever, daemon=True).start()  # serving
        try:
            os.environ["OFFEROWL_ALLOW_LOCAL_LINKS"] = "1"  # a test may fetch from this PC
            r = self.post("/api/v1/jobs", {"url": f"http://127.0.0.1:{web.server_address[1]}/job"})  # the link alone
            jid = r["job"]  # the new job
            posting = (self.tmp / "data" / "workspace" / "jobs" / jid / "posting.md").read_text(encoding="utf-8")  # what was kept
            self.assertIn("- 결제 승인과 정산 백엔드를 설계하고 운영한다", posting)  # the list item as a list item
            self.assertNotIn("var x", posting)  # no script
            self.assertNotIn("메뉴", posting)  # no navigation
            self.assertEqual(f"http://127.0.0.1:{web.server_address[1]}/job", next(j for j in r["state"]["jobs"] if j["id"] == jid)["url"])  # the link is kept
        finally:
            os.environ.pop("OFFEROWL_ALLOW_LOCAL_LINKS", None)  # back to the rule
            web.shutdown()  # the site stops
            web.server_close()  # and its socket goes
        r = self.post("/api/v1/jobs", {"url": f"http://127.0.0.1:{web.server_address[1]}/job"}, expect=400)  # this PC is never fetched otherwise
        self.assertEqual("bad_link", r["what"])  # refused by name
        r = self.post("/api/v1/jobs", {"url": "file:///etc/passwd"}, expect=400)  # not a web link
        self.assertEqual("bad_link", r["what"])  # refused by name


class TestExampleLanguage(PanelCase):
    def test_the_example_person_writes_in_the_pages_language(self):
        name = self.post("/api/v1/example", {"lang": "en"})["material"]["name"]  # a person using the panel in English
        self.assertEqual(name, "sample_full_en.json")


class TestGeneralEdition(PanelCase):
    def test_pdfs_need_no_job(self):  # a person who has not picked a posting yet can still have a PDF of their resume
        self.post("/api/v1/example", {})  # the fictional person
        self.wait_task("ingest")
        self.post("/api/v1/facts/keep-all", {})
        state = self.get("/api/v1/state")
        self.assertEqual(state["general"]["id"], "-general")
        self.assertEqual(state["general"]["builds"], {})  # nothing made yet
        self.assertEqual(state["jobs"], [])  # and it is no job on the board
        started = self.post("/api/v1/jobs/build", {"job": "-general", "lang": "ko", "theme": "navy", "maxPages": 3, "cover": False})
        self.assertTrue(started["started"])  # the same build as a job's
        state = self.wait_task("build:-general", 300)
        self.assertEqual(state["jobs"], [])  # still none
        if not state["engine"]:  # where the typesetting can run, the PDFs are there
            self.assertEqual(state["tasks"]["build:-general"]["state"], "done", state["tasks"]["build:-general"])
            self.assertEqual(state["general"]["builds"]["ko"]["pages"], 2)


class TestTracker(PanelCase):
    """The board, the timeline and reminders."""

    def test_rounds_and_every_stages_day(self):
        jid = self.post("/api/v1/jobs", {"company": "델타페이먼츠", "posting": POSTING.read_text(encoding="utf-8")})["job"]  # a card
        self.post("/api/v1/tracker/next", {"job": jid})  # preparing -> submitted
        # an interview round: its kind, day and time, the questions asked, notes
        rec = self.post("/api/v1/tracker/round", {"job": jid, "kind": "first", "at": "2026-11-12T14:00", "asked": "가장 어려웠던 장애\n왜 이 회사", "notes": "설계 질문이 길었다"})["round"]
        self.assertEqual(("i1", "first", "2026-11-12T14:00"), (rec["id"], rec["kind"], rec["at"]))
        call = self.post("/api/v1/tracker/round", {"job": jid, "kind": "call", "at": "2026-11-05"})["round"]  # an earlier call, added later
        job = next(j for j in self.get("/api/v1/state")["jobs"] if j["id"] == jid)
        self.assertEqual(["i2", "i1"], [r["id"] for r in job["rounds"]])  # in the order they happen
        self.assertEqual("submitted", job["stage"])  # a round never moves the card by itself
        self.post("/api/v1/tracker/round", {"job": jid, "id": "i1", "notes": "다음엔 숫자를 먼저"})  # changed in place
        job = next(j for j in self.get("/api/v1/state")["jobs"] if j["id"] == jid)
        self.assertEqual("다음엔 숫자를 먼저", next(r for r in job["rounds"] if r["id"] == "i1")["notes"])
        self.assertEqual("가장 어려웠던 장애\n왜 이 회사", next(r for r in job["rounds"] if r["id"] == "i1")["asked"])  # the rest kept
        for bad in ({"kind": "chat", "at": "2026-11-12"}, {"kind": "first", "at": "tomorrow"}, {"id": "i9", "notes": "x"}):   # an unknown kind, no day, no such round
            self.post("/api/v1/tracker/round", {"job": jid, **bad}, expect=400)
        kinds = [(e["kind"], e.get("round")) for e in self.get("/api/v1/tracker")["timeline"] if e.get("job") == jid]
        self.assertIn(("round", "first"), kinds)  # on the timeline, each on its day
        self.assertIn(("round", "call"), kinds)
        funnel = self.get("/api/v1/insights")["funnel"]
        self.assertGreaterEqual(funnel["interview"], 1)  # a recorded round is an interview reached, whatever the column
        # every stage's own day, as the progress tab edits them
        self.post("/api/v1/tracker/edit", {"job": jid, "dates": {"preparing": "2026-10-01", "submitted": "2026-10-05", "interview": "nope"}})
        job = next(j for j in self.get("/api/v1/state")["jobs"] if j["id"] == jid)
        self.assertEqual("2026-10-01", job["dates"]["preparing"])
        self.assertEqual("2026-10-05", job["dates"]["submitted"])
        self.assertNotIn("nope", job["dates"].values())  # what is no day is left out
        self.assertEqual({"preparing": "2026-10-01", "submitted": "2026-10-05"}, job["days"])  # the days that count
        self.assertEqual([], validate.check_file("job", self.tmp / "data" / "workspace" / "jobs" / jid / "status.json"))  # still fits its schema
        self.assertIsNone(self.post("/api/v1/tracker/round", {"job": jid, "id": call["id"], "remove": True})["round"])  # off the card
        self.post("/api/v1/undo", {})  # and back
        job = next(j for j in self.get("/api/v1/state")["jobs"] if j["id"] == jid)
        self.assertEqual(2, len(job["rounds"]))

    def test_posting_pasted_again(self):
        """A job whose posting the reading found no duty lines in takes the part with them, pasted again from the Fit tab:
        the posting is replaced in one undo step and read again; a next step and a reminder keep a long meeting link whole."""
        jid = self.post("/api/v1/jobs", {"company": "감마클라우드", "role": "백엔드", "posting": "감마클라우드 백엔드 엔지니어를 찾습니다. 자세한 내용은 면접에서."})["job"]
        posting = self.tmp / "data" / "workspace" / "jobs" / jid / "posting.md"
        first = posting.read_text(encoding="utf-8")
        self.post("/api/v1/jobs/posting", {"job": jid, "posting": "짧음"}, expect=400)  # too short to be a posting
        out = self.post("/api/v1/jobs/posting", {"job": jid, "posting": POSTING.read_text(encoding="utf-8")})
        self.assertEqual(jid, out["job"])
        self.assertEqual(POSTING.read_text(encoding="utf-8").strip(), posting.read_text(encoding="utf-8").strip())  # replaced as pasted
        self.post("/api/v1/undo", {})  # and back
        self.assertEqual(first, posting.read_text(encoding="utf-8"))
        link = "https://teams.microsoft.com/l/meetup-join/" + "x" * 230  # a long-form meeting link
        st = self.post("/api/v1/tracker/edit", {"job": jid, "next": "2차 면접 " + link})["state"]
        self.assertIn(link, next(j for j in st["jobs"] if j["id"] == jid)["next"])  # whole, not cut at 200
        rec = self.post("/api/v1/reminders", {"job": jid, "at": "2099-01-01T09:30", "text": "접속 " + link})["reminder"]
        self.assertIn(link, rec["text"])

    def test_board_timeline_reminders(self):
        jid = self.post("/api/v1/jobs", {"company": "감마클라우드", "posting": POSTING.read_text(encoding="utf-8")})["job"]  # a card
        st = self.post("/api/v1/tracker/next", {"job": jid})["state"]  # preparing -> submitted
        self.assertEqual("submitted", next(j for j in st["jobs"] if j["id"] == jid)["stage"])  # one column right
        st = self.post("/api/v1/tracker/edit", {"job": jid, "next": "서류 결과 확인"})["state"]  # the next step typed
        self.assertEqual("서류 결과 확인", next(j for j in st["jobs"] if j["id"] == jid)["next"])  # saved on the card
        today = st["today"]  # the board's day
        rec = self.post("/api/v1/reminders", {"job": jid, "at": today, "text": "결과 메일 확인"})["reminder"]  # due today
        self.post("/api/v1/reminders", {"job": jid, "at": "2099-01-01T09:30", "text": "먼 훗날"})  # not due
        due = self.get("/api/v1/reminders/due")["due"]  # what is due now
        self.assertEqual(["결과 메일 확인"], [d["text"] for d in due])  # only today's
        tr = self.get("/api/v1/tracker")  # the board and the timeline
        kinds = [(e["kind"], e.get("stage") or e.get("text")) for e in tr["timeline"]]  # in order
        self.assertEqual([("stage", "preparing"), ("stage", "submitted"), ("reminder", "결과 메일 확인"), ("reminder", "먼 훗날")], kinds)  # oldest first
        ctype, ics = self.raw_get("/api/v1/reminders.ics")  # the calendar file
        self.assertTrue(ctype.startswith("text/calendar"))  # opened by the calendar
        self.assertIn("SUMMARY:감마클라우드: 결과 메일 확인", ics.decode("utf-8"))  # each open reminder
        self.assertIn("DTSTART:20990101T093000", ics.decode("utf-8"))  # a time when it has one
        self.post("/api/v1/tracker/edit", {"job": jid, "stage": "result", "result": "rejected"})  # the application ended
        self.assertEqual([], self.get("/api/v1/reminders/due")["due"])  # its reminders ask nothing more
        self.post("/api/v1/undo", {})  # back where it was
        self.assertEqual(["결과 메일 확인"], [d["text"] for d in self.get("/api/v1/reminders/due")["due"]])  # due again
        self.post("/api/v1/reminders", {"job": jid, "id": rec["id"], "done": True})  # dealt with
        self.assertEqual([], self.get("/api/v1/reminders/due")["due"])  # no longer due
        self.post("/api/v1/reminders", {"job": jid, "at": "tomorrow", "text": "x"}, expect=400)  # not a date
        self.assertEqual([], validate.check_file("job", self.tmp / "data" / "workspace" / "jobs" / jid / "status.json"))  # the card still fits its schema
        for _ in range(5):  # the reminders, the next step and the move taken back
            self.post("/api/v1/undo", {})  # one step each
        st = self.get("/api/v1/state")  # the card now
        self.assertEqual("preparing", next(j for j in st["jobs"] if j["id"] == jid)["stage"])  # in the first column again


class TestStandin(PanelCase):
    """The agent's steps through the stand-in, on the real code path of src/ingest.py, src/draft.py and src/llm.py."""

    agent = "standin"  # the agent's steps run, answered by the stand-in

    def test_ingest_analysis_regenerate(self):  # notes read, a posting matched, a sentence rewritten
        m = self.upload(NOTES)  # plain notes: read by the (stand-in) agent
        self.post("/api/v1/materials/read", {"ids": [m["id"]]})  # the stand-in reads them
        st = self.wait_task("ingest")  # the reading ends
        rows = self.get("/api/v1/facts")["rows"]  # the facts read (the state carries only their counts)
        kinds = sorted({r["kind"] for r in rows})  # every kind found
        self.assertEqual(["certificate", "education", "other", "project", "role"], kinds)  # each kind the notes hold, none missed
        self.assertTrue(all(r["source"]["name"] == "notes_ko.txt" for r in rows))  # a name, not a path
        self.post("/api/v1/facts/keep-all", {})  # all kept
        self.post("/api/v1/details", {"fields": {"name": "홍길동", "email": "gildong@example.com"}})  # the notes give no name or email
        self.assertEqual([], self.get("/api/v1/state")["problems"])  # nothing stops a resume now
        m2 = self.upload(SAMPLE)  # a profile beside the notes: its skills give the analysis groups to pick
        self.post("/api/v1/materials/read", {"ids": [m2["id"]]})  # the profile is read as it is
        self.wait_task("ingest")  # the second reading ends
        self.post("/api/v1/facts/keep-all", {})  # its facts kept too
        model = self.resume()  # the resume of both
        notes_sid = next((k for k, v in model["sentences"].items() if any(e.get("file") == "notes_ko.txt" for e in v["evidence"])), None)  # a sentence read from the notes
        self.assertIsNotNone(notes_sid)  # the notes' facts are on the canvas with their file
        jid = self.post("/api/v1/jobs", {"company": "감마클라우드", "posting": POSTING.read_text(encoding="utf-8")})["job"]  # its analysis starts at once
        st = self.wait_task(f"analyze:{jid}")  # by words
        self.assertEqual("words", next(j for j in st["jobs"] if j["id"] == jid)["plan"]["by"])  # adding a job sends nothing to the agent
        self.post("/api/v1/jobs/analyze", {"job": jid})  # asked for
        st = self.wait_task(f"analyze:{jid}")  # the stand-in matched it
        plan = next(j for j in st["jobs"] if j["id"] == jid)["plan"]  # the analysis the page shows
        log = (self.tmp / "data" / "logs" / "panel.log")  # why the agent stopped, when it did: shown with a failure
        why = log.read_text(encoding="utf-8", errors="replace")[-1500:] if log.is_file() else ""
        self.assertEqual("agent", plan["by"], f"{st['tasks'].get(f'analyze:{jid}')}\n{why}")  # made by the agent this time
        self.assertEqual(["Platform", "Data", "Observability"], plan["skillsFocus"])  # the groups the posting names
        sid = next(k for k in model["sentences"] if k.startswith("roles.") and ".summary.s" in k and model["sentences"][k]["evidence"][0].get("file") == "sample_ko.json")  # an example sentence
        r = self.post("/api/v1/sentences/regenerate", {"sid": sid})  # new words from its evidence
        st = self.wait_task(r["task"])  # the stand-in answered
        t = st["tasks"][r["task"]]  # the task's record
        self.assertEqual("done", t["state"], t)  # it passed the fact check
        rec = self.resume()["sentences"][sid]  # the sentence now
        self.assertNotEqual("unsupported", rec["state"])  # still within its evidence
        self.assertEqual(t["result"]["text"], rec["text"].replace("==", ""))  # the new words are on the canvas

    def test_standin_rules(self):  # the stand-in's own reader, without the server
        out = standin_facts("<<<\n과제: 알파페이 | 2023.01 ~ 2023.09 | 결제 승인 | 승인을 분리했다\n>>>")["facts"]  # one line in the notes' format
        self.assertEqual("project", out[0]["kind"])  # 과제 reads as a project
        self.assertIn(out[0]["quote"], "과제: 알파페이 | 2023.01 ~ 2023.09 | 결제 승인 | 승인을 분리했다")  # the quote is taken from the text


class TestSafety(PanelCase):
    """The API refuses a foreign Host or Origin, a form post, a bad upload, unknown paths and an id that leaves."""

    def raw(self, method, path, headers, body=b""):  # a request with exactly these headers
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)  # urllib would set Host itself
        c.request(method, path, body=body, headers=headers)  # a Host given here replaces the default one
        r = c.getresponse()  # the answer
        return r.status, r.read()  # the status is what the tests check

    def test_host_header(self):  # a foreign name pointed at this PC
        for path in ("/api/v1/state", "/"):  # the API and the page
            status, _ = self.raw("GET", path, {"Host": "evil.example:80"})  # DNS rebinding
            self.assertEqual(403, status, path)  # refused before any route

    def test_foreign_origin(self):  # a write from another site's page
        status, _ = self.raw("POST", "/api/v1/undo", {"Host": f"127.0.0.1:{self.port}", "Origin": "http://evil.example",  # right host, foreign page
                                                      "Content-Type": "application/json"}, b"{}")
        self.assertEqual(403, status)  # refused, nothing undone

    def test_another_sites_page_gets_no_work_done(self):
        # an <img> or a fetch on another site's page, pointed at this panel: the answer stays unread there, but a backup would
        # be zipped, a kit server started, the agents' commands run; refused. The panel itself still opens from a link.
        host = {"Host": f"127.0.0.1:{self.port}"}
        for path in ("/api/v1/state", "/api/v1/workspace/backup", "/api/v1/agent?refresh=1", "/kit/no-such-job/"):
            for extra in ({"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image"},  # an <img>
                          {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"},  # another port of this PC
                          {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},  # a link to the API
                          {"Origin": "http://evil.example"}):  # a fetch that names its page
                status, body = self.raw("GET", path, {**host, **extra})
                self.assertEqual((403, "cross_site"), (status, json.loads(body)["error"]), (path, extra))
        status, _ = self.raw("GET", "/", {**host, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
        self.assertEqual(200, status)  # the panel opened from a link elsewhere
        for extra in ({"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}, {"Sec-Fetch-Site": "none"}, {}):
            status, _ = self.raw("GET", "/api/v1/state", {**host, **extra})
            self.assertEqual(200, status, extra)  # the panel's own page, a typed address, a tool

    def test_a_client_that_stops_sending_lets_its_thread_go(self):
        # a client that says a length and sends less would hold a request thread for as long as it kept the socket open
        import socket  # a request no client library would send
        import time  # how long the server waited
        handler = type(self).srv.RequestHandlerClass
        before = handler.timeout
        handler.timeout = 1  # the 120 s of the panel, shortened for the test
        self.addCleanup(setattr, handler, "timeout", before)
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        self.addCleanup(s.close)
        s.sendall((f"POST /api/v1/undo HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Type: application/json\r\n"
                   "Content-Length: 1000\r\n\r\n{").encode())  # 1 byte of the 1000 it promised, then nothing
        t0 = time.monotonic()
        while s.recv(4096):  # the answer, if any, then the closed connection
            pass
        self.assertLess(time.monotonic() - t0, 8)  # let go after its timeout, not held

    def test_form_post(self):  # a type a plain HTML form can send
        status, _ = self.raw("POST", "/api/v1/undo", {"Host": f"127.0.0.1:{self.port}", "Content-Type": "text/plain"}, b"{}")  # needs no preflight
        self.assertEqual(403, status)  # a plain form post from another page cannot write

    def test_upload_needs_its_type(self):  # an upload sent with a form's type
        for path in ("/api/v1/materials",):  # the one upload path
            status, _ = self.raw("POST", path, {"Host": f"127.0.0.1:{self.port}", "Content-Type": "text/plain", "X-File-Name": "a.txt"}, b"hello")  # not raw bytes
            self.assertEqual(403, status, path)  # nothing is kept

    def test_a_refusal_reads_the_body_it_refuses(self):
        # a socket closed with bytes unread is reset: on Windows the reset beat the answer, and the client saw a dropped
        # connection instead of the 403
        status, _ = self.raw("POST", "/api/v1/materials", {"Host": f"127.0.0.1:{self.port}", "Content-Type": "text/plain",
                                                           "X-File-Name": "a.txt"}, b"x" * 600_000)  # still on its way when refused
        self.assertEqual(403, status)  # the refusal arrives

    def test_empty_upload(self):
        status, body = self.raw("POST", "/api/v1/materials", {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/octet-stream",
                                                              "X-File-Name": "empty.txt", "Content-Length": "0"})  # nothing in it
        self.assertEqual((400, "empty"), (status, json.loads(body)["error"]))  # said as empty, not as too large

    def test_unknown_paths(self):
        status, body = self.raw("POST", "/api/v1/nothing", {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}, b"{}")
        self.assertEqual((404, "not_found"), (status, json.loads(body)["error"]))  # an unknown write, not a server error
        status, _ = self.raw("GET", "/api/v1/nothing", {"Host": f"127.0.0.1:{self.port}"})  # an unknown read
        self.assertEqual(404, status)  # not found
        status, _ = self.raw("GET", "/api/v1/jobs/..%2F..%2Fsettings/fit", {"Host": f"127.0.0.1:{self.port}"})  # aims above jobs/
        self.assertIn(status, (400, 404))  # the id check refuses it

    def test_doc_path_cannot_leave(self):  # an encoded ../ in the job id
        for path in ("/doc/..%2F..%2Fsettings/ko/resume.pdf", "/api/v1/jobs/..%2F..%2Fsettings/files/ko/resume.pdf"):  # the old path and the new one
            status, _ = self.raw("GET", path, {"Host": f"127.0.0.1:{self.port}"})  # aims above jobs/
            self.assertIn(status, (400, 404), path)  # the id check refuses it

    def test_page_and_health(self):  # the page, its files and the desktop app's check
        status, body = self.raw("GET", "/", {"Host": f"127.0.0.1:{self.port}"})  # the page
        self.assertEqual(200, status)  # served
        self.assertIn(b"/static/app.js", body)  # with its scripts
        status, body = self.raw("GET", "/health", {"Host": f"127.0.0.1:{self.port}"})  # the desktop app's check
        self.assertEqual({"ok": True, "app": "offerowl", "api": 1}, json.loads(body))  # names Offerowl
        status, _ = self.raw("GET", "/static/../server.py", {"Host": f"127.0.0.1:{self.port}"})  # out of static/
        self.assertEqual(404, status)  # never served


class TestClientAndSchemas(unittest.TestCase):
    """The API in this process (what the command line wraps) and the data model."""

    def test_client(self):
        from apps.api.client import Client  # the in-process API
        os.environ["OFFEROWL_PANEL_BACKEND"] = "none"  # no real CLI is called
        try:
            with tempfile.TemporaryDirectory() as d:  # a data folder of its own
                c = Client(pathlib.Path(d))  # no server, no port
                rec = c.post("/api/v1/materials/file", {"path": str(SAMPLE)})["material"]  # a file from disk, the command line's way in
                c.post("/api/v1/materials/read", {"ids": [rec["id"]]})  # read
                self.assertEqual("done", c.wait("ingest")["state"])  # through the same table as the panel
                self.assertNotIn("state", c.post("/api/v1/facts/keep-all", {}))  # writes leave the state out unless asked
                self.assertEqual(0, c.get("/api/v1/documents/resume", lang="ko")["counts"]["unsupported"])  # the same model the canvas draws
                with self.assertRaises(RuntimeError):  # a refusal is an exception with its code
                    c.post("/api/v1/jobs", {"posting": "short"})  # too short
        finally:
            os.environ.pop("OFFEROWL_PANEL_BACKEND", None)  # the next class starts clean

    def test_a_shell_write_waits_for_its_tasks(self):
        import subprocess  # the command line as a person runs it: its own process
        with tempfile.TemporaryDirectory() as d:  # a data folder of its own
            posting = (ROOT / "tests" / "app" / "fixtures" / "posting_ko.md").read_text(encoding="utf-8")  # a fictional posting
            env = {**os.environ, "OFFEROWL_PANEL_BACKEND": "none", "PYTHONDONTWRITEBYTECODE": "1"}  # no agent
            r = subprocess.run([sys.executable, "-m", "apps.api", "post", "/api/v1/jobs", json.dumps({"posting": posting}), "--data", d],
                               cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)  # one write, then the process ends
            self.assertEqual(0, r.returncode, r.stderr)
            out = json.loads(r.stdout)  # the answer with the tasks it started
            self.assertIn("done", out["tasks"].values())  # the posting's analysis ended before the command did
            self.assertTrue(list(pathlib.Path(d).glob("workspace/jobs/*/plan.json")), "the analysis was cut off")  # and left its plan

    def test_a_folder_the_system_refuses_is_not_named(self):
        from unittest import mock  # the system's refusal, made up
        from apps.api.client import Client  # the API in this process
        with tempfile.TemporaryDirectory() as d:
            c = Client(pathlib.Path(d))
            denied = PermissionError(13, "Permission denied", "/home/someone/Desktop/resume.pdf")  # what the system says
            with mock.patch.object(c.api, "set_settings", side_effect=denied):
                code, body, _ = c.router.handle("POST", "/api/v1/settings", {}, {"lang": "en"})
            self.assertEqual(500, code)  # a general error
            self.assertNotIn("/home/someone", json.dumps(body))  # the path stays in the log
            with mock.patch.object(c.api, "set_settings", side_effect=PermissionError("locked")):  # a rule of the API's own
                self.assertEqual((403, {"error": "locked"}), c.router.handle("POST", "/api/v1/settings", {}, {"lang": "en"})[:2])

    def test_examples_fit_their_schemas(self):
        for f in ("sample_ko.json", "sample_full_ko.json", "sample_full_en.json"):  # the fictional profiles
            self.assertEqual([], validate.check_file("profile", ROOT / "examples" / f), f)  # each one fits
        for f in ("cover_ko.json", "cover_en.json"):  # the fictional cover letters
            self.assertEqual([], validate.check_file("cover", ROOT / "examples" / "cover" / f), f)  # each one fits

    def test_schemas_find_planted_problems(self):  # a schema that passes everything proves nothing
        self.assertTrue(validate.check("profile", {"schema": "x", "person": {"name": 3}}))  # wrong format name and type
        self.assertTrue(validate.check("job", {"id": "Bad Id", "stage": "nowhere"}))  # a made-up id and stage
        self.assertTrue(validate.check("fit", {"score": 200, "lines": [], "gaps": [], "counts": {"strong": 0, "weak": 0, "none": 0}}))  # a score over 100
        self.assertTrue(validate.check("resume", {"kind": "resume"}))  # missing parts


class TestOnePortOneServer(unittest.TestCase):
    """A port another server listens on stops the panel's start with words, not a traceback, before anything else runs; the
    servers hold their port alone (src/ownport.py: on Windows SO_REUSEADDR would let two share it)."""

    def test_a_taken_port_is_said_in_words(self):
        import contextlib  # the error stream, read
        import io  # in memory
        sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules
        from ownport import Server  # the class every server binds with
        held = Server(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)  # a server on a free port
        try:
            port = held.server_address[1]  # its port
            with self.assertRaises(OSError):  # a second one is refused, as on every system
                Server(("127.0.0.1", port), http.server.BaseHTTPRequestHandler).server_close()
            tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-port-"))  # a data folder that must stay untouched
            err = io.StringIO()
            from unittest import mock  # main() points the agent's call log at its data folder: put back after
            llm = sys.modules.get("llm")  # src/llm.py, when a test before this one loaded it
            log = getattr(llm, "LOG", None)  # where it writes now
            with contextlib.redirect_stderr(err), mock.patch.dict(os.environ):  # the environment as it was, afterwards
                code = server.main(["--port", str(port), "--data", str(tmp / "data")])  # the panel on that port
            if llm is not None:
                llm.LOG = log  # the other tests' log place
            self.assertEqual(2, code)  # a failed start
            self.assertIn(f"port {port} is in use", err.getvalue())  # why
            self.assertIn("--port", err.getvalue())  # and what to do
            self.assertFalse((tmp / "data" / "workspace").exists())  # no workspace was opened, no agent asked
            shutil.rmtree(tmp, ignore_errors=True)
        finally:
            held.server_close()


class TestOwnPortOnWindows(unittest.TestCase):
    """The class as Windows' Python builds it (this test runs on any system): SO_REUSEADDR off and its own bind, which sets
    SO_EXCLUSIVEADDRUSE. On Windows itself a second bind of a port in use then fails with WinError 10048 (measured with
    Windows' own Python; Linux refuses it either way, so the test above cannot tell the two classes apart there)."""

    def test_the_windows_class_holds_its_port_alone(self):
        import importlib  # the module built again under another platform's name
        from unittest import mock  # that name
        sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules
        import ownport  # src/ownport.py
        try:
            with mock.patch.object(sys, "platform", "win32"):  # as Windows' Python sees itself
                win = importlib.reload(ownport)
                self.assertFalse(win.Server.allow_reuse_address)  # never SO_REUSEADDR there
                self.assertIn("server_bind", win.Server.__dict__)  # its own bind: SO_EXCLUSIVEADDRUSE first
            self.assertIn("SO_EXCLUSIVEADDRUSE", (ROOT / "src" / "ownport.py").read_text(encoding="utf-8"))
        finally:
            importlib.reload(ownport)  # this system's class again, for every later test


class TestServingLimit(unittest.TestCase):
    """Every server binds through src/ownport.py, which serves at most max_threads requests at once: one more connection
    waits for a free slot, and past slot_wait it is answered 503 with Retry-After at once, without a thread; a slot that
    frees serves the next."""

    def test_the_cap_comes_from_the_environment_within_its_bounds(self):
        sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules
        import ownport  # the cap's rule
        for value, want in (("", 64), ("16", 16), ("4", 4), ("3", 64), ("2000", 64), ("many", 64)):
            with mock.patch.dict(os.environ, {"OFFEROWL_MAX_REQUESTS": value}):
                self.assertEqual(want, ownport.cap_from_env(), value)
        answer = ownport.busy_answer(2)
        head, body = answer.split(b"\r\n\r\n", 1)
        self.assertTrue(head.startswith(b"HTTP/1.1 503 "))
        self.assertIn(b"Retry-After: 2", head)
        self.assertIn(b"Content-Length: %d" % len(body), head)  # the length said is the length sent
        self.assertEqual({"error": "busy"}, json.loads(body))

    @unittest.skipUnless(sys.platform.startswith("linux"), "measured on Linux, whose system queue the burst waits in")
    def test_a_burst_waits_in_the_system_s_queue_instead_of_being_dropped(self):
        """200 clients at once against a server that answers in no time: with Python's own queue of 5 most of them were
        dropped and asked again a second, then 3, 7 and 15 seconds later (300 at once took 27 s); with the server's queue
        every one is answered at once."""
        import concurrent.futures  # the clients
        sys.path.insert(0, str(ROOT / "src"))
        from ownport import Server  # the class every server binds with
        self.assertGreaterEqual(Server.request_queue_size, 128)

        class Quick(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):  # quiet
                pass

        srv = Server(("127.0.0.1", 0), Quick)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_address[1]}/"
        go = threading.Event()

        def one(_):
            go.wait()
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.status
        with concurrent.futures.ThreadPoolExecutor(200) as pool:
            futures = [pool.submit(one, i) for i in range(200)]
            time.sleep(0.5)  # every client waiting at the start line
            t0 = time.monotonic()
            go.set()
            codes = [f.result() for f in futures]
        self.assertEqual([200] * 200, codes)  # every one answered
        # measured on this burst: 0.2 s with the server's queue, 7.4 s with Python's 5 (the clients' retries after 1 and 3 s)
        self.assertLess(time.monotonic() - t0, 3)

    def test_past_the_limit_a_connection_waits_then_is_told_to_try_again(self):
        import socket  # requests by hand
        import threading  # the server beside the test
        import time  # how long it waited
        sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules
        from ownport import Server  # the class every server binds with
        go = threading.Event()  # lets the held request finish

        class Held(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                go.wait(10)  # holds its slot until the test lets go
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):  # quiet
                pass

        class One(Server):  # the limit, made small
            max_threads = 1
            slot_wait = 0.5

        srv = One(("127.0.0.1", 0), Held)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.addCleanup(go.set)
        port = srv.server_address[1]
        first = socket.create_connection(("127.0.0.1", port), timeout=10)  # takes the one slot
        self.addCleanup(first.close)
        first.sendall(b"GET / HTTP/1.0\r\n\r\n")
        time.sleep(0.3)  # its thread is serving it
        second = socket.create_connection(("127.0.0.1", port), timeout=10)  # one more than the limit
        self.addCleanup(second.close)
        second.sendall(b"GET / HTTP/1.0\r\n\r\n")
        t0 = time.monotonic()
        got = b""
        while True:  # the whole answer, until the server closes
            part = second.recv(1000)
            if not part:
                break
            got += part
        self.assertTrue(got.startswith(b"HTTP/1.1 503 "), got)  # answered, not dropped: the page tries again
        self.assertIn(b"Retry-After: 2", got)
        self.assertTrue(got.endswith(b'{"error": "busy"}'), got)
        self.assertLess(time.monotonic() - t0, 5)  # after slot_wait, not when the held one ends
        go.set()  # the held request ends
        self.assertIn(b" 200 ", first.recv(100))  # and was answered
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:  # its slot serves the next
            self.assertEqual(b"ok", r.read())


class TestPageFiles(unittest.TestCase):
    """The page's own files (index.html, its scripts and styles) come with an ETag and `no-cache`, compressed for a browser
    that takes gzip: a load fetches 260 KB instead of 932, and a reload gets 304 with no body for every file it holds,
    while a changed file comes again at once (the page and its scripts stay in step)."""

    def setUp(self):
        import gzip  # the compressed bytes
        self.gzip = gzip
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-static-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.static = self.tmp / "static"  # a copy of the page's files, one of which this test changes
        shutil.copytree(server.STATIC, self.static)
        patch = mock.patch.object(server, "STATIC", self.static)
        patch.start()
        self.addCleanup(patch.stop)
        self.srv = server.serve(0, data=self.tmp / "data")
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def fetch(self, path, **headers):
        """(status, headers, body) of one GET"""
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers), timeout=20) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_a_file_comes_compressed_then_as_304_and_again_when_it_changed(self):
        want = (self.static / "core.js").read_bytes()
        code, head, body = self.fetch("/static/core.js", **{"Accept-Encoding": "gzip"})
        self.assertEqual(200, code)
        self.assertEqual("gzip", head["Content-Encoding"])
        self.assertEqual(want, self.gzip.decompress(body))  # the file itself
        self.assertLess(len(body), len(want) / 2)
        self.assertEqual("no-cache", head["Cache-Control"])  # asked about every time
        self.assertTrue(head["Content-Security-Policy"])  # the page's policy, as on every answer
        tag = head["ETag"]
        code, head, body = self.fetch("/static/core.js", **{"If-None-Match": tag})
        self.assertEqual((304, b""), (code, body))  # nothing to fetch again
        code, head, body = self.fetch("/static/core.js")  # a client that takes no gzip
        self.assertEqual((200, want), (code, body))
        self.assertNotIn("Content-Encoding", head)
        (self.static / "core.js").write_bytes(want + b"\n// changed\n")  # an update
        code, head, body = self.fetch("/static/core.js", **{"If-None-Match": tag})
        self.assertEqual(200, code)  # the new file at once, never the one the browser held
        self.assertNotEqual(tag, head["ETag"])
        self.assertTrue(body.endswith(b"// changed\n"))

    def test_the_page_itself_is_sent_the_same_way(self):
        code, head, body = self.fetch("/", **{"Accept-Encoding": "gzip"})
        self.assertEqual(200, code)
        self.assertEqual((self.static / "index.html").read_bytes(), self.gzip.decompress(body) if head["Content-Encoding"] == "gzip" else body)
        self.assertEqual((304, b""), self.fetch("/", **{"If-None-Match": head["ETag"]})[0::2])


class TestUnderLoadAndStop(unittest.TestCase):
    """What keeps the panel whole when much is asked at once or it is stopped: a task that waits its turn says so, a stop
    from outside ends it cleanly, and the stop names what was cut short."""

    def test_a_task_that_waits_its_turn_says_so_and_then_shows_its_own_step(self):
        from apps.api.client import Client  # the API in this process
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-turn-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        c = Client(tmp)
        self.addCleanup(c.settle, 30)  # cleanups run last first: its tasks end before the folder goes
        t = c.api.tasks
        other = threading.Lock()  # held by another task, as render_lock is during a build
        other.acquire()
        t._set("build:x", state="running", step="queued")
        inside = []  # the step the task showed once its turn came

        def work():
            with t.turn("build:x", other):
                inside.append(t.tasks["build:x"]["step"])
        th = threading.Thread(target=work)
        th.start()
        end = time.monotonic() + 5
        while t.tasks["build:x"].get("step") != "waiting_turn" and time.monotonic() < end:  # waiting, and saying so
            time.sleep(0.02)
        self.assertEqual("waiting_turn", t.tasks["build:x"]["step"])
        other.release()  # the other task ends
        th.join(5)
        self.assertEqual(["queued"], inside)  # its own step again once it runs
        free = threading.Lock()
        with t.turn("build:y", free):  # a free lock: taken at once, nothing said
            self.assertNotIn("build:y", t.tasks)
        self.assertFalse(free.locked())  # given back
        t._set("build:x", state="done")  # the task the test marked running ends, so the cleanup's wait does not

    def test_the_stop_names_what_was_cut_short_and_waits_for_the_answers_being_sent(self):
        sys.path.insert(0, str(ROOT / "src"))
        import ownport  # the request slots
        held = ownport.Server.__new__(ownport.Server)  # the two fields wind_down reads, without a port
        held.cap, held._slots = 2, threading.BoundedSemaphore(2)
        held.server_close = lambda: None
        held._slots.acquire()  # a request being answered
        threading.Timer(0.3, held._slots.release).start()  # answered a moment later

        class Tasks:
            state_lock = threading.Lock()
            tasks = {"build:alpha": {"state": "running"}, "analyze:alpha": {"state": "done"}}

        class Panel:
            tasks = Tasks()
        before = server.Handler.panel
        server.Handler.panel = Panel()
        self.addCleanup(setattr, server.Handler, "panel", before)
        t0 = time.monotonic()
        with self.assertLogs("offerowl.panel", level="INFO") as said:
            server.wind_down(held, grace=5)
        self.assertLess(time.monotonic() - t0, 3)  # it waited for the answer, not for the whole grace
        lines = "\n".join(said.output)
        self.assertIn("build:alpha", lines)  # the running task is named
        self.assertNotIn("analyze:alpha", lines)  # a finished one is not
        self.assertIn("panel stopped", lines)

    @unittest.skipIf(os.name == "nt", "SIGTERM is a POSIX stop")
    def test_a_stop_from_outside_ends_the_panel_cleanly(self):
        import signal  # the container's stop
        import subprocess  # the panel as its own process
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-stop-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        env = dict(os.environ, PYTHONFAULTHANDLER="1")  # a crash prints every thread's stack, for this test's message
        p = subprocess.Popen([sys.executable, str(ROOT / "apps" / "panel" / "server.py"), "--port", "0", "--data", str(tmp)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env)
        self.addCleanup(p.stdout.close)  # cleanups run last first: the pipe goes after the process is reaped
        self.addCleanup(lambda: p.poll() is None and p.kill())
        self.assertTrue(p.stdout.readline().startswith("http://127.0.0.1:"))  # serving
        p.send_signal(signal.SIGTERM)  # docker stop, a pod's end, the desktop app's quit
        code = p.wait(15)  # well inside Docker's ten seconds
        said = p.stdout.read()  # what the panel printed, a crash's stacks with it
        log = (tmp / "logs" / "panel.log").read_text(encoding="utf-8") if (tmp / "logs" / "panel.log").is_file() else ""
        self.assertEqual(0, code, f"the panel's output:\n{said[-4000:]}\nits log:\n{log[-3000:]}")  # a clean exit; else the moment it failed, to read
        self.assertIn("stopping: signal", log)
        self.assertIn("panel stopped", log)


class TestDaysOfABatch(PanelCase):
    """The days that count, and a list of applications added on one day (a list brought in): the day of the adding stamped
    on their stages is cleared from all of them in one undo step."""

    def test_a_day_after_a_later_steps_never_counts(self):
        sys.path.insert(0, str(ROOT))
        from apps.api import tracker  # the rule itself
        job = {"stage": "result", "dates": {"preparing": "2026-11-07", "submitted": "2026-11-07", "result": "2026-10-28"}}
        self.assertEqual({"result": "2026-10-28"}, tracker.stage_days(job))  # prepared and sent after the answer: neither counts
        job = {"stage": "interview", "dates": {"preparing": "2026-10-01", "submitted": "2026-10-05", "interview": "2026-10-20"}}
        self.assertEqual(job["dates"], tracker.stage_days(job))  # in order: every day counts
        job = {"stage": "interview", "dates": {"preparing": "2026-11-07", "submitted": "2026-10-15", "interview": "2026-11-09"}}
        self.assertEqual({"submitted": "2026-10-15", "interview": "2026-11-09"}, tracker.stage_days(job))  # only the day out of order goes

    def test_the_day_of_a_batch_is_cleared_in_one_step(self):
        posting = POSTING.read_text(encoding="utf-8")
        ids = [self.post("/api/v1/jobs", {"company": f"배치{i}", "posting": posting})["job"] for i in range(5)]  # five added today
        for jid in ids:
            self.wait_task(f"analyze:{jid}")  # their analyses end first: each is a step of its own
        today = time.strftime("%Y-%m-%d")
        jobs = {j["id"]: j for j in self.get("/api/v1/state")["jobs"]}
        self.assertTrue(all(jobs[jid]["dates"].get("preparing") == today for jid in ids))  # the adding stamped today on them
        self.assertEqual([], self.post("/api/v1/tracker/clear_day", {"day": "2001-01-01"})["cleared"])  # no batch on that day: nothing changes
        self.assertEqual(sorted(ids), sorted(self.post("/api/v1/tracker/clear_day", {"day": today})["cleared"]))
        jobs = {j["id"]: j for j in self.get("/api/v1/state")["jobs"]}
        self.assertTrue(all(not jobs[jid]["dates"].get("preparing") for jid in ids))  # that day, gone from each
        self.assertEqual("undo_board_days", self.get("/api/v1/history")["steps"][0]["label"]["code"])  # one step for all five
        self.post("/api/v1/undo", {})  # and back at once
        jobs = {j["id"]: j for j in self.get("/api/v1/state")["jobs"]}
        self.assertTrue(all(jobs[jid]["dates"].get("preparing") == today for jid in ids))


class TestStandinAsAProgram(unittest.TestCase):
    """The stand-in started as a program, as the closed-network test starts it in the app image (`python3 apps/api/standin.py
    serve <port>`): from another folder, with no PYTHONPATH, it still binds through src/ownport.py and answers. An earlier
    build died there at once (no module named ownport), so the agent read signed out and nothing was written."""

    def test_it_serves_from_any_folder(self):
        import subprocess  # the program, as its own process
        import urllib.request  # one request to it
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-standin-"))  # a working folder far from the repository
        self.addCleanup(shutil.rmtree, tmp, True)
        child = subprocess.Popen([sys.executable, "-I", str(ROOT / "apps" / "api" / "standin.py"), "serve", "0"], cwd=tmp,  # -I: no PYTHONPATH, no script folder
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.addCleanup(child.stderr.close)  # cleanups run last first: its pipes close after it is stopped and reaped
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.wait, 10)  # reaped after it is stopped below
        self.addCleanup(child.kill)  # it serves until stopped
        line = child.stdout.readline().strip()  # its port, or nothing when it died
        self.assertTrue(line.isdigit(), "the stand-in did not start: " + (line + child.stderr.read() if not line.isdigit() else ""))
        body = json.dumps({"model": "standin", "messages": [{"role": "user", "content": "probe"}]}).encode()  # any prompt: it answers every one
        req = urllib.request.Request(f"http://127.0.0.1:{line}/v1/chat/completions", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20) as r:  # no proxy: this PC only
            self.assertIn("choices", json.loads(r.read()))  # an OpenAI-compatible answer


class TestKoreanTable(unittest.TestCase):
    """Every English text the page can show has its Korean (i18n/ko.js), and every placeholder survives."""

    def test_every_key(self):  # reads the page's code, no server needed
        ko = (STATIC / "i18n" / "ko.js").read_text(encoding="utf-8")  # the Korean table
        table = dict(re.findall(r'"((?:[^"\\]|\\.)*)":\s*"((?:[^"\\]|\\.)*)"', ko))  # "en": "ko"
        used = set()  # every text the scripts can show
        for f in sorted(STATIC.glob("*.js")):  # each script of the page
            js = f.read_text(encoding="utf-8")  # its code
            used |= set(re.findall(r'\bt\(\s*"((?:[^"\\]|\\.)*)"', js))  # t("...") calls
            for one, many in re.findall(r'\btn\([^,]+,\s*"((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)"', js):  # tn(n, "one", "many"): both forms
                used |= {one, many}  # each needs its Korean
            for name in ("KIND", "STAGE", "RATING", "CATEGORY", "ISSUE", "RATING_COUNT", "COVERAGE", "MARGIN_NAME", "WHERE", "STEP_WORDS", "RUN_STEPS", "RESULT", "BLIND_NOTES", "PARTS"):  # tables whose values go through t()
                m = re.search(r"const %s = \{(.*?)\};" % name, js, re.S)  # the table's body
                if m:  # the table lives in this file
                    used |= set(re.findall(r':\s*"([^"]+)"', m.group(1)))  # its values
            for name in ("VIEWS", "TABS", "OB_STEPS"):  # [key, words] lists
                m = re.search(r"const %s = \[(.*?)\];" % name, js, re.S)  # the list's body
                if m:  # the list lives in this file
                    used |= set(re.findall(r'\["[a-z]+",\s*"([^"]+)"\]', m.group(1)))  # its words
            used |= set(re.findall(r'\[\s*"(?:[a-z_-]+|\d+)",\s*"([A-Z][^"]+)"', js))  # option lists and lamp tables: ["key", "Words"]
            used |= set(re.findall(r'\[(?:\d+),\s*"([^"]+)"\]', js))  # numbered options: [2, "2 pages"]
            used |= set(re.findall(r'\b(?:field|seg)\(\s*"[a-z_]*",?\s*"([^"]+)"', js))  # field("name", "Name") and seg("Label", ...)
            used |= set(re.findall(r'\bseg\(\s*"([^"]+)"', js))  # seg's own label
            m = re.search(r"const L = \{(.*?)\};", js, re.S)  # the history's words
            if m:  # in this file
                used |= set(re.findall(r'"([^"]+)"', m.group(1)))  # its values: each step's words with a name and without one
        used -= {"한국어", "English", "Claude Code", "Codex", "Stand-in", "KO", "EN"}  # names that stay as they are (the script view's language keys among them)
        missing = sorted(k for k in used if k and k not in table and not re.fullmatch(r"[\s·,→+/]*", k))  # punctuation alone needs none
        self.assertEqual([], missing)  # every text has its Korean
        for en, kr in table.items():  # placeholders kept
            self.assertEqual(sorted(set(re.findall(r"\{(\w+)", en))), sorted(set(re.findall(r"\{(\w+)", kr))), en)  # names the faulty entry


class TestForms(PanelCase):
    """The resume's form and the deck's look, chosen in the panel, reach the canvas and the typesetting."""

    def test_a_form_reaches_the_canvas_and_the_edition(self):
        self.post("/api/v1/example", {"lang": "ko"})  # the fictional person
        self.wait_task("ingest")  # read
        self.post("/api/v1/facts/keep-all", {})  # every fact kept
        sections = lambda: [b.get("key") for b in self.get("/api/v1/documents/resume?lang=ko")["blocks"] if b["type"] == "section"]  # noqa: E731  the canvas's headings, in order
        self.assertEqual(["overview", "career", "edu", "comp", "skills", "detail"], sections()[:6])  # the detailed form by default
        self.post("/api/v1/settings", {"form": "compact"})  # one column
        self.assertEqual(["detail", "skills", "edu"], sections()[:3])  # the work first, and no overview
        self.assertNotIn("overview", sections())  # its cards stay out
        self.assertNotIn("career", sections())  # and its table
        blocks = self.get("/api/v1/documents/resume?lang=ko")["blocks"]  # the blocks
        self.assertEqual("headline", blocks[0]["type"])  # what the person does still leads
        self.post("/api/v1/settings", {"form": "table"})  # tables
        self.assertEqual(["edu", "career"], sections()[:2])  # as the standard form asks
        self.post("/api/v1/settings", {"form": "nothing we print", "deck_style": "clean"})  # a stale page's value, and a look
        self.assertEqual("table", self.get("/api/v1/state")["settings"]["form"])  # the odd value is ignored
        self.post("/api/v1/settings", {"form": "compact"})  # back to one column
        api = self.srv.RequestHandlerClass.panel  # the running API
        out = api.tasks.edition_inputs("-general", "ko")  # what the typesetting reads
        job = json.loads((out / "job.json").read_text(encoding="utf-8"))  # its settings
        self.assertEqual(("compact", "clean"), (job["form"], job["deckStyle"]))  # both reach it
        self.post("/api/v1/settings", {"form": "detailed", "deck_style": "classic"})  # as it was, for the class


class TestBackup(PanelCase):
    """The whole workspace as one file: out, in again, and refused when it is not a backup."""

    def send_file(self, data: bytes, origin=None):  # a picked file, sent as the page sends it
        headers = {"Content-Type": "application/octet-stream", "X-File-Name": "backup.zip"}  # the page's own headers
        if origin:  # as a page of another site would
            headers["Origin"] = origin  # its address
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/workspace/restore", data=data, method="POST", headers=headers)  # the raw file
        try:  # a refusal raises HTTPError
            with urllib.request.urlopen(req, timeout=60) as r:  # a hung server fails the test
                return r.status, json.loads(r.read())  # the answer
        except urllib.error.HTTPError as e:  # 4xx answers land here
            return e.code, json.loads(e.read() or b"{}")  # the error's own JSON

    def test_out_and_in_again(self):
        self.post("/api/v1/example", {"lang": "ko"})  # the fictional person
        self.wait_task("ingest")  # read
        self.post("/api/v1/facts/keep-all", {})  # every fact kept
        kept = self.get("/api/v1/state")["facts"]["counts"]["kept"]  # how many
        self.assertGreater(kept, 0)  # there are some
        ctype, data = self.raw_get("/api/v1/workspace/backup")  # the file a browser saves
        self.assertEqual("application/zip", ctype)  # a zip
        with zipfile.ZipFile(io.BytesIO(data)) as z:  # read back
            self.assertIn("offerowl-backup.json", z.namelist())  # it says what it is
            self.assertIn("profile/profile.json", z.namelist())  # and holds the person's profile
        self.post("/api/v1/facts/decide", {"cid": self.get("/api/v1/facts")["rows"][0]["cid"], "action": "drop"})  # a change after the backup
        self.assertEqual(kept - 1, self.get("/api/v1/state")["facts"]["counts"]["kept"])  # one fact fewer
        code, out = self.send_file(data)  # the backup comes back
        self.assertEqual(200, code, out)  # restored
        self.assertEqual(kept, self.get("/api/v1/state")["facts"]["counts"]["kept"])  # as it was
        aside = self.tmp / "data" / out["kept"]  # the workspace as it was before restoring
        self.assertTrue((aside / "profile" / "profile.json").is_file())  # nothing was deleted
        self.assertFalse(list((self.tmp / "data").glob("*.restoring-*")))  # and no working folder is left

    def test_an_upload_is_written_to_the_data_folder_and_goes(self):
        # a backup can be hundreds of megabytes: it is written to a file beside the workspace (a container's /tmp is memory),
        # restored from there, and removed; a piece an upload cut off left goes once it is an hour old
        import os  # a file's time
        import time  # an hour ago
        from unittest import mock  # the restore, watched
        data = self.tmp / "data"
        stale, fresh = data / ".upload-1-1.part", data / ".upload-2-2.part"  # one left long ago, one on its way now
        stale.write_bytes(b"old")
        os.utime(stale, (time.time() - 7200, time.time() - 7200))
        fresh.write_bytes(b"new")
        self.addCleanup(fresh.unlink, True)
        seen = []
        api = type(self).srv.RequestHandlerClass.router.api

        def restore(arg):  # what the server hands the restore
            seen.append((arg, isinstance(arg, pathlib.Path) and arg.is_file() and arg.read_bytes() == b"PK-not-a-real-zip"))
            raise ValueError("not_a_backup")

        with mock.patch.object(api, "restore", side_effect=restore):
            code, out = self.send_file(b"PK-not-a-real-zip")
        self.assertEqual((400, "not_a_backup"), (code, out.get("error")))
        self.assertEqual(1, len(seen))
        path, whole = seen[0]
        self.assertTrue(whole)  # a file, holding the upload
        self.assertEqual(data, path.parent)  # in the data folder
        self.assertFalse(path.exists())  # and gone after
        self.assertFalse(stale.exists())  # the old piece went
        self.assertTrue(fresh.exists())  # one that may be on its way stays

    def test_a_file_that_is_not_a_backup_changes_nothing(self):
        before = sorted(p.name for p in (self.tmp / "data").iterdir())  # the data folder as it is
        code, out = self.send_file(b"not a zip at all")  # any file
        self.assertEqual((400, "not_a_backup"), (code, out.get("error")))  # said so
        plain = io.BytesIO()  # a zip with no mark
        with zipfile.ZipFile(plain, "w") as z:  # as any other zip
            z.writestr("profile/profile.json", "{}")  # looks like one inside
        self.assertEqual("not_a_backup", self.send_file(plain.getvalue())[1].get("error"))  # still refused
        for name in ("../outside.txt", "/etc/outside.txt", "..\\outside.txt", "C:\\outside.txt"):  # entries that would land elsewhere, on any system
            bad = io.BytesIO()  # a planted file
            with zipfile.ZipFile(bad, "w") as z:  # with the mark
                z.writestr("offerowl-backup.json", "{}")  # says it is one
                z.writestr("profile/x.json", "{}")  # has a profile
                z.writestr(name, "planted")  # and one entry outside
            self.assertEqual("not_a_backup", self.send_file(bad.getvalue())[1].get("error"), name)  # refused before anything is written
        self.assertEqual(before, sorted(p.name for p in (self.tmp / "data").iterdir()))  # nothing changed
        self.assertFalse((self.tmp / "outside.txt").exists())  # nothing landed outside

    def backup_of(self, entries):  # a planted file, with the mark and a profile folder
        out = io.BytesIO()  # in memory
        with zipfile.ZipFile(out, "w") as z:  # a zip
            z.writestr("offerowl-backup.json", "{}")  # says it is a backup
            for name, text in entries:  # and holds these
                z.writestr(name, text)  # one entry
        return out.getvalue()  # its bytes

    def test_a_name_that_could_break_out_of_a_page_is_refused(self):
        for name in ('jobs/x/"><script>.png', "profile/<b>.json", 'profile/a"b.json'):  # would reach a slide's HTML as a picture's path
            self.assertEqual("not_a_backup", self.send_file(self.backup_of([("profile/profile.json", "{}"), (name, "x")]))[1].get("error"), name)  # refused

    def test_a_backup_the_panel_cannot_read_leaves_the_files_as_they_were(self):
        self.get("/api/v1/state")  # it answers now
        before = (self.tmp / "data" / "workspace" / "prefs.json").is_file(), sorted(p.name for p in (self.tmp / "data" / "workspace").iterdir())  # the workspace as it is
        for entries in ([("profile/profile.json", "{}"), ("jobs", "a file where a folder belongs")],  # stops at the layout
                        [("profile/profile.json", "{}"), ("jobs/x/status.json", "{}")]):  # a job with no id: only reading it shows that
            code, out = self.send_file(self.backup_of(entries))  # sent
            self.assertEqual(400, code, out)  # refused
            self.assertIn(out.get("error"), ("not_a_backup", "restore_failed"))  # said why
            self.assertEqual(200, urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/v1/state", timeout=20).status)  # the panel still answers
            self.assertEqual(before, ((self.tmp / "data" / "workspace" / "prefs.json").is_file(), sorted(p.name for p in (self.tmp / "data" / "workspace").iterdir())))  # and its files are back

    def test_a_backup_holds_a_person_s_files_and_not_the_undo_steps(self):
        ws = self.tmp / "data" / "workspace"  # the workspace
        (ws / "jobs" / "live").mkdir(parents=True, exist_ok=True)  # a job at a company called Live
        (ws / "jobs" / "live" / "status.keep").write_text("kept", encoding="utf-8")  # one of its files
        (ws / "sources" / "notes.tmp").write_text("kept", encoding="utf-8")  # a person's own file with that ending
        (ws / ".history" / "1.json").write_text("{}", encoding="utf-8")  # an undo step
        (ws / "sources" / "x.1.2.tmp").write_text("passing", encoding="utf-8")  # a write in progress
        (ws / "jobs" / "live" / "live").mkdir(exist_ok=True)  # the live deck's working folder
        (ws / "jobs" / "live" / "live" / "w.json").write_text("{}", encoding="utf-8")  # a file in it
        with zipfile.ZipFile(io.BytesIO(self.raw_get("/api/v1/workspace/backup")[1])) as z:  # the file a browser saves
            names = set(z.namelist())  # what it holds
        self.assertLessEqual({"jobs/live/status.keep", "sources/notes.tmp"}, names)  # the person's
        self.assertFalse({"jobs/live/live/w.json", "sources/x.1.2.tmp", ".history/1.json"} & names)  # and nothing passing through
        for f in (ws / "jobs" / "live" / "live" / "w.json", ws / "jobs" / "live" / "status.keep", ws / "sources" / "x.1.2.tmp", ws / "sources" / "notes.tmp", ws / ".history" / "1.json"):  # the class shares this workspace
            f.unlink()  # as it was
        (ws / "jobs" / "live" / "live").rmdir()  # empty now
        (ws / "jobs" / "live").rmdir()  # and this

    def test_undo_and_materials_stay_inside_the_workspace(self):
        from apps.api.workspace import Workspace  # the class itself
        root = self.tmp / "planted" / "workspace"  # a workspace with a sibling that shares its name's start
        ws = Workspace(root)  # made
        other = root.with_name("workspace-other")  # the sibling
        other.mkdir()  # there
        (other / "secret.txt").write_text("keep", encoding="utf-8")  # a file in it
        (root / ".history" / "00001.json").write_text(json.dumps({"label": {}, "files": {"../workspace-other/secret.txt": None, "../workspace-other/new.txt": "x"}}), encoding="utf-8")  # a planted step
        ws.undo()  # it runs
        self.assertTrue((other / "secret.txt").is_file())  # nothing deleted there
        self.assertFalse((other / "new.txt").exists())  # nothing written there
        self.assertEqual(root / "sources" / "passwd", ws.material_path({"file": "/etc/passwd"}))  # a planted record reads inside sources/

    def test_another_site_cannot_send_one(self):
        self.assertEqual(403, self.send_file(b"x", origin="https://evil.example")[0])  # refused before the body is read


class TestUndoKeepsLaterFiles(unittest.TestCase):
    """The list of added files grows outside the undo steps: undoing a step keeps the files added after it, and puts the
    step's own records back as they were."""

    def setUp(self):
        from apps.api.workspace import Workspace  # the class itself
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-undo-"))  # a workspace of its own
        self.addCleanup(shutil.rmtree, self.root, True)  # gone afterwards
        self.ws = Workspace(self.root)  # made

    def test_a_file_added_after_a_step_stays_listed(self):
        from apps.api.facts import FACT_FILES  # the files a fact step snapshots, the list of files among them
        with self.ws.change({"code": "undo_keep"}, FACT_FILES):  # a fact kept
            (self.root / "sources" / "review.json").write_text('{"kept": ["c1"]}', encoding="utf-8")  # its own change
        self.ws.add_material("old_resume.txt", b"a fictional resume")  # a file added after it, outside any step
        self.ws.undo()  # the fact step is undone
        self.assertEqual(["old_resume.txt"], [m["name"] for m in self.ws.materials()])  # the file is still listed
        self.assertEqual("m2", self.ws.add_material("notes.txt", b"more")["id"])  # and its id is not handed out again

    def test_the_step_s_own_records_go_back(self):
        from apps.api.facts import FACT_FILES  # as above
        first = self.ws.add_material("a.txt", b"one")  # listed before the step
        with self.ws.change({"code": "undo_add_material"}, FACT_FILES):  # a step that changes a record and lists a new one
            self.ws.update_material(first["id"], state="done", facts=3)  # read
            self.ws.add_material("b.txt", b"two")  # and one more, inside the step
        self.ws.add_material("c.txt", b"three")  # after the step
        self.ws.undo()  # the step is undone
        self.assertEqual([("a.txt", "new"), ("c.txt", "new")], [(m["name"], m["state"]) for m in self.ws.materials()])  # a as it was, b gone with its step, c kept


class TestJobUndoAndBoard(unittest.TestCase):
    """Undoing the adding of a job leaves no folder behind, and the board takes real days only."""

    def setUp(self):
        from apps.api.client import Client  # the API in this process
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-job-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ["OFFEROWL_PANEL_BACKEND"] = "none"  # no agent
        self.addCleanup(os.environ.pop, "OFFEROWL_PANEL_BACKEND", None)
        self.c = Client(self.tmp)
        self.posting = (ROOT / "tests" / "app" / "fixtures" / "posting_ko.md").read_text(encoding="utf-8") + "\n\n## 지원서 문항\n\n1. 지원 동기를 쓰세요. (500자 이내)\n"  # with a form's question

    def test_an_undone_job_leaves_its_name_free(self):
        jid = self.c.post("/api/v1/jobs", {"posting": self.posting}).get("job") or self.c.get("/api/v1/state")["job"]
        self.c.settle()  # its analysis ends (an undo step of its own)
        self.assertTrue((self.c.api.ws.job_dir(jid) / "questions.json").is_file())  # the posting's question came along
        self.c.post("/api/v1/undo", {})  # the analysis
        self.c.post("/api/v1/undo", {})  # the job itself
        self.assertFalse(self.c.api.ws.job_dir(jid).exists())  # nothing of it left
        again = self.c.post("/api/v1/jobs", {"posting": self.posting}).get("job") or self.c.get("/api/v1/state")["job"]
        self.c.settle()
        self.assertEqual(jid, again)  # the same name, not a -2

    def test_removing_a_job_says_so_on_the_undo_key(self):
        jid = self.c.post("/api/v1/jobs", {"posting": self.posting}).get("job") or self.c.get("/api/v1/state")["job"]
        self.c.settle()
        self.c.post("/api/v1/jobs/remove", {"job": jid})  # off the board
        self.assertEqual("undo_remove_job", self.c.get("/api/v1/state")["undo"]["code"])  # the undo key names a removal, not a card change

    def test_the_example_keeps_its_own_facts_only(self):
        from apps.api.client import Client  # a client of its own, with the stand-in reading the person's notes
        os.environ["OFFEROWL_PANEL_AGENT"] = "standin"  # the agent, made up: it reads "kind: org | period | title | statement" lines
        self.addCleanup(os.environ.pop, "OFFEROWL_PANEL_AGENT", None)
        c = Client(self.tmp / "standin")
        notes = self.tmp / "notes.txt"  # the person's own notes, about fictional work
        notes.write_text("<<<\n과제: 엡실론뱅크 | 2023.01 ~ 2023.09 | 결제 승인 | 승인을 분리했다\n>>>\n", encoding="utf-8")
        mine = c.post("/api/v1/materials/file", {"path": str(notes)})["material"]
        c.post("/api/v1/materials/read", {"ids": [mine["id"]]})
        c.wait("ingest")
        todo = c.get("/api/v1/state")["facts"]["counts"]["to_confirm"]  # theirs, still to review
        self.assertGreater(todo, 0)
        ex = c.post("/api/v1/example", {"lang": "ko"})["material"]  # the example, for a first look
        c.wait("ingest")
        c.post("/api/v1/facts/keep-all", {"material": ex["id"]})  # as "Try an example" keeps it
        self.assertEqual(todo, c.get("/api/v1/state")["facts"]["counts"]["to_confirm"])  # the person's own facts still wait for them

    def test_the_board_takes_real_days(self):
        jid = self.c.post("/api/v1/jobs", {"posting": self.posting}).get("job") or self.c.get("/api/v1/state")["job"]
        self.c.settle()
        self.c.post("/api/v1/tracker/edit", {"job": jid, "date": "2026-03-01"})  # a day
        for bad in ("abcd-efghi", "2026-02-30", "2026/03/01"):
            self.c.post("/api/v1/tracker/edit", {"job": jid, "date": bad})  # refused quietly, the day stays
        st = self.c.api.ws.job(jid)
        self.assertEqual("2026-03-01", st["dates"][st["stage"]])  # only the real day was kept


class TestNoFileStaysReading(unittest.TestCase):
    """A file shows "reading" only while it is read: not after the reading broke, and not after a restart."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-reading-"))  # a data folder of its own
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ["OFFEROWL_PANEL_BACKEND"] = "none"  # no agent
        self.addCleanup(os.environ.pop, "OFFEROWL_PANEL_BACKEND", None)

    def test_a_reading_that_breaks(self):
        from unittest import mock  # one step made to fail
        from apps.api.client import Client  # the API in this process
        c = Client(self.tmp)
        rec = c.post("/api/v1/materials/file", {"path": str(SAMPLE)})["material"]  # a file
        with mock.patch.object(c.api.facts, "import_profile", side_effect=RuntimeError("a bug")):  # the reading breaks part way
            c.post("/api/v1/materials/read", {"ids": [rec["id"]]})
            self.assertEqual("error", c.wait("ingest")["state"])  # the task says so
        self.assertEqual("new", c.get("/api/v1/state")["materials"][0]["state"])  # and the file can be read again

    def test_a_restart_after_a_reading_that_never_ended(self):
        from apps.api.client import Client  # as above
        c = Client(self.tmp)
        rec = c.post("/api/v1/materials/file", {"path": str(SAMPLE)})["material"]
        c.api.ws.update_material(rec["id"], state="reading")  # as a closed app left it
        self.assertEqual("new", Client(self.tmp).get("/api/v1/state")["materials"][0]["state"])  # the next start shows it unread


if __name__ == "__main__":  # run as a script
    unittest.main(verbosity=2)  # each test's name as it runs
