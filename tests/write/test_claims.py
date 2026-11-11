# -*- coding: utf-8 -*-
"""Claim strength (src/factcheck.py claim_issues): planted cases in both languages, and the same check inside the resume
draft, the cover letter and the drafted-profile check. No model, no container."""
import pathlib  # paths
import sys  # the import path
import unittest  # the test runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
import factcheck as F  # noqa: E402  (the path is set above)

# (sentence, evidence, flagged?): each row plants one case the check must get right
CASES = [
    ("I designed the recovery scheme.", "학습 작업이 끊기면 사용자가 다시 돌려야 했다. 설계안을 만들어 제안했다", True),  # designed over "proposed"
    ("I designed and proposed a recovery scheme.", "설계안을 만들어 제안했다", False),  # the sentence keeps the qualifier
    ("Built a shared component library for the payment pages.", "결제 화면을 공용 컴포넌트 묶음으로 팀과 함께 재구성했다", True),  # built over "with the team"
    ("Led the directory migration.", "디렉터리 이관 작업에 참여했다", True),  # led over "participated"
    ("Owned the release pipeline.", "동료와 함께 배포 파이프라인을 적용했다", True),  # owned over "a colleague"
    ("Built the user dashboard.", "사용자 대시보드 구축을 도왔다", True),  # built over "helped"
    ("Built the user dashboard.", "사용자 대시보드를 구축했다", False),  # the evidence makes the same claim
    ("Led the SRE team.", "SRE 팀장을 맡아 팀을 이끌었다", False),  # a team lead leads
    ("Built the CI pipeline.", "I helped build the CI pipeline.", True),  # English evidence: helped
    ("Designed a caching layer.", "Proposed a caching layer for the order service.", True),  # English evidence: proposed
    ("Led the SRE team that built the platform.", "I led the team that built the platform.", False),  # "led the team" is not a qualifier
    ("파이프라인을 구축했다", "파이프라인 구축에 참여했다", True),  # Korean sentence over Korean evidence
    ("배포 체계 개편을 주도했다", "팀이 배포 체계 개편을 주도했다", True),  # the team did it
    ("공용 컴포넌트 묶음 구축", "결제 화면을 공용 컴포넌트 묶음으로 팀과 함께 재구성했다", True),  # a bare work noun at the end claims too (resume bullet style)
    ("Developed the order API and the admin screen.", "주문 API와 내부 관리 화면을 함께 개발했다", False),  # "A와 B를 함께" lists two objects
    ("Led the split into a separate service.", "별도 서비스로 분리할 것을 제안해 관철했다", False),  # a proposal that went through is a result
    ("Founded the data team and set up the review rotation.", "채용부터 팀 구성까지 직접 이끌어 데이터 팀을 신설했다. 리뷰 순번을 문서로 고정했다", False),
    ("Founded the company and built its backend.", "친구들과 공동창업. 주문 API 서버를 구성했다", True),  # founded over "co-founded"
    ("Designed the payment network as two zones.", "공동 결제망의 구역은 둘로 나눠 설계했다", False),  # "joint" names the network, not who designed
    ("Ran the weekly sync with the partners.", "파트너와 주간 회의를 운영했다", False),  # no claim of strength at all
]


class ClaimCases(unittest.TestCase):
    def test_planted_cases(self):  # every planted case flags exactly when it should
        for sentence, evidence, flagged in CASES:
            with self.subTest(sentence=sentence):
                got = F.claim_issues(sentence, evidence)  # the problems found
                self.assertEqual(bool(got), flagged, got)  # the message shows what was found

    def test_the_message_names_the_claim_and_the_qualifier(self):  # a person can act on the message
        got = F.claim_issues("Built the user dashboard.", "동료가 만든 대시보드 구축을 도왔다")
        self.assertEqual(got[0]["claim"], "build")  # the claim class
        self.assertEqual(got[0]["hedge"], "helped")  # the most specific qualifier is named first
        self.assertIn("도왔", F.claim_text(got[0], "en"))  # the message quotes the evidence's word
        self.assertIn("근거", F.claim_text(got[0], "ko"))  # and has a Korean form

    def test_evidence_as_blocks(self):  # a list of blocks is read block by block
        blocks = ["사용자 대시보드를 구축했다", "로그 수집은 팀과 함께 진행했다"]  # one block supports the claim, the other qualifies other work
        self.assertEqual(F.claim_issues("Built the user dashboard.", blocks), [])  # one unqualified supporting sentence is enough

    def test_a_sentence_without_claims_is_never_flagged(self):  # ordinary verbs are not claims of strength
        self.assertEqual(F.claim_issues("Wrote down the on-call steps.", "팀이 온콜을 맡았다"), [])


if __name__ == "__main__":
    unittest.main()
