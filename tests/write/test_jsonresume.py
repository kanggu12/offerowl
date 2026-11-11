# -*- coding: utf-8 -*-
"""JSON Resume interop (src/write_jsonresume.py): import, export, and round trips both ways. Fictional data only."""
import copy  # inputs are copied before a test changes them
import json  # every file is JSON
import pathlib  # paths
import shutil  # is node installed
import subprocess  # the command line and the loader
import sys  # the import path
import tempfile  # scratch folders
import unittest  # the test runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
HERE = pathlib.Path(__file__).resolve().parent  # tests/write
sys.path.insert(0, str(ROOT / "src"))  # the module under test
import write_jsonresume as J  # noqa: E402  (the path is set above)

RESUME = json.loads((HERE / "fixtures" / "resume_en.json").read_text(encoding="utf-8"))  # a fictional JSON Resume document
SAMPLE = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the fictional example profile
LEDGER = json.loads((HERE / "fixtures" / "ledger_ko.json").read_text(encoding="utf-8"))  # a fictional ledger-shaped profile


class ImportTests(unittest.TestCase):  # JSON Resume -> profile
    def setUp(self):  # one import per test
        self.prof = J.import_resume(copy.deepcopy(RESUME))  # the imported profile

    def test_basics_become_the_person_and_the_intro(self):  # basics
        P = self.prof["person"]  # the person block
        self.assertEqual((P["name"], P["email"], P["tagline"]), ("Mira Solberg", "mira@example.com", "Platform Engineer"))  # name, e-mail and tagline
        self.assertIn(["GitHub", "github.com/example-mira", "https://github.com/example-mira"], P["links"])  # a profile becomes a link row
        self.assertEqual(P["location"], "Example City, XX")  # city and country in one line
        self.assertEqual(self.prof["summary"]["intro"], "Platform engineer who moved payment services onto Kubernetes.")  # the summary is the introduction

    def test_work_becomes_roles_with_their_highlights_as_evidence(self):  # the drafting step reads the highlights as blocks
        r = self.prof["roles"][0]  # the first employer
        self.assertEqual((r["org"], r["title"], r["start"], r["end"]), ("Northwind Payments", "Platform Engineer", "2021.03", None))  # no end date: ongoing
        self.assertEqual(r["desc"], "Payment processor for small shops.")  # the summary is the company line
        self.assertEqual(r["projects"][0]["points"][0], "Proposed the move of the checkout service to Kubernetes and carried it out with the team")  # a highlight is evidence for the drafting step
        self.assertEqual(self.prof["roles"][1]["end"], "2021.02")  # the second role ended

    def test_projects_join_the_role_they_name_and_the_rest_become_a_section(self):  # projects
        titles = [p["title"] for p in self.prof["roles"][0]["projects"]]  # the first role's projects
        self.assertIn("Shop analytics", titles)  # its entity is the first employer
        sec = next(s for s in self.prof["sections"] if s["_jr"] == "projects")  # the section for the rest
        self.assertTrue(sec["lines"][0][0].startswith("Open-source CLI"))  # before any work entry: a dated line

    def test_education_skills_and_dated_sections(self):  # the other parts
        e = self.prof["education"][0]  # the school
        self.assertEqual((e["school"], e["major"], e["degree"], e["note"]), ("Example University", "Computer Science", "B.S.", "3.8/4.0"))  # school, field, degree, grade
        self.assertEqual(self.prof["skills"][1], {"category": "Go", "items": ["Go"], "level": "Advanced"})  # a group without keywords names itself
        parts = {s["_jr"]: s for s in self.prof["sections"]}  # sections by their part
        self.assertEqual(parts["awards"]["lines"], [["Hackathon winner", "Example Meetup", "2019.10"]])  # awards as dated lines
        self.assertEqual(parts["languages"]["items"], ["English: Fluent", "Korean: Basic"])  # languages as items

    def test_parts_without_a_place_travel_along(self):  # interests, volunteer work and meta are kept for the way back
        self.assertEqual(set(self.prof["_jsonresume"]), {"interests", "volunteer", "meta"})  # kept under _jsonresume

    def test_not_a_resume_is_refused(self):  # a wrong document
        with self.assertRaises(ValueError):  # is refused
            J.import_resume({"hello": "world"})  # neither basics nor work

    @unittest.skipUnless(shutil.which("node"), "node is not installed")  # the loader is JavaScript
    def test_the_renderer_reads_an_imported_profile(self):  # the profile loader accepts it as it is
        with tempfile.TemporaryDirectory() as tmp:  # a scratch folder
            f = pathlib.Path(tmp) / "p.json"  # the imported profile as a file
            f.write_text(json.dumps(self.prof, ensure_ascii=False), encoding="utf-8")  # as the renderer reads it
            out = subprocess.run(["node", str(ROOT / "src" / "profile_loader.js"), str(f), "en"], capture_output=True, text=True, timeout=60)  # the loader's command line
            self.assertEqual(out.returncode, 0, out.stderr)  # it read it
            self.assertEqual(json.loads(out.stdout)["roles"][0]["org"], "Northwind Payments")  # and found the role


class RoundTripTests(unittest.TestCase):  # both directions
    def test_json_resume_in_and_out_keeps_every_part(self):  # import, then export: the same document, apart from the meta stamp
        back = J.export_profile(J.import_resume(copy.deepcopy(RESUME)), "en")  # in and out
        for key in ("name", "label", "email", "phone", "url", "summary"):  # the basics
            self.assertEqual(back["basics"][key], RESUME["basics"][key], key)  # unchanged
        self.assertEqual(back["basics"]["profiles"][0]["url"], RESUME["basics"]["profiles"][0]["url"])  # the profile link
        self.assertEqual([(w["name"], w["position"], w.get("startDate"), w.get("endDate")) for w in back["work"]],  # work entries with their dates
                         [(w["name"], w["position"], w.get("startDate"), w.get("endDate")) for w in RESUME["work"]])  # the same as the input
        self.assertEqual(back["work"][1]["highlights"], RESUME["work"][1]["highlights"])  # imported highlights come back as they were
        self.assertEqual(back["education"][0]["institution"], "Example University")  # the school
        self.assertEqual(back["skills"][0]["keywords"], ["Kubernetes", "Helm"])  # the keywords
        self.assertEqual(back["awards"][0], {"title": "Hackathon winner", "awarder": "Example Meetup", "date": "2019-10"})  # day precision is not kept: the resume prints months
        self.assertEqual(back["certificates"][0]["issuer"], "Example Org")  # certificates
        self.assertEqual(back["publications"][0]["publisher"], "Example Journal")  # publications
        self.assertEqual(back["languages"], RESUME["languages"])  # languages
        self.assertEqual(back["interests"], RESUME["interests"])  # kept through the profile
        self.assertEqual(back["volunteer"], RESUME["volunteer"])  # volunteer work kept through the profile
        self.assertEqual(back["meta"]["theme"], "elegant")  # the input's meta survives, with Offerowl's stamp added
        self.assertEqual(back["meta"]["offerowl"]["lang"], "en")  # and the language of the export

    def test_an_offerowl_profile_out_and_in_keeps_its_facts(self):  # the example profile through JSON Resume and back
        jr = J.export_profile(copy.deepcopy(SAMPLE), "ko")  # the example profile out
        back = J.import_resume(jr)  # and back in
        self.assertEqual(back["person"]["name"], SAMPLE["person"]["name"])  # the name
        self.assertEqual(back["person"]["email"], SAMPLE["person"]["email"])  # the e-mail
        self.assertEqual([(r["org"], r["title"], r["start"], r["end"]) for r in back["roles"]],  # roles with their dates
                         [(r["org"], r["title"], r["start"], r["end"]) for r in SAMPLE["roles"]])  # the same as the example
        self.assertEqual([s["category"] for s in back["skills"]], [s["category"] for s in SAMPLE["skills"]])  # the skill groups
        self.assertTrue(jr["work"][0]["highlights"][0].startswith("결제 승인 서비스 재설계 (2023.01 ~ 2023.09): "))  # an item as 'Title (period): summary'
        self.assertNotIn("==", json.dumps(jr, ensure_ascii=False))  # highlight marks never leave Offerowl

    def test_a_ledger_profile_exports_in_english(self):  # a ledger's career block gives the English names
        jr = J.export_profile(copy.deepcopy(LEDGER), "en")  # the fictional ledger out in English
        self.assertEqual(jr["basics"]["name"], "Haneul Yoon")  # the Latin name in parentheses
        self.assertEqual([w["name"] for w in jr["work"]], ["Nara Cloud", "Dasom Soft"])  # the English employer names
        self.assertEqual(jr["work"][0]["startDate"], "2022-03")  # ISO dates
        self.assertEqual(jr["education"][0]["institution"], "Gasang University")  # the school from 'Degree  School'

    def test_the_command_line(self):  # import and export write files beside their inputs
        with tempfile.TemporaryDirectory() as tmp:  # a scratch folder
            src = pathlib.Path(tmp) / "resume.json"  # the input
            src.write_text(json.dumps(RESUME), encoding="utf-8")  # written
            r = subprocess.run([sys.executable, str(ROOT / "src" / "write_jsonresume.py"), "import", str(src)], capture_output=True, text=True, timeout=60)  # import
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)  # exit 0
            prof = pathlib.Path(tmp) / "resume.profile.json"  # the profile beside the input
            self.assertTrue(prof.is_file())  # exists
            r = subprocess.run([sys.executable, str(ROOT / "src" / "write_jsonresume.py"), "export", str(prof), "--lang", "en"], capture_output=True, text=True, timeout=60)  # export
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)  # exit 0
            self.assertEqual(json.loads((pathlib.Path(tmp) / "resume.profile.resume.en.json").read_text(encoding="utf-8"))["basics"]["name"], "Mira Solberg")  # the English document beside the profile
            bad = pathlib.Path(tmp) / "bad.json"  # a file that is no resume
            bad.write_text("{}", encoding="utf-8")  # an empty object
            r = subprocess.run([sys.executable, str(ROOT / "src" / "write_jsonresume.py"), "import", str(bad)], capture_output=True, text=True, timeout=60)  # import refuses it
            self.assertEqual(r.returncode, 1)  # not a JSON Resume document


if __name__ == "__main__":
    unittest.main()  # run this file alone
