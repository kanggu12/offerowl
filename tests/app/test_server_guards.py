#!/usr/bin/env python3
"""The server's guards that an independent review of 0.9.1 asked for: a change that stops half way leaves its files as they
were; a source's long name on disk; jobs added at once; an undo that leaves no file "reading"; the toast's Undo after a job
is added or its posting pasted again; a lock that asks the export's checks; a body sent in chunks; names on the Desktop and
beside a restored workspace that every system takes; an own edition that fails to come in; tailoring's build seen as a
build; settings changed at once; an impossible day on the board. Fictional data only: nothing real is called and no
typesetting runs.

  python3 -m unittest tests/app/test_server_guards.py -v
"""
import json  # the records
import os  # the server's environment
import pathlib  # paths
import shutil  # temporary folders
import socket  # a request written by hand
import sys  # the import path
import tempfile  # a folder per test
import threading  # things done at once
import time  # waiting for a task
import unittest  # the runner
from unittest import mock  # slow writes and stopped imports

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src", ROOT / "tests" / "app", ROOT / "tests" / "render"):  # apps/, the engine, the helpers beside this file
    sys.path.insert(0, str(p))
from test_choices import Base  # noqa: E402  one data folder per test, nothing real called
from test_pdftools import write_pdf  # noqa: E402  a small PDF with a text layer
from apps.api import app as appmod  # noqa: E402  the settings' writer, slowed down below
from apps.api import backup, library  # noqa: E402  the names under test
from apps.api.facts import FACT_FILES, OwnFacts  # noqa: E402  the files of a fact change, an own edition's facts
from apps.api.routes import Router  # noqa: E402  the table the panel calls
from apps.api.tasks import file_hash  # noqa: E402  what a build records
from apps.api.workspace import Workspace, read_json, stored_name, write_json  # noqa: E402  the files and their names
import pdfmeta  # noqa: E402  the title and the author a build stamps

POSTING = (ROOT / "tests" / "app" / "fixtures" / "posting_ko.md").read_text(encoding="utf-8")  # a fictional posting
SAMPLE = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the fictional person's profile


class Folder(unittest.TestCase):
    """A workspace in a folder of the test's own."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-guards-"))  # the folder
        self.addCleanup(shutil.rmtree, self.tmp, True)  # gone afterwards
        self.ws = Workspace(self.tmp / "ws")  # its layout


class Changes(Folder):
    def test_a_change_that_stops_half_way_leaves_the_files_as_they_were(self):
        a, b = self.ws.path("profile", "a.json"), self.ws.path("profile", "b.json")  # one file there, one not yet
        write_json(a, {"v": 1})  # as it was
        with self.assertRaises(RuntimeError):  # the caller's error still comes out
            with self.ws.change({"code": "undo_x"}, ["profile/a.json", "profile/b.json"]):
                write_json(a, {"v": 2})  # written
                write_json(b, {"v": 2})  # made
                raise RuntimeError("stopped half way")  # a bug, a full disk
        self.assertEqual({"v": 1}, read_json(a, {}))  # back as it was
        self.assertFalse(b.exists())  # the file it made went
        self.assertEqual(0, self.ws.history_count())  # and no undo step names it

    def test_a_job_folder_a_failed_change_made_goes_with_it(self):
        with self.assertRaises(ValueError):
            with self.ws.change({"code": "undo_add_job"}, self.ws.job_files("gamma")):
                self.ws.save_job({"id": "gamma", "company": "Gamma"})  # its card
                raise ValueError("posting")  # refused after the card was written
        self.assertFalse(self.ws.path("jobs", "gamma").exists())  # its name is free again


class Names(Folder):
    def test_a_long_korean_name_is_cut_by_bytes_and_keeps_its_extension(self):
        name = stored_name("m3", "가" * 150 + ".pdf")  # 450 bytes of name: more than a disk takes
        self.assertTrue(name.startswith("m3_") and name.endswith(".pdf"), name)  # its id first, its kind last
        self.assertLessEqual(len(name.encode("utf-8")), 180)  # room for a twin's number
        rec = self.ws.add_material("나" * 150 + ".pdf", b"%PDF-1.4\n")  # kept under such a name
        self.assertTrue(rec["file"].endswith(".pdf"), rec["file"])  # read by its kind
        self.assertTrue((self.ws.path("sources") / rec["file"]).is_file())  # and on disk

    def test_a_name_without_an_extension_is_cut_too(self):
        name = stored_name("m4", "다" * 200)  # no extension at all
        self.assertTrue(name.startswith("m4_") and len(name.encode("utf-8")) <= 180, name)

    def test_names_on_the_desktop_are_names_every_system_takes(self):
        self.assertEqual("_CON.md", library.desk_name("CON.md"))  # a device name of Windows
        self.assertEqual("notes", library.desk_name("notes. "))  # no dot or space at the end
        self.assertEqual("a_b_.txt", library.desk_name("a<b>.txt"))  # a refused character
        long = library.desk_name("라" * 120 + ".pdf")  # 360 bytes of name
        self.assertTrue(long.endswith(".pdf") and len(long.encode("utf-8")) <= 180, long)

    def test_a_workspace_set_aside_twice_in_one_second_keeps_both(self):
        root = self.tmp / "workspace"  # the workspace's folder
        with mock.patch.object(backup.time, "strftime", return_value="20261113-101010"):  # one second for both
            first = backup.aside_name(root)  # the plain name
            first.mkdir()  # taken by the first restore
            second = backup.aside_name(root)  # the next one
        self.assertEqual("workspace-before-restore-20261113-101010", first.name)
        self.assertEqual("workspace-before-restore-20261113-101010-2", second.name)


class Jobs(Base):
    def wait(self, api, key, timeout=30):
        """Until a task is no longer running."""
        end = time.time() + timeout  # a stuck task fails the test
        while time.time() < end and api.tasks.state().get(key, {}).get("state") == "running":
            time.sleep(0.05)

    def test_jobs_added_at_once_get_folders_of_their_own(self):
        api = self.make()  # an empty workspace
        start, ids = threading.Barrier(6), []  # six adds let go at once
        def add():
            start.wait()  # all together
            ids.append(api.add_job({"company": "감마클라우드", "posting": POSTING}, select=False))  # the same company each time
        threads = [threading.Thread(target=add) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(6, len(set(ids)), ids)  # six folders
        for jid in ids:  # each with its own card and posting
            self.assertEqual("감마클라우드", api.ws.job(jid)["company"])
            self.assertTrue((api.ws.job_dir(jid) / "posting.md").is_file())

    def test_the_toasts_undo_takes_back_a_job_with_its_analysis(self):
        api = self.make()
        r = Router(api)  # as the panel calls it
        _, body, _ = r.handle("POST", "/api/v1/jobs", {"state": "0"}, {"company": "감마클라우드", "posting": POSTING})
        jid, step = body["job"], body["step"]  # the job and the undo step its toast offers
        self.wait(api, f"analyze:{jid}")  # the analysis that follows
        self.assertTrue((api.ws.job_dir(jid) / "plan.json").is_file())  # it wrote its plan
        _, body, _ = r.handle("POST", "/api/v1/undo", {"state": "0"}, {"only": step})  # the toast's Undo
        self.assertNotIn("moved", body)  # the analysis made no step that came after it
        self.assertEqual("undo_add_job", body["undone"]["code"])
        self.assertFalse(api.ws.job_dir(jid).exists())  # the job went with its plan

    def test_a_posting_pasted_again_and_undone_brings_back_its_plan(self):
        api = self.make()
        r = Router(api)
        jid = r.handle("POST", "/api/v1/jobs", {"state": "0"}, {"company": "감마클라우드", "posting": POSTING})[1]["job"]
        self.wait(api, f"analyze:{jid}")
        plan = (api.ws.job_dir(jid) / "plan.json").read_text(encoding="utf-8")  # the plan of the first posting
        _, body, _ = r.handle("POST", "/api/v1/jobs/posting", {"state": "0"}, {"job": jid, "posting": "Kubernetes 운영 경험이 있는 분을 찾습니다. Go 로 서비스를 만듭니다."})
        self.wait(api, f"analyze:{jid}")
        self.assertEqual("undo_posting", api.ws.history()[0]["label"]["code"])  # the newest step is the paste: none of the analysis
        _, body, _ = r.handle("POST", "/api/v1/undo", {"state": "0"}, {"only": body["step"]})  # its toast's Undo
        self.assertEqual("undo_posting", body["undone"]["code"])
        self.assertEqual(POSTING.strip(), api.ws.posting(jid).strip())  # the first posting
        self.assertEqual(plan, (api.ws.job_dir(jid) / "plan.json").read_text(encoding="utf-8"))  # and its plan

    def test_an_undo_leaves_no_file_reading(self):
        api = self.make()
        rec = api.ws.add_material("notes.txt", b"a fictional note")  # a file added
        api.ws.update_material(rec["id"], state="reading")  # its reading began
        with api.ws.change({"code": "undo_add_material", "n": 1}, FACT_FILES):  # the reading's step
            api.ws.update_material(rec["id"], state="done", facts=1)  # read
        Router(api).handle("POST", "/api/v1/undo", {"state": "0"}, {})  # taken back: the list as it was, while the file was read
        self.assertEqual("new", api.ws.materials()[0]["state"])  # no reading runs, so it is not left turning

    def test_an_impossible_day_is_refused_in_words(self):
        api = self.make()
        r = Router(api)
        jid = r.handle("POST", "/api/v1/jobs", {"state": "0"}, {"company": "감마클라우드", "posting": POSTING})[1]["job"]
        self.wait(api, f"analyze:{jid}")
        for req in ({"date": "2026-02-30"}, {"dates": {"submitted": "2026-13-01"}}):  # a day no calendar has
            status, body, _ = r.handle("POST", "/api/v1/tracker/edit", {"state": "0"}, {"job": jid, **req})
            self.assertEqual((400, "date"), (status, body.get("what")), req)
        status, _, _ = r.handle("POST", "/api/v1/tracker/edit", {"state": "0"}, {"job": jid, "date": "2026-02-28"})  # a real one
        self.assertEqual(200, status)

    def test_settings_changed_at_once_keep_both(self):
        api = self.make()
        real = appmod.write_json  # the writer, slowed so two changes overlap
        def slow(path, data):
            time.sleep(0.05)
            real(path, data)
        start = threading.Barrier(2)
        def change(req):
            start.wait()
            api.set_settings(req)
        with mock.patch.object(appmod, "write_json", side_effect=slow):
            threads = [threading.Thread(target=change, args=(req,)) for req in ({"export_extras": True}, {"export_pptx": True})]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        saved = read_json(api.settings_file, {})  # as kept for the next start
        self.assertTrue(saved.get("export_extras") and saved.get("export_pptx"), saved)  # neither change lost

    def test_tailorings_build_is_seen_as_a_build(self):
        api = self.make()
        seen = {}
        def build():  # stands for the build tailoring runs in its own thread
            seen["state"] = api.tasks.state().get("build:gamma", {}).get("state")  # what the page sees meanwhile
            seen["twin"] = api.tasks.start("build:gamma", lambda: None)  # the page's own build asked for now
        self.assertTrue(api.tasks.run_here("build:gamma", build))
        self.assertEqual({"state": "running", "twin": False}, seen)  # running, and a second build refused
        self.assertEqual("done", api.tasks.state()["build:gamma"]["state"])  # done once it returned

    def test_an_own_edition_that_fails_to_come_in_keeps_the_one_before(self):
        api = self.make()
        jid = api.add_job({"company": "감마클라우드", "posting": POSTING}, select=False)
        self.wait(api, f"analyze:{jid}")
        api.own_edition({"job": jid, "profile": SAMPLE, "langs": ["ko"], "name": "first"})  # the one that came in
        before = (api.ws.job_dir(jid) / "own" / "own.json").read_text(encoding="utf-8")
        with mock.patch.object(OwnFacts, "import_profile", side_effect=RuntimeError("stopped")):  # the second stops half way
            with self.assertRaises(RuntimeError):
                api.own_edition({"job": jid, "profile": SAMPLE, "langs": ["ko"], "name": "second"})
        self.assertEqual(before, (api.ws.job_dir(jid) / "own" / "own.json").read_text(encoding="utf-8"))  # the first stays
        self.assertEqual(["own"], sorted(p.name for p in api.ws.job_dir(jid).iterdir() if p.name.startswith("own")))  # nothing half made beside it


class Lock(Base):
    def edition(self, api, issues):
        """A named edition as a build leaves it: a resume with its title and author, and the build's record."""
        jid = api.add_edition({"name": "Platform roles"})  # an edition that can be locked
        ed = api.tasks.build_dir(jid, "ko")
        ed.mkdir(parents=True)
        write_pdf(ed / "resume.pdf", [[(72, 72, 12, "Gildong Hong")]])  # one page
        pdfmeta.stamp(ed / "resume.pdf", "홍길동 이력서", "홍길동")  # as the build stamps it
        write_json(ed / "build.json", {"pages": 1, "issues": issues, "hashes": {"resume.pdf": file_hash(ed / "resume.pdf")}})
        return jid, ed

    def test_a_lock_asks_the_exports_checks(self):
        api = self.make()
        jid, ed = self.edition(api, ["pages:6:3"])  # an edition that failed its checks
        with self.assertRaisesRegex(ValueError, "checks_failed"):
            api.tasks.lock(jid, "ko")  # never frozen as sent: export_sent would copy it unchecked
        self.assertNotIn("locked", api.ws.job(jid))
        write_json(ed / "build.json", {"pages": 1, "issues": [], "hashes": {"resume.pdf": "0" * 64}})  # checked bytes that are not these
        with self.assertRaisesRegex(ValueError, "changed"):
            api.tasks.lock(jid, "ko")
        write_json(ed / "build.json", {"pages": 1, "issues": [], "hashes": {"resume.pdf": file_hash(ed / "resume.pdf")}})  # passed
        self.assertEqual("ko", api.tasks.lock(jid, "ko")["lang"])  # locked
        self.assertTrue(api.ws.job(jid)["locked"])


class Chunks(unittest.TestCase):
    def test_a_body_in_chunks_is_refused_with_411(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-chunks-"))  # the data folder
        self.addCleanup(shutil.rmtree, tmp, True)
        p = mock.patch.dict(os.environ, {"OFFEROWL_PANEL_BACKEND": "none", "OFFEROWL_DESKTOP": str(tmp / "Desktop")})  # nothing real
        p.start()
        self.addCleanup(p.stop)
        from apps.panel import server  # the panel's server
        srv = server.serve(0, data=tmp / "data")  # a free port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]
        body = b"{}"  # one chunk, then the last
        req = (f"POST /api/v1/settings HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\n"
               f"Transfer-Encoding: chunked\r\n\r\n{len(body):x}\r\n").encode() + body + b"\r\n0\r\n\r\n"
        with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
            s.sendall(req)
            got = b""
            while b"\r\n\r\n" not in got:  # the answer's head
                chunk = s.recv(4096)
                if not chunk:
                    break
                got += chunk
        self.assertTrue(got.startswith(b"HTTP/1.1 411") or got.startswith(b"HTTP/1.0 411"), got[:80])  # told to send a length


if __name__ == "__main__":
    unittest.main()
