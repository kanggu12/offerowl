"""The audit without a model: the stricter coverage rule, the portfolio claims, the risk order and
the call budget of the consistency pass, the judges with stand-ins, the answer key score and the answer cache."""
import json  # records
import pathlib  # paths
import shutil  # clean up
import tempfile  # scratch folders
import unittest  # the test runner
import unittest.mock  # a stand-in for llm.run

import helpers  # the import path and the example
from interview import audit, check, cover  # the parts under test


def item(iid, role, title, en="", text=""):
    """A minimal corpus item for the coverage rule."""
    return {"id": iid, "role": role, "tko": title, "ten": "", "key": "", "en": en, "ko": "", "text": text or en,
            "md": f"**면접관** {title}\n**나** {en}"}


class CoverageRuleTest(unittest.TestCase):  # cover.py's rule: a scene is measured on what it says
    def test_terms_and_notes_do_not_make_a_line_strong(self):
        """A "what is X" entry, or a scene whose notes quote the line, rates weak; a scene that says it rates strong."""
        line = "Participate in weekly on-call rotation"  # a posting line
        term = item("Q1", "terms", "What is on-call rotation?", "On-call rotation means weekly turns.")  # a definition
        noted = item("L1", "scenes", "After-hours work", "Yes, that is fine.", text="Yes, that is fine. Note: answers 'Participate in weekly on-call rotation'.")  # notes quote it
        said = item("L2", "scenes", "Are you okay with the weekly on-call rotation?", "Yes, a weekly on-call rotation is fine with me.")  # it says it
        rate = lambda items: cover.Coverage(items, {}, {}).rate(line)[0]  # noqa: E731  the rating for this line
        self.assertEqual(rate([term]), "weak")  # a term entry alone
        self.assertEqual(rate([noted]), "none")  # the notes do not count, and nothing it says is about the line
        self.assertEqual(rate([term, said]), "strong")  # the scene that says it
        self.assertEqual(cover.Coverage([noted], {}, {"coverage": {"spoken": False}}).rate(line)[0], "weak")  # every word counted: the notes reach the share, but the title is not about the line
        self.assertEqual(cover.first_question(said), "Are you okay with the weekly on-call rotation?")  # the interviewer's first line


class PartsTest(unittest.TestCase):  # the no-model parts
    def test_paragraphs_keep_headers_with_what_they_head(self):
        """In reading order a company, its dates and its title are three paragraphs; merge joins them."""
        text = "Acme\n\nSeoul 2019.03 - 2022.06 (3 yrs)\n\nPlatform Team / Lead Engineer\n\nBuilt the deploy path for every team and ran it."
        self.assertEqual(audit.paragraphs(text, merge=True), ["Acme Seoul 2019.03 - 2022.06 (3 yrs) Platform Team / Lead Engineer Built the deploy path for every team and ran it."])
        self.assertEqual(len(audit.paragraphs(text)), 3)  # without merge the one-word name is dropped, the rest stand apart

    def test_related_prefers_rare_words(self):
        """The text that shares the rarest words comes first."""
        idx = audit.Related({"a": "the deploy path for payments", "b": "kafka settlement events for payments", "c": "the deploy path for orders"})
        self.assertEqual(idx.best("kafka settlement for payments", 1)[0][0], "b")  # kafka and settlement are rare

    def test_names_are_found_in_time_on_a_long_run_of_digits(self):
        """A name with an inner capital or a digit is found, and a token with a word character after its digits no longer
        backtracks exponentially (22 zeros took 0.15 s and every one more doubled it: 32 took minutes)."""
        import time  # the bound
        names = [p for kind, p, _ in audit.claim_phrases("We moved MoAI and KohakuHub onto H100 nodes with Codex in 2024.") if kind == "name"]
        self.assertEqual(["MoAI", "KohakuHub", "H100", "Codex"], names)
        t0 = time.perf_counter()
        audit.claim_phrases("The trace held A" + "0" * 32 + "_x and nothing more.")
        self.assertLess(time.perf_counter() - t0, 1.0)

    def test_risk_order(self):
        """A scene that limits its scope and claims in the first person ranks above a plain one."""
        hedged = audit.risk("Honestly, the service already ran before I came; I set up the billing team in March 2024.", 30)
        plain = audit.risk("We use dashboards for every service.", 30)
        self.assertGreater(hedged, plain)  # riskier
        self.assertEqual(plain, 0)  # no signal at all

    def test_portfolio_claims_list_the_unanswered_line(self):
        """The example portfolio's engineering day line is said by no scene, so it is listed."""
        job = helpers.example_job()  # the example
        claims = audit.portfolio_claims(job, audit.scene_answers(job), limit=0)  # every candidate
        hits = [c for c in claims if "engineering day" in c["text"]]  # the planted line
        self.assertTrue(hits)  # listed
        self.assertIn("engineering day", " ".join(hits[0]["missing"]))  # with the phrase no scene says


class JudgeTest(unittest.TestCase):  # the judges with stand-ins
    def test_coverage_judge_moves_ratings(self):
        """A strong line no scene answers drops to weak; a weak line a candidate answers rises to strong."""
        job = helpers.example_job()  # the example
        items, alts = __import__("interview.corpus", fromlist=["load"]).load(job)  # its items
        rows = audit.coverage(job, items, alts)  # the rule's ratings
        strong = next(r for r in rows if r[3] == "strong")  # some strong line
        weak = next(r for r in rows if r[3] != "strong")  # some line that is not

        def ask(prompt, ids):  # the stand-in judge: no for the strong line, yes for the weak one with the first candidate it was shown
            first = prompt.split(f"Line {weak[0]}:", 1)[1].split("[", 1)[1].split("]", 1)[0]  # the weak line's first candidate id
            return {"lines": [{"n": str(strong[0]), "verdict": "no", "id": "", "why": "off-topic"},
                              {"n": str(weak[0]), "verdict": "yes", "id": first, "why": "answers it"}]}
        out, verdicts, why = audit.judge_coverage(rows, audit.scene_answers(job), items, ask)
        got = {r[0]: r[3] for r in out}  # line -> rating
        self.assertEqual((got[strong[0]], got[weak[0]], why, len(verdicts)), ("weak", "strong", "", 2))

    def test_claims_judge_order(self):
        """The judge's picks come back in its order; unknown numbers are ignored; no answer keeps the rule's order."""
        claims = [{"page": 1, "text": f"line {k}", "missing": ["x"], "score": 1} for k in range(5)]  # five candidates
        picked, why = audit.judge_claims(claims, lambda p, ids: {"picks": [{"n": "3", "why": "a"}, {"n": "9", "why": "?"}, {"n": "0", "why": "b"}]}, keep=2)
        self.assertEqual(([c["text"] for c in picked], why), (["line 3", "line 0"], ""))

        def down(p, ids):  # no model at all
            raise RuntimeError("no model")
        self.assertEqual([c["text"] for c in audit.judge_claims(claims, down, keep=2)[0]], ["line 0", "line 1"])


class ConsistencyBudgetTest(unittest.TestCase):  # the call budget and the cross-scene quotes
    def setUp(self):  # a scratch output folder
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-audit2-"))  # never the repository
        self.addCleanup(shutil.rmtree, self.out, True)  # removed afterwards

    def test_budget_and_cross_scene_flags(self):
        """calls=1 sends one batch, the riskiest scenes first; a flag quoting another scene is checked against it."""
        job = helpers.example_job()  # the example
        answers = audit.scene_answers(job)  # my lines of every scene
        _, scenes = check.load_scenes(job)  # every scene
        batches = []  # the ids of each call

        def ask(prompt, ids):  # the stand-in: a real cross-scene flag and a made-up one
            batches.append(ids)  # counted
            a, b = ids[0], ids[1]  # two scenes of the batch
            qa, qb = answers[a][1].split(".")[0], answers[b][1].split(".")[0]  # a sentence of each
            return {"flags": [{"id": a, "scene_quote": qa, "doc": f"scene {b}", "doc_quote": qb, "kind": "scene", "why": "real quotes"},
                              {"id": a, "scene_quote": qa, "doc": f"scene {b}", "doc_quote": "words nobody said", "kind": "scene", "why": "made up"}]}
        kept, dropped, sent, why, considered = audit.consistency_flags(job, scenes, audit.docs(job), ask, answers=answers, calls=1)
        self.assertEqual(len(batches), 1)  # one call
        self.assertEqual(sent, min(audit.BATCH_BUDGET, considered))  # a full batch
        self.assertEqual((len(kept), len(dropped)), (1, 1))  # the real quotes kept, the made-up one dropped
        plan = audit.plan_consistency(job, answers, audit.docs(job))  # the order
        self.assertEqual(batches[0], [w[1]["id"] for w in plan[:audit.BATCH_BUDGET]])  # the riskiest scenes went first


class KeyTest(unittest.TestCase):  # scoring against an answer key, and the answer cache
    def setUp(self):  # a scratch output folder
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-key-"))  # never the repository
        self.addCleanup(shutil.rmtree, self.out, True)  # removed afterwards

    def test_example_key(self):
        """The example's fictional key: the uncovered line, the planted rollback number and the unanswered claim."""
        job = helpers.example_job()  # the example

        def ask(prompt, ids):  # the stand-in consistency model: the planted R1 flag
            if "R1" not in ids:  # only the batch with R1
                return {"flags": []}
            return {"flags": [{"id": "R1", "scene_quote": "from 30 minutes to about 5", "doc": "portfolio", "doc_quote": "rollback from 30 to 4 minutes",
                               "kind": "number", "why": "rollback time differs"}]}
        audit.main(job, out=str(self.out), consistency=True, ask=ask, key=str(helpers.JOB / "expected_findings.json"))
        rec = json.loads((self.out / "recall.json").read_text(encoding="utf-8"))  # the score
        self.assertEqual((rec["recall"]["found"], rec["recall"]["key"]), (3, 3))  # every key item found
        self.assertGreater(rec["precision"]["findings"], rec["precision"]["in_key"])  # the audit also lists things the key does not hold
        self.assertIn("Against the answer key", (self.out / "audit.md").read_text(encoding="utf-8"))  # the report says so

    def test_cache_asks_once(self):
        """The same prompt twice is one model call; the answer comes back from the cache the second time."""
        calls = []  # llm.run's calls

        def fake(task, prompt, **kw):  # stands in for llm.run
            calls.append(task)
            return {"flags": [{"id": "X"}]}
        with unittest.mock.patch("llm.run", fake):  # no model
            ask = audit.model_ask("none", cache=self.out / "cache")  # with a cache folder
            first, second = ask("same prompt", []), ask("same prompt", [])  # asked twice
            third = ask("another prompt", [])  # a new prompt is a new call
        self.assertEqual((first, second, third, len(calls)), ({"flags": [{"id": "X"}]},) * 3 + (2,))


class CliTest(unittest.TestCase):  # the command line reaches the new options
    def test_cue_and_audit_options(self):
        """cue writes its page; audit --judge --calls --key with backend none keeps the rule's results and scores them."""
        out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-cli-"))  # never the repository
        self.addCleanup(shutil.rmtree, out, True)  # removed afterwards
        from interview import cli  # the command line
        job = str(helpers.JOB)  # the example job
        self.assertEqual(cli.main(["cue", "--job", job, "--sec", "A", "--out", str(out)]), 0)  # three cards
        self.assertTrue((out / "cue_cards.html").is_file())
        rc = cli.main(["audit", "--job", job, "--out", str(out), "--judge", "--consistency", "--calls", "1", "--backend", "none",
                       "--key", str(helpers.JOB / "expected_findings.json")])  # no model: the judges and the consistency pass say why and step aside
        self.assertEqual(rc, 0)
        rec = json.loads((out / "recall.json").read_text(encoding="utf-8"))  # scored anyway
        self.assertEqual(rec["parts"]["coverage"]["found"], 1)  # the uncovered Terraform line, by rule
        self.assertEqual(rec["parts"]["portfolio_contradictions"]["found"], 0)  # no model, no flags
        self.assertFalse((out / "model_cache").exists())  # nothing was asked, so nothing was cached


if __name__ == "__main__":  # the file can also run on its own
    unittest.main()
