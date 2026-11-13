"""Practice mode without a model or a speech model: the feedback rules, the sessions, the speech worker's protocol,
the server's practice routes, the cue cards and the phone layout's markup."""
import json  # API answers and session files
import os  # the speech worker setting
import pathlib  # paths
import shutil  # clean up
import stat  # the stand-in worker's mode
import tempfile  # scratch folders
import threading  # the server beside the test
import unittest  # the test runner
import unittest.mock  # pinned settings
import urllib.error  # refused requests
import urllib.request  # requests

import helpers  # the import path and the example
from interview import check, cue, i18n, practice, server, transcribe  # the parts under test
from interview import text as T  # synonyms


class RulesTest(unittest.TestCase):  # the rule-made feedback, one rule at a time
    def test_spoken_text_and_numbers(self):
        """Speech marks and stage notes are not words; number words compare as digits."""
        self.assertEqual(practice.spoken("(웃으며) I **split** it / into ==two parts== // and moved on."), "I split it into two parts and moved on.")
        self.assertEqual(practice.count_words("I **split** it / into two // parts."), 6)  # marks are not words
        self.assertEqual(practice.digits("it took four minutes and twenty five seconds"), "it took 4 minutes and 25 seconds")
        self.assertEqual(practice.digits("two hundred and twelve nodes"), "212 nodes")  # hundreds with "and"
        self.assertEqual(practice.digits("and then"), "and then")  # "and" alone is no number

    def test_turns_follow_the_interviewer(self):
        """Each interviewer line opens a turn with my lines and both translations."""
        dialogue = [("면접관", "Why?", 1), ("해석", "왜요?", 2), ("나", "Because / it ==failed==.", 3), ("해석", "실패해서요.", 4),
                    ("면접관", "Then?", 5), ("해석", "그래서요?", 6), ("나", "I fixed it.", 7), ("해석", "고쳤습니다.", 8)]
        tt = practice.turns(dialogue)  # two turns
        self.assertEqual([t["q"] for t in tt], ["Why?", "Then?"])  # the questions in order
        self.assertEqual(tt[0]["a"], "Because it failed.")  # my answer without marks
        self.assertEqual((tt[0]["q_ko"], tt[0]["a_ko"]), ("왜요?", "실패해서요."))  # each translation under its own line
        self.assertIn("==failed==", tt[0]["raw"])  # the marked text keeps the key phrase

    def test_fillers(self):
        """Fillers are whole words; "like" counts only between commas, "kind of" not after "what"."""
        pack = check.style_pack(helpers.example_job())  # the built-in list plus the example's pack
        got = dict(practice.fillers("Um, so, like, the deploy was, um, kind of slow. What kind of deploy? I like Helm, you know.", pack))
        self.assertEqual(got.get("um"), 2)  # both
        self.assertEqual(got.get("like"), 1)  # ", like," only, not "I like Helm"
        self.assertEqual(got.get("kind of"), 1)  # "kind of slow", not "What kind of deploy"
        self.assertEqual(got.get("you know"), 1)  # a phrase

    def test_departures(self):
        """A changed number, a number and a name found nowhere, and a claim stronger than the scene are all reported."""
        scene = "We cut the rollback from 30 minutes to about 4 minutes. The team moved every service to Argo CD."
        pool = check.Pool(helpers.example_job(), strict=False, checked_paths=set())  # the example's evidence
        got = practice.departures("I led the move and the rollback took five minutes at Zeta Corp, with 77 retries.", scene, scene, pool)
        kinds = {(d["kind"], d["said"]) for d in got}  # what was reported
        self.assertIn(("changed", "5 minute"), kinds)  # the scene says 4 minutes (spoken five became 5)
        self.assertIn(("number", "77"), kinds)  # in neither the scene nor the evidence
        self.assertIn(("name", "Zeta Corp"), kinds)  # neighbouring capitals are one name
        self.assertIn(("claim", "I led"), kinds)  # the scene gives the move to the team
        self.assertEqual(next(d["fact"] for d in got if d["kind"] == "claim"), "claim_team")  # and says so
        self.assertEqual(practice.departures("The team cut the rollback to about 4 minutes.", scene, scene, pool), [])  # the same facts: nothing

    def test_key_phrase_and_pauses(self):
        """The key phrase counts when most of its words were said; long pauses come from word times or levels."""
        syn = T.synonyms()  # the built-in groups
        raw = "So / ==approvals deploy and roll back on their own==."  # a turn's marked line
        self.assertTrue(practice.key_check(raw, "now approvals deploy and roll back by themselves", syn)["landed"])  # most words said
        self.assertFalse(practice.key_check(raw, "we split the service", syn)["landed"])  # missed
        self.assertIsNone(practice.key_check("No marks here.", "anything", syn))  # this turn has no key phrase
        words = [{"w": "So", "start": 0.0, "end": 0.3}, {"w": "we", "start": 3.5, "end": 3.7}, {"w": "split", "start": 3.8, "end": 4.1}]
        self.assertEqual(practice.long_pauses(words=words), [(0.3, 3.2)])  # the gap between word times
        self.assertEqual(practice.long_pauses(pauses=[[1.0, 1.2], [4.0, 2.6]]), [(4.0, 2.6)])  # only the long silence counts

    def test_typed_answers_have_no_speaking_rate(self):
        """Typing time is not speaking time: no words per minute and no pause measure for a typed answer."""
        job = helpers.example_job()  # the example
        fb = practice.feedback("A short typed answer.", None, "", None, check.style_pack(job), {}, seconds=30)  # typed
        self.assertIsNone(fb["length"]["wpm"])  # no rate
        self.assertFalse(fb["pauses"]["measured"])  # no pauses
        fb = practice.feedback("A short spoken answer here.", None, "", None, check.style_pack(job), {}, seconds=3, speech_seconds=2.5, pauses=[], spoken_answer=True)
        self.assertEqual(fb["length"]["wpm"], 120)  # five words in two and a half seconds
        self.assertTrue(fb["pauses"]["measured"])  # measured


class SessionTest(unittest.TestCase):  # the practice service with stand-ins for the model
    def setUp(self):  # a scratch output folder per test
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-pr-"))  # never the repository
        self.addCleanup(shutil.rmtree, self.out, True)  # removed afterwards
        self.calls = []  # the stand-in's calls

    def ask(self, task, prompt, system):  # the stand-in model
        """Phrases every question, and asks one follow-up with one real and one made-up departure."""
        self.calls.append(task)  # counted
        if task == "interview-practice-ask":  # the session's one phrasing call
            ids = [ln.split("\t")[0] for ln in prompt.splitlines() if ln.startswith("q")]  # the question ids sent
            return {i: f"So, question {i}, tell me more about it?" for i in ids}  # one wording each
        return {"followup": "How long did the rollback take?",  # the follow-up call
                "departures": [{"said": "about 9 minutes", "fact": "about **5**", "why": "the notes say 5"},  # quotes that are not in the texts
                               {"said": "I led it", "fact": "never said", "why": "made up"}]}

    def test_fixed_list_session(self):
        """Without an agent: the scene's own lines, the scene's follow-up, feedback, a saved summary and the history."""
        p = practice.Practice(helpers.example_job(), self.out, backend="none")  # no model
        self.assertEqual(p.setup()["agent"], "")  # the fixed list
        s = p.start(n=4, seed=3)  # four questions
        self.assertEqual((s["interviewer"], len(s["questions"])), ("fixed", 4))  # all from the scripts
        q = s["questions"][0]  # the first question
        self.assertEqual(q["ask"], q["fixed"])  # asked with the scene's own line
        self.assertNotEqual(p.scenes()[q["scene"]][0]["role"], "terms")  # a posting question is answered by a scene, not a term entry
        fb = p.answer(s["id"], q["qid"], text="Um, I did it in five minutes, you know.", typed=True, seconds=12)  # a typed answer
        self.assertEqual(fb["feedback"]["fillers"]["count"], 2)  # um and you know
        fu = p.followup(s["id"], q["qid"])  # the scene's own follow-up, no call
        self.assertEqual(fu["from"], "scene" if p.scenes()[q["scene"]][1][1:] else "")  # from the script when it has one
        end = p.end(s["id"], seconds=40)  # close it
        self.assertFalse(pathlib.Path(end["file"]).is_absolute())  # the page is told where in the job's output, never the PC's own path
        saved = json.loads((self.out / end["file"]).read_text(encoding="utf-8"))  # the file on this PC
        self.assertEqual((saved["summary"]["answers"], saved["seconds"]), (1, 40.0))  # one answer, the session clock
        self.assertEqual(p.store.list()[0]["id"], s["id"])  # the history lists it
        self.assertEqual(self.calls, [])  # no model was asked

    def test_agent_session(self):
        """With an agent: one call phrases the session, one call per follow-up; made-up quotes are dropped."""
        p = practice.Practice(helpers.example_job(), self.out, ask=self.ask)  # the stand-in model
        s = p.start(n=3, seed=1)  # three questions
        self.assertEqual(self.calls, ["interview-practice-ask"])  # one call for the whole session
        self.assertTrue(all(q["ask"].startswith("So, question") for q in s["questions"]))  # the agent's wording
        q = s["questions"][0]  # the first
        p.answer(s["id"], q["qid"], text="I led it and it took about 9 minutes.", typed=False, seconds=8, speech_seconds=7, pauses=[[2.0, 3.0]])
        fu = p.followup(s["id"], q["qid"])  # one more call
        self.assertEqual((fu["from"], fu["followup"]), ("agent", "How long did the rollback take?"))  # the agent asks
        self.assertEqual(fu["departures"], [])  # neither departure quotes the notes exactly, so neither is kept
        self.assertEqual(self.calls, ["interview-practice-ask", "interview-practice-followup"])  # two calls in all
        fb = p.answer(s["id"], q["qid"], turn=1, text="About five minutes.", typed=True)  # the follow-up's answer
        self.assertIsNone(fb["scene"]["turn"])  # an agent follow-up is not held to a turn of the scene

    def test_questions_asked_before_come_in_their_own_words(self):
        """A question an earlier round asked is asked again as it was written down, and the agent's phrasing leaves it so."""
        from interview.job import Job  # the copied job
        tmp, job_dir = helpers.copy_workspace()
        try:
            (job_dir / "status.json").write_text(json.dumps({"rounds": [{"id": "i1", "kind": "first", "at": "2026-11-10",
                                                                         "asked": "Tell me about yourself.\nHow do you roll back a bad deploy?"}]}), encoding="utf-8")
            p = practice.Practice(Job(job_dir), self.out, ask=self.ask)  # the stand-in agent phrases the session
            s = p.start(n=4, kinds=["asked"], seed=1)
            self.assertTrue(s["questions"])  # the example's scripts answer them
            for q in s["questions"]:
                self.assertEqual(q["kind"], "asked")
                self.assertIn(q["ask"], ("Tell me about yourself.", "How do you roll back a bad deploy?"))  # never the agent's wording
            self.assertIn("asked", p.setup()["default_kinds"])  # on by default
        finally:
            shutil.rmtree(tmp)

    def test_a_follow_up_in_another_language_falls_back(self):
        """The interview is in English: a follow-up the agent writes in Korean gives way to the scene's own."""
        korean = lambda task, prompt, system: ({"q1": "Tell me about it?"} if task == "interview-practice-ask" else  # noqa: E731  phrases in English
                                               {"followup": "그 일에서 가장 어려웠던 점은 무엇인가요?", "departures": []})  # asks in Korean
        p = practice.Practice(helpers.example_job(), self.out, ask=korean)  # the stand-in model
        s = p.start(n=1, seed=1)  # one question
        q = s["questions"][0]  # that question
        p.answer(s["id"], q["qid"], text="I split the service.", typed=True)  # an answer
        fu = p.followup(s["id"], q["qid"])  # the agent's follow-up is not English
        nxt = p.scenes()[q["scene"]][1][1]["q"] if len(p.scenes()[q["scene"]][1]) > 1 else ""  # the scene's own follow-up
        self.assertEqual((fu["followup"], fu["from"]), (nxt, "scene" if nxt else ""))  # it stands in
        self.assertIn("in English", practice.FOLLOW_SYSTEM)  # and the prompt asks for English in the first place

    def test_drafts_are_practised_marked_and_a_start_with_nothing_keeps_nothing(self):
        """A kit whose scripts are all the agent's drafts is practised, each question marked as a draft; a kit with no script
        at all starts nothing and keeps no empty session (each start added an empty row to the history)."""
        from interview.job import Job  # the copied job
        tmp, job_dir = helpers.copy_workspace()
        try:
            job = Job(job_dir)  # its output folder is where the agent's drafts go
            drafts = job.out_path() / "drafts"  # as draft.py writes them
            drafts.mkdir(parents=True)
            (drafts / "drafts-1.md").write_text((job_dir / "interview" / "qa.md").read_text(encoding="utf-8"), encoding="utf-8")   # the person's scenes, as if the agent had drafted them
            for name, head in (("qa.md", "# 문답\n"), ("deep.md", "# 이력상세\n"), ("terms.md", "# 용어\n")):   # no scene of the person's own left
                (job_dir / "interview" / name).write_text(head, encoding="utf-8")
            p = practice.Practice(Job(job_dir), self.out, backend="none")  # no model
            s = p.start(n=4, seed=1)
            self.assertTrue(s["questions"])  # practised, not refused
            self.assertTrue(all(q["draft"] for q in s["questions"]))  # and each says it comes from a draft
            self.assertTrue(s["id"])  # a real session, kept
            shutil.rmtree(drafts)  # now no script at all
            p = practice.Practice(Job(job_dir), self.out, backend="none")
            before = len(p.store.list())  # the sessions kept so far
            empty = p.start(n=4, seed=1)
            self.assertEqual((empty["id"], empty["questions"]), ("", []))  # nothing to practise with
            self.assertEqual(before, len(p.store.list()))  # and nothing kept for it
        finally:
            shutil.rmtree(tmp)

    def test_bad_ids_and_the_cap(self):
        """A session id of any other shape names no file, and only the newest KEEP sessions stay."""
        p = practice.Practice(helpers.example_job(), self.out, backend="none")  # no model
        for bad in ("../x", "20260101-000000-zzzz", "", None):  # path tricks and malformed ids
            with self.assertRaises(KeyError):
                p.store.load(bad)
        with unittest.mock.patch.object(practice, "KEEP", 2):  # a small cap
            ids = [p.start(n=1)["id"] for _ in range(3)]  # three sessions (ids carry the second, so they may share one)
        self.assertEqual(len(list((self.out / "practice").glob("*.json"))), 2)  # the oldest is gone
        self.assertIn(ids[-1] + ".json", [f.name for f in (self.out / "practice").glob("*.json")])  # the newest stays


class SpeechTest(unittest.TestCase):  # the optional speech model's protocol, with a stand-in worker
    def test_without_a_speech_model(self):
        """No faster-whisper: available() says so and transcribe() asks for a typed answer."""
        with unittest.mock.patch.dict(os.environ, {"OFFEROWL_STT_PYTHON": "/nonexistent/python"}), \
                unittest.mock.patch.dict(transcribe._state, {"ok": None, "why": ""}):  # a fresh check
            ok, why = transcribe.available()  # cannot run
            self.assertFalse(ok)
            self.assertEqual(transcribe.transcribe(b"x")["code"], "no_stt")  # the page's cue to ask for typing

    def test_worker_protocol(self):
        """The worker's one JSON line becomes the answer; the recording goes to it as a file."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-stt-"))  # the stand-in worker's folder
        self.addCleanup(shutil.rmtree, tmp, True)  # removed afterwards
        fake = tmp / "python"  # stands in for a Python with faster-whisper
        fake.write_text("#!/bin/sh\n[ \"$1\" = -c ] && exit 0\n"  # the import check passes
                        "echo noise\necho '{\"text\": \"um hello\", \"words\": [{\"w\": \"um\", \"start\": 0, \"end\": 0.2}], \"seconds\": 1.5, \"language\": \"en\"}'\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)  # runnable
        with unittest.mock.patch.dict(os.environ, {"OFFEROWL_STT_PYTHON": str(fake)}), \
                unittest.mock.patch.dict(transcribe._state, {"ok": None, "why": ""}):
            self.assertEqual(transcribe.available(), (True, "faster-whisper"))  # the import check
            got = transcribe.transcribe(b"\x1aE\xdf\xa3 fake webm", "audio/webm;codecs=opus")  # a recording
        self.assertEqual((got["text"], got["seconds"]), ("um hello", 1.5))  # the last line, parsed
        self.assertEqual(transcribe.suffix("audio/mp4"), ".mp4")  # Safari records MP4


class ServerPracticeTest(unittest.TestCase):  # the practice routes over real HTTP
    def setUp(self):  # a server for the example on a free port
        self.addCleanup(i18n.use)  # the language follows the environment again afterwards
        with unittest.mock.patch.dict(os.environ, {"OFFEROWL_LANG": "en"}):  # the English strings
            i18n.use("en")
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-srv-"))  # sessions go here
        self.addCleanup(shutil.rmtree, self.out, True)  # removed afterwards
        stt = lambda audio, mime: {"text": "I split the approval service.", "words": [], "seconds": 2.0, "language": "en"}  # noqa: E731  a stand-in speech model
        srv, _ = server.make_server(helpers.example_job(), port=0, out_dir=self.out, backend="none", stt=stt)  # no model
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()  # serve beside the test
        self.addCleanup(srv.server_close)  # close the socket last
        self.addCleanup(srv.shutdown)  # stop the loop first
        self.base = f"http://127.0.0.1:{srv.server_address[1]}"  # the base URL

    def call(self, path, body=None, origin=None, raw=None, ctype="application/json"):
        """(status, JSON or text) of a practice call."""
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)  # the body
        headers = {"Content-Type": ctype} if data is not None else {}  # its type
        if origin:  # a page's origin
            headers["Origin"] = origin
        req = urllib.request.Request(self.base + path, data=data, headers=headers)  # GET without a body, POST with one
        try:
            with urllib.request.urlopen(req, timeout=20) as r:  # a stuck server fails the test
                text = r.read().decode("utf-8")
                return r.status, json.loads(text) if r.headers.get("Content-Type", "").startswith("application/json") else text
        except urllib.error.HTTPError as e:  # error statuses
            return e.code, e.read().decode("utf-8", "replace")

    def test_an_unexpected_failure_is_a_word_on_the_page(self):
        # a full disk or a broken file: the page gets a code, never the error's text (it can name this PC's paths and user)
        from interview import practice  # the service the routes call
        boom = OSError(28, "No space left on device", "/home/someone/offerowl/practice/x.json")
        with unittest.mock.patch.object(practice.Practice, "start", side_effect=boom), \
                unittest.mock.patch("traceback.print_exc"):  # the details go to the server's own output, kept quiet here
            code, body = self.call("/api/practice/start", {"n": 1}, self.base)
        self.assertEqual(500, code)
        self.assertEqual({"error": "unexpected"}, json.loads(body))
        self.assertNotIn("someone", body)

    def test_routes(self):
        """setup, start, transcribe, answer, follow-up, end and history; foreign origins and bad bodies are refused."""
        own = self.base  # the page's own origin
        code, setup = self.call("/api/practice/setup")  # what is offered
        self.assertEqual((code, setup["agent"], setup["stt"]), (200, "", True))  # fixed list, the stand-in speech model
        code, s = self.call("/api/practice/start", {"n": 2, "seed": 2}, own)  # a session
        self.assertEqual((code, len(s["questions"])), (200, 2))
        code, tr = self.call("/api/practice/transcribe", raw=b"fake audio", ctype="audio/webm", origin=own)  # a recording
        self.assertEqual((code, tr["text"]), (200, "I split the approval service."))
        q = s["questions"][0]  # the first question
        code, fb = self.call("/api/practice/answer", {"sid": s["id"], "qid": q["qid"], "text": tr["text"], "typed": False,
                                                       "seconds": 4, "speech_seconds": 3.5, "pauses": [[1, 2.8]]}, own)  # its answer
        self.assertEqual((code, fb["feedback"]["pauses"]["count"]), (200, 1))  # the long pause
        code, fu = self.call("/api/practice/followup", {"sid": s["id"], "qid": q["qid"]}, own)  # the script's follow-up
        self.assertEqual(code, 200)
        code, end = self.call("/api/practice/end", {"sid": s["id"], "seconds": 30}, own)  # close it
        self.assertEqual((code, end["summary"]["answers"]), (200, 1))
        self.assertTrue((self.out / end["file"]).is_file())  # kept in the output folder
        self.assertNotIn(str(self.out), end["file"])  # and the page is told where in it, never the PC's own path
        code, hist = self.call("/api/practice/history")  # earlier sessions
        self.assertEqual(hist["sessions"][0]["id"], s["id"])
        self.assertEqual(self.call("/api/practice/start", {"n": 1}, "http://evil.example")[0], 403)  # another site cannot start one
        self.assertEqual(self.call("/api/practice/answer", raw=b"not json", origin=own)[0], 400)  # not JSON
        self.assertEqual(self.call("/api/practice/answer", {"sid": "../../etc", "qid": "q1"}, own)[0], 404)  # no such session
        self.assertEqual(self.call("/api/practice/transcribe", raw=b"", ctype="audio/webm", origin=own)[0], 413)  # no recording

    def test_a_null_origin_reads_nothing(self):
        """Origin "null" is a saved copy, or any web site's sandboxed frame: it learns that the server is up and nothing more."""
        def raw(path, method="GET", origin="null", body=None):  # (status, the CORS header, the body) as that origin gets them
            req = urllib.request.Request(self.base + path, data=body, method=method, headers={"Origin": origin, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status, r.headers.get("Access-Control-Allow-Origin"), r.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                return e.code, e.headers.get("Access-Control-Allow-Origin"), e.read().decode("utf-8", "replace")
        self.assertEqual(raw("/api/health"), (200, "null", '{"ok": true}'))  # up, and no counts, model or memory
        code, cors, page = raw("/")  # the kit's page with the person's scenes
        self.assertEqual((code, cors), (200, None))  # served, but no other origin may read it
        self.assertIsNone(raw("/api/practice/history")[1])  # nor the practice history
        self.assertEqual(raw("/api/practice/start", "OPTIONS")[0], 403)  # no preflight for a POST
        self.assertEqual(raw("/api/practice/start", "POST", body=b'{"n": 1}')[0], 403)  # nor the POST itself
        self.assertEqual(raw("/api/health", origin=self.base)[1], self.base)  # the server's own page is answered as before

    def test_page_and_cue_cards(self):
        """The page carries the practice key, its pane, the phone rule and the inlined script; /cue prints the scenes."""
        code, html = self.call("/")  # the page
        self.assertEqual(code, 200)
        for part in ('id="practiceBtn"', 'id="practicePane"', "@media (max-width: 720px)", "function openPractice()", 'location.hash === "#practice"'):
            self.assertIn(part, html)  # each part is there
        self.assertNotIn("/*__PRACTICE__*/", html)  # the script was inlined
        self.assertNotIn("{{", html)  # every string slot filled
        code, page = self.call("/cue?ids=A1,R1")  # two cards
        self.assertEqual((code, page.count('<article class="cue"')), (200, 2))
        self.assertIn('<mark class="hl">', page)  # the key phrase on the highlighter
        self.assertIn('class="tr"', page)  # the translation under my lines
        self.assertNotIn("==", page)  # no raw marks
        self.assertEqual(self.call("/cue?sec=Z")[1].count('<article class="cue"'), 0)  # no such section: no cards
        code, page = self.call("/deck?ids=A1&lang=ko")  # the interview deck, one script
        self.assertEqual((code, page.count('<section class="scene"')), (200, 1))
        self.assertIn("@page { size: 297mm 167.06mm", page)  # 16:9 pages
        self.assertEqual(self.call("/deck?n=x&lang=zz")[0], 200)  # odd values fall back, never an error


class CueTest(unittest.TestCase):  # the cue command
    def test_cue_file(self):
        """cue writes the cards of a section to the output folder."""
        out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-cue-"))  # never the repository
        self.addCleanup(shutil.rmtree, out, True)  # removed afterwards
        self.assertEqual(cue.main(helpers.example_job(), sections="A", out=str(out)), 0)  # section A
        html = (out / "cue_cards.html").read_text(encoding="utf-8")  # the page to print
        self.assertEqual(html.count('<article class="cue"'), 3)  # A1, A2, A3
        self.assertIn("@page { size: A4", html)  # printed on A4
        self.assertIn('<span class="br">/</span>', cue.line_html("one / two"))  # a breath shows as a faint slash
        self.assertEqual(cue.line_html("one // two"), "one<br>two")  # a sentence mark is a new line


if __name__ == "__main__":  # the file can also run on its own
    unittest.main()
