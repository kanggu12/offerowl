"""What was taken off, on a fresh workspace with fictional data only: the Removed list, putting back, and deleting for good.

Deleting for good is checked by what is on disk: a fictional profile file, a job and a job's material each carry words found
nowhere else, and after their deletion no file under the data folder holds them, the undo steps included, while undo still
works. Putting back is checked after later changes, when undo can no longer reach the removal.

    python3 -m unittest tests/app/test_removed.py -v
"""
import io  # a backup in memory
import json  # requests, answers and the files on disk
import pathlib  # paths
import struct  # a picture made for the test
import sys  # the import path
import tempfile  # a profile file to upload
import time  # the asides' names
import urllib.parse  # upload names
import urllib.request  # uploads
import zipfile  # a backup's entries
import zlib  # a picture made for the test

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT))  # apps/ is found from here
sys.path.insert(0, str(ROOT / "tests" / "app"))  # the shared test case
from apps.panel import server  # noqa: E402  the running panel's API object
from test_panel import PanelCase, POSTING, q  # noqa: E402  one server and workspace per class, on the fictional example

SAMPLE = ROOT / "examples" / "sample_ko.json"  # the fictional person
SOURCE_WORDS = "ZQXJ7731"  # words only the fictional profile file of the first test carries
JOB_WORDS = "ZQXJ4410"  # words only the fictional job carries
MATERIAL_WORDS = "ZQXJ5521"  # words only the fictional job material carries


def png(rgb=(230, 120, 30), w=3, h=4) -> bytes:
    """A small PNG of one colour, drawn for the test."""
    rows = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))  # each row: no filter, then its pixels
    chunk = lambda kind, body: struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class TestRemoved(PanelCase):
    """Taking off, the list, putting back and deleting for good, on one workspace."""

    @property
    def api(self):  # the panel's API object, as its server holds it
        return server.Handler.panel

    def send(self, path: str, name: str, data: bytes) -> dict:  # a file sent as the page sends it
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST",
                                     headers={"Content-Type": "application/octet-stream", "X-File-Name": urllib.parse.quote(name)})
        with urllib.request.urlopen(req, timeout=20) as r:  # a hung server fails the test
            return json.loads(r.read())

    def traces(self, words: str) -> list[str]:
        """Every file under the data folder (the workspace and its undo steps, the settings, the log, anything beside them)
        that holds these words, as they are or in lower case (a job's folder name is made from its company's)."""
        found = []  # the files that hold them
        for f in sorted((self.tmp / "data").rglob("*")):  # every file, hidden folders too
            if f.is_file():
                data = f.read_bytes()
                if words.encode() in data or words.lower().encode() in data:
                    found.append(f.relative_to(self.tmp).as_posix())
        return found

    def removed(self) -> dict:  # the Removed list as the page reads it
        return self.get("/api/v1/removed")

    def row(self, rid: str) -> dict | None:  # one row of it
        return next((r for r in self.removed()["rows"] if r["id"] == rid), None)

    def fact_rows(self) -> list[dict]:  # the facts as the profile view reads them
        return self.get("/api/v1/facts")["rows"]

    def profile_file(self, words: str) -> pathlib.Path:
        """The fictional profile with some of its items renamed to carry words found nowhere else."""
        doc = json.loads(SAMPLE.read_text(encoding="utf-8"))
        doc["roles"][0]["org"] = f"{words} Labs"  # a role's company
        doc["roles"][0]["projects"][0]["title"] = f"{words} search"  # and one of its projects
        f = pathlib.Path(tempfile.mkdtemp(dir=self.tmp)) / f"{words.lower()}-profile.json"  # its name carries them too
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return f

    # ------------------------------------------------------------------ a source

    def test_a_source_deleted_for_good_leaves_nothing_and_undo_still_works(self):
        rec = self.upload(self.profile_file(SOURCE_WORDS))  # brought in
        self.post("/api/v1/materials/read", {"ids": [rec["id"]]})  # read as a profile file: no agent
        self.wait_task("ingest")
        mine = [r for r in self.fact_rows() if SOURCE_WORDS in json.dumps(r, ensure_ascii=False)]  # its facts that carry the words
        self.assertTrue(mine)
        self.post("/api/v1/facts/decide", {"cid": mine[0]["cid"], "action": "keep"})  # decisions the undo steps hold
        self.post("/api/v1/facts/decide", {"cid": mine[-1]["cid"], "action": "edit", "fields": {"title": f"{SOURCE_WORDS} edited"}})
        self.post("/api/v1/facts/keep-all", {})  # every fact kept
        self.post("/api/v1/facts/add", {"kind": "skill", "title": "Typed after", "statement": "A fact typed by the person"})  # a later change of their own
        st = self.post("/api/v1/materials/remove", {"id": rec["id"]})["state"]  # taken off
        self.assertGreaterEqual(st["removed"]["sources"], 1)  # counted for the page, by kind
        self.assertEqual(sum(v for k, v in st["removed"].items() if k != "all"), st["removed"]["all"])  # and in all
        row = self.row("source:" + rec["id"])
        self.assertEqual(time.strftime("%Y-%m-%d"), row["at"])  # with the day it went
        self.assertGreater(row["note"]["facts"], 0)  # and the facts a put-back brings
        self.assertEqual({"path": "/api/v1/removed/restore", "body": {"id": "source:" + rec["id"]}}, row["restore"])  # its routes
        self.assertFalse([r for r in self.fact_rows() if SOURCE_WORDS in json.dumps(r, ensure_ascii=False)])  # its facts are off the profile
        self.assertTrue(self.traces(SOURCE_WORDS))  # but nothing of it was deleted yet
        out = self.post("/api/v1/removed/delete", {"id": "source:" + rec["id"]})  # deleted for good
        self.assertEqual(["source:" + rec["id"]], out["deleted"])
        self.assertEqual([], self.traces(SOURCE_WORDS))  # no file holds its words: not the folder, not an undo step, not a setting
        self.assertIsNone(self.row("source:" + rec["id"]))  # off the list
        for f in sorted(self.api.ws.path(".history").glob("*.json")):  # every step still reads
            self.assertIsInstance(json.loads(f.read_text(encoding="utf-8")), dict, f.name)
        n = self.get("/api/v1/state")["history"]
        self.assertGreater(n, 0)  # the typed fact's step and the others stay
        self.post("/api/v1/history/undo", {"steps": 50})  # every step taken back
        self.assertEqual([], self.traces(SOURCE_WORDS))  # none of them brought it back
        self.assertNotIn(SOURCE_WORDS, json.dumps(self.fact_rows(), ensure_ascii=False))
        again = self.upload(self.profile_file("PLAIN0000"))  # a new file
        self.assertGreater(int(again["id"][1:]), int(rec["id"][1:]))  # never the id of the one deleted

    def test_a_source_comes_back_whole_after_later_changes(self):
        m = self.post("/api/v1/example", {})["material"]  # the fictional example
        self.wait_task("ingest")
        self.post("/api/v1/facts/keep-all", {})
        before = self.get("/api/v1/state")  # its facts kept, its details filled
        kept = before["facts"]["counts"]["kept"]
        self.assertTrue(before["details"].get("email"))
        self.post("/api/v1/materials/remove", {"id": m["id"]})  # taken off: its facts and details go
        st = self.get("/api/v1/state")
        self.assertLess(st["facts"]["counts"]["kept"], kept)
        self.assertFalse(st["details"].get("email"))  # the example's email left with it
        self.post("/api/v1/facts/add", {"kind": "skill", "title": "Later", "statement": "Typed after the removal"})  # undo no longer reaches the removal first
        out = self.post("/api/v1/removed/restore", {"id": "source:" + m["id"]})
        self.assertFalse(out["read_again"])  # whole
        st = out["state"]
        self.assertEqual(kept + 1, st["facts"]["counts"]["kept"])  # every fact as it was decided, and the one typed since
        self.assertEqual(before["details"]["email"], st["details"]["email"])  # its details back where they were empty
        self.assertIn(m["id"], [x["id"] for x in st["materials"]])  # on the list again
        self.assertIsNone(self.row("source:" + m["id"]))
        self.assertFalse(self.api.ws.path("sources", "removed", m["id"] + ".json").exists())  # what it took along is used
        self.assertEqual("undo_put_back", st["undo"]["code"])  # one undo takes it off again
        self.post("/api/v1/undo", {})
        self.assertIsNotNone(self.row("source:" + m["id"]))  # taken off again, and listed
        self.post("/api/v1/removed/restore", {"id": "source:" + m["id"]})  # back for the other tests
        self.post("/api/v1/removed/restore", {"id": "source:" + m["id"]}, expect=400)  # twice is a stale page

    # ------------------------------------------------------------------ a job and its materials

    def test_a_job_deleted_for_good_leaves_nothing(self):
        posting = POSTING.read_text(encoding="utf-8") + f"\n{JOB_WORDS} builds search for fictional shops.\n"  # a fictional posting with its words
        jid = self.post("/api/v1/jobs", {"posting": posting, "company": f"{JOB_WORDS} Corp", "role": "Backend"})["job"]
        self.wait_task("analyze:" + jid)
        self.post("/api/v1/tracker/next", {"job": jid})  # moved on the board
        self.post("/api/v1/reminders", {"job": jid, "at": "2030-01-02", "text": f"{JOB_WORDS} call back"})  # a reminder
        self.send(f"/api/v1/jobs/materials?job={q(jid)}", f"{JOB_WORDS} brief.md", f"# {JOB_WORDS}\n".encode())  # one of its materials
        self.post("/api/v1/interview/start", {"job": jid})  # its kit server, if it has a kit (none here: refused quietly)
        self.post("/api/v1/jobs/select", {"job": jid})  # in view
        self.post("/api/v1/jobs/remove", {"job": jid})  # off the board
        self.assertGreaterEqual(len(self.traces(JOB_WORDS)), 4)  # its folder's files and the undo steps hold its words before the deletion
        row = self.row("job:" + jid)
        self.assertEqual(("job", time.strftime("%Y-%m-%d")), (row["kind"], row["at"]))
        for path, body in (("/api/v1/jobs/build", {"job": jid, "lang": "ko"}), ("/api/v1/jobs/analyze", {"job": jid}),   # a job in the Trash takes no work:
                           ("/api/v1/tracker/edit", {"job": jid, "next": "x"}), ("/api/v1/jobs/select", {"job": jid})):  # nothing writes into a folder on its way out
            self.assertEqual("job", self.post(path, body, expect=400)["what"], path)
        self.assertEqual(time.strftime("%Y-%m-%d"), self.api.ws.job(jid)["removed_at"])  # kept on its card, in the schema's shape
        self.post("/api/v1/removed/delete", {"id": "job:" + jid})  # deleted for good
        self.assertEqual([], self.traces(JOB_WORDS))  # nothing holds its words or its folder's name
        self.assertFalse((self.api.ws.root / "jobs" / jid).exists())
        self.assertFalse(list(self.api.ws.path(".gone").glob("*")))  # swept
        self.assertNotEqual(jid, self.get("/api/v1/state")["job"])  # another job, or none, in view
        self.post("/api/v1/tracker/edit", {"job": jid, "next": "late"}, expect=400)  # a late request is refused, never makes its folder again
        self.assertEqual("removed", self.post("/api/v1/removed/delete", {"id": "job:" + jid}, expect=400)["what"])  # a second click: said as gone
        self.assertEqual("removed", self.post("/api/v1/removed/restore", {"id": "job:" + jid}, expect=400)["what"])  # a stale tab: the same
        self.assertFalse((self.api.ws.root / "jobs" / jid).exists())
        again = self.post("/api/v1/jobs", {"posting": POSTING.read_text(encoding="utf-8"), "company": f"{JOB_WORDS} Corp", "role": "Backend"})["job"]
        self.assertNotEqual(jid, again)  # its name is not given out again in this run
        self.post("/api/v1/jobs/remove", {"job": again})
        self.post("/api/v1/removed/delete", {"id": "job:" + again})

    def test_a_job_on_the_board_and_a_source_on_the_list_are_never_deleted(self):
        jid = self.post("/api/v1/jobs", {"posting": POSTING.read_text(encoding="utf-8"), "company": "Board Stays", "role": "Backend"})["job"]
        r = self.post("/api/v1/removed/delete", {"id": "job:" + jid}, expect=400)
        self.assertEqual("removed", r["what"])  # only what was taken off
        self.assertTrue((self.api.ws.root / "jobs" / jid / "status.json").is_file())
        for rid in ("source:m1", "material:" + jid + ":m1", "photo", "nothing", "aside:../x", "job:../../x"):  # not taken off, or made up
            self.post("/api/v1/removed/delete", {"id": rid}, expect=400)
            self.post("/api/v1/removed/restore", {"id": rid}, expect=400)

    def test_a_job_and_an_edition_come_back(self):
        jid = self.post("/api/v1/jobs", {"posting": POSTING.read_text(encoding="utf-8"), "company": "Comes Back", "role": "Backend"})["job"]
        eid = self.post("/api/v1/editions", {"name": "For headhunters"})["job"]  # a named edition
        self.post("/api/v1/jobs/remove", {"job": jid})
        st = self.post("/api/v1/jobs/remove", {"job": eid})["state"]
        self.assertEqual("undo_remove_edition", st["undo"]["code"])  # an edition says so on the undo key
        self.assertNotIn(eid, [e["id"] for e in st["editions"]])
        self.assertEqual({"job", "edition"}, {self.row("job:" + jid)["kind"], self.row("job:" + eid)["kind"]})
        self.post("/api/v1/removed/restore", {"id": "job:" + jid})
        st = self.post("/api/v1/removed/restore", {"id": "job:" + eid})["state"]
        self.assertIn(jid, [j["id"] for j in st["jobs"]])  # on the board again
        self.assertIn(eid, [e["id"] for e in st["editions"]])  # among the editions again
        self.assertNotIn("removed_at", self.api.ws.job(jid))  # with no day of removal
        self.assertEqual("undo_put_back", st["undo"]["code"])

    def test_a_job_material_comes_back_or_goes_for_good(self):
        jid = self.post("/api/v1/jobs", {"posting": POSTING.read_text(encoding="utf-8"), "company": "Materials Here", "role": "Backend"})["job"]
        keep = self.send(f"/api/v1/jobs/materials?job={q(jid)}", "notes.md", b"# fictional notes\n")["material"]
        gone = self.send(f"/api/v1/jobs/materials?job={q(jid)}", f"{MATERIAL_WORDS}.md", f"# {MATERIAL_WORDS} answers\n".encode())["material"]
        for m in (keep, gone):
            self.post("/api/v1/jobs/materials/remove", {"job": jid, "id": m["id"]})
        self.assertEqual(time.strftime("%Y-%m-%d"), self.row(f"material:{jid}:{gone['id']}")["at"])
        self.assertGreaterEqual(len(self.traces(MATERIAL_WORDS)), 3)  # its file, its record, its removal's undo step
        self.post("/api/v1/removed/restore", {"id": f"material:{jid}:{keep['id']}"})  # back
        listed = [m["id"] for m in self.get(f"/api/v1/jobs/{q(jid)}/materials")["materials"]]
        self.assertEqual([keep["id"]], listed)
        self.post("/api/v1/removed/delete", {"id": f"material:{jid}:{gone['id']}"})  # for good
        self.assertEqual([], self.traces(MATERIAL_WORDS))  # its name, its words, its title in the undo steps: gone
        index = json.loads((self.api.ws.root / "jobs" / jid / "materials" / "index.json").read_text(encoding="utf-8"))
        self.assertIn({"id": gone["id"], "gone": True}, index)  # its id stays, alone
        new = self.send(f"/api/v1/jobs/materials?job={q(jid)}", "later.md", b"# later\n")["material"]
        self.assertGreater(int(new["id"][1:]), int(gone["id"][1:]))  # never given again
        self.post("/api/v1/undo", {})  # undo still works around it
        self.post("/api/v1/jobs/remove", {"job": jid})  # its job off the board: its materials are not listed on their own
        self.assertFalse([r for r in self.removed()["rows"] if r["id"].startswith(f"material:{jid}:")])
        self.post("/api/v1/removed/restore", {"id": "job:" + jid})

    # ------------------------------------------------------------------ the photo

    def test_the_photo_comes_back_a_new_one_goes_aside_and_it_can_go_for_good(self):
        first, second, third = png((230, 120, 30)), png((20, 90, 200)), png((90, 160, 60))  # three pictures
        self.send("/api/v1/photo", "first.png", first)
        out = self.post("/api/v1/photo/remove", {})  # removed: it waits in the Trash
        self.assertIsNone(out["state"]["photo"])
        a = out["removed"]  # its id there, for the note's Undo
        self.assertRegex(a, r"^photo:\d{8}-\d{6}(-\d+)?$")
        self.assertEqual("photo.png", self.row(a)["name"])
        self.send("/api/v1/photo", "second.png", second)  # another one meanwhile
        b = self.post("/api/v1/photo/remove", {})["removed"]  # removed too, within the same second: the first one stays in the Trash
        self.assertNotEqual(a, b)
        self.assertEqual(2, self.get("/api/v1/state")["removed"]["photo"])  # both kept, none deleted without asking
        self.send("/api/v1/photo", "third.png", third)  # a third one in use
        self.post("/api/v1/removed/restore", {"id": a})  # the first one back
        _, now = self.raw_get("/api/v1/photo")
        self.assertEqual(self.api.ws.path("profile", "photo.png").read_bytes(), now)
        self.assertEqual(2, self.get("/api/v1/state")["removed"]["photo"])  # the third went to the Trash in its place, the second is still there
        self.assertIsNone(self.row(a))  # no longer in the Trash
        for pid in [r["id"] for r in self.removed()["rows"] if r["kind"] == "photo"]:  # both others, for good
            self.post("/api/v1/removed/delete", {"id": pid})
        self.assertFalse(list(self.api.ws.path("profile").glob("removed-photo*")))
        self.assertIsNotNone(self.get("/api/v1/state")["photo"])  # the photo in use stays
        self.post("/api/v1/removed/restore", {"id": a}, expect=400)  # a stale page

    # ------------------------------------------------------------------ undo from a toast

    def test_a_toasts_undo_takes_back_its_own_change_only(self):
        out = self.post("/api/v1/facts/add", {"kind": "skill", "title": "First", "statement": "One"})
        first = out["step"]  # the write names the undo step it made, whatever another writer did since
        self.assertEqual(first, out["state"]["undo_id"])  # here, the newest
        self.assertNotIn("step", self.post("/api/v1/jobs/select", {"job": "-general"}))  # a write that makes no step names none
        self.post("/api/v1/facts/add", {"kind": "skill", "title": "Second", "statement": "Two"})  # another change after it
        n = self.get("/api/v1/state")["history"]
        out = self.post("/api/v1/undo", {"only": first})
        self.assertEqual((None, True), (out["undone"], out.get("moved")))  # nothing taken back
        self.assertEqual(n, out["state"]["history"])
        out = self.post("/api/v1/undo", {"only": out["state"]["undo_id"]})  # the newest one's own name
        self.assertEqual("undo_typed", out["undone"]["code"])
        self.assertEqual(n - 1, out["state"]["history"])

    # ------------------------------------------------------------------ the asides, the busy rule, the backup, the bar's history

    def test_asides_are_listed_and_deleted_by_their_own_name_only(self):
        root = self.api.ws.root  # the workspace's folder
        real = root.with_name(root.name + "-before-restore-20260101-000000")  # as a restore names it
        (real / "profile").mkdir(parents=True)
        (real / "profile" / "profile.json").write_text("{}", encoding="utf-8")
        odd = root.with_name(root.name + "-before-restore-x")  # not that shape
        odd.mkdir()
        target = self.tmp / "elsewhere"  # a folder a link points to
        (target / "keep").mkdir(parents=True)
        link = root.with_name(root.name + "-before-restore-20260102-000000")
        link.symlink_to(target, target_is_directory=True)
        asides = self.removed()["asides"]
        self.assertEqual([real.name], [a["name"] for a in asides])  # the real one only
        self.assertNotIn("restore", asides[0])  # a whole workspace is never put back from here
        self.assertEqual("2026-01-01 00:00", asides[0]["at"])
        for name in (odd.name, link.name, "../elsewhere", root.name):
            self.post("/api/v1/removed/delete", {"id": "aside:" + name}, expect=400)
        self.post("/api/v1/removed/delete", {"all": True})  # emptying the list leaves the asides
        self.assertTrue(real.is_dir())
        self.post("/api/v1/removed/delete", {"id": "aside:" + real.name})
        self.assertFalse(real.exists())
        self.assertTrue((target / "keep").is_dir() and odd.is_dir() and root.is_dir())  # nothing else was touched
        link.unlink()

    def test_deleting_waits_for_a_running_task(self):
        jid = self.post("/api/v1/jobs", {"posting": POSTING.read_text(encoding="utf-8"), "company": "Waits", "role": "Backend"})["job"]
        self.wait_task("analyze:" + jid)
        self.post("/api/v1/jobs/remove", {"job": jid})
        t = self.api.tasks
        with t.state_lock:
            t.tasks["build:other"] = {"state": "running", "t": time.time()}  # a task in progress
        try:
            r = self.post("/api/v1/removed/delete", {"id": "job:" + jid}, expect=400)
            self.assertEqual("busy", r["what"])
            self.assertTrue((self.api.ws.root / "jobs" / jid).is_dir())  # nothing went
        finally:
            with t.state_lock:
                t.tasks.pop("build:other", None)
        self.post("/api/v1/removed/delete", {"id": "job:" + jid})

    def test_a_file_held_open_stops_a_deletion_before_it_changes_anything(self):
        from unittest import mock  # the system refusing, as Windows refuses a file another program has open
        m = self.upload(self.profile_file("HELD0000"))  # a file, taken off
        self.post("/api/v1/materials/remove", {"id": m["id"]})
        jid = self.post("/api/v1/jobs", {"posting": POSTING.read_text(encoding="utf-8"), "company": "Held Open", "role": "Backend"})["job"]
        self.wait_task("analyze:" + jid)
        self.post("/api/v1/jobs/remove", {"job": jid})  # an application, taken off
        steps = sorted(p.name for p in self.api.ws.path(".history").glob("*.json"))  # the undo steps as they are
        refuse = PermissionError(13, "held open")  # what the system says
        with mock.patch("pathlib.Path.unlink", side_effect=refuse):  # no file can be deleted
            r = self.post("/api/v1/removed/delete", {"id": "source:" + m["id"]}, expect=400)
        self.assertEqual("delete_failed", r["what"])  # said in the panel's words, never as a bug
        self.assertIsNotNone(self.row("source:" + m["id"]))  # still in the Trash, whole
        self.assertTrue(any(f.name.startswith(m["id"] + "_") for f in self.api.ws.path("sources").iterdir()))  # its file still there
        with mock.patch("apps.api.removed.retried", side_effect=refuse):  # the application's folder cannot move
            r = self.post("/api/v1/removed/delete", {"id": "job:" + jid}, expect=400)
        self.assertEqual("delete_failed", r["what"])
        self.assertTrue((self.api.ws.root / "jobs" / jid / "status.json").is_file())  # still there
        self.assertNotIn(jid, self.api.ws.gone)  # and still its own: put back, it works as before
        self.assertEqual(steps, sorted(p.name for p in self.api.ws.path(".history").glob("*.json")))  # no undo step was rewritten
        self.post("/api/v1/removed/restore", {"id": "job:" + jid})  # it comes back
        self.post("/api/v1/tracker/edit", {"job": jid, "next": "call back"})  # and takes a change
        self.post("/api/v1/removed/restore", {"id": "source:" + m["id"]})

    def test_what_an_older_offerowl_removed_is_listed_and_comes_back(self):
        from apps.api.facts import FACT_FILES  # the files a fact change touches
        ws, facts = self.api.ws, self.api.facts  # the running panel's own
        rec = ws.add_material("old-notes.txt", b"fictional notes")  # a file an agent read, as an earlier version kept it
        cand = {"kind": "skill", "org": "", "period": "", "title": "Old fact", "statement": "Read by an agent", "quote": "Read by an agent",
                "cid": "oldcid000001", "origin": "ingest", "source": {"material": rec["id"], "name": "old-notes.txt", "offset": 0, "more": 0}}
        with ws.change({"code": "undo_add_material", "n": 1}, FACT_FILES):  # its reading, one undo step
            facts.add_candidates([cand])
            facts.set_status(cand["cid"], "accepted")
            facts.rebuild()
        ws.update_material(rec["id"], state="done", facts=1)
        self.post("/api/v1/materials/remove", {"id": rec["id"]})  # removed
        ws.update_material(rec["id"], removed_at=None)  # as an earlier version left it: no day,
        ws.path("sources", "removed", rec["id"] + ".json").unlink()  # nothing kept aside
        self.assertEqual("", self.row("source:" + rec["id"])["at"])  # listed, its day unknown
        out = self.post("/api/v1/removed/restore", {"id": "source:" + rec["id"]})
        self.assertFalse(out["read_again"])  # its facts came back from the undo step that removed it
        self.assertIn("accepted", [r.get("status") for r in self.fact_rows() if r["cid"] == "oldcid000001"])  # as it was decided
        jid = self.post("/api/v1/jobs", {"posting": POSTING.read_text(encoding="utf-8"), "company": "Older Removal", "role": "Backend"})["job"]
        self.wait_task("analyze:" + jid)
        mat = self.send(f"/api/v1/jobs/materials?job={q(jid)}", "old brief.md", b"# fictional\n")["material"]
        self.post("/api/v1/jobs/materials/remove", {"job": jid, "id": mat["id"]})
        (ws.root / "jobs" / jid / "materials" / "removed_at.json").unlink()  # an earlier version kept no day
        self.assertEqual("", self.row(f"material:{jid}:{mat['id']}")["at"])
        self.post("/api/v1/removed/restore", {"id": f"material:{jid}:{mat['id']}"})  # back
        self.post("/api/v1/jobs/remove", {"job": jid})
        st = ws.job(jid)
        st.pop("removed_at")  # an earlier version kept no day
        ws.save_job(st)
        self.assertEqual("", self.row("job:" + jid)["at"])
        self.post("/api/v1/removed/delete", {"id": "job:" + jid})  # and it can go for good
        self.assertFalse((ws.root / "jobs" / jid).exists())

    def test_reads_during_a_deletion_never_fail(self):
        import threading  # the page's polls, beside the deletion
        import urllib.error  # a refused read
        jids = []  # applications to delete while the page reads
        for n in range(4):
            jid = self.post("/api/v1/jobs", {"posting": POSTING.read_text(encoding="utf-8"), "company": f"Read During {n}", "role": "Backend"})["job"]
            self.wait_task("analyze:" + jid)
            self.send(f"/api/v1/jobs/materials?job={q(jid)}", "notes.md", b"# fictional\n")  # a file in its folder
            self.post("/api/v1/jobs/remove", {"job": jid})
            jids.append(jid)
        bad, good, stop = [], [], threading.Event()  # reads that failed, reads that answered, the end of the polling

        def poll():  # the page's reads, as fast as they come
            while not stop.is_set():
                for path in ("/api/v1/state", "/api/v1/library", "/api/v1/insights", "/api/v1/removed", "/api/v1/tracker"):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=30) as r:
                            r.read()
                        good.append(path)
                    except urllib.error.HTTPError as e:  # anything but 200
                        bad.append((path, e.code, e.read()[:120]))
                    except Exception as e:  # noqa: BLE001  a dropped or refused connection fails the test too, never the poller alone
                        bad.append((path, type(e).__name__, str(e)[:120]))
        readers = [threading.Thread(target=poll, daemon=True) for _ in range(3)]  # three tabs
        for t in readers:
            t.start()
        try:
            for jid in jids:  # one at a time, each a folder moved and swept
                self.post("/api/v1/removed/delete", {"id": "job:" + jid})
        finally:
            stop.set()
            for t in readers:
                t.join(30)
        self.assertEqual([], bad)  # no read failed while folders went
        self.assertGreater(len(good), 10)  # and the pollers really read meanwhile
        self.assertFalse([j for j in jids if (self.api.ws.root / "jobs" / j).exists()])

    def test_a_step_the_scrub_could_not_fix_goes_at_the_next_sweep(self):
        import tempfile  # a workspace of its own
        from unittest import mock  # the system refusing one step
        from apps.api.workspace import Workspace, write_json  # the layout and its writes
        ws = Workspace(pathlib.Path(tempfile.mkdtemp(dir=self.tmp)) / "workspace")  # fresh
        for n in range(2):  # two changes, each an undo step holding a word
            with ws.change({"code": "undo_typed", "title": f"WORD{n}"}, ["sources/edits.json"]):
                write_json(ws.path("sources", "edits.json"), {"x": f"WORD{n} kept"})
        held = ws.path(".history", "000001.json")  # the step the system will not let go of
        real_unlink, real_write = pathlib.Path.unlink, write_json
        def unlink(path, *a, **k):  # this one step is held
            if path == held:
                raise PermissionError(13, "held")
            return real_unlink(path, *a, **k)
        def write(path, data):  # and cannot be rewritten
            if pathlib.Path(path) == held:
                raise PermissionError(13, "held")
            return real_write(path, data)
        edit = lambda step: (step["files"].update({"sources/edits.json": None}), True)[1]  # noqa: E731  every step changed
        with mock.patch("pathlib.Path.unlink", unlink), mock.patch("apps.api.workspace.write_json", write):
            with self.assertRaises(ValueError) as caught:  # said: something could not be deleted
                ws.scrub(edit)
        self.assertEqual("delete_failed", str(caught.exception))
        self.assertTrue(held.exists())  # still there for now, and named
        self.assertIn("000001.json", ws.path(".history", "stuck.txt").read_text(encoding="utf-8"))
        ws.sweep()  # the next start or deletion
        self.assertFalse(held.exists())  # gone, with the words it held
        self.assertFalse(ws.path(".history", "stuck.txt").exists())
        self.assertEqual(ws.history_count(), len(ws.history()))  # the list of steps reads as before (stuck.txt was never a step)

    def test_a_backup_leaves_out_what_is_on_its_way_out(self):
        gone = self.api.ws.path(".gone", "x-1")  # what a stopped deletion left
        gone.mkdir(parents=True)
        (gone / "status.json").write_text("{}", encoding="utf-8")
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/v1/workspace/backup", timeout=60) as r:
            names = zipfile.ZipFile(io.BytesIO(r.read())).namelist()
        self.assertFalse([n for n in names if n.startswith(".gone")])
        self.api.ws.sweep()  # and the next start or deletion sweeps it
        self.assertFalse(gone.exists())

    def test_writes_stopped_half_way_are_swept_at_the_start(self):
        import os  # file times
        from apps.api.workspace import Workspace  # a second look at the same folder, as the next start opens it
        ws = self.api.ws
        old = ws.path("sources", "candidates.json.4242.4242.tmp")  # a write the PC's power cut stopped
        old.write_text("{", encoding="utf-8")
        os.utime(old, (time.time() - 7200, time.time() - 7200))  # two hours ago
        fresh = ws.path("sources", "review.json.4243.4243.tmp")  # one that may still be going on
        fresh.write_text("{", encoding="utf-8")
        mine = ws.path("profile", "my notes.tmp")  # the person's own file that happens to end so
        mine.write_text("mine", encoding="utf-8")
        os.utime(mine, (time.time() - 7200, time.time() - 7200))
        Workspace(ws.root)  # the next start
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists() and mine.exists())  # nothing else
        fresh.unlink()
        mine.unlink()

    def test_the_command_bar_history_can_be_emptied(self):
        from apps.api import ask  # its file
        ask.keep(self.api, {"at": "2026-01-01 10:00", "text": "a fictional ask", "answer": "done", "ok": True})
        self.assertEqual(1, len(self.get("/api/v1/ask")["history"]))
        out = self.post("/api/v1/ask/clear", {})
        self.assertEqual(1, out["cleared"])
        self.assertEqual([], self.get("/api/v1/ask")["history"])

    def test_emptying_the_list(self):
        jid = self.post("/api/v1/jobs", {"posting": POSTING.read_text(encoding="utf-8"), "company": "Emptied", "role": "Backend"})["job"]
        self.wait_task("analyze:" + jid)
        self.post("/api/v1/jobs/remove", {"job": jid})
        self.send("/api/v1/photo", "third.png", png((10, 200, 10)))
        self.post("/api/v1/photo/remove", {})
        out = self.post("/api/v1/removed/delete", {"all": True})
        self.assertIn("job:" + jid, out["deleted"])
        self.assertEqual([], self.removed()["rows"])
        self.assertEqual(0, out["state"]["removed"]["all"])


if __name__ == "__main__":
    import unittest
    unittest.main()
