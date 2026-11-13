#!/usr/bin/env python3
"""The document checks of 0.10.0 on a real typeset resume: phrases fixed once, the edition against the profile, the shape kept
and what the pages show (src/check_claims.py, src/check_ledger.py, src/check_pages.py). The fictional full example passes
every rule held to values it meets; a seeded copy of it fails on each one. Typeset in the render container, as the panel's
builds are, and checked there with the ledger and the edition's kind the build hands over.
  python3 -m unittest tests/render/test_rules_typeset.py -v
"""
import copy  # the seeded copy
import json  # profiles, packs and reports
import os  # the checks' language
import pathlib  # paths
import shutil  # the test's folder
import sys  # the import path
import tempfile  # a folder the container sees
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT / "src", ROOT / "tests" / "render"):  # the engine, the helpers beside this file
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from test_blind_figures import render_image  # noqa: E402  is the render container's image here
import resume  # noqa: E402  the typesetting

EXAMPLE = ROOT / "examples" / "sample_full_ko.json"  # the fictional full example: logos, a badge, figures, about me, other sections
JOB = json.loads((ROOT / "examples" / "job_full_ko.json").read_text(encoding="utf-8"))  # its settings
ORDER = ["개요", "경력요약", "학력사항", "핵심역량", "보유기술", "상세경력사항", "기타사항", "자기소개", ["지원 동기", "커리어 목표"]]
# every new rule on, at values the example meets
STRICT = {
    "claims": {"retired": {"ko": [["결제 표준을 홀로 세워", "결제 표준을 팀과 정리", "the standard was the team's", "승인 경로를 독립 배포 단위로"]]},
               "shared": [["주문 상태 변경", "Kafka 이벤트로 내보내", "one wording in every general edition"]],
               "proposal": {"ko": [["주문 재처리", "제안", "the reprocessing was proposed only"]]}},
    "ledger": {"periods": True, "ids": [{"printed": r"KR(\d{9})0000", "ledger": r"KR(\d{9})B1", "why": "a registered patent's number"}],
               "lists": ["발표"], "required": {"ko": ["정보처리기사", ["영어", "English"]]}, "core": ["장애 대응 자동화"],
               "min_items": {"알파페이": 3, "베타커머스": 3}},
    "structure": {"sections": {"ko": ORDER}, "figures": ["timeline", "stack"], "about_max": 3, "title_lead": "same", "title_ranks": True,
                  "not_skills": ["Statistics", "Soft Skills"]},
    "pages": {"fill_last": 55, "mid_gap": 22, "summary_first": ["경력요약"], "bands": 0.75, "volume": 1.6},
}
NEW = {"claim_retired", "claim_shared", "claim_proposal", "claim_anchor", "ledger_period", "ledger_id", "ledger_id_missing", "ledger_entry",
       "required_missing", "core_missing", "items_fewer", "section_missing", "section_order", "figure_missing", "about_parts", "title_lead",
       "title_mixed", "title_rank", "not_skill", "last_page_room", "page_gap", "summary_spills", "band_off", "band_logo", "band_count",
       "volume_order", "volume_density", "volume_section", "volume_band"}  # the codes of these rules


def check(profile: pathlib.Path, pdf: pathlib.Path, pack: pathlib.Path, ledger: pathlib.Path, edition: str) -> tuple[int, dict]:
    """src/check_documents.py on a resume as the panel runs it (in the container, with --report): its exit code and report."""
    rep = ROOT / "output" / f"{pdf.stem}.rules.checks.json"
    rep.unlink(missing_ok=True)
    r = resume.sh(["python3", "src/check_documents.py", resume.rel(str(profile)), resume.rel(str(pdf)), "--style", resume.rel(str(pack)),
                   "--max-pages", "4", "--report", resume.rel(str(rep)), "--ledger", resume.rel(str(ledger)), "--edition", edition],
                  dict(os.environ, OFFEROWL_LANG="ko"))
    got = json.loads(rep.read_bytes()) if rep.is_file() else {}
    rep.unlink(missing_ok=True)
    return r.returncode, got


@unittest.skipUnless(os.environ.get("OFFEROWL_TEST_RENDER") != "0" and render_image(), "the render container's image is not built here (render/run.sh builds it)")
@unittest.skipUnless((ROOT / "node_modules" / "docx").is_dir(), "the typesetting libraries are not installed (render/run.sh npm ci)")
class DocumentRulesTests(unittest.TestCase):
    """The example passes every new rule; a seeded copy fails each one."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="rules-", dir=str(ROOT / "output")))  # where the container sees it

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)  # the profiles, packs and ledger of the test
        out = ROOT / "output"  # and what the two builds left in the engine's folder
        for name in ("rules_example", "rules_seeded"):
            for f in [*out.glob(f"{name}.*"), *out.glob(f"_figures/{name}_*"), *out.glob(f"_inputs/*{name}*")]:
                f.unlink(missing_ok=True)

    def put(self, name: str, data) -> pathlib.Path:
        """A JSON file in the test's folder, written as bytes."""
        f = self.tmp / name
        f.write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        return f

    def make(self, prof: dict, job: dict, name: str) -> tuple[pathlib.Path, pathlib.Path]:
        """A profile and its settings typeset in the container: (the profile's file, the PDF)."""
        f = self.put(f"{name}.json", prof)
        return f, resume.build(str(f), str(self.put(f"{name}.job.json", {**job, "out": name})))

    def test_the_example_passes_and_a_seeded_copy_fails_each_rule(self):
        prof = json.loads(EXAMPLE.read_bytes())
        ledger = self.put("ledger.json", {"profiles": [prof]})  # the facts: the example itself
        src, pdf = self.make(prof, JOB, "rules_example")
        pack = self.put("strict.json", STRICT)
        for edition in ("general", "job"):  # a general edition, and an application whose last page the example fills enough
            code, rep = check(src, pdf, pack, ledger, edition)
            self.assertEqual([], [x for x in rep.get("defects") or [] if x.get("code") in NEW], (edition, rep))
            self.assertEqual(0, code, (edition, rep))
        seeded = json.loads(json.dumps(prof, ensure_ascii=False).replace("Kafka 이벤트로 내보내", "큐로 보내"))  # the shared phrase gone everywhere
        alpha, beta, gamma = seeded["roles"]
        alpha["projects"][2]["resume"] = False  # a core project left out, and the company's items under its minimum
        alpha["projects"][0]["summary"] += " 결제 표준을 홀로 세워 이끌었다. 주문 재처리를 구현했다."  # a retired phrase; a proposal said as done
        alpha["projects"][1]["period"] = "2023.10 ~ 2024.05"  # a period the facts do not have
        alpha["title"] = "Platform Lead, 플랫폼 리드"  # a rank said twice, and the one title that leads in Latin letters
        gamma["projects"] += [{"id": f"gamma-{i}", "title": f"출시 뒤 운영 과제 {i}", "period": "2017.07 ~ 2019.06",
                               "summary": "주문과 회원 API의 응답 지연을 줄이고 출시 뒤 운영 절차를 팀과 정리해 같은 장애가 다시 나지 않게 했다. " * 2} for i in range(2, 9)]  # two years with the most lines
        others = seeded["sections"][0]["groups"]
        others[0]["lines"] = [["가상의 자격증", "", "2019.05"], ["등록 특허 KR9876543210000", "", "2020.01"]]  # a required word gone; a number the facts lack
        others[2]["rows"].append(["가상의 발표가 하나 더 있었다", "가상의 행사", "2022.01"])  # an entry the facts lack
        seeded["about"].append(["넷째 이야기", "가상의 네 번째 자기소개 문단입니다."])  # about me in four parts
        seeded["skills"].append({"category": "Statistics", "items": ["A/B Testing"]})  # experience in the skills table
        ssrc, spdf = self.make(seeded, {**JOB, "competencyFigure": False}, "rules_seeded")  # the hierarchy figure left out
        tight = copy.deepcopy(STRICT)  # rules the example meets by a margin, held tighter so its pages fail them
        tight["claims"]["retired"]["ko"].append(["이 문구는 쓰지 않는다", "", "a rule on words the facts never held", "프로필에 없는 구절"])  # a stale rule
        tight["ledger"]["ids"][0]["all"] = False
        tight["structure"]["sections"]["ko"] = ORDER[:3] + ["보유기술", "핵심역량"] + ORDER[5:]  # an order the form does not print
        tight["pages"].update({"fill_last": 12, "mid_gap": 5, "summary_first": ["자기소개"], "bands": 0.05})
        tight["structure"]["title_lead"] = "latin"  # the titles printed under the bands are Korean: held to Latin leads, they fail
        tight_f = self.put("tight.json", tight)
        code, rep = check(ssrc, spdf, tight_f, ledger, "general")  # as a general edition
        found = {x.get("code") for x in rep.get("defects") or []}
        self.assertEqual(1, code, rep)
        for want in ("claim_retired", "claim_shared", "claim_proposal", "claim_anchor", "ledger_period", "ledger_id", "ledger_entry",
                     "required_missing", "core_missing", "items_fewer", "section_order", "figure_missing", "about_parts", "title_lead",
                     "title_rank", "not_skill", "page_gap", "band_off", "volume_order"):
            self.assertIn(want, found, rep)
        code, rep = check(ssrc, spdf, tight_f, ledger, "job")  # as an application
        found = {x.get("code") for x in rep.get("defects") or []}
        for want in ("last_page_room", "summary_spills"):  # the rules for one posting
            self.assertIn(want, found, rep)
        self.assertNotIn("claim_shared", found, rep)  # an application words a topic its own way


if __name__ == "__main__":
    unittest.main()
