#!/usr/bin/env python3
"""The blind edition from the panel: the person's own mask table (kept in the workspace, checked before it is kept), each
build's own switches (handed to that build alone, never through the server's environment), what a blind edition leaves out,
its names on the Desktop, and the check that refuses to export a blind edition whose PDFs still show a covered name.
Fictional people and companies only. No typesetting runs: the steps are stood in for, and the PDFs are small ones written here.

  python3 -m unittest tests/app/test_blind.py -v
"""
import json  # tables and records
import os  # the server's own environment
import pathlib  # paths
import shutil  # temporary folders, and is node here
import subprocess  # node, for the JavaScript side of the table
import sys  # the import path
import tempfile  # a folder per test
import threading  # two builds at once
import time  # waiting for the reading of the example
import unittest  # the runner
from unittest import mock  # stand-ins for the typesetting

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src", ROOT / "tests" / "app", ROOT / "tests" / "render"):  # apps/, the engine, the helpers beside this file
    sys.path.insert(0, str(p))
from test_choices import Base  # noqa: E402  one data folder per test, nothing real called
from test_pdftools import W, H, write_pdf  # noqa: E402  a small PDF with a text layer
from apps.api.routes import Router  # noqa: E402  the table the panel calls
from apps.api.tasks import OWN_FORM_KEYS  # noqa: E402  the layout choices of an own edition
from apps.api.workspace import read_json, write_json  # noqa: E402  the files of an edition
import blind as B  # noqa: E402  src/blind.py
import pdfmeta  # noqa: E402  the title and author a PDF reader shows
import pdftools  # noqa: E402  is there a PDF reader on this PC
import resume  # noqa: E402  the typesetting steps that are stood in for

# A fictional table: two invented companies, an invented address, and a word that must never show
TABLE = {"mask": ["Alphapay", "Betacommerce", r"gildong@example\.com"], "mask_whole": [r"gildong@example\.com"], "leak": ["Gammaworks"]}


def pdf_with_link(path: pathlib.Path, text: str, uri: str) -> None:
    """A one-page PDF whose page holds text and a link annotation to uri (as Chromium writes a mail link)."""
    stream = f"BT /F1 12 Tf 1 0 0 1 72 {H - 72} Tm ({text}) Tj ET"  # one line
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Contents 5 0 R /Resources << /Font << /F1 3 0 R >> >> /Annots [6 0 R] >>",
               f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
               f"<< /Type /Annot /Subtype /Link /Rect [72 700 300 720] /A << /S /URI /URI ({uri}) >> >>"]
    out, offsets = "%PDF-1.4\n", []  # the file, and where each object starts
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(out.encode("latin-1"))


class Person(Base):
    """The fictional example person with every fact kept, and a Desktop of the test's own."""

    def person(self):
        a = self.make()  # the PC, nothing real called
        a.add_example("ko")  # the fictional person, read as a profile file
        for _ in range(200):  # its reading runs in a thread of its own
            if a.tasks.state().get("ingest", {}).get("state") != "running":
                break
            time.sleep(0.05)
        a.keep_all()  # every fact kept: a resume can be made
        desk = self.tmp / "Desktop"  # where the export writes
        p = mock.patch.dict(os.environ, {"OFFEROWL_DESKTOP": str(desk)})
        p.start()
        self.addCleanup(p.stop)
        return a


class TableTests(Person):
    """The person's own table: checked before it is kept, kept in the workspace, read back, taken away, undone."""

    def test_a_table_is_checked_before_it_is_kept(self):
        a = self.person()
        r = Router(a)  # the routes the panel calls
        status, body, _ = r.handle("POST", "/api/v1/blind", None, {"table": {**TABLE, "script": "kept out"}})
        self.assertEqual(200, status, body)  # kept
        self.assertEqual((True, {"mask": 3, "mask_whole": 1, "leak": 1}), (body["blind"]["own"], body["blind"]["counts"]))  # the summary the panel shows
        kept = read_json(a.ws.path("blind.json"), {})  # in the workspace
        self.assertEqual(TABLE, kept)  # a key the table does not have stays out
        self.assertEqual(TABLE, r.handle("GET", "/api/v1/blind")[1]["table"])  # read back as kept
        self.assertEqual(body["blind"], a.state()["blind"])  # the state carries it, with the table's stamp
        self.assertTrue(body["blind"]["stamp"])
        shipped = json.loads((ROOT / "src" / "blind.json").read_text(encoding="utf-8"))  # the repository's table
        self.assertEqual([], shipped["mask"])  # never written: a person's names stay in their workspace
        refused = {  # what each bad table is answered with
            "blind_table": [[], {"mask": "Alphapay"}, {**TABLE, "mask_fill": "red"}, {**TABLE, "mask": ["x"] * 501},
                            {**TABLE, "footer": {"ko": "<b>" * 30}}, {**TABLE, "banner": {"en": ["BLIND"]}}],
            "blind_pattern:mask:1": [{"mask": ["(?P<name>Alphapay)"]}, {"mask": ["(?i)alphapay"]}, {"mask": ["Alphapay["]}, {"mask": ["x*"]},
                                     {"mask": [r"Alphapay\Z"]}, {"mask": ["[]x]"]}, {"mask": ["C++"]}, {"mask": ["a{,3}"]}],
            "blind_pattern:leak:2": [{"leak": ["Gammaworks", ""]}, {"leak": ["Gammaworks", "x" * 301]}],
        }
        for what, tables in refused.items():  # each refused with its words, the kept table untouched
            for table in tables:
                status, body, _ = r.handle("POST", "/api/v1/blind", None, {"table": table})
                self.assertEqual((400, what), (status, body.get("what")), table)
        self.assertEqual(TABLE, read_json(a.ws.path("blind.json"), {}))  # still the good one
        self.assertEqual(400, r.handle("POST", "/api/v1/blind", None, {})[0])  # a request that names no table changes nothing
        self.assertEqual(200, r.handle("POST", "/api/v1/blind", None, {"table": None})[0])  # taken away
        self.assertFalse(a.ws.path("blind.json").exists())  # the shipped table applies again
        self.assertEqual({"own": False, "counts": {"mask": 0, "mask_whole": 0, "leak": 0}, "stamp": ""}, a.blind_view())
        a.ws.undo()  # undo brings it back
        self.assertEqual(TABLE, read_json(a.ws.path("blind.json"), {}))

    @unittest.skipUnless(shutil.which("node"), "node is not on this PC")
    def test_python_and_javascript_read_the_patterns_alike(self):
        """Every pattern the checks let through compiles in JavaScript, and blind.js and blind.py cover the same characters."""
        tried = [r"Alphapay", r"\bBeta\w*\b", r"[0-9]{2,4} GPUs?", r"(?:Gamma|Delta) Labs", r"(?<=@)example\.com", r"오메가\s?랩스",
                 r"x{2,}", r"\d+(?:\.\d+)? ?MW", r"(?<!\w)ACME(?!\w)", r"[^\s]+@example\.com", r"(?P<n>x)", r"(?i)x", r"\Ax"]
        ok = [p for p in tried if not B.pattern_problem(p)]  # what a table may hold
        self.assertEqual(10, len(ok))  # the Python-only forms are refused
        table = B.merged({"mask": ok, "mask_whole": [r"[0-9]{2,4} GPUs?"]})  # one table of them
        with tempfile.TemporaryDirectory() as d:  # the table as blind.js reads it, by its absolute path
            f = pathlib.Path(d) / "t.json"
            f.write_text(json.dumps(table), encoding="utf-8")
            text = "Alphapay and Betacommerce ran 128 GPUs at gildong@example.com, 1.5 MW, 오메가 랩스 and ACME, xxx, Gamma Labs."
            js = subprocess.run(["node", "-e", "const B = require(process.argv[1]); process.stdout.write(JSON.stringify(B.segments(process.argv[2])))",
                                 str(ROOT / "src" / "blind.js"), text], capture_output=True, text=True, encoding="utf-8", timeout=60,
                                env={**os.environ, "OFFEROWL_BLIND": "1", "OFFEROWL_BLIND_TABLE": str(f)})
            self.assertEqual(0, js.returncode, js.stderr)
            self.assertEqual([list(x) for x in B.segments(text, table)], json.loads(js.stdout))  # the same pieces, covered alike
            empty = subprocess.run(["node", "-e", "const B = require(process.argv[1]); process.stdout.write(String(B.hit('anything')))",
                                    str(ROOT / "src" / "blind.js")], capture_output=True, text=True, encoding="utf-8", timeout=60, env={**os.environ, "OFFEROWL_BLIND": "1"})
            self.assertEqual("false", empty.stdout)  # the shipped table covers nothing (an empty expression once matched every run)

    def test_a_name_joined_by_a_no_break_space_is_covered(self):
        """The documents join a name's words with a no-break space (deck.js), so a pattern written with a plain space must take
        either: blind.js and blind.py cut the same pieces, and the export's check finds nothing left."""
        table = {"mask": ["Gamma Labs", "a[ ]x"], "mask_whole": [], "leak": []}  # fictional; a space inside a class stays a space
        text = "Built at Gamma\u00a0Labs and Gamma Labs, a x and a\u00a0x."  # one name joined, one plain
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "t.json"
            f.write_text(json.dumps(table), encoding="utf-8")
            js = subprocess.run(["node", "-e", "const B = require(process.argv[1]); process.stdout.write(JSON.stringify(B.segments(process.argv[2])))",
                                 str(ROOT / "src" / "blind.js"), text], capture_output=True, text=True, encoding="utf-8", timeout=60,
                                env={**os.environ, "OFFEROWL_BLIND": "1", "OFFEROWL_BLIND_TABLE": str(f)})
        self.assertEqual(0, js.returncode, js.stderr)
        pieces = json.loads(js.stdout)
        self.assertEqual([list(x) for x in B.segments(text, table)], pieces)  # the same pieces in both
        self.assertEqual("GammaLabsGammaLabsax", "".join(t for t, on in pieces if on))  # both names, word by word; a[ ]x only with its plain space
        self.assertEqual([], B.leaks(B.plain(text, table), {"mask": ["Gamma Labs"], "leak": []}))  # what a reader can copy shows neither name

    def test_leak_words_are_matched_as_written(self):
        """The leak list holds words, as the tables people keep mean them: "500+" is five hundred and more, never a pattern that
        finds 50000 in a patent number, and a Latin word counts only on its own (a person's table refused every export of a
        clean edition when NCI was found inside COMPETENCIES)."""
        table = {"leak": ["NCI", "500+", "Gammaworks", "감마"], "mask": []}  # fictional names and a figure
        self.assertEqual([], B.leaks("CORE COMPETENCIES\npatent KR1025219150000", table))  # inside a longer word, or read as a pattern
        self.assertEqual(["NCI", "500+", "감마"], B.leaks("funded by NCI, 500+ GPUs at 감마랩", table))  # on their own; Hangul anywhere
        self.assertEqual(["Gammaworks"], B.leaks("built at Gamma-\nworks Gammaworks", table))  # a name on its own, after a broken one
        self.assertEqual([], B.problems({"leak": ["C++", "(주)", "500+"]}))  # words that are no patterns are kept as they are


class Builds(Person):
    """Builds with the typesetting stood in for: each step records the environment it was given."""

    def stand_in(self, a):
        """resume.build, build_deck and build_plain, the check and the page pictures stood in for. self.calls gets (step,
        the environment's OFFEROWL_BLIND* names, whether the named table was there at that moment)."""
        self.calls = []  # every step, in order
        out = self.tmp / "made"  # what the steps "make"
        out.mkdir(exist_ok=True)
        lock = threading.Lock()  # two builds at once write here

        def seen(step, env):  # what one step was given
            blind = {k: v for k, v in (env or {}).items() if k.startswith("OFFEROWL_BLIND")}  # its blind switches
            there = (ROOT / blind["OFFEROWL_BLIND_TABLE"]).is_file() if "OFFEROWL_BLIND_TABLE" in blind else None  # the staged table
            with lock:
                self.calls.append((step, blind, there))

        def made(name, text):  # a small PDF with a text layer
            f = out / f"{name}_{len(self.calls)}.pdf"
            write_pdf(f, [[(72, 72, 12, text)]])
            return f

        def build(profile, cfg=None, env=None):
            seen("resume", env)
            return made("resume", "Gildong Hong")

        def build_deck(profile, cfg=None, env=None):
            seen("deck", env)
            return made("deck", "Portfolio")

        def build_plain(profile, cfg=None, env=None):
            seen("plain", env)
            (out / "p.docx").write_bytes(b"PK")
            (out / "p.txt").write_text("words", encoding="utf-8")
            return out / "p.docx", out / "p.txt"

        def check(profile, pdf, deck, max_pages, env=None):
            seen("check", env)
            return [], []

        for p in (mock.patch.object(resume, "build", side_effect=build), mock.patch.object(resume, "build_deck", side_effect=build_deck),
                  mock.patch.object(resume, "build_plain", side_effect=build_plain), mock.patch.object(a.tasks, "_check", side_effect=check),
                  mock.patch.object(a.tasks, "_previews", return_value=1), mock.patch.object(a.tasks, "engine_ready", return_value="")):
            p.start()
            self.addCleanup(p.stop)

    def record(self, a, job, lang="ko"):
        """An edition's build.json."""
        return read_json(a.tasks.build_dir(job, lang) / "build.json", {})


class EnvTests(Builds):
    """Each build gets its own switches; the server's environment is never changed and never reaches a build."""

    def test_two_builds_at_once_keep_their_own_switches(self):
        a = self.person()
        a.set_blind({"table": TABLE})  # the person's table
        self.stand_in(a)
        named = a.add_edition({"name": "Platform roles"})  # a second edition, made at the same time
        before = {k: v for k, v in os.environ.items() if k.startswith("OFFEROWL_BLIND")}  # the server's own
        runs = [threading.Thread(target=a.tasks._build, args=("-general", "ko", "navy", 3, False, False, True)),  # a blind one
                threading.Thread(target=a.tasks._build, args=(named, "en", "navy", 3, False, False, False))]  # and an ordinary one
        with mock.patch.object(a.tasks, "english_for", return_value=a.ws.path("profile", "profile.json")):  # the English one reads the same profile here
            for t in runs:
                t.start()
            for t in runs:
                t.join(60)
        blind = [c for c in self.calls if c[1]]  # the steps that got switches
        plain = [c for c in self.calls if not c[1]]  # and those that got none
        self.assertEqual(["resume", "deck", "check"], [c[0] for c in blind])  # the blind edition's three, and no plain words
        self.assertEqual(["resume", "deck", "check", "plain"], [c[0] for c in plain])  # the ordinary one's, plain words too
        for _, env, there in blind:  # each blind step got the edition's own switches
            self.assertEqual("1", env["OFFEROWL_BLIND"])
            self.assertEqual("ko", env["OFFEROWL_BLIND_LANG"])
            self.assertEqual(("output", "_inputs"), pathlib.Path(env["OFFEROWL_BLIND_TABLE"]).parts[:2])  # staged where the container sees it
            self.assertTrue(there)  # and there while the step ran
        self.assertEqual(before, {k: v for k, v in os.environ.items() if k.startswith("OFFEROWL_BLIND")})  # the server's environment as it was
        self.assertFalse((ROOT / blind[0][1]["OFFEROWL_BLIND_TABLE"]).exists())  # the staged copy of the person's names is gone again
        rec = self.record(a, "-general")  # the blind edition
        self.assertIs(True, rec["blind"])
        self.assertEqual(a.tasks.blind_stamp(), rec["blind_table"])  # which table its bars came from
        self.assertIs(True, read_json(a.tasks.build_dir("-general", "ko") / "job.json", {})["blind"])  # its job.json says so
        self.assertNotIn("blind", self.record(a, named, "en"))  # the ordinary one is not
        self.assertFalse((a.tasks.build_dir("-general", "ko") / "resume.txt").exists())  # no plain words in a blind edition
        self.assertTrue((a.tasks.build_dir(named, "en") / "resume.txt").exists())  # the ordinary edition has them

    def test_the_servers_own_switches_never_reach_an_ordinary_build(self):
        a = self.person()
        self.stand_in(a)
        with mock.patch.dict(os.environ, {"OFFEROWL_BLIND": "1", "OFFEROWL_BLIND_TABLE": "output/_inputs/elsewhere.json"}):  # started with them
            a.tasks._build("-general", "ko", "navy", 3, False, False, False)  # an ordinary edition
            self.assertEqual([], [c for c in self.calls if c[1]])  # no step saw them
            self.assertEqual("1", os.environ["OFFEROWL_BLIND"])  # and they were not taken away from the server either
        self.calls.clear()
        a.tasks._build("-general", "ko", "navy", 3, False, False, True)  # a blind one with no table of the person's own
        self.assertEqual({"OFFEROWL_BLIND": "1", "OFFEROWL_BLIND_LANG": "ko"}, self.calls[0][1])  # the shipped table, by naming none

    def test_the_choice_stays_until_it_is_changed(self):
        a = self.person()
        self.stand_in(a)
        build = lambda blind=None: (a.tasks._build("-general", "ko", "navy", 3, False, False, blind), self.record(a, "-general").get("blind") is True)[1]  # noqa: E731
        self.assertFalse(build())  # an edition starts ordinary
        self.assertTrue(build(True))  # the switch
        self.assertTrue(build())  # made again: still blind
        self.assertFalse(build(False))  # switched off
        self.assertFalse(build())  # and it stays off
        status, body, _ = Router(a).handle("POST", "/api/v1/jobs/build", None, {"job": "-general", "lang": "ko", "blind": True, "cover": False})
        self.assertEqual(200, status, body)  # the route takes the switch
        for _ in range(200):  # the build runs in a thread
            if a.tasks.state().get("build:-general", {}).get("state") != "running":
                break
            time.sleep(0.05)
        self.assertIs(True, self.record(a, "-general").get("blind"))

    def test_an_own_edition_brought_in_blind_stays_blind(self):
        a = self.person()
        self.stand_in(a)
        jid = a.add_job({"company": "Deltasoft", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a fictional job
        own = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the same person's resume, brought in
        self.assertIn("blind", OWN_FORM_KEYS)  # a layout choice an own edition keeps
        Router(a).handle("POST", "/api/v1/jobs/own", None, {"job": jid, "profile": own, "langs": ["ko"], "name": "blind", "form": {"ko": {"blind": True}}})
        self.assertIs(True, a.tasks.edition_cfg(jid, "ko", "navy")["blind"])  # its job.json carries it
        a.tasks._build(jid, "ko", "navy", 3, False, False)  # made with nothing said
        self.assertIs(True, self.record(a, jid)["blind"])  # blind, as it was brought in
        a.tasks._build(jid, "ko", "navy", 3, False, False, False)  # the switch turned off
        a.tasks._build(jid, "ko", "navy", 3, False, False)  # made again with nothing said
        self.assertNotIn("blind", self.record(a, jid))  # it stays as the person left it
        self.assertNotIn("blind", read_json(a.tasks.build_dir(jid, "ko") / "job.json", {}))  # and its job.json says so


class LeftOutTests(Builds):
    """What no bar can cover stays out of a blind edition, and its notes say so."""

    PDF = b"%PDF-1.4\n% a fictional one-page file\n%%EOF\n"  # enough for the type check of an own file

    def test_own_files_the_profiles_deck_and_the_letter(self):
        a = self.person()
        self.stand_in(a)
        jid = a.add_job({"company": "Deltasoft", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})
        a.own_file(jid, "ko", "resume", "mine.pdf", self.PDF)  # the person's own resume file
        a.own_file(jid, "ko", "deck", "mine.pdf", self.PDF)  # and their own portfolio
        out = a.tasks.build_dir(jid, "ko")
        (out / "cover").mkdir(parents=True)
        write_json(out / "cover" / "cover.json", {"reviewed": True, "paragraphs": [{"sentences": [{"text": "Dear Deltasoft."}]}]})  # a letter there is
        with mock.patch.object(a.tasks, "_cover", side_effect=AssertionError("a blind edition writes no letter")):
            a.tasks._build(jid, "ko", "navy", 3, True, False, True)  # blind, with the letter asked for
        rec = self.record(a, jid)
        self.assertEqual(["resume", "check"], [c[0] for c in self.calls])  # the resume typeset from the words; no deck drawn in place of theirs
        self.assertEqual({"blind_own_file", "blind_no_deck", "blind_no_cover"}, set(rec["notes"]))  # each said
        self.assertEqual(0, rec["slides"])  # no deck
        self.assertIsNone(rec["cover"])  # no letter
        self.assertEqual({"resume.pdf"}, set(rec["hashes"]))  # only the resume may go
        self.assertFalse((out / "deck.pdf").exists() or (out / "cover.pdf").exists())  # nothing of theirs ships unmasked
        self.calls.clear()
        a.tasks._build(jid, "ko", "navy", 3, False, False, False)  # the ordinary edition
        self.assertEqual([], [c[0] for c in self.calls if c[0] in ("resume", "deck")])  # their own files stand for both again
        self.assertEqual(["own_file"], self.record(a, jid)["notes"])

    def test_a_profile_that_names_its_own_deck(self):
        self.make()  # a folder of the test's own
        d = self.tmp
        deck = d / "mine.pdf"
        write_pdf(deck, [[(72, 72, 12, "Cover")]])
        prof, cfg = d / "profile.json", d / "job.json"
        prof.write_text(json.dumps({"person": {"name": "Gildong Hong"}, "deck": {"pdf": "mine.pdf"}}), encoding="utf-8")  # the profile's own portfolio
        cfg.write_text(json.dumps({"lang": "ko"}), encoding="utf-8")
        self.assertTrue(resume.blind_leaves_deck(str(prof), str(cfg), {"OFFEROWL_BLIND": "1"}))  # a blind edition leaves it out
        self.assertFalse(resume.blind_leaves_deck(str(prof), str(cfg), {}))  # an ordinary one keeps it
        prof.write_text(json.dumps({"person": {"name": "Gildong Hong"}, "deck": {"pdf": "gone.pdf"}}), encoding="utf-8")  # named but gone
        self.assertTrue(resume.blind_leaves_deck(str(prof), str(cfg), {"OFFEROWL_BLIND": "1"}))  # left out all the same, never drawn instead
        prof.write_text(json.dumps({"person": {"name": "Gildong Hong"}}), encoding="utf-8")  # none named
        self.assertFalse(resume.blind_leaves_deck(str(prof), str(cfg), {"OFFEROWL_BLIND": "1"}))  # Offerowl draws one, with its bars


@unittest.skipUnless(pdftools.reader(), "no PDF reader on this PC (poppler or pypdfium2): a blind edition's text cannot be read")
class ExportTests(Person):
    """A blind edition's PDFs are read before they go: a covered name in their text, their titles or their links stops them."""

    def edition(self, a, resume_text, title="Gildong Hong Resume (Blind version)", link=None):
        """The general edition as a blind build left it: a resume and a deck, stamped, with their hashes."""
        out = a.tasks.build_dir("-general", "ko")
        out.mkdir(parents=True, exist_ok=True)
        if link:  # a resume with a link annotation
            pdf_with_link(out / "resume.pdf", resume_text, link)
        else:
            write_pdf(out / "resume.pdf", [[(72, 72, 12, resume_text)]])
        write_pdf(out / "deck.pdf", [[(72, 72, 12, "Payments platform")]])
        pdfmeta.stamp(out / "resume.pdf", title, "Gildong Hong")  # a title and an author of its own
        pdfmeta.stamp(out / "deck.pdf", "Gildong Hong Portfolio (Blind version)", "Gildong Hong")
        from apps.api.tasks import file_hash  # the hashes the build records
        write_json(out / "build.json", {"lang": "ko", "issues": [], "notes": [], "blind": True, "blind_table": a.tasks.blind_stamp(),
                                        "hashes": {f: file_hash(out / f) for f in ("resume.pdf", "deck.pdf")}})
        return out

    def test_a_covered_name_that_shows_stops_the_export(self):
        a = self.person()
        a.set_blind({"table": TABLE})
        desk = pathlib.Path(os.environ["OFFEROWL_DESKTOP"])
        self.edition(a, "Built the checkout at Betacommerce")  # a covered name in the text layer
        with self.assertRaises(ValueError) as e:
            a.tasks.export("-general", "ko")
        self.assertEqual("blind_leak:1", str(e.exception))  # one pattern shows
        self.assertFalse(desk.exists() and any(desk.iterdir()))  # nothing went
        status, body, _ = Router(a).handle("POST", "/api/v1/jobs/export", None, {"job": "-general", "lang": "ko"})
        self.assertEqual((400, "blind_leak:1"), (status, body.get("what")))  # the page gets the code
        self.edition(a, "Built the checkout at a client")  # clean text, a word that must never show in the title
        a.set_blind({"table": {**TABLE, "leak": ["Gammaworks", "Resume (Blind"]}})  # added after the build: the table as it is now counts
        with self.assertRaises(ValueError) as e:
            a.tasks.export("-general", "ko")
        self.assertEqual("blind_leak:1", str(e.exception))  # found in the title, not the text
        a.set_blind({"table": TABLE})
        self.edition(a, "Write to me", link="mailto:gildong@example.com")  # a covered address left in a link
        with self.assertRaises(ValueError):
            a.tasks.export("-general", "ko")
        self.edition(a, "")  # a resume with no text to read
        with self.assertRaises(ValueError) as e:
            a.tasks.export("-general", "ko")
        self.assertEqual("blind_unread", str(e.exception))  # nothing read is never taken for clean
        self.assertFalse(desk.exists() and any(desk.iterdir()))  # still nothing on the Desktop

    def test_a_clean_blind_edition_goes_under_blind_names(self):
        a = self.person()
        a.set_blind({"table": {**TABLE, "mask": TABLE["mask"] + ["Platform roles"]}})  # the named edition's own name is covered too
        self.edition(a, "Built the checkout at a client")
        names = a.tasks.export("-general", "ko")
        self.assertEqual(["홍길동 블라인드 이력서.pdf", "홍길동 블라인드 포트폴리오.pdf"], names)  # the word for blind, in the edition's language
        named = a.add_edition({"name": "Platform roles"})  # a named edition whose name the table covers
        out = a.tasks.build_dir(named, "ko")
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(a.tasks.build_dir("-general", "ko"), out)
        names = a.tasks.export(named, "ko")
        self.assertTrue(all("Platform" not in n and "블라인드" in n for n in names), names)  # a covered name never lands in a file name
        rec = a.tasks.lock(named, "ko")  # submitted as it is
        self.assertIs(True, rec["blind"])  # the lock remembers it was the blind edition
        sent = a.tasks.export(named, "ko")  # the copies that went out
        self.assertTrue(all("블라인드" in n for n in sent), sent)  # under the blind names too


class OwnLengthTests(Builds):
    """A resume the person brought in prints whole, so its own length is never over the page limit. The panel sends its own
    limit (three by default) with the switch and with Make PDFs: a six-page edition brought in failed its checks when it was
    made again, blind or not, and its export was refused with nothing the person could change."""

    def test_an_own_edition_is_measured_against_its_own_length(self):
        a = self.person()
        self.stand_in(a)
        limits = []  # the limit each check was given
        jid = a.add_job({"company": "Deltasoft", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})  # a fictional job
        own = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the same person's resume, brought in
        Router(a).handle("POST", "/api/v1/jobs/own", None, {"job": jid, "profile": own, "langs": ["ko"], "name": "resume.pdf"})
        check = lambda profile, pdf, deck, max_pages, env=None: (limits.append(max_pages), ([], []))[1]  # noqa: E731  records the limit
        with mock.patch.object(pdfmeta, "pages", return_value=6), mock.patch.object(a.tasks, "_check", side_effect=check):  # every PDF six pages long
            a.tasks._build(jid, "ko", "navy", 3, False, False, True)  # the person's own edition, made blind with the panel's limit of three
            a.tasks._build("-general", "ko", "navy", 3, False, False)  # one written from the profile, as long
        self.assertEqual([6, 3], limits)  # the own edition against its own six pages; the written one still against three
        self.assertEqual(3, self.record(a, jid)["maxPages"])  # the limit asked for is what the edition records


class OwnLetterPagesTests(Builds):
    """A cover letter the person brought in is shown on the Cover letter tab only as its page pictures. The build copied its
    PDF but drew none and recorded no page count, so the tab said "No PDF yet" for every letter brought in."""

    def letter(self, name="Letter"):
        """A small one-page PDF letter with a text layer."""
        f = self.tmp / f"{name}.pdf"
        write_pdf(f, [[(72, 72, 12, f"Dear Deltasoft, {name}")]])
        return f.read_bytes()

    def job(self, a):
        return a.add_job({"company": "Deltasoft", "posting": (ROOT / "examples" / "cover" / "posting_ko.md").read_text(encoding="utf-8")})

    def test_a_build_draws_the_pages_of_an_own_letter(self):
        a = self.person()
        self.stand_in(a)
        jid = self.job(a)
        a.own_file(jid, "ko", "cover", "mine.pdf", self.letter())  # the person's own letter
        a.tasks._build(jid, "ko", "navy", 3, True, False, False)  # an ordinary edition, with the letter
        cover = self.record(a, jid)["cover"]
        self.assertTrue(cover["own"])  # the letter is theirs
        self.assertEqual(1, cover["pages"])  # and its pages are drawn: the tab has something to show

    def test_an_edition_made_before_gets_its_letter_pages(self):
        a = self.person()
        self.stand_in(a)
        jid = self.job(a)
        a.own_file(jid, "ko", "cover", "mine.pdf", self.letter())
        a.tasks._build(jid, "ko", "navy", 3, True, False, False)
        out = a.tasks.build_dir(jid, "ko")
        rec = self.record(a, jid)
        del rec["cover"]["pages"]  # as an edition made before the build drew them
        write_json(out / "build.json", rec)
        self.assertEqual({f"{jid}|ko": 1}, a.tasks.letter_pages_all())  # drawn once
        self.assertEqual(1, self.record(a, jid)["cover"]["pages"])
        self.assertEqual({}, a.tasks.letter_pages_all())  # and never again
        self.assertIsNone(a.tasks.letter_pages("-general", "ko"))  # an edition without a letter of the person's own is left alone

    def test_a_submitted_letter_shows_the_copy_that_went_out(self):
        import hashlib  # byte for byte
        a = self.person()
        self.stand_in(a)
        jid = self.job(a)
        a.own_file(jid, "ko", "cover", "draft.pdf", self.letter("Draft"))  # the letter the edition was made with
        a.tasks._build(jid, "ko", "navy", 3, True, False, False)
        sent = self.letter("Sent")  # what went out differs from the draft
        a.sent_file(jid, "ko", "cover", "sent.pdf", sent)  # brought in as submitted: the job is locked
        out = a.tasks.build_dir(jid, "ko")
        self.assertEqual(1, a.tasks.letter_pages(jid, "ko"))  # drawn from the sent copy
        self.assertEqual(sent, (out / "cover.pdf").read_bytes())  # the edition's letter is the copy that went out
        rec = self.record(a, jid)
        self.assertEqual(hashlib.sha256(sent).hexdigest(), rec["cover"]["sent"])  # and says which bytes it shows
        self.assertEqual(hashlib.sha256(sent).hexdigest()[:16], rec["hashes"]["cover.pdf"])
        self.assertIsNone(a.tasks.letter_pages(jid, "ko"))  # once
        st = a.ws.job(jid)
        frozen = a.ws.job_dir(jid) / "submitted" / st["locked"]["folder"] / "cover.pdf"
        frozen.write_bytes(b"%PDF-1.4 changed")  # a frozen copy that is no longer what was sent
        self.assertIsNone(a.tasks.sent_letter(jid, "ko"))  # never shown as sent


if __name__ == "__main__":
    unittest.main()
