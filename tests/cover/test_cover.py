# -*- coding: utf-8 -*-
"""Tests of the cover letter pipeline (src/cover.py, src/cover_form.js).

Nothing here calls a model: the backend is `none` or a stand-in that replaces llm.run. The render test needs Docker and is
opt-in:  OFFEROWL_RENDER_TESTS=1 python3 -m unittest discover -s tests/cover

  python3 -m unittest discover -s tests/cover        (or: python3 -m pytest tests/cover)
"""
import contextlib  # silence the CLI printing
import copy  # profile variants
import io  # captured output
import json  # example files
import os  # opt-in switch
import pathlib  # paths
import sys  # import path
import tempfile  # scratch folders
import unittest  # test runner

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # repository root
sys.path.insert(0, str(ROOT / "src"))  # cover.py imports its siblings the flat way, like every script in src/
import cover as C  # the module under test
import llm  # replaced by a stand-in in the model tests

EX = ROOT / "examples" / "cover"  # fictional example files
PROFILE = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the fictional person
POST_EN = (EX / "posting_en.md").read_text(encoding="utf-8")  # English example posting: headings, bullets, a location line
POST_KO = (EX / "posting_ko.md").read_text(encoding="utf-8")  # Korean example posting, wrapped in a fence with a note outside it


def sent(text, ev=(), frame=False, names=None, duties=()):
    """A sentence object as the model returns it."""
    return C.norm_sentence({"text": text, "ev": list(ev), "frame": frame, "names": names or {}, "duties": list(duties)})  # goes through the real normaliser so tests see the shape that model answers get


class StandIn:
    """A model that answers from a table of task name -> function(prompt) and records every call."""

    def __init__(self, answers):  # answers maps a task name to a fixed reply or to a function of the prompt
        self.answers, self.calls = answers, []  # calls is what tests read to count model calls and look at prompts

    def __call__(self, task, prompt, **kw):  # same call shape as llm.run, so it can be swapped in directly
        self.calls.append((task, prompt, kw))  # recorded before anything can fail, so a refused call is visible too
        if task not in self.answers:  # a task without a canned answer behaves like a missing model
            raise llm.LLMUnavailable("no answer for " + task)  # the error llm.run raises when no backend answers, so cover.py takes its fallback path
        return self.answers[task](prompt) if callable(self.answers[task]) else self.answers[task]  # a function answer sees the prompt, so a test can check what the model was asked


@contextlib.contextmanager  # lets a test write `with model(...)` and always get llm.run back
def model(answers):
    """Replace llm.run for a block."""
    saved, fake = llm.run, StandIn(answers)  # keep the real function to put back afterwards
    llm.run = fake  # cover.py calls llm.run through the module, so replacing the attribute is enough
    try:  # the body of the with block runs at the yield
        yield fake  # the test gets the recorder to inspect calls
    finally:  # a failed assertion inside the block must not leave the fake installed for later tests
        llm.run = saved  # restore the real backend entry point


class PostingTests(unittest.TestCase):  # parse_posting: sections, bullets, front matter and the company name
    def test_english_sections_keep_the_posting_order(self):  # duties, requirements and preferred lines must come out in the order the posting prints them
        p = C.parse_posting(POST_EN)  # the English example has headings, bullets and a location line
        self.assertEqual(p["title"], "Backend Platform Engineer")  # the first short line before any heading is the title
        self.assertEqual(p["company"], "Orion Payments")  # found through the "At <Company>" style of English postings
        kinds = [i["kind"] for i in p["items"]]  # only the kind sequence matters for the order check
        self.assertEqual(kinds, ["duty"] * 6 + ["requirement"] * 5 + ["preferred"] * 4)  # six duties, then five requirements, then four preferred lines, as the posting lists them
        self.assertEqual(p["items"][0]["text"], "Design and build the backend services for payment approval and settlement")  # the bullet marker is gone from the first line
        self.assertIn("Seoul", p["location"])  # the place of work comes from the location section, not from the lists

    def test_korean_posting_and_company(self):  # a Korean posting parses the same way and gives its company from the first sentence
        p = C.parse_posting(POST_KO)  # the Korean example uses Korean section headings
        self.assertEqual(p["company"], "델타페이")  # the name is read from the "<name> is ..." opening sentence
        self.assertEqual(len([i for i in p["items"] if i["kind"] == "duty"]), 6)  # the Korean duty heading was recognised, so all six duties were collected
        self.assertEqual(p["items"][6]["kind"], "requirement")  # the seventh line is the first requirement, so the section switch worked
        self.assertTrue(all(not i["text"].startswith("-") for i in p["items"]))  # list markers are gone

    def test_notes_outside_the_fence_are_not_part_of_the_posting(self):  # prose around the fenced posting must not turn into duty or requirement lines
        p = C.parse_posting(POST_KO)  # the example file adds a note outside the fence
        self.assertNotIn("가상의 예제", " ".join(i["text"] for i in p["items"]))  # none of the note's words may appear in any extracted line

    def test_bullets_with_wrapped_lines_become_one_item(self):  # a wrapped bullet is one item, not two
        p = C.parse_posting("Responsibilities:\n- Run the cluster and\n  keep it healthy\n- Write the runbooks\n\nQualifications:\n* Linux\n")  # the second line of the first bullet is indented, as a wrapped line is
        self.assertEqual([i["text"] for i in p["items"]], ["Run the cluster and keep it healthy", "Write the runbooks", "Linux"])  # the continuation is joined with a space, and a star bullet works like a dash

    def test_front_matter_wins(self):  # values given in front matter beat what the text parser would guess
        p = C.parse_posting("---\ncompany: Acme Cloud\nrole: Site Reliability Engineer\n---\nResponsibilities\nRun things\nQualifications\nLinux\n")  # company and role exist only in the front matter here
        self.assertEqual((p["company"], p["title"]), ("Acme Cloud", "Site Reliability Engineer"))  # both front matter values come back unchanged

    def test_preferred_is_not_taken_for_a_requirement(self):  # the heading "Preferred Qualifications" must win over the plain "Qualifications" pattern
        p = C.parse_posting("Qualifications\nLinux\nPreferred Qualifications\nRust\nResponsibilities\nOn-call\n")  # the preferred section sits between two other sections, so it also has to end the requirement list
        self.assertEqual([i["kind"] for i in p["items"]], ["requirement", "preferred", "duty"])  # one line per section, in the order of the sections

    def test_no_company_stays_empty(self):  # with no "At <Company>" phrase the company stays empty, so the letter names none
        self.assertEqual(C.parse_posting("Responsibilities\nRun things\n")["company"], "")  # an empty string, not a guessed word


    def test_about_you_heads_the_requirements(self):  # "About you" and its kin open the requirements: their lines were read as duties
        for head in ("About you", "Your profile", "Who we're looking for", "What you bring", "The ideal candidate", "Skills & experience"):
            text = f"# Engineer\n\n## What you will do\n\n- Run the deploy path.\n\n## {head}\n\n- Fluent in Python.\n- Two years in an SRE role.\n"
            items = C.parse_posting(text)["items"]
            self.assertEqual([(i["kind"], i["section"]) for i in items],
                             [("duty", "What you will do"), ("requirement", head), ("requirement", head)], head)

    def test_square_headings_and_a_company_named_in_a_we_are_sentence(self):
        p = C.parse_posting("■ 담당업무\n- 서비스 개발\n- 인프라 운영\n■ 자격요건\n- 컴퓨터공학 전공\n■ 우대사항\n- 클라우드 경험\n")  # a square in front of a heading is decoration
        self.assertEqual([(i["kind"], i["text"]) for i in p["items"]],
                         [("duty", "서비스 개발"), ("duty", "인프라 운영"), ("requirement", "컴퓨터공학 전공"), ("preferred", "클라우드 경험")])
        self.assertEqual(C.parse_posting("**About us**\nWe are Acme Cloud, a company.\n## What you'll do\n* Run it\n")["company"], "Acme Cloud")  # "We are X"
        self.assertEqual(C.parse_posting("Site Reliability Engineer\nAcme Cloud is a company that runs clusters.\nResponsibilities\nRun clusters\n")["company"], "Acme Cloud")  # "X is a ..."

    def test_korean_bracket_headings_and_a_wrapped_bullet(self):
        p = C.parse_posting("[주요업무]\n· 데이터 파이프라인 설계 및 운영\n  (Kafka, Airflow 기반)\n· 장애 대응\n\n[자격요건]\n· Python 또는 Go 사용 경험\n\n[우대사항]\n· Kubernetes 운영 경험\n")
        self.assertEqual([i["text"] for i in p["items"]],
                         ["데이터 파이프라인 설계 및 운영 (Kafka, Airflow 기반)", "장애 대응", "Python 또는 Go 사용 경험", "Kubernetes 운영 경험"])  # the wrapped line joins its bullet


class EvidenceTests(unittest.TestCase):  # units_of, split_blocks and evidence_hash: the citable pieces of a profile
    def test_ids_heads_and_resume_flags(self):  # block ids, role heads and the resume flag are what every later check leans on
        U = C.units_of(PROFILE, "ko")  # units of the Korean example person
        self.assertIn("alpha-1#1", U["index"])  # a project block id has the form <project id>#<n>
        self.assertTrue(U["index"]["alpha-1#1"]["resume"])  # the project summary is printed on the resume
        self.assertFalse(U["index"]["alpha-1#2"]["resume"])  # the points are not
        self.assertIn("알파페이", U["heads"]["alpha-1"])  # the company name travels with every block
        self.assertEqual(U["proj"]["alpha-2"][0], "alpha-2#1")  # proj lists the block ids of a project in text order
        self.assertIn("skills#Platform", U["index"])  # a skills row is a unit of its own, named after its category

    def test_project_id_means_the_whole_project(self):  # citing a project id without #n must give the text of all its blocks
        U = C.units_of(PROFILE, "ko")  # units of the Korean example person
        whole = C.unit_text(U, "alpha-2")  # an id with no block number stands for the whole project
        self.assertIn("Argo CD", whole)  # the summary block is part of it
        self.assertIn("저장소 변경", whole)  # so is text that only the flow figure carries
        self.assertNotIn("Redis", whole)  # nothing from another project may leak in

    def test_body_md_blocks_split_bullets_headings_and_tables(self):  # every Markdown shape of body_md must split into the blocks that evidence ids point at
        md = "첫 문단은 배경을 적는다.\n\n- 첫째 항목\n  이어 쓴 줄\n- 둘째 항목\n\n### 소제목\n\n소제목 아래 문단\n\n| 항목 | 내용 |\n|---|---|\n| 대상 | 결제 서버 두 대 |\n"  # a paragraph, a bullet with a wrapped line, a heading with a paragraph, and a two-column table
        self.assertEqual(C.split_blocks(md), ["첫 문단은 배경을 적는다.", "첫째 항목 이어 쓴 줄", "둘째 항목", "소제목: 소제목 아래 문단", "대상 : 결제 서버 두 대"])  # a heading joins the paragraph under it
        blocks = C.split_blocks(md)  # split once, then look for single blocks
        self.assertIn("첫째 항목 이어 쓴 줄", blocks)  # a wrapped line joins the bullet it continues
        self.assertIn("대상 : 결제 서버 두 대", blocks)  # a table data row becomes "cell : cell"
        self.assertNotIn("항목 : 내용", blocks)  # a table header names columns and says nothing itself

    def test_a_heading_joins_the_block_under_it_and_ledger_comments_vanish(self):  # a heading prefixes the block under it, and notes to the ledger's owner are dropped
        blocks = C.split_blocks("<!-- note to the person -->\n본문 한 줄이다.\n\n### 소제목\n\n소제목 아래 문단이다.")  # the HTML comment is a note to the ledger's owner, not a fact the letter may use
        self.assertEqual(blocks, ["본문 한 줄이다.", "소제목: 소제목 아래 문단이다."])  # the note is gone and the heading text leads the paragraph under it

    def test_the_tool_vocabulary_holds_tools_and_not_ordinary_words(self):  # tool names enter the vocabulary, ordinary words and labels do not
        # a slash category, one-word items, a parenthesised alias, a mixed-case item, and a project full of capitalised everyday words
        prof = {"summary": {"intro": "RESULT label stays out"}, "skills": [{"category": "Data/Stream", "items": ["Kubernetes", "Apache Kafka(MSK)", "Go", "pgBouncer"]}],
                "roles": [{"key": "a", "org": "Acme", "projects": [{"id": "a-1", "title": "t", "summary": "We tuned the Stream with ClickHouse and Pull Request habits."}]}]}
        v = C.tool_vocab(C.units_of(prof, "en"))  # the vocabulary a sentence is held against
        for tool in ("kubernetes", "msk", "pgbouncer", "clickhouse"):  # one-word skills items, an alias in parentheses, a mixed-case word, and a name from project text
            self.assertIn(tool, v)  # each of these is a tool the profile really uses
        for word in ("data", "stream", "apache", "request", "pull", "result", "label", "go"):  # category names, words inside longer items, summary labels, capitalised everyday words, and Go (an everyday word as well)
            self.assertNotIn(word, v)  # taking any of these for a tool would reject ordinary prose

    def test_exported_profile_shape(self):  # the exported profile shape feeds evidence the same way as the plain shape
        # bilingual intro, a role with career names, a context table, and a project whose text sits in a Markdown body
        prof = {"summary": {"intro": {"ko": "한국어 소개", "en": "English intro"}},
                "roles": [{"key": "acme", "heading": "아크미 (Acme)", "period": "20.01 ~ 21.01", "career": {"en": {"name": "Acme", "role": "SRE"}},
                           "context": [{"title": "개요", "body_md": "| a | b |\n|---|---|\n| 대상 | 클러스터 |"}],
                           "projects": [{"id": "acme-1", "title": "관측 체계", "period": "20.02", "body_md": "- 대시보드를 고쳤다\n- Prometheus 경보를 정리했다"}]}]}  # the project text is a bulleted body_md, not summary and points
        U = C.units_of(prof, "en")  # English is asked for, so the bilingual intro must resolve to English
        self.assertEqual(U["index"]["summary#intro"]["text"], "English intro")  # the English half is picked
        self.assertIn("Acme", U["heads"]["acme-1"])  # the career name reaches the project head
        self.assertIn("Prometheus", C.unit_text(U, "acme-1#2"))  # the second body_md bullet is block 2 of the project
        self.assertIn("acme#c1.1", U["index"])  # context blocks are numbered <role key>#c<context>.<block>

    def test_hash_changes_with_the_text(self):  # an edit must change the fingerprint of the project that holds it and of no other
        U = C.units_of(PROFILE, "ko")  # fingerprints before the edit
        other = copy.deepcopy(PROFILE)  # edit a copy, never the shared PROFILE
        other["roles"][0]["projects"][0]["points"][0] = "다른 문장"  # change one portfolio bullet of the first project
        V = C.units_of(other, "ko")  # fingerprints after the edit
        self.assertNotEqual(C.evidence_hash(U, ["alpha-1"]), C.evidence_hash(V, ["alpha-1"]))  # the edited project gets a new fingerprint
        self.assertEqual(C.evidence_hash(U, ["alpha-2"]), C.evidence_hash(V, ["alpha-2"]))  # an untouched project keeps its own, so only plans that cite the edited one go stale


class PlanWithoutModelTests(unittest.TestCase):  # plan() with backend none: word matching alone
    @classmethod  # one plan serves all tests of the class, and none of them changes it
    def setUpClass(cls):  # matching reads the whole profile, so do it once
        cls.plan = C.plan(PROFILE, POST_EN, backend="none")  # no model: strengths come from word overlap

    def test_lines_keep_the_posting_order_and_ids(self):  # line ids and order numbers follow the posting
        ids = [l["id"] for l in self.plan["lines"]]  # ids as the plan numbered them
        self.assertEqual(ids[:7], ["d1", "d2", "d3", "d4", "d5", "d6", "q1"])  # six duties d1 to d6, then the first requirement
        self.assertEqual([l["order"] for l in self.plan["lines"]], list(range(1, 16)))  # fifteen lines, numbered in the posting's order
        self.assertEqual(self.plan["lang"], "en")  # an English posting gives an English plan
        self.assertEqual(self.plan["posting"]["company"], "Orion Payments")  # the company is read from the posting

    def test_the_tool_the_profile_lacks_is_a_gap(self):  # a tool the profile never mentions turns the line into a gap
        d6 = next(l for l in self.plan["lines"] if l["id"] == "d6")  # the duty about firmware in Rust
        self.assertEqual(d6["strength"], "none")  # no evidence shows it
        self.assertFalse(d6["use"])  # a gap line is not answered by the letter
        self.assertIn("Rust", d6["missing"])  # the missing tool is named on the line itself
        self.assertIn("Rust", self.plan["gap_terms"])  # and in the plan-wide list that the draft prompt and the fact check read

    def test_a_clear_match_is_found_and_cites_real_ids(self):  # a line the profile clearly covers cites ids that exist
        d1 = next(l for l in self.plan["lines"] if l["id"] == "d1")  # the first duty is the payment approval one
        self.assertIn(d1["strength"], ("strong", "weak"))  # word matching may call it strong or weak, but not none
        self.assertIn("alpha-1", d1["ev"])  # the approval project must be among its evidence
        U = C.units_of(PROFILE, "en")  # units to check the cited ids against
        for l in self.plan["lines"]:  # every planned line
            for e in l["ev"]:  # every id it cites
                self.assertTrue(C.known_id(U, e), e)  # an id missing from the profile would make the letter cite nothing

    def test_groups_follow_the_posting_order_and_only_hold_used_lines(self):  # groups hold used lines only, in the posting's order
        by = {l["id"]: l for l in self.plan["lines"]}  # line lookup by id
        flat = [x for g in self.plan["groups"] for x in g["lines"]]  # all grouped line ids, group by group
        self.assertEqual(flat, sorted(flat, key=lambda x: by[x]["order"]))  # grouped order must equal posting order
        self.assertTrue(all(by[x]["use"] for x in flat))  # a grouped line is a line the letter answers
        self.assertTrue(all(by[x]["strength"] != "none" for x in flat))  # a line without evidence never reaches a group
        self.assertEqual(sorted(x for x in by if by[x]["use"]), sorted(flat))  # and every used line is in a group, none is lost

    def test_a_skipped_line_says_why(self):  # a line left out of the letter has to say why
        for l in self.plan["lines"]:  # every planned line
            if not l["use"]:  # only the lines left out need a reason
                self.assertTrue(l["skipped"], l["id"])  # the line id is the failure message

    def test_the_plan_is_plain_json(self):  # plan.json must survive a save and read back unchanged
        self.assertEqual(json.loads(json.dumps(self.plan)), self.plan)  # a set, tuple or object left in the plan would break the round trip
        self.assertEqual(self.plan["matched_by"], "words")  # with no model, word overlap did the matching

    def test_korean_posting_gives_a_korean_plan(self):  # a Korean posting gives a Korean plan with the same gap detection
        pk = C.plan(PROFILE, POST_KO, backend="none")  # no model here either
        self.assertEqual(pk["lang"], "ko")  # the letter language follows the posting
        self.assertEqual(pk["posting"]["company"], "델타페이")  # company from the Korean opening sentence
        self.assertIn("Rust", pk["gap_terms"])  # the tool gap is found in Korean text as well

    def test_no_lines_stops_with_a_message(self):  # a posting with no lists stops with a message instead of producing an empty plan
        with self.assertRaises(SystemExit):  # the stop is a SystemExit that carries the message
            C.plan(PROFILE, "Just a paragraph about a company with no lists at all.", backend="none")  # prose only, so there is no line to match


class PlanWithModelTests(unittest.TestCase):  # plan() with a stand-in model: its answer is used only after checks against the profile
    def answer(self, **over):  # a canned reply; a test overrides the keys it wants to vary
        # d1 mixes a real and an invented id, d4 claims strong with no id, d6 is strong but names a tool nobody shows, p3 names a tool only a skills row has
        base = {"lines": [
            {"id": "d1", "ids": ["alpha-1", "no-such-id"], "strength": "strong", "missing": [], "basis": "approval path split"},  # one real id and one invented id
            {"id": "d2", "ids": ["beta-1"], "strength": "strong", "missing": [], "basis": "kafka events"},  # a plain valid match
            {"id": "d3", "ids": ["alpha-2"], "strength": "strong", "missing": ["Not In Line"], "basis": "argo and helm"},  # declares a tool that the line does not contain
            {"id": "d4", "ids": [], "strength": "strong", "missing": [], "basis": "claims strong without an entry"},  # strong with no entry behind it
            {"id": "d5", "ids": ["beta-3"], "strength": "weak", "missing": [], "basis": "doc and training"},  # a weak match, kept as it is
            {"id": "d6", "ids": ["alpha-1"], "strength": "strong", "missing": ["Rust"], "basis": "says strong, but names a tool nobody has"},  # strong, but the line names a tool that nothing shows
            {"id": "p3", "ids": ["alpha-2"], "strength": "strong", "missing": ["Terraform"], "basis": "tool shown in a skills row only"}],  # a tool shown only by a skills row
            "groups": [{"lines": ["d1", "d2"], "theme": "services"}, {"lines": ["d3", "d5"], "theme": "platform"}], "fit": ["alpha-1", "ghost"]}  # groups keep the posting order; fit holds one real and one invented project
        base.update(over)  # a test replaces only the keys it needs to vary
        return base  # stands in for the parsed answer of llm.run

    def test_the_models_view_is_checked_against_the_profile(self):  # every claim of the model is checked against the profile before it enters the plan
        with model({"cover-match": self.answer()}):  # plan() asks llm.run, which is replaced here
            pl = C.plan(PROFILE, POST_EN)  # no backend is named, so the stand-in acts as the model
        by = {l["id"]: l for l in pl["lines"]}  # line lookup by id
        self.assertEqual(by["d1"]["ev"], ["alpha-1"])  # an id that does not exist is dropped
        self.assertEqual(by["d4"]["strength"], "none")  # strong without an entry is no match
        self.assertEqual(by["d3"]["missing"], [])  # a declared term that the line does not contain is ignored
        self.assertEqual(by["d6"]["strength"], "weak")  # a tool the line names and no evidence shows takes the line down a step
        self.assertEqual(by["d6"]["missing"], ["Rust"])  # the tool stays on the line as a gap
        self.assertIn("Rust", pl["gap_terms"])  # and joins the plan-wide gap list
        self.assertEqual(by["p3"]["missing"], [])  # Terraform is named by a skills row, which is added as evidence
        self.assertIn("skills#Platform", by["p3"]["ev"])  # the skills row that shows the tool becomes evidence
        self.assertEqual(by["p3"]["strength"], "strong")  # every tool is shown now, so the line keeps its strength
        self.assertEqual(pl["fit"], ["alpha-1"])  # the invented project id is dropped from fit
        self.assertEqual(pl["matched_by"], "model")  # the plan records that a model did the matching
        self.assertEqual([g["lines"] for g in pl["groups"]], [["d1", "d2"], ["d3", "d5"]])  # the model's sound grouping is taken over unchanged
        self.assertFalse(by["q1"]["use"])  # lines the model left out of every group are not answered

    def test_unsound_groups_fall_back_to_the_plans_own(self):  # a grouping that breaks the posting order is replaced by the plan's own
        bad = self.answer(groups=[{"lines": ["d1", "d3"], "theme": "a"}, {"lines": ["d2"], "theme": "b"}])  # d2 would come after d3
        with model({"cover-match": bad}):  # the line matches are fine, only the groups are wrong
            pl = C.plan(PROFILE, POST_EN)  # default backend, so the stand-in answers
        self.assertTrue(any("groups were not sound" in n for n in pl["notes"]))  # the plan tells the user why it regrouped
        by = {l["id"]: l for l in pl["lines"]}  # line lookup by id
        flat = [x for g in pl["groups"] for x in g["lines"]]  # all grouped line ids, group by group
        self.assertEqual(flat, sorted(flat, key=lambda x: by[x]["order"]))  # the plan's own grouping keeps the posting order

    def test_a_model_that_is_down_leaves_word_matching(self):  # a model that cannot answer leaves the plan to word matching, with a warning
        with model({}):  # an empty table makes every call raise LLMUnavailable
            pl = C.plan(PROFILE, POST_EN)  # default backend, so the failing stand-in is asked
        self.assertEqual(pl["matched_by"], "words")  # the plan says words did the matching
        self.assertTrue(any("no model matched" in n for n in pl["notes"]))  # and warns that the strengths are rough

    def test_the_model_is_asked_once_for_matching(self):  # matching costs exactly one model call
        with model({"cover-match": self.answer()}) as m:  # m records every call that plan() makes
            C.plan(PROFILE, POST_EN)  # default backend, so the stand-in is used
        self.assertEqual([c[0] for c in m.calls], ["cover-match"])  # no other task name may appear
        self.assertIn("d6. [duty] Write firmware in Rust", m.calls[0][1])  # the prompt lists each posting line with its id and kind
        self.assertIn("alpha-2 |", m.calls[0][1])  # the profile index is in the prompt

    def test_backend_none_never_calls(self):  # the none backend must never reach the model, even when one would answer
        with model({"cover-match": self.answer()}) as m:  # an answer is ready but has to stay unused
            C.plan(PROFILE, POST_EN, backend="none")  # the explicit opt-out
        self.assertEqual(m.calls, [])  # not even an attempt was made


def make_ctx(lang="en", numbers="forbid", gaps=("Rust",), allow=("Orion Payments",), banned=()):
    """A checking context for sentences about the fictional person."""
    style = C.load_style(None)  # the default style pack merged with the cover defaults
    style["cover"]["numbers"] = numbers  # a test picks the number policy
    style["cover"]["banned_words"] = list(banned)  # a test can add banned words
    # a plan in miniature: company and role from the posting, a short overview, the gap tools from the caller
    plan = {"lang": lang, "posting": {"company": allow[0] if allow else "", "role": "Backend Platform Engineer", "overview": "We run a payment service"},
            "gap_terms": list(gaps), "allow": []}
    return C.make_ctx(C.units_of(PROFILE, lang), plan, style)  # the same context builder that draft and check use


def problems(ctx, text, ev, kind="duties", **kw):  # reduces the issues of a sentence to their codes, so assertions stay short
    return [i["code"] for i in C.fact_issues(sent(text, ev, **kw), kind, ctx)]  # runs the full per-sentence check


class FactCheckTests(unittest.TestCase):  # fact_issues: ids, numbers, names, tools and style of one sentence
    def test_a_grounded_sentence_passes(self):  # a sentence that stays inside its evidence raises no issue
        self.assertEqual(problems(make_ctx("ko"), "알파페이 결제 승인 서비스에서 승인 기능을 독립된 배포 단위로 나누었습니다.", ["alpha-1#1"]), [])  # the company and the facts both come from block alpha-1#1 and its head

    def test_numbers_are_forbidden_even_when_the_evidence_has_them(self):  # digits are banned in the default style even when the cited text has the same digits
        ctx = make_ctx("ko")  # default policy: forbid
        self.assertEqual(problems(ctx, "알파페이에서 배포 시간을 42분에서 9분으로 줄였습니다.", ["alpha-1"]), ["number"])  # 42 and 9 both appear in the evidence, yet the forbid policy rejects them
        self.assertEqual(problems(ctx, "알파페이에서 두 개의 배포 단위를 만들었습니다.", ["alpha-1"]), ["number_word"])  # a counted amount in words (two items) is a number word
        self.assertEqual(problems(make_ctx("en"), "I cut it by 40% in three steps.", ["alpha-1"]), ["number", "number_word"])  # a percentage and a spelled-out count each get their own issue

    def test_numbers_pass_when_the_style_allows_them_and_the_evidence_states_them(self):  # with the evidence policy only numbers that the cited text states are allowed
        ctx = make_ctx("ko", numbers="evidence")  # switch the policy to evidence
        self.assertEqual(problems(ctx, "알파페이에서 배포 시간을 42분에서 9분으로 줄였습니다.", ["alpha-1"]), [])  # 42 and 9 are in alpha-1, so nothing is flagged
        self.assertEqual(problems(ctx, "알파페이에서 배포 시간을 50분에서 9분으로 줄였습니다.", ["alpha-1"]), ["number"])  # 50 is not in the evidence, so exactly one number issue

    def test_a_tool_outside_the_cited_evidence_is_dropped_and_the_hint_names_where_it_lives(self):  # a tool missing from the cited evidence is rejected, and the hint says where the profile does use it
        ctx = make_ctx("ko")  # Korean letter
        got = C.fact_issues(sent("알파페이에서 Terraform 으로 인프라를 관리했습니다.", ["alpha-2#1"]), "duties", ctx)  # Terraform is in a skills row, not in the cited block alpha-2#1
        self.assertEqual([i["code"] for i in got], ["name"])  # one name issue and nothing else
        self.assertIn("skills#Platform", got[0]["detail"])  # the detail points to the unit that holds the word
        self.assertEqual(problems(ctx, "알파페이에서 Argo CD 와 Helm 으로 공용 배포 경로를 만들었습니다.", ["alpha-2#1"]), [])  # Argo CD and Helm are in the cited block, so they pass

    def test_an_organisation_the_evidence_lacks_is_dropped(self):  # an organisation the cited text lacks is rejected
        self.assertEqual(problems(make_ctx("ko"), "카카오페이에서 일했습니다.", ["alpha-2#1"]), ["org"])  # the org issue, not a name issue, because the name is in Korean

    def test_the_postings_company_may_be_named(self):  # the company of the posting is allowed without evidence
        self.assertEqual(problems(make_ctx("ko", allow=("델타페이",)), "델타페이 직무에 지원합니다.", [], "opening", frame=True), [])  # allowed through the plan's company; an opening frame cites nothing

    def test_ids_must_exist_and_frames_stay_in_their_place(self):  # unknown ids, missing ids and misplaced frames each have their own code
        ctx = make_ctx("ko")  # Korean letter
        self.assertEqual(problems(ctx, "승인 경로를 나누었습니다.", ["alpha-9#1"]), ["unknown_id"])  # alpha-9 does not exist in the profile
        self.assertEqual(problems(ctx, "승인 경로를 나누었습니다.", []), ["no_ev"])  # a sentence that is not a frame needs at least one id
        self.assertEqual(problems(ctx, "승인 경로를 나누었습니다.", ["alpha-1"], "opening", frame=True), ["frame_ev"])  # a framing sentence must not cite evidence
        self.assertEqual(problems(ctx, "감사합니다.", [], "duties", frame=True), ["frame_where"])  # framing sentences belong to the opening and the closing only
        self.assertEqual(problems(ctx, "승인 경로를 나누었습니다.", ["alpha-1"]), [])  # a whole-project id is fine

    def test_english_names_must_come_from_the_cited_evidence(self):  # English names must occur in the cited evidence, not just anywhere in the profile
        ctx = make_ctx("en")  # English letter, so the capitalised-word rules apply
        self.assertEqual(problems(ctx, "I built the shared path on Argo CD and Helm.", ["alpha-2#1"]), [])  # Argo CD and Helm are in the cited block
        self.assertEqual(problems(ctx, "I moved order updates onto Kafka events.", ["alpha-1#1"]), ["name"])  # Kafka lives in another project
        self.assertEqual(problems(ctx, "I moved order updates onto Kafka events.", ["beta-1#1"]), [])  # the same sentence passes with the project that does mention Kafka
        self.assertEqual(problems(ctx, "I worked with Postgres every day.", ["beta-2#1"]), ["name"])  # the cited block never names this database
        self.assertEqual(problems(ctx, "Kubernetes was the platform for it.", ["alpha-2#1"]), ["name"])  # a name at the start of a sentence counts too

    def test_ordinary_english_words_need_no_evidence(self):  # common English words need no evidence
        self.assertEqual(problems(make_ctx("en"), "Every request gets a key so that a retry cannot lead to a duplicate approval.", ["alpha-1#3"]), [])  # the evidence is Korean and holds none of these English words, yet nothing is flagged

    def test_a_translated_name_needs_a_source_in_the_evidence(self):  # a name spelled differently from the evidence passes only with a declared source that the evidence holds
        ctx = make_ctx("en")  # English letter over Korean evidence
        text = "At Alpha Pay I split the approval path out of a single application."  # an English spelling of a company that the evidence writes in Korean
        self.assertEqual(problems(ctx, text, ["alpha-1#1"]), ["name", "name"])  # with no declared source each word of the name is flagged
        self.assertEqual(problems(ctx, text, ["alpha-1#1"], names={"Alpha Pay": "알파페이"}), [])  # a source found in the cited evidence makes the spelling count
        self.assertEqual(problems(ctx, text, ["alpha-1#1"], names={"Alpha Pay": "베타커머스"}), ["name_src", "name", "name"])  # a source that the evidence does not hold is rejected, and the words stay unexplained

    def test_a_tool_the_plan_marked_as_missing_is_never_claimed(self):  # a tool the plan marked as missing is never claimed
        ctx = make_ctx("ko")  # gap terms default to Rust
        self.assertIn("gap_term", problems(ctx, "Rust 로 단말 펌웨어를 만들었습니다.", ["alpha-1"]))  # a Korean sentence that names the tool in Latin letters
        self.assertIn("gap_term", problems(make_ctx("en"), "I write rust all day.", ["alpha-1"]))  # case does not matter

    def test_style_rules(self):  # banned characters, banned words and run-on sentences are style issues
        ctx = make_ctx("en", banned=("leverage",))  # leverage is banned for this test
        ctx.style["banned_chars"] = "—"  # the em dash is banned
        self.assertEqual(problems(ctx, "I leverage the path.", ["alpha-1"]), ["banned_word"])  # a banned word in a sentence
        self.assertEqual(problems(ctx, "I built the path — alone.", ["alpha-1"]), ["banned_char"])  # a banned character
        self.assertEqual(problems(ctx, "word " * 60, ["alpha-1"]), ["too_long"])  # sixty words are beyond the sentence limit
        self.assertEqual(problems(ctx, "I leveraged nothing.", ["alpha-1"]), [])  # a word, not a prefix of one

    def test_highlight_marks_are_removed(self):  # the resume's == highlight marks must not reach the letter
        self.assertEqual(sent("A ==marked== phrase", ["alpha-1"])["text"], "A marked phrase")  # normalising drops the marks


class ResumeRepeatTests(unittest.TestCase):  # repeat_hits: a sentence copied from the resume is flagged, a reused phrase is not
    # two resume lines, one sentence per line, as a PDF text extraction would give them
    RESUME = ["Metrics, logs and alerts on Prometheus, Grafana and Loki, with service levels judged by error budgets.",
              "Turned the payment service deployment into code with Argo CD, Helm, Kustomize and GitHub Actions, with a nightly check for manual changes."]

    def test_a_copied_line_is_found_and_a_new_wording_is_not(self):  # a verbatim resume line and most of a shorter variant are repeats; a fresh wording is not
        style = C.load_style(None)  # default run limits: 14 words, or 6 words that make up 60 percent of the sentence
        # one paragraph: the exact resume line, a shortened copy of it, and a new sentence on the same topic
        par = [{"sentences": [{"text": "Turned the payment service deployment into code with Argo CD, Helm, Kustomize and GitHub Actions, with a nightly check for manual changes."},
                              {"text": "Turned the payment service deployment into code with Argo CD, Helm and GitHub Actions."},
                              {"text": "I rebuilt observability on Prometheus and Loki after the old dashboards had gone blank."}]}]
        hits = C.repeat_hits(par, self.RESUME, "en", style)  # the same check that draft and check run
        self.assertEqual(list(hits), [(0, 0), (0, 1)])  # the whole line, and most of a shorter one
        self.assertGreaterEqual(hits[(0, 0)][0], 14)  # the copied line shares at least the 14-word run limit

    def test_reusing_a_phrase_is_allowed(self):  # sharing a long phrase is allowed when the sentence adds plenty of its own
        style = C.load_style(None)  # default run limits
        par = [{"sentences": [{"text": "On the payment team I turned the payment service deployment into code with Argo CD, Helm, then wrote the runbooks for the night shift myself."}]}]  # a phrase of the resume sits inside a longer sentence of the letter's own
        n, _ = C.shared_run(par[0]["sentences"][0]["text"], "\n".join(self.RESUME), "en")  # measure the shared run directly
        self.assertGreaterEqual(n, 9)  # a long shared phrase ...
        self.assertEqual(C.repeat_hits(par, self.RESUME, "en", style), {})  # ... in a sentence that says more is not a copy

    def test_a_shared_tool_list_alone_is_not_a_repeat(self):  # a list of the same tools is not a copy of the line
        style = C.load_style(None)  # default run limits
        par = [{"sentences": [{"text": "I run monitoring on Prometheus, Loki and Grafana."}]}]  # only the tool names overlap with the resume line
        self.assertEqual(C.repeat_hits(par, self.RESUME, "en", style), {})  # the shared run is shorter than the minimum, so there is no hit

    def test_korean_runs_count_characters(self):  # Korean runs are counted in characters, which survive spacing differences
        style = C.load_style(None)  # default run limits
        resume = ["주문 장애 유형별 대응 절차를 문서로 만들고 당번 교육에 썼다."]  # one resume line
        same = [{"sentences": [{"text": "주문 장애 유형별 대응 절차를 문서로 만들고 당번 교육에 썼다고 적었습니다."}]}]  # the resume line plus a short tail, with the same spacing
        fresh = [{"sentences": [{"text": "장애는 유형별로 절차를 문서에 남겨 두고 교육에 그대로 썼습니다."}]}]  # the same topic in other words
        self.assertEqual(list(C.repeat_hits(same, resume, "ko", style)), [(0, 0)])  # the copy is found
        self.assertEqual(C.repeat_hits(fresh, resume, "ko", style), {})  # the reworded sentence is not

    def test_without_a_resume_file_the_profiles_resume_text_stands_in(self):  # without a resume file the profile's own resume-bound text is the comparison
        lines, src = C.resume_source(None, PROFILE, "ko")  # no file given, so the profile stands in
        self.assertTrue(any("승인 경로를 독립 배포 단위로" in l for l in lines))  # the project summary, which the resume prints, is among the lines


class PlanHelperTests(unittest.TestCase):  # small helpers of the planner: tool words, whole-word matching, trimming
    def test_declared_missing_terms_become_tool_words(self):  # terms that a model declares as missing are reduced to tool words
        # an unclosed bracket, a pair joined by a space, a slash pair, a degree (not a tool), a lowercase tool, a Korean certificate and a two-letter word that is dropped
        self.assertEqual(C.clean_terms(["AMD (AOCC", "PGI OpenACC", "UNIX/Linux", "Bachelor’s Degree", "gcc", "정보보안기사", "IT"]),
                         ["AMD", "AOCC", "PGI", "OpenACC", "UNIX", "Linux", "gcc", "정보보안기사"])

    def test_mentions_matches_whole_words_only(self):  # a short tool name must not match inside a longer word
        self.assertTrue(C.mentions("Run Terraform/Helm and Rust daily", "Rust"))  # a whole word in the middle of a sentence
        self.assertTrue(C.mentions("run rust daily", "Rust"))  # lower case counts as the same tool
        self.assertFalse(C.mentions("trusted by many", "Rust"))  # "trusted" holds the letters but is not the word
        self.assertTrue(C.mentions("정보보안기사 자격증", "정보보안기사"))  # Korean terms match as plain text

    def test_a_long_plan_is_trimmed_to_the_strongest_duties_first(self):  # when too many lines remain, the weak and lower-ranked ones go first
        # d2 is weak and the other duties strong; q1 is a strong requirement, which still ranks below the duties
        lines = [{"id": f"d{i}", "order": i, "kind": "duty", "strength": "weak" if i == 2 else "strong"} for i in range(1, 5)] + \
                [{"id": "q1", "order": 5, "kind": "requirement", "strength": "strong"}]
        groups = [{"id": "g1", "lines": ["d1", "d2", "d3"], "theme": "a"}, {"id": "g2", "lines": ["d4", "q1"], "theme": "b"}]  # two groups, as the planner builds them
        kept, dropped = C.trim_groups(groups, lines, 3)  # room for three lines only
        self.assertEqual([g["lines"] for g in kept], [["d1", "d3"], ["d4"]])  # d2 (weak) leaves the first group and q1 leaves the second
        self.assertEqual(sorted(dropped), ["d2", "q1"])  # the dropped ids are reported, so the plan can say why
        self.assertEqual(C.trim_groups(groups, lines, 9), (groups, []))  # within the limit nothing changes and nothing is dropped


class WorkspaceHintTests(unittest.TestCase):
    def test_a_style_pack_named_in_a_plan_is_found_in_the_workspace_above_the_job_folder(self):
        with tempfile.TemporaryDirectory() as d:
            ws = pathlib.Path(d)
            (ws / "style").mkdir()
            (ws / "style" / "mine.json").write_text(json.dumps({"banned_chars": "~"}), encoding="utf-8")  # the workspace's own pack
            job = ws / "jobs" / "acme" / "cover"
            job.mkdir(parents=True)
            self.assertEqual(C.load_style("mine", hints=C.workspace_hints(job))["banned_chars"], "~")
            with self.assertRaises(SystemExit):  # without the hints the pack is not found, and the typo guard stops
                C.load_style("mine")


class CoverageTests(unittest.TestCase):  # coverage_issues: missing answers, wrong order, and answers to lines the profile cannot show
    # d1 and d2 are to be answered; d3 is a gap that the plan left out of the letter
    PLAN = {"lines": [{"id": "d1", "order": 1, "use": True, "strength": "strong"}, {"id": "d2", "order": 2, "use": True, "strength": "weak"},
                      {"id": "d3", "order": 3, "use": False, "strength": "none"}]}

    def paras(self, *spec):  # one paragraph per spec entry, each answering the given line ids
        return [{"id": f"p{i}", "duties": d, "sentences": [{"text": "x", "duties": d}]} for i, d in enumerate(spec, 1)]  # the sentence carries the same tags as its paragraph, so either level answers the lines

    def codes(self, paras):  # issue code and the line id it concerns, in the order reported
        return [(i["code"], i.get("id") or i.get("a")) for i in C.coverage_issues(paras, self.PLAN)]  # the order issue keeps its line under a, every other issue under id

    def test_in_order_and_complete(self):  # both wanted lines answered in the posting's order raise nothing
        self.assertEqual(self.codes(self.paras(["d1"], ["d2"])), [])  # d1 first, then d2, as planned

    def test_a_missing_line(self):  # a wanted line with no answer is reported
        self.assertEqual(self.codes(self.paras(["d1"])), [("missing_line", "d2")])  # d2 has no paragraph

    def test_out_of_order(self):  # answers in the wrong sequence are reported
        self.assertEqual(self.codes(self.paras(["d2"], ["d1"])), [("order", "d1")])  # d2 is answered before d1

    def test_answering_a_line_the_profile_cannot_show(self):  # answering a line the plan marked as not shown is reported
        self.assertEqual(self.codes(self.paras(["d1"], ["d2"], ["d3"])), [("gap_line", "d3")])  # d3 has strength none and was not used

    def test_a_sentence_without_tags_answers_its_paragraphs_lines(self):  # the lines tagged on a paragraph count for sentences that carry no tags
        paras = [{"id": "p1", "duties": ["d1", "d2"], "sentences": [{"text": "x"}]}]  # the sentence has no duties of its own
        self.assertEqual(C.coverage_issues(paras, self.PLAN), [])  # both lines count as answered through the paragraph


class DraftTests(unittest.TestCase):  # draft(): one call for the body, an optional repair, trimming, and the skeleton fallback
    def setUp(self):  # fresh copies of the example files for every test
        self.plan = json.loads((EX / "plan_en.json").read_text(encoding="utf-8"))  # the reviewed English plan
        self.good = json.loads((EX / "cover_en.json").read_text(encoding="utf-8"))  # the reviewed letter, which passes every check
        self.style = C.load_style(str(EX / "style.json"))  # the example style pack: no numbers, a 470 word budget

    def body(self, edit=None):  # a model answer made from the good letter, optionally spoiled by a function
        paras = [{"id": p["id"], "sentences": copy.deepcopy(p["sentences"])} for p in self.good["paragraphs"]]  # copied, so an edit never touches self.good
        if edit:  # the test decides what is wrong with the answer
            edit(paras)  # edits the copy in place
        return {"paragraphs": paras}  # the shape the model returns

    def run_draft(self, answers, **kw):  # runs draft() against a stand-in and hands back the letter and the recorder
        with model(answers) as m:  # m records the calls
            out = C.draft(PROFILE, self.plan, style=self.style, **kw)  # the example style pack makes the limits known
        return out, m  # tests read both the letter and the prompts

    def test_the_opening_and_the_motivation_may_cite_the_summary_rows(self):
        with model({"cover-draft": self.body()}) as m:
            C.draft(PROFILE, self.plan, style=self.style)
        prompt = m.calls[0][1]  # the first call carries the paragraph plan
        opening = prompt[prompt.index("p1 (opening)"):prompt.index("p2 (motivation)")]
        motivation = prompt[prompt.index("p2 (motivation)"):prompt.index("p3 (duties)")]
        for uid in ("summary#c1", "summary#h1", "summary#l1"):  # cards, highlights and layers name the clients and the places
            self.assertIn(uid, opening)
        self.assertIn("summary#l1", motivation)  # the layers show the path through the stack
        self.assertNotIn("summary#c1", motivation)  # the cards stay with the opening

    def test_a_clean_answer_is_kept_whole_with_one_call(self):  # a clean answer is kept whole and needs no repair call
        out, m = self.run_draft({"cover-draft": self.body()})  # the unchanged letter body
        self.assertEqual([c[0] for c in m.calls], ["cover-draft"])  # one call: nothing needed repair
        self.assertEqual(out["dropped"], [])  # nothing was rejected
        self.assertEqual(out["unresolved"], [])  # nothing is left open
        self.assertEqual(out["stats"]["sentences"], 16)  # all sixteen sentences survive
        self.assertEqual(out["signature"], "Gildong Hong")  # "Last, First" becomes "First Last" in an English letter

    def test_sentences_with_numbers_or_foreign_tools_are_dropped_and_repaired_once(self):  # a sentence with a number and a foreign tool is dropped, and one repair call fixes the paragraph
        def spoil(paras):  # adds one bad sentence to a paragraph
            paras[3]["sentences"].append({"text": "I cut the deploy time by 40% with Terraform.", "ev": ["alpha-2#1"], "duties": ["d3"]})  # a figure and a tool that the cited block lacks, in the fourth paragraph
        fixed = {"paragraphs": [{"id": "p4", "sentences": [dict(s) for s in self.good["paragraphs"][3]["sentences"]]}]}  # the repair answer returns the paragraph without the bad sentence
        out, m = self.run_draft({"cover-draft": self.body(spoil), "cover-repair": fixed})  # the draft carries the bad sentence; the repair answer is clean
        self.assertEqual([c[0] for c in m.calls], ["cover-draft", "cover-repair"])  # one draft call, then one repair call
        self.assertEqual(len(out["dropped"]), 1)  # exactly the one spoiled sentence was rejected
        self.assertEqual([i["code"] for i in out["dropped"][0]["issues"]], ["number", "name"])  # both the figure and the tool were found
        repair_prompt = m.calls[1][1]  # the second call is the repair request
        self.assertIn("rejected: number not allowed: 40%", repair_prompt)  # the verdict on the rejected sentence is spelled out for the model
        self.assertNotIn("p3 (duties)", repair_prompt)  # only the paragraph that lost a sentence is sent again
        self.assertEqual(out["stats"]["calls"], 2)  # both calls are counted
        self.assertEqual(out["unresolved"], [])  # the repair closed every gap

    def test_a_line_that_loses_its_only_answer_is_asked_again_and_reported_when_still_open(self):  # a line that loses its only answer is asked for again, and reported if it stays unanswered
        def spoil(paras):  # p5 is the only paragraph that answers d5
            for x in paras[4]["sentences"]:  # every sentence of that paragraph
                x["ev"] = []  # d5 loses the evidence of both its sentences
        out, m = self.run_draft({"cover-draft": self.body(spoil), "cover-repair": {"paragraphs": []}})  # the repair answer is empty, so nothing comes back
        self.assertEqual([c[0] for c in m.calls], ["cover-draft", "cover-repair"])  # the loss of d5 triggered the repair call
        self.assertEqual([(u["code"], u["id"]) for u in out["unresolved"]], [("missing_line", "d5")])  # d5 stays unanswered and is reported as open
        self.assertNotIn("p5", [p["id"] for p in out["paragraphs"]])  # a paragraph without sentences is not printed

    def test_a_repeat_of_the_resume_is_sent_back(self):  # a sentence that repeats the resume goes back for rewording, and is reported if it stays
        echoed = self.good["paragraphs"][3]["sentences"][1]["text"]  # a sentence the resume of this application also prints
        out, m = self.run_draft({"cover-draft": self.body(), "cover-repair": {"paragraphs": []}}, resume=["Skills. " + echoed + " Education."])  # the resume of this application contains the sentence; the repair gives nothing back
        self.assertEqual([c[0] for c in m.calls], ["cover-draft", "cover-repair"])  # the repeat alone triggered the repair call
        self.assertIn("repeats the resume", m.calls[1][1])  # the repair prompt says why the sentence was rejected
        self.assertEqual([u["code"] for u in out["unresolved"]], ["repeat"])  # the repeat is the one open item

    def test_no_repair_when_asked_not_to(self):  # repairs=0 switches the repair round off
        def spoil(paras):  # adds one sentence with a number
            paras[3]["sentences"].append({"text": "I cut it by 40%.", "ev": ["alpha-2#1"], "duties": ["d3"]})  # a percentage, which the style forbids
        out, m = self.run_draft({"cover-draft": self.body(spoil)}, repairs=0)  # no repair answer is offered, and repairs=0 says not to ask
        self.assertEqual(len(m.calls), 1)  # the draft call only
        self.assertEqual(len(out["dropped"]), 1)  # the bad sentence is gone and nothing replaced it

    def test_a_letter_over_its_budget_is_cut_from_the_longest_paragraph_without_losing_a_line(self):  # a letter over its budget is cut from the paragraph furthest over its limit, and no planned line loses its answer
        style = copy.deepcopy(self.style)  # a private copy of the style pack
        style["cover"]["max_words"]["en"] = 330  # a budget below the words of the clean letter
        with model({"cover-draft": self.body()}):  # the model returns the full letter
            out = C.draft(PROFILE, self.plan, style=style)  # trimming happens inside draft()
        self.assertLessEqual(C.words_of(out)[0], 330)  # the trimmed letter fits the budget
        self.assertTrue(out["dropped"] and all(d["round"] == "trim" for d in out["dropped"]))  # something was cut, and every cut is marked as a trim
        self.assertEqual(out["unresolved"], [])  # every planned line still has an answer
        self.assertTrue(all(len(p["sentences"]) >= 1 for p in out["paragraphs"]))  # no paragraph was emptied

    def test_the_prompt_gives_every_paragraph_its_own_limit(self):  # every paragraph gets its own word limit in the prompt
        with model({"cover-draft": self.body()}) as m:  # capture the prompt
            C.draft(PROFILE, self.plan, style=self.style)  # the clean letter needs no repair
        prompt = m.calls[0][1]  # the draft request
        limits = C.allocation(C.paragraph_plan(self.plan, C.units_of(PROFILE, "en")), 470)  # the same allocation draft() used, for the 470 word budget
        self.assertAlmostEqual(sum(limits.values()), 470, delta=12)  # the limits add up to the budget, give or take the rounding of each share
        self.assertGreater(limits["p3"], limits["p5"])  # two lines get more room than one
        self.assertIn(f"p3 (duties): {C.KIND_PURPOSE['duties']} At most {limits['p3']} words.", prompt)  # the prompt shows the limit right after the paragraph's purpose line

    def test_trimming_takes_the_least_relevant_sentence_of_the_paragraph_furthest_over_its_limit(self):  # the first cut is the sentence that speaks least to its posting lines, in the paragraph furthest over its limit
        filler = "A filler sentence that repeats nothing in particular and only adds words to the paragraph."  # shares no content word with any posting line

        def pad(paras):  # the incident paragraph runs long with sentences that speak to no posting line
            paras[4]["sentences"] += [{"text": filler, "ev": ["beta-3#1"], "duties": ["d5"]}] * 3  # three copies of the filler, tagged to d5, so they count as answers of that line
        style = copy.deepcopy(self.style)  # a private copy of the style pack
        style["cover"]["max_words"]["en"] = 380  # the clean letter has 374 words
        with model({"cover-draft": self.body(pad)}):  # the padded letter is the model's answer
            out = C.draft(PROFILE, self.plan, style=style)  # trimming happens inside draft()
        self.assertLessEqual(C.words_of(out)[0], 380)  # the letter fits the budget again
        self.assertEqual(out["unresolved"], [])  # d5 keeps an answer, so nothing is left open
        self.assertEqual(out["dropped"][0]["text"], filler)  # the first cut is the sentence that answers nothing, in the paragraph furthest over
        self.assertEqual(out["dropped"][0]["paragraph"], "p5")  # p5 is the padded paragraph
        self.assertTrue(all(d["round"] == "trim" for d in out["dropped"]))  # every cut here is a trim, none is a fact-check drop

    def test_a_budget_that_cannot_be_met_without_losing_an_answer_is_left_for_check(self):  # when the budget cannot be met without losing an answer, trimming stops and check reports the length
        style = copy.deepcopy(self.style)  # a private copy of the style pack
        style["cover"]["max_words"]["en"] = 20  # far below what one sentence per paragraph needs
        with model({"cover-draft": self.body()}):  # the model returns the full letter
            out = C.draft(PROFILE, self.plan, style=style)  # trimming gives up when only answers are left to cut
        self.assertGreater(C.words_of(out)[0], 20)  # one sentence per paragraph is the least that keeps every answer
        self.assertEqual(out["unresolved"], [])  # no planned line lost its answer, and length is not an open item of the draft
        with tempfile.TemporaryDirectory() as d:  # the same limit applied by `check`
            f = pathlib.Path(d) / "tight.json"  # a style pack file with the same 20 word limit
            f.write_text(json.dumps({"cover": {"max_words": {"en": 20}}}), encoding="utf-8")  # only the cover options that differ from the defaults
            res = C.check_cover(PROFILE, out, style_spec=str(f))  # check measures the length against the same limit
        self.assertEqual({c["key"]: c["status"] for c in res["checks"]}["length"], "fail")  # and fails the length check, which is where the user sees the problem

    def test_a_gap_that_was_already_open_does_not_block_trimming(self):
        def drop_d3(paras):  # the answer to d3 is missing before any cutting starts
            paras[3]["sentences"] = [x for x in paras[3]["sentences"] if "d3" not in x["duties"]]
        style = copy.deepcopy(self.style)
        style["cover"]["max_words"]["en"] = 330  # well under the clean letter, so cuts are needed
        with model({"cover-draft": self.body(drop_d3), "cover-repair": {"paragraphs": []}}):
            out = C.draft(PROFILE, self.plan, style=style)
        self.assertLessEqual(C.words_of(out)[0], 330)  # trimming still worked
        self.assertEqual([(u["code"], u["id"]) for u in out["unresolved"]], [("missing_line", "d3")])  # and the old gap is still reported, once

    def test_a_plan_made_from_other_evidence_is_reported(self):  # a plan made from older evidence is reported, not hidden
        other = copy.deepcopy(PROFILE)  # a profile copy that differs from what the plan saw
        other["roles"][1]["projects"][0]["points"][1] = "소비 지연을 보지 않았다"  # beta-1 changed after the plan
        with model({"cover-draft": self.body()}):  # the model answers as usual
            out = C.draft(other, self.plan, style=self.style)  # drafted against the changed profile
        self.assertEqual([u["code"] for u in out["unresolved"]], ["stale"])  # only the stale warning is open

    def test_no_model_gives_a_skeleton_to_fill_by_hand(self):  # no model leaves an empty skeleton to fill by hand
        out, m = self.run_draft({})  # an empty table: every call fails
        self.assertIn("no answer", out["why_empty"])  # the reason is kept in the file
        self.assertTrue(all(p["sentences"] == [] for p in out["paragraphs"]))  # no sentence was written
        self.assertEqual([p["duties"] for p in out["paragraphs"] if p["kind"] == "duties"], [["d1", "d2"], ["d3", "d4"], ["d5"], ["p2"]])  # duty paragraphs keep their planned line ids, so a person knows what to answer
        self.assertEqual(out["stats"]["calls"], 0)  # nothing was written, so no call is counted

    def test_the_prompt_carries_the_rules_the_plan_and_the_evidence(self):  # the prompt holds the rules, the plan and the evidence
        out, m = self.run_draft({"cover-draft": self.body()})  # a clean run, only the prompt matters here
        prompt = m.calls[0][1]  # the draft request
        # pieces that must be in the prompt: the number rule, the gap tool, a paragraph header, a posting line, an evidence block id, a banned word, the names field, and the role with the company
        for needle in ("Write no numbers at all", "Rust", "p3 (duties)", "d3. Run the Kubernetes deployment pipeline", "[alpha-2#3]",
                       "passionate", "\"names\"", "Backend Platform Engineer at Orion Payments"):
            self.assertIn(needle, prompt)
        self.assertNotIn("{{", prompt)  # every placeholder was filled

    def test_a_korean_letter_prompt_asks_for_korean(self):  # a Korean plan asks the model to write Korean and signs with the Korean name
        plan = json.loads((EX / "plan_ko.json").read_text(encoding="utf-8"))  # the reviewed Korean plan
        good = json.loads((EX / "cover_ko.json").read_text(encoding="utf-8"))  # the reviewed Korean letter
        with model({"cover-draft": {"paragraphs": [{"id": p["id"], "sentences": p["sentences"]} for p in good["paragraphs"]]}}) as m:  # the stand-in answers with the sentences of the good Korean letter
            out = C.draft(PROFILE, plan, style=self.style)  # the style pack has Korean tone and limits too
        self.assertIn("in Korean", m.calls[0][1])  # the prompt names the letter language
        self.assertEqual(out["unresolved"], [])  # no sentence was rejected or left open
        self.assertEqual(out["signature"], "홍길동")  # the Korean name is used as written


class CheckTests(unittest.TestCase):  # check_cover: every category passes on the examples and can be made to fail
    def check(self, lang, **kw):  # runs check_cover on one example letter
        cover = json.loads((EX / f"cover_{lang}.json").read_text(encoding="utf-8"))  # the reviewed letter of that language
        return C.check_cover(PROFILE, cover, style_spec=str(EX / "style.json"), **kw), cover  # the example style pack, as at drafting time

    def status(self, res):  # check key to status, so a test reads one check at a time
        return {c["key"]: c["status"] for c in res["checks"]}  # the order of the checks does not matter to the tests

    def test_both_example_letters_pass(self):  # both example letters pass every check that can run
        for lang in ("ko", "en"):  # one letter per language
            res, _ = self.check(lang)  # no PDF and no extra options
            self.assertTrue(res["ok"], res)  # ok means no check failed; the result is the failure message
            # no PDF is given, so page and layout are skipped and the other eight pass (claim strength included)
            self.assertEqual(self.status(res), {"evidence": "pass", "facts": "pass", "repeat": "pass", "duties": "pass", "gaps": "pass",
                                                "claims": "pass", "style": "pass", "length": "pass", "page": "skip", "layout": "skip"})

    def test_a_skipped_check_is_not_a_pass(self):  # a check that did not run is shown as skipped, never as passed
        out = io.StringIO()  # capture the printed report
        res, _ = self.check("en")  # English example letter
        C.print_check(res, out)  # writes into the buffer instead of the screen
        self.assertIn("[skip] one page: no PDF given", out.getvalue())  # the skipped check is named, with the reason
        self.assertTrue(out.getvalue().strip().endswith("cover check: PASS (8 passed, 2 not run)"))  # the verdict line counts eight passes (claim strength included) and two checks that did not run

    def test_every_category_can_fail(self):  # each check category can be made to fail
        cover = json.loads((EX / "cover_en.json").read_text(encoding="utf-8"))  # a fresh copy of the example letter to break
        cover["paragraphs"][2]["sentences"][0]["text"] = "I moved approval out of the application in three steps with Rust."  # number, tool
        cover["paragraphs"][2]["sentences"][1]["ev"] = ["nope"]  # id
        cover["paragraphs"][3]["sentences"][0]["text"] = "This is passionate work."  # style word
        cover["paragraphs"] = [cover["paragraphs"][0]] + cover["paragraphs"][3:5] + [cover["paragraphs"][2]] + cover["paragraphs"][5:]  # order
        res = C.check_cover(PROFILE, cover, style_spec=str(EX / "style.json"))  # no plan argument: the plan inside the letter is used
        st = self.status(res)  # status per check key
        self.assertFalse(res["ok"])  # one failing check fails the whole result
        for key in ("evidence", "facts", "duties", "gaps", "style"):  # the five categories that were broken above
            self.assertEqual(st[key], "fail", key)  # the key is the failure message

    def test_a_changed_profile_makes_the_plan_stale(self):  # an edited profile makes the saved plan stale, which fails the evidence check
        other = copy.deepcopy(PROFILE)  # profile copy that differs from what the plan saw
        other["roles"][0]["projects"][0]["points"][1] = "멱등 키를 쓰지 않았다"  # change one bullet that the plan cites
        cover = json.loads((EX / "cover_en.json").read_text(encoding="utf-8"))  # the reviewed letter with its plan inside
        res = C.check_cover(other, cover, style_spec=str(EX / "style.json"))  # check against the changed profile
        self.assertEqual(self.status(res)["evidence"], "fail")  # stale evidence is reported under the evidence check
        self.assertIn("changed or vanished", C.issue_text(res["checks"][0]["items"][0]["issues"][0]))  # the stale message is the first item of that check

    def test_a_hand_written_letter_without_a_plan_still_gets_the_sentence_checks(self):  # a letter written by hand, with no plan, still gets the sentence checks
        # no plan inside: only the job, and one sentence that cites a real block
        cover = {"lang": "ko", "job": {"company": "델타페이", "role": "x"}, "paragraphs": [{"id": "p1", "kind": "duties", "sentences": [
            {"text": "알파페이에서 승인 경로를 나누었습니다.", "ev": ["alpha-1#1"]}]}]}
        res = C.check_cover(PROFILE, cover)  # no plan, no PDF, no style name
        self.assertEqual(self.status(res)["duties"], "skip")  # duty coverage cannot run without a plan
        self.assertTrue(res["ok"])  # a skipped check is not a failure

    def test_messages_follow_the_language_setting(self):  # messages follow the OFFEROWL_LANG setting
        saved = os.environ.get("OFFEROWL_LANG")  # keep the caller's value so it can be restored
        os.environ["OFFEROWL_LANG"] = "ko"  # the switch that the panel sets
        try:  # the Korean switch stays on only for this block
            out = io.StringIO()  # capture the printed report
            res, _ = self.check("ko")  # the Korean example letter
            C.print_check(res, out)  # writes into the buffer instead of the screen
            self.assertIn("자기소개서 검사: 통과", out.getvalue())  # the verdict line is in Korean
        finally:  # other tests expect the default language back, even after a failure
            if saved is None:  # the variable was not set before this test
                os.environ.pop("OFFEROWL_LANG")  # remove it again instead of leaving an empty value
            else:  # the variable had a value before the test, so that value must come back
                os.environ["OFFEROWL_LANG"] = saved  # put the original value back


class CommandLineTests(unittest.TestCase):  # the command line entry points, run in-process with a stand-in model
    def run_cli(self, *args):  # runs main() with the given arguments and captures what it prints
        out = io.StringIO()  # the commands print their summary to stdout
        with contextlib.redirect_stdout(out):  # keeps the test output clean and lets tests read the summary
            rc = C.main(list(args))  # main returns its exit code instead of exiting
        return rc, out.getvalue()  # tests assert on both the code and the text

    def test_plan_draft_check_with_a_stand_in_model(self):  # plan, draft and check work end to end on the example files with no real model
        good = json.loads((EX / "cover_en.json").read_text(encoding="utf-8"))  # the reviewed English letter
        body = {"paragraphs": [{"id": p["id"], "sentences": p["sentences"]} for p in good["paragraphs"]]}  # its sentences in the shape that the model answers with
        with tempfile.TemporaryDirectory() as d, model({"cover-draft": body}):  # output goes to a scratch folder; the stand-in answers the draft call
            prof, post = str(ROOT / "examples" / "sample_ko.json"), str(EX / "posting_en.md")  # the example profile and the English posting
            rc, out = self.run_cli("plan", prof, post, "--backend", "none", "-o", f"{d}/plan.json", "--style", str(EX / "style.json"))  # a word-matched plan, written to the scratch folder
            self.assertEqual(rc, 0, out)  # exit 0 is success, and the output is the failure message
            self.assertIn("plan: 15 lines (6 duties, 5 requirements, 4 preferred)", out)  # the summary line counts the posting lines by kind
            self.assertIn("Rust", out)  # the gap tool is reported to the user
            # the word-matched plan groups differently from the reviewed one, so draft from the reviewed plan
            rc, out = self.run_cli("draft", prof, str(EX / "plan_en.json"), "-o", f"{d}/cover.json", "--style", str(EX / "style.json"))  # draft from the reviewed plan
            self.assertEqual(rc, 0, out)  # exit 0: nothing was left open
            self.assertIn("16 sentences kept, 0 dropped", out)  # every sentence of the model's answer passed the fact check
            rc, out = self.run_cli("check", prof, f"{d}/cover.json", "--json", f"{d}/check.json")  # check the file that draft wrote, and save the result as JSON
            self.assertEqual(rc, 0, out)  # exit 0: every check that can run passed
            self.assertTrue(json.loads(pathlib.Path(f"{d}/check.json").read_text(encoding="utf-8"))["ok"])  # the saved result agrees with the exit code

    def test_draft_without_a_model_exits_with_2_and_writes_the_skeleton(self):  # draft without a model exits with 2 and still writes the skeleton
        with tempfile.TemporaryDirectory() as d, model({}):  # an empty table: the model is unavailable
            rc, out = self.run_cli("draft", str(ROOT / "examples" / "sample_ko.json"), str(EX / "plan_ko.json"), "-o", f"{d}/cover.json")  # the Korean example plan
            self.assertEqual(rc, 2)  # 2 is the code for "no model answered"
            self.assertIn("empty skeleton", out)  # the message says an empty skeleton was written
            self.assertTrue(json.loads(pathlib.Path(f"{d}/cover.json").read_text(encoding="utf-8"))["why_empty"])  # and the file records why it is empty


class ExampleFileTests(unittest.TestCase):  # the files in examples/cover must stay consistent with the code
    def test_example_files_are_consistent(self):  # plan and letter examples agree with each other and with the schema names
        for lang in ("ko", "en"):  # both languages
            plan = json.loads((EX / f"plan_{lang}.json").read_text(encoding="utf-8"))  # the reviewed plan
            cover = json.loads((EX / f"cover_{lang}.json").read_text(encoding="utf-8"))  # the reviewed letter
            self.assertEqual(plan["schema"], C.SCHEMA_PLAN)  # the schema name is the one that the code writes
            self.assertEqual(cover["schema"], C.SCHEMA_COVER)  # same for the letter
            self.assertEqual(cover["plan"], plan)  # the letter carries the plan it answers
            self.assertEqual(plan["lang"], lang)  # each file is in its own language
            answered = {d for p in cover["paragraphs"] for s in p["sentences"] for d in s["duties"]}  # the lines that the letter's sentences tag as answered
            self.assertEqual(answered, {l["id"] for l in plan["lines"] if l["use"]})  # exactly the lines that the plan marks as used

    def test_the_example_style_pack_loads_with_its_cover_options(self):  # the example style pack loads together with its cover options
        st = C.load_style(str(EX / "style.json"))  # the pack is loaded by path
        self.assertEqual(st["cover"]["numbers"], "forbid")  # the pack forbids numbers
        self.assertIn("synergy", st["cover"]["banned_words"])  # a banned word of the pack
        self.assertEqual(st["cover"]["repeat_run"]["en"], 14)  # defaults fill what the pack leaves out

    def test_a_style_path_stored_relative_to_the_repository_is_found_from_any_folder(self):
        here = os.getcwd()
        with tempfile.TemporaryDirectory() as d:  # a plan made in one folder is drafted from another
            os.chdir(d)
            try:
                self.assertEqual(C.load_style("examples/cover/style.json")["cover"]["numbers"], "forbid")
            finally:
                os.chdir(here)

    def test_a_missing_style_pack_stops_instead_of_switching_the_rules_off(self):  # a style pack name with no file stops the run instead of switching the rules off
        with self.assertRaises(SystemExit):  # a typo must not silently mean no rules
            C.load_style("no-such-pack")  # a name with no file behind it


@unittest.skipUnless(os.environ.get("OFFEROWL_RENDER_TESTS") == "1", "set OFFEROWL_RENDER_TESTS=1 (needs Docker; renders two letters)")  # opt-in, because rendering needs Docker
class RenderTests(unittest.TestCase):  # build() renders real files in the container
    def test_both_example_letters_render_on_one_page_and_pass_the_full_check(self):  # both examples render to one page and pass the full check, layout included
        for lang in ("ko", "en"):  # both languages
            with tempfile.TemporaryDirectory() as d:  # the rendered copies go to a scratch folder
                info = C.build(ROOT / "examples" / "sample_ko.json", EX / f"cover_{lang}.json", EX / f"job_{lang}.json", dest=d)  # DOCX and PDF come from the container
                self.assertEqual(info["pages"], 1)  # the letter fits one page
                self.assertTrue(pathlib.Path(info["docx"]).stat().st_size > 5000)  # the DOCX is a real file, not an empty stub
                cover = json.loads((EX / f"cover_{lang}.json").read_text(encoding="utf-8"))  # the letter that was rendered
                res = C.check_cover(PROFILE, cover, pdf=info["pdf"], style_spec=str(EX / "style.json"))  # check again, now with the PDF so that page and layout run
                self.assertTrue(res["ok"], res)  # the page and layout checks pass as well
                self.assertEqual({c["key"]: c["status"] for c in res["checks"]}["page"], "pass")  # the page count check ran and passed
                text = C.subprocess.run(["pdftotext", info["pdf"], "-"], capture_output=True, text=True).stdout  # read the printed text back from the PDF
                first = cover["paragraphs"][1]["sentences"][0]["text"].split()[0]  # the first word of the second paragraph
                self.assertIn(first, text)  # the paragraph really reached the page
                self.assertIn("Gildong" if lang == "en" else "홍길동", text)  # the signature is printed in the language's script


if __name__ == "__main__":  # lets the file run directly as well as through discover
    unittest.main()  # same runner as the discover command
