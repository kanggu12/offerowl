"""The Insights view's numbers and the Library's list, on the fictional example: how a result's own words are read, how
far an application got, how a requirement line is sorted into an area (the hiring's own lines left out, "data center"
not taken for data), the career's spans; then GET /api/v1/insights and GET /api/v1/library on a running panel, every
file the Library offers to open answering, and a path that is not one of its files refused.

    python3 -m unittest tests/app/test_insights_library.py -v
"""
import os  # the Desktop the tests use
import pathlib  # paths
import sys  # the import path
import unittest  # the runner
import urllib.error  # a refused read
import urllib.request  # reads of files
from datetime import date  # "until now"

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "tests" / "app"))  # the shared test case
from apps.api import insights as I  # noqa: E402  the numbers
from test_panel import POSTING, PanelCase, q  # noqa: E402  one server and workspace per class, on the fictional example


class TestReading(unittest.TestCase):
    """The rules the numbers rest on, without a server."""

    def test_result_words(self):
        self.assertEqual("rejected", I.result_kind("result", "탈락(서류 합격 뒤 2차 면접)"))   # a rejection after a passed round
        self.assertEqual("rejected", I.result_kind("result", "불합격"))   # 불합격 holds 합격: read as a rejection
        self.assertEqual("closed", I.result_kind("result", "정리(지원 취소)"))
        self.assertEqual("offer", I.result_kind("result", "최종 합격"))
        self.assertEqual("none", I.result_kind("result", "지원 기간 끝남"))   # ended, nothing said of how
        self.assertEqual("open", I.result_kind("interview", "탈락"))   # a card still going has no end yet
        for words in ("1차 면접 미합격", "No offer", "오퍼 없음", "합격하지 못함"):   # words that hold 합격 or offer and say the opposite
            self.assertEqual("rejected", I.result_kind("result", words), words)

    def test_how_far(self):
        self.assertEqual({"submitted": True, "interview": True, "offer": False}, I.reached({"stage": "interview", "dates": {}}))
        self.assertEqual({"submitted": True, "interview": False, "offer": False}, I.reached({"stage": "result", "result": "탈락", "dates": {}}))   # a rejection answers a submission
        self.assertEqual({"submitted": False, "interview": False, "offer": False}, I.reached({"stage": "result", "result": "정리", "dates": {}}))
        self.assertEqual({"submitted": True, "interview": True, "offer": True}, I.reached({"stage": "result", "result": "최종 합격", "dates": {}}))   # an offer went through both: the funnel never grows

    def test_spans(self):
        today = date(2026, 11, 9)
        self.assertEqual((date(2026, 4, 1), date(2026, 8, 1), False), I.span("26.04 ~ 26.08", today))   # a two-digit year is this century's
        self.assertEqual((date(2023, 3, 1), date(2026, 11, 1), True), I.span("2023.03 ~", today))   # open: until now
        self.assertIsNone(I.span("3년", today))   # no year: no span to draw
        self.assertEqual((date(2016, 1, 1), date(2019, 12, 1), False), I.span("2016-2019", today))   # the second year is not a month of the first
        self.assertEqual((date(1999, 3, 1), date(2003, 2, 1), False), I.span("99.03 ~ 03.02", today))   # a two-digit year in the future is last century's
        self.assertEqual((date(2019, 2, 1), date(2019, 2, 1), False), I.span("2019.02", today))   # one month, never "until now" without a mark
        self.assertEqual(5, I.months(date(2026, 4, 1), date(2026, 8, 1)))   # April to August is five months, as a resume counts it

    def test_areas(self):
        a = I.Areas([("Cluster/HPC", ["Slurm", "xCAT"]), ("Collaboration", ["Jira"])])   # the person's groups
        self.assertEqual("process", a.of("국가보훈대상자 및 장애인은 우대하여 채용합니다"))   # 장애인 is not an outage
        self.assertEqual("process", a.of("45min culture interview"))   # a round of the hiring
        self.assertEqual("GPU & HPC", a.of("AI 데이터센터 구축 경험"))   # a data center is infrastructure, not data
        self.assertEqual("GPU & HPC", a.of("Experience running Slurm at scale"))   # the person's own tool joins its group's area
        self.assertEqual("Data & analytics", a.of("A/B 테스트와 통계적 가설검정 경험"))
        self.assertEqual("Communication", a.of("Outstanding verbal and written communication skills"))
        self.assertEqual("Other", a.of("Join a brilliant team"))
        self.assertEqual("이과 졸업", I.plain_text("{'ko': '이과', 'en': 'Science track'} {'ko': '졸업', 'en': 'Graduated'}"))   # a printed two-language value


class TestInsightsAndLibrary(PanelCase):
    """The two reads on the example with one application."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        case = cls("test_numbers")   # the shared helpers need an instance
        case.start_profile()   # the example's facts, kept
        cls.jid = case.post("/api/v1/jobs", {"company": "감마클라우드", "role": "백엔드 플랫폼 엔지니어", "posting": POSTING.read_text(encoding="utf-8")})["job"]

    def test_numbers(self):
        d = self.get("/api/v1/insights")
        f = d["funnel"]
        self.assertGreaterEqual(f["added"], 1)
        self.assertTrue(f["added"] >= f["submitted"] >= f["interview"] >= f["offer"])   # each step a part of the one before
        self.assertEqual(f["added"], d["kpi"]["applications"])
        self.assertEqual(10, len(d["weeks"]))   # the last ten weeks, this one last
        fit = self.get(f"/api/v1/jobs/{q(self.jid)}/fit")   # the posting's lines, rated
        counted = sum(a["demand"] for a in d["areas"]) + d["unsorted"]["other"] + d["unsorted"]["process"]
        self.assertEqual(len(fit["lines"]), counted)   # every line lands in an area, or is counted apart
        for a in d["areas"]:   # each area's parts add up
            self.assertEqual(a["demand"], a["strong"] + a["weak"] + a["none"])
        self.assertTrue(d["evidence"]["kinds"])   # the facts by kind
        self.assertTrue(any(r["job"] == self.jid for r in d["ready"]))   # an open application is on the readiness list

    def test_library_lists_and_opens(self):
        d = self.get("/api/v1/library")
        rows = d["rows"]
        self.assertEqual(sum(d["counts"].values()), len(rows))
        self.assertTrue(any(r["group"] == "source" for r in rows))   # the example's file
        self.assertTrue(any(r["id"] == "posting:" + self.jid for r in rows))   # the pasted posting
        for r in [r for r in rows if r.get("open")][:6]:   # what it offers to open answers
            ctype, body = self.raw_get(r["open"])
            self.assertTrue(body, r["open"])
        made = next((r for r in rows if r.get("export") and r["group"] == "source"), None)   # copying a row copies that very file
        if made:
            name = self.post(made["export"]["path"], made["export"]["body"])["exported"][0]
            desk = pathlib.Path(os.environ["OFFEROWL_DESKTOP"])
            self.assertTrue((desk / name).is_file(), name)
            self.assertEqual(self.raw_get(made["open"])[1], (desk / name).read_bytes())   # byte for byte what the row opens
        self.post("/api/v1/library/export", {"id": "made:nothing:ko:resume.pdf"}, expect=400)   # a row with no file is refused, never "copied"
        for r in rows:   # every action names a write route
            for k in ("export", "remove"):
                if r.get(k):
                    self.assertTrue(r[k]["path"].startswith("/api/v1/"))

    def test_the_kit_lists_its_scripts_not_its_workings(self):
        """The Library's interview kit rows are the scripts: the agent's drafts file (never its rejected scenes), not the
        settings and texts the panel writes into every kit; Insights counts the questions a draft answers apart."""
        self.post("/api/v1/interview/kit", {"job": self.jid, "lang": "ko"})   # the question map, on this PC
        api = self.srv.RequestHandlerClass.panel   # the running API
        drafts = api.ws.path("out", "interview", self.jid, "drafts")   # where the agent's drafts go
        drafts.mkdir(parents=True, exist_ok=True)
        scene = "# drafts\n\n## D. 인성\n\n### D1. 자기소개 / Tell me about yourself.\n\n**면접관** Tell me about yourself.\n**해석** 자기소개 부탁드립니다.\n**나** I build payment backends.\n**해석** 결제 백엔드를 만듭니다.\n"
        (drafts / "drafts-1.md").write_text(scene, encoding="utf-8")
        (drafts / "drafts-1.rejected.md").write_text("rejected\n", encoding="utf-8")   # a side file the check keeps
        rows = [r for r in self.get("/api/v1/library")["rows"] if r["group"] == "kit"]
        names = {r["name"] for r in rows}
        self.assertIn("drafts-1.md", names)   # the drafts are listed
        self.assertFalse(names & {"kit.json", "names.txt", "portfolio.txt", "resume.txt", "drafts-1.rejected.md"}, names)   # the workings and the rejected scenes are not
        row = next(r for r in rows if r["name"] == "drafts-1.md")
        self.assertTrue(row["note"].get("draft"))   # said to be the agent's
        self.assertEqual((drafts / "drafts-1.md").read_bytes(), self.raw_get(row["open"])[1])   # and it opens that very file, byte for byte (CRLF on Windows, where write_text wrote it so)
        ready = next(r for r in self.get("/api/v1/insights")["ready"] if r["job"] == self.jid)
        self.assertIn("draft", ready["coverage"] or {})   # the drafts' questions counted apart, as the map draws them

    def test_refuses_what_is_not_its_file(self):
        for path in (f"/api/v1/jobs/{q(self.jid)}/kit/..", f"/api/v1/jobs/{q(self.jid)}/kit/out/secret.md",   # no climbing out, only the made files
                     f"/api/v1/jobs/{q(self.jid)}/sent/resume.pdf",   # nothing was sent: no copy to give
                     f"/api/v1/jobs/{q(self.jid)}/kit/..%2F..%2Fprofile%2Fprofile.json", "/api/v1/materials/m999"):
            with self.assertRaises(urllib.error.HTTPError, msg=path) as e:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}")
            self.assertEqual(404, e.exception.code, path)


if __name__ == "__main__":
    unittest.main()
