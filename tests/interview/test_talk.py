"""The talk (src/interview/talk.py): the brief's kinds and minutes, the plan's slides and times, the pace check, and the whole run
on the fictional example, with no agent and with the stand-in agent (apps/api/standin.py). The runs draw and print the deck with
the PC's browser, so they are skipped where Node.js or a browser is missing."""
import json  # the talk's record
import os  # the renderer and the stand-in's address
import pathlib  # paths
import shutil  # Node.js, and the output folder
import sys  # the stand-in's import path
import tempfile  # an output folder per run
import threading  # the stand-in serves in this process
import unittest  # the runner

from helpers import example_job  # the fictional job, with the import path set

from interview import talk  # the talk

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository


def can_draw() -> bool:
    """Node.js and a browser that prints, as the html renderer needs them (the runs below use that renderer, never the container)."""
    if not shutil.which("node"):
        return False
    sys.path.insert(0, str(ROOT / "src"))
    try:
        import resume  # noqa: E402
        return not resume.html_renderer().doctor()["html"]["needs"]
    except Exception:  # noqa: BLE001  no browser, no fonts: the runs are skipped
        return False


class BriefTest(unittest.TestCase):
    def test_kinds_from_the_words(self):
        """A topic's words name what it asks for, in Korean and in English; 'why us, and your plan' is both."""
        self.assertEqual(talk.kinds_of("본인의 소개 및 핵심 역량"), ["intro"])
        self.assertEqual(talk.kinds_of("과제/업무를 통해 배운 경험 및 기술"), ["experience"])
        self.assertEqual(talk.kinds_of("가장 도전적이었던 문제를 돌파한 과정"), ["challenge"])
        self.assertEqual(talk.kinds_of("지원 계기 및 향후 커리어 계획"), ["motivation", "plan"])
        self.assertEqual(talk.kinds_of("The hardest problem you solved"), ["challenge"])
        self.assertEqual(talk.kinds_of("Why this company?"), ["motivation"])
        self.assertEqual(talk.kinds_of("A system you would design for us"), ["custom"])

    def test_defaults_and_minutes(self):
        """No brief: the usual four topics share the half hour; given minutes stay, the rest is shared by what each asks."""
        b = talk.normalize({}, "ko")
        self.assertEqual(len(b["topics"]), 4)
        self.assertAlmostEqual(sum(t["minutes"] for t in b["topics"]), 30, delta=0.5)
        b = talk.normalize({"minutes": 40, "topics": [{"title": "소개", "minutes": 10}, "경험과 기술"]}, "ko")
        self.assertEqual(b["topics"][0]["minutes"], 10)
        self.assertAlmostEqual(b["topics"][1]["minutes"], 30, delta=0.5)

    def test_odd_briefs(self):
        """A second topic of a kind becomes a topic of the person's own; given minutes that run over the length are scaled so
        every topic keeps time; values that are not topics or swaps are left out instead of stopping the run."""
        b = talk.normalize({"topics": ["가장 어려웠던 문제", "실패를 극복한 경험"]}, "ko")
        self.assertEqual([t["kinds"] for t in b["topics"]], [["challenge"], ["custom"]])
        b = talk.normalize({"minutes": 30, "topics": [{"title": "소개", "minutes": 20}, {"title": "경험", "minutes": 20}, "지원 계기"]}, "ko")
        self.assertAlmostEqual(sum(t["minutes"] for t in b["topics"]), 30, delta=0.6)
        self.assertGreaterEqual(b["topics"][2]["minutes"], 1)
        b = talk.normalize({"topics": [None, 5, "소개"], "swaps": [["a"], ["b", "c"], "x"], "pages": [3, "4", True, "9999"]}, "ko")
        self.assertEqual([t["title"] for t in b["topics"]], ["소개"])
        self.assertEqual(b["swaps"], [["b", "c"]])
        self.assertEqual(b["pages"], [3, 4])
        self.assertEqual(talk.kinds_of("커리어 중 가장 의미 있었던 프로젝트"), ["experience"])
        self.assertEqual(talk.kinds_of("가장 자신 있는 프로젝트"), ["experience"])

    def test_bad_values_fall_back(self):
        """A theme that is not two hex colours is no theme; a length out of range is half an hour; no topic is an error."""
        b = talk.normalize({"minutes": 500, "theme": {"frame": "black", "accent": "#d9480f"}}, "en")
        self.assertEqual(b["minutes"], 30)
        self.assertIsNone(b["theme"])
        with self.assertRaises(talk.TalkError):
            talk.normalize({"topics": [{"title": " "}]}, "ko")


def fake_info():
    """A portfolio of four projects and a profile with strengths, as talk_slides.js --pages reports them."""
    slides = [{"n": 1, "kind": "front", "title": "홍길동", "tag": "", "period": "", "project": None, "text": ""}]
    for i, (t, per) in enumerate([("결제 승인 서비스 재설계", "2023.01 ~ 2023.09"), ("사내 배포 플랫폼 구축", "2023.10 ~ 2024.06"),
                                  ("주문 이벤트 파이프라인 개발", "2020.03 ~ 2021.04"), ("첫 서비스 백엔드", "2017.07 ~ 2019.06")], 2):
        slides.append({"n": i, "kind": "project", "title": t, "tag": per, "period": per, "project": f"p{i}", "text": t})
    slides.append({"n": 6, "kind": "end", "title": "홍길동", "tag": "", "period": "", "project": None, "text": ""})
    view = {"person": {"name": "홍길동"}, "summary": {"highlights": [{"title": "주문 이벤트 파이프라인", "rows": [["문제", "a"], ["한 일", "b"], ["결과", "c"]]}]},
            "competencies": [{"name": "결제 백엔드", "text": "승인과 정산"}], "roles": [], "education": [], "skills": []}
    return {"own": False, "slides": slides, "view": view}


class PlanTest(unittest.TestCase):
    def test_order_and_story(self):
        """The talk opens with the cover and the agenda, gives each part its divider, shows the story's project in its own part
        only, keeps the experience in time order, and ends with the questions. No slide holds the posting against the record."""
        b = talk.normalize({}, "ko")
        slides = talk.plan(b, fake_info(), {"items": [{"kind": "duty", "text": "결제 백엔드 운영"}]})
        kinds = [s["kind"] for s in slides]
        self.assertEqual(kinds[:3], ["cover", "agenda", "chapter"])
        self.assertEqual(kinds[-1], "end")
        self.assertNotIn("fit", kinds)
        story = [s for s in slides if s["kind"] == "page" and s["part"] == 2]
        self.assertEqual([s["title"] for s in story], ["주문 이벤트 파이프라인 개발"])
        exp = [s for s in slides if s["kind"] == "page" and s["part"] == 1]
        self.assertNotIn("주문 이벤트 파이프라인 개발", [s["title"] for s in exp])
        starts = [talk.start_of(s["period"]) for s in exp]
        self.assertEqual(starts, sorted(starts))
        for k in ("problem", "approach", "result", "why", "plan", "lessons"):
            self.assertIn(k, kinds)

    def test_no_story_without_its_topic(self):
        """With no topic asking for the hardest problem, its project stays with the rest of the work."""
        b = talk.normalize({"topics": ["소개", "경험과 기술"], "minutes": 30}, "ko")
        slides = talk.plan(b, fake_info(), None)
        self.assertIn("주문 이벤트 파이프라인 개발", [s["title"] for s in slides if s["kind"] == "page"])
        self.assertNotIn("problem", [s["kind"] for s in slides])

    def test_a_part_with_nothing_leaves(self):
        """Made without the agent, a topic of the person's own has no slide: its divider leaves, the parts are numbered again,
        their minutes keep the talk's length, and the record says why."""
        b = talk.normalize({"topics": ["소개", "우리 서비스에 바라는 점", "경험과 기술"], "minutes": 30}, "ko")
        slides = talk.plan(b, fake_info(), None)
        parts = [{"no": f"{i + 1:02d}", "title": t["title"], "short": "", "minutes": round(t["minutes"])} for i, t in enumerate(b["topics"])]
        talk_ = {"parts": parts}
        record = {"dropped": []}
        kept = talk.prune_parts([s for s in slides if s["kind"] != "points"], talk_, b, record)
        self.assertEqual([p["no"] for p in talk_["parts"]], ["01", "02"])
        self.assertEqual(len([s for s in kept if s["kind"] == "chapter"]), 2)
        self.assertAlmostEqual(sum(t["minutes"] for t in b["topics"]), 30, delta=0.6)
        self.assertEqual(record["dropped"][0]["text"], "우리 서비스에 바라는 점")

    def test_times_add_up(self):
        """Each part's minutes are shared by its slides, so the talk's seconds come to the brief's minutes."""
        b = talk.normalize({"minutes": 40}, "ko")
        slides = talk.plan(b, fake_info(), None)
        talk.timing(slides, b)
        self.assertAlmostEqual(sum(s["seconds"] for s in slides), 40 * 60, delta=5 * len(slides))

    def test_pace(self):
        """A slide whose words are far too few or too many for its time is named; a drafted script is not measured."""
        slides = [{"key": "a", "page": 1, "seconds": 120, "script": {"lines": ["가" * 100]}},
                  {"key": "b", "page": 2, "seconds": 120, "script": {"lines": ["가" * 440]}},
                  {"key": "c", "page": 3, "seconds": 120, "script": {"lines": ["가" * 10], "rule": True}}]
        self.assertEqual([x["key"] for x in talk.pace_checks(slides, "ko")], ["a"])


@unittest.skipUnless(can_draw(), "no Node.js or no browser that prints on this PC")
class RunTest(unittest.TestCase):
    """The whole run on the fictional job. Slow: it draws the portfolio and prints the deck."""

    @classmethod
    def setUpClass(cls):
        cls.renderer = os.environ.get("OFFEROWL_RENDERER")  # put back afterwards
        os.environ["OFFEROWL_RENDERER"] = "html"  # the PC's browser prints: the container's image may not be built here

    @classmethod
    def tearDownClass(cls):
        if cls.renderer is None:
            os.environ.pop("OFFEROWL_RENDERER", None)
        else:
            os.environ["OFFEROWL_RENDERER"] = cls.renderer

    def run_talk(self, backend):
        out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-talk-"))
        self.addCleanup(shutil.rmtree, out, True)
        summary = talk.make(example_job(), lang="ko", backend=backend, out=str(out), pdf=False, log=lambda *_: None)
        folder = out / "talk"
        return summary, json.loads((folder / "talk.json").read_text(encoding="utf-8")), folder

    def test_without_an_agent(self):
        """With no agent the talk is the documents' own words: a deck with no layout defect, the story told on one slide, and a
        script marked as a draft on every slide."""
        summary, made, folder = self.run_talk("none")
        self.assertEqual(summary["layout"], 0, made["checks"]["layout"])
        self.assertTrue((folder / "deck.pdf").is_file())
        kinds = [s["kind"] for s in made["slides"]]
        self.assertIn("story", kinds)
        self.assertNotIn("lessons", kinds)  # only the agent writes them
        self.assertTrue(all(s["script"].get("rule") for s in made["slides"]))
        self.assertEqual(made["record"]["calls"], 0)
        html = (folder / "script.html").read_text(encoding="utf-8")
        self.assertIn(made["slides"][3].get("title") or "", html)

    def test_with_the_stand_in(self):
        """With the stand-in agent every text rests on the evidence by construction: the slides get their own words, every slide
        a script of its own, and what failed the checks is listed with its reasons."""
        sys.path.insert(0, str(ROOT / "apps" / "api"))
        import standin  # noqa: E402
        srv = standin.serve(0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        old = {k: os.environ.get(k) for k in ("OFFEROWL_LLM_URL", "OFFEROWL_LLM_MODEL")}
        os.environ.update(OFFEROWL_LLM_URL=f"http://127.0.0.1:{srv.server_address[1]}", OFFEROWL_LLM_MODEL="standin")
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in old.items()])
        summary, made, folder = self.run_talk("openai-compat")
        self.assertGreater(made["record"]["calls"], 4)
        kinds = [s["kind"] for s in made["slides"]]
        for k in ("lessons", "problem", "approach", "result"):
            self.assertIn(k, kinds)
        self.assertTrue(any(not s["script"].get("rule") for s in made["slides"]))
        self.assertTrue(all("why" in d for d in made["checks"]["dropped"]))
        self.assertEqual(summary["layout"], 0, made["checks"]["layout"])


if __name__ == "__main__":
    unittest.main()
