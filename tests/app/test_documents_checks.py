#!/usr/bin/env python3
"""The Documents view's server side in 0.9.2: a submitted application's sentences, letter and deck refused from every key
that would change them; a save of the same words makes no undo step; a build that fails for any reason says why without a
path and leaves the edition as its PDF was made; the document checks' findings kept with their codes; the printed-word
rules and the line checks (src/check_documents.py, src/check_lines.py); a deck source's own checks on every build; a slot
left in an application answer; a finding's words as the sentence writes them. Fictional people and companies only.
  python3 -m unittest tests/app/test_documents_checks.py -v
"""
import json  # records and reports
import os  # the renderer for a deck tool run here
import pathlib  # paths
import subprocess  # a finished tool's output, stood in for
import sys  # the import path
import unittest  # the runner
from unittest import mock  # stand-ins

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src", ROOT / "tests" / "app", ROOT / "tests" / "render"):  # apps/, the engine, the helpers beside this file
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from test_blind import Builds, Person  # noqa: E402  a fictional person, and builds with the typesetting stood in for
from apps.api import answers as A  # noqa: E402  the application answers' checks
from apps.api import documents  # noqa: E402  the canvas's resume model
from apps.api.evidence import as_written  # noqa: E402  a finding's words as written
from apps.api.routes import Router  # noqa: E402  the table the panel calls
from apps.api.tasks import build_error  # noqa: E402  a failed typesetting's error
from apps.api.workspace import read_json  # noqa: E402  an edition's files
import check_documents as CD  # noqa: E402  src/check_documents.py
import check_lines as CL  # noqa: E402  src/check_lines.py
import resume  # noqa: E402  the typesetting steps

POSTING = "Backend platform engineer. Build payment services on Kubernetes, run Kafka pipelines, write runbooks, keep releases safe. " * 3


def lock(a, jid):
    """A job marked submitted and locked, as the lock records it."""
    st = a.ws.job(jid)
    st["locked"] = {"at": "2026-11-07", "folder": "sent", "files": {"resume.pdf": "0" * 64}, "lang": "ko"}
    a.ws.save_job(st)


class LockedApplicationTests(Person):
    """A submitted application's documents stay as they went: every key that would change them is refused by the server."""

    def test_every_write_to_a_locked_jobs_documents_is_refused(self):
        a = self.person()
        r = Router(a)
        jid = a.add_job({"company": "감마클라우드", "posting": POSTING}, select=False)  # a fictional job
        sid = next(iter(documents.resume(a.tasks, "ko", "navy", jid)["sentences"]))  # one of its sentences
        lock(a, jid)
        for path, body in (("/api/v1/sentences/edit", {"sid": sid, "text": "새 문장", "job": jid}),
                           ("/api/v1/sentences/lock", {"sid": sid, "locked": True, "job": jid}),
                           ("/api/v1/sentences/regenerate", {"sid": sid, "job": jid, "way": "shorter"}),
                           ("/api/v1/jobs/write", {"job": jid}), ("/api/v1/jobs/figures", {"job": jid}),
                           ("/api/v1/jobs/tailor", {"job": jid}), ("/api/v1/jobs/build", {"job": jid})):
            status, out, _ = r.handle("POST", path, {"state": "0"}, body)
            self.assertEqual((400, "locked"), (status, out.get("what")), (path, out))  # refused, with the rule's name

    def test_the_general_edition_still_takes_an_edit_and_the_same_words_make_no_step(self):
        a = self.person()
        r = Router(a)
        m = documents.resume(a.tasks, "ko", "navy", None)  # the general edition
        sid, rec = next((k, v) for k, v in m["sentences"].items() if v["state"] == "ok" and not k.startswith(("headline", "intro")))  # a fact's sentence
        before = a.ws.newest()[0]  # the newest undo step
        status, out, _ = r.handle("POST", "/api/v1/sentences/edit", {"state": "0"}, {"sid": sid, "text": rec["text"]})
        self.assertEqual(200, status, out)  # saved
        self.assertEqual(before, a.ws.newest()[0])  # nothing changed, so no step names a change
        status, out, _ = r.handle("POST", "/api/v1/sentences/edit", {"state": "0"}, {"sid": sid, "text": rec["text"].rstrip(".") + " XYZ로 옮겼다."})
        self.assertEqual(200, status, out)  # saved, outside the evidence
        self.assertNotEqual(before, a.ws.newest()[0])  # one step
        new = out["sentence"]
        self.assertEqual("unsupported", new["state"], new)  # a tool the evidence lacks
        self.assertIn("XYZ", " ".join(i.get("words", "") for i in new["issues"]))  # quoted as typed, never lower-cased
        self.assertEqual(1, documents.resume(a.tasks, "ko", "navy", None)["counts"]["edited"])  # counted as changed by the person, evidence or not


class StylePackTests(Person):
    """A pack's printed rules are checked when it is added: a pattern that does not compile is refused there, not at a build."""

    def test_printed_rules_are_checked_when_a_pack_is_added(self):
        a = self.person()
        r = Router(a)
        good = {"printed": {"comma_after_endings": True, "not_a_but_b": 0, "lines": "fail", "colloquial": ["도는 "], "highlight_names": ["Gasang Bank"],
                            "editing_notes": [["이직\\s*사유", "a reason for leaving"]]}}
        status, out, _ = r.handle("POST", "/api/v1/style", {"state": "0"}, {"name": "printed", "pack": good})
        self.assertEqual(200, status, out)  # kept
        for bad in ({"colloquial": ["(unclosed"]}, {"editing_notes": [["ok", "why", "extra"]]}, {"lines": "maybe"}, {"not_a_but_b": True}, {"highlight_names": [3]}):
            status, out, _ = r.handle("POST", "/api/v1/style", {"state": "0"}, {"name": "printed", "pack": {"printed": bad}})
            self.assertEqual((400, "style"), (status, out.get("what")), bad)  # refused, said as a rules file that cannot be used


class BuildFailureTests(Builds):
    """A build that fails says why without a path, cleans the engine's folder and leaves the edition's inputs as its PDF had them."""

    def test_any_error_while_typesetting_ends_the_build_and_puts_the_inputs_back(self):
        a = self.person()
        self.stand_in(a)
        a.tasks._build("-general", "ko", "navy", 3, False, False)  # a first edition, made
        out_dir = a.tasks.build_dir("-general", "ko")
        made = (out_dir / "profile.json").read_bytes(), (out_dir / "job.json").read_bytes()  # what its PDF was made from
        real = a.tasks._edition_profile

        def shortened(job_id, src, lang, out, compact=0, drop=0):  # the attempt writes another profile, as a page-fitting loop does
            real(job_id, src, lang, out, compact, drop)
            (out / "profile.json").write_text('{"shortened": true}', encoding="utf-8")
        with mock.patch.object(a.tasks, "_edition_profile", side_effect=shortened), \
             mock.patch.object(resume, "build", side_effect=OSError(28, "No space left on device", "/home/someone/secret/out.pdf")), \
             mock.patch.object(a.tasks, "_clean_engine", wraps=a.tasks._clean_engine) as clean, \
             self.assertLogs(level="ERROR") as logged:  # its trace goes to the log, and only there
            a.tasks._build("-general", "ko", "navy", 3, False, False)
        self.assertTrue(any("build -general failed" in x for x in logged.output), logged.output)
        task = a.tasks.state()["build:-general"]
        self.assertEqual("error", task["state"], task)
        self.assertEqual("build_failed", task["error"]["code"], task)
        self.assertNotIn("/home", json.dumps(task))  # never a path
        clean.assert_called_once()  # the engine's working copies went
        self.assertEqual(made, ((out_dir / "profile.json").read_bytes(), (out_dir / "job.json").read_bytes()))  # the inputs of the PDF on screen again

    def test_a_missing_english_text_is_named_from_nodes_own_line_however_long_its_stack(self):
        stack = "\n".join(f"    at step{i} (/very/long/path/to/the/repository/src/module_{i}.js:{i}:{i})" for i in range(60))  # a stack past the kept tail
        err = f"/work/src/resume_form.js:12\n  throw new Error(x);\n  ^\n\nError: summary.intro has no en text (translate it or write it in the profile)\n{stack}\n\nNode.js v22"
        text = resume.failed_output(subprocess.CompletedProcess([], 1, "", err))  # what resume.py raises with
        self.assertEqual("needs_translation", build_error(text, "en")["code"])  # the band that offers the translation
        self.assertIn("summary.intro has no en text", build_error(text, "en")["detail"])
        self.assertEqual("build_failed", build_error(text, "ko")["code"])  # a Korean edition has no English to miss
        self.assertNotIn("/very", build_error(text, "en")["detail"])  # paths out


class CheckReportTests(Builds):
    """The checks' findings are kept with their codes, for the panel to word in the person's language."""

    def test_a_report_is_read_once_with_its_codes(self):
        a = self.person()
        pdf = ROOT / "output" / "owl_test_report_ko.pdf"
        f = a.tasks.check_report(pdf)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"defects": [{"code": "too_long", "pages": 6, "limit": 3, "text": "6 pages, more than the limit of 3"}, "junk"],
                                 "polish": [{"code": "last_word", "tail": "분리", "end": "소비 쪽을 분리", "text": "…"}]}), encoding="utf-8")
        defects, polish = a.tasks.read_checks(pdf)
        self.assertEqual([{"code": "too_long", "pages": 6, "limit": 3, "text": "6 pages, more than the limit of 3"}], defects)  # well formed only
        self.assertEqual("last_word", polish[0]["code"])
        self.assertFalse(f.exists())  # read once
        self.assertEqual(([], []), a.tasks.read_checks(pdf))  # none left

    def test_a_finding_keeps_its_code_and_values(self):
        x = CD.issue("too_long", pages=6, limit=3)
        self.assertEqual(CD.t("too_long", pages=6, limit=3), x)  # a str to every caller
        self.assertEqual({"code": "too_long", "pages": 6, "limit": 3, "text": str(x)}, CD.report_item(x))
        self.assertEqual({"code": "", "text": "a line"}, CD.report_item("a line"))  # a line worded elsewhere


class PrintedRulesTests(unittest.TestCase):
    """What no printed document may hold, and the pack's own rules for printed words."""

    CLEAN = ("결제 서비스의 백엔드를 만들었다. 팀이 함께 쓰는 배포 플랫폼을 Kubernetes 위에 구축했다. 장애 대응 절차를 문서와 자동화로 옮겨 "
             "신규 입사자도 같은 기준으로 운영하게 했다. Node.js/Vue.js 로 만든 화면을 사용자를 대신해 실행하는 도구도 두었다.")
    STRICT = {"printed": {"comma_after_endings": True, "instead": True, "not_a_but_b": 0, "latin_and": True, "repeated_words": True,
                          "colloquial": ["(?:에서|으로|로|까지|이|가|게) 도는 "], "editing_notes": [["이직\\s*사유", "이직 사유"]]}}

    def codes(self, text, pack=None, lang="ko", paras=None):
        return [getattr(x, "code", "") for x in CD.printed_issues(text, pack or {}, lang, paras)]

    def test_a_clean_text_passes_every_rule(self):
        self.assertEqual([], self.codes(self.CLEAN))  # the default pack: nothing
        self.assertEqual([], self.codes(self.CLEAN, self.STRICT, paras=[self.CLEAN]))  # every switch on: Node.js is no file, 사용자를 대신해 no contrast

    def test_what_no_document_prints(self):
        self.assertIn("empty_value", self.codes("경력 undefined 년"))
        self.assertNotIn("empty_value", self.codes("an undefined segment of the cluster", lang="en"))  # an English adjective
        self.assertIn("empty_value", self.codes("Led the team. undefined. Shipped it.", lang="en"))
        self.assertIn("markup_left", self.codes("승인 경로를 ==따로 배포했다"))
        self.assertIn("markup_left", self.codes("**굵게** 남은 표시"))
        for note in ("(확인 필요) 날짜", "TODO: 숫자", "<!-- 메모 -->", "자료는 resume_v2.docx 참고"):
            self.assertIn("editing_note", self.codes(note), note)
        self.assertEqual([], self.codes("학습 중 NaN 손실을 잡았다"))  # a real NaN is a real thing to write

    def test_the_packs_rules_catch_what_they_name(self):
        seeded = {"comma_ending": "배포 경로를 만들고, 설정을 모았다.", "instead": "수동 점검 대신 자동화했다.", "not_a_but_b": "속도가 아니라 안정성이다.",
                  "latin_and": "Kafka 와 Redis 로 옮겼다.", "colloquial": "내부망에서 도는 서비스를 옮겼다.", "editing_note": "이직 사유: 성장"}
        for code, text in seeded.items():
            self.assertIn(code, self.codes(text, self.STRICT), code)  # caught
            self.assertNotIn(code, self.codes(text), code)  # and only when the pack asks (an editing note of the person's own list too)
        self.assertIn("repeated_word", self.codes("x", self.STRICT, paras=["배포 플랫폼을 만들고 사내 플랫폼을 넓혔다."]))
        self.assertNotIn("comma_ending", self.codes("주간 보고, 회의록을 썼다.", self.STRICT))  # 보고 is a noun
        self.assertIn("instead", self.codes("Instead of importing tools, we wrote them.", self.STRICT, lang="en"))

    def test_the_line_rules_come_from_the_pack(self):
        rules = CD.line_rules({"resume": {"highlight": {"ko": [10, 22]}}, "printed": {"lines": "fail", "highlight_names": ["KOTRA"]}}, "ko")
        self.assertEqual((10, 22), rules["hl_range"])
        self.assertFalse(rules["polish"])  # defects
        self.assertTrue(rules["names"].search("KOTRA 과제"))
        self.assertFalse(rules["names"].search("KOTRAX"))  # a longer word is not the name
        self.assertTrue(CD.line_rules({}, "ko")["polish"])  # notes to polish unless the pack says otherwise


def page(lines):
    """pdftotext -bbox-layout XML of one page: each line a list of (word, x0, x1) at its own height."""
    rows = []
    for i, words in enumerate(lines):
        y = 100 + i * 20  # one line under another
        rows.append("<line>" + "".join(f'<word xMin="{x0}" yMin="{y}" xMax="{x1}" yMax="{y + 10}">{w}</word>' for w, x0, x1 in words) + "</line>")
    return f'<html xmlns="http://www.w3.org/1999/xhtml"><body><doc><page width="595" height="842"><flow><block>{"".join(rows)}</block></flow></page></doc></body></html>'


class LineChecksTests(unittest.TestCase):
    """The line checks on a page's word boxes and the typesetting's sidecar."""

    def run_on(self, lines, data, **kw):
        bad, seen = CL.analyze(CL.words_from_xml(page(lines)), data, "ko", **kw)
        return [x.code for x in bad], seen

    def test_a_good_page_passes(self):
        lines = [[("승인", 10, 40), ("경로를", 45, 90), ("따로", 95, 120), ("배포하고", 125, 170), ("되돌린다", 175, 220)],
                 [("팀이", 10, 40), ("함께", 45, 70), ("쓰는", 75, 100), ("배포", 105, 130), ("플랫폼을", 135, 180), ("만들었다.", 185, 230)]]
        codes, seen = self.run_on(lines, {"highlights": ["승인 경로를 따로 배포하고"], "paras": ["승인 경로를 따로 배포하고 되돌린다", "팀이 함께 쓰는 배포 플랫폼을 만들었다."]})
        self.assertEqual([], codes)
        self.assertEqual({"highlights": 1, "found": 1, "paragraphs": 2, "measured": 2}, seen)  # measured, not passed over

    def test_seeded_defects_are_found(self):
        lines = [[("KOTRA와", 10, 50), ("함께", 55, 80), ("만든", 85, 110), ("수출", 115, 140), ("상담", 145, 170), ("창구를", 175, 210)],
                 [("열었고", 10, 40), ("대기를", 45, 80), ("줄였다", 85, 120)],
                 [("배포", 10, 40), ("경로를", 45, 80), ("하나로", 85, 120), ("묶어", 125, 150), ("팀이", 155, 180), ("함께", 185, 210)],
                 [("썼다.", 10, 40)]]
        data = {"highlights": ["창구를 열었고", "KOTRA와 함께 만든 수출 상담", "없는 강조"],   # broken, a name and too long for 6..12, missing
                "paras": ["KOTRA와 함께 만든 수출 상담 창구를 열었고 대기를 줄였다", "배포 경로를 하나로 묶어 팀이 함께 썼다."]}
        codes, seen = self.run_on(lines, data, hl_range=(6, 12), names=CL.name_pattern(["KOTRA"], []))
        for code in ("hl_broken", "hl_name", "hl_size", "hl_missing", "last_word"):
            self.assertIn(code, codes, codes)
        self.assertEqual(2, seen["found"])

    def test_a_cards_paragraph_read_row_by_row_is_followed_down_its_column(self):
        # two cards side by side whose rows line up: the text layer reads each card's first line, then the second card's
        # second line, and the first card's second line last, as pdftotext read the resume's cards once their labels
        # shared rows (0.9.2); the first card's paragraph is measured down its own column, not lost
        def line(words, y):  # one line of word boxes at height y
            return "<line>" + "".join(f'<word xMin="{x0}" yMin="{y}" xMax="{x1}" yMax="{y + 10}">{w}</word>' for w, x0, x1 in words) + "</line>"
        rows = [line([("정산과", 10, 40), ("알림이", 45, 75), ("주문", 80, 100), ("서비스를", 105, 140)], 100),   # card 1, line 1
                line([("승인", 210, 230), ("기능을", 235, 265), ("분리하고", 270, 305), ("멱등", 310, 330)], 100),  # card 2, line 1
                line([("키를", 210, 230), ("정했다", 235, 265)], 114),                                             # card 2, line 2
                line([("불렀다", 10, 40)], 114)]                                                                  # card 1, line 2, read last
        xml = f'<html xmlns="http://www.w3.org/1999/xhtml"><body><doc><page width="595" height="842"><flow><block>{"".join(rows)}</block></flow></page></doc></body></html>'
        data = {"highlights": [], "paras": ["정산과 알림이 주문 서비스를 불렀다", "승인 기능을 분리하고 멱등 키를 정했다"]}
        bad, seen = CL.analyze(CL.words_from_xml(xml), data, "ko")
        codes = [x.code for x in bad]
        self.assertEqual(2, seen["measured"], codes)  # both paragraphs measured
        self.assertNotIn("para_missing", codes)
        self.assertIn("last_word", codes)  # the first card ends on one word: found where it stands

    def test_no_sidecar_means_nothing_to_measure(self):
        self.assertEqual([], CL.check(str(ROOT / "output" / "no_such_resume.pdf")))


class DeckToolsTests(Builds):
    """A deck source's own checks run on every build's deck; their failures are the deck's issues."""

    def tools(self, a, body):
        """A staged deck source whose tools/check_deck.py runs `body`, and a deck PDF and page for it to read."""
        src = ROOT / "output" / "_inputs" / "test_deck_src"
        (src / "tools").mkdir(parents=True, exist_ok=True)
        (src / "tools" / "check_deck.py").write_text("import sys\n" + body, encoding="utf-8")
        self.addCleanup(lambda: __import__("shutil").rmtree(src, ignore_errors=True))
        deck = ROOT / "output" / "owl_test_tools_ko_deck.pdf"
        deck.write_bytes(b"%PDF-1.4\n")
        self.addCleanup(lambda: deck.unlink(missing_ok=True))
        return deck, src.relative_to(ROOT).as_posix()

    def run_tools(self, a, body):
        deck, src = self.tools(a, body)
        with mock.patch.dict(os.environ, {"OFFEROWL_RENDERER": "html"}):  # the tools run on this PC, as the browser renderer runs them
            return a.tasks._deck_tools(deck, src, dict(os.environ))

    def test_a_failing_tool_gives_its_lines_and_a_passing_one_nothing(self):
        a = self.person()
        got = self.run_tools(a, 'print("deck: 2 problems")\nprint("  - slide 3: a figure under 150 ppi")\nprint("  - slide 5: no figure")\nsys.exit(1)\n')
        self.assertEqual(["deck_tool", "deck_tool"], [x["code"] for x in got])
        self.assertEqual("slide 3: a figure under 150 ppi", got[0]["what"])
        self.assertEqual([], self.run_tools(a, 'print("deck: passed")\n'))

    def test_a_tool_that_breaks_says_it_did_not_run(self):
        a = self.person()
        got = self.run_tools(a, 'raise RuntimeError("no such file /home/someone/deck.html")\n')
        self.assertEqual(["deck_tool_failed"], [x["code"] for x in got])
        self.assertNotIn("/home", got[0]["what"])  # paths out


class AnswerSlotTests(unittest.TestCase):
    """A slot left in an application answer is said, and keeps the answers from being saved out."""

    def test_slots_are_found_and_plain_text_is_not(self):
        self.assertEqual(["placeholder:<link>"], A.placeholders("Portfolio (PDF): <link> Slide 7 shows the design."))
        self.assertEqual(["placeholder:[회사명]", "placeholder:○○"], A.placeholders("[회사명]에 지원합니다. ○○ 팀에서 일했습니다."))
        self.assertEqual([], A.placeholders("a < b and c > d, Python [3.11], I <3 code"))
        q = {"text": "Additional Information", "limit": 500, "unit": "chars", "answer": "See <link> for slides.", "issues": []}
        self.assertEqual(["placeholder:<link>"], A.with_placeholders(q))  # an answer checked before the check existed shows it too
        self.assertIn("placeholder:<link>", A.problems(q, q["answer"], [], {}, {}))


class WordsAsWrittenTests(unittest.TestCase):
    def test_a_finding_quotes_the_sentences_own_letters(self):
        got = as_written([{"code": "latin", "words": "xyz, def"}, {"code": "claim", "words": "led", "said": "helped"}], "Built XYZ with ==DeF==")
        self.assertEqual("XYZ, DeF", got[0]["words"])
        self.assertEqual("led", got[1]["words"])  # a claim's words are the check's own


if __name__ == "__main__":
    unittest.main()
