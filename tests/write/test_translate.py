#!/usr/bin/env python3
"""The English profile: Markdown bodies translated cell by cell, and only what a resume draft does not hold asked for."""
import copy  # profiles are changed only in copies
import pathlib  # paths
import re  # the stand-in's words
import sys  # the import path
import unittest  # the runner
from unittest import mock  # the model call

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"  # the engine
sys.path.insert(0, str(SRC))  # flat modules
import draft as D  # noqa: E402  the module under test

BODY = "<!-- a note to the person: not printed -->\n| 구분 | 등급 | 취득일 |\n|---|---|---|\n| 가상 자격 | 1급 | 2018.05 |\n\n- 가상 강연\n### 소제목\nplain line"
LEDGER = {  # a fictional profile in the ledger form, with a draft's parts in both languages
    "person": {"name": "홍길동", "name_en": "Gildong Hong"},
    "summary": {"headline": "결제 플랫폼 엔지니어", "intro": {"ko": "소개 문장", "en": "An introduction"}, "layers": {"ko": [["계층", "기술"]]}},
    "roles": [{"key": "alpha", "heading": "알파페이", "career": {"ko": {"name": "알파페이"}, "en": {"name": "Alpha Pay"}},
               "projects": [{"id": "alpha-1", "title": "결제 승인 재설계", "body_md": "- 승인 경로 분리"}]},
              {"key": "beta", "heading": "베타 연구실", "career": {}, "projects": []}],
    "skills": [{"category": "Languages", "items": ["Go", "Python"]}, {"category": "협업", "items": ["Jira", "사내 위키"]}],
    "sections": [{"title": "자격증", "body_md": BODY}],
    "competencies": {"ko": [["강점", "설명"]]},
}


def word_for_word(task, prompt, required, schema, result, log):
    """A stand-in for the model: each Korean word becomes 'word', the way apps/api/standin.py answers."""
    fields = D.json.loads(re.search(r"Fields \(JSON object id -> Korean\):\n(\{.*?\})\n", prompt, re.S).group(1))  # the fields asked for
    return {"t": {k: re.sub(r"[가-힣]+", "word", v) for k, v in fields.items()}}  # every id answered


class MarkdownTests(unittest.TestCase):
    def test_the_parts_of_a_body(self):
        units = D.md_units(BODY)  # the Korean parts
        self.assertEqual(["구분", "등급", "취득일", "가상 자격", "1급", "가상 강연", "소제목"], [t for _, t in units])  # cells, the bullet and the heading
        self.assertNotIn("note", " ".join(t for _, t in units))  # a note is not a part

    def test_a_body_is_rebuilt_around_the_translations(self):
        units = D.md_units(BODY)  # the parts
        out = D.md_apply(BODY, {k: f"E{i}" for i, (k, _) in enumerate(units)})  # each part translated
        self.assertEqual("| E0 | E1 | E2 |\n|---|---|---|\n| E3 | E4 | 2018.05 |\n\n- E5\n### E6\nplain line\n", out)  # the same shape, the date kept, the note gone


class StringsTests(unittest.TestCase):
    def test_a_full_translation_asks_for_every_korean_field(self):
        paths = [p for p, _, _ in D._strings(LEDGER)]  # what would be asked
        self.assertIn(("summary", "headline"), paths)  # the headline
        self.assertIn(("roles", 0, "projects", 0, "title"), paths)  # a project's title
        self.assertNotIn(("summary", "intro", "en"), paths)  # the person's own English stays

    def test_the_place_and_the_personal_line_are_asked_unless_the_person_wrote_english(self):
        prof = copy.deepcopy(LEDGER)  # a copy to change
        prof["person"].update(location="서울", info="1990년생 (서울 거주)")  # one text for both editions
        paths = [p for p, _, _ in D._strings(prof, skip_drafted=True)]  # also with a draft: no draft writes them
        self.assertIn(("person", "location"), paths)  # the place
        self.assertIn(("person", "info"), paths)  # the personal line
        prof["person"].update(location={"ko": "서울"}, info={"ko": "1990년생", "en": ""})  # per language: no English side, and an English side left empty on purpose
        paths = [p for p, _, _ in D._strings(prof)]
        self.assertIn(("person", "location", "en"), paths)  # its Korean side goes to its English one
        self.assertNotIn(("person", "info", "en"), paths)  # an empty English side prints no row, as the person chose
        self.assertNotIn(("person", "info"), paths)

    def test_with_a_draft_only_what_it_does_not_hold_is_asked(self):
        paths = [p for p, _, _ in D._strings(LEDGER, skip_drafted=True)]  # what would be asked
        self.assertNotIn(("summary", "headline"), paths)  # the draft writes it
        self.assertFalse([p for p in paths if p[:1] == ("competencies",) or p[2:3] == ("projects",)])  # and these
        self.assertIn(("roles", 1, "heading"), paths)  # a ledger role with no English name
        self.assertNotIn(("roles", 0, "heading"), paths)  # one with an English name in its career block
        self.assertIn(("skills", 1, "category"), paths)  # a skill group named in Korean
        self.assertIn(("skills", 1, "items", 1), paths)  # and its Korean item, not its Latin one
        self.assertIn(("summary", "layers", "en", 0, 0), paths)  # the hierarchy rows, which no draft writes
        self.assertIn(("sections", 0, "body_md", 3, 0), paths)  # a cell of the Markdown body


class TranslateTests(unittest.TestCase):
    def test_a_ledger_profile_with_a_draft(self):
        before = copy.deepcopy(LEDGER)  # to see that the input is not changed
        with mock.patch.object(D, "ask", word_for_word):  # no model
            new, log = D.task_translate(LEDGER, {}, skip_drafted=True)  # the parts a draft does not hold
        self.assertEqual(before, LEDGER)  # the input stays as it was
        body = new["sections"][0]["body_md"]  # the translated body
        self.assertIn("| word word | 1word | 2018.05 |", body)  # a row keeps its cells, the date untouched
        self.assertNotIn("note", body)  # the note is not carried over
        self.assertFalse(re.search(r"[가-힣]", body))  # no Korean left in it
        self.assertEqual("word", new["sections"][0]["title"])  # its title
        self.assertEqual("word word", new["roles"][1]["heading"])  # the role with no English name
        self.assertEqual("결제 플랫폼 엔지니어", new["summary"]["headline"])  # the draft's part is not touched
        self.assertTrue(all(e["kept"] for e in log), [e for e in log if not e["kept"]][:3])  # every answer passed the checks

    def test_a_translation_that_loses_a_number_is_not_used(self):
        def drops(task, prompt, required, schema, result, log):  # a model that loses the grade
            out = word_for_word(task, prompt, required, schema, result, log)  # the usual answer
            out["t"] = {k: v.replace("1", "") for k, v in out["t"].items()}  # the 1 of '1급' goes
            return out
        with mock.patch.object(D, "ask", drops):
            new, log = D.task_translate(LEDGER, {}, skip_drafted=True)
        self.assertIn("1급", new["sections"][0]["body_md"])  # that cell stays in Korean, so nothing false is printed
        self.assertTrue(any(not e["kept"] for e in log))  # and the record says why


if __name__ == "__main__":  # run as a script
    unittest.main()
