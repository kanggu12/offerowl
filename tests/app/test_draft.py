#!/usr/bin/env python3
"""The resume drafted in the panel: written from the evidence, shown with what each sentence cites, edited, locked, written
again, used for one job or for all, and typeset. The agent is the stand-in of apps/api/standin.py."""
import hashlib  # the stamp of a translated profile
import json  # the stored files
import os  # the stand-in's switch
import pathlib  # paths
import shutil  # temporary folders
import sys  # the import path
import tempfile  # a data folder per class
import unittest  # the runner
import urllib.parse  # a job id in an address
from unittest import mock  # no PDF for the check's rule

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
from apps.api.client import Client  # noqa: E402  the API in this process
from core.schema import validate  # noqa: E402  the board's schema

POSTING = (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")  # a fictional posting
GENERAL = "-general"  # the edition with no job


class LedgerCards(unittest.TestCase):
    """A profile in the ledger form (another tool's export) shows its companies, titles, dates and evidence on the cards."""

    def test_the_career_block_and_the_evidence_text_fill_the_cards(self):
        from apps.api import facts as F  # the import of a profile file
        doc = json.loads((ROOT / "tests" / "write" / "fixtures" / "ledger_ko.json").read_text(encoding="utf-8"))  # a fictional ledger
        _, cands = F.import_profile(doc, "m1", "ledger_ko.json")
        role = next(c for c in cands if c["kind"] == "role")  # the first job held
        self.assertEqual(("나라클라우드(Nara Cloud)", "플랫폼 엔지니어", "2022.03 ~ 2024.08"), (role["org"], role["title"], role["period"]))  # from the career block
        proj = next(c for c in cands if c["kind"] == "project")  # its first project
        self.assertEqual("나라클라우드(Nara Cloud)", proj["org"])  # under its company
        self.assertIn("설계안을 만들어 제안했다", proj["statement"])  # the evidence text, not an empty card
        self.assertNotIn("- ", proj["statement"][:2])  # without the list's marks

    def test_ledger_text_drops_the_marks(self):
        from apps.api import facts as F
        md = "## 맡은 일\n\n- 설계안을 만들었다\n| 항목 | 값 |\n|---|---|\n| 기간 | 6개월 |\n<!-- note -->\n> 인용"
        self.assertEqual("맡은 일 설계안을 만들었다 항목 · 값 기간 · 6개월", F.ledger_text(md))  # sentences and rows, no marks


class OwnEnglishLists(unittest.TestCase):
    """An English list the person wrote apart from the Korean one (another count of rows) is facts of its own: each English
    sentence rests on its own row, and none is left without evidence (which stops the English edition's export)."""

    def test_a_translation_shares_the_rows_and_a_list_written_apart_does_not(self):
        from apps.api.facts import own_english  # the rule
        self.assertEqual([], own_english({"ko": [["가", "나"]], "en": [["A", "B"]]}))  # row for row: a translation
        self.assertEqual([0, 1], [i for i, _ in own_english({"ko": [["가", "나"]], "en": [["A", "B"], ["C", "D"]]})])  # written apart
        self.assertEqual([], own_english([["가", "나"]]))  # one list for both editions
        self.assertEqual([], own_english({"en": [["A", "B"]]}))  # English only: the plain rules apply

    def test_each_english_row_rests_on_its_own_words(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-own-en-"))  # a workspace of its own
        self.addCleanup(shutil.rmtree, tmp, True)  # gone afterwards
        doc = json.loads((ROOT / "examples" / "sample_full_ko.json").read_text(encoding="utf-8"))  # the fictional person
        ko = [["결제 플랫폼", "승인 경로를 나눠 배포 시간을 줄였다"], ["운영", "장애를 원인까지 추적했다"]]  # two Korean strengths
        en = [["Payments", "Split the authorization path to deploy it alone"], ["Incidents", "Traced outages to their cause"],
              ["Leadership", "Led a team of four engineers"]]  # three English ones, written apart
        doc["competencies"] = {"ko": ko, "en": en}  # as a ledger with its own English edition keeps them
        f = tmp / "profile_in.json"  # the file the person drops
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with mock.patch.dict(os.environ, {"OFFEROWL_PANEL_BACKEND": "none"}):  # no agent: a profile is read as it is
            c = Client(tmp / "data")  # the API
            rec = c.post("/api/v1/materials/file", {"path": str(f)})["material"]  # dropped
            c.post("/api/v1/materials/read", {"ids": [rec["id"]]})  # read
            c.wait("ingest")  # done
            c.post("/api/v1/facts/keep-all", {})  # every fact kept
            src = c.api.tasks.ws.path("profile", "profile.json")  # the kept profile
            mine = json.loads(src.read_text(encoding="utf-8"))  # stands for its translation: the English list is already there
            mine["_from"] = hashlib.sha256(src.read_bytes()).hexdigest()[:16]  # made from this profile
            (src.parent / "profile.en.json").write_text(json.dumps(mine, ensure_ascii=False), encoding="utf-8")  # beside it
            m_en = c.get("/api/v1/documents/resume", lang="en")  # the English canvas
            m_ko = c.get("/api/v1/documents/resume", lang="ko")  # the Korean one
        for i, (head, _) in enumerate(en):  # every English strength
            s = m_en["sentences"][f"competencies.{i}"]  # its sentence
            self.assertEqual("ok", s["state"], s)  # with evidence, the third one too
            self.assertEqual([head], [e["where"] for e in s["evidence"]])  # its own row, not the Korean row of the same number
        for i, (head, _) in enumerate(ko):  # the Korean edition keeps its own
            self.assertEqual([head], [e["where"] for e in m_ko["sentences"][f"competencies.{i}"]["evidence"]])
        self.assertNotIn("competencies.2", m_ko["sentences"])  # and has two


class EditionItems(unittest.TestCase):
    """An item written for one language ("lang": a skills row, a list section, a project) shows on that edition's canvas only,
    as src/profile_loader.js prints it: the canvas never shows a row the PDF leaves out."""

    def test_each_canvas_shows_its_own_language_s_items(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-lang-items-"))  # a workspace of its own
        self.addCleanup(shutil.rmtree, tmp, True)
        doc = json.loads((ROOT / "examples" / "sample_full_ko.json").read_text(encoding="utf-8"))  # the fictional person
        doc["skills"] = [{"category": "언어", "items": ["Go", "Python"], "lang": "ko"}, {"category": "Languages", "items": ["Go", "Python"], "lang": "en"},
                         {"category": "Tools", "items": ["Git"]}]  # one row per edition, one for both
        doc["sections"] = [{"title": "자격", "items": ["가상 자격 1급"], "lang": "ko"}, {"title": "Certifications", "items": ["A fictional licence"], "lang": "en"}]
        f = tmp / "profile_in.json"  # the file the person drops
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with mock.patch.dict(os.environ, {"OFFEROWL_PANEL_BACKEND": "none"}):  # no agent: a profile is read as it is
            c = Client(tmp / "data")
            c.post("/api/v1/materials/read", {"ids": [c.post("/api/v1/materials/file", {"path": str(f)})["material"]["id"]]})  # dropped and read
            c.wait("ingest")
            c.post("/api/v1/facts/keep-all", {})  # kept
            src = c.api.tasks.ws.path("profile", "profile.json")  # the kept profile, standing for its own translation
            mine = json.loads(src.read_text(encoding="utf-8"))
            mine["_from"] = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
            (src.parent / "profile.en.json").write_text(json.dumps(mine, ensure_ascii=False), encoding="utf-8")
            ko, en = (c.get("/api/v1/documents/resume", lang=lang) for lang in ("ko", "en"))  # both canvases
        rows = lambda m: [r["category"] for b in m["blocks"] if b["type"] == "skills" for r in b["rows"]]  # the skills table's rows
        self.assertEqual(["언어", "Tools"], rows(ko))  # its own row and the shared one
        self.assertEqual(["Languages", "Tools"], rows(en))
        heads = lambda m: [b.get("title") for b in m["blocks"] if b["type"] == "section"]  # the section headings
        self.assertIn("자격", heads(ko)); self.assertNotIn("Certifications", heads(ko))  # never the other edition's list
        self.assertIn("Certifications", heads(en)); self.assertNotIn("자격", heads(en))


class SlideParts(unittest.TestCase):
    """A drafted project's slide (apps/api/drafts.py slide_parts) has words in every language its summary has."""

    def test_a_language_that_does_not_split_keeps_its_summary_as_the_lede(self):
        from apps.api.drafts import slide_parts  # the function under test
        project = {"summary": {"ko": "결제 승인 경로를 나눴다. 승인만 따로 배포하게 했다. 배포가 9분으로 줄었다.",  # three parts in Korean
                               "en": "Split the authorization path out."}}  # one sentence left in English (the others failed a check)
        draft = {"evidence": [{"lang": "ko", "at": "project.p1.summary", "text": t, "part": k} for t, k in
                              (("결제 승인 경로를 나눴다.", "scope"), ("승인만 따로 배포하게 했다.", "decision"), ("배포가 9분으로 줄었다.", "result"))]}
        got = slide_parts(draft, "p1", project)  # the slide's parts
        self.assertEqual({"ko", "en"}, set(got["lede"]) & set(got["cards"]))  # both languages, so the English edition has its words
        self.assertEqual("Split the authorization path out.", got["lede"]["en"])  # the English summary leads
        self.assertEqual([], got["cards"]["en"])  # with no cards
        self.assertEqual(2, len(got["cards"]["ko"]))  # the Korean slide as before


class Draft(unittest.TestCase):
    """One workspace per test, with the fictional person's facts kept and the stand-in on."""

    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ("OFFEROWL_PANEL_AGENT", "OFFEROWL_PANEL_BACKEND", "OFFEROWL_LLM", "OFFEROWL_LLM_URL", "OFFEROWL_LLM_MODEL")}  # put back afterwards
        os.environ["OFFEROWL_PANEL_AGENT"] = "standin"  # no real model
        os.environ.pop("OFFEROWL_PANEL_BACKEND", None)  # a class run earlier must not count
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-draft-"))  # the data folder
        self.c = Client(self.tmp)  # the API
        self.c.post("/api/v1/example", {"lang": "ko"})  # the fictional person
        self.c.wait("ingest")  # read
        self.c.post("/api/v1/facts/keep-all", {})  # every fact kept

    def tearDown(self):
        try:
            self.c.settle(120)  # a job's analysis still running wrote into the folder again after it was removed
        finally:  # a task that hangs fails the test, and the folder and environment are put back all the same
            for k, v in self.env.items():  # the environment as it was
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            shutil.rmtree(self.tmp, ignore_errors=True)  # nothing left

    def resume(self, job=None, lang="ko"):
        """The canvas's model."""
        return self.c.get("/api/v1/documents/resume", lang=lang, **({"job": job} if job else {}))

    def write(self, job=GENERAL):
        """Write the resume, and return the task's record."""
        started = self.c.post("/api/v1/jobs/write", {"job": job, "lang": "ko"})  # the task starts
        self.assertTrue(started["started"])  # it was not running
        return self.c.wait(started["task"])  # done or refused

    def stored(self, job=GENERAL):
        return json.loads((self.tmp / "workspace" / "jobs" / job / "draft.json").read_text(encoding="utf-8"))  # as saved

    def first(self, m):
        """A drafted sentence of a project, in print order, with its id."""
        for b in m["blocks"]:  # in print order
            for p in b.get("projects") or []:  # a role's projects
                for sid in p["sids"]:  # its sentences
                    if m["sentences"][sid].get("drafted"):  # one the draft wrote
                        return sid, m["sentences"][sid]
        self.fail("no drafted sentence")

    def test_written_with_what_each_sentence_cites(self):
        before = self.resume()  # the facts' own sentences
        self.assertIsNone(before["draft"])  # no draft yet
        self.assertEqual("done", self.write()["state"])  # written
        m = self.resume()  # the draft on the canvas
        self.assertEqual(0, m["counts"]["unsupported"])  # every sentence stands on its evidence
        self.assertTrue(m["draft"]["own"] and m["draft"]["general"] and not m["draft"]["stale"])  # the general edition's own, and current
        self.assertGreater(m["draft"]["counts"]["written"], 0)  # the counts the inspector shows
        sid, rec = self.first(m)  # a sentence it wrote
        self.assertEqual("ok", rec["state"])  # as the checks passed it
        self.assertTrue(rec["evidence"], rec)  # its evidence
        self.assertTrue(rec["evidence"][0]["quote"])  # the source's own words
        self.assertEqual("sample_ko.json", rec["evidence"][0]["file"])  # and the file they came from

    def test_a_job_without_its_own_uses_the_general_one(self):
        self.write()  # the general edition
        jid = self.c.post("/api/v1/jobs", {"company": "감마", "posting": POSTING})["job"]  # a job
        self.c.wait(f"analyze:{jid}")  # ordered by words
        m = self.resume(jid)  # its canvas
        self.assertTrue(m["draft"]["general"] and not m["draft"]["own"])  # the general draft
        self.assertEqual("done", self.write(jid)["state"])  # written for the job
        m = self.resume(jid)  # now its own
        self.assertTrue(m["draft"]["own"] and not m["draft"]["general"])  # kept with the job
        self.assertTrue((self.tmp / "workspace" / "jobs" / jid / "draft.json").is_file())  # in its folder
        self.assertTrue(self.stored(jid)["_draft"]["posting"]["sha"])  # written for that posting

    def test_the_draft_a_job_draws_is_found_without_reading_it_again(self):
        # the state asks every job which draft it draws at every poll: decided from a check kept while the file is unchanged,
        # and a build still goes stale when the general draft is rewritten or the job gets its own
        from apps.api import drafts as D  # the draft's owner
        from apps.api.tasks import file_hash  # the stamp a build keeps
        t = self.c.api.tasks
        jid = self.c.post("/api/v1/jobs", {"company": "감마클라우드", "role": "백엔드 플랫폼 엔지니어",
                                           "posting": "결제 승인 서비스와 Kubernetes 배포 플랫폼을 운영할 백엔드 엔지니어를 찾습니다."})["job"]
        self.assertEqual(("", None), (t.draft_stamp(jid), D.owner(t, jid)))  # no draft yet
        self.write(GENERAL)  # the general edition's draft
        general = self.tmp / "workspace" / "jobs" / GENERAL / "draft.json"
        first = t.draft_stamp(jid)
        self.assertEqual((GENERAL, file_hash(general)), (D.owner(t, jid), first))  # the job draws the general one
        d = json.loads(general.read_text(encoding="utf-8"))
        d["_draft"]["rewritten"] = True  # the general draft written again
        general.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        self.assertNotEqual(first, t.draft_stamp(jid))  # a build made before it is stale
        own = self.tmp / "workspace" / "jobs" / jid / "draft.json"
        own.write_text(json.dumps({"_draft": {"langs": ["ko"]}}), encoding="utf-8")  # the job's own draft
        self.assertEqual((jid, jid), (D.owner(t, jid), D.load(t, jid)[1]))  # its own first, as load() finds it
        own.write_text(json.dumps({"no": "draft"}), encoding="utf-8")  # a file that is no draft
        self.assertEqual((GENERAL, GENERAL), (D.owner(t, jid), D.load(t, jid)[1]))  # the general one again

    def test_an_edit_goes_into_the_draft_and_is_checked_again(self):
        self.write()  # written
        sid, rec = self.first(self.resume())  # a sentence it wrote
        same = rec["text"].replace("==", "").rstrip(".") + " 그대로"  # its own words and nothing the evidence must back
        got = self.c.post("/api/v1/sentences/edit", {"sid": sid, "text": same, "lang": "ko", "job": GENERAL})["sentence"]  # saved
        self.assertEqual("edited", got["state"], got)  # still inside the evidence
        self.assertIn(same, json.dumps(self.stored(), ensure_ascii=False))  # in the stored draft
        worse = rec["text"].replace("==", "").rstrip(".") + " 처리량을 97% 높였다"  # a number the evidence does not have
        got = self.c.post("/api/v1/sentences/edit", {"sid": sid, "text": worse, "lang": "ko", "job": GENERAL})["sentence"]  # saved
        self.assertEqual("unsupported", got["state"], got)  # marked
        self.assertIn("number", [i["code"] for i in got["issues"]])  # with the reason
        self.c.post("/api/v1/undo", {})  # back
        self.assertEqual("edited", self.resume()["sentences"][sid]["state"])  # one undo step

    def test_a_locked_sentence_stays_through_a_new_draft(self):
        self.write()  # written
        sid, rec = self.first(self.resume())  # a sentence it wrote
        self.c.post("/api/v1/sentences/lock", {"sid": sid, "locked": True, "lang": "ko", "job": GENERAL})  # locked
        m = self.resume()  # the canvas
        self.assertTrue(m["sentences"][sid]["locked"])  # marked
        with self.assertRaises(RuntimeError):  # edits are refused
            self.c.post("/api/v1/sentences/edit", {"sid": sid, "text": "다른 말", "lang": "ko", "job": GENERAL})
        self.assertEqual("done", self.write()["state"])  # written again
        m = self.resume()  # the new draft
        kept = [s for s in m["sentences"].values() if s["locked"]]  # what stayed locked
        self.assertEqual([rec["text"]], [s["text"] for s in kept])  # the same words
        self.assertTrue(kept[0]["evidence"])  # with the evidence it had

    def test_a_changed_fact_marks_what_rested_on_it(self):
        self.write()  # written
        m = self.resume()  # the canvas
        self.assertFalse(m["draft"]["stale"])  # current
        rows = self.c.get("/api/v1/facts")["rows"]  # the facts (the state carries only their counts)
        cid = next(c["cid"] for c in rows if c.get("kind") == "project")  # one project's fact
        self.c.post("/api/v1/facts/decide", {"cid": cid, "action": "edit", "fields": {"title": "다르게 고친 제목"}})  # changed
        m = self.resume()  # the canvas now
        self.assertTrue(m["draft"]["stale"])  # the page offers to write it again
        self.c.post("/api/v1/facts/decide", {"cid": cid, "action": "drop"})  # the fact is gone
        m = self.resume()  # the canvas now
        self.assertGreater(m["counts"]["unsupported"], 0)  # what rested on it is marked, and stops the export

    def test_the_edition_is_typeset_from_the_draft(self):
        self.write()  # written
        api = self.c.api  # the object behind the client
        out = api.tasks.edition_inputs(GENERAL, "ko")  # what the typesetting reads
        prof = json.loads((out / "profile.json").read_text(encoding="utf-8"))  # the edition's profile
        self.assertEqual(self.stored()["summary"]["headline"], prof["summary"]["headline"])  # the draft's sentences
        self.assertEqual("길동", prof["person"]["name"][-2:])  # the facts' name

    def test_the_document_check_reads_a_drafted_profile(self):
        self.write()  # written
        out = self.c.api.tasks.edition_inputs(GENERAL, "ko")  # the edition's inputs
        prof = json.loads((out / "profile.json").read_text(encoding="utf-8"))  # titles as language pairs
        sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules
        import check_documents as CD  # the check every edition goes through
        printed = []  # what the PDF would hold: the titles of the printed projects, in Korean
        for r in prof["roles"]:  # each role
            printed.append(r["org"])  # its name
            printed += [p["title"]["ko"] if isinstance(p["title"], dict) else p["title"] for p in r["projects"] if p.get("resume") is not False]  # its printed projects
        with mock.patch.object(CD.P, "text", return_value="\n".join(printed)), mock.patch.object(CD.CR, "footer_clearance", return_value=[]), \
                mock.patch.object(CD.CR, "number_unit_split", return_value=[]):  # no PDF needed for this rule
            bad = CD.check_resume(prof, "x.pdf", "default", 3)  # the same call the build makes
        self.assertEqual([], [x for x in bad if "project" in x.lower() or "프로젝트" in x])  # every printed project was found, and a left-out one is not asked for

    def test_a_sentence_of_a_longer_linked_text_has_its_evidence(self):
        self.write()  # written
        d = self.stored()  # the stored draft
        for x in d["evidence"]:  # the introduction's link
            if x["at"] == "summary.intro" and x["lang"] == "ko":  # one text
                x["text"] = "첫 문장은 사실 그대로 적었습니다. 둘째 문장도 사실 그대로 적었습니다."  # two sentences under one link
        d["summary"]["intro"]["ko"] = "첫 문장은 사실 그대로 적었습니다. 둘째 문장도 사실 그대로 적었습니다."  # as an agent writes an introduction
        (self.tmp / "workspace" / "jobs" / GENERAL / "draft.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")  # saved
        m = self.resume()  # the canvas
        self.assertTrue(m["sentences"]["summary.intro.s1"].get("drafted"), m["sentences"]["summary.intro.s1"])  # the second sentence is the draft's too
        got = self.c.post("/api/v1/sentences/edit", {"sid": "summary.intro.s1", "text": "둘째 문장을 고쳐 적었습니다.", "lang": "ko", "job": GENERAL})["sentence"]  # one of the two
        self.assertEqual("둘째 문장을 고쳐 적었습니다.", got["text"])  # changed
        self.assertTrue(self.resume()["sentences"]["summary.intro.s0"].get("drafted"))  # the first still has its link
        self.assertIn("첫 문장은 사실 그대로 적었습니다.", self.stored()["summary"]["intro"]["ko"])  # and its words

    def test_a_letter_leaves_nothing_in_the_engine_s_folder(self):
        short = self.c.api.tasks.short(GENERAL)  # as the engine names it, the edition's outputs share this
        planted = ROOT / "output" / "_inputs" / f"owl_cover_{short}_ko.planted.json"  # a working copy, as typesetting a letter leaves them
        planted.parent.mkdir(parents=True, exist_ok=True)  # a clean checkout has no such folder yet
        planted.write_text("{}", encoding="utf-8")  # there now
        out = self.c.api.tasks.edition_inputs(GENERAL, "ko")  # the edition's inputs
        self.c.api.tasks._cover(GENERAL, "ko", out, render=False)  # a letter on its own, as tailoring writes it
        self.assertFalse(planted.exists())  # gone with the rest

    def test_words_that_look_like_a_path_stay_words_on_a_slide(self):
        from apps.api.tasks import live_html  # the page for the frame
        secret = self.tmp / "secret.png"  # a picture's name, outside where pictures come from
        secret.write_bytes(b"not for the page")  # its bytes
        spaced = self.tmp / "with space"  # a folder a person may have
        spaced.mkdir()  # there
        (spaced / "logo.png").write_bytes(b"logo bytes")  # a picture in it
        page = (f'<head></head><p>see file://{secret} and file:///etc/hostname</p><img src="file://{spaced}/logo.png">'  # text, and a picture the page asks for
                f'<img src="file://{secret}"><img src="file:///etc/hostname"><script>alert(1)</script>')  # pictures it must not read
        out = live_html(page, (spaced,))  # the frame's page
        self.assertIn(f"see file://{secret} and file:///etc/hostname", out)  # the words stay words
        self.assertIn("data:image/png;base64,bG9nbyBieXRlcw==", out)  # the picture from an allowed folder, spaces and all
        self.assertNotIn("bm90IGZvciB0aGUgcGFnZQ==", out)  # a file from elsewhere is not read
        self.assertEqual(2, out.count('src=""'))  # and draws nothing
        self.assertNotIn("<script", out)  # the frame runs nothing

    def test_the_canvas_has_the_pictures_the_pdf_prints(self):
        # 2026-11-09: the live resume showed no photo, no timeline, no hierarchy figure and no logos, all of which the PDF
        # prints; the model now names them, the panel serves them, and the contacts are the printed header's rows
        import io  # a photo made here
        from PIL import Image  # its pixels
        buf = io.BytesIO()
        Image.new("RGB", (30, 40), "#335577").save(buf, "PNG")  # a stand-in photo, no person in it
        self.c.api.set_photo(buf.getvalue())  # on the resume
        m = self.resume(GENERAL)  # the canvas
        self.assertTrue(m["person"]["photo"].startswith("/api/v1/photo?v="))  # in the name band
        figs = {b["key"]: b for b in m["blocks"] if b["type"] == "figure"}  # the figures, by name
        self.assertIn("timeline", figs)  # the overview timeline
        at = m["blocks"].index(figs["timeline"])  # where it sits
        self.assertEqual(("section", "overview"), (m["blocks"][at - 1]["type"], m["blocks"][at - 1].get("key")))  # right after the overview heading, as printed
        png = self.c.get(figs["timeline"]["src"].split("?")[0])  # served by the panel
        self.assertEqual(b"\x89PNG", png[:4])  # a picture
        self.assertEqual(figs["timeline"]["w"], int.from_bytes(png[16:20], "big"))  # of the size the model gave
        rows = [r for b in m["blocks"] if b["type"] in ("career", "education") for r in b["rows"]]  # the tables
        for r in rows:  # each logo the model names is one the panel has
            if r.get("logo"):
                self.assertEqual(b"\x89PNG", self.c.get(r["logo"].split("?")[0])[:4])
        with self.assertRaises(RuntimeError):  # a picture this resume does not have
            self.c.get(f"/api/v1/jobs/{GENERAL}/figures/ko/logo_nothing.png")
        career = next(b for b in m["blocks"] if b["type"] == "career")["rows"]  # the career summary
        self.assertTrue(all("role" in r and "department" in r for r in career))  # the printed table's own columns
        self.assertNotIn("live", [p.name for p in (self.tmp / "workspace" / "jobs" / GENERAL).iterdir()] if (self.tmp / "workspace" / "jobs" / GENERAL).is_dir() else [])  # nothing left on disk
        self.c.post("/api/v1/settings", {"photo": False})  # taken off the resume
        self.assertNotIn("photo", self.resume(GENERAL)["person"])  # and off the canvas

    def test_a_role_that_prints_nowhere_is_not_on_the_canvas(self):
        # a ledger's note of a company that has neither a name nor a career block: src/profile_loader.js leaves it out of the
        # PDF, and the canvas showed it as an empty row and an empty band
        from apps.api import evidence as E  # the model itself
        prof = {"person": {"name": "홍길동", "email": "gildong@example.com", "info": {"ko": "1990년생", "en": ""}, "location": {"ko": "", "en": "Seoul"},
                           "linkedin": "https://www.linkedin.com/in/example"},
                "roles": [{"heading": "예전 회사 (Old)", "org": "", "career": None},  # prints nowhere
                          {"org": "가나다랩", "start": "2019.01", "end": "2020.12", "title": "엔지니어"},
                          {"org": "라마바", "start": "2021.03", "end": None, "title": "리드"}]}
        m = E.Resume(prof, "ko", "navy", evmap={}, cands=[], base=None, edits={}, locks={}, details={}).build()
        career = next(b for b in m["blocks"] if b["type"] == "career")["rows"]
        self.assertEqual(["라마바", "가나다랩"], [r["name"] for r in career])  # the empty one out, newest first as printed
        self.assertEqual(["roles.2", "roles.1"], [r["sid"] for r in career])  # each keeps its place in the profile
        self.assertEqual(["role_role2", "role_role1"], [r["logo_id"] for r in career])  # tiles named as the loader names them
        self.assertEqual([["인적사항", "1990년생"], ["이메일", "gildong@example.com"], ["LinkedIn", "linkedin.com/in/example"]], m["person"]["contacts"])  # the printed rows; an English-only location stays off the Korean header

    def test_an_svg_picture_on_a_slide_is_in_the_page(self):
        # 2026-11-09: a person's own deck draws its timeline's logo tiles as SVG <image href="file://...">; the frame showed
        # them broken because only <img src> was put in the page
        from apps.api.tasks import live_html  # the page for the frame
        pics = self.tmp / "pics"  # where pictures come from
        pics.mkdir()
        (pics / "tile.png").write_bytes(b"tile bytes")  # one logo tile
        secret = self.tmp / "secret.png"  # a picture outside it
        secret.write_bytes(b"not for the page")
        page = (f'<head></head><svg><image x="1" href="file://{pics}/tile.png"/><image xlink:href="file://{pics}/tile.png"/>'  # both spellings
                f'<image href="file://{secret}"/></svg><a href="file://{pics}/tile.png">a link</a>')  # one from elsewhere, and a link
        out = live_html(page, (pics,))  # the frame's page
        self.assertEqual(2, out.count('href="data:image/png;base64,dGlsZSBieXRlcw=="'))  # both tiles in the page
        self.assertNotIn("bm90IGZvciB0aGUgcGFnZQ==", out)  # a file from elsewhere is not read
        self.assertIn('<image href=""/>', out)  # and draws nothing
        self.assertIn(f'<a href="file://{pics}/tile.png">', out)  # a link stays a link: only pictures are read

    def test_the_deck_is_shown_as_it_will_print_without_a_pdf(self):
        d = self.c.get(f"/api/v1/jobs/{GENERAL}/deck/ko")  # the facts' deck, before anything is written
        self.assertEqual(d["slides"], d["html"].count('<section class="slide'))  # the count the frame sizes itself by
        self.assertGreater(d["slides"], 3)  # a cover, some slides and an end
        self.write()  # the draft comes in
        d = self.c.get(f"/api/v1/jobs/{GENERAL}/deck/ko")  # made again from it
        html = d["html"]  # the page
        self.assertNotIn("file://", html)  # no path of this PC reaches the page, and a frame could not read one
        self.assertNotIn("<script", html)  # it runs nothing
        self.assertNotIn(str(self.tmp), html)  # nor names the data folder
        self.assertIn('url("/fonts/Pretendard-Regular.ttf")', html)  # the panel's copy of the same fonts
        sid, s = self.first(self.resume())  # a sentence the draft wrote
        words = s["text"].replace("==", "")  # as printed
        self.assertIn(words.split(".")[0][:12], html)  # it is on a slide
        with mock.patch.object(self.c.api.tasks, "_make_live_deck", side_effect=AssertionError("made again")):  # nothing changed: the kept page answers
            self.assertEqual(html, self.c.get(f"/api/v1/jobs/{GENERAL}/deck/ko")["html"])  # the same page
        self.c.post("/api/v1/sentences/edit", {"sid": sid, "text": "슬라이드에 보여야 할 새 문장을 적었습니다.", "lang": "ko", "job": GENERAL})  # a word changed
        self.assertIn("슬라이드에 보여야 할 새 문장을 적었습니다", self.c.get(f"/api/v1/jobs/{GENERAL}/deck/ko")["html"])  # the slide follows
        short = self.c.api.tasks.short(GENERAL)  # as the engine names it, the edition's outputs share this
        self.assertEqual([], [f.name for f in (ROOT / "output").glob(f"**/owl_{short}_ko_live*")])  # nothing stays in the engine's folder
        self.assertFalse((self.tmp / "workspace" / "jobs" / GENERAL / "live").exists())  # nor a working folder
        self.assertFalse((self.tmp / "workspace" / "jobs" / GENERAL / "resume" / "ko" / "profile.json").exists())  # and the edition was not touched: a locked job stays as submitted
        self.assertEqual("needs_translation", self.c.get(f"/api/v1/jobs/{GENERAL}/deck/en").get("missing"))  # the English edition says what it needs

    def test_a_profile_with_its_own_portfolio_shows_no_drawn_deck(self):
        prof = dict(self.c.api.tasks.facts.profile(), deck={"pdf": {"ko": "mine.pdf"}})  # the person's own portfolio, Korean only
        with mock.patch.object(self.c.api.tasks.facts, "profile", return_value=prof):  # as the profile keeps it
            self.assertEqual("own_deck", self.c.get(f"/api/v1/jobs/{GENERAL}/deck/ko").get("missing"))  # its pages are the deck, never redrawn
            self.assertNotEqual("own_deck", self.c.get(f"/api/v1/jobs/{GENERAL}/deck/en").get("missing"))  # the other language is drawn as before

    def test_the_slides_come_from_the_sentences_and_the_figures_from_the_evidence(self):
        self.write()  # written
        got = self.c.wait(self.c.post("/api/v1/jobs/figures", {"job": GENERAL, "lang": "ko"})["task"])  # the figure step
        self.assertEqual("done", got["state"], got)  # answered
        self.assertGreater(got["result"]["added"], 0)  # some passed every check
        m = self.resume()  # the canvas
        self.assertTrue(m["draft"]["figures"])  # the band stops offering them
        out = self.c.api.tasks.edition_inputs(GENERAL, "ko")  # what the deck reads
        prof = json.loads((out / "profile.json").read_text(encoding="utf-8"))  # the edition's profile
        self.assertEqual("chapters", json.loads((out / "job.json").read_text(encoding="utf-8")).get("deck"))  # a project slide per printed project
        drafted = [p for r in prof["roles"] for p in r["projects"] if p.get("cards")]  # projects with cards
        self.assertTrue(drafted)  # there are some
        first = drafted[0]  # one of them
        self.assertTrue(first["lede"]["ko"])  # its scope on top
        self.assertEqual("한 일", first["cards"]["ko"][0][0])  # what was done
        self.assertTrue(any(p.get("figure") for p in drafted))  # and a figure
        self.assertTrue(prof["summary"]["stats"]["ko"] and prof["summary"]["focus"]["ko"])  # the cover's tiles and columns, from the draft
        self.assertTrue(all(r.get("journey", {}).get("line", {}).get("ko") for r in prof["roles"]), [r.get("journey") for r in prof["roles"]])  # and each role's station on the career path
        self.assertEqual("done", self.write()["state"])  # written again
        self.assertTrue(self.resume()["draft"]["figures"])  # the figures stay

    def test_figures_need_the_resume_first(self):
        got = self.c.wait(self.c.post("/api/v1/jobs/figures", {"job": GENERAL, "lang": "ko"})["task"])  # no draft yet
        self.assertEqual("error", got["state"])  # refused
        self.assertEqual("needs_draft", got["error"]["code"])  # the band offers to write the resume

    def test_the_english_edition_takes_the_draft_and_the_translated_names(self):
        self.write()  # written in both languages, for a profile in Korean
        self.assertEqual(["needs_translation"], self.resume(lang="en")["missing"])  # names and schools still need English
        api = self.c.api  # the object behind the client
        src = api.tasks.ws.path("profile", "profile.json")  # the Korean profile
        en = json.loads((ROOT / "examples" / "sample_full_en.json").read_text(encoding="utf-8"))  # stands for its translation
        en["_from"] = hashlib.sha256(src.read_bytes()).hexdigest()[:16]  # made from this profile
        (src.parent / "profile.en.json").write_text(json.dumps(en, ensure_ascii=False), encoding="utf-8")  # beside the Korean one
        m = self.resume(lang="en")  # the English canvas
        self.assertFalse(m.get("missing"))  # drawn
        self.assertTrue(any(s.get("drafted") and s["text"].startswith("Worked on this") for s in m["sentences"].values()))  # the draft's English sentences
        org = next(b for b in m["blocks"] if b["type"] == "role")["org"]  # a company's name
        self.assertRegex(org, r"[A-Za-z]")  # from the translation
        sid, rec = self.first(m)  # a sentence the draft wrote
        got = self.c.post("/api/v1/sentences/edit", {"sid": sid, "text": "Worked on this as the record says", "lang": "en", "job": GENERAL})["sentence"]  # an English sentence of the draft can be edited
        self.assertEqual("edited", got["state"], got)  # checked again

    def test_with_a_draft_the_translation_asks_only_for_the_rest(self):
        self.write()  # the general edition, in both languages
        self.c.post("/api/v1/translate", {"job": GENERAL})  # the band's button
        got = self.c.wait("translate")  # its task
        self.assertEqual("done", got["state"], got)  # answered
        en = json.loads((self.tmp / "workspace" / "profile" / "profile.en.json").read_text(encoding="utf-8"))  # as saved
        self.assertTrue(en.get("_partial"))  # the draft's parts were not asked for
        m = self.resume(lang="en")  # the English canvas
        self.assertFalse(m.get("missing"))  # drawn
        self.assertTrue(any(s.get("drafted") for s in m["sentences"].values()))  # with the draft's English
        os.remove(self.tmp / "workspace" / "jobs" / GENERAL / "draft.json")  # the draft goes
        self.assertEqual(["needs_translation"], self.resume(lang="en")["missing"])  # so the partial translation is not enough any more

    def test_a_profile_in_english_is_written_in_english_only(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-draft-en-"))  # its own workspace
        self.addCleanup(shutil.rmtree, tmp, True)  # gone afterwards
        c = Client(tmp)  # the API
        self.addCleanup(c.settle, 120)  # cleanups run last first: its tasks end before the folder goes
        c.post("/api/v1/example", {"lang": "en"})  # the fictional person in English
        c.wait("ingest")  # read
        c.post("/api/v1/facts/keep-all", {})  # kept
        got = c.wait(c.post("/api/v1/jobs/write", {"job": GENERAL, "lang": "en"})["task"])  # written
        self.assertEqual("done", got["state"], got)  # answered
        d = json.loads((tmp / "workspace" / "jobs" / GENERAL / "draft.json").read_text(encoding="utf-8"))  # as saved
        self.assertEqual(["en"], d["_draft"]["langs"])  # one language, so no tokens go to a Korean version nobody asked for
        self.assertTrue(c.get("/api/v1/documents/resume", lang="en")["draft"]["own"])  # on the canvas

    def test_a_build_leaves_no_copy_in_the_engine(self):
        tasks = self.c.api.tasks  # the object behind the client
        out_dir = tasks.build_dir(GENERAL, "ko")  # the edition's folder
        out_dir.mkdir(parents=True, exist_ok=True)  # made
        (out_dir / "profile.json").write_text("{}", encoding="utf-8")  # its input
        short = self.c.api.tasks.short(GENERAL)  # as the engine names it, the name its outputs share
        engine = ROOT / "output"  # the engine's folder
        made = [engine / f"owl_{short}_ko.pdf", engine / "_figures" / f"owl_{short}_ko_timeline.png", engine / "_inputs" / f"owl_{short}_ko.job.json",  # what a build leaves
                engine / "_inputs" / (hashlib.sha1(str((out_dir / "profile.json").resolve()).encode()).hexdigest()[:8] + "_profile.json")]  # and the stage of its input
        for f in made:  # planted, so the test needs no typesetting
            f.parent.mkdir(parents=True, exist_ok=True)  # the folders may be new
            f.write_text("x", encoding="utf-8")  # a working copy
        tasks._clean_engine(GENERAL, "ko", out_dir)  # as the build ends
        self.assertEqual([], [f.name for f in made if f.exists()])  # nothing of it stays

    def test_the_interview_kit_gets_the_resume_s_english_names(self):
        self.write()  # a draft, whose English sentences declare their spellings of names
        d = self.stored()  # as saved
        d["evidence"].append({"at": "summary.intro", "lang": "en", "text": "At Alpha Pay.", "ev": [], "names": {"Alpha Pay": "알파페이"}})  # a declared spelling
        (self.tmp / "workspace" / "jobs" / GENERAL / "draft.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")  # saved
        jid = self.c.post("/api/v1/jobs", {"company": "감마", "posting": POSTING})["job"]  # a job, which uses the general draft
        self.c.wait(f"analyze:{jid}")  # ordered by words
        self.c.api.tasks.ensure_kit(jid, "ko")  # the question map and the kit's files
        iv = self.tmp / "workspace" / "jobs" / jid / "interview"  # the kit's folder
        self.assertIn("알파페이 = Alpha Pay", (iv / "names.txt").read_text(encoding="utf-8"))  # the spelling the scenes may use
        self.assertEqual("interview/names.txt", json.loads((iv / "kit.json").read_text(encoding="utf-8"))["names"])  # named in the kit
        from interview.job import Job  # the kit as the scene writer reads it
        from interview.evidence import Evidence  # its evidence
        job = Job(self.tmp / "workspace" / "jobs" / jid)  # the job
        self.assertIn((iv / "names.txt").resolve(), job.material_files())  # the checks ground names in it
        entry = {"text": "a question", "ask": {"en": ["a question"]}, "source": "posting.md:1", "kind": "posting"}  # any entry
        self.assertIn("알파페이 = Alpha Pay", Evidence(job, []).collect(entry))  # and the prompt carries it

    def test_write_more_scripts_goes_on_and_the_kit_shows_them(self):
        """One click writes the likeliest questions, the search view's items hold them at once, and the next click goes on."""
        jid = self.c.post("/api/v1/jobs", {"company": "감마", "posting": POSTING})["job"]  # a job
        self.c.wait(f"analyze:{jid}")  # ordered by words
        got = self.c.post("/api/v1/interview/scripts", {"job": jid, "lang": "ko"})  # the button
        self.assertEqual(f"scripts:{jid}", got["task"])  # its task
        first = self.c.wait(f"scripts:{jid}")  # finished
        self.assertEqual("done", first["state"], first)  # no trouble
        self.assertEqual(10, first["result"]["drafted"], first)  # one click's worth, all passing
        self.assertFalse(first["result"]["stopped"])  # the agent did not stop
        board = self.c.get(f"/api/v1/jobs/{urllib.parse.quote(jid)}/interview")  # the studio
        self.assertEqual([], validate.check("interview", board))  # it fits its schema, new kinds included
        kinds = [c["kind"] for c in board["categories"]]  # the columns
        self.assertEqual(["behavioral", "company"], kinds[:2])  # the likeliest first
        self.assertIn("scenario", kinds)  # the agent's expected questions joined the map
        self.assertEqual(10, sum(1 for s in board["scripts"] if s["draft"]))  # ten drafts among the cards
        from interview import corpus  # what the search view and practice read
        from interview.job import Job  # the kit
        job = Job(self.tmp / "workspace" / "jobs" / jid)  # the job
        self.assertEqual(10, sum(1 for it in corpus.load(job)[0] if it.get("draft")))  # the same ten
        self.c.post("/api/v1/interview/scripts", {"job": jid, "lang": "ko"})  # the button again
        self.assertEqual(10, self.c.wait(f"scripts:{jid}")["result"]["drafted"])  # ten more
        items = [it for it in corpus.load(job)[0] if it.get("draft")]  # all of them
        self.assertEqual(20, len(items))  # twenty, none written twice
        self.assertEqual(20, len({it["id"] for it in items}))  # with their own ids

    def test_a_round_s_questions_lead_the_board_and_get_their_scripts(self):
        """The questions a round asked lead the interview board, each with the rounds that asked it, and one click writes a
        script for each one that no script answers yet; the board then says a draft answers them."""
        jid = self.c.post("/api/v1/jobs", {"company": "감마", "posting": POSTING})["job"]  # a job
        self.c.wait(f"analyze:{jid}")  # ordered by words
        self.c.api.tasks.ensure_kit(jid, "ko")  # its kit and question map, no script yet
        asked = "1. 가장 어려웠던 장애를 말해 주세요\n- Tell me about the time you scaled a queue"  # as written down after the round (fictional)
        rec = self.c.post("/api/v1/tracker/round", {"job": jid, "kind": "first", "at": "2026-11-12T14:00", "asked": asked})["round"]
        url = f"/api/v1/jobs/{urllib.parse.quote(jid)}/interview"
        board = self.c.get(url)  # read now, with the round just kept
        self.assertEqual([], validate.check("interview", board))  # it fits its schema
        self.assertEqual("asked", board["categories"][0]["kind"])  # first
        qs = board["categories"][0]["questions"]
        self.assertEqual(["가장 어려웠던 장애를 말해 주세요", "Tell me about the time you scaled a queue"], [q["text"] for q in qs])  # list marks dropped
        self.assertEqual([[rec["id"]], [rec["id"]]], [q["rounds"] for q in qs])
        missing = [q["id"] for q in qs if q["coverage"] == "none"]
        self.assertEqual(2, len(missing))  # no script answers them yet
        for bad in (["../x"], [], ["a"] * 31, "a1b2c3"):  # not a list of the map's ids
            with self.assertRaisesRegex(RuntimeError, "bad_ids"):  # refused, nothing started
                self.c.post("/api/v1/interview/scripts", {"job": jid, "lang": "ko", "ids": bad})
        got = self.c.post("/api/v1/interview/scripts", {"job": jid, "lang": "ko", "ids": missing})  # the round's key
        done = self.c.wait(got["task"])
        self.assertEqual("done", done["state"], done)
        self.assertEqual(2, done["result"]["drafted"], done)  # one script each, and no other question's
        after = {q["id"]: q for q in self.c.get(url)["categories"][0]["questions"]}
        self.assertTrue(all(after[i]["coverage"] != "none" and after[i]["covered_by"] for i in missing), after)  # a script answers each now
        self.c.post("/api/v1/undo", {})  # the round taken back
        self.assertNotIn("asked", [c["kind"] for c in self.c.get(url)["categories"]])  # its questions leave the board with it

    def test_a_submitted_application_still_gets_its_interview_scripts(self):
        """Interviews come after the application is sent: a locked job writes its scripts into the kit's folder."""
        jid = self.c.post("/api/v1/jobs", {"company": "감마", "posting": POSTING})["job"]  # a job
        self.c.wait(f"analyze:{jid}")  # ordered by words
        card = self.tmp / "workspace" / "jobs" / jid / "status.json"  # its record
        st = json.loads(card.read_text(encoding="utf-8"))  # as saved
        st["locked"] = {"at": "2026-11-07", "folder": "sent", "files": {}, "lang": "ko"}  # submitted, as the lock records it
        card.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")  # saved
        got = self.c.post("/api/v1/interview/scripts", {"job": jid, "lang": "ko"})  # the button
        self.assertEqual(f"scripts:{jid}", got.get("task"), got)  # started, not refused
        done = self.c.wait(f"scripts:{jid}")  # finished
        self.assertEqual("done", done["state"], done)  # written
        self.assertEqual(10, done["result"]["drafted"], done)  # one click's worth

    def test_an_edition_printed_as_written_gives_the_kit_its_printed_lines(self):
        """An edition the person wrote has no sentences of ours: the kit asks about the lines its PDF printed, in the language
        it has, and never about the name, the headings or the contact lines."""
        from apps.api import documents  # the resume's text for the kit
        jid = self.c.post("/api/v1/jobs", {"company": "감마", "posting": POSTING})["job"]  # a job
        out = self.c.api.tasks.build_dir(jid, "en")  # its English edition, the only one made
        out.mkdir(parents=True, exist_ok=True)  # made
        (out / "resume.txt").write_text("Jin Kim\nHPC / AI INFRASTRUCTURE DEVOPS ENGINEER\n+82 10-1234-5678 | jin@example.com | Seoul\n\nOverview\n"
                                        "- Built Linux HPC clusters for customers with operations as code\n"
                                        "Ran the GPU nodes of an AI cloud on Kubernetes, from the racks to the scheduler\n"
                                        "010-1234-5678 is my number for the interview day\n", encoding="utf-8")  # as a build prints it
        with mock.patch.object(documents, "resume", return_value={"blocks": [], "sentences": {}}):  # an edition printed as written
            text = documents.resume_text(self.c.api.tasks, "ko", jid)  # asked in Korean, which this edition lacks
        self.assertEqual(["- Built Linux HPC clusters for customers with operations as code",
                          "- Ran the GPU nodes of an AI cloud on Kubernetes, from the racks to the scheduler"], text.splitlines())  # the claims only

    def test_no_agent_writes_nothing(self):
        os.environ.pop("OFFEROWL_PANEL_AGENT", None)  # the stand-in off
        self.c.post("/api/v1/settings", {"backend": "none"})  # no agent
        got = self.write()  # asked anyway
        self.assertEqual("error", got["state"])  # refused
        self.assertEqual("agent_unavailable", got["error"]["code"])  # the band offers to turn it on
        self.assertFalse((self.tmp / "workspace" / "jobs" / GENERAL / "draft.json").exists())  # nothing written


if __name__ == "__main__":  # run as a script
    unittest.main()
