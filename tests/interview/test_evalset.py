"""The eval command's question sets: the job's own eval set by default, or another file of the same form
(`eval --questions`), such as the example kit's cards asked in other words (docs/DECISIONS.md, Search). No browser:
the sets are read and checked before any page opens."""
import contextlib  # the printed lines
import io  # the printed lines
import pathlib  # paths
import sys  # the import path
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # helpers.py
import helpers  # noqa: E402  the import path and the example workspace
from interview import corpus, evalset  # noqa: E402  the cards and the eval

REWORDED = helpers.ROOT / "tests" / "decide" / "fixtures" / "kit_questions_reworded.json"  # the example's cards in other words


class QuestionSets(unittest.TestCase):
    def test_the_jobs_own_set_by_default(self):
        qs = evalset.questions(helpers.example_job())
        self.assertEqual(len(qs), 15)
        self.assertEqual(qs[0], ("Tell me about yourself", ["A1"]))

    def test_another_file_of_the_same_form(self):
        qs = evalset.questions(helpers.example_job(), REWORDED)
        self.assertEqual(len(qs), 28)
        items, _ = corpus.load(helpers.example_job())
        cards = {it["id"] for it in items}  # the example kit's cards
        for q, want in qs:  # every question names cards the kit has
            self.assertTrue(want and set(want) <= cards, q)
        self.assertEqual(sum(has_hangul(q) for q, _ in qs), 14)  # half of them in Korean

    def test_a_missing_file_is_named_and_nothing_runs(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = evalset.main(helpers.example_job(), questions_file=helpers.ROOT / "no-such-questions.json")
        self.assertEqual(rc, 2)  # nothing to measure, before any page opens
        self.assertIn("no-such-questions.json", out.getvalue())


def has_hangul(text):
    """Does the text have Hangul?"""
    return any("가" <= ch <= "힣" for ch in text)


if __name__ == "__main__":
    unittest.main()
