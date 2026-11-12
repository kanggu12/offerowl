# -*- coding: utf-8 -*-
"""The decision layer (src/decide): the interface, each backend with stand-ins, the evaluation's scoring, and the
labelled fixtures. No model, no download, no network beyond a stand-in server on 127.0.0.1.

Run: python3 -m unittest discover -s tests/decide -v
"""
import http.server  # the stand-in for a Jev gateway
import importlib.machinery  # where a package name resolves, without importing it
import json  # fixtures and answers
import os  # settings
import pathlib  # paths
import shutil  # the stand-in package's folder goes away
import subprocess  # the command line
import sys  # the import path
import tempfile  # folders that vanish
import threading  # the stand-in server runs beside the test
import unittest  # the test runner
from unittest import mock  # settings and stand-ins

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
sys.path.insert(0, str(ROOT / "tests" / "decide"))  # the evaluation script
import decide as D  # noqa: E402  the interface
from decide import agent, jev, laya, rules, vega  # noqa: E402  the backends
import evaluate as E  # noqa: E402  the evaluation's builders and scoring

FIX = ROOT / "tests" / "decide" / "fixtures"  # the labelled fictional sets
CLEAN = {k: v for k, v in os.environ.items() if not k.startswith(("OFFEROWL_DECIDE", "OFFEROWL_JEV", "OFFEROWL_LAYA", "OFFEROWL_VEGA"))}  # no setting of the person leaks in


class Interface(unittest.TestCase):
    def test_the_default_backend_is_the_rules(self):  # nothing is switched on unless a person chooses it
        with mock.patch.dict(os.environ, CLEAN, clear=True):
            self.assertEqual(D.chosen(), "rules")
            self.assertEqual(D.decide("line_kind", [{"text": "Run the deploy platform"}])[0]["backend"], "rules")

    def test_a_mistyped_backend_is_refused(self):  # a typo must not pass silently for the rules
        with mock.patch.dict(os.environ, dict(CLEAN, OFFEROWL_DECIDE="laya2"), clear=True):
            with self.assertRaises(D.DecideUnavailable):
                D.chosen()

    def test_items_need_the_tasks_fields(self):  # every backend gets the same input shape
        with self.assertRaises(ValueError):
            D.decide("coverage", [{"line": "Kubernetes"}], backend="rules")  # no evidence
        with self.assertRaises(ValueError):
            D.decide("no_such_task", [{"text": "x"}], backend="rules")
        self.assertEqual(D.decide("claim", [], backend="rules"), [])  # nothing to decide

    def test_every_result_has_the_common_shape(self):  # label from the task, confidence, scores, backend, time
        out = D.decide("contradiction", [{"a": "It took 5 minutes.", "b": "It took 4 minutes."}], backend="rules")[0]
        self.assertEqual(set(out) >= {"label", "confidence", "scores", "backend", "ms"}, True)
        self.assertIn(out["label"], D.TASKS["contradiction"]["labels"])
        self.assertIsNone(out["confidence"])  # the rules give no probability

    def test_a_backend_cannot_return_a_label_the_task_lacks(self):  # the shape guard in result()
        with self.assertRaises(ValueError):
            D.result("claim", "maybe", None, "x", 0)

    def test_the_jev_row_says_inputs_leave_the_pc(self):  # the local-first fact is never hidden
        with mock.patch.dict(os.environ, CLEAN, clear=True):
            rows = {r["name"]: r for r in D.backend_info("en")}
        self.assertFalse(rows["jev"]["local"])
        self.assertFalse(rows["jev"]["ready"])
        self.assertIn("sent to", rows["jev"]["notice"])
        self.assertTrue(rows["rules"]["ready"])


class Rules(unittest.TestCase):
    def test_line_kind_reads_the_lines_own_words(self):  # duty, requirement, preferred without a heading
        self.assertEqual(rules.line_kind("Build service metrics and alerting"), "duty")
        self.assertEqual(rules.line_kind("3+ years building and running backend services"), "requirement")
        self.assertEqual(rules.line_kind("Experience running Kubernetes"), "requirement")
        self.assertEqual(rules.line_kind("Terraform experience is a plus"), "preferred")
        self.assertEqual(rules.line_kind("Kubernetes 운영 경험"), "requirement")
        self.assertEqual(rules.line_kind("결제 도메인 경험 우대"), "preferred")
        self.assertEqual(rules.line_kind("장애 대응 절차 수립과 당번 운영"), "duty")

    def test_coverage_uses_the_audits_thresholds(self):  # 60 percent strong, 30 percent weak
        line = "Kafka event pipelines between orders and settlement"
        self.assertEqual(rules.coverage(line, ["I ran Kafka event pipelines from orders to settlement."]), "strong")
        self.assertEqual(rules.coverage(line, ["Our order service used Kafka."]), "weak")
        self.assertEqual(rules.coverage(line, ["I wrote runbooks."]), "none")
        self.assertEqual(rules.coverage(line, []), "none")  # no evidence at all

    def test_claim_follows_factcheck(self):  # the same rule as the drafts
        self.assertEqual(rules.claim("Built the CI pipeline.", "I helped build the CI pipeline."), "overclaim")
        self.assertEqual(rules.claim("Built the user dashboard.", "사용자 대시보드를 구축했다"), "supported")

    def test_contradiction_signals(self):  # number, month, scope; and agreement
        self.assertEqual(rules.contradiction("a rollback from 30 minutes to about 5", "rollback from 30 to 4 minutes"), "contradiction")
        self.assertEqual(rules.contradiction("I started in September 2021.", "Gamma Corp (2021.08 - 2024.02)"), "contradiction")
        self.assertEqual(rules.contradiction("The structure already existed when I joined.", "Designed the hybrid structure."), "contradiction")
        self.assertEqual(rules.contradiction("되돌리기가 5분으로 줄었다", "되돌리기는 4분으로 줄었다"), "contradiction")
        self.assertEqual(rules.contradiction("I published order events to Kafka.", "Published order status changes as Kafka events."), "consistent")
        self.assertEqual(rules.contradiction("I worked there from July 2019.", "(2019.07 - 2022.02)"), "consistent")


class Agent(unittest.TestCase):
    def answers(self, labels):  # a stand-in for llm.run that answers every numbered item in the prompt
        calls = []  # every prompt the stand-in saw

        def run(task, prompt, **kw):
            calls.append((task, prompt, kw))
            nums = [line.split("]")[0][1:] for line in prompt.splitlines() if line.startswith("[")]  # the item numbers
            return {"decisions": [{"n": n, "label": labels[(int(n) - 1) % len(labels)], "confidence": 0.8} for n in nums]}
        return run, calls

    def test_items_go_in_batches_with_continuing_numbers(self):  # many items per call, one decision each
        run, calls = self.answers(["duty", "requirement"])
        items = [{"text": f"line number {i} " + "x" * 40} for i in range(10)]
        with mock.patch("llm.run", run), mock.patch("llm.chosen", lambda b=None: ("claude-code", "default")):
            out = agent.decide("line_kind", items, batch_chars=200)  # small batches on purpose
        self.assertGreater(len(calls), 1)  # split into several calls
        self.assertEqual([d["label"] for d in out], ["duty", "requirement"] * 5)  # the numbering continued across calls
        self.assertEqual(calls[0][2]["schema"]["properties"]["decisions"]["items"]["properties"]["label"]["enum"], list(D.TASKS["line_kind"]["labels"]))

    def test_only_the_tasks_fields_reach_the_model(self):  # gold labels and ids never go into the prompt
        run, calls = self.answers(["consistent"])
        with mock.patch("llm.run", run), mock.patch("llm.chosen", lambda b=None: ("claude-code", "default")):
            agent.decide("contradiction", [{"a": "x", "b": "y", "gold": "contradiction", "id": "secret-id"}])
        self.assertNotIn("secret-id", calls[0][1])
        self.assertNotIn("gold", calls[0][1])

    def test_the_cache_answers_a_rerun_without_a_call(self):  # reruns cost nothing
        run, calls = self.answers(["supported"])
        with tempfile.TemporaryDirectory() as tmp, mock.patch("llm.run", run), mock.patch("llm.chosen", lambda b=None: ("claude-code", "default")):
            first = agent.decide("claim", [{"claim": "Built it.", "evidence": "I built it."}], cache=tmp)
            again = agent.decide("claim", [{"claim": "Built it.", "evidence": "I built it."}], cache=tmp)
        self.assertEqual(len(calls), 1)
        self.assertFalse(first[0]["cached"])
        self.assertTrue(again[0]["cached"])

    def test_a_skipped_or_unknown_label_is_a_failure(self):  # a measured backend must not hide a bad answer
        with mock.patch("llm.run", lambda *a, **k: {"decisions": [{"n": "1", "label": "maybe", "confidence": 1}]}), \
                mock.patch("llm.chosen", lambda b=None: ("claude-code", "default")):
            with self.assertRaises(D.DecideUnavailable):
                agent.decide("claim", [{"claim": "a", "evidence": "b"}])


class FakeTokens:
    """A tokenizer stand-in: one id per word, so the layout can be read back."""
    cls, sep, mask, pad, mask_token = 1, 2, 3, 0, "[MASK]"

    def ids(self, text):
        return [100 + len(w) for w in text.split()]  # one token per word


class Laya(unittest.TestCase):
    def test_the_sequence_follows_the_published_layout(self):  # [CLS] question [SEP] [MASK] option ... [SEP] state [SEP]
        q = {"type": "choice", "instructions": "Pick one", "criteria": {"a": "first", "b": "second"}}
        ids, markers, cut = laya.build_sequence(FakeTokens(), "one two three", q, max_len=64, head_max_len=32)
        self.assertEqual(ids[0], 1)  # [CLS]
        self.assertEqual([ids[m] for m in markers], [3, 3])  # every option starts with its [MASK]
        self.assertEqual(ids.count(2), 3)  # after the question, after the options, after the state
        self.assertEqual(ids[-1], 2)  # the state is closed
        self.assertEqual(cut, 0)  # the state fit

    def test_a_long_state_is_cut_and_the_cut_is_reported(self):  # the start of the state is kept
        q = {"type": "choice", "instructions": "Pick", "criteria": {"a": None, "b": None}}
        ids, markers, cut = laya.build_sequence(FakeTokens(), "w " * 100, q, max_len=40, head_max_len=16)
        self.assertEqual(len(ids), 40)
        self.assertGreater(cut, 0)
        self.assertEqual(len(markers), 2)  # the options always fit before the state

    def test_options_render_as_trained(self):  # key: description, levels, false then true
        self.assertEqual(laya.render_options({"type": "choice", "criteria": {"x": "an x", "y": None}}), ["x: an x", "y"])
        self.assertEqual(laya.render_options({"type": "noul"})[0].split(":")[0], "false")

    def test_hangul_goes_to_the_multilingual_checkpoint(self):  # the English ones cannot read Korean
        with mock.patch.dict(os.environ, dict(CLEAN, OFFEROWL_LAYA_EN="english"), clear=True):
            self.assertEqual(laya.route("결제 도메인 경험"), "multilingual")
            self.assertEqual(laya.route("Payments experience"), "english")
        with mock.patch.dict(os.environ, dict(CLEAN, OFFEROWL_LAYA_MODEL="typed-decisions"), clear=True):
            self.assertEqual(laya.route("결제 도메인 경험"), "typed-decisions")  # a fixed choice wins

    def test_temperatures_are_clamped(self):  # a sharpening temperature below 0.5 is refused, as the maker's runtime does
        m = laya.Model("english")
        m.cfg = {"temperature": [1.0, 1.0, 1.0], "temperature_by_options": {"choice:11+": 0.1, "choice:2": 9.0}}
        self.assertEqual(m.temperature(0, 12), 0.5)
        self.assertEqual(m.temperature(0, 2), 5.0)
        self.assertEqual(m.temperature(0, 3), 1.0)

    def test_nothing_is_downloaded_without_permission(self):  # a missing model is an error, not a download
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, dict(CLEAN, OFFEROWL_LAYA_DIR=tmp), clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("no download")):
            with self.assertRaises(D.DecideUnavailable):
                D.decide("claim", [{"claim": "a", "evidence": "b"}], backend="laya", variant="multilingual")
            self.assertFalse(laya.status()["ready"])

    def test_coverage_takes_the_strongest_candidate(self):  # one candidate that shows the line is enough
        class Stand:
            def ask_many(self, pairs, batch=8):
                weak = {"choice": "weak", "probabilities": {"strong": 0.2, "weak": 0.7, "none": 0.1}, "confidence": 0.7, "cut": 0}
                strong = {"choice": "strong", "probabilities": {"strong": 0.9, "weak": 0.05, "none": 0.05}, "confidence": 0.9, "cut": 0}
                return [weak, strong, weak][:len(pairs)]
        with mock.patch.object(laya, "model", lambda name: Stand()):
            out = laya.decide("coverage", [{"line": "Kafka", "evidence": ["a", "b", "c"]}], variant="english")
        self.assertEqual(out[0]["label"], "strong")
        self.assertEqual(out[0]["best"], 1)
        self.assertEqual(out[0]["backend"], "laya:english")

    def test_every_variant_has_its_large_files_pinned(self):  # a later upload cannot replace a measured model
        for v, spec in laya.VARIANTS.items():
            self.assertIn(spec["weights"] if not spec["sub"] else spec["sub"] + "/" + spec["weights"], laya.SHA256, v)
            self.assertEqual(len(spec["repo"][1]), 40)  # a full commit hash


class Gateway(http.server.BaseHTTPRequestHandler):
    """A stand-in for a Jev gateway: records the request and answers in the shape of the gateway's API reference (its
    example: the choice, the model's own confidence, a probability per option that need not equal it, the served model
    and the usage). `mode` changes the answer: "full", "no_probs" (only the confidence, as the reference allows),
    "refusal" (the model declines the question), "busy_once" (a 429 with Retry-After first, then the answer)."""
    seen = []  # requests received
    mode = "full"  # the answer to give

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Gateway.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if Gateway.mode == "busy_once" and len(Gateway.seen) == 1:  # the first request finds the gateway busy
            return self.answer(429, {"error": {"code": 429, "message": "Rate limit exceeded"}}, {"Retry-After": "0"})
        q = body["questions"]["decision"]
        first = list(q["criteria"])[0]  # always the first option
        ans = {"type": "choice", "choice": first, "confidence": 0.75,  # the reference's own numbers: 0.75 stated, 0.84 as the probability
               "probabilities": {k: (0.84 if k == first else round(0.16 / (len(q["criteria"]) - 1), 4)) for k in q["criteria"]}}
        if Gateway.mode == "no_probs":  # probabilities are optional in the reference
            del ans["probabilities"]
        if Gateway.mode == "refusal":  # the reference's refusal answer: a type and nothing else
            ans = {"type": "refusal"}
        self.answer(200, {"answers": {"decision": ans}, "id": "gen-dec-test", "model": body["model"] + "-20261101", "provider": "TypeSafe",
                          "usage": {"cost": 0.00002, "input_tokens": 40, "output_tokens": 0}})

    def answer(self, code, obj, headers=None):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # quiet
        pass


class Jev(unittest.TestCase):
    def test_nothing_is_sent_without_the_key_and_the_consent(self):  # off by default
        with mock.patch.dict(os.environ, CLEAN, clear=True), mock.patch("urllib.request.urlopen", side_effect=AssertionError("sent")):
            with self.assertRaises(D.DecideUnavailable):
                D.decide("claim", [{"claim": "a", "evidence": "b"}], backend="jev")
        with mock.patch.dict(os.environ, dict(CLEAN, OFFEROWL_JEV_KEY="k"), clear=True), mock.patch("urllib.request.urlopen", side_effect=AssertionError("sent")):
            with self.assertRaises(D.DecideUnavailable):
                D.decide("claim", [{"claim": "a", "evidence": "b"}], backend="jev")
            self.assertIn("OFFEROWL_JEV_SEND", jev.status()["why"])

    def ask(self, task, items, mode="full"):
        """The decisions of a stand-in gateway answering in `mode`, and the requests it received."""
        srv = http.server.HTTPServer(("127.0.0.1", 0), Gateway)  # a free port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)  # cleanups run last first: stop serving, then close the socket
        self.addCleanup(srv.shutdown)
        Gateway.seen.clear()
        Gateway.mode = mode
        self.addCleanup(setattr, Gateway, "mode", "full")
        env = dict(CLEAN, OFFEROWL_JEV_KEY="test-key", OFFEROWL_JEV_SEND="1", OFFEROWL_JEV_URL=f"http://127.0.0.1:{srv.server_address[1]}")
        with mock.patch.dict(os.environ, env, clear=True):
            return D.decide(task, items, backend="jev"), Gateway.seen

    def test_the_request_has_the_documented_shape(self):  # model, state as an object, typed questions, bearer key
        out, seen = self.ask("contradiction", [{"a": "It took 5 minutes.", "b": "It took 4 minutes.", "id": "private"}])
        req = seen[0]
        self.assertEqual(req["path"], "/v1/systemone")
        self.assertEqual(req["auth"], "Bearer test-key")
        self.assertEqual(req["body"]["model"], jev.DEFAULT_MODEL)
        self.assertEqual(req["body"]["state"], {"statement A": "It took 5 minutes.", "statement B": "It took 4 minutes."})  # readable names
        self.assertNotIn("private", json.dumps(req["body"]))  # only the task's fields leave the PC
        self.assertEqual(req["body"]["questions"]["decision"]["type"], "choice")
        self.assertEqual(out[0]["label"], "contradiction")
        self.assertEqual(out[0]["backend"], "jev")
        self.assertAlmostEqual(out[0]["confidence"], 0.75)  # the confidence Jev states, never the choice's probability (0.84)
        self.assertAlmostEqual(out[0]["scores"]["contradiction"], 0.84)
        self.assertEqual(out[0]["model"], jev.DEFAULT_MODEL + "-20261101")  # the version that answered, for the record

    def test_a_posting_line_goes_as_text_and_coverage_with_all_its_evidence(self):
        _, seen = self.ask("line_kind", [{"text": "5+ years of Go."}])
        self.assertEqual(seen[0]["body"]["state"], "5+ years of Go.")
        _, seen = self.ask("coverage", [{"line": "Run Kubernetes", "evidence": ["Ran EKS clusters", "Wrote Helm charts"]}])
        self.assertEqual(seen[0]["body"]["state"], {"posting line": "Run Kubernetes", "evidence": ["Ran EKS clusters", "Wrote Helm charts"]})

    def test_an_answer_without_probabilities_keeps_its_confidence(self):  # the reference marks probabilities optional
        out, _ = self.ask("claim", [{"claim": "Built it.", "evidence": "I helped build it."}], mode="no_probs")
        self.assertEqual(out[0]["label"], "overclaim")
        self.assertAlmostEqual(out[0]["confidence"], 0.75)
        self.assertEqual(out[0]["scores"], {})

    def test_a_refusal_is_said_plainly(self):
        with self.assertRaisesRegex(D.DecideUnavailable, "declined to answer claim item 1"):
            self.ask("claim", [{"claim": "Built it.", "evidence": "I helped build it."}], mode="refusal")

    def test_a_busy_gateway_is_asked_again(self):  # a rate limit in the middle of a measurement does not end it
        out, seen = self.ask("claim", [{"claim": "Built it.", "evidence": "I helped build it."}], mode="busy_once")
        self.assertEqual(len(seen), 2)  # asked again after the wait
        self.assertEqual(out[0]["label"], "overclaim")
        self.assertEqual(jev.wait_of("0"), jev.WAIT[0])  # never a busy loop
        self.assertEqual(jev.wait_of("3600"), jev.WAIT[1])  # never a long stall
        self.assertEqual(jev.wait_of("Wed, 21 Oct 2026 07:28:00 GMT"), 2.0)  # a date: the usual wait


# A stand-in for the maker's package and the libraries Vega's loader imports, written to a folder put first on the path:
# the real reader is 1.7 GB, and the shape it answers in was read from the package itself (laya 0.4.31, vegaml 0.16.1).
FAKE = {
    "laya/__init__.py": (
        "CALLS = []\n"
        "class Agent:\n"
        "    def __init__(self, **kw):\n"
        "        CALLS.append(('init', kw))\n"
        "    def predict(self, state, questions):\n"
        "        CALLS.append(('predict', state, questions))\n"
        "        keys = list(questions['decision']['criteria'])\n"
        "        p = {k: (0.6 if i == 1 else round(0.4 / (len(keys) - 1), 4)) for i, k in enumerate(keys)}\n"
        "        return {'answers': {'decision': {'type': 'choice', 'probabilities': p, 'answer_confidence': 0.6, 'confidence': 0.2,\n"
        "                'prediction_set': keys[:2], 'abstain': True, 'unbound': False, 'readout': 'engine', 'choice': keys[1],\n"
        "                'route': 'review', 'route_reason': 'conformal set at alpha 0.1 holds 2 options'}}, 'calibrated': False}\n"),
    "vegaml/__init__.py": "",
    "torch/__init__.py": "THREADS = []\ndef set_num_threads(n):\n    THREADS.append(n)\n",
    "transformers/__init__.py": "",
    "huggingface_hub/__init__.py": ("CACHED = {'yes': True}\n"
                                    "def try_to_load_from_cache(repo, filename, revision=None):\n"
                                    "    return f'/cache/{repo}/{filename}' if CACHED['yes'] else None\n"),
    "huggingface_hub/constants.py": "HF_HUB_OFFLINE = False\n",
}


class Vega(unittest.TestCase):
    """The Vega backend against the stand-in package: what it hands the maker's loader, the state and question each
    item becomes, and how an answer is read."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-vega-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for rel, text in FAKE.items():  # the stand-in packages
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / rel).write_text(text, encoding="utf-8")
        modules = mock.patch.dict(sys.modules)  # every module imported here goes away afterwards, and the real ones come back
        modules.start()
        self.addCleanup(modules.stop)
        for n in [n for n in sys.modules if n.split(".")[0] in ("laya", "vegaml", "torch", "transformers", "huggingface_hub")]:
            del sys.modules[n]  # the stand-ins import instead
        path = mock.patch.object(sys, "path", [str(self.tmp)] + sys.path)  # the stand-ins first
        path.start()
        self.addCleanup(path.stop)
        vega._LOADED.clear()  # no reader from another test
        self.addCleanup(vega._LOADED.clear)

    def test_an_item_becomes_one_state_and_the_answer_keeps_its_route(self):
        with mock.patch.dict(os.environ, dict(CLEAN, OFFEROWL_VEGA_THREADS="3"), clear=True):
            self.assertTrue(vega.status()["ready"])
            out = D.decide("claim", [{"claim": "Built it.", "evidence": "I helped build it.", "id": "private"}], backend="vega")
        import huggingface_hub.constants as hf
        import laya as maker
        import torch
        init, (state, questions) = maker.CALLS[0][1], maker.CALLS[1][1:]  # ('init', kwargs), ('predict', state, questions)
        self.assertEqual(init["revision"], vega.ENGINE[1])  # the engine measured, never whatever is newest
        self.assertEqual(init["device"], "cpu")
        self.assertIs(init["vegaml"], True)  # the default reader
        self.assertEqual(torch.THREADS, [3])
        self.assertTrue(hf.HF_HUB_OFFLINE)  # files on this PC only: not even an update check leaves it
        self.assertEqual(state, {"claim": "Built it.", "evidence": "I helped build it."})  # never the id
        self.assertEqual(questions["decision"], laya.question("claim"))  # the question Laya gets
        r = out[0]
        self.assertEqual((r["label"], r["backend"]), ("supported", "vega:0.8b"))
        self.assertAlmostEqual(r["confidence"], 0.6)  # the chosen option's probability, as for Laya
        self.assertEqual((r["route"], r["abstain"], r["prediction_set"]), ("review", True, ["overclaim", "supported"]))

    def test_a_reader_that_is_not_on_this_pc_is_named_with_the_command_to_fetch_it(self):
        import huggingface_hub
        huggingface_hub.CACHED["yes"] = False
        with mock.patch.dict(os.environ, CLEAN, clear=True):
            self.assertIn("cli.py fetch vega", vega.status()["why"])
            with self.assertRaisesRegex(D.DecideUnavailable, "fetch vega"):
                D.decide("line_kind", [{"text": "Run the deploy platform"}], backend="vega")
            with mock.patch.dict(os.environ, {"OFFEROWL_VEGA_DOWNLOAD": "1"}):
                out = D.decide("line_kind", [{"text": "Run the deploy platform"}], backend="vega", reader_name="4b")
        import huggingface_hub.constants as hf
        import laya as maker
        self.assertFalse(hf.HF_HUB_OFFLINE)  # a download was asked for
        self.assertEqual(maker.CALLS[0][1]["vegaml"], "4b")
        self.assertEqual(maker.CALLS[1][1], "Run the deploy platform")  # a posting line as plain text
        self.assertEqual(out[0]["backend"], "vega:4b")

    def test_offerowls_own_laya_py_never_passes_for_the_makers_package(self):  # src/decide is on the path when cli.py runs
        shutil.rmtree(self.tmp / "laya")  # no maker's package at all
        with mock.patch.object(sys, "path", [vega.HERE] + sys.path):
            spec = importlib.machinery.PathFinder.find_spec("laya", vega.outside_path())
            self.assertTrue(spec is None or os.path.dirname(spec.origin) != vega.HERE)  # the maker's, or nothing
            if spec is None:  # no maker's package on this machine: the row says it is missing
                with mock.patch.dict(os.environ, CLEAN, clear=True):
                    self.assertIn("laya", vega.status()["why"])


class Fixtures(unittest.TestCase):
    def test_the_labelled_sets_are_well_formed(self):  # labels from the task, unique ids, both classes, both languages
        for name, task in (("claims_example.json", "claim"), ("pairs_example.json", "contradiction")):
            items = json.loads((FIX / name).read_text(encoding="utf-8"))["items"]
            self.assertEqual(len({it["id"] for it in items}), len(items), name)
            self.assertEqual({it["gold"] for it in items}, set(D.TASKS[task]["labels"]), name)
            for it in items:
                self.assertEqual(set(it["input"]), set(D.TASKS[task]["fields"]), it["id"])
            langs = {E.lang_of(*it["input"].values()) for it in items}
            self.assertTrue({"en", "ko"} <= langs | {"ko-en"} and ("ko" in langs or "ko-en" in langs), name)

    def test_posting_lines_take_their_kind_from_the_heading(self):  # the kind set agrees with the reviewed plan
        items = E.build_postings({"files": ["examples/cover/posting_en.md"]})
        plan = json.loads((ROOT / "examples" / "cover" / "plan_en.json").read_text(encoding="utf-8"))
        self.assertEqual([(it["input"]["text"], it["gold"]) for it in items], [(l["text"], l["kind"]) for l in plan["lines"]])

    def test_the_planted_claim_cases_are_read_from_tests_write(self):  # the same rows, not a copy that can drift
        items = E.build_cases({"file": "tests/write/test_claims.py"})
        self.assertGreaterEqual(len(items), 20)
        self.assertTrue(all(it["gold"] in ("overclaim", "supported") for it in items))

    def test_scores(self):  # accuracy, F1 and per-language numbers
        items = [{"gold": "contradiction", "lang": "en"}, {"gold": "consistent", "lang": "ko"}, {"gold": "contradiction", "lang": "ko"}]
        r = E.score("contradiction", items, ["contradiction", "contradiction", "consistent"], [1.0, 3.0, 2.0])
        self.assertEqual(r["acc"], 0.333)
        self.assertEqual(r["f1"], 0.5)
        self.assertEqual(r["by_lang"]["ko"]["acc"], 0.0)
        self.assertEqual(r["ms_p50"], 2.0)
        kit = [{"gold": "gap", "lang": "en", "input": {"line": "x", "evidence": []}}, {"gold": "covered", "lang": "en", "input": {"line": "y", "evidence": ["z"]}}]
        r = E.score("coverage", kit, ["weak", "strong"], [])
        self.assertEqual(r["acc"], 1.0)  # weak counts as a gap
        self.assertEqual((r["gaps_found"], r["flagged"], r["n_with_evidence"]), ("1/1", 1, 1))
        self.assertEqual(E.score("coverage", kit, ["gap", "gap"], [])["acc"], 0.5)  # a rule already written as gap or covered keeps its words


class Command(unittest.TestCase):
    def test_list_names_every_backend_and_the_jev_notice(self):  # the command a person runs first
        env = dict(CLEAN, OFFEROWL_LANG="en", OFFEROWL_LLM="none")  # no model is called by list
        r = subprocess.run([sys.executable, str(ROOT / "src" / "decide" / "cli.py"), "list"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in D.BACKENDS:
            self.assertIn(name, r.stdout)
        self.assertIn("inputs leave this PC", r.stdout)

    def test_messages_exist_in_both_languages(self):  # the same keys and placeholders, Korean in Korean
        from decide import cli
        self.assertEqual(sorted(cli.MSG["en"]), sorted(cli.MSG["ko"]))
        for k in ("ready", "not_ready", "stays", "leaves", "failed"):
            self.assertRegex(cli.MSG["ko"][k], "[가-힣]")
        self.assertEqual(sorted(jev.NOTICE), ["en", "ko"])

    def test_run_decides_a_file_of_items(self):  # the rules need no setup
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "items.json"
            f.write_text(json.dumps([{"text": "Experience running Kubernetes"}]), encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "src" / "decide" / "cli.py"), "run", "line_kind", str(f), "--backend", "rules"],
                               capture_output=True, text=True, env=dict(CLEAN, OFFEROWL_LANG="en"), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)[0]["label"], "requirement")


if __name__ == "__main__":
    unittest.main()
