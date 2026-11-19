#!/usr/bin/env python3
"""What an edition is held against (0.10.0, apps/api/task_compare.py): the pages of the copy that last went out (its
baseline, src/baseline.py), the edition in the other language and its own deck (src/check_parity.py), and a blind edition's
ordinary twin (src/check_blind.py). Fictional people and companies only: the example profiles, and seeded differences.
No typesetting runs: the PDFs and the page pictures are small ones written here, and the checks run on this PC
(OFFEROWL_RENDERER=html), where Node.js reads the profiles as the typesetting does.

  python3 -m unittest tests/app/test_compare.py -v
"""
import copy  # seeded copies of the example
import json  # profiles, reports, records
import os  # the renderer setting
import pathlib  # paths
import shutil  # is node here
import subprocess  # a check run by hand, as a console runs it
import sys  # the import path
import tempfile  # a folder per test
import unittest  # the runner
import zipfile  # a Word file is a zip
from unittest import mock  # stand-ins

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src", ROOT / "tests" / "app", ROOT / "tests" / "render"):  # apps/, the engine, the helpers beside this file
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from test_blind import Builds, Person  # noqa: E402  a fictional person, and builds with the typesetting stood in for
from test_pdftools import H, W, write_pdf  # noqa: E402  a small PDF with a text layer
from apps.api.routes import Router  # noqa: E402  the table the panel calls
from apps.api.workspace import read_json, write_json  # noqa: E402  an edition's files
import baseline as BL  # noqa: E402  src/baseline.py
import check_blind as CB  # noqa: E402  src/check_blind.py
import check_parity as CP  # noqa: E402  src/check_parity.py
import pdfmeta  # noqa: E402  the title and author an export reads
import pdftools  # noqa: E402  is there a PDF reader here

EX = ROOT / "examples"  # the fictional example
NODE = shutil.which("node") is not None  # the profile loader needs it
READER = bool(pdftools.reader())  # the word boxes and the pages need one
try:
    from PIL import Image, ImageDraw  # noqa: F401  the pictures
    PIL = True
except ImportError:  # the pdf extra is not installed here
    PIL = False


def pdf_with_font(path: pathlib.Path, pages: list, font: str = "Helvetica") -> None:
    """write_pdf with another base font: a deck set in a face the resume does not use."""
    write_pdf(path, pages)  # Helvetica
    raw = path.read_bytes().replace(b"/BaseFont /Helvetica", b"/BaseFont /" + font.encode())  # the font's name only: no reader is asked for its offsets
    path.write_bytes(raw)


def page(path: pathlib.Path, size=(300, 420), boxes=(), fill=(20, 20, 20)) -> None:
    """A page picture: white, with dark boxes where text would be."""
    from PIL import Image, ImageDraw  # Pillow
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    for box in boxes:  # each line of 'text'
        d.rectangle(box, fill=fill)
    im.save(path)


def docx(path: pathlib.Path, paras: list) -> None:
    """A Word file with these paragraphs, each a list of runs."""
    body = "".join("<w:p>" + "".join(f"<w:r><w:t>{r}</w:t></w:r>" for r in runs) + "</w:p>" for runs in paras)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')


# ---------------------------------------------------------------- the baseline's pictures


@unittest.skipUnless(PIL, "Pillow is not installed here")
class BaselineTests(unittest.TestCase):
    """src/baseline.py: the kept form, the bands, the picture."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="baseline-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.new, self.kept = self.tmp / "preview", self.tmp / "baseline"
        self.new.mkdir()
        lines = [(30, 40 + 30 * i, 270, 50 + 30 * i) for i in range(10)]  # ten lines of a page
        for n in (1, 2):  # a two-page resume
            page(self.new / f"r-{n}.png", boxes=lines)
        page(self.new / "d-1.png", size=(400, 225), boxes=[(20, 20, 380, 40)])  # a one-slide deck

    def test_an_unchanged_build_changes_nothing_and_the_kept_pictures_are_small(self):
        rec = BL.keep(self.new, self.kept, {"at": "2026-11-13 10:00"})
        self.assertEqual({"r": 2, "d": 1}, rec["pages"])  # every page of each document
        self.assertEqual("2026-11-13 10:00", read_json(self.kept / "baseline.json", {})["at"])  # with what it was told
        found = BL.compare(self.new, self.kept)
        self.assertEqual({"resume": [], "deck": []}, {k: v["pages"] for k, v in found.items()})  # the same pictures: no page changed
        self.assertFalse(BL.changed(found))
        with Image.open(self.kept / "r-1.png") as im:
            self.assertEqual(("P", (200, 280)), (im.mode, im.size))  # two thirds of the preview, with the fixed palette

    def test_a_changed_line_a_moved_highlight_and_an_added_page_are_seen(self):
        BL.keep(self.new, self.kept)
        im = Image.open(self.new / "r-2.png").convert("RGB")
        ImageDraw.Draw(im).rectangle((200, 190, 260, 200), fill="white")  # the end of one line taken away
        im.save(self.new / "r-2.png")
        im = Image.open(self.new / "r-1.png").convert("RGB")
        ImageDraw.Draw(im).rectangle((30, 395, 120, 410), fill=(0xFF, 0xF0, 0xA0))  # a pale highlight where the page was white: its brightness barely moves
        im.save(self.new / "r-1.png")
        page(self.new / "r-3.png", boxes=[(30, 40, 270, 50)])  # a third page
        found = BL.compare(self.new, self.kept)
        self.assertEqual([1, 2, 3], found["resume"]["pages"])  # both changed pages, and the new one
        self.assertEqual((2, 3), (found["resume"]["before"], found["resume"]["after"]))
        band = found["resume"]["bands"]["2"][0]  # where page 2 changed, in the kept form's rows
        self.assertTrue(band[0] <= 195 / 1.5 <= band[1] + 1, band)  # the changed line
        self.assertIn("1", found["resume"]["bands"])  # the highlight shows, by its colour
        out = self.tmp / "changes.png"
        self.assertTrue(BL.picture(self.new, self.kept, found, out))  # the bands, before | now
        with Image.open(out) as sheet:
            self.assertEqual(200 * 2 + 12, sheet.width)  # the two halves side by side

    def test_a_letter_left_from_an_older_build_is_not_this_build_s(self):
        page(self.new / "c-1.png", boxes=[(30, 40, 270, 50)])  # an older build's letter, still in the folder
        BL.keep(self.new, self.kept, only={"r", "d", "c"})
        found = BL.compare(self.new, self.kept, only={"r", "d"})  # this build made no letter
        self.assertEqual({"before": 1, "after": 0, "pages": [1]}, {k: found["cover"][k] for k in ("before", "after", "pages")})  # it is gone, said as a change

    @unittest.skipUnless(READER, "no PDF reader here")
    def test_two_pdfs_are_compared_page_by_page(self):
        a, b = self.tmp / "a.pdf", self.tmp / "b.pdf"
        write_pdf(a, [[(72, 72, 12, "Gildong Hong, Platform Engineer")], [(72, 72, 12, "Alpha Pay 2022.03 - 2024.06")]])
        b.write_bytes(a.read_bytes() + b"\n% bytes after the end\n")  # other bytes, the same pages
        self.assertEqual({"resume": []}, {k: v["pages"] for k, v in BL.compare_pdfs(str(a), str(b)).items()})
        write_pdf(b, [[(72, 72, 12, "Gildong Hong, Platform Engineer")], [(72, 72, 12, "Alpha Pay 2022.03 - 2024.07")]])  # one digit
        found = BL.compare_pdfs(str(a), str(b), str(self.tmp / "c.png"))
        self.assertEqual([2], found["resume"]["pages"])  # the page with the digit
        self.assertTrue((self.tmp / "c.png").is_file())
        self.assertEqual(1, BL.main(["compare", str(a), str(b)]))  # the command line says it with its exit code
        self.assertEqual(0, BL.main(["compare", str(a), str(a)]))


# ---------------------------------------------------------------- a blind edition against its twin


@unittest.skipUnless(READER, "no PDF reader here")
class BlindTwinTests(unittest.TestCase):
    """src/check_blind.py: the words the bars leave stand where the twin has them; every pattern matches some words."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="blind-twin-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lines = [(72, 100 + 20 * i, 11, f"Line {i} of the resume with Kafka at Alphapay") for i in range(8)]  # body lines, under the band, the name last
        self.ordinary = self.tmp / "ordinary.pdf"
        write_pdf(self.ordinary, [self.lines, self.lines])

    def blind(self, pages):
        f = self.tmp / "blind.pdf"
        write_pdf(f, pages)
        return f

    def codes(self, found):
        return [x.code for x in found]

    def test_bars_that_cover_and_move_nothing_pass(self):
        covered = [(x, y, s, t.replace("Alphapay", "########")) for x, y, s, t in self.lines]  # the name under a bar (the documents' bar glyph is no Latin-1 letter)
        self.assertEqual([], CB.layout(self.ordinary, self.blind([covered, covered])))  # a bar of another width with nothing after it moves nothing
        early = [(x, y, s, t.replace("with Kafka at Alphapay", "with ######## at Alphapay")) for x, y, s, t in self.lines]  # a bar narrower than its word
        self.assertEqual(["blind_moved"], self.codes(CB.layout(self.ordinary, self.blind([early, early]))))  # moves the words after it

    def test_a_word_moved_or_pushed_and_a_page_more_fail(self):
        moved = [(x + (3 if i == 2 else 0), y, s, t) for i, (x, y, s, t) in enumerate(self.lines)]  # one line 3 pt to the right
        found = CB.layout(self.ordinary, self.blind([self.lines, moved]))
        self.assertEqual(["blind_moved"], self.codes(found))
        self.assertEqual((2, 3.0), (found[0].values["page"], found[0].values["dx"]))  # where, and how far
        pushed = [(x, y + (60 if i == 5 else 0), s, t) for i, (x, y, s, t) in enumerate(self.lines)]  # a line pushed down past the radius
        self.assertIn("blind_pushed", self.codes(CB.layout(self.ordinary, self.blind([pushed, self.lines]))))
        self.assertEqual(["blind_pages"], self.codes(CB.layout(self.ordinary, self.blind([self.lines, self.lines, self.lines]))))

    def test_patterns_that_match_nothing_are_named_unless_kept(self):
        w = self.tmp / "twin.docx"
        docx(w, [["Built the checkout at ", "Alphapay"], ["Mail gildong@example.com"]])  # the twin's words, run by run
        page_ = self.tmp / "twin_deck.html"
        page_.write_text("<html><body><p>Betacommerce orders</p><script>var x = 'Gammaworks';</script></body></html>", encoding="utf-8")  # a script is no word
        table = {"mask": ["Alphapay", r"gildong@example\.com", "Betacommerce(?=\\s*$)", "Gammaworks", "Deltasoft"], "mask_keep": ["Deltasoft"]}
        self.assertEqual(["Gammaworks"], CB.unmatched(table, CB.docx_texts(w) + CB.html_texts(page_)))  # the end of a text node holds; a name kept on purpose is not named
        note = CB.masks(table, [w, page_])[0]
        self.assertEqual(("blind_unmatched", True, 1), (note.code, note.polish, note.values["n"]))  # a note: a pattern may be meant for another edition
        rep = self.tmp / "rep.json"
        tf = self.tmp / "table.json"
        tf.write_text(json.dumps(table), encoding="utf-8")
        self.assertEqual(0, CB.main(["layout", str(self.ordinary), str(self.ordinary), "--table", str(tf), "--files", str(w), str(page_), "--report", str(rep)]))
        self.assertEqual(["Alphapay", r"gildong@example\.com", "Betacommerce(?=\\s*$)"], read_json(rep, {})["matched"])  # what this edition's words took


# ---------------------------------------------------------------- the Korean and the English edition


def example(lang: str) -> dict:
    """The fictional full example in one language."""
    return json.loads((EX / f"sample_full_{lang}.json").read_text(encoding="utf-8"))


@unittest.skipUnless(NODE, "Node.js is not on this PC: the profile loader cannot run")
class LangsTests(unittest.TestCase):
    """src/check_parity.py langs: the example's editions agree; each seeded difference is named."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="parity-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_langs(self, en: dict, pack: dict | None = None, notes: bool = False):
        """The check on the Korean example and an English profile: (findings, the defects' codes)."""
        (self.tmp / "en.json").write_text(json.dumps(en, ensure_ascii=False), encoding="utf-8")
        va, ca = CP.load(EX / "sample_full_ko.json", EX / "job_full_ko.json")
        vb, cb = CP.load(self.tmp / "en.json", EX / "job_full_en.json")
        found, _ = CP.langs(va, ca, vb, cb, pack or {}, notes)
        return found, sorted({x.code for x in found if not x.polish})

    def test_the_example_agrees(self):
        found, defects = self.run_langs(example("en"))
        self.assertEqual([], defects)  # nothing that keeps the English edition home
        self.assertEqual({"parity_sentences", "parity_entries"}, {x.code for x in found})  # two notes: one sentence joined, and the native language the English names

    def test_seeded_differences_are_named(self):
        en = example("en")
        alpha = en["roles"][0]
        alpha["projects"] = alpha["projects"][:2]  # a project dropped from the translation
        alpha["projects"][1]["period"] = "2023.11 - 2024.06"  # a period changed in one edition
        alpha["projects"][0]["summary"] = alpha["projects"][0]["summary"].replace("idempotency keys", "keys")  # a fact left out
        en["about"][1][1] = en["about"][1][1].split(". ")[0] + "."  # an about-me part cut short
        en["skills"][0]["items"].append("Rust")  # a tool the Korean edition does not list
        en["competencies"] = en["competencies"][:4]  # a competency dropped
        found, defects = self.run_langs(en)
        self.assertEqual(["parity_competencies", "parity_items", "parity_period", "parity_sentences", "parity_skills"], defects)
        words = [x for x in found if x.code == "parity_items"][0]
        self.assertEqual((3, 2), (words.values["ko"], words.values["en"]))  # the counts, for the panel's own words
        self.assertTrue(all(x.polish for x in self.run_langs(en, notes=True)[0]))  # in the source's own edition they are notes

    def test_a_latin_word_left_out_and_the_pack_s_words(self):
        en = example("en")
        beta = en["roles"][1]["projects"][0]
        beta["summary"] = beta["summary"].replace("Kafka", "a message bus")  # the tool's name translated away
        found, defects = self.run_langs(en)
        self.assertIn("parity_words", defects)
        self.assertIn("'Kafka'", [x for x in found if x.code == "parity_words"][0].values["words"])
        _, defects = self.run_langs(en, {"parity": {"aliases": {"Kafka": ["message bus"]}}})  # the person's own alias
        self.assertNotIn("parity_words", defects)
        ko = example("ko")
        self.assertTrue(CP.glossary_miss(ko["about"][0][1], en["about"][0][1], [["공동창업", "co-?found"]]) == [])  # the English says it
        self.assertEqual(["출시"], CP.glossary_miss("출시 범위를 정했다", "We set the scope", [["출시", "launch|release"]]))  # a Korean word whose English is missing

    def test_a_dated_entry_is_a_defect_and_an_undated_line_a_note(self):
        en = example("en")
        talks = en["sections"][0]["groups"][2]["rows"]  # the talks table
        talks[0][2] = "2021.12"  # dated otherwise
        _, defects = self.run_langs(en)
        self.assertIn("parity_dates", defects)


@unittest.skipUnless(NODE and READER, "Node.js or a PDF reader is not on this PC")
class EditionTests(unittest.TestCase):
    """src/check_parity.py edition: the deck's project slides carry the resume's names and periods, its colours and fonts."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="edition-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.view, self.cfg = CP.load(EX / "sample_full_en.json", EX / "job_full_en.json")  # what the English resume prints
        self.raw = example("en")
        self.resume = self.tmp / "resume.pdf"
        write_pdf(self.resume, [[(72, 72, 12, "Gildong Hong")]])

    def deck(self, slides: list, font="Helvetica", html=None) -> pathlib.Path:
        """A deck PDF with one page per (kind, company, title, text), its measurement beside it, and its page when given."""
        f = self.tmp / "deck.pdf"
        pdf_with_font(f, [[(40, 40, 14, title), (40, 80, 11, text)] for _, _, title, text in slides], font)
        probe = {"slides": [{"n": i, "kind": k, "company": c, "title": t} for i, (k, c, t, _) in enumerate(slides, 1)]}
        (self.tmp / "deck.probe.json").write_text(json.dumps(probe), encoding="utf-8")
        if html is not None:
            (self.tmp / "deck.html").write_text(html, encoding="utf-8")
        return f

    def codes(self, deck, pack=None):
        found, paired = CP.edition(self.view, self.cfg, self.raw, self.resume, deck, pack or {})
        return sorted(x.code for x in found if x.code != "dates_order"), paired

    def test_slides_that_carry_the_resume_s_names_and_periods_pass(self):
        deck = self.deck([("front", "", "PORTFOLIO Gildong Hong", ""),
                          ("project", "Alpha Pay", "Payment authorization service redesign", "2023.01 - 2023.09"),
                          ("", "Alpha Pay", "In-house deployment platform build", "2023.10 - 2024.06")])  # a slide of a company with no kind counts too
        self.assertEqual(([], 2), self.codes(deck))

    def test_a_renamed_slide_a_period_apart_and_the_whole_period(self):
        deck = self.deck([("project", "Alpha Pay", "Payments platform rework", "2023.01 - 2023.09"),  # a name the profile does not have
                          ("project", "Alpha Pay", "Payment authorization service redesign", "2023.02 - 2023.09")])  # another start
        self.assertEqual((["deck_period", "deck_unpaired"], 1), self.codes(deck))
        self.assertEqual((["deck_period"], 1), self.codes(deck, {"parity": {"deck_only": ["Payments platform rework"]}}))  # kept apart by the person
        cut = self.deck([("project", "Alpha Pay", "Payment authorization servi", "2023.01 - 2023.09")])  # a measurement that kept the first letters only
        self.assertEqual(([], 1), self.codes(cut))
        deck = self.deck([("project", "Alpha Pay", "Payment authorization service redesign", "2023.01 - 2023.09, 2024.01 - 2024.03")])  # two spells
        self.assertEqual(([], 1), self.codes(deck))  # the resume's period is one of the slide's
        self.assertEqual((["deck_whole_period"], 1), self.codes(deck, {"parity": {"whole_period": ["authorization"]}}))  # unless it must print them all

    def test_a_letter_spaced_period_is_read_beside_a_figure_s_dates(self):
        # a deck that prints the period with wide letter spacing reads back digit by digit; the figure's own month must not stand for it
        self.assertEqual(["2017.03", "2017.11", "2017.06"], CP.dates("2 0 1 7.0 3 ~ 2 0 1 7.1 1 pilot 2017.06"))
        self.assertEqual(["2017.02", "2017.05", "2031.12"], CP.dates("2 0 1 7 .0 2 ~ 2 0 1 7.0 5, 2 0 31 .1 2"))  # the reader's groups vary
        self.assertEqual(["2023.01", "2023.09"], CP.dates("2023.01 2023.09"))  # dates side by side stay two
        self.assertEqual([], CP.dates("2019 2020 1 2 3 4"))  # years alone and loose digits are no dates
        deck = self.deck([("project", "Alpha Pay", "Payment authorization service redesign", "2 0 2 3.0 1 - 2 0 2 3.0 9  pilot 2023.05")])
        self.assertEqual(([], 1), self.codes(deck))
        deck = self.deck([("project", "Alpha Pay", "Payment authorization service redesign", "2 0 2 3.0 2 - 2 0 2 3.0 9  pilot 2023.05")])
        self.assertEqual((["deck_period"], 1), self.codes(deck))  # a spaced period that differs is still a finding

    def test_colours_and_fonts_apart(self):
        deck = self.deck([("project", "Alpha Pay", "Payment authorization service redesign", "2023.01 - 2023.09")], font="Times-Roman",
                         html="<style>:root { --navy: #123456 }</style>")
        self.assertEqual((["deck_font", "deck_theme"], 1), self.codes(deck))
        colours = CP.theme_colours("navy")
        page_ = "<style>" + "".join(f".x{i} {{ color: #{colours[k]} }}" for i, k in enumerate(CP.THEME_KEYS)) + f" mark {{ background: #{CP.HILITE} }}</style>"
        deck = self.deck([("project", "Alpha Pay", "Payment authorization service redesign", "2023.01 - 2023.09")], html=page_)
        self.assertEqual(([], 1), self.codes(deck))  # the resume's colours, and its face

    def test_a_portfolio_the_person_made_is_not_measured(self):
        deck = self.deck([("", "", "", "My own pages")], font="Times-Roman")
        (self.tmp / "deck.probe.json").write_text(json.dumps({"slides": [{"n": 1, "title": "", "issues": []}], "own": True}), encoding="utf-8")
        self.assertEqual(([], 0), self.codes(deck))

    def terms(self, found) -> list:
        """The term_drift findings as (the word to use, the resume's words, the deck's words, a note?)."""
        return [(x.values["first"], x.values["resume"], x.values["deck"], x.polish) for x in found if x.code == "term_drift"]

    def test_one_thing_named_with_two_words_in_the_resume_and_the_deck(self):
        pack = {"parity": {"terms": [["idempotency key", "dedup keys?", "duplicate-request keys?"], ["runbook", "playbook"]]}}  # the first is the word to use
        write_pdf(self.resume, [[(72, 72, 12, "Gildong Hong"), (72, 100, 11, "Split authorization out and set idempotency"),
                                 (72, 114, 11, "keys and a retry policy."), (72, 128, 11, "Wrote a runbook for each incident type.")]])  # a term the line broke inside
        slide = lambda text: ("project", "Alpha Pay", "Payment authorization service redesign", "2023.01 - 2023.09 " + text)  # noqa: E731  the project's slide, its period printed
        deck = self.deck([slide("Dedup keys stopped double charges.")])  # another member of the same group
        self.assertEqual((["term_drift"], 1), self.codes(deck, pack))  # one finding, and the slide is still paired
        found = CP.edition(self.view, self.cfg, self.raw, self.resume, deck, pack)[0]
        self.assertEqual([("idempotency key", "idempotency key", "Dedup keys", False)], self.terms(found))  # the words as printed, the line end a space; a defect
        self.assertEqual(([], 1), self.codes(deck))  # no terms in the pack: nothing to hold the words to
        probe = self.tmp / "deck.probe.json"  # a portfolio the person made: its pages are not measured, its words are read
        probe.write_text(json.dumps({"slides": [{"n": 1, "title": "", "issues": []}], "own": True}), encoding="utf-8")
        self.assertEqual((["term_drift"], 0), self.codes(deck, pack))
        probe.unlink()  # a deck no measurement came with: the same
        self.assertEqual((["term_drift"], 0), self.codes(deck, pack))
        same = self.deck([slide("Idempotency keys stopped double charges.")])  # the same member in both, whatever its case
        self.assertEqual(([], 1), self.codes(same, pack))  # and the runbook only the resume names says nothing
        rep, style = self.tmp / "rep.json", self.tmp / "pack.json"  # the command line, as a build runs it
        style.write_text(json.dumps(pack), encoding="utf-8")
        deck = self.deck([slide("Duplicate-request keys stopped double charges.")])
        argv = ["edition", str(EX / "sample_full_en.json"), str(EX / "job_full_en.json"), str(self.resume), str(deck), "--style", str(style), "--report", str(rep)]
        self.assertEqual(1, CP.main(argv))  # a defect
        got = [x for x in read_json(rep, {})["defects"] if x["code"] == "term_drift"]
        self.assertEqual([("idempotency key", "idempotency key", "Duplicate-request keys")], [(x["first"], x["resume"], x["deck"]) for x in got])  # with its values, for the panel's own words

    def test_one_place_is_one_word_and_a_line_broken_at_a_hyphen_reads_whole(self):
        pack = {"parity": {"terms": [["canary release", "staged rollout", "rollout plan"], ["blue-green deployment", "red-black deployment"]]}}
        write_pdf(self.resume, [[(72, 72, 12, "Gildong Hong"), (72, 100, 11, "Set a staged rollout plan for each service"),
                                 (72, 114, 11, "and moved every release to blue-"), (72, 128, 11, "green deployment.")]])  # a line broken after a hyphen
        deck = self.deck([("project", "Alpha Pay", "Payment authorization service redesign", "2023.01 - 2023.09 A staged rollout with red-black deployment.")])
        found = CP.edition(self.view, self.cfg, self.raw, self.resume, deck, pack)[0]
        self.assertEqual([("blue-green deployment", "blue-green deployment", "red-black deployment", False)], self.terms(found))  # the rollout is one word in both: 'staged rollout plan' holds 'rollout plan' too
        self.assertEqual(["staged rollout"], [w for _, w in CP.term_uses("a staged rollout plan", CP.term_groups(pack["parity"])[0][1])])  # the match that starts first takes the place
        lines = [["blue-"], ["green\u00a0deployment", "and/"], ["or", "a", "C\u2060++"], [" ", "rule", "-"], ["next"]]  # lines of words, as a PDF's boxes hold them
        self.assertEqual("blue-green deployment and/or a C++ rule - next", CP.term_text(lines))  # the typesetting's ties go; a line broken inside a word joins, a dash alone does not
        self.assertEqual("C++", CP.as_written(r"C\+\+"))  # the word to use, as the person reads it

    def test_a_malformed_terms_object_is_refused(self):
        self.assertEqual("", CP.pack_problem({"parity": {"terms": [["idempotency key", "dedup keys?"]]}}))
        for bad in ("idempotency key", ["idempotency key", "dedup key"], [["idempotency key"]], [["idempotency key", " "]],
                    [["idempotency key", 3]], [["idempotency key", "dedup (keys"]]):  # not groups, one word, a blank, not a word, a pattern that does not compile
            self.assertEqual("parity.terms", CP.pack_problem({"parity": {"terms": bad}}), bad)
        self.assertEqual([], CP.term_groups({"terms": [["idempotency key", "dedup (keys"], ["runbook"]]}))  # a pack given by hand: such a group is left out, never a stop

    def test_a_list_the_person_keeps_newest_first(self):
        self.assertEqual([], CP.edition(self.view, self.cfg, self.raw, self.resume, None, {})[0])  # a list's order is the person's own: not held by default
        found, _ = CP.edition(self.view, self.cfg, self.raw, self.resume, None, {"parity": {"newest_first": ["Talks"]}})
        self.assertEqual([("dates_order", False, "2021.11, 2024.05")], [(x.code, x.polish, x.values["dates"]) for x in found])  # the example's talks run oldest first
        papers = {"title": "Papers", "rows": [["First author", "A", "2021.09"], ["First author", "B", "2018.09"], ["Co-author", "C", "2021.11"], ["Co-author", "D", "2019.02"]]}
        self.assertEqual([("Papers", [["2021.09", "2018.09"], ["2021.11", "2019.02"]])], CP.dated_runs(papers))  # newest first within each kind of row
        mixed = {"title": "Credentials", "groups": [{"title": "Held", "lines": [["Cert A", "", "2019.02"], ["Cert B", "", "2012.09"], ["Service", "", "2021.09"]]}]}
        self.assertEqual([("Credentials / Held", [["2019.02", "2012.09", "2021.09"]])], CP.dated_runs(mixed))  # lines are one run: held only when named
        self.assertEqual("parity.newest_first", CP.pack_problem({"parity": {"newest_first": "Talks"}}))  # a list of words, or the pack is refused


# ---------------------------------------------------------------- the command line's build


class WordXmlTests(unittest.TestCase):
    """The word boxes of any reader parse: PDFium marks a hyphen that ends a line with U+FFFE, which XML cannot hold (0.13.1;
    the public CI, which reads PDFs with PDFium, stopped on it)."""

    def test_a_line_end_hyphen_and_control_characters_do_not_stop_the_parser(self):
        import check_lines as CL  # src/check_lines.py, the parser the checks share
        box = 'xMin="1" yMin="1" xMax="2" yMax="2"'  # one box for every element
        xml = (f'<doc><page width="10" height="10"><flow><block {box}><line {box}><word {box}>blue\ufffe</word></line></block>'
               f'<block {box}><line {box}><word {box}>green\x02</word><word {box}>deployment</word></line></block></flow></page></doc>')
        words = [w[2] for w in CL.words_from_xml(xml)]  # the texts, in reading order
        self.assertEqual(["blue-", "green", "deployment"], words)  # the hyphen it stood for; the control character gone


class CommandLineBuildTests(unittest.TestCase):
    """`offerowl build` runs the checks across documents after the document check, as the panel's build does: the resume
    against its deck, and a blind edition against its twin, which it typesets with no bars."""

    def test_the_build_command_checks_the_deck_and_a_blind_edition_s_twin(self):
        import subprocess  # a finished tool, stood in for
        import resume  # src/resume.py
        (ROOT / "output").mkdir(exist_ok=True)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="cli-cross-", dir=str(ROOT / "output")))  # inside the repository, as the container needs
        self.addCleanup(shutil.rmtree, tmp, True)
        job = tmp / "job.json"
        job.write_text(json.dumps({"out": "cli_cross_test", "lang": "ko"}), encoding="utf-8")
        calls, builds = [], []  # the tools run, and the builds made with their environment

        def sh(cmd, env=None):  # every tool says it passed
            calls.append(cmd[:3])
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        def build(profile, cfg=None, env=None):  # the twin is typeset with no blind switch
            builds.append((json.loads(pathlib.Path(cfg).read_text(encoding="utf-8"))["out"], (env or os.environ).get("OFFEROWL_BLIND")))
            return tmp / "twin.pdf"
        for p in (mock.patch.object(resume, "sh", side_effect=sh), mock.patch.object(resume, "build", side_effect=build),
                  mock.patch.object(resume, "build_deck", side_effect=lambda profile, cfg=None, env=None: tmp / "twin_deck.pdf")):
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.dict(os.environ, {"OFFEROWL_BLIND": ""}):  # an ordinary edition: the deck check only
            self.assertEqual(0, resume.cross(str(EX / "sample_full_ko.json"), str(job), tmp / "r.pdf", tmp / "d.pdf"))
        self.assertEqual([["python3", "src/check_parity.py", "edition"]], calls)
        calls.clear()
        with mock.patch.dict(os.environ, {"OFFEROWL_BLIND": "1"}):  # a blind edition: its twin too
            self.assertEqual(0, resume.cross(str(EX / "sample_full_ko.json"), str(job), tmp / "r.pdf", tmp / "d.pdf"))
        self.assertEqual([["python3", "src/check_parity.py", "edition"], ["python3", "src/check_blind.py", "layout"]], calls)
        self.assertEqual([("cli_cross_test_twin", None)], builds)  # under its own name, with no bars
        for f in ("cli_cross_test_twin.cfg.json", "cli_cross_test.job.json"):  # the settings the build staged
            (ROOT / "output" / "_inputs" / f).unlink(missing_ok=True)


# ---------------------------------------------------------------- in the panel: the build, the export, the baseline key


class PanelCompareTests(Builds):
    """The comparisons where the panel runs them: a build's record, the export, the baseline route and its command."""

    def edition(self, a, job, lang, profile: dict, words="Gildong Hong"):
        """An edition as a build leaves it: its profile and settings, a stamped resume, its record."""
        out = a.tasks.build_dir(job, lang)
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "profile.json", profile)
        write_json(out / "job.json", {"lang": lang, "theme": "navy", "out": "x"})
        write_pdf(out / "resume.pdf", [[(72, 72, 12, words)]])
        pdfmeta.stamp(out / "resume.pdf", "Gildong Hong Resume" if lang == "en" else "홍길동 이력서", "Gildong Hong")
        from apps.api.tasks import file_hash  # the hashes a build records
        write_json(out / "build.json", {"lang": lang, "issues": [], "notes": [], "hashes": {"resume.pdf": file_hash(out / "resume.pdf")}, "at": "2026-11-13 09:00"})
        return out

    @unittest.skipUnless(NODE, "Node.js is not on this PC")
    def test_the_export_holds_a_translation_to_its_source(self):
        a = self.person()
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "html"}):  # the check runs on this PC
            en = example("en")
            en["roles"][0]["projects"] = en["roles"][0]["projects"][:2]  # the translation lost a project
            self.edition(a, "-general", "ko", example("ko"))
            self.edition(a, "-general", "en", en)
            self.assertEqual("ko", a.tasks.reference_lang("-general"))  # the fictional person writes in Korean
            with self.assertRaises(ValueError) as e:
                a.tasks.export("-general", "en")
            self.assertEqual("parity:1", str(e.exception))  # one difference, and nothing went
            self.assertEqual(1, len(a.tasks.export("-general", "ko")))  # the source goes
            self.edition(a, "-general", "en", example("en"))  # made again from a whole translation
            self.assertEqual(1, len(a.tasks.export("-general", "en")))
        self.assertFalse(list((ROOT / "output" / "_inputs").glob("parity_*")))  # nothing of the person's stays in the engine's folder

    @unittest.skipUnless(NODE, "Node.js is not on this PC")
    def test_the_checks_read_through_a_pipe_in_a_windows_code_page(self):
        # Windows gives a child's output pipe the code page cp1252, and a finding that names a Korean word stopped the check
        # before it wrote its report: the export said the pair was unchecked, the build found nothing (0.10.0's Windows run)
        a = self.person()
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "html", "PYTHONIOENCODING": "cp1252"}):  # the children inherit it
            en = example("en")
            en["roles"][0]["projects"] = en["roles"][0]["projects"][:2]  # the translation lost a project: a finding in Korean words
            ko_dir, en_dir = self.edition(a, "-general", "ko", example("ko")), self.edition(a, "-general", "en", en)
            self.assertEqual(1, len(a.tasks.parity_now("-general", "en")))  # read through the panel's own call, not 'unchecked'
            rep = self.tmp / "parity.json"  # the command run by hand in such a console
            argv = [sys.executable, "src/check_parity.py", "langs", str(ko_dir / "profile.json"), str(ko_dir / "job.json"),
                    str(en_dir / "profile.json"), str(en_dir / "job.json"), "--report", str(rep)]
            r = subprocess.run(argv, cwd=ROOT, capture_output=True, env=dict(os.environ))  # its bytes as they come
            self.assertEqual(1, r.returncode, r.stderr.decode("utf-8", "replace")[-800:])  # a defect, never a crash
            self.assertEqual(1, len(json.loads(rep.read_text(encoding="utf-8"))["defects"]))  # the report was written
            r.stdout.decode("utf-8")  # and what it printed is UTF-8, whatever the code page said
        a.tasks._clean_engine("-general", "ko", ko_dir)  # nothing left in the engine's folder
        a.tasks._clean_engine("-general", "en", en_dir)

    @unittest.skipUnless(NODE, "Node.js is not on this PC")
    def test_a_build_s_checks_across_documents(self):
        a = self.person()
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "html"}):  # the checks run on this PC
            en = example("en")
            en["skills"][0]["items"].append("Rust")  # the English lists a tool the Korean does not
            ko_dir, en_dir = self.edition(a, "-general", "ko", example("ko")), self.edition(a, "-general", "en", en)
            name = "owl_" + a.tasks.short("-general") + "_en"  # the edition's name in the engine's folder
            got = a.tasks.cross_checks("-general", "en", en_dir, name, self.tmp_pdf(en_dir / "resume.pdf"), None, dict(os.environ), None)
            self.assertIn("parity_skills", [x["code"] for x in got["checks"]])  # a defect of the translation
            self.assertTrue(got["issues"])  # with its words for the build's own list
            got = a.tasks.cross_checks("-general", "ko", ko_dir, name[:-2] + "ko", self.tmp_pdf(ko_dir / "resume.pdf"), None, dict(os.environ), None)
            self.assertIn("parity_skills", [x["code"] for x in got["polish"]])  # a note on the source
            self.assertFalse([x for x in got["checks"] if x["code"].startswith("parity")])
            a.tasks._clean_engine("-general", "ko", ko_dir)  # the build's clean-up
            a.tasks._clean_engine("-general", "en", en_dir)
        left = [f.name for f in (ROOT / "output" / "_inputs").glob(f"owl_{a.tasks.short('-general')}_*")]
        self.assertEqual([], left)  # the other edition's copies went with the edition's own

    def test_a_blind_edition_whose_twin_failed_is_not_taken_for_checked(self):
        a = self.person()
        self.stand_in(a)
        import resume  # the typesetting, stood in for by stand_in
        made = resume.build.side_effect  # the stand-in's resume

        def build(profile, cfg=None, env=None):  # the blind resume is made; its ordinary twin is not
            if "_twin" in str(cfg):
                raise SystemExit("no LibreOffice for the twin")
            return made(profile, cfg, env)
        from apps.api.task_compare import Comparisons  # the real checks across documents, under the stand-in
        with mock.patch.object(a.tasks, "cross_checks", side_effect=lambda *x: Comparisons.cross_checks(a.tasks, *x)), \
             mock.patch.object(a.tasks, "_compare_tool", return_value=None), mock.patch.object(resume, "build", side_effect=build):
            a.tasks._build("-general", "ko", "navy", 3, False, False, True)  # a blind edition
        rec = self.record(a, "-general")
        self.assertIn("blind_unchecked", [x["code"] for x in rec["checks"]])  # its bars were not checked: never taken for passed
        self.assertTrue(rec["issues"])  # and the export says so

    def tmp_pdf(self, src: pathlib.Path | None = None):
        """A PDF in the engine's folder, where a build's own PDFs are (a check stages a copy of one from anywhere else)."""
        (ROOT / "output").mkdir(exist_ok=True)
        d = pathlib.Path(tempfile.mkdtemp(prefix="cmp-made-", dir=str(ROOT / "output")))
        self.addCleanup(shutil.rmtree, d, True)
        f = d / "r.pdf"
        if src is not None:  # a copy of an edition's own
            f.write_bytes(src.read_bytes())
        else:
            write_pdf(f, [[(72, 72, 12, "Gildong Hong")]])
        return f

    def test_patterns_another_blind_edition_matched_are_not_dead(self):
        a = self.person()
        a.set_blind({"table": {"mask": ["Alphapay", "Betacommerce", "Gammaworks"], "mask_keep": ["Gammaworks"]}})
        other = a.tasks.build_dir("-general", "en")  # an English blind edition made before with this table
        other.mkdir(parents=True)
        write_json(other / "build.json", {"blind": True, "blind_table": a.tasks.blind_stamp()})
        write_json(other / "blind_matched.json", ["Betacommerce"])  # what its words took
        out_dir = a.tasks.build_dir("-general", "ko")
        out_dir.mkdir(parents=True)
        write_json(out_dir / "profile.json", example("ko"))
        write_json(out_dir / "job.json", {"lang": "ko"})
        twin = {"pdf": self.tmp_pdf(), "deck": None, "docx": None, "page": None}
        reports = {"edition": {"defects": [], "polish": []}, "layout": {"defects": [], "polish": [], "matched": ["Alphapay"]}}
        with mock.patch.object(a.tasks, "_compare_tool", side_effect=lambda argv, env, rep: reports["layout" if "check_blind.py" in argv[1] else "edition"]):
            got = a.tasks.cross_checks("-general", "ko", out_dir, "owl_x_ko", self.tmp_pdf(), None, {}, twin)
        self.assertEqual(["Alphapay"], got["matched"])  # kept with this edition
        self.assertEqual([], [x for x in got["polish"] if x["code"] == "blind_unmatched"])  # Betacommerce is the English edition's; Gammaworks is kept on purpose
        reports["layout"]["matched"] = []  # this edition's words took none of them
        with mock.patch.object(a.tasks, "_compare_tool", side_effect=lambda argv, env, rep: reports["layout" if "check_blind.py" in argv[1] else "edition"]):
            got = a.tasks.cross_checks("-general", "ko", out_dir, "owl_x_ko", self.tmp_pdf(), None, {}, twin)
        self.assertEqual([(1, "Alphapay")], [(x["n"], x["patterns"]) for x in got["polish"] if x["code"] == "blind_unmatched"])
        a.tasks._clean_engine("-general", "ko", out_dir)  # the edition's staged profile and settings go, as a build's clean-up takes them

    @unittest.skipUnless(PIL, "Pillow is not installed here")
    def test_the_baseline_is_kept_on_export_and_a_later_build_names_what_changed(self):
        a = self.person()
        out = self.edition(a, "-general", "ko", example("ko"))
        (out / "preview").mkdir()
        for n in (1, 2):  # its page pictures, as the build drew them
            page(out / "preview" / f"r-{n}.png", boxes=[(30, 40 + 30 * i, 270, 50 + 30 * i) for i in range(10)])
        self.assertIsNone(a.tasks.compare_baseline("-general", "ko", out, {}))  # nothing kept yet
        a.tasks.export("-general", "ko")  # it goes out
        kept = read_json(a.tasks.baseline_dir("-general", "ko") / "baseline.json", {})
        self.assertEqual(("export", {"r": 2}), (kept["why"], kept["pages"]))  # its pages are the baseline
        im = Image.open(out / "preview" / "r-2.png").convert("RGB")
        ImageDraw.Draw(im).rectangle((150, 100, 270, 110), fill="white")  # a later build changed a line of page 2
        im.save(out / "preview" / "r-2.png")
        got = a.tasks.compare_baseline("-general", "ko", out, {"resume.pdf": "another"})
        self.assertEqual(([2], "export", True), (got["docs"]["resume"]["pages"], got["why"], got["picture"]))
        rec = read_json(out / "build.json", {})
        write_json(out / "build.json", {**rec, "changes": got})  # as the build records it
        r = Router(a)
        status, body, kind = r.handle("GET", "/api/v1/jobs/-general/files/ko/preview/changes.png")
        self.assertEqual((200, "image/png"), (status, kind))  # the picture, for the panel
        status, body, _ = r.handle("POST", "/api/v1/jobs/baseline", {"state": "0"}, {"job": "-general", "lang": "ko"})
        self.assertEqual((200, "accepted", {"r": 2}), (status, body["baseline"]["why"], body["baseline"]["pages"]))  # this build is the baseline now
        self.assertNotIn("changes", read_json(out / "build.json", {}))  # and shows no changes
        self.assertFalse((out / "preview" / "changes.png").exists())
        self.assertEqual([], a.tasks.compare_baseline("-general", "ko", out, {})["docs"]["resume"]["pages"])
        status, body, _ = r.handle("POST", "/api/v1/jobs/baseline", {"state": "0"}, {"job": "-general", "lang": "en"})
        self.assertEqual((400, "not_built"), (status, body.get("what")))  # an edition never made
        with mock.patch.object(a.tasks, "page_reader", return_value="pdfium 9999"):  # another reader draws the pages now
            self.assertTrue(a.tasks.compare_baseline("-general", "ko", out, {"resume.pdf": "x"})["reader_changed"])

    @unittest.skipUnless(PIL, "Pillow is not installed here")
    def test_the_command_line_shows_and_accepts_through_the_same_route(self):
        a = self.person()
        out = self.edition(a, "-general", "ko", example("ko"))
        (out / "preview").mkdir()
        page(out / "preview" / "r-1.png", boxes=[(30, 40, 270, 50)])
        self.assertEqual(1, BL.main(["show", "-general", "--lang", "en", "--data", str(self.tmp)]))  # never made
        self.assertEqual(0, BL.main(["show", "-general", "--data", str(self.tmp)]))  # no baseline yet: said, not a failure
        self.assertEqual(0, BL.main(["accept", "-general", "--lang", "ko", "--data", str(self.tmp)]))
        self.assertEqual("accepted", read_json(a.tasks.baseline_dir("-general", "ko") / "baseline.json", {})["why"])
        rec = read_json(out / "build.json", {})
        write_json(out / "build.json", {**rec, "changes": {"since": "2026-11-13 10:00", "why": "accepted", "docs": {"resume": {"before": 1, "after": 1, "pages": [1]}}}})
        self.assertEqual(1, BL.main(["show", "-general", "--data", str(self.tmp)]))  # a page changed: said with the exit code


if __name__ == "__main__":
    unittest.main()
