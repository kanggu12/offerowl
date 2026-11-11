# -*- coding: utf-8 -*-
"""The resume drafting step (src/write_resume.py, `draft.py write` and `draft.py check`) with a stand-in model.

The stand-in (standin.py) answers for the fictional ledger in fixtures/ledger_ko.json and plants the problems the checks
must catch. No real model and no container: the drafted profile is read back through the profile loader with node, which
is what the renderer reads."""
import copy  # profiles are copied before a test spoils them
import json  # every file is JSON
import os  # environment for the command line tests
import pathlib  # paths
import shutil  # is node installed
import subprocess  # the command line and the loader
import sys  # the import path
import tempfile  # scratch folders
import unittest  # the test runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
HERE = pathlib.Path(__file__).resolve().parent  # tests/write
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
sys.path.insert(0, str(HERE))  # the stand-in
import llm  # noqa: E402  (replaced by the stand-in in each test)
import standin  # noqa: E402
import write_resume as W  # noqa: E402

LEDGER = json.loads((HERE / "fixtures" / "ledger_ko.json").read_text(encoding="utf-8"))  # the fictional ledger
POSTING = (HERE / "fixtures" / "posting_en.md").read_text(encoding="utf-8")  # the fictional posting
PRIVATE = str(HERE / "fixtures" / "style_private.json")  # a fictional private style pack


class Model:
    """Replace llm.run with a stand-in for the length of a with-block."""

    def __init__(self, **over):  # override answers per task
        self.stand = standin.StandIn(**over)  # the canned answers, with any override

    def __enter__(self):  # entering the block
        self.real = llm.run  # the real function, put back afterwards
        llm.run = self.stand  # every call goes to the stand-in
        return self.stand

    def __exit__(self, *exc):  # leaving the block
        llm.run = self.real  # restore, even when the test failed


def run_draft(style=None, posting=POSTING, **over):
    """One drafting run with the stand-in; returns (new profile, record, stand-in)."""
    st = style or W.load_style(PRIVATE)  # the private pack forbids numbers, so the planted "half" must go
    with Model(**over) as m:  # llm.run answers from the table
        new, rec = W.draft(copy.deepcopy(LEDGER), posting_text=posting, style=st)  # a copy, so no test changes the fixture
    return new, rec, m


class DraftTests(unittest.TestCase):  # draft() with the stand-in
    def test_every_part_is_written_in_both_languages(self):  # headline, intro, cards, selected projects, competencies, items, about, motivation
        new, rec, m = run_draft()  # one run with the planted problems
        self.assertEqual([c[0] for c in m.calls], ["write-items", "write-summary", "write-competencies", "write-about", "write-deck", "write-repair"])  # five stages and one repair
        for lang in ("ko", "en"):  # both editions
            p = rec["check"]["parts"][lang]  # what the renderer would print
            self.assertTrue(p["headline"] and p["intro"] and p["motivation"], p)  # the top of the resume and the motivation
            self.assertEqual(p["cards"], 4)  # four overview cards
            self.assertEqual(p["highlights"], 2)  # the selected-project cards the stand-in wrote
            self.assertEqual(p["competencies"], 4)  # four competencies
            self.assertEqual(p["about"], 2)  # two about me sections
            self.assertEqual(p["items"], 3)  # three items survive; the fourth (a dashboard the person only helped with) is dropped
            self.assertEqual(p["role_desc"], 1)  # one company line (the other role has no context to describe)

    def test_the_result_passes_its_own_check_with_every_sentence_linked(self):  # 0 fact flags, 0 texts without evidence
        new, rec, _ = run_draft()  # one run
        res = W.check_profile(new, W.load_style(PRIVATE))  # an independent pass over the new profile
        self.assertTrue(res["ok"], res)  # the result passes
        self.assertEqual(res["facts"], [])  # no fact flag
        self.assertEqual(res["unlinked"], [])  # every printed text is linked to its evidence
        self.assertEqual(res["claims"], [])  # what was too strong was repaired or dropped
        self.assertGreater(res["sentences"], 40)  # both languages, every field
        self.assertTrue(all(x["ev"] or x.get("frame") for x in new["evidence"]))  # every sentence cites evidence, or frames the company in the motivation

    def test_a_claim_stronger_than_its_evidence_is_repaired(self):  # "designed and led" where the ledger says "proposed" and "with the team"
        new, rec, m = run_draft()  # one run
        first = [e for e in rec["texts"] if e["at"] == "project.nara-1.summary" and e["lang"] == "en" and e["round"] == "repair"]  # the overclaim's repair round
        self.assertTrue(first, "the sentence went to the repair round")  # it was sent back
        repair_prompt = next(p for t_, p in m.calls if t_ == "write-repair")  # what the repair request said
        self.assertIn("Designed and led", repair_prompt)  # the request shows the rejected text
        self.assertIn("제안했", repair_prompt)  # the reason quotes the evidence's word
        summary = new["roles"][0]["projects"]  # the first role's projects
        item = next(p for p in summary if p["id"] == "nara-1")  # the item that held the overclaim
        self.assertIn("Proposed a design", item["summary"]["en"])  # the qualifier is kept
        self.assertNotIn("Designed and led", item["summary"]["en"])  # the strong claim is gone

    def test_numbers_and_invented_names_do_not_survive(self):  # "half" under a pack that forbids numbers; a client no evidence names
        new, rec, _ = run_draft()  # one run
        text = json.dumps({k: new[k] for k in ("summary", "roles", "competencies", "about", "motivation")}, ensure_ascii=False)  # everything the renderer prints
        self.assertNotIn("in half", text)  # repaired
        self.assertNotIn("Delta Bank", text)  # dropped
        gone = {(d["at"], d["lang"]) for d in rec["dropped"]}  # what was dropped for good
        self.assertIn(("project.nara-3.summary", "en"), gone)  # the item without support is gone in English
        self.assertIn(("project.nara-3.summary", "ko"), gone)  # both languages go, so the editions say the same thing
        nara3 = next(p for p in new["roles"][0]["projects"] if p["id"] == "nara-3")  # the project itself
        self.assertIs(nara3.get("resume"), False)  # the project stays in the profile, off the resume

    def test_items_follow_scope_decision_result_and_carry_one_highlight(self):  # the order of the parts and one highlight per item
        new, _, _ = run_draft()  # one run
        item = next(p for p in new["roles"][0]["projects"] if p["id"] == "nara-1")  # the item with three parts
        en = item["summary"]["en"]  # its English sentences
        self.assertLess(en.index("single server"), en.index("Proposed a design"))  # scope before decision, although the model wrote them the other way round
        self.assertLess(en.index("Proposed a design"), en.index("Prometheus"))  # decision before result
        for lang in ("ko", "en"):  # both editions
            self.assertEqual(item["summary"][lang].count("=="), 2)  # exactly one highlighted phrase
        self.assertTrue(item["summary"]["ko"].replace("==", "").endswith("확인"))  # Korean items end in a noun (resume bullet style), without a full stop

    def test_one_item_is_one_project(self):  # a sentence may not borrow a block of another project
        bad = copy.deepcopy(standin.ITEMS)  # a copy of the stand-in's items
        bad["roles"][0]["items"][1]["sentences"][0]["ev"] = ["nara-2#1", "nara-1#4"]  # nara-1's block in a nara-2 sentence
        new, rec, _ = run_draft(**{"write-items": bad})  # the stand-in answers with the spoiled items
        e = next(x for x in rec["texts"] if x["at"] == "project.nara-2.summary" and x["lang"] == "en")  # the sentence that borrowed a block
        self.assertEqual(e["ev"], ["nara-2#1"])  # the other project's block is gone

    def test_the_old_ledger_title_is_kept_and_the_ids_keep_their_meaning(self):  # a drafted summary would shift the block numbers
        new, _, _ = run_draft()  # one run
        item = next(p for p in new["roles"][0]["projects"] if p["id"] == "nara-1")  # a drafted project
        self.assertEqual(item["ledger"]["title"], "결제 데이터 플랫폼 이관")  # what the draft replaced
        view = W.ledger_view(new)  # the profile as the ids read it
        U = W.C.units_of(view, "ko")  # its units
        self.assertEqual(U["index"]["nara-1#2"]["text"], "분석 플랫폼을 Kubernetes로 옮기는 설계안을 만들어 제안했다")  # the same block as before drafting

    def test_an_edit_after_drafting_is_reported(self):  # text that no linked sentence covers cannot pass as evidenced
        new, _, _ = run_draft()  # one run
        edited = copy.deepcopy(new)  # a copy to edit
        edited["summary"]["headline"]["en"] = "Led every platform at a global bank"  # a person's edit with a new claim
        res = W.check_profile(edited, W.load_style(PRIVATE))  # the check after the edit
        self.assertFalse(res["ok"])  # it fails
        self.assertTrue(any(x["at"] == "summary.headline" and x["lang"] == "en" for x in res["unlinked"]))  # and says which field

    def test_the_deck_s_opening_words_rest_on_the_evidence(self):  # tiles, columns and lines for the deck, held to the same checks
        bad = copy.deepcopy(standin.DECK)  # the usual answer, with one tile that claims a number
        bad["stats"].append({"value": {"ko": "지연 70% 감소", "en": "70% less latency"}, "ko": "쿼리 지연 감소", "en": "Cut query latency", "ev": ["nara-1#4"]})  # 70 is in no evidence
        new, rec, m = run_draft(style=W.load_style(None), **{"write-deck": bad})  # every part, the default pack (numbers must be in the evidence)
        S = new["summary"]  # where the deck's words go
        self.assertEqual(3, len(S["stats"]["ko"]))  # three tiles: the one with the made-up number did not pass
        self.assertNotIn("70", json.dumps(S["stats"], ensure_ascii=False))  # and nothing of it was printed
        self.assertEqual(["Platform moves", "Deployment", "On-call"], [f[0] for f in S["focus"]["en"]])  # the columns, in both languages
        self.assertTrue(S["contents"]["en"].startswith("Most recent first"))  # the line over the contents
        linked = {x["at"] for x in new["evidence"]}  # every drafted text with its ids
        self.assertIn("summary.stats.0.value", linked)  # a tile's head
        self.assertIn("summary.focus.1.text", linked)  # a column's line
        path = {r["key"]: r.get("journey") for r in new["roles"]}  # the cover's career path
        self.assertEqual("Platform", path["nara"]["phase"]["en"])  # a station's kind of work, in both languages
        self.assertEqual("Ansible 플레이북 검증", path["dasom"]["key"]["ko"])  # and what the role is known by
        self.assertEqual({"nara", "dasom"}, {k for k, v in path.items() if v})  # a role that is not in the profile has no station
        self.assertIn("role.nara.journey.line", linked)  # each part has its ids
        strayed = copy.deepcopy(standin.DECK)  # a station that cites only another role's blocks
        strayed["journey"][0]["ev"] = ["dasom-1#1"]  # Nara's words on Dasom's evidence
        new2, _, _ = run_draft(style=W.load_style(None), **{"write-deck": strayed})  # drafted again
        self.assertFalse(any(r.get("journey") for r in new2["roles"]))  # one station stands alone, so the cover keeps its timeline
        edited = copy.deepcopy(new)  # a person's edit after the draft
        next(r for r in edited["roles"] if r["key"] == "nara")["journey"]["key"]["en"] = "9000 nodes at OpenAI"  # a claim no evidence holds
        res = W.check_profile(edited, W.load_style(None))  # the independent check
        self.assertTrue(any(x["at"] == "role.nara.journey.key" for x in res["unlinked"] + res["facts"]), res["unlinked"][:3])  # it looks at the career path too
        lone = copy.deepcopy(standin.DECK)  # only one station: no path
        lone["journey"] = lone["journey"][:1]  # the first one
        new1, _, _ = run_draft(style=W.load_style(None), **{"write-deck": lone})  # drafted again
        self.assertFalse(any(r.get("journey") for r in new1["roles"]))  # the cover keeps its timeline
        self.assertEqual([], [x for x in rec["check"]["facts"] if x["at"].startswith("summary.stats") or x["at"].startswith("summary.focus")])  # the independent check finds nothing in them
        long = copy.deepcopy(standin.DECK)  # a tile whose value would not fit its line on the cover
        long["stats"][0]["value"] = {"ko": "한 서버의 분석 플랫폼을 이관", "en": "Moved the whole analytics platform"}  # too long for a tile
        new2, _, _ = run_draft(style=W.load_style(None), **{"write-deck": long})  # drafted again
        self.assertNotIn("한 서버의 분석 플랫폼을 이관", json.dumps(new2["summary"].get("stats"), ensure_ascii=False))  # the stand-in cannot shorten it, so it is left out
        wide = copy.deepcopy(standin.DECK)  # an English value of few words but many letters
        wide["stats"][0]["value"] = {"ko": "플랫폼 이관", "en": "Active-Standby failover"}  # 23 letters, past a tile
        new3, _, _ = run_draft(style=W.load_style(None), **{"write-deck": wide})  # drafted again
        self.assertNotIn("Active-Standby failover", json.dumps(new3["summary"].get("stats"), ensure_ascii=False))  # left out, since the stand-in cannot shorten it

    def test_without_a_posting_only_missing_parts_are_drafted(self):  # a run that fills gaps keeps what the person wrote
        prof = copy.deepcopy(LEDGER)  # a ledger with a written summary
        prof["summary"].update(headline="직접 쓴 머리 문장", intro="직접 쓴 소개", cards=[["a", "b"], ["c", "d"]],  # the person's own top of the resume
                               highlights=[{"title": "t", "where": "w", "rows": [["문제", "x"], ["한 일", "y"], ["결과", "z"]]}])  # one selected-project card
        self.assertEqual(W.missing_parts(prof), ["items", "competencies", "about", "deck"])  # the summary is there already
        with Model() as m:  # the stand-in
            new, rec = W.draft(prof, style=W.load_style(PRIVATE))  # no posting: fill what is missing
        self.assertNotIn("write-summary", [c[0] for c in m.calls])  # not asked
        self.assertEqual(new["summary"]["headline"], "직접 쓴 머리 문장")  # untouched

    def test_the_prompts_carry_the_rules_the_posting_and_the_evidence(self):  # what the model is told
        _, _, m = run_draft()  # one run
        items = m.calls[0][1]  # the items prompt
        self.assertIn("Site Reliability Engineer", items)  # the job
        self.assertIn("[nara-1#2] 분석 플랫폼을 Kubernetes로 옮기는 설계안을 만들어 제안했다", items)  # the evidence with its id
        self.assertIn("Never turn it into led, designed, built or owned", items)  # the claim rule
        self.assertIn("Write no numbers in the prose", items)  # the private pack forbids numbers
        self.assertIn("spearheaded", items)  # the pack's banned words
        self.assertIn("Observability (not 관측 가능성)", items)  # the pack's coined term
        self.assertNotIn("메모", items)  # notes to the ledger's owner never reach a prompt
        summary = m.calls[1][1]  # the summary prompt
        self.assertIn("Do not lead the headline or the introduction with these roles: dasom", summary)  # the pack's lead rule

    def test_replay_reproduces_a_run_without_a_model(self):  # stored answers re-checked after a rule change cost no call
        raw = []  # the answers as the model wrote them
        st = W.load_style(PRIVATE)  # the private pack
        with Model():  # the stand-in
            new1, _ = W.draft(copy.deepcopy(LEDGER), posting_text=POSTING, style=st, ask=W.model_ask(None, raw))  # a run that records its answers
        new2, rec2 = W.draft(copy.deepcopy(LEDGER), posting_text=POSTING, style=st, ask=W.replay_ask(raw))  # the same answers, no model
        drop = lambda p: {k: v for k, v in p.items() if k != "_draft"}  # the stamp carries the date only
        self.assertEqual(drop(new1), drop(new2))  # the same profile

    def test_each_role_is_trimmed_to_its_space(self):  # space follows tenure: words, not items
        st = W.load_style(PRIVATE)  # the private pack
        st["resume"]["items"], st["resume"]["work_words"] = 2, {"en": 40}  # a tiny budget: one short item per role
        new, rec, _ = run_draft(style=st)  # one run with the tiny budget
        self.assertIn("nara-2", rec["trimmed"])  # the second item of the first role gave way
        nara2 = next(p for p in new["roles"][0]["projects"] if p["id"] == "nara-2")  # the second item of the first role
        self.assertIs(nara2.get("resume"), False)  # and stays off the resume
        first = next(p for p in new["roles"][0]["projects"] if p["id"] == "nara-1")  # the first item
        self.assertNotEqual(first.get("resume"), False)  # the role keeps its minimum

    def test_a_short_role_gets_little_room(self):  # bounds and words in proportion to tenure
        roles = [{"key": "a", "months": 5, "projects": [None] * 12}, {"key": "b", "months": 60, "projects": [None] * 12}]  # a short role and a long one
        got = W.shares(roles, 20, 1200)  # their bounds and words
        self.assertEqual(got["a"][:2], (1, 2))  # one or two items for five months
        self.assertLess(got["a"][2], got["b"][2] / 5)  # and a small share of the words

    def test_no_model_changes_nothing(self):  # the none backend stops before anything is written
        with self.assertRaises(W.Stopped):  # the none backend
            W.draft(copy.deepcopy(LEDGER), posting_text=POSTING, style=W.load_style(PRIVATE), backend="none")  # never reaches a model


class LoaderTests(unittest.TestCase):  # the drafted profile through the profile loader
    @unittest.skipUnless(shutil.which("node"), "node is not installed")  # the loader is JavaScript
    def test_the_renderer_reads_the_drafted_profile_in_both_languages(self):  # the profile loader is what the resume and the deck read
        new, _, _ = run_draft()  # one run
        with tempfile.TemporaryDirectory() as tmp:  # a scratch folder
            f = pathlib.Path(tmp) / "draft.json"  # the drafted profile as a file
            f.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")  # as the renderer would read it
            for lang in ("ko", "en"):  # both editions
                out = subprocess.run(["node", str(ROOT / "src" / "profile_loader.js"), str(f), lang], capture_output=True, text=True, encoding="utf-8", timeout=60)  # the loader's command line
                self.assertEqual(out.returncode, 0, out.stderr)  # it read the profile
                p = json.loads(out.stdout)  # the normalized profile
                self.assertTrue(p["summary"]["headline"])  # a string in that language
                self.assertEqual(len(p["summary"]["cards"]), 4)  # four cards
                self.assertTrue(all(c["evidence"] for c in p["competencies"]))  # each competency names its projects
                shown = [x for r in p["roles"] for x in r["projects"] if x.get("resume") is not False]  # the items the resume prints
                self.assertTrue(all(isinstance(x["summary"], str) and x["summary"] for x in shown))  # every item on the resume has its sentences


class CommandLineTests(unittest.TestCase):  # draft.py write and check
    def test_draft_write_without_a_model_exits_2_and_writes_nothing(self):  # the launcher's path
        with tempfile.TemporaryDirectory() as tmp:  # a scratch folder
            out = pathlib.Path(tmp) / "x.draft.json"  # where a draft would go
            env = {**os.environ, "OFFEROWL_LLM": "none", "OFFEROWL_LANG": "en"}  # no model, English messages
            r = subprocess.run([sys.executable, str(ROOT / "src" / "draft.py"), "write", str(HERE / "fixtures" / "ledger_ko.json"), "-o", str(out)],  # the launcher's path
                               capture_output=True, text=True, env=env, timeout=120)  # captured
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)  # exit 2: no model
            self.assertIn("No model answered", r.stdout)  # the message says so
            self.assertFalse(out.exists())  # nothing was written

    def test_draft_check_passes_a_drafted_profile_and_fails_an_edited_one(self):  # the verdict is the last line
        new, _, _ = run_draft()  # one run
        with tempfile.TemporaryDirectory() as tmp:  # a scratch folder
            f = pathlib.Path(tmp) / "p.draft.json"  # the drafted profile as a file
            f.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")  # written
            env = {**os.environ, "OFFEROWL_LANG": "en"}  # English messages
            r = subprocess.run([sys.executable, str(ROOT / "src" / "draft.py"), "check", str(f), "--style", PRIVATE], capture_output=True, text=True, env=env, timeout=120)  # the check command
            self.assertEqual(r.returncode, 0, r.stdout)  # exit 0
            self.assertTrue(r.stdout.strip().splitlines()[-1].startswith("resume check: PASS"), r.stdout)  # the verdict line
            new["motivation"]["en"] += " I doubled revenue."  # an edit with a number and a claim no evidence holds
            f.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")  # the edited profile
            r = subprocess.run([sys.executable, str(ROOT / "src" / "draft.py"), "check", str(f), "--style", PRIVATE], capture_output=True, text=True, env=env, timeout=120)  # the check again
            self.assertEqual(r.returncode, 1)  # exit 1
            self.assertTrue(r.stdout.strip().splitlines()[-1].startswith("resume check: FAIL"), r.stdout)  # the verdict line


class StyleTests(unittest.TestCase):  # style packs
    def test_the_default_pack_is_generic(self):  # no numbers rule beyond the evidence, only general hype words
        st = W.load_style(None)  # the shipped default
        self.assertEqual(st["resume"]["numbers"], "evidence")  # numbers only from the evidence
        self.assertIn("world-class", st["resume"]["banned_words"]["en"])  # general hype words
        self.assertEqual(st["resume"]["avoid_lead"], [])  # no person's rules

    def test_a_private_pack_adds_its_rules(self):  # banned words, coined terms, Korean endings and title ends are applied
        st = W.load_style(PRIVATE)  # the fictional private pack
        ctx = W.Ctx(LEDGER, st)  # a checking context over the ledger
        codes = lambda text, lang, ids, kind="item": [i["code"] for i in W.text_issues(text, lang, ids, {}, ctx, kind=kind, marks=(0, 1))]  # the codes of one text
        self.assertIn("banned_word", codes("Spearheaded the move to Kubernetes", "en", ["nara-1#2"]))  # a banned word
        self.assertIn("coined", codes("관측 가능성 지표로 지연 확인", "ko", ["nara-1#4"]))  # a coined term
        self.assertIn("ending", codes("Prometheus 지표로 쿼리 지연을 확인했다", "ko", ["nara-1#4"]))  # prose ending in a resume bullet: polish
        self.assertIn("number", codes("Cut the latency by 50%", "en", ["nara-1#5"]))  # numbers are forbidden even when the evidence has them
        self.assertIn("banned_char", codes("Moved the platform — with the team", "en", ["nara-1#3"]))  # a banned character

    def test_a_missing_pack_stops(self):  # a typo must never switch the rules off
        with self.assertRaises(SystemExit):  # a missing pack
            W.load_style("no-such-pack")  # stops the run


if __name__ == "__main__":  # run this file alone
    unittest.main()  # run this file alone
