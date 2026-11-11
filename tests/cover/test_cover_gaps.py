# -*- coding: utf-8 -*-
"""The cover-letter gaps (docs/WRITING.md, "Cover letters"): weak posting lines with evidence get a
paragraph, the duty paragraphs also see the projects that word matching finds, names cross languages through the profile's
glossary, a stated direction reaches the opening, the plan's themes reach the prompt, and claim strength is checked.
No model: llm.run is replaced by the stand-in of test_cover.py."""
import copy  # profile and plan variants
import json  # example files
import pathlib  # paths
import sys  # import path
import unittest  # test runner

HERE = pathlib.Path(__file__).resolve().parent  # tests/cover
sys.path.insert(0, str(HERE))  # the helpers of test_cover.py
from test_cover import C, EX, POST_EN, PROFILE, model, sent  # noqa: E402  the module under test and its fixtures


def answer(**over):
    """A matching answer for the example posting: d6 is weak by the model's own judgement, q5 (English) too."""
    base = {"lines": [  # one entry per posting line the stand-in answers
        {"id": "d1", "ids": ["alpha-1"], "strength": "strong", "missing": [], "basis": "approval path split"},  # a plain strong match
        {"id": "d2", "ids": ["beta-1"], "strength": "strong", "missing": [], "basis": "kafka events"},  # a plain strong match
        {"id": "d3", "ids": ["alpha-2"], "strength": "strong", "missing": [], "basis": "argo and helm"},  # a plain strong match
        {"id": "d5", "ids": ["beta-3"], "strength": "strong", "missing": [], "basis": "on-call steps"},  # a plain strong match
        {"id": "d6", "ids": ["alpha-1"], "strength": "strong", "missing": ["Rust"], "basis": "says strong, but the line names a tool nobody has"},  # strong, but the tool is missing: the plan lowers it
        {"id": "q1", "ids": ["alpha-1"], "strength": "weak", "missing": [], "basis": "years of service"},  # weak, but about years: routine
        {"id": "q5", "ids": ["beta-3"], "strength": "weak", "missing": [], "basis": "training material for colleagues; English not stated"}],  # weak by the model's own judgement
        "groups": [{"lines": ["d1", "d2"], "theme": "services"}, {"lines": ["d3", "d5"], "theme": "platform"}], "fit": ["alpha-1"]}
    base.update(over)  # a test changes what it needs
    return base


class WeakLineTests(unittest.TestCase):  # weak lines and the budget
    def setUp(self):  # one plan per test
        with model({"cover-match": answer()}):  # the stand-in answers the matching
            self.pl = C.plan(PROFILE, POST_EN)  # the stand-in matches the lines
        self.by = {l["id"]: l for l in self.pl["lines"]}  # lines by id

    def test_a_weak_line_the_model_judged_partly_shown_gets_a_paragraph(self):  # the English line, shown in part
        held = [x for g in self.pl["groups"] for x in g["lines"]]  # every line a paragraph answers
        self.assertIn("q5", held)  # the English line is answered
        self.assertTrue(self.by["q5"]["use"])  # and marked for use
        self.assertTrue(any("q5" in n for n in self.pl["notes"]))  # the plan says it added the line

    def test_a_line_lowered_for_a_missing_tool_does_not(self):  # "Write firmware in Rust" has nothing of its own in the evidence
        self.assertTrue(self.by["d6"]["lowered"])  # lowered for the missing tool
        self.assertFalse(self.by["d6"]["use"])  # and left out

    def test_degree_and_years_lines_stay_with_the_resume(self):  # weak, with evidence, but routine
        self.assertFalse(self.by["q1"]["use"])  # the years line stays out

    def test_the_groups_keep_the_posting_order(self):  # a new group sits where its lines are
        flat = [x for g in self.pl["groups"] for x in g["lines"]]  # every grouped line
        self.assertEqual(flat, sorted(flat, key=lambda x: self.by[x]["order"]))  # in the posting's order

    def test_trimming_keeps_requirements_before_preferred_lines(self):  # a partly shown requirement beats a nice-to-have
        lines = [{"id": "d1", "order": 1, "kind": "duty", "strength": "strong"}, {"id": "q1", "order": 2, "kind": "requirement", "strength": "weak"},  # a strong duty and a weak requirement
                 {"id": "p1", "order": 3, "kind": "preferred", "strength": "strong"}]  # and a strong nice-to-have
        groups = [{"id": "g1", "lines": ["d1", "q1"], "theme": ""}, {"id": "g2", "lines": ["p1"], "theme": ""}]  # two paragraphs
        kept, dropped = C.trim_groups(groups, lines, 2)  # room for two lines
        self.assertEqual(dropped, ["p1"])  # the preferred line goes


class PoolTests(unittest.TestCase):  # evidence pools
    def setUp(self):  # the reviewed example plan
        self.plan = json.loads((EX / "plan_en.json").read_text(encoding="utf-8"))  # the reviewed English example plan
        self.U = C.units_of(PROFILE, "en")  # its units

    def test_word_matching_adds_projects_to_a_duty_paragraph(self):  # facts deep inside a project the plan did not choose
        plan = copy.deepcopy(self.plan)  # a copy to change
        next(l for l in plan["lines"] if l["id"] == "d4")["ev"] = ["alpha-2"]  # the metrics line no longer cites the project its words match best
        plain = C.paragraph_plan(plan, self.U)  # without the word index: the plan's own evidence only
        wide = C.paragraph_plan(plan, self.U, C.Lex(self.U))  # with it
        g2 = next(b for b in wide if b["lines"] == ["d3", "d4"])  # the metrics paragraph
        self.assertIn("beta-1", g2["pool"])  # the project word matching ranks first for the metrics line is back in reach
        for a, b in zip(plain, wide):  # paragraph by paragraph
            self.assertTrue(set(a["pool"]) <= set(b["pool"]), a["id"])  # nothing is taken away
        self.assertTrue(any(len(b["pool"]) > len(a["pool"]) for a, b in zip(plain, wide) if a["kind"] == "duties"))  # something is added

    def test_the_opening_sees_every_matched_project_and_the_persons_statements(self):  # the opening
        prof = copy.deepcopy(PROFILE)  # a copy to change
        prof["summary"]["direction"] = {"en": "I want to keep payment paths simple enough to ship every day.", "ko": "결제 경로를 매일 배포할 만큼 단순하게 두고 싶다."}  # a stated direction
        U = C.units_of(prof, "en")  # its units
        self.assertIn("summary#direction", U["index"])  # the stated direction is a unit
        paras = C.paragraph_plan(self.plan, U, C.Lex(U))  # with the word index
        opening = paras[0]  # the opening
        self.assertIn("summary#direction", opening["pool"])  # the direction is citable
        used = {e for l in self.plan["lines"] for e in l["ev"] if l.get("use")}  # every entry a used line rests on
        self.assertTrue(used <= set(opening["pool"]))  # every project the planned lines rest on

    def test_the_prompt_shows_the_themes_and_a_plan_direction(self):  # a person's edits in plan.json steer the paragraphs
        plan = copy.deepcopy(self.plan)  # a copy to change
        plan["groups"][0]["theme"] = "THEME EDITED BY A PERSON"  # a person's theme
        plan["direction"] = "Payments should be dull to run."  # a person's direction
        good = json.loads((EX / "cover_en.json").read_text(encoding="utf-8"))  # the reviewed letter
        with model({"cover-draft": {"paragraphs": [{"id": p["id"], "sentences": p["sentences"]} for p in good["paragraphs"]]}}) as m:  # the stand-in answers with it
            C.draft(PROFILE, plan, style=C.load_style(str(EX / "style.json")))  # one draft
        prompt = m.calls[0][1]  # the prompt
        self.assertIn("Theme: THEME EDITED BY A PERSON", prompt)  # the theme is printed
        self.assertIn("Payments should be dull to run.", prompt)  # and the direction


class NameTests(unittest.TestCase):  # names across languages
    def test_a_glossary_name_needs_no_declaration(self):  # the profile's glossary pairs a Korean name with its English spelling
        prof = copy.deepcopy(PROFILE)  # a copy to change
        prof["glossary"] = {"알파페이": "Alpha Pay"}  # the person's glossary
        U = C.units_of(prof, "en")  # its units
        plan = {"lang": "en", "posting": {"company": "Orion Payments", "role": "Backend Platform Engineer", "overview": ""}, "gap_terms": [], "allow": []}  # a plan in miniature
        style = C.load_style(None)  # the default pack
        bare = C.make_ctx(U, plan, style)  # no glossary
        glossed = C.make_ctx(U, plan, style, C.F.glossary_of(prof))  # with the glossary
        s = sent("At Alpha Pay I split approval out of the application.", ["alpha-1#1"])  # an English name over Korean evidence
        self.assertIn("name", [i["code"] for i in C.fact_issues(s, "duties", bare)])  # without the pair the English name is unknown
        self.assertNotIn("name", [i["code"] for i in C.fact_issues(s, "duties", glossed)])  # with it the Korean name in the evidence backs it

    def test_places_cross_languages_without_a_glossary(self):  # general places: 서울 in the evidence backs Seoul in the letter
        U = C.units_of(PROFILE, "en")  # the example's units
        plan = {"lang": "en", "posting": {"company": "Orion Payments", "role": "x", "overview": ""}, "gap_terms": [], "allow": []}  # a plan in miniature
        ctx = C.make_ctx(U, plan, C.load_style(None), C.F.glossary_of(PROFILE))  # the glossary of the example: general places only
        s = sent("I worked from Seoul on the approval path.", ["role:alpha", "alpha-1#1"])  # Seoul over 서울
        self.assertEqual([i["code"] for i in C.fact_issues(s, "duties", ctx) if i["code"] == "name"], [])  # no name issue

    def test_the_evidence_listing_names_the_spellings(self):  # the model sees the names it may keep
        prof = copy.deepcopy(PROFILE)  # a copy to change
        prof["glossary"] = {"알파페이": "Alpha Pay"}  # the person's glossary
        U = C.units_of(prof, "en")  # its units
        text = C.evidence_listing(U, C.Lex(U), ["alpha-1"], "approval", C.F.glossary_of(prof))  # the listing with the glossary
        self.assertIn("알파페이 = Alpha Pay", text)  # the pair is shown


class ClaimTests(unittest.TestCase):  # claim strength
    def test_a_claim_stronger_than_its_evidence_fails_the_check(self):  # led where the evidence says the person took part
        prof = copy.deepcopy(PROFILE)  # a copy to change
        prof["roles"][1]["projects"][2]["summary"] = "주문 장애 대응 절차 문서화에 참여했다."  # beta-3: took part
        cover = json.loads((EX / "cover_en.json").read_text(encoding="utf-8"))  # the reviewed letter
        target = next(p for p in cover["paragraphs"] if p["kind"] == "duties")  # its first duty paragraph
        target["sentences"].append({"text": "I led the incident procedures for the order team.", "ev": ["beta-3#1"], "duties": target["duties"][:1]})  # an overclaim over the changed evidence
        res = C.check_cover(prof, cover, style_spec=str(EX / "style.json"))  # check it
        st = {c["key"]: c["status"] for c in res["checks"]}  # status by check
        self.assertEqual(st["claims"], "fail")  # the claims check fails
        item = next(c for c in res["checks"] if c["key"] == "claims")["items"][0]  # its first item
        self.assertIn("참여", item["issues"][0]["detail"])  # the message quotes the evidence's word

    def test_the_draft_sends_an_overclaim_to_repair(self):  # the same check runs while drafting
        plan = json.loads((EX / "plan_en.json").read_text(encoding="utf-8"))  # the reviewed plan
        good = json.loads((EX / "cover_en.json").read_text(encoding="utf-8"))  # the reviewed letter
        prof = copy.deepcopy(PROFILE)  # a copy to change
        prof["roles"][1]["projects"][2]["summary"] = "주문 장애 대응 절차 문서화에 참여했다."  # the evidence now says "took part"
        paras = [{"id": p["id"], "sentences": copy.deepcopy(p["sentences"])} for p in good["paragraphs"]]  # the model's answer
        duty = next(p for p in paras if p["id"] == next(x["id"] for x in good["paragraphs"] if x["kind"] == "duties"))  # its first duty paragraph
        duty["sentences"].append({"text": "I led the incident procedures for the order team.", "ev": ["beta-3#1"], "duties": []})  # the overclaim
        with model({"cover-draft": {"paragraphs": paras}, "cover-repair": {"paragraphs": []}}) as m:  # the repair gives nothing back
            out = C.draft(prof, plan, style=C.load_style(str(EX / "style.json")))  # one draft
        self.assertIn("cover-repair", [c[0] for c in m.calls])  # the repair round ran
        self.assertTrue(any(i["code"] == "claim" for d in out["dropped"] for i in d["issues"]))  # the overclaim was dropped for its claim
        self.assertNotIn("I led the incident procedures", json.dumps(out["paragraphs"]))  # and is not in the letter


if __name__ == "__main__":
    unittest.main()  # run this file alone
