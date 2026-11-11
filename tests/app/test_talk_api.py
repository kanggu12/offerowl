#!/usr/bin/env python3
"""The talk's routes (apps/api/task_kit.py, apps/api/routes.py) through the panel's server, on a fictional job: the brief kept
with only its own keys and refused without a topic, the job's talk read before it is made, the kit's /talk page and its PDFs at
the panel's own address, the Desktop copy refused when there is nothing to copy. Making the talk draws and prints a deck and is
tested in tests/interview/test_talk.py and the panel's walk.

    python3 -m unittest tests/app/test_talk_api.py -v
"""
import html  # the page's words as the page escapes them
import json  # requests and answers
import os  # environment
import pathlib  # paths
import shutil  # temporary folders
import sys  # the import path
import tempfile  # a data folder per class
import threading  # the server in the background
import unittest  # the runner
import urllib.error  # refused requests
import urllib.parse  # job ids in addresses
import urllib.request  # requests
from unittest import mock  # the environment

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
from apps.panel import server  # noqa: E402  the panel (the page and the API)
sys.path.insert(0, str(ROOT / "src"))  # src/interview, for the page's own words
from interview import talk_page  # noqa: E402  the kit's /talk page

POSTING = ROOT / "tests" / "app" / "fixtures" / "posting_ko.md"  # a fictional posting of a fictional company


class TalkApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-talk-api-"))  # the data folder and the Desktop
        cls.env = mock.patch.dict(os.environ, {"OFFEROWL_DESKTOP": str(cls.tmp / "Desktop"), "OFFEROWL_PANEL_BACKEND": "none"})  # no agent is ever asked
        cls.env.start()
        os.environ.pop("OFFEROWL_PANEL_AGENT", None)  # a stand-in class run earlier must not count
        cls.srv = server.serve(0, data=cls.tmp / "data")  # a free port
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.job = cls.post(cls, "/api/v1/jobs", {"company": "감마클라우드", "posting": POSTING.read_text(encoding="utf-8")})["job"]  # a fictional job

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str):
        """A read whose answer is JSON."""
        with urllib.request.urlopen(self.url(path), timeout=60) as r:
            return json.loads(r.read())

    def raw(self, path: str) -> tuple[int, bytes, str]:
        """A read as bytes: (status, body, type), a refusal included."""
        try:
            with urllib.request.urlopen(self.url(path), timeout=120) as r:
                return r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "")

    def post(self, path: str, body: dict, expect: int = 200) -> dict:
        """A JSON write as the page makes it."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.port}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                assert r.status == expect, r.status
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            assert e.code == expect, (e.code, body[:300])
            return json.loads(body or b"{}")

    def test_brief_kept_with_its_own_keys(self):
        """The brief is kept beside kit.json with the brief's own keys only, and read back with the job's talk."""
        brief = {"topics": [{"title": "소개와 핵심 역량"}, {"title": "가장 도전적이었던 문제"}], "minutes": 30, "when": "2026-11-20 14:00",
                 "format": "발표와 질의응답", "request": "요청 원문", "lang": "ko", "extra": "not a brief key"}
        got = self.post("/api/v1/interview/talk/brief", {"job": self.job, "brief": brief})
        self.assertNotIn("extra", got["brief"])
        kept = json.loads((self.tmp / "data" / "workspace" / "jobs" / self.job / "interview" / "talk.json").read_text(encoding="utf-8"))
        self.assertEqual([t["title"] for t in kept["topics"]], ["소개와 핵심 역량", "가장 도전적이었던 문제"])
        state = self.get(f"/api/v1/jobs/{urllib.parse.quote(self.job)}/talk")
        self.assertEqual(state["brief"]["minutes"], 30)
        self.assertFalse(state["made"])
        self.assertEqual(state["task"], f"talk:{self.job}")

    def test_the_form_keeps_what_it_does_not_show(self):
        """The panel's form sends the titles, the minutes and the day; what the person wrote by hand in talk.json (the pages,
        the theme, a topic's own minutes) stays."""
        f = self.tmp / "data" / "workspace" / "jobs" / self.job / "interview" / "talk.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"topics": [{"title": "소개", "minutes": 4}], "pages": [3, 5], "theme": {"frame": "#000000", "accent": "#d9480f"}}), encoding="utf-8")
        got = self.post("/api/v1/interview/talk/brief", {"job": self.job, "brief": {"topics": [{"title": "소개"}, {"title": "경험"}], "minutes": 20}})["brief"]
        self.assertEqual(got["pages"], [3, 5])
        self.assertEqual(got["theme"]["accent"], "#d9480f")
        self.assertEqual(got["topics"][0].get("minutes"), 4)
        self.assertEqual(got["minutes"], 20)

    def test_brief_without_a_topic_is_refused(self):
        """A brief whose topics are empty, or that is no object at all, is refused and changes nothing."""
        got = self.post("/api/v1/interview/talk/brief", {"job": self.job, "brief": {"topics": [{"title": "  "}]}}, expect=400)
        self.assertEqual(got.get("what"), "bad_brief")
        self.post("/api/v1/interview/talk/brief", {"job": self.job, "brief": "topics"}, expect=400)

    def test_kit_pages_before_the_talk_is_made(self):
        """At the panel's own address the kit's /talk says there is no talk yet, and its PDFs are not there; the Desktop copy
        writes nothing."""
        self.post("/api/v1/interview/talk/brief", {"job": self.job, "brief": {"topics": ["소개"]}})  # the interview folder exists now
        self.assertTrue(self.post("/api/v1/interview/start", {"job": self.job})["started"])
        code, body, ctype = self.raw(f"/kit/{urllib.parse.quote(self.job)}/talk")
        self.assertEqual(code, 200)
        self.assertIn("text/html", ctype)
        page = body.decode("utf-8")
        self.assertTrue(any(html.escape(W["none"]) in page for W in talk_page.WORDS.values()), page[:300])  # "no talk yet", in the kit's language
        self.assertIn("background: #ffffff", page)  # a sheet of its own: its dark words never stand on the panel's dark desk
        self.assertNotIn(b"<script", body)
        code, _, _ = self.raw(f"/kit/{urllib.parse.quote(self.job)}/talk/deck.pdf")
        self.assertEqual(code, 404)
        code, _, _ = self.raw(f"/kit/{urllib.parse.quote(self.job)}/talk/..%2Fplan.json")
        self.assertIn(code, (404, 400))
        self.assertEqual(self.post("/api/v1/interview/talk/deliver", {"job": self.job})["files"], [])

    def test_planted_talk_runs_no_script(self):
        """A talk.json that came with a restored backup cannot put a script into the kit's page: page numbers print as numbers,
        the accent only as a colour, and the page's policy runs no script at all."""
        self.post("/api/v1/interview/talk/brief", {"job": self.job, "brief": {"topics": ["소개"]}})
        folder = self.tmp / "data" / "workspace" / "out" / "interview" / self.job / "talk"
        folder.mkdir(parents=True, exist_ok=True)
        bad = "<script>fetch('/api/v1/state')</script>"
        planted = {"brief": {"lang": "ko", "minutes": 30, "theme": {"frame": "#000000", "accent": "red;}</style>" + bad + "<style>"}},
                   "company": bad, "parts": [{"no": "01", "title": bad}], "seconds": 60, "checks": {"pace": [{"page": bad}], "layout": []},
                   "slides": [{"key": "a", "kind": "about", "part": 0, "page": bad, "seconds": bad, "title": bad,
                               "script": {"lines": [bad], "cue": bad, "short": bad, "questions": [{"q": bad, "a": bad}]}}]}
        (folder / "talk.json").write_text(json.dumps(planted), encoding="utf-8")
        self.assertTrue(self.post("/api/v1/interview/start", {"job": self.job})["started"])
        req = urllib.request.Request(self.url(f"/kit/{urllib.parse.quote(self.job)}/talk"))
        with urllib.request.urlopen(req, timeout=120) as r:
            body, policy = r.read().decode("utf-8"), r.headers.get_all("Content-Security-Policy") or []
        self.assertNotIn("<script", body)
        self.assertTrue(any("script-src 'none'" in x for x in policy), policy)
        self.assertIn("word-break: keep-all", body)  # a Korean word is never split across two lines, on the page or in its PDF


if __name__ == "__main__":
    unittest.main()
