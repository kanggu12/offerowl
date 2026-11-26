"""The kit's writes are undo steps of their own (round 3, C3-02 and C3-05): scenes brought in, a kit carried and the question map
made each take back with the files the map's maker wrote, and the bar's Undo never reaches an older change. The same file sent
twice is refused with its own reason. No model is called.

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

    def plan(self):
        """The map as written now, and the kit's files the maker writes."""
        api = type(self).srv.RequestHandlerClass.panel  # the panel's API
        f = api.ws.path("out", "interview", self.job, "plan.json")  # the map
        return (f.read_text(encoding="utf-8") if f.is_file() else None), api.ws.job_dir(self.job) / "interview"

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
