"""One run from files or folders to finished documents (apps/api/autopilot.py), with the stand-in as the agent and the
typesetting replaced by a quick stand-in, so the order of the steps and what each one leaves are what is tested."""
import base64  # the test's small pictures
import json  # the stand-in's PDFs
import os  # the stand-in's switch
import struct  # the blocks a camera writes into a photo
import zlib  # a PNG chunk's checksum
import pathlib  # paths
import shutil  # temporary folders
import sys  # the import path
import tempfile  # a data folder per test
import unittest  # the runner
from unittest import mock  # the typesetting stand-in

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
from apps.api import autopilot as AP  # noqa: E402  the run
from apps.api.client import Client  # noqa: E402  the API in this process
sys.path.insert(0, str(ROOT / "src"))  # the engine's modules
sys.path.insert(0, str(ROOT / "tests" / "render"))  # the small PDF writer
import pdfmeta  # noqa: E402  the title and the author the engine writes
from test_office import make_docx  # noqa: E402  a Word file of the shape the typesetting writes
from test_pdftools import write_pdf  # noqa: E402  a one-page PDF with text

POSTING = (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")  # a fictional posting
JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/wAALCAAEAAMBAREA/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/ACv/2Q==")  # a grey 3x4 picture, drawn for the test
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAMAAAAECAIAAADETxJQAAAAF0lEQVR4nGM8kWLEwMDAwMDAxAAD2FgANVIBZoI3fxcAAAAASUVORK5CYII=")  # an orange 3x4 picture, drawn for the test


def segment(marker: int, body: bytes) -> bytes:
    """One JPEG segment: its marker, its length and its body."""
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(body) + 2) + body


def png_chunk(kind: bytes, body: bytes) -> bytes:
    """One PNG chunk with its checksum."""
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def camera_tiff(turn: int) -> bytes:
    """A camera's EXIF data, big endian: the phone's maker, and the picture turned (6: stored on its side)."""
    make = b"PhoneCo\x00"  # the maker, as an ASCII value stored after the directory
    entries = struct.pack(">HHII", 0x010F, 2, len(make), 8 + 2 + 24 + 4) + struct.pack(">HHIHH", 0x0112, 3, 1, turn, 0)  # Make, Orientation
    return b"MM\x00*" + struct.pack(">I", 8) + struct.pack(">H", 2) + entries + struct.pack(">I", 0) + make
NOTES = ROOT / "tests" / "app" / "fixtures" / "notes_ko.txt"  # the fictional person's career notes, one fact a line


def career_folder(root: pathlib.Path) -> pathlib.Path:
    """A folder as a person keeps one: notes in subfolders, and folders that hold no career (code, version control)."""
    f = root / "my career"  # a space in the name, as people name folders
    (f / "2023 alpha").mkdir(parents=True)  # a subfolder per job
    (f / ".git").mkdir()  # version control: skipped
    (f / "node_modules" / "x").mkdir(parents=True)  # code dependencies: skipped
    text = NOTES.read_text(encoding="utf-8")  # the fictional facts: a job, projects, a school
    (f / "2023 alpha" / "notes.md").write_text(text, encoding="utf-8")  # read
    (f / "summary.txt").write_text("홍길동\ngildong.hong@example.com | 010-1234-5678\n결제 플랫폼 백엔드 엔지니어. 알파페이에서 결제 승인 서비스를 재설계했다.\n", encoding="utf-8")  # read: the name and contact as a resume's top writes them
    (f / ".git" / "config.txt").write_text("not a career", encoding="utf-8")  # skipped with its folder
    (f / "node_modules" / "x" / "readme.md").write_text("a package", encoding="utf-8")  # skipped with its folder
    (f / "~$draft.docx").write_bytes(b"lock")  # an Office lock file: skipped
    (f / "photo.heic").write_bytes(b"x")  # not a kind the readers know: skipped
    return f


class Collect(unittest.TestCase):
    """What a pasted path brings in."""

    def setUp(self):  # a folder per test
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-ap-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_folder_brings_its_documents_and_nothing_else(self):
        f = career_folder(self.tmp)  # the folder
        files, skipped = AP.collect([str(f), str(self.tmp / "nowhere")])  # it and a path that is not there
        self.assertEqual(["notes.md", "summary.txt"], sorted(p.name for p in files))  # the documents
        self.assertEqual([{"path": str(self.tmp / "nowhere"), "why": "not_found"}], skipped)  # the missing path is said

    def test_one_file_once_under_two_paths(self):
        f = career_folder(self.tmp)  # the folder
        files, _ = AP.collect([str(f / "summary.txt"), str(f)])  # the file and its folder
        self.assertEqual(2, len(files))  # summary.txt once

    def zipped(self, members: dict) -> bytes:
        import io, zipfile  # an archive made in memory
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            for n, body in members.items():
                z.writestr(n, body)
        return b.getvalue()

    def test_a_linkedin_export_gives_the_career_files_and_never_other_peoples(self):
        from apps.api.workspace import Workspace
        ws = Workspace(self.tmp / "ws")
        data = self.zipped({"Profile.csv": "First Name,Headline\nGildong,Backend engineer\n", "Positions.csv": "Company Name,Title\nAlpha Pay,Engineer\n",
                            "Connections.csv": "First Name,Email Address\nMinsu,minsu@example.com\n", "messages.csv": "FROM,CONTENT\nx,hi\n"})
        names = [m["name"] for m in ws.add_materials("Basic_LinkedInDataExport.zip", data)]
        self.assertEqual(["Basic_LinkedInDataExport - Profile.csv", "Basic_LinkedInDataExport - Positions.csv"], names)

    def test_a_zipped_folder_is_opened_into_its_documents(self):
        f = self.tmp / "old.zip"  # a zip among the paths a run is given
        f.write_bytes(self.zipped({"old/notes.md": "# notes", "old/app.exe": "MZ", "__MACOSX/._notes.md": "x", "old/.hidden.md": "x"}))
        files, _ = AP.collect([str(f)])
        self.assertEqual([f], files)  # taken as one file
        from apps.api.workspace import Workspace
        self.assertEqual(["old - notes.md"], [m["name"] for m in Workspace(self.tmp / "ws2").add_materials(f.name, f.read_bytes())])

    def test_a_whole_drive_is_capped_and_said(self):
        d = self.tmp / "many"  # many files
        d.mkdir()
        for n in range(AP.MAX_FILES + 5):  # past the cap
            (d / f"n{n:03d}.txt").write_text("x", encoding="utf-8")
        files, skipped = AP.collect([str(d)])  # all of it
        self.assertEqual(AP.MAX_FILES, len(files))  # the cap
        self.assertEqual("too_many", skipped[-1]["why"])  # and the rest said

    def test_a_home_folder_pasted_whole_skips_the_systems_own_folders(self):
        """C:\\Users\\<name> holds AppData: its settings and tokens must not go to the agent."""
        home = self.tmp / "home"  # a home folder
        (home / "AppData" / "Roaming" / "app").mkdir(parents=True)  # a program's settings
        (home / "AppData" / "Roaming" / "app" / "settings.json").write_text('{"token": "x"}', encoding="utf-8")
        (home / "Library" / "Preferences").mkdir(parents=True)  # the same on a Mac
        (home / "Library" / "Preferences" / "a.json").write_text("{}", encoding="utf-8")
        (home / "Documents").mkdir()  # where a career is
        (home / "Documents" / "resume.pdf").write_bytes(b"%PDF-1.4 x")
        files, _ = AP.collect([str(home)])
        self.assertEqual(["resume.pdf"], [p.name for p in files])  # the document alone

    def test_past_the_cap_documents_come_first(self):
        d = self.tmp / "mixed"  # pictures first in name order, then a note and a PDF
        d.mkdir()
        for n in ("a.png", "b.png", "c.png", "d.txt", "e.pdf"):
            (d / n).write_bytes(b"x")
        with mock.patch.object(AP, "MAX_FILES", 3):  # a small cap
            files, skipped = AP.collect([str(d)])
        self.assertEqual(["a.png", "d.txt", "e.pdf"], [p.name for p in files])  # the PDF and the note kept, in walk order
        self.assertEqual("too_many", skipped[-1]["why"])

    def test_the_walk_stops_on_a_whole_drive(self):
        d = self.tmp / "drive"  # more files than are ever looked at
        d.mkdir()
        for n in range(12):
            (d / f"n{n:02d}.txt").write_text("x", encoding="utf-8")
        with mock.patch.object(AP, "MAX_SEEN", 5):  # a small limit
            files, skipped = AP.collect([str(d)])
        self.assertEqual(5, len(files))  # it stopped looking
        self.assertIn("too_many", [s["why"] for s in skipped])  # and said so

    def test_the_owners_contact_not_a_clone_address_a_picture_or_a_referee(self):
        readme = "# tools\ngit clone git@github.com:someone/tools.git\n![logo](logo@2x.png)\n"  # a README read first
        resume = "홍길동\ngildong.hong@example.com | 010-1234-5678\n결제 플랫폼 백엔드 엔지니어\n"  # the resume's top
        letter = "추천인 김민수 010-9999-0000\n홍길동 드림, 010-1234-5678\n"  # a referee's number, and hers again
        self.assertEqual("gildong.hong@example.com", AP.pick_contact([readme, resume, letter], AP.EMAIL, "email"))
        self.assertEqual("010-1234-5678", AP.pick_contact([readme, letter, resume], AP.PHONE, "phone"))  # written most, wherever it came first
        self.assertEqual("", AP.pick_contact([readme], AP.EMAIL, "email"))  # nothing that is a person's

    def test_paths_written_the_windows_way(self):
        self.assertEqual(pathlib.Path("/root/x/y"), AP.local_path(r"\\wsl.localhost\Ubuntu-22.04\root\x\y"))  # into the Linux side
        if pathlib.Path("/mnt/c").is_dir() and sys.platform != "win32":  # under WSL
            self.assertEqual(pathlib.Path("/mnt/c/Users/a"), AP.local_path(r'"C:\Users\a"'))  # a Windows drive, quotes and all

    def test_the_estimate_grows_with_the_files_and_the_posting(self):
        a, b = AP.estimate(3, False), AP.estimate(3, True)  # without and with a posting
        self.assertLess(a["calls"], b["calls"])  # the posting adds the letter and the scripts
        self.assertGreaterEqual(a["minutes"], 5)  # never promises less than a few minutes


class Run(unittest.TestCase):
    """The whole run, through the panel's API."""

    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ("OFFEROWL_PANEL_AGENT", "OFFEROWL_PANEL_BACKEND", "OFFEROWL_DESKTOP")}  # put back afterwards
        os.environ["OFFEROWL_PANEL_AGENT"] = "standin"  # no real model
        os.environ.pop("OFFEROWL_PANEL_BACKEND", None)  # a class run earlier must not count
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-ap-"))  # the data folder
        os.environ["OFFEROWL_DESKTOP"] = str(self.tmp / "Desktop")  # the exports land here
        self.c = Client(self.tmp / "data")  # the API
        self.built = []  # (job, language) of each typesetting

        def build(job_id, lang, theme, max_pages, with_cover=True, write_cover=False):  # the typesetting stand-in: one PDF per document
            self.built.append((job_id, lang))  # in order
            d = self.c.api.tasks.build_dir(job_id, lang)  # the edition's folder
            d.mkdir(parents=True, exist_ok=True)
            for f in ("resume.pdf", "deck.pdf") + (("cover.pdf",) if with_cover else ()):  # what the run would make
                write_pdf(d / f, [[(72, 72, 12, "Gildong Hong")]])  # one page
                pdfmeta.stamp(d / f, f"Gildong Hong {f}", "Gildong Hong")  # with its title and author, as the engine writes them
            from apps.api.tasks import file_hash  # the bytes the checks passed, as the real build records them
            (d / "build.json").write_text(json.dumps({"pages": 2, "hashes": {f.name: file_hash(f) for f in d.glob("*.pdf")}}), encoding="utf-8")
            self.c.api.tasks._set(f"build:{job_id}", state="done")  # as the real one ends
        self.patch = mock.patch.object(self.c.api.tasks, "_build", side_effect=build)  # no browser, no container
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        for k, v in self.env.items():  # the environment as it was
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)  # nothing left

    def steps(self, rec):
        """{step: state} of a finished run."""
        return {s["id"]: s["state"] for s in rec.get("steps") or []}

    def test_a_folder_and_a_posting_give_every_document(self):
        """Read, keep, the posting, write, English, figures, typeset, the interview kit and the Desktop, with nothing clicked."""
        f = career_folder(self.tmp)  # the person's folder
        got = self.c.post("/api/v1/autopilot", {"paths": [str(f)], "posting": POSTING})  # one action
        self.assertTrue(got["started"])  # it runs
        self.assertEqual(2, got["files"])  # the two documents, before the run reads them
        self.assertGreater(got["estimate"]["calls"], 2)  # and what it will cost
        rec = self.c.wait("autopilot", 600)  # finished
        self.assertEqual("done", rec["state"], rec)
        st = self.steps(rec)  # each step
        self.assertEqual(["collect", "read", "keep", "contact", "analyze", "write", "english", "figures", "typeset", "interview", "export"], [s["id"] for s in rec["steps"]])  # in order
        for sid in ("collect", "read", "keep", "contact", "analyze", "write", "typeset", "export"):  # the ones the stand-in can do
            self.assertEqual("done", st[sid], (sid, rec))
        jid = rec["result"]["job"]  # the job the posting became
        self.assertNotEqual("-general", jid)  # a job of its own
        self.assertIn((jid, "ko"), self.built)  # Korean
        self.assertIn((jid, "en"), self.built)  # and English
        self.assertTrue(rec["result"]["files"])  # files on the Desktop
        self.assertTrue(all((self.tmp / "Desktop" / n).is_file() for n in rec["result"]["files"]))  # really there
        names = {m["name"] for m in self.c.get("/api/v1/state")["materials"]}  # what the workspace kept
        self.assertEqual({"notes.md", "summary.txt"}, names)  # the documents and nothing from .git or node_modules

    def test_an_engine_that_exits_leaves_no_build_running(self):
        """The engine stops with SystemExit when a conversion fails: the run says so, and the PDFs key is free again."""
        # over the stand-in that makes PDFs: this one stops the way resume.py does when a conversion fails
        stop = mock.patch.object(self.c.api.tasks, "_build", side_effect=SystemExit("The documents could not be made."))
        stop.start()
        self.addCleanup(stop.stop)
        got = self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))], "posting": POSTING})  # one run
        self.assertTrue(got["started"])
        rec = self.c.wait("autopilot", 600)  # it ends
        st = self.steps(rec)
        self.assertEqual("failed", st["typeset"], rec)  # said on its step
        builds = {k: v.get("state") for k, v in self.c.api.tasks.state().items() if k.startswith("build:")}  # every build key
        self.assertTrue(builds)
        self.assertNotIn("running", builds.values(), builds)  # none left running: Make PDFs takes a new press

    def test_the_name_and_contact_come_from_the_files(self):
        """The top of an old resume fills "Your details": the email and phone by their shape, the name as the files write it."""
        self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})  # one action
        self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        det = self.c.api.facts.details()  # "Your details"
        self.assertEqual(("홍길동", "gildong.hong@example.com", "010-1234-5678"), (det.get("name"), det.get("email"), det.get("phone")))
        files = {m["name"] for m in self.c.get("/api/v1/state")["materials"]}  # the files the run read
        for k in ("name", "email", "phone"):  # each field says which file it came from, and the words it was found in
            self.assertIn(det["_src"][k]["file"], files, k)
        self.assertIn("gildong.hong@example.com", det["_src"]["email"]["quote"])  # the address in its own line of the file
        self.assertEqual(det["_src"], self.c.get("/api/v1/state")["details"]["_src"])  # the panel gets them

    def test_a_name_the_person_typed_stays(self):
        """The person's own words are never replaced by what a file says."""
        self.c.post("/api/v1/details", {"fields": {"name": "길동 홍", "email": "me@example.org"}})  # typed before the run
        self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})
        self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        det = self.c.api.facts.details()  # after the run
        self.assertEqual(("길동 홍", "me@example.org", "010-1234-5678"), (det.get("name"), det.get("email"), det.get("phone")))  # only the empty one was filled
        self.assertEqual(({"typed": True}, {"typed": True}), (det["_src"]["name"], det["_src"]["email"]))  # typed by the person
        self.assertTrue(det["_src"]["phone"].get("file"))  # the one filled names its file

    def test_again_makes_one_editions_pdfs_once_more(self):
        """After the person fills in what was missing: the PDFs and the Desktop again, nothing else."""
        self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})  # the general edition
        self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        self.built.clear()  # count this run's typesetting alone
        self.c.post("/api/v1/autopilot", {"again": "-general", "theme": "forest"})  # once more, in another colour
        rec = self.c.wait("autopilot", 600)
        self.assertEqual(["typeset", "export"], [s["id"] for s in rec["steps"]])  # only those
        self.assertEqual([("-general", "ko"), ("-general", "en")], self.built)  # both languages

    def test_without_a_posting_the_general_edition(self):
        """No posting: the general resume and deck, in both languages, and no job."""
        f = career_folder(self.tmp)  # the person's folder
        self.c.post("/api/v1/autopilot", {"paths": [str(f)]})  # one action
        rec = self.c.wait("autopilot", 600)  # finished
        self.assertEqual("done", rec["state"], rec)
        self.assertNotIn("analyze", self.steps(rec))  # no posting step
        self.assertNotIn("interview", self.steps(rec))  # and no kit
        self.assertEqual("-general", rec["result"]["job"])  # the general edition
        self.assertEqual([("-general", "ko"), ("-general", "en")], self.built)  # both languages

    def test_a_posting_alone_tailors_what_is_kept(self):
        """Once a career is kept, a posting alone makes its documents and kit without reading the files again."""
        f = career_folder(self.tmp)  # the person's folder
        self.c.post("/api/v1/autopilot", {"paths": [str(f)]})  # the general edition first
        self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        self.built.clear()  # count this run's typesetting alone
        got = self.c.post("/api/v1/autopilot", {"posting": POSTING})  # then a posting, and nothing else
        self.assertTrue(got["started"])  # it runs
        rec = self.c.wait("autopilot", 600)  # finished
        self.assertEqual("done", rec["state"], rec)
        ids = [s["id"] for s in rec["steps"]]  # the steps it took
        self.assertNotIn("read", ids)  # nothing read again
        self.assertEqual(["analyze", "write", "english", "figures", "typeset", "interview", "export"], ids)  # the posting's steps
        jid = rec["result"]["job"]  # the job the posting became
        self.assertNotEqual("-general", jid)
        self.assertEqual([(jid, "ko"), (jid, "en")], self.built)  # both languages, for the posting

    def test_a_posting_pasted_during_a_run_follows_it(self):
        """The person drops a folder, then pastes a posting while it is read: the posting's run starts when the first ends."""
        import threading  # the pause inside the first run
        f = career_folder(self.tmp)  # the person's folder
        real, go_on, inside = self.c.api.tasks._write, threading.Event(), threading.Event()  # the writing step, and two signals

        def slow_write(*a, **kw):  # the first run waits here until the posting has been sent
            inside.set()  # the run is in progress
            go_on.wait(60)  # until the test lets it go
            return real(*a, **kw)
        with mock.patch.object(self.c.api.tasks, "_write", side_effect=slow_write):
            self.assertTrue(self.c.post("/api/v1/autopilot", {"paths": [str(f)]})["started"])  # the folder
            self.assertTrue(inside.wait(60))  # it is writing
            got = self.c.post("/api/v1/autopilot", {"posting": POSTING})  # the posting, meanwhile
            self.assertEqual((False, True), (got["started"], got["queued"]))  # it waits for the first
            go_on.set()  # the first run goes on
            rec = self.c.wait("autopilot", 600)  # both finished
        self.assertEqual("done", rec["state"], rec)
        self.assertIn("analyze", [s["id"] for s in rec["steps"]])  # the card shows the posting's run last
        runs = self.c.get("/api/v1/state")["runs"]  # the list on the page, newest first
        self.assertEqual(2, len(runs))  # one line per run
        self.assertNotEqual("-general", runs[0]["job"])  # the posting's
        self.assertEqual("-general", runs[1]["job"])  # then the general edition
        self.assertTrue(runs[0]["files"] and runs[1]["files"])  # each put files on the Desktop

    def test_a_job_already_added_gets_its_documents(self):
        """The Jobs view's key: a job added and read earlier, written, typeset and given its scripts, with no posting step."""
        self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})  # a career first
        self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        jid = self.c.post("/api/v1/jobs", {"posting": POSTING})["job"]  # added in the Jobs view
        self.c.wait(f"analyze:{jid}", 120)  # read there
        self.built.clear()  # count this run's typesetting alone
        self.c.post("/api/v1/autopilot", {"job": jid})  # its documents
        rec = self.c.wait("autopilot", 600)
        self.assertEqual("done", rec["state"], rec)
        self.assertEqual(["write", "english", "figures", "typeset", "interview", "export"], [s["id"] for s in rec["steps"]])  # no reading, no posting step
        self.assertEqual(jid, rec["result"]["job"])  # that job, not a new one
        self.assertEqual([(jid, "ko"), (jid, "en")], self.built)  # both languages

    def test_the_example_leaves_before_the_persons_own_files(self):
        """Seen the example first, then dropped one's own folder: nothing of the fictional person stays in the documents."""
        self.c.post("/api/v1/example", {"lang": "ko"})  # "Try an example"
        self.c.wait("ingest", 60)  # read as a profile file
        self.c.post("/api/v1/facts/keep-all", {})  # kept, as the example does
        self.assertEqual("gildong@example.com", self.c.api.facts.details().get("email"))  # the example filled "Your details"
        example = self.c.api.facts.details()["_src"]["email"]["file"]  # and said so
        self.assertTrue(example)
        self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})  # then the person's own folder
        self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        self.assertEqual("gildong.hong@example.com", self.c.api.facts.details().get("email"))  # the address of the person's own files
        self.assertIn(self.c.api.facts.details()["_src"]["email"]["file"], {"notes.md", "summary.txt"})  # and its source is theirs, not the example's
        names = {m["name"] for m in self.c.get("/api/v1/state")["materials"]}  # the files listed
        self.assertEqual({"notes.md", "summary.txt"}, names)  # the example's file is gone
        self.assertFalse([c for c in self.c.api.facts.candidates() if c.get("origin") == "profile"])  # and its facts

    def test_a_stop_while_the_files_are_collected_reads_nothing(self):
        real, calls = AP.collect, []  # the walk, and the times it was asked

        def collect_then_stop(paths):  # the person presses Stop as the run takes the files
            calls.append(paths)
            if len(calls) == 2:  # the run's own call (the first is the request's)
                self.c.post("/api/v1/autopilot/stop", {})
            return real(paths)
        with mock.patch.object(AP, "collect", side_effect=collect_then_stop):
            self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})
            rec = self.c.wait("autopilot", 600)
        st = self.steps(rec)
        self.assertEqual(("done", "skipped", "skipped", "skipped"), (st["collect"], st["read"], st["keep"], st["contact"]), rec)  # nothing read or kept
        self.assertTrue(rec["result"]["stopped"])  # said as stopped
        self.assertEqual([], rec["result"]["files"])  # nothing on the Desktop
        self.assertFalse(self.c.api.facts.details().get("email"))  # "Your details" untouched
        self.assertEqual([], self.built)  # nothing typeset

    def test_a_request_after_a_stop_still_runs(self):
        """Stop, then drop the right files while the stopped run finishes its step: the new files are read."""
        import threading
        f = career_folder(self.tmp)
        real, go_on, inside = self.c.api.tasks._write, threading.Event(), threading.Event()

        def slow_write(*a, **kw):  # the first run waits inside its writing
            inside.set()
            go_on.wait(60)
            return real(*a, **kw)
        with mock.patch.object(self.c.api.tasks, "_write", side_effect=slow_write):
            self.c.post("/api/v1/autopilot", {"paths": [str(f)]})  # the first run
            self.assertTrue(inside.wait(60))
            self.c.post("/api/v1/autopilot/stop", {})  # stopped
            got = self.c.post("/api/v1/autopilot", {"posting": POSTING})  # then a posting, after the stop
            self.assertTrue(got["queued"])
            go_on.set()
            rec = self.c.wait("autopilot", 600)
        self.assertEqual("done", rec["state"], rec)
        self.assertFalse(rec["result"]["stopped"])  # the second run was not stopped
        self.assertIn("analyze", [s["id"] for s in rec["steps"]])  # it is the posting's
        runs = self.c.get("/api/v1/state")["runs"]
        self.assertEqual([False, True], [bool(r.get("stopped")) for r in runs[:2]])  # the posting's run, then the stopped one

    def test_a_stop_takes_what_waited_with_it(self):
        import threading
        real, go_on, inside = self.c.api.tasks._write, threading.Event(), threading.Event()

        def slow_write(*a, **kw):
            inside.set()
            go_on.wait(60)
            return real(*a, **kw)
        with mock.patch.object(self.c.api.tasks, "_write", side_effect=slow_write):
            self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})
            self.assertTrue(inside.wait(60))
            self.assertTrue(self.c.post("/api/v1/autopilot", {"posting": POSTING})["queued"])  # waits
            self.c.post("/api/v1/autopilot/stop", {})  # then Stop: for everything asked so far
            go_on.set()
            rec = self.c.wait("autopilot", 600)
        self.assertTrue(rec["result"]["stopped"])  # the first run, stopped
        self.assertEqual(1, len(self.c.get("/api/v1/state")["runs"]))  # and the posting never ran

    def test_two_drops_during_a_run_are_both_read(self):
        import threading
        a, b = self.tmp / "a", self.tmp / "b"  # two folders, dropped one after the other
        a.mkdir(); b.mkdir()
        text = NOTES.read_text(encoding="utf-8")
        (a / "first.md").write_text(text, encoding="utf-8")
        (b / "second.md").write_text(text, encoding="utf-8")
        real, go_on, inside = self.c.api.tasks._write, threading.Event(), threading.Event()

        def slow_write(*args, **kw):
            inside.set()
            go_on.wait(60)
            return real(*args, **kw)
        with mock.patch.object(self.c.api.tasks, "_write", side_effect=slow_write):
            self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})  # the first run
            self.assertTrue(inside.wait(60))
            self.c.post("/api/v1/autopilot", {"paths": [str(a)]})  # one folder
            self.c.post("/api/v1/autopilot", {"paths": [str(b)]})  # and another, before the first run ends
            go_on.set()
            self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        names = {m["name"] for m in self.c.get("/api/v1/state")["materials"]}
        self.assertTrue({"first.md", "second.md"} <= names, names)  # both read

    def test_a_job_the_run_adds_is_not_put_in_view(self):
        """An edit in progress on one job must not land on the job a run adds meanwhile."""
        self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})
        self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        mine = self.c.post("/api/v1/jobs", {"posting": POSTING, "company": "Mine"})["job"]  # added by the person: in view
        self.c.wait(f"analyze:{mine}", 120)
        self.c.post("/api/v1/autopilot", {"posting": POSTING.replace("백엔드", "플랫폼")})  # a run adds another
        rec = self.c.wait("autopilot", 600)
        self.assertNotEqual(mine, rec["result"]["job"])  # a job of its own
        self.assertEqual(mine, self.c.get("/api/v1/state")["job"])  # the one in view stays

    def test_only_the_editions_this_run_made_are_copied(self):
        """English fails this time: the Desktop gets the Korean files alone, never the English of an earlier run."""
        self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})  # both editions, once
        self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        made = self.c.api.tasks._build.side_effect  # the stand-in

        def english_fails(job_id, lang, *a, **kw):  # the English edition stops early, its old files left in place
            if lang == "en":
                self.c.api.tasks._set(f"build:{job_id}", state="error", error={"code": "needs_translation"})
                return
            made(job_id, lang, *a, **kw)
        self.c.api.tasks._build.side_effect = english_fails
        self.c.post("/api/v1/autopilot", {"again": "-general"})
        rec = self.c.wait("autopilot", 600)
        self.assertEqual(["ko"], rec["result"]["langs"])  # what this run made
        self.assertTrue(rec["result"]["files"])
        self.assertFalse([n for n in rec["result"]["files"] if "Resume" in n or "Portfolio" in n], rec["result"]["files"])  # no English file

    def test_a_letter_that_failed_shows_no_tile(self):
        """The letter's picture from an earlier build stays in preview/, but its PDF is gone: no tile that leads nowhere."""
        from apps.api import documents  # the editions in the state
        d = self.c.api.tasks.build_dir("-general", "ko")  # an edition
        (d / "preview").mkdir(parents=True)
        (d / "build.json").write_text("{}", encoding="utf-8")
        for f in ("resume.pdf", "preview/r-1.png", "preview/c-1.png"):  # the resume, and an old letter's picture
            (d / f).write_bytes(b"x")
        prev = documents.editions(self.c.api.tasks, "-general")["ko"]["previews"]
        self.assertEqual((1, 0), (prev["r"], prev["c"]))  # the resume's page, and no letter

    def test_a_step_that_raises_leaves_no_task_running(self):
        """A bug inside the typesetting must not leave its key running, or its button refuses until a restart."""
        self.c.api.tasks._build.side_effect = RuntimeError("pdftoppm missing")  # the build breaks
        self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})
        self.assertEqual("done", self.c.wait("autopilot", 600)["state"])
        self.assertEqual("error", self.c.api.tasks.state()["build:-general"]["state"])  # free again

    def test_a_posting_alone_with_no_career_is_refused(self):
        with self.assertRaises(Exception):  # nothing kept yet: there is nothing to tailor
            self.c.post("/api/v1/autopilot", {"posting": POSTING})

    def test_nothing_to_read_is_said_before_anything_runs(self):
        with self.assertRaises(Exception):  # refused as a bad request
            self.c.post("/api/v1/autopilot", {"paths": []})

    def test_a_folder_with_no_documents_says_so(self):
        empty = self.tmp / "empty"  # a folder with nothing readable
        (empty / "node_modules").mkdir(parents=True)
        self.c.post("/api/v1/autopilot", {"paths": [str(empty)]})  # one action
        rec = self.c.wait("autopilot", 120)  # it ends at once
        self.assertEqual("error", rec["state"])
        self.assertEqual("no_files", rec["error"]["code"])  # the page names the problem

    def test_without_an_agent_it_stops_after_reading(self):
        """No agent: the run says so, and writes nothing."""
        os.environ.pop("OFFEROWL_PANEL_AGENT", None)  # the stand-in off
        self.c.post("/api/v1/settings", {"backend": "none"})  # no agent
        self.c.post("/api/v1/autopilot", {"paths": [str(career_folder(self.tmp))]})  # one action
        rec = self.c.wait("autopilot", 120)  # it ends
        self.assertEqual("error", rec["state"])
        self.assertEqual("agent_unavailable", rec["error"]["code"])  # the page offers to turn the agent on
        self.assertEqual([], self.built)  # nothing typeset

    def test_a_stop_ends_the_run_after_the_step_in_progress(self):
        """The stop button: the next steps are skipped."""
        f = career_folder(self.tmp)  # the person's folder
        real = self.c.api.tasks._write  # the writing step

        def write_then_stop(*a, **kw):  # the person presses stop while the resume is written
            out = real(*a, **kw)
            self.c.post("/api/v1/autopilot/stop", {})
            return out
        with mock.patch.object(self.c.api.tasks, "_write", side_effect=write_then_stop):
            self.c.post("/api/v1/autopilot", {"paths": [str(f)]})  # one action
            rec = self.c.wait("autopilot", 600)  # it ends
        st = self.steps(rec)
        self.assertEqual("done", st["write"])  # the step in progress finished
        self.assertEqual("skipped", st["figures"])  # the rest did not run
        self.assertTrue(rec["result"]["stopped"])  # and the page says it was stopped
        self.assertEqual([], self.built)  # nothing typeset


class Deliver(unittest.TestCase):
    """What reaches the Desktop, the person's own writing rules and the resume's photo."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-deliver-"))  # the data folder
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old = os.environ.get("OFFEROWL_DESKTOP")  # put back afterwards
        os.environ["OFFEROWL_DESKTOP"] = str(self.tmp / "Desktop")  # the exports land here
        self.addCleanup(lambda: os.environ.pop("OFFEROWL_DESKTOP", None) if self.old is None else os.environ.__setitem__("OFFEROWL_DESKTOP", self.old))
        office = mock.patch.dict(os.environ, {"OFFEROWL_OFFICE": "0"})  # the Word file is made ready, and no Office of this PC is started
        office.start()
        self.addCleanup(office.stop)
        self.c = Client(self.tmp / "data")  # the API
        self.c.post("/api/v1/example", {"lang": "ko"})  # the fictional person, so the files get a name
        self.c.wait("ingest", 60)
        self.c.post("/api/v1/facts/keep-all", {})
        self.ed = self.c.api.tasks.build_dir("-general", "ko")  # an edition, made by hand below
        self.ed.mkdir(parents=True)
        for f in ("resume.pdf", "deck.pdf"):  # one-page PDFs with their title and author, as the engine writes them
            write_pdf(self.ed / f, [[(72, 72, 12, "Gildong Hong")]])
            pdfmeta.stamp(self.ed / f, f"홍길동 {f}", "홍길동")
        make_docx(self.ed / "resume.docx")  # a Word copy beside them, as the typesetting writes one
        from apps.api.tasks import file_hash  # what the build records
        self.record = {"pages": 1, "issues": [], "hashes": {f: file_hash(self.ed / f) for f in ("resume.pdf", "deck.pdf")}}
        (self.ed / "build.json").write_text(json.dumps(self.record), encoding="utf-8")

    def desk(self) -> list[str]:
        return sorted(p.name for p in (self.tmp / "Desktop").iterdir()) if (self.tmp / "Desktop").is_dir() else []

    def test_the_pdfs_alone_unless_word_files_are_asked_for(self):
        names = self.c.api.tasks.export("-general", "ko")
        self.assertEqual(2, len(names))  # the resume and the deck
        self.assertTrue(all(n.endswith(".pdf") for n in self.desk()), self.desk())  # no Word file
        self.c.post("/api/v1/settings", {"export_extras": True})  # asked for
        self.assertTrue(any(n.endswith(".docx") for n in self.c.api.tasks.export("-general", "ko")))  # now it goes too

    def test_an_english_edition_s_files_carry_the_english_name(self):
        en = self.c.api.tasks.build_dir("-general", "en")  # the English edition, made by hand as above
        en.mkdir(parents=True)
        for f, word in (("resume.pdf", "Resume"), ("deck.pdf", "Portfolio")):  # titled as the engine titles them
            write_pdf(en / f, [[(72, 72, 12, "Gildong Hong")]])
            pdfmeta.stamp(en / f, f"Gildong Hong {word}", "Gildong Hong")
        from apps.api.tasks import file_hash  # what the build records
        (en / "build.json").write_text(json.dumps({"pages": 1, "issues": [], "hashes": {f: file_hash(en / f) for f in ("resume.pdf", "deck.pdf")}}),
                                       encoding="utf-8")
        self.assertEqual(["Gildong Hong Resume.pdf", "Gildong Hong Portfolio.pdf"], self.c.api.tasks.export("-general", "en"))  # a foreign recruiter's view
        self.assertEqual(["홍길동 이력서.pdf", "홍길동 포트폴리오.pdf"], self.c.api.tasks.export("-general", "ko"))  # the Korean ones as before

    def test_a_document_that_failed_its_checks_never_goes(self):
        (self.ed / "build.json").write_text(json.dumps({**self.record, "issues": ["page 3 of 2"]}), encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            self.c.api.tasks.export("-general", "ko")
        self.assertEqual("checks_failed", str(cm.exception))
        self.assertEqual([], self.desk())  # nothing on the Desktop

    def test_the_letters_failed_checks_keep_every_document_home(self):
        (self.ed / "build.json").write_text(json.dumps({**self.record, "cover": {"state": "done", "pages": 1, "issues": ["check_failed"]}}), encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            self.c.api.tasks.export("-general", "ko")
        self.assertEqual("checks_failed", str(cm.exception))
        self.assertEqual([], self.desk())  # the resume and the deck stay too

    def test_an_edition_that_recorded_no_bytes_is_made_again(self):
        (self.ed / "build.json").write_text(json.dumps({"pages": 1, "issues": []}), encoding="utf-8")  # made before the checked delivery
        with self.assertRaises(ValueError) as cm:
            self.c.api.tasks.export("-general", "ko")
        self.assertEqual("changed", str(cm.exception))
        self.assertEqual([], self.desk())

    def test_a_pdf_the_check_never_saw_never_goes(self):
        write_pdf(self.ed / "cover.pdf", [[(72, 72, 12, "Gildong Hong")]])  # a letter put in after the record was written
        pdfmeta.stamp(self.ed / "cover.pdf", "홍길동 자기소개서", "홍길동")
        with self.assertRaises(ValueError) as cm:
            self.c.api.tasks.export("-general", "ko")
        self.assertEqual("changed", str(cm.exception))
        self.assertEqual([], self.desk())

    def test_a_copy_that_does_not_read_back_takes_every_copy_away(self):
        from apps.api.tasks import Tasks  # its reading back, made to fail for the deck
        with mock.patch.object(Tasks, "reads_back", side_effect=lambda copy, src: src.name != "deck.pdf"):
            with self.assertRaises(ValueError) as cm:
                self.c.api.tasks.export("-general", "ko")
        self.assertEqual("copy_unreadable", str(cm.exception))
        self.assertEqual([], self.desk())  # the resume's copy, made first, went with it

    def test_a_pdf_changed_after_its_check_never_goes(self):
        write_pdf(self.ed / "resume.pdf", [[(72, 72, 12, "Someone else")]])  # replaced after the check
        with self.assertRaises(ValueError) as cm:
            self.c.api.tasks.export("-general", "ko")
        self.assertEqual("changed", str(cm.exception))

    def test_a_pdf_still_named_by_the_build_is_made_again_before_anything_goes(self):
        write_pdf(self.ed / "deck.pdf", [[(72, 72, 12, "Gildong Hong")]])
        pdfmeta.stamp(self.ed / "deck.pdf", "owl_1a2b3c4d_ko_deck", "홍길동")  # the browser's file name as its title
        rec = {**self.record, "hashes": {**self.record["hashes"], "deck.pdf": __import__("apps.api.tasks", fromlist=["file_hash"]).file_hash(self.ed / "deck.pdf")}}
        (self.ed / "build.json").write_text(json.dumps(rec), encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            self.c.api.tasks.export("-general", "ko")
        self.assertEqual("changed", str(cm.exception))
        self.assertEqual([], self.desk())  # not even the resume, which was fine

    def test_a_letter_whose_checks_never_ran_counts_as_failed(self):
        t = self.c.api.tasks
        cdir = self.ed / "cover"  # a letter written before
        cdir.mkdir()
        (cdir / "cover.json").write_text("{}", encoding="utf-8")

        def step(cover, job_id, argv):  # the typesetting works, the check stops before it writes its result
            if argv[0] == "build":
                write_pdf(cdir / "cover.pdf", [[(72, 72, 12, "Gildong Hong")]])
                return 0
            return 2
        with mock.patch.object(t, "cover_available", return_value=True), mock.patch.object(t, "engine_ready", return_value=""), \
                mock.patch.object(t, "_cover_step", side_effect=step), mock.patch.object(t, "_previews", return_value=1):
            got = t._write_cover("-general", "ko", self.ed, True, False)
        self.assertEqual(("done", ["check_failed"]), (got["state"], got["issues"]))  # never a clean letter

    def test_the_persons_rules_reach_the_checks_and_leave_with_the_edition(self):
        self.c.post("/api/v1/style", {"name": "mine", "pack": {"banned_chars": "—"}})
        t = self.c.api.tasks
        import resume  # src/resume.py: how the checks reach the container
        seen = {}

        def sh(argv, *a, **kw):  # the check's command line
            seen["style"] = argv[argv.index("--style") + 1]
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(resume, "sh", side_effect=sh), mock.patch.object(resume, "rel", side_effect=lambda p: "staged/" + pathlib.Path(p).name):
            t._check("profile.json", self.ed / "resume.pdf", self.ed / "deck.pdf", 2)
        self.assertEqual("staged/mine.json", seen["style"])  # a path the container sees, not the workspace's
        staged = ROOT / resume.rel(t.style_spec())  # where the real staging puts it
        self.addCleanup(staged.unlink, True)
        self.assertTrue(staged.is_file())
        t._clean_engine("-general", "ko", self.ed)
        self.assertFalse(staged.exists())  # it leaves with the edition's other working copies

    def test_a_rules_file_is_checked_kept_and_used(self):
        with self.assertRaises(Exception):  # a pattern that would stop every check later
            self.c.post("/api/v1/style", {"name": "mine", "pack": {"banned_patterns": [["(unclosed", "why"]]}})
        for odd in ({"resume": {"numbers": "sometimes"}}, {"cover": {"numbers": "often"}}, {"cover": {"banned_words": "hype"}}, {"resume": {"rules": "be brief"}}):  # what the writers' loader stops on, or walks as a list
            with self.assertRaises(Exception, msg=odd):
                self.c.post("/api/v1/style", {"name": "odd", "pack": odd})
        self.assertNotIn("odd", self.c.get("/api/v1/state")["styles"])  # none of them kept
        got = self.c.post("/api/v1/style", {"name": "mine", "pack": {"banned_chars": "—", "resume": {"numbers": "forbid"}}})
        self.assertEqual("mine", got["style"])  # kept under its name
        st = self.c.get("/api/v1/state")
        self.assertEqual((["mine"], "mine"), (st["styles"], st["settings"]["style"]))  # listed and chosen
        spec = self.c.api.tasks.style_spec()  # what every draft and check is given
        self.assertTrue(pathlib.Path(spec).as_posix().endswith("style/mine.json"), spec)  # the path as this system writes it
        import draft  # src/draft.py: the pack as the drafting step reads it
        self.assertEqual("—", draft.style_pack(spec)["banned_chars"])
        self.c.post("/api/v1/settings", {"style": "default"})
        self.assertEqual("default", self.c.api.tasks.style_spec())  # back to the shipped rules

    def test_a_photo_is_a_jpeg_or_a_png_and_goes_on_the_resume(self):
        api = self.c.api
        with self.assertRaises(ValueError):
            api.set_photo(b"GIF89a not a photo")  # refused by what it is
        with self.assertRaises(ValueError):
            api.set_photo(JPEG[:30])  # a JPEG cut short
        api.set_photo(JPEG)  # a JPEG
        st = self.c.get("/api/v1/state")["photo"]
        self.assertTrue(st and st["on"])  # kept, and on the resume
        self.assertEqual("photo.jpg", api.tasks.photo_for_build().name)  # the build passes it on
        self.c.post("/api/v1/settings", {"photo": False})
        self.assertIsNone(api.tasks.photo_for_build())  # taken off the resume, kept in the workspace
        self.c.post("/api/v1/photo/remove", {})
        self.assertIsNone(self.c.get("/api/v1/state")["photo"])  # gone

    def test_a_photo_keeps_its_picture_and_its_turn_but_not_what_the_phone_wrote(self):
        from apps.api import photo  # the reader of the turn
        head, rest = JPEG[:20], JPEG[20:]  # the start and JFIF, then the tables, the frame and the scan
        phone = (segment(0xE1, b"Exif\x00\x00" + camera_tiff(6))  # the maker, and stored on its side
                 + segment(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>GPSLatitude 37.5665</x:xmpmeta>")  # where
                 + segment(0xED, b"Photoshop 3.0\x00 by-line") + segment(0xFE, b"taken at home"))  # an editor's block, a comment
        self.c.api.set_photo(head + phone + rest)
        kept = self.c.api.photo_file().read_bytes()
        for word in (b"PhoneCo", b"GPSLatitude", b"Photoshop", b"taken at home"):
            self.assertNotIn(word, kept)
        self.assertTrue(kept.startswith(head) and kept.endswith(rest))  # the picture itself, byte for byte
        self.assertEqual(6, photo.orientation(kept[kept.index(b"Exif\x00\x00") + 6:]))  # still turned, so it prints upright
        upright = PNG[:33] + png_chunk(b"tEXt", b"Author\x00Gildong") + png_chunk(b"tIME", b"\x07\xea\x0b\x06\x0c\x00\x00") + png_chunk(b"eXIf", camera_tiff(1)) + PNG[33:]
        self.c.api.set_photo(upright)
        self.assertEqual(PNG, self.c.api.photo_file().read_bytes())  # the PNG as drawn, with nothing of the rest


class Questions(unittest.TestCase):
    """An application's own questions, each answered from the kept facts within its limit, checked, edited and saved."""

    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ("OFFEROWL_PANEL_AGENT", "OFFEROWL_DESKTOP")}  # put back afterwards
        os.environ["OFFEROWL_PANEL_AGENT"] = "standin"  # no real model
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-qa-"))
        os.environ["OFFEROWL_DESKTOP"] = str(self.tmp / "Desktop")
        self.c = Client(self.tmp / "data")
        self.c.post("/api/v1/example", {"lang": "ko"})  # the fictional person
        self.c.wait("ingest", 60)
        self.c.post("/api/v1/facts/keep-all", {})
        self.jid = self.c.post("/api/v1/jobs", {"posting": POSTING})["job"]  # a job
        self.c.wait(f"analyze:{self.jid}", 120)

    def tearDown(self):
        for k, v in self.env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def questions(self):
        return next(j for j in self.c.get("/api/v1/state")["jobs"] if j["id"] == self.jid)["questions"]

    def test_answers_come_from_the_facts_within_the_limit(self):
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [{"text": "지원 동기와 입사 후 하고 싶은 일을 쓰세요.", "limit": 160, "unit": "chars"},
                                                                             {"text": "Describe a system you built.", "limit": 60, "unit": "words"}]})
        self.c.post("/api/v1/jobs/questions/write", {"job": self.jid})
        self.assertEqual("done", self.c.wait(f"answers:{self.jid}", 120)["state"])
        qs = self.questions()
        self.assertEqual(2, len(qs))
        for q in qs:  # each answered, within its limit, with what it rests on, and nothing to fix
            self.assertTrue(q["answer"], q)
            self.assertLessEqual(q["count"], q["limit"], q)
            self.assertTrue(q["cited"], q)
            self.assertEqual([], q["issues"], q)

    def test_an_edit_is_checked_and_a_flawed_answer_stays_home(self):
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [{"text": "지원 동기를 쓰세요.", "limit": 160, "unit": "chars"}]})
        self.c.post("/api/v1/jobs/questions/write", {"job": self.jid})
        self.c.wait(f"answers:{self.jid}", 120)
        good = self.questions()[0]["answer"]
        self.c.post("/api/v1/jobs/questions/edit", {"job": self.jid, "id": "q1", "answer": good + " 처리량을 97% 늘렸다."})  # a number no fact holds
        q = self.questions()[0]
        self.assertTrue(any(i.startswith("unsupported:") for i in q["issues"]), q["issues"])  # caught
        with self.assertRaises(ValueError) as cm:  # never sent while it needs a fix
            self.c.api.tasks.export_answers(self.jid)
        self.assertEqual("answers_need_attention", str(cm.exception))
        self.c.post("/api/v1/jobs/questions/edit", {"job": self.jid, "id": "q1", "answer": good})  # put right
        names = self.c.api.tasks.export_answers(self.jid)
        self.assertEqual(1, len(names))
        text = (self.tmp / "Desktop" / names[0]).read_text(encoding="utf-8")
        self.assertIn("지원 동기를 쓰세요.", text)  # the question
        self.assertIn(good, text)  # and its answer

    def test_a_changed_question_loses_its_answer_and_an_unchanged_one_keeps_it(self):
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [{"text": "A?", "limit": 100}, {"text": "지원 동기를 쓰세요.", "limit": 160}]})
        self.c.post("/api/v1/jobs/questions/edit", {"job": self.jid, "id": "q2", "answer": "직접 쓴 답"})
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [{"text": "지원 동기를 쓰세요.", "limit": 160}, {"text": "B?", "limit": 100}]})  # reordered, one new
        qs = self.questions()
        self.assertEqual(("직접 쓴 답", ""), (qs[0]["answer"], qs[1]["answer"]))  # the kept one moved with its answer
        self.assertEqual(["q2", "q3"], [q["id"] for q in qs])  # and with its id; the new one is not given the removed one's

    def test_ids_stay_with_their_questions_and_a_late_answer_lands_nowhere_else(self):
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [{"text": "A?", "limit": 100}, {"text": "지원 동기를 쓰세요.", "limit": 160}]})
        self.assertEqual(["q1", "q2"], [q["id"] for q in self.questions()])
        from apps.api import answers as A  # the writer, held up for the first question
        real = A.write

        def write(q, *a, **kw):  # the person removes the question while its answer is written, and adds another
            if q["text"] == "A?":
                self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [{"text": "지원 동기를 쓰세요.", "limit": 160}, {"text": "C?", "limit": 100}]})
                return {**q, "answer": "늦게 온 답", "cites": [], "state": "drafted", "issues": []}
            return real(q, *a, **kw)
        with mock.patch.object(A, "write", side_effect=write):
            self.c.post("/api/v1/jobs/questions/write", {"job": self.jid})
            self.c.wait(f"answers:{self.jid}", 120)
        qs = self.questions()
        self.assertEqual([("q2", "지원 동기를 쓰세요."), ("q3", "C?")], [(q["id"], q["text"]) for q in qs])  # the kept one has its id; the new one a number nobody had
        self.assertNotIn("늦게 온 답", [q["answer"] for q in qs])  # the late answer went nowhere
        self.assertTrue(qs[0]["answer"])  # the kept question was answered
        self.assertEqual("", qs[1]["answer"])  # the new one was never asked

    def test_a_new_limit_is_checked_at_once_and_again_at_the_export(self):
        q = {"text": "지원 동기를 쓰세요.", "limit": 160, "unit": "chars"}
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [q]})
        self.c.post("/api/v1/jobs/questions/write", {"job": self.jid})
        self.c.wait(f"answers:{self.jid}", 120)
        self.assertEqual([], self.questions()[0]["issues"])
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [{**q, "limit": 20}]})  # the form's limit was shorter
        got = self.questions()[0]
        self.assertTrue(got["answer"])  # the answer stays
        self.assertTrue(any(i.startswith("too_long:") for i in got["issues"]), got["issues"])  # and is over the new limit at once
        with self.assertRaises(ValueError) as cm:
            self.c.api.tasks.export_answers(self.jid)
        self.assertEqual("answers_need_attention", str(cm.exception))
        f = self.c.api.ws.job_dir(self.jid) / "questions.json"  # a stored list that says nothing is not trusted either
        data = json.loads(f.read_text(encoding="utf-8"))
        data["questions"][0]["issues"] = []
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.c.api.tasks.export_answers(self.jid)
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [q]})  # back to the form's real limit
        self.assertEqual([], self.questions()[0]["issues"])
        self.assertEqual(1, len(self.c.api.tasks.export_answers(self.jid)))

    def test_a_forms_questions_are_read_with_their_limits(self):
        from apps.api.answers import parse_questions
        form = ("자기소개서 문항\n1. 지원 동기와 입사 후 포부를 기술해 주세요. (공백 포함 700자 이내)\n"
                "2. 가장 어려웠던 기술적 문제와 해결 과정을 서술하십시오.\n최대 1,000자\n"
                "3) 협업 경험을 말씀해 주세요 (500자)\nQ4. Why do you want to join us? (300 words)\n5. 성장 과정(가족, 학교)을 기술하세요 [1500byte]")
        got = [(q["text"], q["limit"], q["unit"]) for q in parse_questions(form)]
        self.assertEqual([("지원 동기와 입사 후 포부를 기술해 주세요.", 700, "chars"), ("가장 어려웠던 기술적 문제와 해결 과정을 서술하십시오.", 1000, "chars"),
                          ("협업 경험을 말씀해 주세요", 500, "chars"), ("Why do you want to join us?", 300, "words"),
                          ("성장 과정(가족, 학교)을 기술하세요", 750, "chars")], got)  # a limit on the next line belongs to the question; bytes are halved

    def test_a_posting_brings_its_questions_but_never_its_duty_lines(self):
        posting = POSTING + "\n\n주요 업무\n- 결제 승인 서비스를 설계하고 운영하실 분\n\n지원서 문항\n① 본인의 강점을 설명해 주세요 (800자 이내)\n② 이 직무에 지원한 이유는 무엇인가요?\n"
        jid = self.c.post("/api/v1/jobs", {"posting": posting})["job"]
        self.c.wait(f"analyze:{jid}", 120)
        qs = next(j for j in self.c.get("/api/v1/state")["jobs"] if j["id"] == jid)["questions"]
        self.assertEqual([("본인의 강점을 설명해 주세요", 800), ("이 직무에 지원한 이유는 무엇인가요?", 500)], [(q["text"], q["limit"]) for q in qs])

    def test_pasted_questions_join_the_kept_ones_once(self):
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [{"text": "지원 동기를 쓰세요.", "limit": 160}]})
        got = self.c.post("/api/v1/jobs/questions/paste", {"job": self.jid, "text": "1. 지원 동기를 쓰세요. (160자)\n2. 입사 후 하고 싶은 일을 기술해 주세요. (600자 이내)"})
        self.assertEqual(1, got["added"])  # the one already kept is not added twice
        self.assertEqual([("지원 동기를 쓰세요.", 160, "q1"), ("입사 후 하고 싶은 일을 기술해 주세요.", 600, "q2")], [(q["text"], q["limit"], q["id"]) for q in self.questions()])
        with self.assertRaises(Exception):  # nothing that reads as a question
            self.c.post("/api/v1/jobs/questions/paste", {"job": self.jid, "text": "안녕하세요"})

    def test_a_saved_form_page_or_text_file_brings_its_questions(self):
        page = "<html><body><h2>자기소개서</h2><p>1. 지원 동기를 기술해 주세요. (700자 이내)</p><p>2. 본인의 강점을 설명해 주세요. (최대 1,000자)</p><script>var x=1</script></body></html>"
        self.assertEqual(2, self.c.api.questions_from_file(self.jid, "form.html", page.encode("utf-8")))
        self.assertEqual(1, self.c.api.questions_from_file(self.jid, "q.txt", "Q3. Why us? (250 words)".encode("utf-8")))
        self.assertEqual([700, 1000, 250], [q["limit"] for q in self.questions()])
        with self.assertRaises(ValueError):  # a kind with no reader
            self.c.api.questions_from_file(self.jid, "form.xlsx", b"PK")

    def test_a_limit_ocr_misread_is_mended_or_left_out(self):
        from apps.api.answers import parse_questions
        got = parse_questions("1. 경험을 서술하십시오. (최대 ]000자)\n2. 강점을 설명해 주세요. (|,500자)\n3. 목표를 기술해 주세요. (000자)")
        self.assertEqual([1000, 1500, 500], [q["limit"] for q in got])  # a 1 read as ] or | is a 1; a number that lost its start is the usual limit

    def test_scenes_written_before_join_the_kit(self):
        kit = ROOT / "examples" / "interview" / "jobs" / "gamma-platform" / "interview"  # the fictional kit's scene files
        with self.assertRaises(ValueError):  # a file with no scene is refused
            self.c.api.add_scenes(self.jid, "notes.md", "그냥 메모입니다.".encode("utf-8"))
        got = self.c.api.add_scenes(self.jid, "qa.md", (kit / "qa.md").read_bytes())  # question scripts
        self.assertGreater(got["scenes"], 0)
        deep = self.c.api.add_scenes(self.jid, "deep.md", (kit / "deep.md").read_bytes())  # resume deep dives keep their role
        iv = self.c.api.ws.job_dir(self.jid) / "interview"
        roles = {s["file"]: s["role"] for s in json.loads((iv / "kit.json").read_text(encoding="utf-8"))["sources"] if s["file"] != "@stories"}
        self.assertEqual("deep", roles[deep["file"]])
        self.assertEqual("scenes", roles[got["file"]])
        again = self.c.api.add_scenes(self.jid, "qa.md", (kit / "qa.md").read_bytes())  # the same name twice: never over the first
        self.assertNotEqual(got["file"], again["file"])

    def test_a_run_for_the_job_answers_its_questions(self):
        self.c.post("/api/v1/jobs/questions", {"job": self.jid, "questions": [{"text": "지원 동기를 쓰세요.", "limit": 160}]})
        with mock.patch.object(self.c.api.tasks, "_build", side_effect=lambda job_id, lang, *a, **kw: self.c.api.tasks._set(f"build:{job_id}", state="done")):  # no typesetting
            self.c.post("/api/v1/autopilot", {"job": self.jid})
            rec = self.c.wait("autopilot", 600)
        self.assertIn("answers", [s["id"] for s in rec["steps"]], rec)  # a step of its own
        self.assertEqual("done", {s["id"]: s["state"] for s in rec["steps"]}["answers"], rec)
        self.assertTrue(self.questions()[0]["answer"])  # answered


class Ledger(unittest.TestCase):
    """The profile's own lists (papers, certificates, press) as a resume prints them, by the person's rules."""

    STYLE = {"banned_chars": "\u2014", "banned_patterns": [["정보처리기능사", "never held"]]}
    PROFILE = {"sections": [
        {"title": "자격증", "body_md": "| 구분 | 취득일 |\n|---|---|\n| 네트워크관리사 | 2012.09.11 |\n| 정보처리기능사 | 2010.12.09 |\n<!-- a note\n정보처리기능사는 빼기 -->"},
        {"title": "논문", "body_md": "## SCIE \u2014 주저자 3편\n\n| 제목 | 연도 |\n|---|---|\n| A | 2021 |\n\n## 학회\n\n| 제목 | 연도 |\n|---|---|\n| B | 2019 |"},
        {"title": "언론", "body_md": "- 기사 하나 \u2014 https://example.com/a\n- 기사 둘 \u2014 https://example.com/b"},
        {"title": "직접 고른 것", "resume": True, "body_md": "- 링크 https://example.com/c"}]}

    def test_rules_take_out_rows_and_characters_and_a_list_of_links(self):
        from apps.api.tasks import ledger_for_resume
        got = {s["title"]: s for s in ledger_for_resume(self.PROFILE, self.STYLE)["sections"]}
        self.assertNotIn("정보처리기능사", got["자격증"]["body_md"])  # the row, and the note that named it
        self.assertNotIn("<!--", got["자격증"]["body_md"])
        self.assertIn("네트워크관리사", got["자격증"]["body_md"])
        self.assertIn("## SCIE: 주저자 3편", got["논문"]["body_md"])  # the banned dash became a colon
        self.assertIs(False, got["언론"]["resume"])  # links alone stay out of a resume
        self.assertNotIn("resume", {k for k in got["직접 고른 것"] if got["직접 고른 것"]["resume"] is not True})  # the person's own mark stays

    def test_an_edition_over_its_limit_keeps_each_lists_first_part(self):
        from apps.api.tasks import ledger_for_resume
        from apps.api.tasks import ledger_parts
        self.assertEqual(2, ledger_parts(self.PROFILE))  # the papers have two parts
        got = {s["title"]: s for s in ledger_for_resume(self.PROFILE, self.STYLE, compact=1)["sections"]}
        self.assertIn("| A | 2021 |", got["논문"]["body_md"])
        self.assertNotIn("학회", got["논문"]["body_md"])  # the second part went
        got = {s["title"]: s for s in ledger_for_resume(self.PROFILE, self.STYLE, compact=1, drop=1)["sections"]}
        self.assertIs(False, got["직접 고른 것"]["resume"])  # the last list that would print went first
        self.assertIsNot(False, got["논문"].get("resume"))  # the ones before it stay

    def test_an_empty_list_never_hides_a_ledger_body(self):
        import subprocess
        prof = {"schema": "resume-profile/0.1", "person": {"name": "홍길동", "email": "a@example.com"}, "roles": [],
                "sections": [{"title": "수상", "items": [], "body_md": "| 내용 | 일자 |\n|---|---|\n| 우수상 | 2019.02 |"}]}
        f = pathlib.Path(tempfile.mkdtemp()) / "p.json"
        self.addCleanup(shutil.rmtree, f.parent, True)
        f.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
        js = "const L=require(process.argv[1]); const p=L.load(process.argv[2], 'ko'); console.log(JSON.stringify(p.sections[0].blocks||null))"
        out = subprocess.run(["node", "-e", js, str(ROOT / "src" / "profile_loader.js"), str(f)], capture_output=True, text=True, encoding="utf-8")
        self.assertIn("우수상", out.stdout, out.stderr[-500:])  # the table is read, not hidden by the empty list


class OwnResumeText(unittest.TestCase):
    """A profile that already holds its resume text: a run keeps it, an edition prints each language's own lines."""

    def test_a_runs_general_edition_keeps_the_resume_text_the_profile_has(self):
        env = os.environ.get("OFFEROWL_PANEL_AGENT")
        os.environ["OFFEROWL_PANEL_AGENT"] = "standin"  # no real model
        self.addCleanup(lambda: os.environ.pop("OFFEROWL_PANEL_AGENT", None) if env is None else os.environ.__setitem__("OFFEROWL_PANEL_AGENT", env))
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-own-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        c = Client(tmp / "data")
        c.post("/api/v1/example", {"lang": "ko"})  # a complete profile: items, summary, competencies, about
        c.wait("ingest", 60)
        c.post("/api/v1/facts/keep-all", {})
        before = json.dumps(c.api.tasks.facts.profile().get("competencies"), ensure_ascii=False)
        got = c.api.tasks._write("-general", "ko")  # as a run calls it
        from apps.api import drafts as D
        draft, _ = D.load(c.api.tasks, "-general")
        self.assertEqual(before, json.dumps((draft or c.api.tasks.facts.profile()).get("competencies"), ensure_ascii=False))  # the person's words, not new ones
        self.assertIn(got["state"], ("done", "needs_agent"))

    def test_an_edition_prints_its_own_languages_lines_and_carries_logo_files(self):
        import subprocess
        tile = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-logo-"))
        self.addCleanup(shutil.rmtree, tile, True)
        write_pdf(tile / "x.pdf", [[(72, 72, 12, "x")]])  # any file stands in for the picture: only its staging is tested here
        prof = {"schema": "resume-profile/0.1", "person": {"name": "홍길동", "email": "a@example.com"},
                "roles": [{"key": "alpha", "org": "알파페이", "logo": str(tile / "x.pdf"),
                           "projects": [{"title": "한국어 항목", "summary": "한국어 문장", "lang": "ko"}, {"title": "English item", "summary": "An English line", "lang": "en"}]}],
                "skills": [{"category": "Languages", "items": ["Go"], "lang": "ko"}, {"category": "Data", "items": ["SQL"], "lang": "en"}],
                "sections": [{"title": "기타", "lang": "ko", "lines": [["자격", "", "2019"]]}, {"title": "Other", "lang": "en", "lines": [["Cert", "", "2019"]]}]}
        f = tile / "p.json"
        f.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
        js = ("const L=require(process.argv[1]); for (const g of ['ko','en']) { const p=L.load(process.argv[2], g); "
              "console.log(g, p.roles[0].projects.map(x=>x.title).join('|'), p.skills.map(x=>x.category).join('|'), p.sections.map(x=>x.title).join('|')); }")
        out = subprocess.run(["node", "-e", js, str(ROOT / "src" / "profile_loader.js"), str(f)], capture_output=True, text=True, encoding="utf-8").stdout
        self.assertIn("ko 한국어 항목 Languages 기타", out)
        self.assertIn("en English item Data Other", out)
        import resume  # src/resume.py: a profile outside the repository is staged with its logo files
        staged = json.loads((ROOT / resume.rel(str(f))).read_text(encoding="utf-8"))
        self.addCleanup(lambda: [(ROOT / x).unlink(missing_ok=True) for x in (resume.rel(str(f)), staged["roles"][0]["logo"])])
        self.assertTrue(staged["roles"][0]["logo"].startswith("output/_inputs/"))  # where the container sees it
        self.assertTrue((ROOT / staged["roles"][0]["logo"]).is_file())


class WindowsOcr(unittest.TestCase):
    """A picture on a Windows PC with no tesseract is read by the OCR engine Windows ships (src/ingest.py, apps/api/winocr.ps1)."""

    def test_windows_reads_a_screenshot_itself_korean_first(self):
        import ingest  # src/ingest.py
        calls = []

        def run(cmd, **kw):  # PowerShell, as Windows answers
            calls.append(cmd)
            return mock.Mock(returncode=0 if cmd[-1] == "ko" else 3, stdout="1. 지원 동기를 기술해 주세요. (700자 이내)\n" if cmd[-1] == "ko" else "")
        with mock.patch.object(ingest.sys, "platform", "win32"), mock.patch("shutil.which", return_value=None), \
                mock.patch.object(ingest.subprocess, "run", side_effect=run):
            text = ingest.ocr(pathlib.Path("form.png"))
        self.assertIn("700자", text)
        self.assertEqual(("powershell", "winocr.ps1", "ko"), (calls[0][0], pathlib.Path(calls[0][5]).name, calls[0][-1]))
        self.assertTrue((ROOT / "apps" / "api" / "winocr.ps1").is_file())  # the script the app carries

    def test_no_korean_pack_falls_back_to_english_and_then_to_nothing(self):
        import ingest
        langs = []
        with mock.patch.object(ingest.sys, "platform", "win32"), mock.patch("shutil.which", return_value=None), \
                mock.patch.object(ingest.subprocess, "run", side_effect=lambda cmd, **kw: langs.append(cmd[-1]) or mock.Mock(returncode=3, stdout="")):
            self.assertEqual("", ingest.ocr(pathlib.Path("form.png")))
        self.assertEqual(["ko", "en-US"], langs)


class WslDesktop(unittest.TestCase):
    """Under WSL the PDFs go to the Windows Desktop the person sees, and "Open" asks Windows' Explorer (apps/api/delivery.py)."""

    def setUp(self):
        from apps.api import delivery  # the functions under test, where they live (tasks.py names them too)
        self.T = delivery
        self.T.WSL_DESKTOP.clear()  # no answer kept from another test
        self.addCleanup(self.T.WSL_DESKTOP.clear)
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-wsl-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def fake_run(self, ps_out: bytes, wsl_out: str):
        """subprocess.run as WSL's interop answers: PowerShell's bytes, then wslpath's line."""
        def run(cmd, **kw):
            if cmd[0] == "powershell.exe":  # the Desktop, as Windows names it
                return mock.Mock(returncode=0, stdout=ps_out)
            return mock.Mock(returncode=0, stdout=wsl_out)  # wslpath -u
        return run

    def test_the_windows_desktop_is_used(self):
        win = self.tmp / "바탕 화면"  # a Korean OneDrive Desktop
        win.mkdir()
        with mock.patch.object(self.T.subprocess, "run", side_effect=self.fake_run("C:\\Users\\a\\OneDrive\\바탕 화면\r\n".encode("utf-8"), str(win) + "\n")):
            self.assertEqual(win, self.T.windows_desktop())  # read as UTF-8, mapped by wslpath
        self.assertEqual([win], self.T.WSL_DESKTOP)  # asked once

    def test_no_answer_means_the_linux_desktop(self):
        with mock.patch.object(self.T.subprocess, "run", side_effect=OSError("no interop")):
            self.assertIsNone(self.T.windows_desktop())  # the Linux Desktop is used then

    def test_a_greeting_is_not_a_folder(self):
        with mock.patch.object(self.T.subprocess, "run", side_effect=self.fake_run(b"Welcome to PowerShell\r\n", "")):
            self.assertIsNone(self.T.windows_desktop())  # only a drive path counts

    def test_open_asks_explorer_with_the_windows_path(self):
        popen = mock.Mock()
        with mock.patch.object(self.T, "in_wsl", return_value=True), mock.patch.object(self.T.shutil, "which", side_effect=lambda n: "/x/" + n if n == "explorer.exe" else None), \
                mock.patch.object(self.T.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="C:\\Users\\a\\Desktop\n")), \
                mock.patch.object(self.T.subprocess, "Popen", popen), mock.patch.object(self.T.sys, "platform", "linux"):
            self.assertTrue(self.T.open_in_files(pathlib.Path("/mnt/c/Users/a/Desktop")))
        self.assertEqual(["explorer.exe", "C:\\Users\\a\\Desktop"], popen.call_args[0][0])  # Explorer, on the Windows path
        self.assertTrue(popen.call_args[1]["start_new_session"])  # never waited on


if __name__ == "__main__":  # run directly
    unittest.main()
