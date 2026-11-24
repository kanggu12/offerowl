# -*- coding: utf-8 -*-
"""The depth review (src/depth_review.py) with a stand-in model, on the fictional ledger of fixtures/ledger_ko.json.

One item is written as a draft writes it (its ledger kept under "ledger"), one by hand beside a ledger of the same company
(a resume kept by hand, with its company's projects off the resume), and a deck of three fictional pages. The stand-in is a
plain function with the model's signature; no real model and no container."""
import copy  # profiles are copied before a test changes them
import io  # the command line's words, caught
import os  # the language of messages
from unittest import mock  # one test's environment
import json  # every file is JSON
import pathlib  # paths
import subprocess  # the command line
import sys  # the import path
import tempfile  # scratch folders
import unittest  # the test runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
HERE = pathlib.Path(__file__).resolve().parent  # tests/write
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
sys.path.insert(0, str(ROOT))  # apps/, for the canvas's own sentence cut
import depth_review as D  # noqa: E402
import factcheck as F  # noqa: E402  the circumstance patterns live with the other fact rules
import write_resume as W  # noqa: E402

LEDGER = json.loads((HERE / "fixtures" / "ledger_ko.json").read_text(encoding="utf-8"))  # the fictional ledger


def edition() -> dict:
    """The fictional ledger as an edition prints it: nara-1 drafted, a hand-written item for dasom beside its ledger."""
    p = copy.deepcopy(LEDGER)  # never the fixture itself
    n1 = p["roles"][0]["projects"][0]  # nara-1, drafted as src/write_resume.py writes an item
    n1["ledger"] = {"title": n1["title"], "summary": None}  # what the draft replaced: the ids keep their meaning
    n1["title"] = {"ko": "가상은행 분석 플랫폼 이관", "en": "Gasang Bank analytics platform migration"}  # the drafted title
    n1["summary"] = {"ko": "가상은행 분석 플랫폼 이관 과제. 플랫폼을 혼자 Kubernetes로 이관. ==쿼리 지연 개선==",  # thin on purpose: no difficulty, no mechanism, a circumstance
                     "en": "Took on the Gasang Bank analytics platform. Moved the platform to Kubernetes alone. ==Improved query latency=="}
    for q in p["roles"][0]["projects"][1:]:  # the other nara projects stay in the ledger, off the resume
        q["resume"] = False
    d = p["roles"][1]  # dasom: a resume written by hand beside its ledger
    for q in d["projects"]:  # the ledger projects
        q["resume"] = False  # off the resume: the evidence of the hand-written item
    d["projects"].append({"id": "dasom-ko1", "lang": "ko", "title": "사내 배포 파이프라인", "period": "2020.01 ~ 2022.02",  # the item a person wrote
                          "summary": "사내 배포 파이프라인 운영"})  # routine, and thin
    d["projects"].append({"id": "dasom-en1", "lang": "en", "title": "In-house deployment pipeline", "summary": "Ran the in-house deployment pipeline"})  # the English edition's own
    return p


def stand_in(answers: dict, calls: list | None = None):
    """A model that answers each batch with the findings given per unit id."""
    def ask(task, prompt, required):  # the signature of src/write_resume.py's ask
        if calls is not None:  # the test counts and reads them
            calls.append(prompt)
        ids = [line.split(" | ")[0][4:] for line in prompt.splitlines() if line.startswith("### ")]  # the units of this batch
        return {"units": [{"id": i, **answers[i]} for i in ids if i in answers]}  # only the units it was asked about
    return ask


class Units(unittest.TestCase):
    """What is read, and with which evidence."""

    def test_the_items_the_resume_prints_in_its_language(self):  # off the resume, the other language and titles alone are not read
        ko = [u["id"] for u in D.items_of(edition(), "ko")]
        self.assertEqual(["item:nara-1", "item:dasom-ko1"], ko)  # print order: the roles' order, then the projects'
        en = [u["id"] for u in D.items_of(edition(), "en")]
        self.assertEqual(["item:nara-1", "item:dasom-en1"], en)  # the English edition's own item, not the Korean one

    def test_sentences_are_cut_as_the_canvas_cuts_them(self):  # a rewrite names its sentence by its words: both cuts must agree
        from apps.api.services.profile import evidence  # the canvas's cut
        for text in ("가상은행 분석 플랫폼 이관 과제. 플랫폼을 이관. ==쿼리 지연 개선==", "Moved it. Cut ==latency. by half==. Version 3.5 shipped. Done!",
                     "한 문장", "", "A? B! C."):  # Korean bullets, a stop inside a highlight, a number, one sentence, nothing, every end mark
            self.assertEqual(evidence.sentences(text), D.sentences(text), text)

    def test_a_drafted_item_is_read_with_its_own_ledger_and_its_company(self):  # its ledger blocks and its role's context, nothing of another project
        P = D.Pools(edition(), "ko")
        item = D.items_of(edition(), "ko")[0]  # nara-1
        ids = [i for i, _ in P.pool(item)]  # its evidence
        self.assertEqual(["nara-1#1", "nara-1#2", "nara-1#3", "nara-1#4", "nara-1#5"], [i for i in ids if i.startswith("nara-1#")])  # every ledger block, in order
        self.assertTrue(any(i.startswith("nara#c") for i in ids))  # the company's context
        self.assertFalse(any(i.startswith(("nara-2", "nara-3", "dasom")) for i in ids))  # one item, one project

    def test_an_item_written_by_hand_is_read_with_its_company_s_ledger(self):  # no ledger of its own: the company's projects off the resume, best first
        P = D.Pools(edition(), "ko")
        item = D.items_of(edition(), "ko")[1]  # dasom-ko1
        ids = [i for i, _ in P.pool(item)]
        self.assertNotIn("dasom-ko1#1", ids)  # its own printed words are never its own evidence
        self.assertEqual("dasom-1#1", ids[0])  # the ledger block that shares most with it: the pipeline
        self.assertFalse(any(i.startswith("nara") for i in ids))  # another company's ledger is not its evidence

    def test_deck_pages_are_paired_with_their_project(self):  # a page that names a project by its title is read with that project's evidence
        pages = ["Nara Cloud", "결제 데이터 플랫폼 이관 " + "한 서버에 몰린 분석 플랫폼을 옮긴 일의 설명이 이어진다. " * 10, "감사합니다"]  # a cover, a project page, an end page
        units = D.slides_of(pages, "ko")
        self.assertEqual(["slide:2"], [u["id"] for u in units])  # the short pages are no work to weigh
        P = D.Pools(edition(), "ko")
        self.assertEqual("nara-1", P.pair(units[0]))  # its title names the project's ledger title
        self.assertIn("nara-1#2", [i for i, _ in P.pool(units[0])])
        rec = D.review(edition(), "ko", pages=pages, backend="none")  # the record keeps the pairing: an answer about the page goes to its project
        self.assertEqual("nara-1", next(u for u in rec["units"] if u["id"] == "slide:2")["pid"])


class RuleChecks(unittest.TestCase):
    """What the review finds with no agent at all."""

    def test_circumstances_are_found_in_both_languages(self):  # the only developer, alone, a team's size, a join date
        for text in ("팀의 유일한 엔지니어로 서버 운영", "1인 개발로 앱 출시", "플랫폼을 혼자 이관", "5명 팀을 맡아 운영", "입사 직후 배포 체계 구축",
                     "As the sole developer, built the app", "Built it single-handedly", "Led a team of four engineers", "Worked mostly alone on the app"):
            self.assertTrue(F.circumstances(text), text)
        for text in ("홀로그램 화면 개발", "단독 서버를 이관", "a standalone service", "Kubernetes로 이관", "so the team could roll back the approval path alone"):  # words that only look like one
            self.assertEqual([], F.circumstances(text), text)

    def test_without_an_agent_only_the_rules_run_and_say_so(self):  # the none backend: no call, the rule findings, the notes
        rec = D.review(edition(), "ko", backend="none")
        self.assertFalse(rec["agent"])
        self.assertEqual(0, rec["calls"])
        self.assertEqual(["no_agent", "no_deck", "no_baseline"], rec["notes"])
        nara = rec["units"][0]
        self.assertEqual(["depth_circumstance"], [f["code"] for f in nara["findings"]])  # "혼자": the work belongs there
        f = nara["findings"][0]
        self.assertEqual(("ask", "rule", "혼자"), (f["way"], f["by"], f["quote"]))
        self.assertIn("혼자", f["question"])  # the question quotes it, in the edition's language

    def test_an_item_thinner_than_the_copy_that_went_out(self):  # names the copy that went out printed and the item lost
        old = edition()  # the copy that went out named its tools
        old["roles"][0]["projects"][0]["summary"]["ko"] = "가상은행 분석 플랫폼을 Kubernetes로 이관. Prometheus 지표로 ==쿼리 지연 확인=="
        now = edition()
        now["roles"][0]["projects"][0]["summary"]["ko"] = "가상은행 분석 플랫폼 이관. ==쿼리 지연 개선=="  # both names gone
        rec = D.review(now, "ko", backend="none", old=old)
        f = next(f for f in rec["units"][0]["findings"] if f["code"] == "depth_thinner")
        self.assertEqual(["kubernetes", "prometheus"], f["lost"])  # in the order the old words name them
        self.assertIn("Prometheus", f["went_out"])  # the words that went out, for the person to compare
        self.assertNotIn("no_baseline", rec["notes"])
        self.assertEqual([], D.lost_names("Blue-green 배포", "Blue\u2011green 배포"))  # a non-breaking hyphen writes the same name
        same = D.review(old, "ko", backend="none", old=old)  # the same words as went out: nothing lost
        self.assertFalse([f for u in same["units"] for f in u["findings"] if f["code"] == "depth_thinner"])


class AgentPart(unittest.TestCase):
    """What the agent finds, and how its rewrites are held to the draft's checks."""

    def review(self, answers, **kw):
        """A review with the stand-in, and the prompts it was sent."""
        calls = []  # the prompts
        return D.review(edition(), "ko", ask=stand_in(answers, calls), **kw), calls

    def test_a_rewrite_that_rests_on_its_evidence_is_offered(self):  # the evidence holds what is missing, and the words pass
        rec, calls = self.review({"item:nara-1": {"findings": [
            {"code": "hard", "missing": "무엇이 어려웠는지 없다", "way": "rewrite", "replaces": "가상은행 분석 플랫폼 이관 과제.",
             "text": "한 서버에 몰려 있던 가상은행 분석 플랫폼의 이관 과제", "ev": ["nara-1#1"]},
            {"code": "mechanism", "missing": "왜 빨라졌는지 없다", "way": "ask", "question": "무엇이 지연을 줄였나요?"}]}})
        self.assertEqual(1, rec["calls"])
        f = rec["units"][0]["findings"]
        self.assertEqual(["depth_hard", "depth_mechanism", "depth_circumstance"], [x["code"] for x in f])  # the agent's, then the rule's, in the reader's order
        hard = f[0]
        self.assertEqual("rewrite", hard["way"])
        self.assertEqual({"replaces": "가상은행 분석 플랫폼 이관 과제.", "text": "한 서버에 몰려 있던 가상은행 분석 플랫폼의 이관 과제", "ev": ["nara-1#1"], "names": {}},
                         hard["rewrite"])  # the printed sentence as the canvas has it, the new words and what they rest on
        self.assertEqual(("ask", "무엇이 지연을 줄였나요?"), (f[1]["way"], f[1]["question"]))
        self.assertEqual(1, rec["counts"]["rewrites"])

    def test_a_rewrite_the_evidence_does_not_hold_becomes_a_question(self):  # a name, a stronger claim, a block it was not shown, a sentence not printed
        rec, _ = self.review({"item:nara-1": {"findings": [
            {"code": "names", "missing": "x", "way": "rewrite", "replaces": "", "text": "AWS EKS로 이관", "ev": ["nara-1#2"]},  # a name the block lacks
            {"code": "decision", "missing": "x", "way": "rewrite", "replaces": "", "text": "Kubernetes 이관 설계를 주도", "ev": ["nara-1#2"]},  # 'led' where it says 'proposed'
            {"code": "scope", "missing": "x", "way": "rewrite", "replaces": "", "text": "온콜 로테이션 정립", "ev": ["nara-2#1"]},  # another project's block
            {"code": "routine", "missing": "x", "way": "rewrite", "replaces": "없는 문장", "text": "쿼리 지연을 Prometheus 지표로 확인", "ev": ["nara-1#4"]}]}})  # a sentence it does not print
        by = {f["code"]: f for f in rec["units"][0]["findings"]}
        self.assertEqual(["name"], by["depth_names"]["rejected"])
        self.assertEqual(["claim"], by["depth_decision"]["rejected"])
        self.assertEqual(["no_ev"], by["depth_scope"]["rejected"])
        self.assertEqual(["replaces"], by["depth_routine"]["rejected"])
        for f in by.values():  # each became the person's question, never words to print
            self.assertEqual("ask", f["way"])
            self.assertNotIn("rewrite", f)
            self.assertTrue(f["question"])

    def test_codes_ways_and_pages(self):  # an unknown code, a second finding of one code, a page set aside, a unit left out
        pages = ["결제 데이터 플랫폼 이관 " + "분석 플랫폼 이관의 설명. " * 20, "목차 " + "차례 " * 90]  # a project page and a contents page
        rec = D.review(edition(), "ko", pages=pages, ask=stand_in({
            "item:nara-1": {"findings": [{"code": "nonsense", "way": "ask"}, {"code": "depth_hard", "missing": "a", "way": "ask"}, {"code": "hard", "missing": "b", "way": "ask"}]},
            "slide:1": {"findings": [{"code": "mechanism", "missing": "왜 됐는지", "way": "ask", "question": "왜?"}]},
            "slide:2": {"skip": True, "findings": [{"code": "hard", "way": "ask"}]}}))
        nara = rec["units"][0]
        self.assertEqual(["depth_hard", "depth_circumstance"], [f["code"] for f in nara["findings"]])  # one per code, the first kept
        self.assertEqual("a", nara["findings"][0]["missing"])
        ids = [u["id"] for u in rec["units"]]
        self.assertIn("slide:1", ids)
        self.assertNotIn("slide:2", ids)  # the contents page is no piece of work
        self.assertEqual(1, rec["counts"]["unreviewed"])  # dasom-ko1 was never answered
        self.assertIn("unreviewed:1", rec["notes"])
        self.assertFalse(next(u for u in rec["units"] if u["id"] == "item:dasom-ko1")["reviewed"])

    def test_a_finding_without_its_words_still_gets_its_question(self):  # the agent's circumstance finding came with no question and no quote
        rec, _ = self.review({"item:nara-1": {"findings": [{"code": "circumstance", "way": "ask"}, {"code": "thinner", "way": "ask"}, {"code": "hard", "way": "rewrite", "ev": 7}]},
                              "item:dasom-ko1": {"findings": "not a list"}})  # and a unit answered in another shape
        by = {f["code"]: f for f in rec["units"][0]["findings"]}
        self.assertIn("혼자", by["depth_circumstance"]["question"])  # its own question, quoting the words that hold it
        plain = edition()
        plain["roles"][0]["projects"][0]["summary"]["ko"] = "가상은행 분석 플랫폼 이관 과제. ==쿼리 지연 개선=="  # no circumstance in its words
        again = D.review(plain, "ko", ask=stand_in({"item:nara-1": {"findings": [{"code": "circumstance", "way": "ask"}]}}))
        self.assertNotIn("('')", again["units"][0]["findings"][0]["question"])  # nothing to quote: no empty quote
        self.assertTrue(by["depth_thinner"]["question"])  # a placeholder with no value is left empty, never an error
        self.assertEqual("ask", by["depth_hard"]["way"])  # a rewrite with no words becomes the question
        self.assertEqual([], next(u for u in rec["units"] if u["id"] == "item:dasom-ko1")["findings"])  # nothing usable: no finding

    def test_an_id_without_its_kind_and_a_second_try_of_one_code(self):  # a model wrote "nara-1" for "item:nara-1", and tried one code twice
        def ask(task, prompt, required):
            return {"units": [{"id": "nara-1", "findings": [
                {"code": "hard", "missing": "a", "way": "rewrite", "replaces": "", "text": "AWS로 이관", "ev": ["nara-1#2"]},  # fails: a name the block lacks
                {"code": "hard", "missing": "b", "way": "rewrite", "replaces": "", "text": "한 서버에 몰려 있던 분석 플랫폼의 이관", "ev": ["nara-1#1"]},  # passes
                {"code": "hard", "missing": "c", "way": "ask", "question": "?"}]}]}  # a third of the code: the passing one stays
        rec = D.review(edition(), "ko", ask=ask)
        nara = next(u for u in rec["units"] if u["id"] == "item:nara-1")
        self.assertTrue(nara["reviewed"])  # read, though its id came without its kind
        hard = [f for f in nara["findings"] if f["code"] == "depth_hard"]
        self.assertEqual(1, len(hard))  # one per code
        self.assertEqual(("rewrite", "b"), (hard[0]["way"], hard[0]["missing"]))  # the try that passed the checks

    def test_an_id_written_with_its_whole_head_line(self):  # a model copied "### item:nara-1 | title | place" as the id: the unit is the same
        def ask(task, prompt, required):
            head = next(line for line in prompt.splitlines() if line.startswith("### item:nara-1 | "))  # the unit's head line, as the prompt wrote it
            return {"units": [{"id": head[4:], "stated": {"hard": "", "decision": "", "mechanism": ""}, "findings": []},  # without the marks
                              {"id": "### item:dasom-ko1 | 사내 배포 파이프라인 | x", "findings": []}]}  # with them
        rec = D.review(edition(), "ko", ask=ask)
        self.assertEqual(0, rec["counts"]["unreviewed"])  # both read
        self.assertEqual("thin", next(u for u in rec["units"] if u["id"] == "item:nara-1")["verdict"])

    def test_the_call_limit_and_the_count_before(self):  # a review makes as many calls as counted, and never more than allowed
        pages = [f"결제 데이터 플랫폼 이관 {n} " + "분석 플랫폼을 옮긴 일의 설명이 이어진다. " * 40 for n in range(40)]  # forty long pages
        need = D.calls_needed(edition(), "ko", pages)
        self.assertGreater(need, 1)  # more than one batch
        rec, calls = self.review({}, pages=pages)
        self.assertEqual(need, rec["calls"])
        self.assertEqual(need, len(calls))
        rec, calls = self.review({}, pages=pages, max_calls=1)
        self.assertEqual((1, 1), (rec["calls"], len(calls)))  # the limit holds
        self.assertGreater(rec["counts"]["unreviewed"], 0)  # and the review says what it did not read

    def test_a_left_finding_stays_left_on_the_same_words(self):  # the person's decision is kept until the words change
        first, _ = self.review({"item:nara-1": {"findings": [{"code": "hard", "missing": "a", "way": "ask"}]}})
        f = first["units"][0]["findings"][0]
        f["state"] = "left"  # the person left it
        again, _ = self.review({"item:nara-1": {"findings": [{"code": "hard", "missing": "a", "way": "ask"}]}}, earlier=first)
        self.assertEqual("left", again["units"][0]["findings"][0]["state"])
        changed = edition()
        changed["roles"][0]["projects"][0]["summary"]["ko"] = "가상은행 분석 플랫폼 이관 과제. ==쿼리 지연 개선=="  # new words
        rec = D.review(changed, "ko", ask=stand_in({"item:nara-1": {"findings": [{"code": "hard", "missing": "a", "way": "ask"}]}}), earlier=first)
        self.assertEqual("open", rec["units"][0]["findings"][0]["state"])  # asked again

    def test_the_prompt_says_what_to_judge_and_lists_the_evidence(self):  # what the model is told
        _, calls = self.review({})
        p = calls[0]
        self.assertIn("what made solving it hard", p)
        self.assertIn('A starting situation on its own is not it: "scattered metadata", "a slow query" or "a closed network"', p)  # where the work began is no difficulty
        self.assertIn("Never invent a difficulty, a reason, an alternative or a mechanism", p)
        self.assertIn("- 가상은행 분석 플랫폼 이관 과제.", p)  # the printed sentences, one a line
        self.assertIn("[nara-1#1] 가상은행의 분석 플랫폼이 한 서버에 몰려 있었다.", p)  # the evidence with its id
        self.assertIn("Never turn it into led, designed, built or owned", p)  # the draft's shared rules for a rewrite's words
        self.assertNotIn("메모", p)  # a note to the ledger's owner never reaches a prompt


STRONG_KO = ("분석 쿼리가 한 서버에 몰려 야간 배치가 아침까지 밀렸다. 서버를 늘리는 대신 배치를 노드마다 나눠 돌리도록 Kubernetes로 옮겼다. "
             "배치가 노드마다 따로 돌자 ==쿼리 지연이 절반으로 줄었다==.")  # a fictional item that states all three parts: what was hard, the choice over another way, why it worked


class Verdicts(unittest.TestCase):
    """Strong, adequate or thin: the rule, the quotes it rests on, the findings it keeps, and the order it lists units in."""

    def test_the_rule_counts_the_parts_the_words_state(self):  # all three strong, one missing adequate, two or three thin
        self.assertEqual("strong", D.verdict_of({"hard": "a", "decision": "b", "mechanism": "c"}))
        self.assertEqual("adequate", D.verdict_of({"hard": "a", "decision": "", "mechanism": "c"}))
        self.assertEqual("thin", D.verdict_of({"hard": "a", "decision": "", "mechanism": ""}))
        self.assertEqual("thin", D.verdict_of({"hard": "", "decision": "", "mechanism": ""}))
        self.assertEqual("thin", D.verdict_of({}))  # nothing stated is nothing said

    def test_a_quote_counts_only_when_the_words_hold_it(self):  # copied with its marks dropped, its spaces moved, a skip: found; a paraphrase: not
        words = "서버를 늘리는 대신 배치를 노드마다 나눠 돌리도록 Kubernetes로 옮겼다. ==쿼리 지연이 절반으로 줄었다==. Blue\u2011green 배포"
        self.assertTrue(D.said_in("서버를 늘리는 대신 배치를 노드마다 나눠", words))
        self.assertTrue(D.said_in("쿼리 지연이 절반으로 줄었다.", words))  # the highlight marks and the end mark are no words
        self.assertTrue(D.said_in("\u201c서버를 늘리는 대신\u201d", words))  # curly quotation marks around it
        self.assertTrue(D.said_in("Blue-green 배포", words))  # a plain hyphen for a typeset one
        self.assertTrue(D.said_in("배치를노드마다 나눠돌리도록", words))  # Korean spacing moved as it was copied
        self.assertTrue(D.said_in("서버를 늘리는 대신 ... Kubernetes로 옮겼다", words))  # a skip between two pieces the words hold
        self.assertFalse(D.said_in("서버를 늘리는 대신 ... 캐시를 붙였다", words))  # one piece they do not hold
        self.assertFalse(D.said_in("노드를 늘려 지연을 줄였다", words))  # a paraphrase states nothing
        self.assertFalse(D.said_in("대신", words))  # a word or two points at nothing
        self.assertFalse(D.said_in("", words))

    def test_a_starting_situation_names_only_where_the_work_began(self):  # a setting, the equipment, the material or a state, said with no difficulty
        for quote in ("여러 팀 폴더에 흩어진 실험 기록과 산출물", "느린 분석 쿼리", "폐쇄망", "폐쇄망 환경의 분석 플랫폼", "인터넷이 막힌 사내 환경", "제조사가 다른 스토리지 장비",
                      "한 서버에 몰려 있던 분석 플랫폼", "수작업 중심의 배포 운영", "Scattered metadata and artifacts", "a slow query", "a closed network",
                      "the legacy monolith", "an air-gapped data center"):
            self.assertTrue(D.is_situation(quote), quote)
        for quote in ("외부 저장소를 쓸 수 없는 폐쇄망", "배포가 승인 경로를 멈추던 구조", "승인 요청이 몰리면 배포가 멈췄다", "재기동에 사흘이 걸렸다",  # a word of how it was hard
                      "정확도와 지연을 동시에 맞춰야 했다", "첫 시도의 적중률이 기대에 못 미쳤다", "서비스를 멈추지 않고 옮겨야 했다",
                      "a closed network where packages could not be installed", "Deploys stopped whenever approvals piled up", "The restart took three days",
                      "야간 백업이 끝나기 전에 집계 작업이 시작되던 순서", "두 작업이 같은 행을 고치던 경합", "옛 값을 내주던 캐시 키", "a race between two writers"):  # an event or a problem: the agent's judgment
            self.assertFalse(D.is_situation(quote), quote)
        self.assertTrue(D.shows_difficulty("폐쇄망이라서 패키지를 받지 못했다"))  # the words of how it was hard, in both languages
        self.assertTrue(D.shows_difficulty("could not reach the package mirror"))
        self.assertFalse(D.shows_difficulty("100밀리초 응답"))  # milliseconds are no delay
        self.assertFalse(D.shows_difficulty("took over the platform"))  # taking over is no cost of time

    def test_a_starting_situation_is_no_difficulty(self):  # found in the words, but it only says where the work began
        p = edition()
        p["roles"][0]["projects"][0]["summary"]["ko"] = "분석 쿼리가 느린 플랫폼. 서버를 늘리는 대신 배치를 노드마다 나눠 돌리도록 Kubernetes로 옮김. 배치가 노드마다 따로 돌자 ==쿼리 지연이 줄었다=="
        rec = D.review(p, "ko", ask=stand_in({"item:nara-1": {"stated": {"hard": "분석 쿼리가 느린 플랫폼", "decision": "서버를 늘리는 대신 배치를 노드마다 나눠",
                                                                            "mechanism": "배치가 노드마다 따로 돌자"}, "findings": []}}))
        nara = next(u for u in rec["units"] if u["id"] == "item:nara-1")
        self.assertEqual(("adequate", ["hard"]), (nara["verdict"], nara["missing"]))  # a slow query is where it began, not what made it hard
        self.assertEqual(({"hard": "분석 쿼리가 느린 플랫폼"}, {"hard": "situation"}), (nara["refused"], nara["refused_why"]))  # said, and why it did not count
        self.assertEqual(["depth_hard"], [f["code"] for f in nara["findings"]])  # the person is asked what made it hard

    def test_a_strong_unit_keeps_only_names_and_routine(self):  # the agent gave a finding of every kind; a strong unit keeps the ones that matter
        p = edition()
        p["roles"][0]["projects"][0]["summary"]["ko"] = STRONG_KO
        rec = D.review(p, "ko", ask=stand_in({"item:nara-1": {
            "stated": {"hard": "분석 쿼리가 한 서버에 몰려 야간 배치가 아침까지 밀렸다", "decision": "서버를 늘리는 대신 배치를 노드마다 나눠 돌리도록",
                       "mechanism": "배치가 노드마다 따로 돌자 쿼리 지연이 절반으로 줄었다"},
            "findings": [{"code": "hard", "missing": "a", "way": "ask"}, {"code": "scope", "missing": "b", "way": "ask"},
                         {"code": "names", "missing": "가상은행이라는 고객 이름이 없다", "way": "ask", "question": "어느 고객의 플랫폼이었나요?"}]}}))
        nara = next(u for u in rec["units"] if u["id"] == "item:nara-1")
        self.assertEqual(("strong", [], False), (nara["verdict"], nara["missing"], nara["gate"]))
        self.assertEqual(["depth_names"], [f["code"] for f in nara["findings"]])  # the agent's hard and scope go: the words say what was hard
        self.assertEqual(("strong", False), (nara["findings"][0]["verdict"], nara["findings"][0]["gate"]))  # a strong unit's note is a suggestion
        self.assertEqual("서버를 늘리는 대신 배치를 노드마다 나눠 돌리도록", nara["stated"]["decision"])  # the words each part rests on

    def test_a_thin_unit_has_a_finding_for_each_missing_part_and_is_the_gate(self):  # one part found, one quote the words do not hold, one part missing
        rec = D.review(edition(), "ko", ask=stand_in({"item:nara-1": {
            "stated": {"hard": "", "decision": "플랫폼을 혼자 Kubernetes로 이관", "mechanism": "캐시로 쿼리 지연을 줄였다"},  # the last is not in its words
            "findings": [{"code": "hard", "missing": "무엇이 어려웠는지 없다", "way": "ask", "question": "무엇이 어려웠나요?"},
                         {"code": "decision", "missing": "x", "way": "ask"}]}}))  # a finding on a part the words state
        nara = next(u for u in rec["units"] if u["id"] == "item:nara-1")
        self.assertEqual(("thin", ["hard", "mechanism"], True), (nara["verdict"], nara["missing"], nara["gate"]))
        self.assertEqual(({"mechanism": "캐시로 쿼리 지연을 줄였다"}, {"mechanism": "not_in_words"}), (nara["refused"], nara["refused_why"]))  # why a part the agent called stated counts as missing
        by = {f["code"]: f for f in nara["findings"]}
        self.assertEqual(["depth_hard", "depth_mechanism", "depth_circumstance"], [f["code"] for f in nara["findings"]])  # no decision: its words state it
        self.assertEqual("무엇이 어려웠나요?", by["depth_hard"]["question"])  # the agent's own question
        self.assertEqual(("ask", D.t("q_mechanism", "ko")), (by["depth_mechanism"]["way"], by["depth_mechanism"]["question"]))  # the agent gave none: the part's own
        self.assertEqual((True, True, False), (by["depth_hard"]["gate"], by["depth_mechanism"]["gate"], by["depth_circumstance"]["gate"]))  # the missing parts are the gate; the rest suggestions
        self.assertTrue(all(f["verdict"] == "thin" for f in nara["findings"]))
        self.assertEqual((1, 1), (rec["counts"]["thin"], rec["counts"]["gates"]))
        self.assertTrue(D.gate_open(nara))
        for f in nara["findings"]:  # each missing part answered or left: the gate is passed
            f["state"] = "answered" if f["code"] == "depth_hard" else "left"
        self.assertFalse(D.gate_open(nara))

    def test_thin_units_come_first_then_adequate_then_no_verdict_then_strong(self):  # the list is what to fill first, not the print order
        p = edition()
        p["roles"][0]["projects"][0]["summary"]["ko"] = STRONG_KO  # nara-1 strong, printed first
        p["roles"][1]["projects"].append({"id": "dasom-ko2", "lang": "ko", "title": "배포 승인 경로 분리", "summary": "승인 요청이 몰리면 배포가 멈췄다. 승인 경로만 따로 배포했다."})
        p["roles"][1]["projects"].append({"id": "dasom-ko3", "lang": "ko", "title": "장애 대응 문서", "summary": "장애 유형별 대응 절차를 문서로 만들었다."})
        rec = D.review(p, "ko", ask=stand_in({
            "item:nara-1": {"stated": {"hard": "야간 배치가 아침까지 밀렸다", "decision": "서버를 늘리는 대신", "mechanism": "배치가 노드마다 따로 돌자"}, "findings": []},
            "item:dasom-ko1": {"stated": {"hard": "", "decision": "", "mechanism": ""}, "findings": []},  # thin, all three missing
            "item:dasom-ko2": {"stated": {"hard": "승인 요청이 몰리면 배포가 멈췄다", "decision": "승인 경로만 따로 배포했다", "mechanism": ""}, "findings": []},  # adequate
            "item:dasom-ko3": {"findings": [{"code": "routine", "missing": "문서 작성은 일상 업무다", "way": "ask"}]}}))  # an answer with no rating
        self.assertEqual(["item:dasom-ko1", "item:dasom-ko2", "item:dasom-ko3", "item:nara-1"], [u["id"] for u in rec["units"]])
        self.assertEqual(["thin", "adequate", None, "strong"], [u["verdict"] for u in rec["units"]])
        self.assertEqual([1, 2, 3, 0], [u["n"] for u in rec["units"]])  # the print order, kept
        self.assertEqual(3, len(rec["units"][0]["findings"]))  # every missing part has a way on, though the agent gave none
        self.assertEqual(["depth_routine"], [f["code"] for f in rec["units"][2]["findings"]])  # no rating: the agent's findings as they came
        self.assertEqual((None, False), (rec["units"][2]["findings"][0]["verdict"], rec["units"][2]["findings"][0]["gate"]))
        c = rec["counts"]
        self.assertEqual((1, 1, 1, 1, 1), (c["thin"], c["adequate"], c["strong"], c["unrated"], c["gates"]))

    def test_with_no_agent_no_unit_has_a_verdict(self):  # the rules alone judge no depth: no verdict, the print order
        rec = D.review(edition(), "ko", backend="none")
        self.assertEqual([None, None], [u["verdict"] for u in rec["units"]])
        self.assertEqual(["item:nara-1", "item:dasom-ko1"], [u["id"] for u in rec["units"]])
        self.assertEqual((0, 0, 0, 2, 0), tuple(rec["counts"][k] for k in ("thin", "adequate", "strong", "unrated", "gates")))

    def test_the_prompt_asks_for_the_words_of_each_part(self):  # the model quotes; the code decides
        _, calls = AgentPart.review(AgentPart(), {})
        p = calls[0]
        self.assertIn('Under "stated", copy for each part the printed words that state it, exactly as printed', p)
        self.assertIn("All three stated: the unit is strong. Give it no findings, except \"names\" or \"routine\" when they matter.", p)
        self.assertIn('"stated": {"hard":', p)  # the shape of the answer


class ReviewFindings(unittest.TestCase):
    """What an independent review of the harness found in the engine, each held here (fictional words only)."""

    def test_a_page_pairs_by_its_title_and_a_page_naming_two_stays_unpaired(self):  # the title area decides, held to more; two alike: no pair
        P = D.Pools(edition(), "ko")
        body = "당번이 받는 알림을 줄인 일의 설명이 이어진다. " * 8  # the page's own words, no title in them
        own = D.slides_of(["02\nNARA CLOUD\nPROJECT 02 / 03\n온콜 체계 수립\n플랫폼 이관 뒤의 " + body], "ko")[0]  # its title names nara-2; its words hold half of nara-1's title
        self.assertEqual("nara-2", P.pair(own))
        both = D.slides_of(["CONTENTS\n온콜 체계 수립 / 모니터링 대시보드 구축 지원\n" + body], "ko")[0]  # a contents page: two titles alike
        self.assertIsNone(P.pair(both))
        rec = D.review(edition(), "ko", pages=["CONTENTS\n온콜 체계 수립 / 모니터링 대시보드 구축 지원\n" + body], backend="none")
        self.assertNotIn("pid", next(u for u in rec["units"] if u["kind"] == "slide"))  # its answers name their project

    def test_an_english_item_loses_names_not_words(self):  # in English every word is Latin: only names count as lost
        self.assertEqual(["kubernetes", "grafana"], D.lost_names("Moved the billing platform to Kubernetes and watched latency in Grafana.",
                                                                 "Moved the billing platform and cut its latency.", "en"))
        old, now = edition(), edition()
        old["roles"][0]["projects"][0]["summary"]["en"] = "Took on the Gasang Bank analytics platform. Moved it to Kubernetes and watched queries in Grafana."
        now["roles"][0]["projects"][0]["summary"]["en"] = "Took on the Gasang Bank analytics platform. Moved it and cut the waiting."
        rec = D.review(now, "en", backend="none", old=old)
        f = next(f for f in rec["units"][0]["findings"] if f["code"] == "depth_thinner")
        self.assertEqual(["kubernetes", "grafana"], f["lost"])  # never "watched" or "queries"

    def test_quote_pieces_keep_their_order_and_a_length(self):  # "A ... B" means A, then B, each long enough to point at words
        words = "서버를 늘리는 대신 배치를 노드마다 나눠 돌리도록 Kubernetes로 옮겼다."
        self.assertTrue(D.said_in("서버를 늘리는 대신 ... Kubernetes로 옮겼다", words))
        self.assertFalse(D.said_in("Kubernetes로 옮겼다 ... 서버를 늘리는 대신", words))  # out of order
        self.assertFalse(D.said_in("서버를 늘리는 대신 ... 노드", words))  # a piece of two letters points at nothing

    def test_one_sentence_never_states_all_three(self):  # the same words or the same sentence for every part: not strong
        p = edition()
        p["roles"][0]["projects"][0]["summary"]["ko"] = "야간 배치가 아침까지 밀리자 서버를 늘리는 대신 배치를 노드마다 나눠 돌려 지연을 줄였다."
        one = {"hard": "야간 배치가 아침까지 밀리자", "decision": "서버를 늘리는 대신 배치를 노드마다 나눠", "mechanism": "나눠 돌려 지연을 줄였다"}
        rec = D.review(p, "ko", ask=stand_in({"item:nara-1": {"stated": one, "findings": []}}))
        nara = next(u for u in rec["units"] if u["id"] == "item:nara-1")
        self.assertEqual(("adequate", ["mechanism"], {"mechanism": "one_sentence"}), (nara["verdict"], nara["missing"], nara["refused_why"]))
        same = {"hard": "야간 배치가 아침까지 밀리자", "decision": "야간 배치가 아침까지 밀리자", "mechanism": ""}
        rec = D.review(p, "ko", ask=stand_in({"item:nara-1": {"stated": same, "findings": []}}))
        nara = next(u for u in rec["units"] if u["id"] == "item:nara-1")
        self.assertEqual(("thin", {"decision": "repeated"}), (nara["verdict"], nara["refused_why"]))  # the same words count once

    def test_the_scale_of_the_work_is_no_circumstance(self):  # an organisation or an audience is the work's size, never the person's
        for text in ("임직원 3,000명 조직의 그룹웨어를 이관", "a 10,000-person organisation", "500만 명이 쓰는 앱", "직원 120명 회사의 ERP", "served 3,000 people"):
            self.assertEqual([], F.circumstances(text), text)
        for text in ("5명 팀을 맡아 운영", "a 4-person team", "Led a team of four engineers", "12명 개발팀을 이끌며"):  # a team's headcount stays one
            self.assertTrue(F.circumstances(text), text)

    def test_unread_units_say_why(self):  # an answer that left units out is not the call limit, nor a stop
        rec, _ = AgentPart.review(AgentPart(), {"item:nara-1": {"findings": []}})  # dasom-ko1 left out of the answer
        self.assertEqual(["no_deck", "no_baseline", "unreviewed:1", "unanswered:1"], rec["notes"])
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"OFFEROWL_LANG": "en"}):
            D.print_review(rec, out)
        self.assertIn("1 units were not read by the agent\n", out.getvalue())
        self.assertIn("its answer left them out", out.getvalue())
        self.assertNotIn("call limit", out.getvalue())
        pages = [f"결제 데이터 플랫폼 이관 {n} " + "분석 플랫폼을 옮긴 일의 설명이 이어진다. " * 40 for n in range(40)]  # more batches than one call
        rec, _ = AgentPart.review(AgentPart(), {}, pages=pages, max_calls=1)
        self.assertIn("limit", rec["notes"])  # the limit is named only when it cut the review

    def test_an_older_copy_is_matched_by_its_project_id_only(self):  # another project with the same title is not this item
        old = edition()
        moved = old["roles"][0]["projects"][0]
        moved["id"] = "nara-9"  # another project...
        moved["summary"]["ko"] = "가상은행 분석 플랫폼을 Kubernetes로 이관. Prometheus 지표로 확인"  # ...whose words named tools
        rec = D.review(edition(), "ko", backend="none", old=old)
        self.assertFalse([f for u in rec["units"] for f in u["findings"] if f["code"] == "depth_thinner"])  # nothing lost: it was never this item


class CommandLine(unittest.TestCase):
    """python3 src/depth_review.py review, with stored answers and with the count."""

    def test_review_with_stored_answers_and_the_count(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-depth-"))  # a scratch folder
        prof = tmp / "profile.json"
        prof.write_text(json.dumps(edition(), ensure_ascii=False), encoding="utf-8")
        raw = tmp / "answers.json"  # one stored answer, as --raw keeps them
        raw.write_text(json.dumps({"answers": [{"task": "depth-review", "answer": {"units": [{"id": "item:nara-1", "stated": {"hard": "", "decision": "", "mechanism": ""}, "findings": [
            {"code": "mechanism", "missing": "왜 빨라졌는지 없다", "way": "ask", "question": "무엇이 지연을 줄였나요?"}]}]}}]}, ensure_ascii=False), encoding="utf-8")
        env = {"OFFEROWL_LLM": "none", "OFFEROWL_LANG": "en", "PATH": "/usr/bin:/bin"}  # no model, English messages
        r = subprocess.run([sys.executable, str(ROOT / "src" / "depth_review.py"), "review", str(prof), "--replay", str(raw), "-o", str(tmp / "rec.json")],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("depth review (ko): 2 units", r.stdout)
        self.assertIn("verdicts: 1 thin (fill these first), 0 adequate, 0 strong, 1 with no verdict", r.stdout)  # how many of each
        self.assertIn("- [thin] 가상은행 분석 플랫폼 이관 [", r.stdout)  # the thin item, marked
        self.assertIn(": not said: what made it hard, the decision and its alternative, why it worked", r.stdout)  # the parts its words do not state
        self.assertIn("depth_mechanism (ask, fill first)", r.stdout)  # a missing part of a thin item: the gate
        self.assertIn("question: 무엇이 지연을 줄였나요?", r.stdout)
        rec = json.loads((tmp / "rec.json").read_text(encoding="utf-8"))
        self.assertEqual(1, rec["calls"])
        r = subprocess.run([sys.executable, str(ROOT / "src" / "depth_review.py"), "review", str(prof), "--count"], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual("1", r.stdout.strip())  # two small items: one call


if __name__ == "__main__":
    unittest.main()
