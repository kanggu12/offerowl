# -*- coding: utf-8 -*-
"""src/check_documents.py check_resume: an English edition with Korean text other than the person's own name fails.

Run: python3 -m unittest tests/render/test_check_lang.py -v
"""
import pathlib  # paths
import sys  # the import path
import unittest  # the test runner
from unittest import mock  # the page's text, with no PDF

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT / "src"))  # the module under test
import check_documents as CD  # noqa: E402  the module under test

PROFILE = {"person": {"name": "홍 길 동 (Gildong Hong)"}, "roles": [{"org": "Alpha Pay", "projects": []}]}  # fictional, with a ledger-style name
PAGE = "Gildong Hong\n홍길동\nPayments engineer\nAlpha Pay\n" + "Built the payment platform. " * 20  # an English page with the name in Hangul


class KoreanLeft(unittest.TestCase):
    def check(self, text):
        """The resume check on a page with this text, layout checks left out."""
        with mock.patch.object(CD.P, "text", return_value=text), mock.patch.object(CD.CR, "footer_clearance", return_value=[]), \
                mock.patch.object(CD.CR, "number_unit_split", return_value=[]), mock.patch.object(CD, "last_fill", return_value=1.0):
            return [b for b in CD.check_resume(PROFILE, "x.pdf", "default", 3) if "한글" in b or "Korean" in b]  # this rule's findings

    def test_the_person_s_own_name_in_hangul_is_allowed(self):
        self.assertEqual([], self.check(PAGE))  # the name, its syllables joined as printed

    def test_a_korean_line_in_an_english_edition_is_named(self):
        bad = self.check(PAGE + "Personal 1990년생 (서울 거주)\n")  # a line the translation missed, after a long one
        self.assertEqual(bad, self.check(PAGE + "\nPersonal 1990년생 (서울 거주)\n"))  # the same finding on a line of its own
        self.assertEqual(1, len(bad), bad)  # one finding
        self.assertIn("1990년생", bad[0])  # it quotes the first Korean text
        self.assertIn("2", bad[0])  # and counts the places: 년생, 서울 거주

    def test_a_korean_edition_is_not_held_to_it(self):
        self.assertEqual([], self.check("홍길동\n" + "결제 플랫폼을 만들었습니다. " * 30 + "Alpha Pay\n"))  # mostly Hangul: a Korean edition


class FormTests(unittest.TestCase):
    """The education table's lines say alike things alike (check_documents.form_issues)."""

    EDU = [{"school": {"ko": "가나대학교(서울)"}, "sub": {"ko": "일반대학원"}, "major": {"ko": "데이터공학"}},  # fictional schools
           {"school": {"ko": "다라대학교(서울)"}, "sub": {"ko": "정보대학원"}, "major": {"ko": "컴퓨터공학 전공"}},
           {"school": {"ko": "다라대학교(서울)"}, "sub": {"ko": ""}, "major": {"ko": "컴퓨터공학, 경영학 복수전공"}},
           {"school": {"ko": "마바고등학교(서울)"}, "major": {"ko": "이과"}}]

    def test_a_major_written_unlike_the_others_is_named(self):
        bad = CD.form_issues({"education": self.EDU}, "ko")
        self.assertEqual(1, len(bad), bad)  # only the first line: the high school has no major to compare
        self.assertIn("데이터공학", bad[0])
        self.assertIn("가나대학교", bad[0])

    def test_lines_alike_and_english_editions_pass(self):
        edu = [dict(e) for e in self.EDU]
        edu[0] = {**edu[0], "major": {"ko": "데이터공학 전공"}}  # written as the others are
        self.assertEqual([], CD.form_issues({"education": edu}, "ko"))
        self.assertEqual([], CD.form_issues({"education": self.EDU}, "en"))  # the English fields name a major plainly
        self.assertEqual([], CD.form_issues({"education": self.EDU[:1] + self.EDU[3:]}, "ko"))  # one degree: nothing to compare


if __name__ == "__main__":
    unittest.main()
