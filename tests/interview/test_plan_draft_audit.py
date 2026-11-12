"""plan, draft and audit end to end on the fictional example, with stand-ins instead of a model."""
import json  # outputs
import pathlib  # paths
import shutil  # clean up
import tempfile  # output folders
import unittest  # the test runner

import helpers  # the import path and the example
from interview import audit, draft, plan  # the commands
from interview.job import Job  # a copied job

# Two interview rounds as the panel keeps them in the job's status.json: list marks, a stray mark, and one question the
# second round asked again with other spacing (fictional)
ROUNDS = [{"id": "i1", "kind": "first", "at": "2026-11-10T15:00", "asked": "- Tell me about yourself.\n2) Why Gamma?\nQ3: How do you roll back a bad deploy?\n-\n"},
          {"id": "i2", "kind": "second", "at": "2026-11-14", "asked": "How do you roll back a  bad deploy?\nWhat is Kafka?"}]


def with_rounds(rounds):
    """A copy of the example with the rounds written beside its kit; returns (tmp dir, job)."""
    tmp, job_dir = helpers.copy_workspace()  # removed by the caller
    (job_dir / "status.json").write_text(json.dumps({"id": "gamma-platform", "rounds": rounds}), encoding="utf-8")
    return tmp, Job(job_dir)


def scene_answer(title_ko, title_en, me, number=None):
    """A stand-in model answer: a two-line scene built from the example's own facts."""
    mine = me if number is None else me + f" // It took **{number} weeks**."  # an optional invented number makes the scene ungrounded
    return {"title_ko": title_ko, "title_en": title_en, "key": "사실만 짧게",  # the fields the draft prompt asks the model for
            "lines": [["면접관", title_en], ["해석", title_ko + "?"],  # the interviewer asks the question, with its 해석
                      ["나", mine], ["해석", "알파페이에서 Argo CD와 Helm으로 공용 배포 경로를 만들었습니다."]],  # the answer, and a 해석 that restates a profile fact
            "caution": ""}  # no 주의 note


class PlanTest(unittest.TestCase):  # plan: the question map built from the posting and the documents
    def setUp(self):  # runs before each test
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-out-"))  # outputs never go into the repository

    def tearDown(self):  # runs after each test
        shutil.rmtree(self.out)  # remove the output folder

    def test_map_is_deterministic_and_complete(self):
        """Every kind of question is there, and two runs give the same file."""
        job = helpers.example_job()  # the example, read in place
        plan.main(job, out=str(self.out))  # first run
        first = (self.out / "plan.json").read_text(encoding="utf-8")  # the map it wrote
        plan.main(job, out=str(self.out))  # second run into the same folder
        self.assertEqual(first, (self.out / "plan.json").read_text(encoding="utf-8"))  # the same bytes: nothing in the map depends on time or chance
        rows = json.loads(first)["questions"]  # the planned questions
        kinds = {r["kind"] for r in rows}  # which kinds of question appear
        # every source of questions is present
        self.assertEqual(kinds, {"posting", "resume", "portfolio", "term", "behavioral", "company", "opening"})
        posting = [r for r in rows if r["kind"] == "posting"]  # the questions taken from the posting
        self.assertEqual(len(posting), 13)  # every list item of the posting
        self.assertEqual(posting[0]["section"], "What you will do")  # each keeps the posting heading it came from
        self.assertEqual([r["text"] for r in rows if r["kind"] == "portfolio"],  # one question per portfolio project, in document order
                         ["Payment approval service redesign", "Internal deploy platform", "Order event pipeline"])
        terms = [r["text"] for r in rows if r["kind"] == "term"]  # the terms found in the documents
        self.assertIn("Kafka", terms)  # a technology named in the posting becomes a term question
        self.assertNotIn("BACKEND", terms)  # a title set in capitals is not an abbreviation
        by = {r["text"]: r for r in posting}  # posting questions by their text
        # a posting line the documents back well is rated strong
        self.assertEqual(by["Run Kafka event pipelines between orders, settlement and notifications"]["coverage"], "strong")
        self.assertEqual(by["Terraform and infrastructure as code"]["coverage"], "none")  # a posting line the documents never touch is rated none
        self.assertTrue(all(r["ask"]["en"] and r["ask"]["ko"] for r in rows))  # rule-made questions in both languages

    def test_questions_asked_in_earlier_rounds_lead_the_map(self):
        """What the rounds asked comes first, each question once with every round that asked it, its id from its words."""
        import re  # the ids' form
        tmp, job = with_rounds(ROUNDS)
        try:
            rows = plan.build(job)
            asked = [r for r in rows if r["kind"] == "asked"]
            self.assertEqual(rows[:len(asked)], asked)  # before every other kind
            self.assertEqual([r["text"] for r in asked], ["Tell me about yourself.", "Why Gamma?", "How do you roll back a bad deploy?", "What is Kafka?"])
            self.assertEqual([r["rounds"] for r in asked], [["i1"], ["i1"], ["i1", "i2"], ["i2"]])  # the one asked again names both rounds
            self.assertEqual(asked[0]["source"], "2026-11-10 first")  # the first round that asked it
            self.assertTrue(all(re.fullmatch(r"a[0-9a-f]{6}", r["id"]) for r in asked))
            self.assertNotEqual(asked[0]["coverage"], "none")  # the example's self-introduction answers it
            self.assertEqual(asked[0]["ask"], {"en": ["Tell me about yourself."], "ko": ["Tell me about yourself."]})  # as written down
            ids = {r["text"]: r["id"] for r in asked}
            shutil.rmtree(tmp)
            tmp, job = with_rounds([dict(ROUNDS[0], asked="What brought you here?\n" + ROUNDS[0]["asked"]), ROUNDS[1]])  # a line written above them
            again = {r["text"]: r["id"] for r in plan.build(job) if r["kind"] == "asked"}
            self.assertEqual({k: again[k] for k in ids}, ids)  # every question keeps its id, so its draft stays its draft
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_phrase_without_a_model_keeps_the_rule_questions(self):
        """plan --phrase with backend none says so and keeps the rule-made questions."""
        job = helpers.example_job()  # the example
        plan.main(job, out=str(self.out), phrase=True, backend="none")  # ask for model phrasing with no model to ask
        rows = json.loads((self.out / "plan.json").read_text(encoding="utf-8"))["questions"]  # the questions it wrote anyway
        self.assertFalse(any("ask_rule" in r for r in rows))  # nothing was phrased, so no question keeps a rule-made copy


class DraftTest(unittest.TestCase):  # draft: scenes from a stand-in model, checked before they are written
    def setUp(self):  # runs before each test
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-out-"))  # outputs never go into the repository

    def tearDown(self):  # runs after each test
        shutil.rmtree(self.out)  # remove the output folder

    def test_draft_writes_new_files_and_rejects_ungrounded_scenes(self):
        """A grounded scene is written, a scene with an invented number is rejected, and nothing is overwritten."""
        job = helpers.example_job()  # the example
        plan.main(job, out=str(self.out))  # draft reads the plan, so write it first
        calls = []  # what the stand-in was asked

        def ask(prompt, entry):  # the stand-in model: records each call and answers with a fixed scene
            calls.append((entry["id"], prompt))  # which planned question was asked, and the whole prompt
            # an answer made only of facts the example's profile holds
            me = ("At **Alpha Pay** / I moved every team / to **one Argo CD application** pattern, / and the **Helm values** "
                  "for each environment / sit in ==one repository==.")
            # p11 gets an invented number of weeks; p6 stays grounded
            return scene_answer("자동화 경험", "Tell me about moving manual work into automation.", me, number=7 if entry["id"] == "p11" else None)

        rc = draft.main(job, out=str(self.out), ids="p6,p11", ask=ask)  # draft two planned questions with the stand-in
        self.assertEqual(rc, 0)  # a rejected scene is reported, not a failed run
        self.assertEqual([c[0] for c in calls], ["p6", "p11", "p11"])  # one call per id, in the order given, and a second try for the one that failed
        self.assertIn("Your last answer was rejected", calls[2][1])  # the second try says why
        self.assertIn("7", calls[2][1].split("Your last answer was rejected")[1])  # with the number the check found
        self.assertIn("Evidence", calls[0][1])  # the writing rules went in
        self.assertIn("[profile alpha-", calls[0][1])  # with evidence from the profile
        d = self.out / "drafts"  # the drafts folder
        written = (d / "drafts-1.md").read_text(encoding="utf-8")  # the first draft file
        self.assertIn("### P1. 자동화 경험 / Tell me about moving manual work into automation.", written)  # a new section and id
        self.assertIn("- **근거**: p6", written)  # the planned question it answers, hidden on the page
        self.assertNotIn("### P2.", written)  # the ungrounded one is not in the file
        rejected = (d / "drafts-1.rejected.md").read_text(encoding="utf-8")  # the rejected scenes, in a side file
        self.assertIn("7", rejected.split("\n")[2])  # its reason names the number
        draft.main(job, out=str(self.out), ids="p6", ask=ask)  # a second run
        self.assertTrue((d / "drafts-2.md").is_file())  # a new file; the first one is unchanged
        self.assertEqual(written, (d / "drafts-1.md").read_text(encoding="utf-8"))  # the first file is unchanged byte for byte

    def test_terms_join_their_section(self):
        """A drafted term scene joins the kit's term section and takes the next free id there."""
        job = helpers.example_job()  # the example
        plan.main(job, out=str(self.out))  # the plan, with its term questions
        rows = json.loads((self.out / "plan.json").read_text(encoding="utf-8"))["questions"]  # the planned questions
        kafka = next(r["id"] for r in rows if r["kind"] == "term" and r["text"] == "Kafka")  # the planned id of the Kafka term question

        def ask(prompt, entry):  # a stand-in that answers with a grounded Kafka scene
            # settlement and notifications at Beta Commerce are facts the example holds
            me = "**Kafka** is / an event stream. // At **Beta Commerce** / settlement and notifications / ==consume the same events== on their own."
            return scene_answer("Kafka가 뭐야", "What is Kafka?", me)  # titled like the kit's term scenes

        draft.main(job, out=str(self.out), ids=kafka, ask=ask)  # draft only that term
        text = (self.out / "drafts" / "drafts-1.md").read_text(encoding="utf-8")  # the written draft file
        self.assertIn("## Q. 꼬리 질문: 줄임말과 용어", text)  # the scene goes under the kit's term section heading
        self.assertIn("### Q3. Kafka가 뭐야 / What is Kafka?", text)  # terms.md already has Q1 and Q2, so the next free id is Q3

    def test_questions_asked_before_get_a_section_of_their_own(self):
        """A script for a question an earlier round asked is written first, with the depth of a question really asked, under a
        section of its own: L, or the first letter the kit leaves free when its own L is about something else."""
        calls = []

        def ask(prompt, entry):  # a grounded Kafka scene, as in the term test
            calls.append(prompt)
            me = "**Kafka** is / an event stream. // At **Beta Commerce** / settlement and notifications / ==consume the same events== on their own."
            return scene_answer("Kafka가 뭐야", "What is Kafka?", me)

        for planted, letter in ((None, "L"), ("## L. 모를 때, 마무리", "B")):  # the example as it is; then with its K section lettered L
            tmp, job = with_rounds(ROUNDS)
            out = pathlib.Path(tmp) / "out"
            try:
                if planted:  # the kit's own L, about something else
                    qa = job.interview / "qa.md"
                    qa.write_text(qa.read_text(encoding="utf-8").replace("## K. 모를 때, 마무리", planted), encoding="utf-8")
                    job = Job(job.dir)  # read again
                plan.main(job, out=str(out))
                rows = json.loads((out / "plan.json").read_text(encoding="utf-8"))["questions"]
                kafka = next(r["id"] for r in rows if r["kind"] == "asked" and r["text"] == "What is Kafka?")
                self.assertEqual(draft.ranked(rows)[0]["kind"], "asked")  # written before every other kind
                draft.main(job, out=str(out), ids=kafka, ask=ask)
                text = (out / "drafts" / "drafts-1.md").read_text(encoding="utf-8")
                self.assertRegex(text, rf"(?m)^## {letter}\. (지난 면접에서 받은 질문|Asked in earlier rounds)$")  # a heading of its own
                self.assertIn(f"### {letter}1. Kafka가 뭐야 / What is Kafka?", text)
                self.assertIn(f"- **근거**: {kafka} ", text)  # the question it answers
                self.assertIn("really asked this in an earlier round", calls[-1])  # the depth of a question really asked
            finally:
                shutil.rmtree(tmp)

    def test_no_model_stops_cleanly(self):
        """With backend none nothing is written and the command says the model stopped."""
        job = helpers.example_job()  # the example
        plan.main(job, out=str(self.out))  # a plan to draft from
        rc = draft.main(job, out=str(self.out), ids="p6", backend="none")  # no stand-in and no model
        self.assertEqual(rc, 1)  # the command reports that the model stopped
        self.assertFalse((self.out / "drafts" / "drafts-1.md").exists())  # and writes no draft file


class AuditTest(unittest.TestCase):  # audit: posting coverage and the model's consistency flags
    def setUp(self):  # runs before each test
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-out-"))  # outputs never go into the repository

    def tearDown(self):  # runs after each test
        shutil.rmtree(self.out)  # remove the output folder

    def test_coverage_and_quote_checked_consistency(self):
        """Coverage rates every posting line; a consistency flag survives only when both quotes are real."""
        job = helpers.example_job()  # the example

        def ask(prompt, ids):  # the stand-in consistency model: flags for the scenes it is shown
            flags = []  # no flags unless R1 is in this batch
            if "R1" in ids:  # R1 holds the planted rollback time
                flags.append({"id": "R1", "scene_quote": "from 30 minutes to about 5", "doc": "portfolio",  # a real flag: both quotes appear in the files
                              "doc_quote": "rollback from 30 to 4 minutes", "kind": "number", "why": "rollback time differs"})
                flags.append({"id": "R1", "scene_quote": "from 30 minutes to about 3", "doc": "portfolio",  # a made-up flag: no scene says about 3
                              "doc_quote": "rollback from 30 to 4 minutes", "kind": "number", "why": "made-up quote"})
            return {"flags": flags}  # the answer shape audit expects

        audit.main(job, out=str(self.out), consistency=True, ask=ask)  # coverage, plus the consistency pass with the stand-in
        rec = json.loads((self.out / "audit.json").read_text(encoding="utf-8"))  # the audit record
        ratings = [r["rating"] for r in rec["coverage"]]  # one rating per posting line
        self.assertEqual(len(ratings), 13)  # every posting line is rated
        self.assertEqual({"strong", "weak", "none"}, set(ratings))  # the example spans all three ratings
        kept = rec["consistency"]["kept"]  # flags that survived the quote check
        self.assertEqual([(f["id"], f["scene_quote"]) for f in kept], [("R1", "from 30 minutes to about 5")])  # only the flag whose quotes are both real is kept
        self.assertEqual(len(rec["consistency"]["dropped"]), 1)  # the made-up one is dropped and counted
        self.assertIn("rollback time differs", (self.out / "audit.md").read_text(encoding="utf-8"))  # the readable report shows the kept flag's reason


if __name__ == "__main__":  # the file can also run on its own
    unittest.main()
