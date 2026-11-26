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
from apps.api.services import applications, documents  # noqa: E402  the services whose actions the tests call
from apps.api import app as appmod  # noqa: E402  the settings' writer, slowed down below
from apps.api.services.library import backup, library  # noqa: E402  the names under test
from apps.api.services.profile import FACT_FILES, OwnFacts  # noqa: E402  the files of a fact change, an own edition's facts
from apps.api.routes import Router  # noqa: E402  the table the panel calls
from apps.api.core.stamps import file_hash  # noqa: E402  what a build records
from apps.api.core.workspace import Workspace, read_json, stored_name, write_json  # noqa: E402  the files and their names
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
            ids.append(applications.add_job(api, {"company": "감마클라우드", "posting": POSTING}, select=False))  # the same company each time
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
        jid = applications.add_job(api, {"company": "감마클라우드", "posting": POSTING}, select=False)
        self.wait(api, f"analyze:{jid}")
        documents.own_edition(api, {"job": jid, "profile": SAMPLE, "langs": ["ko"], "name": "first"})  # the one that came in
        before = (api.ws.job_dir(jid) / "own" / "own.json").read_text(encoding="utf-8")
        with mock.patch.object(OwnFacts, "import_profile", side_effect=RuntimeError("stopped")):  # the second stops half way
            with self.assertRaises(RuntimeError):
                documents.own_edition(api, {"job": jid, "profile": SAMPLE, "langs": ["ko"], "name": "second"})
        self.assertEqual(before, (api.ws.job_dir(jid) / "own" / "own.json").read_text(encoding="utf-8"))  # the first stays
        self.assertEqual(["own"], sorted(p.name for p in api.ws.job_dir(jid).iterdir() if p.name.startswith("own")))  # nothing half made beside it


class Lock(Base):
    def edition(self, api, issues):
        """A named edition as a build leaves it: a resume with its title and author, and the build's record."""
        jid = documents.add_edition(api, {"name": "Platform roles"})  # an edition that can be locked
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


class Slow(unittest.TestCase):
    """A client that never finishes its request head holds a slot only for the head's own short timeout (D3-11)."""

    def test_an_unfinished_request_head_is_dropped_after_the_head_timeout(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-slow-"))  # the data folder
        self.addCleanup(shutil.rmtree, tmp, True)
        p = mock.patch.dict(os.environ, {"OFFEROWL_PANEL_BACKEND": "none", "OFFEROWL_DESKTOP": str(tmp / "Desktop")})  # nothing real
        p.start()
        self.addCleanup(p.stop)
        from apps.panel import server  # the panel's server
        srv = server.serve(0, data=tmp / "data")  # a free port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        handler = srv.RequestHandlerClass  # the panel's own
        with mock.patch.object(handler, "header_timeout", 1):  # a second instead of ten, for the test
            port = srv.server_address[1]
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
                s.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n")  # the head never ends
                t0 = time.monotonic()
                got = s.recv(4096)  # the server closes it: nothing, or an error answer
                self.assertLess(time.monotonic() - t0, 5)  # long before the body timeout of 120 s
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:  # a whole request still gets its answer
                s.sendall(f"GET /api/v1/history HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode())
                answer = s.recv(100)
                self.assertIn(b" 200 ", answer.split(b"\r\n")[0], answer)  # answered as ever
        self.assertIsInstance(got, bytes)

    def test_a_file_over_its_cap_is_answered_413_to_a_client_still_sending(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-big-"))  # the data folder
        self.addCleanup(shutil.rmtree, tmp, True)
        p = mock.patch.dict(os.environ, {"OFFEROWL_PANEL_BACKEND": "none", "OFFEROWL_DESKTOP": str(tmp / "Desktop")})  # nothing real
        p.start()
        self.addCleanup(p.stop)
        from apps.panel import server  # the panel's server
        srv = server.serve(0, data=tmp / "data")  # a free port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port, size = srv.server_address[1], 12_000_000  # a photo is capped at 10 MB (D3-12: this was a broken pipe, not a 413)
        with socket.create_connection(("127.0.0.1", port), timeout=20) as s:
            s.sendall((f"POST /api/v1/photo HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/octet-stream\r\n"
                       f"X-File-Name: big.png\r\nContent-Length: {size}\r\n\r\n").encode())
            sent = 0
            while sent < size:  # the whole body, as a client that does not stop to read does
                s.sendall(b"\0" * min(1 << 20, size - sent))
                sent += min(1 << 20, size - sent)
            got = s.recv(4096)
        self.assertIn(b" 413 ", got.split(b"\r\n")[0], got[:100])  # told, not cut off


class Bodies(unittest.TestCase):
    """A body that stops coming, a length that is no number and JSON's own non-numbers, each answered with its code and never
    a 500 (D4-02, D4-07)."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-bodies-"))  # the data folder
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.dict(os.environ, {"OFFEROWL_PANEL_BACKEND": "none", "OFFEROWL_DESKTOP": str(self.tmp / "Desktop")})  # nothing real
        p.start()
        self.addCleanup(p.stop)
        from apps.panel import server  # the panel's server
        self.srv = server.serve(0, data=self.tmp / "data")  # a free port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.port = self.srv.server_address[1]

    def send(self, head: str, body: bytes = b"", wait: float = 20) -> tuple[bytes, bytes, float]:
        """A request written by hand: (status line, the answer's body, the seconds it took)."""
        t0 = time.monotonic()
        with socket.create_connection(("127.0.0.1", self.port), timeout=wait) as s:
            s.sendall(head.replace("\n", "\r\n").encode() + b"\r\n" + body)  # the head, its blank line, and what of the body is sent
            got = b""
            while True:  # the whole answer, until the server closes
                piece = s.recv(65536)
                if not piece:
                    break
                got += piece
        head_part, _, rest = got.partition(b"\r\n\r\n")
        return head_part.split(b"\r\n")[0], rest, time.monotonic() - t0

    def write_head(self, path: str, length: str, ctype: str = "application/json", extra: str = "") -> str:
        return (f"POST {path} HTTP/1.1\nHost: 127.0.0.1:{self.port}\nContent-Type: {ctype}\n{extra}"
                f"Content-Length: {length}\nConnection: close\n")

    def test_a_body_that_stops_coming_is_answered_408(self):
        with mock.patch.object(self.srv.RequestHandlerClass, "BODY_WAIT", 1):  # a second instead of ten, for the test
            status, body, took = self.send(self.write_head("/api/v1/settings", "100"), b'{"a":1}')  # 7 of the 100 bytes it said
        self.assertIn(b" 408 ", status, body)  # it was a 500 after ten seconds, with a traceback in the log (D4-02)
        self.assertEqual({"error": "timeout"}, json.loads(body))
        self.assertLess(took, 8)  # after the body's own wait

    def test_a_file_that_stops_coming_is_answered_408_and_leaves_no_piece(self):
        with mock.patch.object(self.srv.RequestHandlerClass, "BODY_WAIT", 1):
            status, body, _ = self.send(self.write_head("/api/v1/workspace/restore", "5000000", "application/octet-stream", "X-File-Name: backup.zip\n"), b"PK" + b"\0" * 1000)
        self.assertIn(b" 408 ", status, body)  # a backup that stopped part way
        self.assertEqual({"error": "timeout"}, json.loads(body))
        self.assertEqual([], [p.name for p in (self.tmp / "data").iterdir() if p.name.endswith(".part")])  # its piece went with it

    def test_a_length_that_is_no_number_is_refused_as_the_length(self):
        for path, ctype, extra in (("/api/v1/settings", "application/json", ""),
                                   ("/api/v1/materials", "application/octet-stream", "X-File-Name: notes.md\n")):  # a write, and an upload (it said "json")
            status, body, _ = self.send(self.write_head(path, "abc", ctype, extra))
            self.assertIn(b" 400 ", status, path)
            self.assertEqual({"error": "bad_request", "what": "length"}, json.loads(body), path)

    def test_json_s_non_numbers_are_refused(self):
        for raw in (b'{"deck_max_mb": NaN}', b'{"deck_max_mb": Infinity}', b'{"deck_max_mb": -Infinity}'):  # Python reads them; JSON has none (D4-07)
            status, body, _ = self.send(self.write_head("/api/v1/settings", str(len(raw))), raw)
            self.assertIn(b" 400 ", status, raw)
            self.assertEqual({"error": "bad_request", "what": "json"}, json.loads(body), raw)
        self.assertNotIn("deck_max_mb", read_json(self.tmp / "data" / "settings.json", {}))  # nothing was kept


class LibraryNames(Base):
    """The Library's copy on the Desktop takes the name every file handed out takes (D4-08): a made or a sent document as the
    Documents view's export names it, other files their own name with no leading dash or dot, a twin numbered _2."""

    def test_the_library_names_its_copies_as_the_export_does(self):
        api = self.make()  # an empty workspace
        desk = self.tmp / "Desktop"  # this test's own Desktop
        p = mock.patch.dict(os.environ, {"OFFEROWL_DESKTOP": str(desk)})
        p.start()
        self.addCleanup(p.stop)
        api.facts.set_details({"name": "홍길동"})  # the person, as their details name them
        api.facts.rebuild()
        jid = applications.add_job(api, {"company": "감마랩스", "posting": POSTING}, select=False)  # an application
        for job, file in (("-general", "resume.pdf"), (jid, "deck.pdf")):  # an edition of each, as a build leaves it
            out = api.tasks.build_dir(job, "ko")
            out.mkdir(parents=True, exist_ok=True)
            (out / file).write_bytes(b"%PDF-1.4 " + job.encode())
            write_json(out / "build.json", {"at": "2026-11-19 15:46", "issues": []})  # the day it was made
        sent = api.ws.job_dir(jid) / "submitted" / "ko-20261120"  # what went out, as a lock keeps it
        sent.mkdir(parents=True)
        (sent / "resume.pdf").write_bytes(b"%PDF-1.4 sent")
        st = api.ws.job(jid)
        st["locked"] = {"folder": "ko-20261120", "files": {"resume.pdf": "x"}, "lang": "ko", "at": "2026-11-20 10:00"}
        api.ws.save_job(st)
        self.assertEqual("홍길동_이력서_20261119.pdf", library.export(api, "made:-general:ko:resume.pdf"))  # it was "-general-ko-resume.pdf"
        self.assertEqual("홍길동_감마랩스_포트폴리오_20261119.pdf", library.export(api, f"made:{jid}:ko:deck.pdf"))  # it was "<job>-ko-deck.pdf"
        self.assertEqual("홍길동_감마랩스_이력서_20261120.pdf", library.export(api, f"sent:{jid}:resume.pdf"))  # the day it went
        self.assertEqual("홍길동_이력서_20261119.pdf", library.export(api, "made:-general:ko:resume.pdf"))  # those very bytes: named, not copied again
        (desk / "홍길동_감마랩스_포트폴리오_20261119.pdf").write_bytes(b"another file")  # another file under that name
        self.assertEqual("홍길동_감마랩스_포트폴리오_20261119_2.pdf", library.export(api, f"made:{jid}:ko:deck.pdf"))  # a twin: _2, never " (2)"
        mid = api.ws.add_materials("-notes.md", "회의 메모".encode("utf-8"))[0]["id"]  # a file whose own name begins with a dash
        self.assertEqual("notes.md", library.export(api, f"source:{mid}"))  # its own name, with no leading dash
        self.assertFalse([x.name for x in desk.iterdir() if x.name.startswith(("-", ".")) or " (" in x.name])  # none an option or hidden, no "(2)"


class DamagedSettings(Base):
    """A settings.json that does not read as settings: the panel starts on it, and the first change of a setting keeps it
    beside as settings.json.bad before the write replaces it (D4-14)."""

    def started_on(self, raw: bytes):
        """An API started on a data folder whose settings.json holds these bytes."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-settings-"))  # the data folder
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "settings.json").write_bytes(raw)  # as a crash or a hand edit left it
        for p in (mock.patch.object(appmod, "START", {}), mock.patch.dict(os.environ, {"OFFEROWL_PANEL_BACKEND": "none"})):  # nothing real
            p.start()
            self.addCleanup(p.stop)
        api = appmod.Api(tmp)  # [1, 2] stopped it here with a TypeError, at every start
        self.addCleanup(self.settle)  # its first look ends before the folder goes
        return api

    def test_a_damaged_settings_file_is_kept_beside_before_a_change_replaces_it(self):
        for raw in (b'{"lang": "ko", "form": ', b"[1, 2]", b'"text"', b"null", b"\xff\xfe broken"):
            with self.subTest(raw=raw):
                api = self.started_on(raw)
                self.assertEqual("auto", api.settings()["lang"])  # no choices read: the defaults
                self.assertIsInstance(api.state(), dict)  # the panel draws
                api.set_settings({"lang": "en"})  # the first change
                self.assertEqual(raw, api.settings_file.with_name("settings.json.bad").read_bytes())  # the damaged file kept (it was replaced, D4-14)
                self.assertEqual("en", api.settings()["lang"])  # the change kept
                api.set_settings({"theme": "dark"})  # a later change has nothing damaged to keep
                self.assertEqual(raw, api.settings_file.with_name("settings.json.bad").read_bytes())
                self.assertFalse(api.settings_file.with_name("settings.json.bad-2").exists())

    def test_settings_that_read_are_never_copied(self):
        api = self.started_on(json.dumps({"lang": "ko"}).encode())
        api.set_settings({"theme": "dark"})
        self.assertEqual(("ko", "dark"), (api.settings()["lang"], api.settings()["theme"]))  # both kept
        self.assertEqual(["settings.json"], sorted(p.name for p in api.data.iterdir() if p.name.startswith("settings")))  # no copy beside it


if __name__ == "__main__":
    unittest.main()
