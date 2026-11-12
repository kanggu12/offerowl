"""What the panel's own interview views read (apps/api/routes.py): every script with its words for the contents, the search
and the cards (kit.js), the interview deck in its printed order, and the talk's speaker script with its slides' pictures
(interview.js). Each answers for the job asked, in the panel's language; the two large ones come with an ETag, so a page that
asks again for an unchanged kit gets a 304 and no body; a job with no kit, or no talk, gets a 404 that says so. No model is
called.

    python3 -m unittest tests/app/test_interview_views.py -v
"""
import gzip  # a compressed answer
import json  # answers
import os  # the similarity model's setting
import pathlib  # paths
import struct  # a picture's header
import sys  # the import path
import unittest  # the runner
import urllib.error  # refusals
import urllib.request  # reads with their headers
import zlib  # a one-pixel picture

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "src"))  # the kit's deck, to compare with
sys.path.insert(0, str(ROOT / "tests" / "app"))  # the shared test case
from test_panel import POSTING, PanelCase, q  # noqa: E402  one server and workspace per class, on the fictional example

EXAMPLE = ROOT / "examples" / "interview" / "jobs" / "gamma-platform" / "interview"  # the fictional example's scripts


def png() -> bytes:
    """A one-pixel PNG: what the talk's thumbs folder holds, in its smallest form."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b"")


class TestInterviewViews(PanelCase):
    """One job with a kit made from the fictional example, one without."""

    @classmethod
    def setUpClass(cls):
        cls.model_setting = os.environ.pop("OFFEROWL_SEARCH_MODEL", None)  # no similarity model, whatever this PC has set: put back afterwards
        super().setUpClass()
        case = cls("test_the_view_answers_for_the_job")  # the shared helpers need an instance
        case.start_profile()  # the example's facts, kept
        posting = POSTING.read_text(encoding="utf-8")
        cls.job = case.post("/api/v1/jobs", {"company": "감마클라우드", "role": "백엔드 플랫폼 엔지니어", "posting": posting})["job"]
        case.post("/api/v1/interview/kit", {"job": cls.job, "lang": "ko"})  # its question map and kit files, no model
        for name in ("qa.md", "deep.md"):  # the example's scripts, added as the panel's "Add scenes you wrote" key sends them
            case.add_scenes(cls.job, EXAMPLE / name)
        cls.bare = case.post("/api/v1/jobs", {"company": "델타페이먼츠", "role": "SRE", "posting": posting})["job"]  # no kit made
        cls.briefed = case.post("/api/v1/jobs", {"company": "엡실론뱅크", "role": "플랫폼 엔지니어", "posting": posting})["job"]  # a talk's brief and nothing else
        case.post("/api/v1/interview/talk/brief", {"job": cls.briefed, "brief": {"topics": [{"title": "소개와 핵심 역량"}], "minutes": 20}})

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if cls.model_setting is not None:  # this PC's own setting back
            os.environ["OFFEROWL_SEARCH_MODEL"] = cls.model_setting

    def add_scenes(self, jid, path):
        """Scripts written before, sent as the page sends a picked file: its raw bytes, its name in X-File-Name."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/interview/scenes?job={q(jid)}", data=path.read_bytes(), method="POST",
                                     headers={"Content-Type": "application/octet-stream", "X-File-Name": q(path.name), "Origin": f"http://127.0.0.1:{self.port}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            self.assertGreater(json.loads(r.read())["scenes"], 0)  # the file held scripts

    def read(self, path, headers=None):
        """(status, headers, body bytes) of a read, a refusal included."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:  # 304 and 404 come here
            return e.code, e.headers, e.read()

    def test_the_view_answers_for_the_job(self):
        code, headers, body = self.read(f"/api/v1/jobs/{q(self.job)}/interview/view?lang=en")
        self.assertEqual(200, code)
        view = json.loads(body)
        self.assertTrue(view["items"])  # every script
        self.assertEqual(f"/kit/{q(self.job)}/", view["api"])  # where its similarity questions go
        self.assertEqual("en", view["str"]["lang"])  # its words in the panel's language
        self.assertRegex(view["stamp"], r"^[0-9a-f]{12}$")  # changes when a kit file does
        self.assertFalse(view["model"])  # no similarity model on this PC's setting
        self.assertIn("text", view["items"][0])  # the script itself, for the cards

    def test_an_unchanged_view_and_deck_are_a_304(self):
        for part in ("view", "deck"):
            path = f"/api/v1/jobs/{q(self.job)}/interview/{part}?lang=ko"
            code, headers, body = self.read(path, {"Accept-Encoding": "gzip"})
            self.assertEqual(200, code, part)
            tag = headers.get("ETag")
            self.assertTrue(tag and tag.startswith('W/"'), part)  # a weak tag: the same data compressed or not
            self.assertEqual("gzip", headers.get("Content-Encoding"), part)  # megabytes for a large kit: compressed
            self.assertTrue(json.loads(gzip.decompress(body)), part)
            code, headers, body = self.read(path, {"If-None-Match": tag})  # the page asks again with the copy it holds
            self.assertEqual((304, b""), (code, body), part)

    def test_the_deck_prints_what_the_printed_deck_prints(self):
        from interview import deck as ivdeck  # the printed deck, to compare with
        from interview.job import Job
        code, _, body = self.read(f"/api/v1/jobs/{q(self.job)}/interview/deck?lang=en")
        self.assertEqual(200, code)
        d = json.loads(body)
        self.assertEqual("Interview deck", d["words"]["title"])  # the deck's own words in the panel's language
        self.assertEqual("감마클라우드", d["company"])  # as its cover names it
        page = ivdeck.page(Job(type(self).srv.RequestHandlerClass.panel.ws.job_dir(self.job), confined=True), lang="en")
        printed = [x.split('"', 1)[0] for x in page.split('<section class="scene" data-id="')[1:]]  # the scripts the printed deck holds, in order
        self.assertEqual(printed, [s["id"] for s in d["scenes"]])  # the same, in the same order
        self.assertTrue(all(s["turns"] for s in d["scenes"]))  # each with its dialogue
        self.assertTrue(any("**" in t["en"] or "==" in t["en"] for s in d["scenes"] for t in s["turns"]))  # the lines as written: the panel draws the marks
        self.assertTrue(d["posting"])  # the posting line by line
        self.assertEqual(d["counts"]["scripts"], len(d["scenes"]))

    def test_a_job_without_a_kit_or_a_talk_says_so(self):
        for part, error in (("interview/view", "no_kit"), ("interview/deck", "no_kit"), ("talk/script", "no_talk")):
            code, _, body = self.read(f"/api/v1/jobs/{q(self.bare)}/{part}")
            self.assertEqual((404, error), (code, json.loads(body).get("error")), part)
        code, _, _ = self.read(f"/api/v1/jobs/{q(self.bare)}/talk/slides/1.png")
        self.assertEqual(404, code)
        code, _, _ = self.read("/api/v1/jobs/no-such-job/interview/deck")
        self.assertEqual(400, code)  # an application that is not there is refused as every job's route refuses it

    def test_a_talk_s_brief_alone_is_no_kit(self):
        """A job whose interview folder holds only a talk's brief has no kit: the board offers to make one, and the view and
        the deck say no_kit alike (one rule for the three: the kit's settings, kit.json)."""
        board = json.loads(self.read(f"/api/v1/jobs/{q(self.briefed)}/interview")[2])
        self.assertFalse(board["ready"])
        for part in ("interview/view", "interview/deck"):
            code, _, body = self.read(f"/api/v1/jobs/{q(self.briefed)}/{part}")
            self.assertEqual((404, "no_kit"), (code, json.loads(body).get("error")), part)
        talk = json.loads(self.read(f"/api/v1/jobs/{q(self.briefed)}/talk")[2])
        self.assertEqual("소개와 핵심 역량", talk["brief"]["topics"][0]["title"])  # the brief itself is kept and read

    def test_a_kit_json_written_after_the_kit_started_is_read(self):
        """Scripts added once the kit's server runs change kit.json (a terms file keeps its role there): the view reads the
        new roles at once, as the deck does, instead of the settings the server started with."""
        view = json.loads(self.read(f"/api/v1/jobs/{q(self.job)}/interview/view?lang=ko")[2])  # the kit's server is up
        self.assertFalse([it for it in view["items"] if it.get("src", "").startswith("terms")])  # no terms file yet
        self.add_scenes(self.job, EXAMPLE / "terms.md")  # a terms file: kit.json names it with its role
        view = json.loads(self.read(f"/api/v1/jobs/{q(self.job)}/interview/view?lang=ko")[2])
        roles = {it["role"] for it in view["items"] if it.get("src", "").startswith("terms")}
        self.assertEqual({"terms"}, roles)  # read with its role, not as scenes

    def test_the_general_edition_has_no_talk(self):
        """The edition with no job has no interview folder at all: its talk reads as not made, never as a dropped connection."""
        code, _, body = self.read("/api/v1/jobs/-general/talk/script")
        self.assertEqual((404, "no_talk"), (code, json.loads(body).get("error")))
        self.assertEqual(404, self.read("/api/v1/jobs/-general/talk/slides/1.png")[0])
        self.assertEqual(200, self.read("/api/v1/jobs/-general/talk")[0])  # its state: no brief, not made

    def test_the_talk_script_and_its_pictures(self):
        api = type(self).srv.RequestHandlerClass.panel  # the panel's API: where it keeps the job's talk
        folder = api.tasks.talk_folder(self.job)
        (folder / "thumbs").mkdir(parents=True, exist_ok=True)
        (folder / "thumbs" / "slide-1.png").write_bytes(png())  # one slide, one picture
        talk = {"company": "감마클라우드", "brief": {"lang": "ko", "minutes": 10}, "parts": [], "checks": {"pace": [{"page": 1}]},
                "slides": [{"kind": "cover", "page": 1, "seconds": 45, "title": "홍길동", "part": -1,
                            "script": {"cue": "이름", "lines": ["**결제** 플랫폼을 ==맡아 온== 홍길동입니다."], "short": "이름만",
                                       "questions": [{"q": "왜 이 회사인가요?", "a": "결제 경험을 이어 가려고"}]}}]}
        (folder / "talk.json").write_text(json.dumps(talk, ensure_ascii=False), encoding="utf-8")
        try:
            code, _, body = self.read(f"/api/v1/jobs/{q(self.job)}/talk/script")
            self.assertEqual(200, code)
            d = json.loads(body)
            s = d["slides"][0]
            self.assertEqual(("0:45", "0:45", True, "이름만"), (s["time"], s["run"], s["picture"], s["short"]))  # its time, the total, its picture
            self.assertEqual(["**결제** 플랫폼을 ==맡아 온== 홍길동입니다."], s["lines"])  # as written: the panel draws the marks
            self.assertEqual([{"q": "왜 이 회사인가요?", "a": "결제 경험을 이어 가려고", "page": 1}], d["qa"])
            self.assertEqual(1, len(d["notes"]))  # what the pace check found
            self.assertIn("감마클라우드", d["title"])
            self.assertIsInstance(d["at"], int)  # the pictures' addresses change with each new talk
            code, headers, body = self.read(f"/api/v1/jobs/{q(self.job)}/talk/slides/1.png")
            self.assertEqual((200, "image/png", png()), (code, headers.get("Content-Type"), body))
            for n in ("0", "2", "999"):  # no picture there
                self.assertEqual(404, self.read(f"/api/v1/jobs/{q(self.job)}/talk/slides/{n}.png")[0], n)
            self.assertEqual(404, self.read(f"/api/v1/jobs/{q(self.job)}/talk/slides/..%2Ftalk.png")[0])  # never a name from the request
        finally:
            (folder / "talk.json").unlink()

    def test_the_page_plays_a_recording_and_frames_nothing(self):
        code, headers, _ = self.read("/")
        self.assertEqual(200, code)
        csp = headers.get("Content-Security-Policy") or ""
        self.assertIn("media-src 'self' blob:", csp)  # a practice answer played back from its recording in the page
        self.assertIn("frame-src 'none'", csp)  # no page in a frame any more, of this address or another (the previews are written into theirs)
        self.assertIn("frame-ancestors 'none'", csp)


if __name__ == "__main__":
    unittest.main()
