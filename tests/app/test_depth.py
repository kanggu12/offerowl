#!/usr/bin/env python3
"""The depth review in the panel's API (apps/api/services/documents/depth.py): an edition reviewed, each finding answered (the answer becomes
evidence of its project), used (the rewrite through the canvas's own sentence path) or left (kept left on the same words),
the copy that went out compared, the review as the last stage of a draft, a review with no agent, the person's corrections
kept as rules of their pack, and the command-line twin `offerowl depth`. Everything is the fictional example person
(examples/sample_ko.json); the agent is the stand-in of apps/api/services/agent/standin.py or a function, never a model.

Run: python3 -m unittest tests/app/test_depth.py -v
"""
import contextlib  # the command's printed words, caught
import io  # in memory
import json  # files
import os  # the stand-in's switch
import pathlib  # paths
import shutil  # temporary folders
import sys  # the import path
import tempfile  # a data folder per test
import unittest  # the runner
from unittest import mock  # the environment of one test

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "src"))  # and the engine's modules
from apps.api.services.documents import depth as DEP  # noqa: E402  the module under test
from apps.api.services.documents import documents  # noqa: E402  the canvas's model
from apps.api.client import Client  # noqa: E402  the API in this process
from apps.api.core.workspace import read_json, write_json  # noqa: E402  files

GENERAL = "-general"  # the edition with no job


def stand_in(prompt_log: list | None = None, rated: dict | None = None):
    """A model for the review: alpha-1 gets a rewrite from its own evidence (block 2, which its words do not hold yet) and a
    question; every other item a question. `rated` gives some units the words that state each core part, so they get a
    verdict; the others answer with findings alone, as before verdicts. Its signature is the draft's ask."""
    def ask(task, prompt, required):
        if prompt_log is not None:  # the test reads what was sent
            prompt_log.append(prompt)
        ids = [line.split(" | ")[0][4:] for line in prompt.splitlines() if line.startswith("### ")]  # the units of this batch
        units = []
        for i in ids:  # each unit
            found = [{"code": "mechanism", "missing": "왜 효과가 났는지 없다", "way": "ask", "question": "무엇이 효과를 냈나요?"}]
            if i == "item:alpha-1":  # its ledger holds the retry policy the words leave general
                found.insert(0, {"code": "decision", "missing": "정한 정책이 무엇인지 없다", "way": "rewrite", "replaces": "멱등 키와 재시도 정책을 정했다.",
                                 "text": "요청마다 멱등 키를 두고, 재시도는 지수 간격으로 늘리되 상한을 두었다.", "ev": ["alpha-1#3"]})
            units.append({"id": i, "findings": found, **({"stated": rated[i]} if rated and i in rated else {})})  # rated, when the test says so
        return {"units": units}
    return ask


class Base(unittest.TestCase):
    """One data folder per test, the fictional example kept."""

    def world(self, agent: str = "none"):
        """The API on a fresh data folder with the example person's facts kept; agent 'none' or 'standin'."""
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-depth-"))  # the data folder
        self.addCleanup(shutil.rmtree, self.tmp, True)  # gone afterwards
        env = {"OFFEROWL_DESKTOP": str(self.tmp / "Desktop"), "OFFEROWL_LANG": "en"}  # no real Desktop; the command's words in English
        env.update({"OFFEROWL_PANEL_AGENT": "standin"} if agent == "standin" else {"OFFEROWL_PANEL_BACKEND": "none"})  # the stand-in agent, or none
        patch = mock.patch.dict(os.environ, env)  # this test's environment only
        patch.start()
        self.addCleanup(patch.stop)
        if agent != "standin":  # a stand-in left by another test must not count
            os.environ.pop("OFFEROWL_PANEL_AGENT", None)
        c = Client(self.tmp / "data")  # the API in this process
        self.addCleanup(lambda: c.settle(60))  # no task writes after the folder goes
        c.post("/api/v1/example", {"lang": "ko"})  # the fictional person
        c.wait("ingest")  # read
        c.post("/api/v1/facts/keep-all", {})  # every fact kept
        return c

    def review(self, c, ask=None, job=GENERAL):
        """A review of the edition through its route, with a stand-in model when given; the review as the page reads it."""
        c.api.tasks.depth_ask = ask  # the model's stand-in, or the backend in use
        c.post("/api/v1/jobs/depth", {"job": job, "lang": "ko"})  # the panel's key
        rec = c.wait(f"depth:{job}")  # its task
        self.assertEqual("done", rec["state"], rec)
        return c.get(f"/api/v1/jobs/{job}/depth", lang="ko")

    def finding(self, rec, unit, code):
        """One finding of a review."""
        u = next(u for u in rec["units"] if u["id"] == unit)
        return next(f for f in u["findings"] if f["code"] == code)


class ReviewTests(Base):
    """The review, and each of the three ways on."""

    def test_a_review_reads_every_printed_item_with_its_evidence(self):
        c = self.world()
        sent = []  # the prompts
        rec = self.review(c, stand_in(sent))
        self.assertEqual(["item:alpha-1", "item:alpha-2", "item:beta-1", "item:beta-2", "item:beta-3"], [u["id"] for u in rec["units"]])  # in print order
        self.assertTrue(rec["agent"])
        self.assertEqual(1, rec["calls"])  # the example fits one call
        self.assertEqual(["no_deck", "no_baseline"], rec["notes"])  # no deck made, nothing went out yet
        self.assertIn("[alpha-1#3]", sent[0])  # its evidence, with ids
        f = self.finding(rec, "item:alpha-1", "depth_decision")
        self.assertEqual(("rewrite", "open"), (f["way"], f["state"]))  # it passed the draft's checks against what it cites
        self.assertFalse(rec["stale"])
        self.assertTrue(read_json(c.api.tasks.ws.job_dir(GENERAL) / "depth.ko.json", None))  # kept with the edition

    def test_an_answer_becomes_evidence_of_its_project_and_one_undo_takes_it_back(self):
        c = self.world()
        rec = self.review(c, stand_in())
        f = self.finding(rec, "item:alpha-1", "depth_mechanism")
        got = c.post("/api/v1/jobs/depth/answer", {"job": GENERAL, "lang": "ko", "finding": f["id"], "text": "승인 경로만 따로 배포하자 배포가 승인을 멈추지 않게 됐다"})
        prof = c.api.tasks.facts.profile()  # the profile now
        alpha1 = next(p for r in prof["roles"] for p in r["projects"] if p.get("id") == "alpha-1")
        self.assertIn("- 승인 경로만 따로 배포하자 배포가 승인을 멈추지 않게 됐다", alpha1["body_md"])  # one more line of its ledger: the next draft can cite it
        import cover as C  # the units a draft cites
        import write_resume as W
        U = C.units_of(W.ledger_view(prof), "ko")
        self.assertTrue(any("배포가 승인을 멈추지 않게" in U["index"][b]["text"] for b in U["proj"]["alpha-1"]))  # a block of alpha-1
        model = documents.resume(c.api.tasks, "ko", "navy", None)  # the canvas
        s = next(v for k, v in model["sentences"].items() if v["text"].startswith("멱등 키"))  # a sentence of alpha-1
        self.assertTrue(any("배포가 승인을 멈추지 않게" in (e.get("quote") or "") for e in s["evidence"]))  # the canvas counts it as the item's evidence
        now = c.get(f"/api/v1/jobs/{GENERAL}/depth", lang="ko")
        self.assertEqual(("answered", got["cid"]), (self.finding(now, "item:alpha-1", "depth_mechanism")["state"], self.finding(now, "item:alpha-1", "depth_mechanism")["fact"]))
        c.post("/api/v1/undo", {})  # one undo: the fact and the finding together
        prof = c.api.tasks.facts.profile()
        alpha1 = next(p for r in prof["roles"] for p in r["projects"] if p.get("id") == "alpha-1")
        self.assertNotIn("배포가 승인을 멈추지", str(alpha1.get("body_md") or ""))
        self.assertEqual("open", self.finding(c.get(f"/api/v1/jobs/{GENERAL}/depth", lang="ko"), "item:alpha-1", "depth_mechanism")["state"])

    def test_a_rewrite_takes_its_sentence_s_place_through_the_canvas_s_checks(self):
        c = self.world()
        rec = self.review(c, stand_in())
        f = self.finding(rec, "item:alpha-1", "depth_decision")
        got = c.post("/api/v1/jobs/depth/apply", {"job": GENERAL, "lang": "ko", "finding": f["id"]})
        model = documents.resume(c.api.tasks, "ko", "navy", None)
        s = model["sentences"][got["sentence"]]  # the sentence that took the rewrite
        self.assertEqual("요청마다 멱등 키를 두고, 재시도는 지수 간격으로 늘리되 상한을 두었다.", s["text"])
        self.assertNotEqual("unsupported", s["state"])  # the canvas's evidence holds it: the export is not stopped
        now = c.get(f"/api/v1/jobs/{GENERAL}/depth", lang="ko")
        self.assertEqual("applied", self.finding(now, "item:alpha-1", "depth_decision")["state"])
        self.assertTrue(next(u for u in now["units"] if u["id"] == "item:alpha-1")["changed"])  # its words moved on since the review
        self.assertTrue(now["stale"])
        status, body, _ = c.router.handle("POST", "/api/v1/jobs/depth/apply", {"state": "0"}, {"job": GENERAL, "lang": "ko", "finding": f["id"]})
        self.assertEqual((400, "depth_no_rewrite"), (status, body["what"]))  # used already
        c.post("/api/v1/undo", {})  # one undo: the words and the finding
        model = documents.resume(c.api.tasks, "ko", "navy", None)
        self.assertTrue(any(v["text"] == "멱등 키와 재시도 정책을 정했다." for v in model["sentences"].values()))

    def test_a_question_or_a_changed_item_takes_no_rewrite(self):
        c = self.world()
        rec = self.review(c, stand_in())
        ask = self.finding(rec, "item:beta-2", "depth_mechanism")
        status, body, _ = c.router.handle("POST", "/api/v1/jobs/depth/apply", {"state": "0"}, {"job": GENERAL, "lang": "ko", "finding": ask["id"]})
        self.assertEqual((400, "depth_no_rewrite"), (status, body["what"]))  # a question has no words to use
        model = documents.resume(c.api.tasks, "ko", "navy", None)
        sid = next(k for k, v in model["sentences"].items() if v["text"] == "멱등 키와 재시도 정책을 정했다.")
        c.post("/api/v1/sentences/edit", {"sid": sid, "text": "멱등 키를 정했다.", "lang": "ko"})  # the person wrote it again since
        f = self.finding(rec, "item:alpha-1", "depth_decision")
        status, body, _ = c.router.handle("POST", "/api/v1/jobs/depth/apply", {"state": "0"}, {"job": GENERAL, "lang": "ko", "finding": f["id"]})
        self.assertEqual((400, "depth_changed"), (status, body["what"]))  # the sentence it stood for is gone
        status, body, _ = c.router.handle("POST", "/api/v1/jobs/depth/apply", {"state": "0"}, {"job": GENERAL, "lang": "ko", "finding": "fnothere"})
        self.assertEqual((400, "depth_finding"), (status, body["what"]))

    def test_a_left_finding_stays_left_until_its_words_change(self):
        c = self.world()
        rec = self.review(c, stand_in())
        f = self.finding(rec, "item:beta-3", "depth_mechanism")
        c.post("/api/v1/jobs/depth/leave", {"job": GENERAL, "lang": "ko", "finding": f["id"]})
        again = self.review(c, stand_in())  # reviewed again: the person's decision holds
        self.assertEqual("left", self.finding(again, "item:beta-3", "depth_mechanism")["state"])
        model = documents.resume(c.api.tasks, "ko", "navy", None)
        sid = next(k for k, v in model["sentences"].items() if v["text"].startswith("주문 장애 유형별"))
        c.post("/api/v1/sentences/edit", {"sid": sid, "text": "주문 장애 유형별 대응 절차를 문서로 만들었다.", "lang": "ko"})  # new words
        third = self.review(c, stand_in())
        self.assertEqual("open", self.finding(third, "item:beta-3", "depth_mechanism")["state"])  # asked again


class EditionTests(Base):
    """What a review is held against, and where it runs."""

    def test_with_no_agent_only_the_rules_run_and_say_so(self):
        c = self.world()
        model = documents.resume(c.api.tasks, "ko", "navy", None)
        sid = next(k for k, v in model["sentences"].items() if v["text"].startswith("주문 장애 유형별"))
        c.post("/api/v1/sentences/edit", {"sid": sid, "text": "주문 장애 유형별 대응 절차를 혼자 문서로 만들고 당번 교육에 썼다.", "lang": "ko"})  # a circumstance
        rec = self.review(c)  # the agent is off
        self.assertFalse(rec["agent"])
        self.assertEqual(0, rec["calls"])
        self.assertIn("no_agent", rec["notes"])
        f = self.finding(rec, "item:beta-3", "depth_circumstance")
        self.assertEqual(("ask", "rule", "혼자"), (f["way"], f["by"], f["quote"]))
        c.post("/api/v1/jobs/depth/answer", {"job": GENERAL, "lang": "ko", "finding": f["id"], "text": "장애 유형을 결제, 재고, 배송으로 나눠 유형마다 대응 순서를 정했다"})  # answered with no agent at all
        self.assertEqual("answered", self.finding(c.get(f"/api/v1/jobs/{GENERAL}/depth", lang="ko"), "item:beta-3", "depth_circumstance")["state"])

    def test_an_item_thinner_than_the_copy_that_went_out(self):
        c = self.world()
        t = c.api.tasks
        old = DEP.edition_profile(t, GENERAL, "ko")  # the edition as it went out, with a tool the words later lost
        alpha2 = next(p for r in old["roles"] for p in r["projects"] if p.get("id") == "alpha-2")
        alpha2["summary"] = "Argo CD 와 Helm 으로 팀 공용 배포 경로를 만들고, Kustomize 로 환경별 설정을 저장소 한 곳으로 모았다."
        kept = t.baseline_dir(GENERAL, "ko")  # where an export keeps its pages and, since 0.11.0, its words
        write_json(kept / "baseline.json", {"at": "2026-11-10 09:00", "why": "export", "pages": {"r": 2}})
        write_json(kept / "profile.json", old)
        rec = self.review(c)
        f = self.finding(rec, "item:alpha-2", "depth_thinner")
        self.assertEqual(["kustomize"], f["lost"])
        self.assertEqual({"why": "export", "at": "2026-11-10 09:00"}, rec["went_out"])
        self.assertNotIn("no_baseline", rec["notes"])

    @unittest.skipUnless(__import__("importlib").util.find_spec("PIL"), "Pillow draws and compares the kept pictures here")
    def test_an_export_keeps_the_words_beside_the_pages(self):
        c = self.world()
        t = c.api.tasks
        out = t.build_dir(GENERAL, "ko")  # a made edition, stood in for: its record, its profile, one page picture
        (out / "preview").mkdir(parents=True)
        from PIL import Image  # a page picture of the preview's size
        Image.new("RGB", (110, 156), "white").save(out / "preview" / "r-1.png")
        write_json(out / "build.json", {"at": "2026-11-10 09:00", "hashes": {}})
        write_json(out / "profile.json", {"schema": "resume-profile/0.1", "person": {"name": "Gildong Hong"}})
        (out / "resume.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")  # the made documents decide what the baseline keeps
        self.assertIsNotNone(t.keep_baseline(GENERAL, "ko", "export"))
        self.assertEqual("Gildong Hong", read_json(t.baseline_dir(GENERAL, "ko") / "profile.json", {})["person"]["name"])

    def test_the_review_is_the_last_stage_of_a_draft(self):
        c = self.world(agent="standin")  # the stand-in writes the resume and reviews it, through the OpenAI-compatible path
        c.post("/api/v1/jobs/write", {"job": GENERAL, "lang": "ko"})  # "Write the resume"
        rec = c.wait(f"write:{GENERAL}", timeout=300)
        self.assertEqual("done", rec["state"], rec)
        self.assertTrue(rec["result"]["depth"]["agent"])  # the draft's task ran the review as its last stage
        got = c.get(f"/api/v1/jobs/{GENERAL}/depth", lang="ko")
        self.assertEqual(got["counts"]["units"], rec["result"]["depth"]["counts"]["units"])
        self.assertGreater(got["counts"]["rewrites"], 0)  # the stand-in's rewrites from the evidence passed the checks
        self.assertGreater(got["counts"]["questions"], 0)
        asks = [f for u in got["units"] for f in u["findings"] if f["way"] == "ask"]  # a Korean edition is asked in Korean
        self.assertTrue(asks and all(any("가" <= ch <= "힣" for ch in f["question"] + f["missing"]) for f in asks), asks[:2])
        f = next(f for u in got["units"] for f in u["findings"] if f["way"] == "rewrite")
        out = c.post("/api/v1/jobs/depth/apply", {"job": GENERAL, "lang": "ko", "finding": f["id"]})  # a drafted sentence: the draft's link takes the rewrite's ids
        s = documents.resume(c.api.tasks, "ko", "navy", None)["sentences"][out["sentence"]]
        self.assertNotEqual("unsupported", s["state"], s)


class ReviewFindingsAPI(Base):
    """What an independent review of the harness found in the API, each held here (the fictional example only)."""

    def kept(self, c, units: list, lang: str = "ko", job: str = GENERAL) -> dict:
        """A kept review with the given units, as a review writes it (its own id, its notes and counts)."""
        rec = {"schema": "offerowl-depth/0.1", "lang": lang, "at": "2026-11-17 09:00", "agent": True, "rid": "r-kept", "notes": [], "counts": {}, "units": units}
        write_json(c.api.tasks.ws.job_dir(job) / f"depth.{lang}.json", rec)
        return rec

    @staticmethod
    def ask_unit(uid: str, pid: str | None, fid: str = "fq") -> dict:
        """One unit with one open question: a deck page (paired with pid, or with none) or an item."""
        return {"id": uid, "kind": "slide" if uid.startswith("slide:") else "item", "page": 3, "title": "승인 경로 분리", "where": "p.3", "text": "승인 경로 분리",
                "hash": "h", "reviewed": True, **({"pid": pid} if pid else {}), "verdict": "thin", "missing": ["hard", "mechanism"], "gate": True,
                "findings": [{"id": fid, "unit": uid, "code": "depth_hard", "missing": "무엇이 어려웠는지 없다", "way": "ask", "question": "무엇이 어려웠나요?",
                              "by": "agent", "state": "open", "verdict": "thin", "gate": True}]}

    @staticmethod
    def printed(prof: dict, words: str) -> list:
        """Where a profile prints some words of its own: a section's items, or a project's title or summary (a ledger line is evidence, never printed)."""
        out = [x for sec in prof.get("sections") or [] for x in sec.get("items") or [] if words in json.dumps(x, ensure_ascii=False)]
        return out + [p for r in prof.get("roles") or [] for p in r.get("projects") or [] if words in json.dumps([p.get("title"), p.get("summary")], ensure_ascii=False)]

    def refused(self, c, path: str, body: dict) -> str:
        """The API's refusal code for a request it must refuse."""
        status, got, _ = c.router.handle("POST", path, {"state": "0"}, body)
        self.assertEqual(400, status, got)
        return got["what"]

    def test_an_answer_never_prints_by_itself(self):  # a page that names no project, a project that is gone: refused; a named project: its ledger
        c = self.world()
        words = "승인 요청이 몰리면 배포가 승인 경로를 멈췄다"
        self.kept(c, [self.ask_unit("slide:3", None)])  # a page the review could not pair
        self.assertEqual("depth_no_project", self.refused(c, "/api/v1/jobs/depth/answer", {"job": GENERAL, "lang": "ko", "finding": "fq", "text": words}))
        prof = c.api.tasks.facts.profile()
        self.assertNotIn(words, json.dumps(prof, ensure_ascii=False))  # nowhere: no section of its own, no project of its own
        c.post("/api/v1/jobs/depth/answer", {"job": GENERAL, "lang": "ko", "finding": "fq", "text": words, "project": "alpha-1"})  # the person names its project
        prof = c.api.tasks.facts.profile()
        alpha1 = next(p for r in prof["roles"] for p in r["projects"] if p.get("id") == "alpha-1")
        self.assertIn("- " + words, alpha1["body_md"])  # one more line of that project's evidence
        self.assertFalse(self.printed(prof, words))  # and nothing prints it by itself
        self.kept(c, [self.ask_unit("item:gone-1", "gone-1", "fg")])  # an item whose project is gone since
        self.assertEqual("depth_no_project", self.refused(c, "/api/v1/jobs/depth/answer", {"job": GENERAL, "lang": "ko", "finding": "fg", "text": "다른 말"}))

    def test_a_submitted_application_takes_no_answer(self):  # as it takes no rewrite
        c = self.world()
        jid = c.post("/api/v1/jobs", {"company": "감마", "posting": (ROOT / "tests" / "app" / "fixtures" / "posting_ko.md").read_text(encoding="utf-8")})["job"]
        c.wait(f"analyze:{jid}")
        card = c.api.tasks.ws.job_dir(jid) / "status.json"  # its record
        st = json.loads(card.read_text(encoding="utf-8"))
        st["locked"] = {"at": "2026-11-07", "folder": "sent", "files": {}, "lang": "ko"}  # submitted, as the lock records it
        card.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        self.kept(c, [self.ask_unit("item:alpha-1", "alpha-1")], job=jid)
        before = c.api.tasks.facts.profile()
        self.assertEqual("locked", self.refused(c, "/api/v1/jobs/depth/answer", {"job": jid, "lang": "ko", "finding": "fq", "text": "승인 경로를 따로 배포했다"}))
        self.assertEqual(before, c.api.tasks.facts.profile())  # no fact was kept

    def test_an_english_edition_translated_from_korean(self):  # its sentences are a translation: no rewrite goes into the Korean fact; an answer goes to its project
        c = self.world(agent="standin")
        c.post("/api/v1/translate", {"job": GENERAL})  # the English profile, translated by the stand-in
        self.assertEqual("done", c.wait("translate")["state"])
        t = c.api.tasks
        src_before = json.dumps(t.facts.profile(), ensure_ascii=False)  # the Korean facts as they are
        rec = self.review_en(c)
        u = next(x for x in rec["units"] if x["id"] == "item:alpha-1")
        u["findings"].append({"id": "frw", "unit": u["id"], "code": "depth_decision", "missing": "x", "way": "rewrite", "by": "agent", "state": "open",
                              "rewrite": {"replaces": "", "text": "Each request carried an idempotency key and retries backed off.", "ev": ["alpha-1#3"], "names": {}}})
        write_json(t.ws.job_dir(GENERAL) / "depth.en.json", {k: v for k, v in rec.items() if k not in ("stale", "now", "projects")})
        self.assertEqual("edit_in_korean", self.refused(c, "/api/v1/jobs/depth/apply", {"job": GENERAL, "lang": "en", "finding": "frw"}))
        self.assertEqual(src_before, json.dumps(t.facts.profile(), ensure_ascii=False))  # the Korean source is untouched
        f = next(f for f in u["findings"] if f["code"] == "depth_mechanism")  # a question of the English item
        c.post("/api/v1/jobs/depth/answer", {"job": GENERAL, "lang": "en", "finding": f["id"], "text": "Approvals kept flowing once their path deployed on its own"})
        prof = t.facts.profile()  # the Korean facts
        alpha1 = next(p for r in prof["roles"] for p in r["projects"] if p.get("id") == "alpha-1")
        self.assertIn("- Approvals kept flowing once their path deployed on its own", alpha1["body_md"])  # its project's evidence, in the person's words
        self.assertFalse(self.printed(prof, "Approvals kept flowing"))  # nothing prints it by itself

    def review_en(self, c) -> dict:
        """The English edition reviewed with the test's stand-in, as the page reads it."""
        c.api.tasks.depth_ask = stand_in()
        c.post("/api/v1/jobs/depth", {"job": GENERAL, "lang": "en"})
        self.assertEqual("done", c.wait(f"depth:{GENERAL}")["state"])
        return c.get(f"/api/v1/jobs/{GENERAL}/depth", lang="en")

    def test_a_failed_review_says_its_language(self):  # the sheet of that language shows the band
        c = self.world()
        c.post("/api/v1/jobs/depth", {"job": GENERAL, "lang": "en"})  # no English profile yet
        got = c.wait(f"depth:{GENERAL}")
        self.assertEqual(("error", {"code": "needs_translation", "lang": "en"}), (got["state"], got["error"]))

    def test_a_review_that_finishes_keeps_what_was_done_meanwhile_and_undo_takes_back_only_its_step(self):
        c = self.world()
        first = self.review(c, stand_in())
        f = self.finding(first, "item:beta-1", "depth_mechanism")

        def answering(task, prompt, required):  # the person answers while the next review runs
            c.post("/api/v1/jobs/depth/answer", {"job": GENERAL, "lang": "ko", "finding": f["id"], "text": "정산과 알림이 각자 이벤트를 읽어 서로 기다리지 않았다"})
            return stand_in()(task, prompt, required)
        second = self.review(c, answering)
        self.assertEqual("answered", self.finding(second, "item:beta-1", "depth_mechanism")["state"])  # the review that finished kept the answer

        def named(task, prompt, required):  # a third review that also finds a name missing on beta-2
            got = stand_in()(task, prompt, required)
            for x in got["units"]:
                if x["id"] == "item:beta-2":
                    x["findings"].append({"code": "names", "missing": "캐시 이름이 없다", "way": "ask", "question": "어떤 캐시였나요?"})
            return got
        third = self.review(c, named)
        self.assertEqual("answered", self.finding(third, "item:beta-1", "depth_mechanism")["state"])  # carried over: its words did not change
        c.post("/api/v1/undo", {})  # the answer taken back, and only the answer
        now = c.get(f"/api/v1/jobs/{GENERAL}/depth", lang="ko")
        self.assertEqual(third["rid"], now["rid"])  # the newest review stays
        self.assertTrue(self.finding(now, "item:beta-2", "depth_names"))  # with what only it found
        self.assertEqual("open", self.finding(now, "item:beta-1", "depth_mechanism")["state"])  # the answer is gone, the gate open again

    def test_a_later_review_keeps_an_answered_gate_closed(self):  # answered, on the same words: done, as a left finding stays left
        c = self.world()
        rec = self.review(c, stand_in(rated={"item:beta-2": {"hard": "", "decision": "", "mechanism": ""}}))  # beta-2 thin
        gate = [f for f in next(u for u in rec["units"] if u["id"] == "item:beta-2")["findings"] if f["gate"]]
        for f in gate:  # each missing part answered
            c.post("/api/v1/jobs/depth/answer", {"job": GENERAL, "lang": "ko", "finding": f["id"], "text": "조회가 몰리는 시간에 읽기가 한도에 닿았다"})
        again = self.review(c, stand_in(rated={"item:beta-2": {"hard": "", "decision": "", "mechanism": ""}}))  # reviewed again: the same words
        self.assertEqual(0, again["now"]["gates"])  # the gate stays closed
        self.assertEqual({"answered"}, {f["state"] for f in next(u for u in again["units"] if u["id"] == "item:beta-2")["findings"] if f["gate"]})

    def test_a_rewrite_records_the_blocks_it_cites(self):  # never the whole project
        c = self.world()
        rec = self.review(c, stand_in())
        f = self.finding(rec, "item:alpha-1", "depth_decision")
        c.post("/api/v1/jobs/depth/apply", {"job": GENERAL, "lang": "ko", "finding": f["id"]})
        rested = [e.get("evidence") for e in c.api.tasks.facts.edits().values() if e.get("evidence")]
        self.assertEqual([["alpha-1#3"]], rested)  # the block it cites


class RuleTests(Base):
    """The person's corrections kept as rules of their pack: the harness's memory."""

    def test_a_correction_becomes_a_rule_every_draft_and_check_reads(self):
        c = self.world()
        self.assertEqual(("default", False), (c.get("/api/v1/style")["style"], c.get("/api/v1/style")["own"]))  # Offerowl's own rules at first
        got = c.post("/api/v1/style/rule", {"list": "retired", "row": ["승인 기능을 혼자 분리", "승인 기능을 팀과 분리", "the split was the team's"], "lang": "ko"})
        self.assertEqual({"style": "rules", "list": "retired", "lang": "ko", "rows": 1}, {k: got[k] for k in ("style", "list", "lang", "rows")})
        st = c.get("/api/v1/style")
        self.assertEqual(("rules", True), (st["style"], st["own"]))  # the person's own pack, chosen
        self.assertEqual([["승인 기능을 혼자 분리", "승인 기능을 팀과 분리", "the split was the team's"]], st["pack"]["claims"]["retired"]["ko"])
        import write_resume as W  # what a draft reads
        self.assertEqual(st["pack"]["claims"], W.load_style(c.api.tasks.style_spec())["claims"])
        c.post("/api/v1/style/rule", {"list": "proposal", "row": ["결제 표준", "제안|propos", "the standard was proposed"]})  # both languages
        self.assertEqual([["결제 표준", "제안|propos", "the standard was proposed"]], c.get("/api/v1/style")["pack"]["claims"]["proposal"])
        status, body, _ = c.router.handle("POST", "/api/v1/style/rule", {"state": "0"}, {"list": "shared", "row": ["(unclosed", "x", "y"]})
        self.assertEqual((400, "style"), (status, body["what"]))  # a pattern that does not compile never reaches a check
        status, body, _ = c.router.handle("POST", "/api/v1/style/rule", {"state": "0"}, {"list": "nope", "row": ["a", "b"]})
        self.assertEqual((400, "rule"), (status, body["what"]))
        c.post("/api/v1/undo", {})  # the last rule taken back
        self.assertNotIn("proposal", c.get("/api/v1/style")["pack"]["claims"])


class VerdictTests(Base):
    """Strong, adequate or thin through the routes and the command line: thin first, its missing parts the gate, counted again
    as the person acts on them."""

    RATED = {"item:alpha-1": {"hard": "승인 요청이 몰리면 배포가 승인 경로를 멈췄다", "decision": "멱등 키와 재시도 정책을 정했다", "mechanism": "승인 경로를 독립 배포 단위로"},  # all three: strong
             "item:beta-1": {"hard": "", "decision": "정산과 알림이 같은 흐름을 읽게 했다",  # what made it hard is not said
                             "mechanism": "주문 상태 변경을 Kafka 이벤트로 내보내 정산과 알림이 같은 흐름을 읽게 했다"},  # so one missing: adequate
             "item:beta-2": {"hard": "", "decision": "자주 읽는 주문 조회에 Redis 캐시를 두고", "mechanism": ""}}  # two missing: thin

    def rated_world(self):
        """The example with alpha-1's first sentence saying what made the work hard, as a person might write it again."""
        c = self.world()
        model = documents.resume(c.api.tasks, "ko", "navy", None)
        sid = next(k for k, v in model["sentences"].items() if v["text"].startswith("단일 애플리케이션"))
        c.post("/api/v1/sentences/edit", {"sid": sid, "text": "승인 요청이 몰리면 배포가 승인 경로를 멈췄다. ==승인 경로를 독립 배포 단위로== 분리했다.", "lang": "ko"})
        return c

    def test_thin_first_and_the_gate_closes_as_the_person_acts(self):
        c = self.rated_world()
        rec = self.review(c, stand_in(rated=self.RATED))
        self.assertEqual(["item:beta-2", "item:beta-1", "item:alpha-2", "item:beta-3", "item:alpha-1"], [u["id"] for u in rec["units"]])  # thin, adequate, no verdict, strong
        self.assertEqual(["thin", "adequate", None, None, "strong"], [u["verdict"] for u in rec["units"]])
        thin = rec["units"][0]
        self.assertEqual((["hard", "mechanism"], True), (thin["missing"], thin["gate"]))
        gate = [f for f in thin["findings"] if f["gate"]]
        self.assertEqual(["depth_hard", "depth_mechanism"], [f["code"] for f in gate])  # the model asked why it worked; what was hard got its own question
        self.assertEqual([], rec["units"][-1]["findings"])  # strong: the model's rewrite and question on it are dropped
        self.assertEqual({"open": 5, "gates": 1}, rec["now"])
        self.assertEqual((1, 1, 1, 2), tuple(rec["counts"][k] for k in ("thin", "adequate", "strong", "unrated")))
        c.post("/api/v1/jobs/depth/answer", {"job": GENERAL, "lang": "ko", "finding": gate[0]["id"], "text": "주문 조회가 몰리는 시간에 DB 읽기가 한도에 닿았다"})  # what was hard, in the person's words
        c.post("/api/v1/jobs/depth/leave", {"job": GENERAL, "lang": "ko", "finding": gate[1]["id"]})  # the person leaves the other
        now = c.get(f"/api/v1/jobs/{GENERAL}/depth", lang="ko")
        self.assertEqual({"open": 3, "gates": 0}, now["now"])  # the gate is passed: each missing part answered or left
        self.assertEqual("thin", now["units"][0]["verdict"])  # the verdict stays the review's until the next review

    def test_the_command_line_lists_thin_first_and_says_what_is_left(self):
        c = self.rated_world()
        self.review(c, stand_in(rated=self.RATED))
        c.settle(60)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = DEP.main(["show", "general", "--data", str(self.tmp / "data")])
        text = out.getvalue()
        self.assertEqual(0, code, err.getvalue())
        self.assertIn("verdicts: 1 thin (fill these first), 1 adequate, 1 strong, 2 with no verdict", text)
        self.assertIn("1 thin item(s) still miss a part", text)
        self.assertIn("- [thin] 주문 조회 캐시 도입 [", text)
        self.assertLess(text.index("[thin] 주문 조회 캐시 도입"), text.index("[adequate] 주문 이벤트 파이프라인 개발"))  # thin first
        self.assertIn(": not said: what made it hard, why it worked", text)
        self.assertIn("depth_hard (ask, open, fill first)", text)  # a thin item's missing part is the gate
        self.assertIn("- [adequate] 주문 이벤트 파이프라인 개발 [", text)  # one part not said
        self.assertIn("depth_hard (ask, open): ", text)  # an adequate item's missing part is a suggestion


class CommandLineTests(Base):
    """`offerowl depth`: the same routes from a shell, in this process."""

    def run_cli(self, *args) -> tuple[int, str, str]:
        """The command with its words caught."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = DEP.main([*args, "--data", str(self.tmp / "data")])
        return code, out.getvalue(), err.getvalue()

    def test_review_show_answer_and_leave(self):
        c = self.world()
        code, _, err = self.run_cli("show", "general")
        self.assertEqual(1, code)  # no review yet, said
        self.assertIn("no review yet", err)
        rec = self.review(c, stand_in())  # a review the panel made
        c.settle(60)
        code, out, _ = self.run_cli("show", "general")
        self.assertEqual(0, code)
        f = self.finding(rec, "item:beta-1", "depth_mechanism")
        self.assertIn(f"[{f['id']}] depth_mechanism (ask, open)", out)  # each finding with its id
        self.assertIn("question: 무엇이 효과를 냈나요?", out)
        code, out, _ = self.run_cli("answer", "general", f["id"], "정산과 알림이 같은 이벤트를 각자 읽어 서로 기다리지 않았다")
        self.assertEqual((0, True), (code, out.startswith("kept as a fact")))
        g = self.finding(rec, "item:beta-2", "depth_mechanism")
        code, out, _ = self.run_cli("leave", "general", g["id"])
        self.assertEqual((0, "left as it is"), (code, out.strip()))
        code, _, err = self.run_cli("apply", "general", g["id"])
        self.assertEqual(1, code)  # a question has no rewrite
        self.assertIn("depth_no_rewrite", err)
        code, out, _ = self.run_cli("review", "general")  # the agent is off: the rules alone, through the same route
        self.assertEqual(0, code)
        self.assertIn("depth review (ko): 5 units", out)


if __name__ == "__main__":
    unittest.main()
