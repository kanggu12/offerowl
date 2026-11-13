"""The corpus loader on the fictional example: sources, roles, ids, fields."""
import unittest  # the test runner

import helpers  # noqa: F401  the import path and the example
from interview import corpus  # the loader


class CorpusTest(unittest.TestCase):  # the loader's output on the untouched example
    def setUp(self):  # runs before each test
        self.job = helpers.example_job()  # read in place, nothing written
        self.items, self.alts = corpus.load(self.job)  # the items and alternate phrasings each test reads

    def test_sources_and_counts(self):
        """Every scene file and the stories load, in the kit's order."""
        srcs = [s[1] for s in self.job.sources()]  # the label of each source
        self.assertEqual(srcs, ["문답", "이력상세", "용어", "이야기"])  # kit.json's order: three scene files, then the workspace stories
        self.assertEqual(len(self.items), 18)  # 15 scenes and 3 stories
        self.assertEqual(sum(1 for it in self.items if it["role"] == "reference"), 3)  # only the stories are reference notes

    def test_ids_titles_and_fields(self):
        """Ids come from the headings, titles split into Korean and English, dialogue fills the en and ko fields."""
        by = {it["id"]: it for it in self.items}  # items by id
        self.assertEqual(len(by), len(self.items))  # ids are unique
        a1 = by["A1"]  # the self-introduction scene
        self.assertEqual(a1["tko"], "1분 자기소개")  # the Korean half of the heading
        self.assertEqual(a1["ten"], "Tell me about yourself")  # the English half
        self.assertTrue(a1["key"].startswith("주문에서 결제로"))  # the 핵심 line fills key
        self.assertIn("backend platform engineer", a1["en"])  # 나 and 면접관 lines
        self.assertIn("백엔드 플랫폼 엔지니어", a1["ko"])  # 해석 lines
        self.assertEqual(by["R1"]["role"], "deep")  # deep.md items take the deep role
        self.assertEqual(by["Q1"]["role"], "terms")  # terms.md items take the terms role
        self.assertEqual(by["S1"]["cat"], "이야기")  # a level-2 story is its own item

    def test_alts_skip_comments(self):
        """alts.json comment keys are not items."""
        self.assertNotIn("_comment", self.alts)  # keys that start with an underscore are dropped
        self.assertIn("A1", self.alts)  # real entries stay

    def test_parse_rules(self):
        """A section without item headings splits into labelled bullets, and a title without English stays whole."""
        text = "# t\n\n## 노트\n\n- **하나**: a\n- **둘**: b\n- **셋**: c\n\n## Z. 묶음\n\n### Z1. 제목만\n본문\n"  # a section of three labelled bullets, then a lettered section with one item heading
        items = corpus.parse_text(text, "노트", "N", "reference", "x.md")  # read as a reference file with the prefix N
        self.assertEqual([it["id"] for it in items], ["N1", "N2", "N3", "Z1"])  # the bullets become N1 to N3; the item heading keeps its own id
        self.assertEqual(items[0]["title"], "노트: 하나")  # an unlettered bullet's title joins the section heading and its label
        self.assertEqual(items[3]["ten"], "")  # a heading with no English half leaves ten empty
        self.assertEqual(corpus.split_title("P/D 분리 / What is P/D?"), ("P/D 분리", "What is P/D?"))  # the slash inside P/D is not the title separator


if __name__ == "__main__":  # the file can also run on its own
    unittest.main()
