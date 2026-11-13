#!/usr/bin/env python3
"""The document checks of 0.10.0, with stand-ins for the pages: phrases fixed once (src/check_claims.py), the edition against
the profile and the shape kept (src/check_ledger.py), what the pages show (src/check_pages.py), the style pack's validator for
them, and the build handing the check its ledger and the edition's kind. Each rule passes what it should and fails a seeded
defect. Fictional people and words only.
  python3 -m unittest tests/app/test_document_rules.py -v
"""
import json  # packs, sidecars and ledgers
import pathlib  # paths
import sys  # the import path
import tempfile  # files of a test's own
import unittest  # the runner
import zipfile  # a Word file made by hand
from unittest import mock  # stand-ins

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src", ROOT / "tests" / "app", ROOT / "tests" / "render"):  # apps/, the engine, the helpers beside this file
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from test_blind import Person  # noqa: E402  a fictional person in a workspace of the test's own
from apps.api.routes import Router  # noqa: E402  the table the panel calls
import check_claims as CC  # noqa: E402  src/check_claims.py
import check_documents as CD  # noqa: E402  src/check_documents.py
import check_ledger as CLG  # noqa: E402  src/check_ledger.py
import check_pages as CP  # noqa: E402  src/check_pages.py
import pdftools as P  # noqa: E402  the PDF readers the checks call

codes = lambda found: [x.code for x in found]  # noqa: E731  what a check found, by code


class ClaimsTests(unittest.TestCase):
    """retired, shared and proposal on a document's words, and the rules held to the ledger they rest on."""

    PACK = {"claims": {
        "retired": {"ko": [["사내 배포 플랫폼 구축", "사내 배포 경로 정리", "the platform was the team's", "배포 경로를 하나로 모았다"]],
                    "en": [["Built the deploy platform", "", "the platform was the team's"]]},
        "shared": [["주문 이벤트", "Kafka 이벤트로 내보내", "one wording in every general edition"]],
        "proposal": {"ko": [["주문 재처리", "제안|설계안", "the reprocessing was proposed only"]]},
    }}

    def test_a_retired_phrase_is_named_with_what_to_write(self):
        bad = CC.check("알파페이에서 사내 배포 플랫폼 구축을 이끌었다.", self.PACK, "ko")
        self.assertEqual(["claim_retired"], codes(bad))
        self.assertEqual(("사내 배포 플랫폼 구축", "사내 배포 경로 정리"), (bad[0].values["old"], bad[0].values["new"]))  # the words and the fix
        self.assertEqual([], CC.check("알파페이에서 사내 배포 경로 정리를 이끌었다.", self.PACK, "ko"))  # the fixed words pass

    def test_each_language_reads_its_own_rules_and_both_read_a_shared_list(self):
        self.assertEqual(["claim_retired"], codes(CC.check("Built the deploy platform at Alpha Pay.", self.PACK, "en")))
        self.assertEqual([], CC.check("Built the deploy platform at Alpha Pay.", self.PACK, "ko"))  # a Korean edition is held to the Korean list
        bad = CC.check("Order events moved to a queue.", {"claims": {"retired": [["Order events", "", "both"]]}}, "en")
        self.assertEqual(["claim_retired"], codes(bad))  # a list for both languages

    def test_shared_phrases_hold_in_general_editions_only(self):
        text = "베타커머스에서 주문 이벤트를 큐로 옮겼다."  # the topic, without the phrase
        self.assertEqual(["claim_shared"], codes(CC.check(text, self.PACK, "ko", general=True)))
        self.assertEqual([], CC.check(text, self.PACK, "ko", general=False))  # an edition rewritten for one posting words it its own way
        self.assertEqual([], CC.check(text, self.PACK, "ko", general=True, blind=True))  # a blind edition's bars may cover the topic
        self.assertEqual([], CC.check(text + " 주문 상태를 Kafka 이벤트로 내보내 정산을 떼었다.", self.PACK, "ko", general=True))  # with the phrase

    def test_a_proposal_says_so_in_its_own_sentence(self):
        # the need in the same sentence passes, only in the next one fails
        rules = {"claims": {"proposal": {"ko": [["주문 재처리", "제안|설계|계획", "a test"]]}}}
        self.assertEqual([], CC.check("결제 승인의 주문 재처리를 설계안으로 제안했습니다. 다음 문장", rules, "ko"))
        self.assertEqual(["claim_proposal"], codes(CC.check("주문 재처리를 구현했습니다. 이어서 다른 설계를 했다", rules, "ko")))
        self.assertEqual([], CC.check("주문 재처리를 구현", rules, "en"))  # the other language's rules are not read
        lead = {"claims": {"proposal": {"ko": [["재처리를 배치가 맡", "제안", "a test"]]}}}
        old = "운영자가 손으로 다시 넣어야 하던 주문 재처리를 배치가 맡는 구조로 설계함. 설정 값으로 켜게 해"  # a rule's words in the middle of a long sentence
        self.assertEqual(["claim_proposal"], codes(CC.check(old, lead, "ko")))
        self.assertEqual([], CC.check(old.replace("설계함", "설계해 제안함"), lead, "ko"))

    def test_a_rule_whose_ledger_words_are_gone_is_stale(self):
        held = "알파페이: 팀마다 다르던 배포 경로를 **하나로** 모았다."  # the profile's words, reflowed and bolded
        self.assertEqual([], CC.check("", self.PACK, "ko", ledger=held))  # still there, spaces and marks aside
        bad = CC.check("", self.PACK, "ko", ledger="알파페이: 배포를 자동화했다.")
        self.assertEqual(["claim_anchor"], codes(bad))  # the facts moved: the rule is said to be stale
        self.assertEqual("배포 경로를 하나로 모았다", bad[0].values["words"])
        self.assertEqual([], CC.check("", self.PACK, "ko"))  # no ledger given: not read

    def test_a_table_the_checks_cannot_read_is_refused(self):
        self.assertEqual([], CC.problems(self.PACK["claims"]))
        for odd in ("x", {"retired": "x"}, {"retired": [["only one"]]}, {"shared": [["(unclosed", "p", "why"]]}, {"proposal": {"fr": []}},
                    {"retired": [["a", "b", "c", 3]]}, {"proposal": [["a", "(unclosed", "why"]]}):
            self.assertTrue(CC.problems(odd), odd)
        self.assertEqual([], CC.problems({"retired": [["a", "b(", "c"]]}))  # a replacement is words, not a pattern

    def test_the_words_come_from_the_word_file_or_the_page_beside_the_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = pathlib.Path(tmp) / "r.pdf"
            with zipfile.ZipFile(pdf.with_suffix(".docx"), "w") as z:  # a Word file with two paragraphs, one in two runs
                z.writestr("word/document.xml", '<w:document><w:body><w:p><w:r><w:t>사내 배포 </w:t></w:r><w:r><w:t>플랫폼 구축</w:t></w:r></w:p>'
                                                '<w:p><w:r><w:t>다음 &amp; 문단</w:t></w:r></w:p></w:body></w:document>')
            self.assertEqual("사내 배포 플랫폼 구축 다음 & 문단", CC.doc_text(str(pdf)))  # runs joined, entities read, one line
            deck = pathlib.Path(tmp) / "d.pdf"
            deck.with_suffix(".html").write_bytes("<html><style>.a{}</style><script>var x='old';</script><p>Order&nbsp;events</p></html>".encode("utf-8"))
            self.assertEqual("Order events", CC.doc_text(str(deck)))  # the page's words, never its code
            with mock.patch.object(P, "text", return_value="from the\nPDF"):
                self.assertEqual("from the PDF", CC.doc_text(str(pathlib.Path(tmp) / "none.pdf")))  # neither beside it: the PDF's text


class LedgerTests(unittest.TestCase):
    """The edition against the profile: periods, identifiers, lists, required words, core projects, items per company."""

    LEDGER = {"profiles": [{"roles": [{"org": "알파페이", "start": "2022.03", "end": None, "projects": [{"title": "결제 승인 서비스 재설계", "period": "23.01 ~ 23.09"}]},
                                      {"org": {"ko": "베타커머스", "en": "Beta Commerce"}, "start": "2019.07", "end": "2022.02"}],
                            "sections": [{"title": "등록 특허", "body_md": "| 제목 | 번호 |\n|---|---|\n| 주문 흐름 제어 장치 | KR123456789B1 |"},
                                         {"title": "논문", "body_md": "| A Queue-Based Order Event Pipeline for Payment Services | 2021 |"}]}]}

    def test_a_period_the_profile_does_not_have_is_named_once(self):
        text = "알파페이 2022.03 ~ 재직 중\n결제 승인 서비스 재설계 (2023.01 ~ 2023.09)\n베타커머스 2019.07 - 2022.02\n주문 (2020.03 ~ 2021.04) 다시 2020.03 ~ 2021.04"
        bad = CLG.period_issues(text, self.LEDGER)
        self.assertEqual(["ledger_period"], codes(bad))  # one unknown period, said once; YY.MM and YYYY.MM are one month
        self.assertEqual("2020.03 ~ 2021.04", bad[0].values["period"])
        spaced = "2 0 2 0.0 3 ~ 2 0 2 1 .0 4"  # a slide header's wide letter spacing splits the digits
        self.assertEqual(["ledger_period"], codes(CLG.period_issues(spaced, self.LEDGER)))  # read, not passed over
        self.assertEqual([], CLG.period_issues("2019.07 ~ 2022.02, 2023.01 - 2023.09", self.LEDGER))  # start and end fields, and a written period
        self.assertEqual([], CLG.period_issues("박사과정 2023.03 ~\n2019.03 ~ 2021.02 석사", {"profiles": [{"education": [{"start": "2019.03", "end": "2021.02"}]}]}))  # an open period, then the next row

    def test_identifiers_are_printed_as_the_profile_writes_them(self):
        rules = [{"printed": r"KR(\d{9})0000", "ledger": r"KR(\d{9})B1", "why": "a patent", "all": True}]
        words = CLG.ledger_text(self.LEDGER)
        self.assertEqual([], CLG.id_issues("등록번호 KR1234567890000", words, rules))  # the shared part matches
        self.assertEqual(["ledger_id", "ledger_id_missing"], codes(CLG.id_issues("등록번호 KR9999999990000", words, rules)))  # unknown, and the profile's own missing
        self.assertEqual(["ledger_id"], codes(CLG.id_issues("KR9999999990000 KR1234567890000", words, [dict(rules[0], all=False)])))

    def test_a_list_holds_the_profiles_own_entries_by_title(self):
        prof = {"sections": [{"title": "기타사항", "groups": [
            {"title": "논문", "rows": [["주저자", "A Queue-based Order Event Pipeline for Payment services", "2021"]]},
            {"title": "등록 특허", "rows": [["주문 흐름 제어 장치", "KR1234567890000"], ["가상의 다른 장치를 만든 방법", "KR0000000000000"]]}]}]}
        bad = CLG.list_issues(prof, CLG.ledger_text(self.LEDGER), ["논문", "등록 특허"], "ko")
        self.assertEqual(["ledger_entry"], codes(bad))  # the title in another case passes; an entry the profile lacks is named
        self.assertEqual("가상의 다른 장치를 만든 방법", bad[0].values["entry"])
        self.assertEqual([], CLG.list_issues(prof, "", [], "ko"))  # no list named: nothing read

    def test_required_words_and_core_projects_are_printed(self):
        rules = {"ko": ["정보처리기사", ["선임 엔지니어", "선임 개발자"]], "en": ["Engineer"]}
        self.assertEqual([], CLG.required_issues("정보 처리기사 … 선임개발자", rules, "ko"))  # spaces aside, any of the alternatives
        bad = CLG.required_issues("정보처리기사", rules, "ko")
        self.assertEqual(["required_missing"], codes(bad))
        self.assertEqual("선임 엔지니어", bad[0].values["words"])  # named by its first form
        self.assertEqual([], CLG.required_issues("a software engineer", rules, "en"))  # any case
        self.assertEqual(["core_missing"], codes(CLG.core_issues("알파페이 결제 승인", ["결제 승인 서비스 재설계"])))
        self.assertEqual([], CLG.core_issues("결제 승인 서비스 ■■■", ["결제 승인 서비스 재설계"], shown=lambda s: s.replace(" 재설계", "")))  # a blind edition's bars

    def test_a_company_keeps_its_items(self):
        prof = {"roles": [{"org": "알파페이", "projects": [{"title": "a"}, {"title": "b", "resume": False}, {"title": "c", "lang": "en"}]},
                          {"career": {"ko": {"name": "베타커머스"}}, "projects": [{"title": "d"}, {"title": "e"}]}]}
        bad = CLG.min_items_issues(prof, {"알파페이": 2, "베타커머스": 2}, "ko")
        self.assertEqual(["items_fewer"], codes(bad))  # a deck-only project and the other language's are not printed
        self.assertEqual((1, 2), (bad[0].values["n"], bad[0].values["min"]))
        self.assertEqual([], CLG.min_items_issues(prof, {"알파페이": 2}, "en"))  # the English edition prints a and c
        pack = {"ledger": {"min_items": {"알파페이": 5}}}  # more than the company prints
        self.assertIn("items_fewer", codes(CLG.check("", prof, {}, pack, "ko", general=True)))  # a general edition keeps its items
        self.assertNotIn("items_fewer", codes(CLG.check("", prof, {}, pack, "ko", general=False)))  # an application drops some on purpose

    def test_the_ledger_rules_wait_for_a_ledger(self):
        pack = {"ledger": {"periods": True, "ids": [{"printed": "X(\\d+)"}], "lists": ["논문"]}}
        self.assertEqual([], CLG.check("2020.03 ~ 2021.04 X12", {}, {}, pack, "ko", None))  # none given: not read
        self.assertEqual(["ledger_period", "ledger_id"], codes(CLG.check("2020.03 ~ 2021.04 X12", {}, {}, pack, "ko", self.LEDGER)))


class StructureTests(unittest.TestCase):
    """The shape kept: sections, figures, about me, job titles, the skills table."""

    ORDER = ["개요", "경력요약", "학력사항", "핵심역량", "보유기술", "상세경력사항", "기타사항", "자기소개", ["지원 동기", "커리어 목표"]]

    def test_sections_in_their_order(self):
        # the order holds, a moved section fails, the alternative title counts
        self.assertEqual([], CLG.section_issues(["개요", "경력요약", "학력사항", "핵심역량", "보유기술", "상세경력사항", "기타사항", "자기소개", "지원 동기"], {"ko": self.ORDER}, "ko"))
        moved = ["개요", "경력요약", "핵심역량", "보유기술", "학력사항", "상세경력사항", "기타사항", "자기소개", "지원 동기"]
        self.assertEqual(["section_order"], codes(CLG.section_issues(moved, {"ko": self.ORDER}, "ko")))
        self.assertEqual([], CLG.section_issues(self.ORDER[:-1] + ["커리어 목표"], {"ko": self.ORDER}, "ko"))  # a general edition's goal
        bad = CLG.section_issues(["개요", "경력요약"], {"ko": ["개요", "경력요약", "자기소개"]}, "ko")
        self.assertEqual(["section_missing"], codes(bad))
        self.assertEqual([], CLG.section_issues(["Overview"], {"ko": self.ORDER}, "en"))  # no English order kept: nothing read

    def test_figures_about_me_and_titles(self):
        figs = [{"name": "owl_ab12cd34_ko_timeline.png"}, {"name": "owl_ab12cd34_ko_stack.png"}]
        self.assertEqual([], CLG.figure_issues(figs, ["timeline", "stack"]))
        self.assertEqual(["figure_missing"], codes(CLG.figure_issues(figs[:1], ["timeline", "stack"])))  # the hierarchy figure lost
        self.assertEqual([], CLG.figure_issues([{"name": "x_timeline_en.png"}], ["timeline"]))  # the English edition's file
        self.assertEqual(["about_parts"], codes(CLG.about_issues(["a", "b", "c", "d"], 3)))
        self.assertEqual([], CLG.about_issues(["a", "b", "c"], 3))
        titles = ["Backend Engineer", "Software Engineer, 선임", "백엔드 개발"]
        self.assertEqual(["title_lead"], codes(CLG.title_issues(titles, "latin", False)))  # a lead in Hangul; a Korean rank after the comma is fine
        self.assertEqual(["title_mixed"], codes(CLG.title_issues(titles, "same", False)))
        self.assertEqual([], CLG.title_issues(titles[:2], "same", False))

    def test_a_title_says_its_rank_once(self):
        # an English rank with a Korean one, or one twice, is the rank said twice; two English ranks are two
        self.assertEqual(["title_rank"], codes(CLG.title_issues(["Project Lead, 플랫폼 운영 리드"], None, True)))
        self.assertEqual(["title_rank"], codes(CLG.title_issues(["Lead Engineer, Team Lead"], None, True)))
        self.assertEqual([], CLG.title_issues(["SRE Lead, Technical Project Owner", "Leader of nothing"], None, True))
        # a gloss in parentheses translates the rank before it; two different ranks are two positions the person held
        self.assertEqual([], CLG.title_issues(["팀장(Platform Lead), Release Owner", "Team Lead (Platform Lead), Release Owner"], None, True))
        self.assertEqual(["title_rank"], codes(CLG.title_issues(["팀장 Platform Lead"], None, True)))  # no parentheses: said twice
        self.assertEqual(["title_rank"], codes(CLG.title_issues(["Release Owner, 릴리스 책임자"], None, True)))  # restated in Korean

    def test_the_skills_table_holds_stacks_only(self):
        pats = ["Soft Skills", "Statistics", r"Experiment(?:ation|s)?\b", "A/B Test"]
        prof = {"skills": [{"category": "Soft Skills", "items": ["Mentoring"]}, {"category": "Statistics", "items": ["A/B Testing", "PCA"]},
                           {"category": "Platform", "items": ["Experimentation"]}, {"category": "Backend", "items": ["Go", "PostgreSQL", "Kafka"]},
                           {"category": "Notes", "items": ["Statistics"], "lang": "en"}]}
        bad = CLG.skills_issues(prof, pats, "ko")
        self.assertEqual(["Soft Skills", "Statistics", "A/B Testing", "Experimentation"], [x.values["what"] for x in bad])  # the English row is not printed here

    def test_a_shape_the_checks_cannot_read_is_refused(self):
        good = {"ledger": {"periods": True, "ids": [{"printed": "a(\\d)", "ledger": "b(\\d)", "why": "w", "all": True}], "lists": ["x"],
                           "required": {"ko": ["a", ["b", "c"]]}, "core": ["d"], "min_items": {"e": 2}},
                "structure": {"sections": ["a", ["b", "c"]], "figures": ["timeline"], "about_max": 3, "title_lead": "same", "title_ranks": True, "not_skills": ["x"]}}
        self.assertEqual([], CLG.problems(good))
        for key, odd in (("ledger", {"periods": "yes"}), ("ledger", {"ids": [{"printed": "(unclosed"}]}), ("ledger", {"ids": "x"}),
                         ("ledger", {"required": {"fr": []}}), ("ledger", {"min_items": {"e": "2"}}), ("ledger", {"lists": [1]}),
                         ("structure", {"title_lead": "roman"}), ("structure", {"about_max": -1}), ("structure", {"not_skills": ["(x"]}),
                         ("structure", {"sections": [1]}), ("ledger", [])):
            self.assertTrue(CLG.problems({key: odd}), (key, odd))


class PagesTests(unittest.TestCase):
    """What the pages show: an empty foot, an application's last page, the summary's page, the lines per company."""

    def test_the_footer_zone_is_not_the_bodys_end(self):
        # a bold footer must not make every page end at the footer
        from PIL import Image, ImageDraw  # a page drawn by hand
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "p.png"
            im = Image.new("L", (600, 842), 255)
            d = ImageDraw.Draw(im)
            d.rectangle((50, 100, 550, 110), fill=0)  # the body
            d.rectangle((50, 810, 550, 816), fill=0)  # the footer
            im.save(f)
            st = CP.page_stats(f)
        self.assertEqual(110, st["bottom"])
        self.assertEqual(round(100 * (842 - 110) / 842, 1), st["tail_gap"])

    def test_a_hole_in_the_middle_and_an_applications_last_page(self):
        page = lambda gap, lines=40: {"tail_gap": gap, "lines": lines, "pitch": 2.0}  # noqa: E731
        rules = {"mid_gap": 22, "fill_last": 12}
        self.assertEqual([], CP.page_issues([page(15), page(20), page(10)], rules, True))
        self.assertEqual(["page_gap"], codes(CP.page_issues([page(15), page(30), page(10)], rules, True)))
        self.assertEqual([], CP.page_issues([page(60, lines=8), page(10)], rules, True))  # a cover of few lines is empty by design
        bad = CP.page_issues([page(15), page(51.4)], rules, True)
        self.assertEqual(["last_page_room"], codes(bad))
        self.assertEqual(20, bad[0].values["lines"])  # (51.4 - 12) / 2.0, rounded up
        self.assertEqual([], CP.page_issues([page(15), page(51.4)], rules, False))  # a general edition is not held to it
        self.assertEqual([], CP.page_issues([page(15), page(51.4)], {}, True))  # nothing set: nothing read

    def test_the_summary_ends_on_page_1(self):
        sections = ["개요", "경력요약", "학력사항"]
        def run(p1, p2):
            pages = {1: p1, 2: p2}
            with mock.patch.object(P, "text", side_effect=lambda pdf, layout=False, first=None, last=None: pages[first]), \
                    mock.patch.object(P, "info", return_value={"pages": 2}):
                return codes(CP.summary_issues("x.pdf", ["경력요약"], sections))
        self.assertEqual([], run("개요\n경력요약\n2022.03 ~ 재직 중 알파페이\n학력사항\n", "핵심역량\n"))  # whole on page 1
        self.assertEqual([], run("개요\n경력요약\n2022.03 ~ 재직 중 알파페이\n", "학력사항\n2013.03 ~ 2019.02 가나대학교\n"))  # the next section begins page 2
        self.assertEqual(["summary_spills"], run("개요\n경력요약\n2022.03 ~ 재직 중 알파페이\n", "2017.07 ~ 2019.06 감마랩스\n학력사항\n"))  # a row ran on
        self.assertEqual(["summary_spills"], run("개요\n", "경력요약\n2022.03 ~ 재직 중\n학력사항\n"))  # the whole table moved

    LAYOUT = ("  상세경력사항\n"
              "    알파페이                                   서울   2022.03 ~ 재직 중 (4년 9개월)\n"
              "  • 결제 승인 서비스 재설계 (2023.01 ~ 2023.09): 승인 경로를\n    나눴다.\n"
              "  • 사내 배포 플랫폼 구축: 배포를 모았다.\n"
              "홍길동  Gildong Hong                                                     2 / 3\n"
              "    베타커머스                                 서울   2019.07 ~ 2022.02 (2년 8개월)\n"
              "  • 주문 이벤트 파이프라인 개발: 이벤트로 내보냈다.\n"
              "  기타사항\n  • 정보처리기사\n")
    PARTS = {"sections": ["경력요약", "상세경력사항", "기타사항"],
             "bands": [{"name": "알파페이", "right": "2022.03 ~ 재직 중 (4년 9개월)", "section": 1}, {"name": "베타커머스", "right": "2019.07 ~ 2022.02 (2년 8개월)", "section": 1}]}

    def test_the_lines_per_company_follow_its_tenure(self):
        self.assertEqual({0: 4, 1: 2}, CP.line_counts(self.LAYOUT, self.PARTS))  # band to band, the footer line aside, up to the next section
        import datetime  # an ongoing role runs to the day it is measured
        self.assertEqual(32, CP.months_of("2019.07 ~ 2022.02 (2년 8개월)"))  # both ends counted
        self.assertEqual(57, CP.months_of("2022.03 ~ 재직 중", datetime.date(2026, 11, 13)))
        names = {0: "A", 1: "B", 2: "C"}
        # a clearly shorter tenure with more lines fails; more than 1.6 times the median density fails
        self.assertEqual(["volume_order"], codes(CP.volume_issues({0: 14, 1: 12}, {0: 24, 1: 5 * 12}, names, 9.0)))  # two years with more lines than five
        self.assertEqual(["volume_density"], codes(CP.volume_issues({0: 60, 1: 20, 2: 20}, {0: 20, 1: 20, 2: 20}, names, 1.6)))
        self.assertEqual([], CP.volume_issues({0: 30, 1: 20, 2: 18}, {0: 30, 1: 20, 2: 18}, names, 1.6))
        self.assertEqual([], CP.volume_issues({0: 30}, {0: 3}, names, 1.6))  # one company is its own median

    def test_lines_that_cannot_be_counted_are_said(self):
        with self.assertRaises(CP.Unmeasured) as e:
            CP.line_counts(self.LAYOUT.replace("상세경력사항", "경험"), self.PARTS)  # the section's title is not on the pages
        self.assertEqual("volume_section", e.exception.args[0].code)
        twice = self.LAYOUT + "    알파페이                                   서울   2022.03 ~ 재직 중\n"
        with self.assertRaises(CP.Unmeasured) as e:
            CP.line_counts(twice.replace("  기타사항\n  • 정보처리기사\n", "") + "  기타사항\n", self.PARTS)
        self.assertEqual("volume_band", e.exception.args[0].code)  # found twice: a count would be a guess
        pack = {"pages": {"volume": 1.6}}
        with mock.patch.object(P, "text", return_value="nothing here"):
            self.assertEqual(["volume_section"], codes(CP.check("x.pdf", self.PARTS, pack, True)))  # said by the check, never passed

    def test_a_pages_object_the_checks_cannot_read_is_refused(self):
        self.assertEqual([], CP.problems({"pages": {"fill_last": 12, "mid_gap": 22.5, "summary_first": ["경력요약"], "bands": 0.75, "volume": 1.6}}))
        for odd in ({"fill_last": "12"}, {"mid_gap": 0}, {"bands": True}, {"summary_first": "경력요약"}, []):
            self.assertTrue(CP.problems({"pages": odd}), odd)


class WiredTests(Person):
    """The rules reach a build: the pack's validator, the ledger the build stages and takes away, the edition's kind."""

    FULL = {"claims": ClaimsTests.PACK["claims"],
            "ledger": {"periods": True, "ids": [{"printed": "KR(\\d{9})0000", "ledger": "KR(\\d{9})B1", "why": "a patent"}], "lists": ["논문"],
                       "required": {"ko": ["정보처리기사"]}, "core": ["결제 승인 서비스 재설계"], "min_items": {"알파페이": 2}},
            "structure": {"sections": {"ko": StructureTests.ORDER}, "figures": ["timeline"], "about_max": 3, "title_lead": "latin", "title_ranks": True,
                          "not_skills": ["Statistics"]},
            "pages": {"fill_last": 12, "mid_gap": 22, "summary_first": ["경력요약"], "bands": 0.75, "volume": 1.6}}

    def test_a_pack_with_every_new_object_is_kept_and_a_broken_one_refused(self):
        a = self.person()
        r = Router(a)
        status, out, _ = r.handle("POST", "/api/v1/style", {"state": "0"}, {"name": "rules", "pack": self.FULL})
        self.assertEqual(200, status, out)  # kept and chosen
        for odd in ({"claims": {"retired": [["(unclosed", "", "why"]]}}, {"ledger": {"ids": [{"printed": 3}]}},
                    {"structure": {"title_lead": "roman"}}, {"pages": {"fill_last": "most"}}, {"claims": []}):
            status, out, _ = r.handle("POST", "/api/v1/style", {"state": "0"}, {"name": "odd", "pack": odd})
            self.assertEqual((400, "style"), (status, out.get("what")), odd)  # refused here, never at a build

    def test_the_build_hands_the_check_its_ledger_and_takes_it_away(self):
        a = self.person()
        t = a.tasks
        import resume  # how the checks reach the container
        seen = []

        def sh(argv, *args, **kw):  # the check's command line, with the ledger read while it is there
            led = pathlib.Path(argv[argv.index("--ledger") + 1])
            seen.append((argv[argv.index("--edition") + 1], led, json.loads(led.read_bytes())))
            return mock.Mock(returncode=0, stdout="", stderr="")
        jid = a.add_job({"company": "감마클라우드", "posting": "Backend engineer. " * 20}, select=False)  # a fictional application
        for job in ("-general", jid):
            out_dir = t.build_dir(job, "ko")
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "profile.json").write_bytes(b"{}")
            with mock.patch.object(resume, "sh", side_effect=sh), mock.patch.object(resume, "rel", side_effect=lambda p: str(p)):
                t._check(str(out_dir / "profile.json"), out_dir / "owl_x_ko.pdf", None, 3)
        self.assertEqual(["general", "job"], [k for k, _, _ in seen])  # a general edition, then an application
        for _, led, data in seen:
            self.assertEqual(t.facts.profile()["person"]["name"], data["profiles"][0]["person"]["name"])  # the person's profile
            self.assertNotIn("schema", data)  # never staged as a profile with its pictures
            self.assertFalse(led.exists())  # and never left in the engine's folder

    def test_the_document_check_reads_its_new_switches(self):
        with mock.patch.object(CD, "check_resume", return_value=[]) as cr, mock.patch.object(CD, "check_deck", return_value=[]) as dk, \
                mock.patch.object(CLG, "read_ledger", return_value={"x": 1}), tempfile.TemporaryDirectory() as tmp:
            prof = pathlib.Path(tmp) / "p.json"
            prof.write_bytes(b"{}")
            argv = ["check_documents.py", str(prof), "r.pdf", "d.pdf", "--ledger", "l.json", "--edition", "general", "--style", "default"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):  # its verdict line is not this test's
                self.assertEqual(0, CD.main())
        self.assertEqual(({"x": 1}, True), cr.call_args[0][4:6])  # the ledger read, a general edition
        self.assertEqual(("d.pdf", "default", True), dk.call_args[0])  # the switches' values are never read as documents

    def test_the_resume_check_runs_the_new_rules(self):
        pack = {"claims": {"retired": [["사내 배포 플랫폼 구축", "", "why"]]}, "ledger": {"periods": True, "core": ["없는 과제"]}}
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "rules.json"
            f.write_bytes(json.dumps(pack, ensure_ascii=False).encode("utf-8"))
            text = "홍길동\n알파페이\n사내 배포 플랫폼 구축 (2020.01 ~ 2020.02)\n" + "결제 승인 서비스를 나눴다. " * 20
            with mock.patch.object(P, "text", return_value=text), mock.patch.object(CD.CR, "footer_clearance", return_value=[]), \
                    mock.patch.object(CD.CR, "number_unit_split", return_value=[]), mock.patch.object(CD, "last_fill", return_value=1.0):
                bad = CD.check_resume({"roles": [{"org": "알파페이", "projects": []}]}, str(pathlib.Path(tmp) / "x.pdf"), str(f), 3, ledger={"roles": []})
        self.assertEqual({"claim_retired", "ledger_period", "core_missing"}, {getattr(x, "code", "") for x in bad} - {""})


if __name__ == "__main__":
    unittest.main()
