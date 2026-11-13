"""The interview deck (src/interview/deck.py) on the fictional example kit: what it prints, in which order, and how."""
import pathlib  # paths
import re  # the page's parts
import shutil  # the output folder
import tempfile  # an output folder per test
import unittest  # the runner

from helpers import example_job  # the fictional job, with the import path set

from interview import deck  # the deck


class DeckTest(unittest.TestCase):
    def setUp(self):
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-deck-"))  # never the repository
        self.addCleanup(shutil.rmtree, self.out, True)  # removed afterwards
        self.job = example_job()  # the kit
        self.assertEqual(deck.main(self.job, out=str(self.out), lang="ko"), 0)  # written
        self.html = (self.out / "deck.html").read_text(encoding="utf-8")  # the page to print

    def scenes(self):
        """[(id, html)] of the scripts, in deck order."""
        parts = re.split(r'(?=<section class="scene")', self.html)  # one piece per script
        return [(re.search(r'data-id="([^"]+)"', p).group(1), p) for p in parts if p.startswith('<section class="scene"')]

    def test_pages_cover_and_posting(self):
        """16:9 pages; the cover names the company; the posting comes line by line with the script for each line."""
        self.assertIn("@page { size: 297mm 167.06mm", self.html)  # landscape 16:9
        self.assertIn('<section class="pg cover">', self.html)  # a cover
        self.assertIn("감마클라우드", self.html)  # with the company's name
        self.assertIn("공고 줄마다 꺼낼 대본", self.html)  # the posting's page
        rows = re.findall(r"<tr><td>", self.html)  # one row per posting line
        self.assertGreaterEqual(len(rows), 10)  # the example posting has more than ten lines
        self.assertIn("대본 없음", self.html)  # a line no script answers says so

    def test_each_script_once_in_the_interview_s_order(self):
        """A script prints once, in the order an interview runs, and lists the other questions it answers."""
        ids = [i for i, _ in self.scenes()]  # in deck order
        self.assertTrue(ids, "no script printed")  # the example has scripts
        self.assertEqual(len(ids), len(set(ids)))  # none twice
        parts = re.findall(r'<div class="part">([^<]+)</div>', self.html)  # each script's part, in order
        order = ["첫 인사", "자기소개와 인성", "지원 동기", "공고 줄", "이력서", "포트폴리오", "예상 상황", "기술 질문", "마지막 역질문"]  # as an interview runs
        seen = [order.index(p) for p in parts]  # their places
        self.assertEqual(seen, sorted(seen))  # never out of order
        self.assertEqual("첫 인사", parts[0])  # the opening first
        self.assertIn("이 대본으로 답할 다른 질문", self.html)  # a script that answers several questions names them

    def test_the_translation_comes_after_the_dialogue(self):
        """English first: the translation is one note after the spoken lines, never between them."""
        for sid, piece in self.scenes():  # every script
            if 'class="note tr"' not in piece:  # a script with no translation
                continue
            last_line = max(piece.rfind('class="me"', 0, piece.find('class="note tr"')), piece.rfind('class="iv"', 0, piece.find('class="note tr"')))  # the dialogue's last line
            self.assertLess(last_line, piece.find('class="note tr"'), sid)  # comes before the note
            talk = piece[piece.find('<div class="talk">'):piece.find('class="note tr"')]  # the spoken lines alone
            self.assertNotRegex(talk, "[가-힣]{4,}(?![^<]*</span>)", sid)  # no Korean sentence among them (stage notes in grey are allowed)

    def test_marks_rendered_and_english_ends_with_the_lines_that_buy_time(self):
        """The writer's marks become bold and the highlighter; an English kit ends with the lines for getting stuck."""
        body = self.html.split("</style>", 1)[1]  # the page without its stylesheet
        self.assertNotIn("**", body)  # no raw stress marks
        self.assertNotIn("==", body)  # no raw highlighter marks
        self.assertIn('<mark class="hl">', body)  # the key phrase on the highlighter
        self.assertIn('<span class="br">/</span>', body)  # a breath
        self.assertIn("막힐 때 쓰는 말", body)  # the example's scripts are in English: the last page is there
        self.assertLess(body.rfind('<section class="scene"'), body.find("막힐 때 쓰는 말"))  # and it comes last

    def test_a_chosen_part_and_scripts(self):
        """kinds and ids narrow the deck; a script asked for by id prints even past a part's limit."""
        only = deck.page(self.job, kinds="opening", lang="ko")  # the opening alone
        parts = set(re.findall(r'<div class="part">([^<]+)</div>', only))  # its parts
        self.assertEqual({"첫 인사"}, parts)  # nothing else
        self.assertNotIn("공고 줄마다 꺼낼 대본", only)  # nor the posting's page
        some = deck.page(self.job, ids="A1", lang="ko")  # one script
        self.assertEqual(['A1'], re.findall(r'<section class="scene" data-id="([^"]+)"', some))  # that one
        none = deck.page(self.job, ids="NOPE", lang="ko")  # nothing matches
        self.assertIn('class="empty"', none)  # the page says why it is empty


    def test_the_script_whose_title_names_the_question_wins(self):
        """Among the scripts the map found, a question script before a deep dive, then the one whose title shares the
        question's words; the closing part takes the script titled for your own questions."""
        scenes = {"O8": ({"role": "scenes", "tko": "본론으로 넘어갈 때"}, [], []), "A1": ({"role": "scenes", "tko": "1분 자기소개"}, [], []),
                  "Z15": ({"role": "deep", "tko": "서버 운영"}, [], []), "K6": ({"role": "scenes", "tko": "역질문: 합류하면 무엇에 집중할지"}, [], [])}
        row = {"text": "Tell me about yourself.", "ask": {"ko": ["자기소개 부탁드립니다."]}, "covered_by": [["Z15", .9], ["O8", .8], ["A1", .7]]}
        self.assertEqual("A1", deck.best(row, scenes))  # not the deep dive the map ranked first, nor the opening it ranked second
        self.assertEqual("K6", deck.closing_scene(scenes))  # your questions at the end
        self.assertIsNone(deck.best({"covered_by": []}, scenes))  # no script yet

    def test_a_kit_can_ask_for_its_own_order(self):
        """"deck": {"order": "file"} prints every question script once, in the file's order, under its heading."""
        self.job.kit["deck"] = {"order": "file"}  # as kit.json would set it
        text = deck.page(self.job, lang="ko")  # the deck
        ids = re.findall(r'<section class="scene" data-id="([^"]+)"', text)  # printed, in order
        want = [sid for sid, (it, _, _) in deck.scenes_of(self.job).items() if it.get("role") == "scenes"]  # every question script, in file order
        self.assertEqual(want, ids)  # all of them, each once, as written
        self.assertNotIn('<div class="part"></div>', text)  # each under its file heading

    def test_breath_marks_stay_inline_on_the_last_page(self):
        """The use under each line is a block; the breath marks inside the line are not."""
        self.assertIn(".stall div > span { display: block", self.html)  # only the use label
        self.assertNotIn(".stall span { display: block", self.html)  # never the faint slash


    def test_named_files_lead_and_the_map_follows(self):
        """"deck": {"order": "file", "files": [...]} prints the named file's scripts first, in its order, then the kit's
        other scripts as the map ranks them, each once."""
        scenes = deck.scenes_of(self.job)  # every script
        first = next(iter(scenes.values()))[0]["path"]  # the file of the first script
        name = __import__("pathlib").Path(str(first)).name  # its name, as kit.json would give it
        self.job.kit["deck"] = {"order": "file", "files": [name]}  # that file leads
        text = deck.page(self.job, lang="ko")
        ids = re.findall(r'<section class="scene" data-id="([^"]+)"', text)  # printed, in order
        own = [sid for sid, (it, _, _) in scenes.items() if it.get("role") == "scenes" and __import__("pathlib").Path(str(it["path"])).name == name]
        self.assertEqual(own, ids[:len(own)])  # the named file's scripts first, as written
        self.assertEqual(len(ids), len(set(ids)))  # none twice

    def test_inside_the_panel_the_pages_stand_on_its_desk(self):
        """Inside the Offerowl panel the deck draws no grey desk and no bar of its own (the panel names it and has the key
        that prints it); on its own, as printed, it keeps both."""
        inside = deck.page(self.job, lang="ko", embedded=True)
        self.assertIn('<html lang="ko" class="embedded">', inside)  # the page knows where it is shown
        self.assertIn("html.embedded { background: transparent; }", inside)  # the panel's desk behind the pages
        self.assertIn("html.embedded .bar { display: none; }", inside)  # no title and print key twice
        alone = deck.page(self.job, lang="ko")
        self.assertIn('<html lang="ko">', alone)  # on its own: the plain page
        self.assertIn('<div class="bar">', alone)  # with its print key
        self.assertEqual(inside.count('<section class="scene"'), alone.count('<section class="scene"'))  # the same scripts either way


if __name__ == "__main__":  # the file can also run on its own
    unittest.main()
