"""The kit's writes are undo steps of their own (round 3, C3-02 and C3-05): scenes brought in, a kit carried and the question map
made each take back with the files the map's maker wrote, and the bar's Undo never reaches an older change. The same file sent
twice is refused with its own reason. Round 4: an undo takes back the folders its step made (C4-03), a file that is not .md or
.txt is refused and the files of one pick are one step (C4-13), the scenes a person added are counted and a renumbered one is
named (C4-06). No model is called.

    python3 -m unittest tests/app/test_kit_undo.py -v
"""
import json  # answers
import os  # the similarity model's setting
import pathlib  # paths
import sys  # the import path
import unittest  # the runner
import urllib.error  # refusals
import urllib.request  # the upload

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "src"))  # the kit's own modules
sys.path.insert(0, str(ROOT / "tests" / "app"))  # the shared test case
from test_panel import POSTING, PanelCase, q  # noqa: E402  one server and workspace per class, on the fictional example

EXAMPLE = ROOT / "examples" / "interview" / "jobs" / "gamma-platform" / "interview"  # the fictional example's scripts


class TestKitUndo(PanelCase):
    """One job whose kit is made, then written to."""

    @classmethod
    def setUpClass(cls):
        cls.model_setting = os.environ.pop("OFFEROWL_SEARCH_MODEL", None)  # no similarity model on this PC's setting
        super().setUpClass()
        case = cls("test_a_map_is_a_step_of_its_own")  # the shared helpers need an instance
        case.start_profile()  # the example's facts, kept
        cls.job = case.post("/api/v1/jobs", {"company": "감마클라우드", "role": "백엔드 플랫폼 엔지니어", "posting": POSTING.read_text(encoding="utf-8")})["job"]

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if cls.model_setting is not None:  # this PC's own setting back
            os.environ["OFFEROWL_SEARCH_MODEL"] = cls.model_setting

    def send(self, path: pathlib.Path):
        """Scripts written before, sent as the page sends a picked file; (status, answer)."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/interview/scenes?job={q(self.job)}", data=path.read_bytes(), method="POST",
                                     headers={"Content-Type": "application/octet-stream", "X-File-Name": q(path.name), "Origin": f"http://127.0.0.1:{self.port}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:  # a refusal
            return e.code, json.loads(e.read())

    def scenes(self, job: str, name: str, text: str, join: str = ""):
        """Scenes written in the test, sent under a name as the page sends a picked file, joined to an earlier step when one is
        named (the page's later files of one pick); (status, answer)."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/interview/scenes?job={q(job)}" + (f"&join={q(join)}" if join else ""),
                                     data=text.encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/octet-stream", "X-File-Name": q(name), "Origin": f"http://127.0.0.1:{self.port}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:  # a refusal
            return e.code, json.loads(e.read())

    def steps(self):
        """The undo steps' names, newest first."""
        return [s["id"] for s in self.get("/api/v1/history")["steps"]]

    def later(self, answer: dict) -> dict:
        """An answer whose step is taken back after the test, pass or fail (the cleanups run newest first, as undo goes): the
        class's job is as it was for the next test."""
        step = (answer or {}).get("step")
        if step:
            self.addCleanup(lambda: step in self.steps() and self.post("/api/v1/undo", {"only": step}))
        return answer

    def plan(self):
        """The map as written now, and the kit's files the maker writes."""
        api = type(self).srv.RequestHandlerClass.panel  # the panel's API
        f = api.ws.path("out", "interview", self.job, "plan.json")  # the map
        return (f.read_text(encoding="utf-8") if f.is_file() else None), api.ws.job_dir(self.job) / "interview"

    def test_c_an_undone_carry_or_scenes_leave_no_folder_they_made(self):
        """C4-03: a job with no kit gets its kit's folders from a carry or from scenes sent to it; the Undo of either takes the
        folders back with the files, so the job is again one with no kit (its pages answered a deck of 0 scripts before)."""
        api = type(self).srv.RequestHandlerClass.panel  # the panel's API
        bare = self.post("/api/v1/jobs", {"company": "델타페이먼츠", "role": "SRE", "posting": POSTING.read_text(encoding="utf-8")})["job"]
        iv, out = api.ws.job_dir(bare) / "interview", api.ws.path("out", "interview", bare)  # the folders a kit has
        self.assertEqual((False, False), (iv.exists(), out.exists()))  # none yet
        self.later(self.post("/api/v1/interview/kit", {"job": self.job, "lang": "ko"}))  # a kit to carry from
        code, sent = self.send(EXAMPLE / "qa.md")
        self.assertEqual(200, code)
        self.later(sent)
        carried = self.later(self.post("/api/v1/interview/carry", {"job": bare, "from": self.job}))  # the whole kit into the bare job
        self.assertEqual((True, True), (iv.is_dir(), out.is_dir()))
        self.post("/api/v1/undo", {"only": carried["step"]})
        self.assertEqual((False, False), (iv.exists(), out.exists()))  # gone with the carry
        code, got = self.scenes(bare, "mine.md", (EXAMPLE / "qa.md").read_text(encoding="utf-8"))  # scenes into the bare job
        self.assertEqual(200, code)
        self.later(got)
        self.assertEqual((True, True), (iv.is_dir(), out.is_dir()))
        self.post("/api/v1/undo", {"only": got["step"]})
        self.assertEqual((False, False), (iv.exists(), out.exists()))  # gone with the scenes
        self.assertTrue(api.ws.job_dir(bare).is_dir())  # the job itself stays

    def test_d_a_document_is_refused_and_the_files_of_one_pick_are_one_step(self):
        """C4-13: scenes come as .md or .txt: a file named otherwise is refused with its own code, whatever its bytes; the files
        of one pick join one undo step (join), and its Undo takes all of them back. A join to a step that is no longer the
        newest makes a step of its own."""
        self.later(self.post("/api/v1/interview/kit", {"job": self.job, "lang": "ko"}))
        _, iv = self.plan()
        one = "### X1. 첫 장면 / First scene\n\n**면접관** Hi?\n**해석** 안녕하세요?\n**나** Hello.\n**해석** 안녕하세요.\n"
        two = "### X2. 둘째 장면 / Second scene\n\n**면접관** Why?\n**해석** 왜요?\n**나** Because.\n**해석** 그래서요.\n"
        for name in ("notes.docx", "deck.pptx", "scenes"):  # a document, a deck, no kind at all
            code, got = self.scenes(self.job, name, one)
            self.assertEqual((400, "scenes_kind"), (code, got.get("error")), name)
        self.assertFalse((iv / "notes.md").exists())  # nothing kept under a made-up name
        before = self.steps()
        code, a = self.scenes(self.job, "first.md", one)
        self.assertEqual(200, code)
        self.later(a)
        code, b = self.scenes(self.job, "second.txt", two, join=a["step"])  # the pick's next file
        self.assertEqual(200, code)
        self.assertEqual(len(before) + 1, len(self.steps()))  # one step for both
        self.assertEqual(a["step"], b["step"])  # named the same: the note's Undo takes both
        self.post("/api/v1/undo", {"only": b["step"]})
        self.assertEqual((False, False), ((iv / "first.md").exists(), (iv / "second.md").exists()))
        self.assertEqual(before, self.steps())
        code, a = self.scenes(self.job, "first.md", one)
        self.later(a)
        self.later(self.post("/api/v1/interview/kit", {"job": self.job, "lang": "en"}))  # a step of another kind meanwhile
        code, b = self.scenes(self.job, "second.md", two, join=a["step"])
        self.assertEqual(200, code)
        self.later(b)
        self.assertNotEqual(a["step"], b["step"])  # not joined over the step between

    def test_e_scenes_you_added_are_counted_and_a_renumbered_one_is_named(self):
        """C4-06: the board counts the scenes the person added (counts.own), whatever their lines hold; a scene whose number the
        kit has already comes in under the next free one, and the answer names it."""
        self.later(self.post("/api/v1/interview/kit", {"job": self.job, "lang": "ko"}))
        board = lambda: self.get(f"/api/v1/jobs/{q(self.job)}/interview?lang=ko")["counts"]  # noqa: E731  the map's numbers
        self.assertEqual(0, board().get("own", 0))
        code, a = self.scenes(self.job, "mine.md", "### Z9. 새 장면 / New scene\n\n**면접관:** 질문?\n\n**나:** 대답입니다.\n")   # labels as a person may write them
        self.assertEqual(200, code)
        self.later(a)
        self.assertEqual([], a.get("renamed"))
        self.assertEqual(1, board()["own"])
        code, b = self.scenes(self.job, "mine2.md", "### Z9. 장면 둘 / Second\n\n**면접관** Hi?\n**나** Hello.\n", join=a["step"])
        self.assertEqual(200, code)
        self.assertEqual([["Z9", "Z9-2"]], b["renamed"])  # named in the answer, as it is in the kit
        self.assertEqual(2, board()["own"])
        code, c = self.scenes(self.job, "aa.md", "### Z9. 장면 셋 / Third\n\n**면접관** Hey?\n**나** Hi.\n", join=a["step"])   # read first by its name: the kit's own scenes move on
        self.assertEqual(200, code)
        self.assertEqual([["Z9", "Z9-2"], ["Z9-2", "Z9-3"]], c["renamed"])  # every number that changed, though the new file kept its own
        self.assertEqual(3, board()["own"])
        self.post("/api/v1/undo", {"only": c["step"]})  # one step for the three files
        self.assertEqual(0, board().get("own", 0))

    def test_f_scenes_keep_the_map_s_language(self):
        """Scenes added to a kit whose map was made in English make it again in English: the map was made again in Korean,
        and an English kit's 496 questions became 323 (found with C4-06)."""
        self.later(self.post("/api/v1/interview/kit", {"job": self.job, "lang": "en"}))
        plan, iv = self.plan()
        self.assertEqual("en", json.loads((iv / "kit.json").read_text(encoding="utf-8"))["ui"])
        code, got = self.scenes(self.job, "mine.md", "### Z9. 새 장면 / New scene\n\n**면접관** Hi?\n**해석** 안녕하세요?\n**나** Hello.\n**해석** 안녕하세요.\n")
        self.assertEqual(200, code)
        self.later(got)
        self.assertEqual("en", json.loads((iv / "kit.json").read_text(encoding="utf-8"))["ui"])  # still the map's language
        after, _ = self.plan()
        self.assertEqual(len(json.loads(plan)["questions"]), len(json.loads(after)["questions"]))  # the same questions, now with a scene beside them

    def test_a_map_is_a_step_of_its_own(self):
        """Making the map puts its files in a step; the bar's Undo takes back the map and nothing older."""
        steps = len(self.get("/api/v1/history")["steps"])  # what the history holds before
        made = self.post("/api/v1/interview/kit", {"job": self.job, "lang": "ko"})  # the map, no model
        self.assertTrue(made["step"])  # named in the answer
        self.assertEqual("undo_map", self.get("/api/v1/history")["steps"][0]["label"]["code"])  # its own kind of step
        self.assertEqual(steps + 1, len(self.get("/api/v1/history")["steps"]))  # one more
        self.post("/api/v1/undo", {"only": made["step"]})  # its Undo
        plan, iv = self.plan()
        self.assertIsNone(plan)  # no map
        self.assertFalse((iv / "kit.json").exists())  # no kit either: the job reads as it did
        self.assertEqual(steps, len(self.get("/api/v1/history")["steps"]))  # the older steps are all still there

    def test_scenes_undo_with_the_map_and_a_file_sent_twice_is_refused(self):
        self.post("/api/v1/interview/kit", {"job": self.job, "lang": "ko"})  # a kit
        before, iv = self.plan()
        n_before = len(json.loads(before)["questions"])
        covered = lambda text: sum(1 for r in json.loads(text)["questions"] if r.get("covered_by"))  # the questions a script answers
        code, got = self.send(EXAMPLE / "qa.md")  # scripts brought in
        self.assertEqual(200, code)
        self.assertTrue(got["step"])  # an undo step of its own, named in the answer
        after, _ = self.plan()
        self.assertGreater(covered(after), covered(before))  # the map sees the scripts
        code, again = self.send(EXAMPLE / "qa.md")  # the same file again
        self.assertEqual((400, "already_there"), (code, again["error"]))  # refused, with its reason
        self.assertEqual(1, len(list(iv.glob("qa*.md"))))  # no second copy
        self.assertEqual("undo_scenes", self.get("/api/v1/history")["steps"][0]["label"]["code"])  # the bar's Undo is this step
        self.post("/api/v1/undo", {"only": got["step"]})  # taken back
        back, _ = self.plan()
        self.assertEqual(before, back)  # the map as it was: no covered_by naming scenes that are gone
        self.assertEqual(n_before, len(json.loads(back)["questions"]))
        self.assertFalse(list(iv.glob("qa*.md")))  # the file went with it
        self.post("/api/v1/undo", {})  # the kit itself, for the next test


if __name__ == "__main__":
    unittest.main()
