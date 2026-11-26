#!/usr/bin/env python3
"""An application's own edition started from another edition's words (apps/api/services/documents/editions.py): the list of editions to start
from, the copy as one undo step that a build prints at once, each refusal, and the command-line twin `offerowl edition`.
Also the two undo rules the rewriting depends on: an edit of an own edition's words is a step of the workspace's one history
(the panel's undo took back the change before it), and bringing an edition in is one step that keeps the files brought in.
Everything is the fictional example person (examples/sample_ko.json) and fictional names.

Run: python3 -m unittest discover -s tests/app -p test_editions.py -v
"""
import contextlib  # the command's printed words, caught
import io  # in memory
import json  # editions as a file would give them
import os  # the language of the command's words
import pathlib  # paths
import subprocess  # the launcher, as a person runs it
import sys  # the import path
import time  # waiting for the example's reading
import unittest  # the runner
from unittest import mock  # the language setting

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "src"))  # and the engine's modules
from test_blind import Builds  # noqa: E402  the fictional person, with the typesetting stood in for
from test_choices import Base  # noqa: E402  one data folder per test, nothing real called
from apps.api.services import applications, documents, profile  # noqa: E402  the services whose actions the tests call
from apps.api.services.documents import documents as canvas  # noqa: E402  the canvas's model
from apps.api.services.documents import editions  # noqa: E402  the module under test
from apps.api.routes import Router  # noqa: E402  the table the panel calls
from apps.api.core.workspace import read_json, today  # noqa: E402  the files of an edition, the day

POSTING = (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")  # a fictional posting
SAMPLE = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the fictional person's resume
PDF = b"%PDF-1.4\n% a fictional one-page file\n%%EOF\n"  # enough for the type check of a file brought in


def edition(headline: str) -> dict:
    """The fictional person's resume with a headline of its own: an edition's words."""
    doc = json.loads(json.dumps(SAMPLE))  # a copy
    doc["summary"]["headline"] = headline  # what tells it apart
    return doc


def words(a, job) -> str:
    """Every sentence of a resume's canvas model, as one text."""
    return " ".join(s["text"] for s in canvas.resume(a.tasks, "ko", "navy", job)["sentences"].values())


class Editions(Base):
    """The fictional person, a named edition with words of its own (where a person keeps the sentences they last wrote), and
    two applications: one with words of its own, one that prints the general resume."""

    def world(self):
        a = self.make()  # the PC, nothing real called
        profile.add_example(a, "ko")  # the fictional person, read as a profile file
        for _ in range(200):  # its reading runs in a thread of its own
            if a.tasks.state().get("ingest", {}).get("state") != "running":
                break
            time.sleep(0.05)
        r = Router(a)  # the routes the panel calls
        self.latest = r.handle("POST", "/api/v1/editions", None, {"name": "플랫폼 직무 기본판"})[1]["job"]  # a named edition
        status, body, _ = r.handle("POST", "/api/v1/jobs/own", None, {"job": self.latest, "profile": edition("플랫폼 직무판의 머리 문장"), "langs": ["ko"],
                                                                  "name": "latest", "form": {"ko": {"photo": False, "footerLabel": "경력기술서"}}})
        self.assertEqual(200, status, body)  # its words
        self.delta = applications.add_job(a, {"company": "델타", "posting": POSTING}, select=False)  # an earlier application, with words of its own
        status, body, _ = r.handle("POST", "/api/v1/jobs/own", None, {"job": self.delta, "profile": edition("델타에 맞춘 머리 문장"), "langs": ["ko"], "name": "delta"})
        self.assertEqual(200, status, body)
        self.gamma = applications.add_job(a, {"company": "감마", "posting": POSTING}, select=False)  # the new application: the general resume for now
        return a, r

    def copy(self, r, job, src, **more):
        """The panel's copy, through the routes."""
        return r.handle("POST", "/api/v1/jobs/own/copy", None, {"job": job, "from": src, **more})


class CopyTests(Editions):
    """The copy: the source's words, layout, edits and locks, built again with the person as they are now."""

    def test_a_job_starts_from_a_named_editions_words(self):
        a, r = self.world()
        model = canvas.resume(a.tasks, "ko", "navy", self.latest)  # the named edition's sentences
        sid = next(k for k in model["sentences"] if k.startswith("roles.0.projects.0.summary"))  # one to rewrite
        held = next(k for k in model["sentences"] if k.startswith("roles.1.projects.0.summary"))  # one to lock
        canvas.edit_sentence(a.tasks, sid, "주문 상태 변경을 이벤트로 내보냈다.", "ko", self.latest)  # rewritten in the named edition
        canvas.lock_sentence(a.tasks, held, True, "ko", self.latest)  # and one kept as it is
        profile.details(a, {"fields": {"email": "gildong.new@example.com"}})  # the person's email changed after that edition came in
        self.assertNotIn("gildong.new@example.com", json.dumps(a.tasks.facts_for(self.latest).profile(), ensure_ascii=False))  # its built profile is older
        status, body, _ = self.copy(r, self.gamma, self.latest)
        self.assertEqual(200, status, body)  # started
        self.assertEqual({"job": self.gamma, "from": self.latest, "langs": ["ko"], "replaced": False, "files": []},
                         {k: body[k] for k in ("job", "from", "langs", "replaced", "files")})  # what the answer says
        self.assertTrue(body.get("step"))  # one undo step, named
        self.assertIn("플랫폼 직무판의 머리 문장", words(a, self.gamma))  # the named edition's own headline
        mine = canvas.resume(a.tasks, "ko", "navy", self.gamma)["sentences"]  # the job's sentences now
        self.assertEqual("주문 상태 변경을 이벤트로 내보냈다.", mine[sid]["text"])  # with the rewriting made there
        self.assertTrue(mine[held].get("locked"))  # and the lock
        self.assertEqual({"photo": False, "footerLabel": "경력기술서"}, a.tasks.own_form(self.gamma, "ko"))  # its layout choices
        self.assertEqual("gildong.new@example.com", a.tasks.facts_for(self.gamma).profile()["person"]["email"])  # built again: the person as they are now
        own = read_json(a.ws.job_dir(self.gamma) / "own" / "own.json", {})  # what it says of itself
        self.assertEqual({"job": self.latest, "name": "플랫폼 직무 기본판"}, own["from"])  # where it came from, for the panel's "Started from"
        self.assertEqual(today(), own["at"])  # started today
        view = next(j for j in a.state()["jobs"] if j["id"] == self.gamma)  # the job as the page draws it
        self.assertEqual(["ko"], view["own"])  # its own edition
        self.assertEqual({"job": self.latest, "name": "플랫폼 직무 기본판"}, view["own_info"]["from"])  # and where it came from
        self.assertNotIn("from", read_json(a.ws.job_dir(self.latest) / "own" / "own.json", {}))  # the source stays as it was
        self.assertNotIn("플랫폼 직무판의 머리 문장", words(a, None))  # and so does the general edition

    def test_undo_takes_the_copy_back(self):
        a, r = self.world()
        status, body, _ = self.copy(r, self.gamma, self.latest)
        self.assertEqual(200, status, body)
        self.assertEqual("undo_own_copy", a.ws.newest()[1]["code"])  # the newest step is the copy
        status, undone, _ = r.handle("POST", "/api/v1/undo", None, {"only": body["step"]})  # the note's Undo
        self.assertEqual(200, status, undone)
        self.assertEqual("undo_own_copy", undone["undone"]["code"])  # that very change
        self.assertIsNone(a.tasks.own_dir(self.gamma))  # no words of its own
        self.assertNotIn("플랫폼 직무판의 머리 문장", words(a, self.gamma))  # the general resume again
        self.assertIn(self.gamma, [j["id"] for j in a.state()["jobs"]])  # and the job itself stays

    def test_a_replace_is_asked_for_and_one_undo_brings_the_words_back(self):
        a, r = self.world()
        before = {rel: (a.ws.job_dir(self.delta) / "own" / rel).read_text(encoding="utf-8") for rel in editions.OWN_FILES
                  if (a.ws.job_dir(self.delta) / "own" / rel).is_file()}  # the earlier application's own edition, as it is
        steps = a.ws.history_count()  # the history before
        status, body, _ = self.copy(r, self.delta, self.latest)  # words of its own already
        self.assertEqual((400, "own_exists"), (status, body.get("what")))  # never replaced unasked
        self.assertEqual(steps, a.ws.history_count())  # and nothing written
        self.assertEqual(before["own.json"], (a.ws.job_dir(self.delta) / "own" / "own.json").read_text(encoding="utf-8"))
        status, body, _ = self.copy(r, self.delta, self.latest, replace=True)  # asked
        self.assertEqual(200, status, body)
        self.assertTrue(body["replaced"])  # said
        self.assertIn("플랫폼 직무판의 머리 문장", words(a, self.delta))  # the named edition's words
        self.assertNotIn("델타에 맞춘 머리 문장", words(a, self.delta))  # in place of its own
        r.handle("POST", "/api/v1/undo", None, {"only": body["step"]})  # one undo
        after = {rel: (a.ws.job_dir(self.delta) / "own" / rel).read_text(encoding="utf-8") for rel in editions.OWN_FILES
                 if (a.ws.job_dir(self.delta) / "own" / rel).is_file()}
        self.assertEqual(before, after)  # every file of its own edition, as it was
        self.assertIn("델타에 맞춘 머리 문장", words(a, self.delta))  # its words back

    def test_a_replace_never_leaves_the_job_without_an_edition_meanwhile(self):
        """The state is read with no lock: while the words are replaced file by file, the job keeps the profile it prints
        until the new one is written, so a poll in between never draws the general resume for a moment."""
        a, r = self.world()
        seen = []  # at each file written: did the job still have an edition to print
        real = editions.write_text  # the write the copy uses

        def watched(path, text):  # each file, as the copy writes it
            seen.append(a.tasks.own_dir(self.delta) is not None)  # what a poll would find now
            real(path, text)
        with mock.patch.object(editions, "write_text", side_effect=watched):
            status, body, _ = self.copy(r, self.delta, self.latest, replace=True)
        self.assertEqual(200, status, body)
        self.assertTrue(seen and all(seen), seen)  # never without one

    def test_the_files_brought_in_for_the_job_stay(self):
        a, r = self.world()
        documents.keep_own_file(a, self.gamma, "ko", "resume", "감마_이력서.pdf", PDF)  # a resume the person made as a file for it
        status, body, _ = self.copy(r, self.gamma, self.latest)
        self.assertEqual(200, status, body)
        self.assertEqual(["resume_ko"], body["files"])  # named: it still stands for the typeset resume
        self.assertEqual(PDF, a.tasks.own_file(self.gamma, "resume", "ko").read_bytes())  # byte for byte where it was
        self.assertEqual(["resume_ko"], next(j for j in a.state()["jobs"] if j["id"] == self.gamma)["own_info"]["files"])  # the page knows
        r.handle("POST", "/api/v1/undo", None, {"only": body["step"]})  # the copy taken back
        self.assertEqual(PDF, a.tasks.own_file(self.gamma, "resume", "ko").read_bytes())  # the file is not touched by the undo either

    def test_each_refusal(self):
        a, r = self.world()
        plain = applications.add_job(a, {"company": "엡실론", "posting": POSTING}, select=False)  # an application with no words of its own
        files_only = applications.add_job(a, {"company": "제타", "posting": POSTING}, select=False)  # one with a file brought in, and no words
        documents.keep_own_file(a, files_only, "ko", "resume", "제타.pdf", PDF)
        trashed = applications.add_job(a, {"company": "에타", "posting": POSTING}, select=False)  # one with words, in the Trash
        r.handle("POST", "/api/v1/jobs/own", None, {"job": trashed, "profile": edition("에타의 머리 문장"), "langs": ["ko"], "name": "eta"})
        applications.board(a, {"job": trashed, "removed": True})
        locked = applications.add_job(a, {"company": "세타", "posting": POSTING}, select=False)  # one that was submitted
        st = a.ws.job(locked)
        st["locked"] = {"at": today(), "folder": "20261110-120000", "files": {}, "lang": "ko"}  # as the lock records it
        a.ws.save_job(st)
        steps = a.ws.history_count()  # nothing below writes a step
        for req, code in (({"job": locked, "from": self.latest}, "locked"),  # submitted: its documents stay as they went
                          ({"job": self.gamma, "from": plain}, "no_edition"),  # prints the general resume
                          ({"job": self.gamma, "from": files_only}, "no_edition"),  # prints a file: no words to start from
                          ({"job": self.gamma, "from": "-general"}, "no_edition"),  # the profile itself
                          ({"job": "-general", "from": self.latest}, "job"),  # the general edition is the profile itself
                          ({"job": self.gamma, "from": self.gamma}, "same_edition"),
                          ({"job": self.gamma, "from": trashed}, "from"),  # in the Trash: as if it were not there
                          ({"job": self.gamma, "from": "nowhere"}, "from"),
                          ({"job": self.gamma}, "from"),  # none named
                          ({"job": trashed, "from": self.latest}, "job")):  # the job itself in the Trash
            status, body, _ = r.handle("POST", "/api/v1/jobs/own/copy", None, req)
            self.assertEqual((400, code), (status, body.get("what")), req)
        self.assertEqual(steps, a.ws.history_count())  # no refusal made a step
        self.assertIsNone(a.tasks.own_dir(self.gamma))  # nor words

    def test_the_list_puts_named_editions_first_and_leaves_the_job_out(self):
        a, r = self.world()
        documents.keep_own_file(a, applications.add_job(a, {"company": "제타", "posting": POSTING}, select=False), "ko", "resume", "제타.pdf", PDF)  # a file and no words: not listed
        status, body, _ = r.handle("GET", "/api/v1/editions", {"job": self.delta})
        self.assertEqual(200, status, body)
        self.assertEqual([self.latest], [e["job"] for e in body["editions"]])  # the named edition; the job asked about left out
        status, body, _ = r.handle("GET", "/api/v1/editions", {"job": self.gamma})
        self.assertEqual([(self.latest, "edition"), (self.delta, "job")], [(e["job"], e["kind"]) for e in body["editions"]])  # named editions first
        self.assertEqual({"job": self.gamma, "name": "감마", "kind": "job", "langs": [], "own": None, "locked": False}, body["target"])  # the general resume
        status, body, _ = r.handle("GET", "/api/v1/editions", {"job": self.delta})
        self.assertEqual(["ko"], body["target"]["langs"])  # words of its own: what a replace would take
        self.assertEqual(0, body["target"]["own"]["edited"])
        self.assertEqual(400, r.handle("GET", "/api/v1/editions", {"job": "nowhere"})[0])  # a job that is not there


class BuildTests(Builds):
    """A build made right after the copy prints the copied words (the typesetting stood in for)."""

    def test_the_build_after_the_copy_prints_its_words(self):
        a = self.person()  # the fictional person, every fact kept
        self.stand_in(a)  # the typesetting stood in for
        r = Router(a)
        src = r.handle("POST", "/api/v1/editions", None, {"name": "플랫폼 직무 기본판"})[1]["job"]
        r.handle("POST", "/api/v1/jobs/own", None, {"job": src, "profile": edition("플랫폼 직무판의 머리 문장"), "langs": ["ko"], "name": "latest",
                                                   "form": {"ko": {"footerLabel": "경력기술서"}}})  # with a layout choice of its own
        jid = applications.add_job(a, {"company": "Deltasoft", "posting": POSTING}, select=False)  # a fictional application
        a.tasks._build(jid, "ko", "navy", 3, False, False)  # made before: the general resume
        self.assertNotIn("플랫폼 직무판의 머리 문장", json.dumps(read_json(a.tasks.build_dir(jid, "ko") / "profile.json", {}), ensure_ascii=False))
        status, body, _ = r.handle("POST", "/api/v1/jobs/own/copy", None, {"job": jid, "from": src})
        self.assertEqual(200, status, body)
        view = next(j for j in a.state()["jobs"] if j["id"] == jid)  # the page's look at it
        self.assertTrue(view["builds"]["ko"]["stale"])  # the PDFs before it are said to be older
        a.tasks._build(jid, "ko", "navy", 3, False, False)  # made again, at once
        made = read_json(a.tasks.build_dir(jid, "ko") / "profile.json", {})  # what the typesetting read
        self.assertEqual("플랫폼 직무판의 머리 문장", made["summary"]["headline"])  # the copied words
        self.assertEqual(a.tasks.own_stamp(jid), self.record(a, jid)["own"])  # made from this own edition
        self.assertFalse(next(j for j in a.state()["jobs"] if j["id"] == jid)["builds"]["ko"]["stale"])  # and current
        self.assertEqual("경력기술서", read_json(a.tasks.build_dir(jid, "ko") / "job.json", {}).get("footerLabel"))  # its layout choices reach the typesetting


class OwnUndoTests(Editions):
    """The rewriting of an own edition is undone by the panel's one undo, and bringing an edition in is one step too."""

    def test_an_edit_of_an_own_editions_words_is_the_step_undo_takes_back(self):
        a, r = self.world()
        sid = next(k for k in canvas.resume(a.tasks, "ko", "navy", self.delta)["sentences"] if k.startswith("roles.0.projects.0.summary"))
        was = canvas.resume(a.tasks, "ko", "navy", self.delta)["sentences"][sid]["text"]  # its words as brought in
        status, body, _ = r.handle("POST", "/api/v1/sentences/edit", None, {"sid": sid, "text": "주문 상태 변경을 이벤트로 내보냈다.", "lang": "ko", "job": self.delta})
        self.assertEqual(200, status, body)
        self.assertTrue(body.get("step"))  # the answer names its step: a note's Undo takes back this one
        self.assertEqual(("undo_sentence", body["step"]), (a.ws.newest()[1]["code"], a.ws.newest()[0]))  # the workspace's newest step
        self.assertEqual([], list((a.ws.job_dir(self.delta) / "own" / ".history").glob("*.json")))  # none in the edition's own folder
        status, undone, _ = r.handle("POST", "/api/v1/undo", None, {"only": body["step"]})
        self.assertEqual("undo_sentence", undone["undone"]["code"])  # that edit, not the change before it
        self.assertEqual(was, canvas.resume(a.tasks, "ko", "navy", self.delta)["sentences"][sid]["text"])  # its words back
        self.assertIn(self.gamma, [j["id"] for j in a.state()["jobs"]])  # the job added before is still there
        status, body, _ = r.handle("POST", "/api/v1/sentences/lock", None, {"sid": sid, "locked": True, "lang": "ko", "job": self.delta})
        self.assertEqual("undo_lock_sentence", a.ws.newest()[1]["code"])  # a lock is a step of the same history
        r.handle("POST", "/api/v1/undo", None, {"only": body["step"]})
        self.assertFalse(canvas.resume(a.tasks, "ko", "navy", self.delta)["sentences"][sid].get("locked"))  # unlocked again

    def test_bringing_an_edition_in_is_one_step_and_keeps_the_files(self):
        a, r = self.world()
        documents.keep_own_file(a, self.gamma, "ko", "cover", "감마_자기소개서.pdf", PDF)  # a letter the person made for it
        status, first, _ = r.handle("POST", "/api/v1/jobs/own", None, {"job": self.gamma, "profile": edition("감마 첫 판"), "langs": ["ko"], "name": "first"})
        self.assertEqual(200, status, first)
        self.assertEqual("undo_own_edition", a.ws.newest()[1]["code"])  # one step
        status, second, _ = r.handle("POST", "/api/v1/jobs/own", None, {"job": self.gamma, "profile": edition("감마 둘째 판"), "langs": ["ko"], "name": "second"})
        self.assertIn("감마 둘째 판", words(a, self.gamma))  # the second replaces the first
        self.assertEqual(PDF, a.tasks.own_file(self.gamma, "cover", "ko").read_bytes())  # and the letter brought in stays
        r.handle("POST", "/api/v1/undo", None, {"only": second["step"]})  # one undo
        self.assertIn("감마 첫 판", words(a, self.gamma))  # the first again
        r.handle("POST", "/api/v1/undo", None, {"only": first["step"]})  # and another
        self.assertEqual([], a.tasks.own_langs(self.gamma))  # the general resume
        self.assertEqual(PDF, a.tasks.own_file(self.gamma, "cover", "ko").read_bytes())  # the letter, through it all


class SwitchTests(Editions):
    """An edition's switches (POST /api/v1/jobs/form): the about-me and the time at each company printed or left out, for an
    own edition, a named edition, a job drafted from the profile and the general edition (2026-11-26 the owner: "offerowl에
    이력서에 자기소개 포함 유무 옵션은 있어야해")."""

    def parts(self, a, job):
        """The canvas's parts of an edition, by their headings' keys."""
        return [b.get("key") for b in canvas.resume(a.tasks, "ko", "navy", job)["blocks"] if b.get("type") == "section"]

    def set(self, r, **body):
        """The head's switch, through the routes."""
        return r.handle("POST", "/api/v1/jobs/form", None, {"lang": "ko", **body})

    def every(self):
        """(the job the route names, the job the canvas is drawn for) of each kind of edition."""
        return [(self.gamma, self.gamma), (self.delta, self.delta), (self.latest, self.latest), ("-general", None)]

    def test_a_workspace_with_no_switch_prints_every_part(self):
        a, r = self.world()
        for job, view in self.every():  # nothing set anywhere: no file says anything
            self.assertEqual({}, a.tasks.edition_switches(view, "ko"))
            self.assertEqual({"about": True, "tenure": True}, canvas.resume(a.tasks, "ko", "navy", view)["switches"])
        for view in (self.delta, self.latest):  # the editions with words of their own draw every part (the example's facts are not kept here)
            self.assertIn("about", self.parts(a, view))  # the about-me printed

    def test_the_about_me_leaves_and_comes_back_in_every_kind_of_edition(self):
        a, r = self.world()
        for job, view in self.every():
            status, body, _ = self.set(r, job=job, about=False)
            self.assertEqual((200, {"about": False, "tenure": True}), (status, body["switches"]), job)
            self.assertEqual({"about": False, "tenure": True}, canvas.resume(a.tasks, "ko", "navy", view)["switches"])  # the head's switch
            if view in (self.delta, self.latest):  # an edition with words of its own: the canvas leaves the part out, the rest stays
                self.assertNotIn("about", self.parts(a, view))
                self.assertIn("career", self.parts(a, view))
            self.assertIs(False, a.tasks.edition_cfg(view, "ko", "navy").get("about"))  # so does the typesetter
            self.assertEqual({}, a.tasks.edition_switches(view, "en"))  # the English edition is its own
            status, body, _ = self.set(r, job=job, about=True)
            self.assertEqual({"about": True, "tenure": True}, body["switches"])
            if view in (self.delta, self.latest):
                self.assertIn("about", self.parts(a, view))  # back
        form = read_json(a.ws.job_dir(self.latest) / "own" / "form.json", {})  # the named edition's own layout choices
        self.assertEqual({"photo": False, "footerLabel": "경력기술서"}, form["ko"])  # kept beside the switch; printed again: no key left

    def test_the_tenure_is_a_switch_too(self):
        a, r = self.world()
        self.set(r, job=self.delta, tenure=False)  # an edition with its career table
        m = canvas.resume(a.tasks, "ko", "navy", self.delta)
        self.assertFalse(any(row.get("tenure") for b in m["blocks"] if b["type"] == "career" for row in b["rows"]))  # no time per company
        self.assertEqual({"about": True, "tenure": False}, m["switches"])

    def test_one_switch_is_one_undo_step_and_the_pdfs_made_before_it_are_stale(self):
        a, r = self.world()
        made = {"lang": "ko", "form": {}}  # a build's record: made with every part
        self.assertFalse(canvas.form_stale(a, self.gamma, made))
        self.assertFalse(canvas.form_stale(a, self.gamma, {"lang": "ko"}))  # a record from before switches: every part
        self.set(r, job=self.gamma, about=False)
        self.assertTrue(canvas.form_stale(a, self.gamma, made))  # made with the about-me: to be made again
        self.assertFalse(canvas.form_stale(a, self.gamma, {"lang": "ko", "form": {"about": False}}))  # made as it is now
        r.handle("POST", "/api/v1/undo", None, {})  # one undo
        self.assertEqual({}, a.tasks.edition_switches(self.gamma, "ko"))  # printed again

    def test_wrong_requests_are_refused_with_their_reason(self):
        a, r = self.world()
        for body, what in (({"job": self.gamma, "about": "no"}, "about"), ({"job": self.gamma}, "fields"),
                           ({"job": self.gamma, "lang": "fr", "about": False}, "lang"), ({"job": "nobody", "about": False}, "job")):
            status, out, _ = r.handle("POST", "/api/v1/jobs/form", None, {"lang": "ko", **body})
            self.assertEqual((400, what), (status, out.get("what")), body)
        st = a.ws.job(self.gamma)  # the application submitted and locked
        st["locked"] = {"at": "2026-11-26", "folder": "sent", "files": {}, "lang": "ko"}
        a.ws.save_job(st)
        status, out, _ = self.set(r, job=self.gamma, about=False)
        self.assertEqual((400, "locked"), (status, out.get("what")))  # its documents stay as they went
        self.assertEqual({}, a.tasks.edition_switches(self.gamma, "ko"))


class CommandTests(Editions):
    """`offerowl edition`: the same list and copy from a shell, in both languages."""

    def run_cli(self, *args, lang="en"):
        """The command in this process: its exit code, what it printed and what it said on stderr."""
        out, err = io.StringIO(), io.StringIO()  # what it prints
        with mock.patch.dict(os.environ, {"OFFEROWL_LANG": lang}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = editions.main([args[0], "--data", str(self.tmp), *args[1:]])  # the test's data folder, before a "--" the words may hold
        return code, out.getvalue(), err.getvalue()

    def test_list_and_start(self):
        a, r = self.world()
        code, out, _ = self.run_cli("list", "감마")  # by the job's id, which is its name here
        self.assertEqual(0, code)
        self.assertIn("감마: prints your general resume.", out)  # the job named, first
        lines = [x for x in out.splitlines() if x.startswith("  ")]  # one per edition
        self.assertEqual([self.latest, self.delta], [x.split()[0] for x in lines])  # named editions first, by id
        code, out, _ = self.run_cli("start", "감마", "--from", self.latest[1:])  # a named edition's id without its dash (ASCII since 0.15.0)
        self.assertEqual(0, code, out)
        self.assertIn("감마 now starts from 플랫폼 직무 기본판 [ko]", out)
        self.assertIn("플랫폼 직무판의 머리 문장", words(a, self.gamma))  # the same copy as the panel's
        code, out, err = self.run_cli("start", "감마", "--from", "델타")  # words of its own now
        self.assertEqual(1, code)
        self.assertIn("It was started from 플랫폼 직무 기본판.", err)  # what it has, said first
        self.assertIn("Add --replace", err)  # then the way to ask
        code, out, _ = self.run_cli("start", "감마", "--from", "델타", "--replace", "--json")  # asked, for a script
        self.assertEqual(0, code)
        self.assertEqual({"job": self.gamma, "from": self.delta, "replaced": True}, {k: json.loads(out)[k] for k in ("job", "from", "replaced")})
        code, _, err = self.run_cli("start", "감마", "--from", "없는 판", lang="ko")  # a name nobody has, in Korean
        self.assertEqual(1, code)
        self.assertIn("시작할 판을 찾지 못했다", err)  # said in the person's language
        code, _, err = self.run_cli("start", "--from=플랫폼 직무 기본판", "--", "-general")  # an id with a dash after "--": the general edition is the profile itself
        self.assertEqual(1, code)
        self.assertIn("-general", err)  # refused, naming it

    def test_the_launcher_runs_it(self):
        self.world()
        (self.tmp / "settings.json").write_text(json.dumps({"backend": "none"}), encoding="utf-8")  # no agent looked for
        env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_")}  # a clean shell
        env.update(OFFEROWL_LANG="ko", PYTHONDONTWRITEBYTECODE="1", OFFEROWL_PANEL_BACKEND="none")
        p = subprocess.run([sys.executable, str(ROOT / "offerowl"), "edition", "list", "--data", str(self.tmp)],  # as a person types it
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertIn("자기 문장이 있는 판", p.stdout)  # its words in Korean
        self.assertIn(self.latest, p.stdout)  # and the named edition, by its id


if __name__ == "__main__":
    unittest.main()
