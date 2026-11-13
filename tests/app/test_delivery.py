#!/usr/bin/env python3
"""What the export writes besides the checked PDFs (apps/api/delivery.py): the resume's and the cover letter's Word files made
ready for Word, the deck as a PowerPoint file beside its PDF, each kept home with its reason when Word or PowerPoint lays
it out otherwise; a submitted edition's frozen files as they were; and the general edition's portfolio kept on the
Desktop, which replaces only the copy it wrote itself. The fictional example person, small files made here, Word and
PowerPoint stood in for: no Office program and no typesetting runs.

  python3 -m unittest tests/app/test_delivery.py -v
"""
import json  # the build's record
import os  # the Desktop and the Office switch
import pathlib  # paths
import shutil  # the edition's files
import sys  # the import path
import unittest  # the runner
import zipfile  # the Word and PowerPoint files
from unittest import mock  # Word, PowerPoint and the typesetting stood in for

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src", ROOT / "tests" / "app", ROOT / "tests" / "render"):  # apps/, the engine, the helpers beside this file
    sys.path.insert(0, str(p))
from test_blind import Person  # noqa: E402  the fictional person with a Desktop of the test's own
from test_office import DECK, WORDS, deck_pdf, make_docx, png  # noqa: E402  a fictional resume DOCX and deck PDF
from test_pdftools import write_pdf  # noqa: E402  a small PDF with a text layer
from apps.api import delivery  # noqa: E402  the module under test
from apps.api.routes import Router  # noqa: E402  the table the panel calls
from apps.api.tasks import file_hash  # noqa: E402  what a build records
from apps.api.workspace import read_json, sha256  # noqa: E402  the record and the hashes
import deck_pptx  # noqa: E402  the PowerPoint copy's DPI
import office_check  # noqa: E402  Word and PowerPoint, stood in for
import pdfmeta  # noqa: E402  the title and the author


class Edition(Person):
    """The general edition made by hand: a one-page resume with its Word file, the fictional deck, their checked record."""

    def setUp(self):
        p = mock.patch.dict(os.environ, {"OFFEROWL_OFFICE": "0"})  # no Office of this PC is ever started by a test
        p.start()
        self.addCleanup(p.stop)
        self.a = self.person()  # the fictional person, every fact kept, a Desktop of the test's own
        self.ed = self.made("-general")  # the general edition
        self.desk = self.tmp / "Desktop"  # where the export writes
        for p in (mock.patch.object(self.a.tasks, "_previews", side_effect=self.previews),  # the deck's pages drawn, with no reader needed
                  mock.patch.object(self.a.tasks, "pdf_text", return_value=WORDS)):  # and their words
            p.start()
            self.addCleanup(p.stop)

    def made(self, job: str) -> pathlib.Path:
        """A job's Korean edition, as a build leaves it: the resume, its Word file, the deck and their checked record."""
        ed = self.a.tasks.build_dir(job, "ko")  # the edition's folder
        ed.mkdir(parents=True)
        write_pdf(ed / "resume.pdf", [[(72, 72, 12, "Gildong Hong")]])  # one page
        pdfmeta.stamp(ed / "resume.pdf", "홍길동 이력서", "홍길동")  # its title and author, as the build writes them
        make_docx(ed / "resume.docx")  # its Word file, of the shape the typesetting writes
        deck_pdf(ed / "deck.pdf", DECK)  # the deck, three pages with links
        pdfmeta.stamp(ed / "deck.pdf", "홍길동 포트폴리오", "홍길동")
        self.record(ed)
        return ed

    def record(self, ed: pathlib.Path | None = None, **extra) -> None:
        """The build's record of what it checked."""
        ed = ed or self.ed  # the general edition unless named
        rec = {"pages": 1, "issues": [], "hashes": {f: file_hash(ed / f) for f in ("resume.pdf", "deck.pdf", "cover.pdf") if (ed / f).is_file()}, **extra}
        (ed / "build.json").write_text(json.dumps(rec), encoding="utf-8")

    def previews(self, pdf, folder, prefix, dpi, last=None):  # what Tasks._previews draws: one PNG per page, at the asked resolution
        folder.mkdir(parents=True, exist_ok=True)
        pages = pdfmeta.page_links(pdf)  # each page's size
        for i, page in enumerate(pages, 1):
            png(folder / f"{prefix}-{i}.png", round(page["width"] * dpi / 72), round(page["height"] * dpi / 72))
        return len(pages)

    def on_desk(self) -> list[str]:
        return sorted(p.name for p in self.desk.iterdir()) if self.desk.is_dir() else []

    def office(self, word=None, powerpoint=None, fail=False):
        """Word and PowerPoint stood in for: each answers its count (None: not on this PC); fail: there, but it did not open."""
        counts = {"word": word, "powerpoint": powerpoint}

        def count(app, path):
            if fail:
                raise office_check.OfficeFailed(f"{app} did not open the file")
            return counts[app]
        return [mock.patch.object(office_check, "available", side_effect=lambda app: counts[app] is not None or fail),
                mock.patch.object(office_check, "count", side_effect=count)]


class WordFiles(Edition):
    def test_the_word_file_goes_ready_for_word(self):
        self.a.set_settings({"export_extras": True})  # Word files too
        names = self.a.tasks.export("-general", "ko")
        self.assertEqual(["홍길동 이력서.pdf", "홍길동 이력서.docx", "홍길동 포트폴리오.pdf"], names)
        with zipfile.ZipFile(self.desk / "홍길동 이력서.docx") as z:
            self.assertIn("<w:embedRegular", z.read("word/fontTable.xml").decode())  # Pretendard inside
            self.assertIn('w:lineRule="exact"', z.read("word/document.xml").decode())  # LibreOffice's line heights
            self.assertIn("<dc:title>홍길동 이력서</dc:title>", z.read("docProps/core.xml").decode())  # the PDF's title
        self.assertEqual(b"PK", (self.ed / "resume.docx").read_bytes()[:2])  # the edition's own file is the build's, untouched
        self.assertNotIn(b"embedRegular", zipfile.ZipFile(self.ed / "resume.docx").read("word/fontTable.xml"))

    def test_word_lays_it_out_on_other_pages_so_it_stays_home(self):
        self.a.set_settings({"export_extras": True})
        refused = []
        patches = self.office(word=2)  # Word gives the one-page resume two pages
        for p in patches:
            p.start()
        try:
            names = self.a.tasks.export("-general", "ko", refused)
        finally:
            for p in patches:
                p.stop()
        self.assertEqual([{"file": "resume.docx", "why": "word_pages:2:1"}], refused)
        self.assertEqual(["홍길동 이력서.pdf", "홍길동 포트폴리오.pdf"], names)  # the PDFs went all the same
        self.assertEqual(["홍길동 이력서.pdf", "홍길동 포트폴리오.pdf"], self.on_desk())

    def test_word_that_agrees_or_does_not_open(self):
        self.a.set_settings({"export_extras": True})
        for p in self.office(word=1):  # the same page count: it goes
            p.start()
            self.addCleanup(p.stop)
        self.assertIn("홍길동 이력서.docx", self.a.tasks.export("-general", "ko"))
        refused = []
        with mock.patch.object(office_check, "count", side_effect=office_check.OfficeFailed("Word did not open the file")):
            self.a.tasks.export("-general", "ko", refused)
        self.assertEqual([{"file": "resume.docx", "why": "word_unopened"}], refused)  # there, and it did not open: never sent unseen

    def test_a_word_file_that_is_not_one_stays_home_and_the_persons_own_goes_as_it_came(self):
        self.a.set_settings({"export_extras": True})
        (self.ed / "resume.docx").write_bytes(b"PK not a Word file")  # broken
        refused = []
        self.a.tasks.export("-general", "ko", refused)
        self.assertEqual([{"file": "resume.docx", "why": "docx_unready"}], refused)
        (self.ed / "own_resume.docx").write_bytes(b"PK the person's own")  # the person brought this one in: it is theirs
        shutil.copyfile(self.ed / "own_resume.docx", self.ed / "resume.docx")
        names = self.a.tasks.export("-general", "ko", refused := [])
        self.assertEqual([], refused)
        self.assertEqual(b"PK the person's own", (self.desk / [n for n in names if n.endswith(".docx")][0]).read_bytes())  # byte for byte

    def test_the_panel_hears_which_file_stayed_home_and_why(self):
        self.a.set_settings({"export_extras": True})
        for p in self.office(word=3):
            p.start()
            self.addCleanup(p.stop)
        status, body, _ = Router(self.a).handle("POST", "/api/v1/jobs/export", None, {"job": "-general", "lang": "ko"})  # as the panel calls it
        self.assertEqual(200, status)
        self.assertEqual([{"file": "resume.docx", "why": "word_pages:3:1"}], body["refused"])
        self.assertEqual(["홍길동 이력서.pdf", "홍길동 포트폴리오.pdf"], body["exported"])

    def test_a_submitted_editions_frozen_files_go_byte_for_byte(self):
        self.a.set_settings({"export_extras": True})
        named = self.a.add_edition({"name": "Platform roles"})  # an edition that can be submitted and locked
        self.made(named)
        rec = self.a.tasks.lock(named, "ko")  # what was sent, frozen
        frozen = self.a.ws.job_dir(named) / "submitted" / pathlib.Path(rec["folder"]).name / "resume.docx"
        names = self.a.tasks.export(named, "ko")  # the copies that went out
        docx = [n for n in names if n.endswith(".docx")]
        self.assertEqual(frozen.read_bytes(), (self.desk / docx[0]).read_bytes())  # never made ready again: the record of what was sent
        self.assertEqual(rec["files"]["resume.docx"], sha256(frozen))  # and the frozen copy itself unchanged


class PowerPointFile(Edition):
    def test_the_deck_goes_as_powerpoint_beside_its_pdf_when_asked(self):
        self.assertNotIn("홍길동 포트폴리오.pptx", self.a.tasks.export("-general", "ko"))  # not unless asked
        self.a.set_settings({"export_pptx": True})
        names = self.a.tasks.export("-general", "ko")
        self.assertEqual(["홍길동 이력서 (2).pdf", "홍길동 포트폴리오 (2).pdf", "홍길동 포트폴리오 (2).pptx"], names)  # under the deck's own name
        made = self.desk / "홍길동 포트폴리오 (2).pptx"
        self.assertEqual([], deck_pptx.problems(made, self.ed / "deck.pdf", "홍길동 포트폴리오", "홍길동", WORDS.split("\f")))  # its pages, links and words
        self.assertEqual(["PORTFOLIO Gildong Hong", "OVERVIEW", ""], deck_pptx.described(made))

    def test_powerpoint_with_other_slides_or_none_drawn_keeps_it_home(self):
        self.a.set_settings({"export_pptx": True})
        refused = []
        with mock.patch.object(office_check, "available", side_effect=lambda app: app == "powerpoint"), \
                mock.patch.object(office_check, "count", return_value=2):  # two slides for three pages
            names = self.a.tasks.export("-general", "ko", refused)
        self.assertEqual([{"file": "deck.pptx", "why": "ppt_slides:2:3"}], refused)
        self.assertNotIn(".pptx", " ".join(names))
        self.assertIn("홍길동 포트폴리오.pdf", names)  # the deck itself went
        with mock.patch.object(self.a.tasks, "_previews", return_value=0):  # no page could be drawn on this PC
            self.a.tasks.export("-general", "ko", refused := [])
        self.assertEqual([{"file": "deck.pptx", "why": "pptx_unmade"}], refused)

    def test_a_copy_that_fails_after_the_powerpoint_file_takes_everything_back(self):
        self.a.set_settings({"export_pptx": True})
        write_pdf(self.ed / "cover.pdf", [[(72, 72, 12, "Gildong Hong")]])  # a letter whose copy will not read back
        pdfmeta.stamp(self.ed / "cover.pdf", "홍길동 자기소개서", "홍길동")
        self.record()
        real = self.a.tasks.reads_back
        with mock.patch.object(self.a.tasks, "reads_back", side_effect=lambda copy, src: src.name != "cover.pdf" and real(copy, src)):
            with self.assertRaises(ValueError):
                self.a.tasks.export("-general", "ko")
        self.assertEqual([], self.on_desk())  # the PowerPoint file went with the rest: nothing half done


class DeskPortfolio(Edition):
    """The general edition's portfolio kept on the Desktop: off by default, replacing only its own copy."""

    def keep(self):
        return delivery.keep_portfolio(self.a.tasks, "ko")

    def new_deck(self, text: str) -> None:
        """The deck made again with other words, and its build's record."""
        deck_pdf(self.ed / "deck.pdf", [(192, 108, [], text)])
        pdfmeta.stamp(self.ed / "deck.pdf", "홍길동 포트폴리오", "홍길동")
        self.record()

    def test_off_unless_asked(self):
        self.assertIsNone(self.keep())
        self.assertEqual([], self.on_desk())
        self.assertEqual({"kept": []}, self.a.state()["desk"])

    def test_turned_on_it_copies_at_once_and_after_each_build_replaces_its_own_copy(self):
        self.a.set_settings({"desk_portfolio": True})  # an edition that passed already goes now
        self.assertEqual(["홍길동 포트폴리오.pdf"], self.on_desk())
        self.assertEqual((self.ed / "deck.pdf").read_bytes(), (self.desk / "홍길동 포트폴리오.pdf").read_bytes())
        self.assertEqual({"kept": ["홍길동 포트폴리오.pdf"]}, self.a.state()["desk"])  # the panel shows its name, never a path
        self.new_deck("Gildong Hong, new")  # made again
        self.assertEqual("홍길동 포트폴리오.pdf", self.keep())
        self.assertEqual(["홍길동 포트폴리오.pdf"], self.on_desk())  # replaced in place, no second copy
        self.assertEqual((self.ed / "deck.pdf").read_bytes(), (self.desk / "홍길동 포트폴리오.pdf").read_bytes())
        self.assertEqual(sha256(self.ed / "deck.pdf"), read_json(self.a.ws.path(*delivery.RECORD), {})["ko"]["sha256"])  # recognised next time

    def test_a_file_it_did_not_write_is_never_touched(self):
        self.desk.mkdir(parents=True)
        (self.desk / "홍길동 포트폴리오.pdf").write_bytes(b"the person's own portfolio")  # same name, not its copy
        self.a.set_settings({"desk_portfolio": True})
        self.assertEqual(b"the person's own portfolio", (self.desk / "홍길동 포트폴리오.pdf").read_bytes())
        self.assertEqual(["홍길동 포트폴리오 (2).pdf", "홍길동 포트폴리오.pdf"], self.on_desk())  # the next free name
        self.new_deck("again")
        self.assertEqual("홍길동 포트폴리오 (2).pdf", self.keep())  # its own copy, replaced
        self.assertEqual(b"the person's own portfolio", (self.desk / "홍길동 포트폴리오.pdf").read_bytes())

    def test_its_copy_changed_by_the_person_is_theirs_now(self):
        self.a.set_settings({"desk_portfolio": True})
        (self.desk / "홍길동 포트폴리오.pdf").write_bytes(b"edited by the person")  # its copy, changed since
        self.new_deck("again")
        self.assertEqual("홍길동 포트폴리오 (2).pdf", self.keep())
        self.assertEqual(b"edited by the person", (self.desk / "홍길동 포트폴리오.pdf").read_bytes())  # left as it is

    def test_a_new_name_replaces_its_old_copy_and_nothing_else(self):
        self.a.set_settings({"desk_portfolio": True})
        self.a.details({"fields": {"name": "한서연"}})  # the person's name, typed anew: the file's name changes
        name = self.keep()
        self.assertNotEqual("홍길동 포트폴리오.pdf", name)
        self.assertEqual([name], self.on_desk())  # the old copy, its own and unchanged, is gone with it

    def test_a_build_that_failed_its_checks_or_a_blind_one_never_goes(self):
        self.a.set_settings({"desk_portfolio": True})
        before = (self.desk / "홍길동 포트폴리오.pdf").read_bytes()
        self.new_deck("broken")
        self.record(issues=["page 3 of 2"])  # failed
        self.assertIsNone(self.keep())
        self.record(blind=True)  # a blind edition: never under the portfolio's own name
        self.assertIsNone(self.keep())
        self.assertEqual(before, (self.desk / "홍길동 포트폴리오.pdf").read_bytes())  # the last copy that passed stays

    def test_the_export_names_the_kept_copy_instead_of_a_second_one(self):
        self.a.set_settings({"desk_portfolio": True})
        names = self.a.tasks.export("-general", "ko")
        self.assertEqual(["홍길동 이력서.pdf", "홍길동 포트폴리오.pdf"], names)  # the kept copy, named
        self.assertEqual(["홍길동 이력서.pdf", "홍길동 포트폴리오.pdf"], self.on_desk())  # no (2) beside it
        self.a.set_settings({"desk_portfolio": False})  # turned off: the export writes its own copy again
        self.assertIn("홍길동 포트폴리오 (2).pdf", self.a.tasks.export("-general", "ko"))
        self.assertEqual({"kept": []}, self.a.state()["desk"])  # and the panel lists nothing kept

    def test_a_build_of_the_general_edition_keeps_it(self):
        """The build's own end: typesetting stood in for, the deck's copy follows it to the Desktop."""
        import resume  # the steps stood in for
        made = self.tmp / "made"
        made.mkdir()

        def build(profile, cfg=None, env=None):  # a resume with its title, as resume.py writes it
            write_pdf(made / "r.pdf", [[(72, 72, 12, "Gildong Hong")]])
            pdfmeta.stamp(made / "r.pdf", "홍길동 이력서", "홍길동")
            return made / "r.pdf"

        def build_deck(profile, cfg=None, env=None):
            deck_pdf(made / "d.pdf", DECK)
            pdfmeta.stamp(made / "d.pdf", "홍길동 포트폴리오", "홍길동")
            return made / "d.pdf"
        self.a.set_settings({"desk_portfolio": True})
        for p in (mock.patch.object(resume, "build", side_effect=build), mock.patch.object(resume, "build_deck", side_effect=build_deck),
                  mock.patch.object(resume, "build_plain", side_effect=SystemExit("no plain words")),
                  mock.patch.object(self.a.tasks, "_check", return_value=([], [])), mock.patch.object(self.a.tasks, "engine_ready", return_value="")):
            p.start()
            self.addCleanup(p.stop)
        (self.desk / "홍길동 포트폴리오.pdf").unlink()  # gone from the Desktop since
        self.a.tasks._build("-general", "ko", "navy", 3, False, False, False)
        self.assertEqual("홍길동 포트폴리오.pdf", self.a.tasks.state()["build:-general"]["result"]["desk"])
        self.assertEqual((self.ed / "deck.pdf").read_bytes(), (self.desk / "홍길동 포트폴리오.pdf").read_bytes())
        self.a.tasks._build("-general", "ko", "navy", 3, False, False, True)  # a blind build of it
        self.assertIsNone(self.a.tasks.state()["build:-general"]["result"]["desk"])  # never copied


if __name__ == "__main__":
    unittest.main()
