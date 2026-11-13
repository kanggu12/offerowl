"""What a drafted scene may stand on, and what the checks hold it to: the evidence reader, the expected questions, the
order of writing, and the rule between explaining how a tool works and saying what the person did."""
import json  # the profile and the outputs
import pathlib  # paths
import shutil  # clean up
import tempfile  # scratch folders
import unittest  # the test runner

import helpers  # the import path and the example
from interview import check, corpus, draft, plan  # the commands
from interview.evidence import Evidence, clean, pieces, role_head  # the reader


def workspace(profile, posting="# Job\n\n- Run the clusters\n", resume=None):
    """A small workspace of its own: a profile, a posting, an optional resume and an empty kit. Returns (tmp, job)."""
    from interview.job import Job  # the kit's job folder
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-ev-"))  # removed by the caller
    (tmp / "profile").mkdir()  # the workspace's profile folder
    (tmp / "profile" / "profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")  # the facts
    job = tmp / "jobs" / "acme"  # the job folder
    (job / "interview").mkdir(parents=True)  # an empty kit
    (job / "posting.md").write_text(posting, encoding="utf-8")  # the posting
    if resume:  # what was sent
        (job / "submitted").mkdir()  # the documents' folder
        (job / "submitted" / "resume.txt").write_text(resume, encoding="utf-8")  # as plain text
    return tmp, Job(job, workspace=tmp)  # the kit as the commands read it


def entry(text, kind="technical", ko=None):
    """A planned question in the map's shape."""
    return {"id": "k1", "kind": kind, "source": "anticipated.json", "text": text, "ask": {"en": [text], "ko": [ko or text]}, "coverage": "none", "covered_by": []}


def project(pid, title, body):
    """A project of the profile."""
    return {"id": pid, "title": title, "body_md": body}


LONG = "\n\n".join(f"긴 작업 기록 {i}번째 문단입니다. job 을 옮기고 job 을 살폈고 job 기록을 정리했습니다. " * 6 for i in range(12))  # a long project that says "job" a lot


class EvidenceTest(unittest.TestCase):
    def setUp(self):  # each test makes its own workspace
        self.tmp = None  # set by the test

    def tearDown(self):  # runs after each test
        if self.tmp:  # the workspace it made
            shutil.rmtree(self.tmp)  # removed

    def collect(self, prof, q, resume=None, kind="technical", stories=()):
        self.tmp, job = workspace(prof, resume=resume)  # the workspace
        return Evidence(job, list(stories)).collect(entry(q, kind))  # the real reader

    def test_a_rare_word_beats_a_common_one(self):
        """The project that says "Slurm" once comes before those that say "job" many times."""
        prof = {"roles": [{"key": "a", "org": "Acme", "projects": [project("a-1", "기록 정리", LONG), project("a-2", "기록 옮기기", LONG),
                                                                 project("a-3", "스케줄러 이중화", "Slurm 컨트롤러를 이중화했다.")]}]}
        text = self.collect(prof, "A Slurm job is stuck. How do you debug it?")  # the question
        self.assertIn("[profile a-3]", text.split("[profile a-1]")[0])  # first among the projects

    def test_long_projects_do_not_crowd_out_the_resume(self):
        """The one resume line that names the tool arrives, however long the projects are."""
        prof = {"roles": [{"key": "a", "org": "Acme", "projects": [project(f"a-{i}", f"기록 {i}", LONG) for i in range(1, 9)]}]}
        resume = "- Made the Slurm controller and the accounting database redundant at a national lab\n- Other work on the job records of the team\n"
        text = self.collect(prof, "A Slurm job is stuck. How do you debug it?", resume=resume)  # the question
        self.assertIn("[resume] Made the Slurm controller", text)  # the line that answers it
        self.assertLess(text.index("[resume] Made the Slurm"), text.index("[profile a-"))  # before the long bodies
        self.assertLess(len(text), 21000)  # and the whole stays within its room

    def test_the_room_follows_the_kit(self):
        """A kit for a small local model can lower the room."""
        prof = {"roles": [{"key": "a", "org": "Acme", "projects": [project(f"a-{i}", f"job {i}", LONG) for i in range(1, 9)]}]}
        self.tmp, job = workspace(prof)  # the workspace
        wide = Evidence(job, []).collect(entry("job records"))  # the default room
        job.kit["evidence_chars"] = 4000  # a smaller one
        narrow = Evidence(job, []).collect(entry("job records"))  # read again
        self.assertLess(len(narrow), len(wide) / 2)  # far less text

    def test_confirmed_facts_and_skills_arrive(self):
        """What the person confirmed and the skills they list are evidence too."""
        prof = {"roles": [], "confirmed": [{"title": "Slurm 범위", "body_md": "Slurm 은 운영까지 해 봤다."}],
                "skills": [{"category": "Cluster", "items": ["Slurm", "xCAT"]}, {"category": "Web", "items": ["React"]}]}
        text = self.collect(prof, "How do you run Slurm?")  # the question
        self.assertIn("[confirmed] Slurm 범위", text)  # the confirmed fact
        self.assertIn("[skills] Cluster: Slurm, xCAT", text)  # the skill group that names it
        self.assertNotIn("React", text)  # not the group that does not

    def test_a_question_with_no_shared_word_still_has_something_real(self):
        """An English line against a Korean profile: the latest work and the person's own representative work."""
        prof = {"summary": {"intro": {"ko": "소개", "en": "I build things."}, "highlights": {"en": [{"title": "Big move", "where": "Acme 2024", "rows": [["RESULT", "Moved it"]]}]}},
                "roles": [{"key": "a", "org": "에이", "projects": [project("a-1", "이관", "서버를 옮겼다.")]}]}
        text = self.collect(prof, "Work with stakeholders across functions", kind="posting")  # no word in common
        self.assertIn("[profile a-1]", text)  # the latest work
        self.assertIn("[representative work] Big move", text)  # and the person's own choice

    def test_a_behavioral_question_sees_the_representative_work(self):
        """A question that names no topic has the person's own choice in view."""
        prof = {"summary": {"highlights": [{"title": "Platform team", "where": "Beta Commerce", "rows": [["ACTION", "Founded the team"]]}]}, "roles": []}
        text = self.collect(prof, "What's the work you're most proud of?", kind="behavioral")  # no topic
        self.assertIn("[representative work] Platform team (Beta Commerce). ACTION: Founded the team", text)  # the card, in one line

    def test_writer_comments_never_reach_the_model(self):
        """A note to the writer inside a project is not evidence."""
        self.assertEqual("보이는 글", clean("<!-- 2026 정정: 보이면 안 된다 -->\n보이는 글"))  # gone
        prof = {"roles": [{"key": "a", "org": "Acme", "projects": [project("a-1", "Slurm 일", "<!-- 비밀 메모 --> Slurm 을 옮겼다.")]}]}
        self.assertNotIn("비밀 메모", self.collect(prof, "Slurm"))  # gone from the prompt too

    def test_both_forms_of_a_role_give_where_and_when(self):
        """The ledger form keeps the period and the title in a career block."""
        self.assertEqual("Beta Commerce, Platform Lead (2019.07 - 2022.02)", role_head({"heading": "베타커머스", "career": {"start": "2019.07", "end": "2022.02", "title": "Platform Lead", "en": {"name": "Beta Commerce"}}}))
        self.assertEqual("알파페이, 백엔드 (2022.03)", role_head({"org": "알파페이", "title": "백엔드", "start": "2022.03", "end": None}))
        self.assertEqual("감마랩스 (17.07 ~ 19.06)", role_head({"heading": "감마랩스", "period": "17.07 ~ 19.06", "career": None}))

    def test_passages_are_cut_at_paragraphs_and_sentences(self):
        """No passage runs far past its size, and nothing is lost."""
        text = "\n\n".join("문장입니다. " * 60 for _ in range(3))  # three long paragraphs
        got = pieces(text, 300)  # cut
        self.assertTrue(all(len(p) < 320 for p in got))  # each short
        self.assertEqual(text.count("문장입니다"), sum(p.count("문장입니다") for p in got))  # nothing lost


class ClaimTest(unittest.TestCase):
    """Explaining how a tool works may name anything; saying what the person did may not."""

    def test_explanation_and_claim_are_told_apart(self):
        got = check.claim_sentences(["`sinfo -R` shows the drain reason. // I check the PDU first, / then the BMC.",
                                     "I built the Foo gateway. // We then ran `dmesg` on it. // My team moved it. // It took 7 weeks.",
                                     "At Acme, I check the racks. // In 2025 the node came back."], ["Acme"])  # the three lines
        self.assertEqual(["I built the Foo gateway.", "We then ran `dmesg` on it.", "My team moved it.", "It took 7 weeks.", "At Acme, I check the racks.", "In 2025 the node came back."], got)

    def test_denying_what_the_documents_show(self):
        own = {"slurm", "kubernetes"}  # the person's own words
        self.assertEqual(["Slurm"], check.denials(["I have **not** operated **Slurm** myself, / so this is general."], own))  # denied, and it is there
        self.assertEqual([], check.denials(["I haven't used **Scyld** yet, / but I know the idea."], own))  # truly not there
        self.assertEqual([], check.denials(["Slurm never starts a job without resources."], own))  # not about the person

    def test_what_is_hard_to_say_is_named(self):
        fine = "I check the **logs** first, / then `dmesg`. // After that / I look at the **switch**."  # easy
        self.assertEqual([], check.hard_to_say([fine]))  # nothing to say
        long_turn = " ".join(["word"] * 120)  # over a minute
        self.assertIn("answer 2 has 120 words", check.hard_to_say([fine, long_turn])[0])  # named
        self.assertEqual([], check.hard_to_say([long_turn]))  # the first answer may be a self-introduction
        many = "`a` `b` `c` `d` are the tools I would run on it to see what it is doing."  # a list of commands
        self.assertIn("names 4 commands", check.hard_to_say([many])[0])  # named
        self.assertIn("long command", check.hard_to_say(["I run `openssl s_client -connect host:6443 -showcerts` first and read it."])[0])  # nobody says that
        self.assertIn("are bold", check.hard_to_say(["**all** **of** **these** **words** are bold here"])[0])  # stress means nothing then

    def test_orgs_come_from_either_form_of_a_role(self):
        tmp, job = workspace({"roles": [{"heading": "감마랩스 (Gamma Labs)", "career": {"en": {"name": "Gamma Labs"}, "ko": {"name": "베타커머스(Beta Commerce)"}}}, {"org": "Acme Pay"}]})  # both forms
        self.addCleanup(shutil.rmtree, tmp)  # removed afterwards
        self.assertEqual({"Gamma Labs", "Beta Commerce", "Acme Pay"}, check.person_orgs(job))  # the Latin names


class DraftRulesTest(unittest.TestCase):
    def setUp(self):  # runs before each test
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-out-"))  # outputs never go into the repository
        self.addCleanup(shutil.rmtree, self.out)  # removed afterwards

    def plan_file(self, rows):
        """A question map of its own."""
        path = self.out / "plan.json"  # where draft reads it
        path.write_text(json.dumps({"job": "x", "questions": rows}), encoding="utf-8")  # the map
        return str(path)  # for the call

    @staticmethod
    def scene(me, title="How do you check a node?"):
        """A stand-in answer with one line of mine."""
        return {"title_ko": "노드 점검", "title_en": title, "key": "핵심", "caution": "",
                "lines": [["면접관", title], ["해석", "노드를 어떻게 점검하나요?"], ["나", me], ["해석", "노드를 점검합니다."]]}

    def test_a_technical_scene_may_explain_what_the_documents_never_name(self):
        """A term the materials lack passes in an explanation, and fails in a statement of what the person did."""
        job = helpers.example_job()  # the example
        rows = [entry("How do you check a node?")]  # one technical question
        says = {"good": "`kubectl describe node` shows the **NotReady** reason, / and I check the **kubelet** first.", "bad": "At **Alpha Pay** / I fixed **NotReady** nodes with **Zorblatt**."}

        def ask(prompt, e):  # first the good one
            return self.scene(says["good"])  # present tense, no company
        rc = draft.main(job, out=str(self.out), plan_file=self.plan_file(rows), ask=ask)  # draft it
        self.assertEqual(0, rc)  # no model trouble
        self.assertIn("kubectl describe node", (self.out / "drafts" / "drafts-1.md").read_text(encoding="utf-8"))  # kept

        def ask_bad(prompt, e):  # then one that says the person did it
            return self.scene(says["bad"])  # a name the materials do not hold, in a claim
        draft.main(job, out=str(self.out), ids="k1", plan_file=self.plan_file(rows), ask=ask_bad)  # draft it again
        self.assertIn("Zorblatt", (self.out / "drafts" / "drafts-2.rejected.md").read_text(encoding="utf-8"))  # rejected, with the name

    def test_a_scene_that_denies_the_persons_experience_is_written_again(self):
        """The first answer denies what the documents show; the second, told why, is kept."""
        job = helpers.example_job()  # the example; its profile names Kubernetes
        answers = ["I have **not** used **Kubernetes** myself, / so this is the general way.", "In general, / a **pod** stays pending / when no node fits it."]  # first and second
        calls = []  # what the stand-in was asked

        def ask(prompt, e):  # answers in turn
            calls.append(prompt)  # kept
            return self.scene(answers[len(calls) - 1])  # the next answer
        draft.main(job, out=str(self.out), plan_file=self.plan_file([entry("How do you debug a pod?")]), ask=ask)  # draft it
        self.assertEqual(2, len(calls))  # asked twice
        self.assertIn("Kubernetes", calls[1].split("Your last answer was rejected")[1])  # told why
        written = (self.out / "drafts" / "drafts-1.md").read_text(encoding="utf-8")  # what was kept
        self.assertIn("a **pod** stays pending", written)  # the second answer
        self.assertNotIn("have **not** used", written)  # not the first

    def test_the_likeliest_questions_come_first_and_a_second_run_goes_on(self):
        """With a cap, the first scenes are behavioral, and the next run takes the next questions."""
        job = helpers.example_job()  # the example
        rows = [dict(entry(f"Line {i}", "posting"), id=f"p{i}") for i in range(3)] + [dict(entry("What is X?", "term"), id="t1"), dict(entry("Tell me about yourself", "behavioral"), id="b1"),
                                                                                  dict(entry("A node fails", "scenario"), id="s1")]  # in the map's order
        asked = []  # the order of the calls

        def ask(prompt, e):  # records the order
            asked.append(e["id"])  # which question
            return self.scene("In general, / I check the **logs** first.")  # passes for any kind
        path = self.plan_file(rows)  # the map
        draft.main(job, out=str(self.out), plan_file=path, ask=ask, limit=2)  # two scenes
        self.assertEqual(["b1", "s1"], asked)  # the likeliest kinds
        asked.clear()  # the second run
        draft.main(job, out=str(self.out), plan_file=path, ask=ask, limit=2)  # two more
        self.assertEqual(["p0", "p1"], asked)  # goes on where the first stopped

    def test_several_at_a_time_keep_the_ids_and_the_order(self):
        """Side by side: the ids follow the map's order, whichever scene finishes first, and progress is told."""
        job = helpers.example_job()  # the example
        rows = [dict(entry(f"Question {i}"), id=f"k{i}") for i in range(1, 5)]  # four questions
        told = []  # the progress calls

        def ask(prompt, e):  # the same answer for each
            return self.scene(f"In general, / question **{e['id'][1:]}** / starts with the **logs**.", e["text"])  # says which
        draft.main(job, out=str(self.out), plan_file=self.plan_file(rows), ask=ask, jobs=3, progress=lambda d, n: told.append((d, n)))  # three at a time
        text = (self.out / "drafts" / "drafts-1.md").read_text(encoding="utf-8")  # the file
        self.assertLess(text.index("### T1."), text.index("### T4."))  # in the map's order
        self.assertIn("Question 1", text.split("### T2.")[0])  # the first id goes with the first question
        self.assertEqual((4, 4), told[-1])  # told as each one finished
        self.assertEqual(4, len(told))  # once each


class VerifyTest(unittest.TestCase):
    """A scene that passed its checks is read once against the evidence around what it says."""

    def setUp(self):  # runs before each test
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-out-"))  # outputs never go into the repository
        self.addCleanup(shutil.rmtree, self.out)  # removed afterwards
        (self.out / "plan.json").write_text(json.dumps({"job": "x", "questions": [entry("How do you check a node?")]}), encoding="utf-8")  # one question

    @staticmethod
    def scene(me):
        """A stand-in answer with one line of mine."""
        return {"title_ko": "노드 점검", "title_en": "How do you check a node?", "key": "핵심", "caution": "",
                "lines": [["면접관", "How do you check a node?"], ["해석", "노드를 어떻게 점검하나요?"], ["나", me], ["해석", "노드를 점검합니다."]]}

    def run_it(self, first, second, found):
        """One scene through the writer and the second reading. Returns (the writer's prompts, the reader's prompts, the file)."""
        job = helpers.example_job()  # the example
        written, read = [], []  # the calls

        def ask(prompt, e):  # the writer
            written.append(prompt)  # kept
            return self.scene(first if len(written) == 1 else second)  # first, then the correction

        def verify(prompt):  # the reader
            read.append(prompt)  # kept
            return {"problems": found}  # what it found
        draft.main(job, out=str(self.out), plan_file=str(self.out / "plan.json"), ask=ask, verify=verify)  # draft it
        return written, read, (self.out / "drafts" / "drafts-1.md").read_text(encoding="utf-8")

    def test_a_scene_told_wrongly_is_corrected(self):
        """What the reader finds goes back with what the evidence backs, and the corrected scene stands."""
        written, read, text = self.run_it("At **Alpha Pay** / I moved every team / to one **Argo CD** application pattern.", "At **Alpha Pay** / the team moved / to one **Argo CD** application pattern.",
                                          [{"quote": "I moved every team", "why": "the team did it", "fix": "say the team moved"}])
        self.assertEqual(2, len(written))  # written twice
        self.assertIn("the team did it", written[1])  # told why
        self.assertIn("## More evidence", written[1])  # with the wider evidence
        self.assertIn("I moved every team", read[0].replace("**", ""))  # the reader saw what the scene says, without its marks
        self.assertIn("the team moved", text)  # the correction stands

    def test_a_finding_whose_quote_is_not_there_changes_nothing(self):
        """A quote that is not in the scene is the reader's mistake."""
        written, _, text = self.run_it("I **check** the logs first.", "unused", [{"quote": "something it never said", "why": "x", "fix": "y"}])
        self.assertEqual(1, len(written))  # not written again
        self.assertIn("**check**", text)  # as first written

    def test_nothing_found_is_the_usual_case(self):
        """One writer call and one reader call."""
        written, read, _ = self.run_it("I **check** the logs first.", "unused", [])
        self.assertEqual((1, 1), (len(written), len(read)))  # no more

    def test_the_evidence_around_follows_what_the_scene_says(self):
        """A passage the question did not reach comes back when the scene talks about it."""
        tmp, job = workspace({"roles": [{"key": "a", "org": "Acme", "projects": [project("a-1", "복구 제안", "spare 장치로 복구하는 방식을 제안했다."), project("a-2", "다른 일", "서버를 옮겼다.")]}]})  # two projects
        self.addCleanup(shutil.rmtree, tmp)  # removed afterwards
        around = Evidence(job, []).around("I designed recovery with spare devices.")  # what the scene says
        self.assertIn("제안했다", around)  # the word that qualifies the claim
        self.assertNotIn("서버를 옮겼다", around)  # nothing else


class HardToSayTest(unittest.TestCase):
    def test_one_more_try_but_a_true_scene_is_not_thrown_away(self):
        """A scene hard to say aloud goes back once, and is kept either way."""
        out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-out-"))  # outputs never go into the repository
        self.addCleanup(shutil.rmtree, out)  # removed afterwards
        job = helpers.example_job()  # the example
        rows = [entry("How do you check a node?")]  # one technical question
        (out / "plan.json").write_text(json.dumps({"job": "x", "questions": rows}), encoding="utf-8")  # the map
        calls = []  # what the stand-in was asked

        def ask(prompt, e):  # always too many commands
            calls.append(prompt)  # kept
            me = "I run `a`, `b`, `c` and `d`, / and I read what they say."  # four commands
            return {"title_ko": "노드 점검", "title_en": "How do you check a node?", "key": "핵심", "caution": "",
                    "lines": [["면접관", "How do you check a node?"], ["해석", "노드를 어떻게 점검하나요?"], ["나", me], ["해석", "네 개를 실행해 읽습니다."]]}
        draft.main(job, out=str(out), plan_file=str(out / "plan.json"), ask=ask)  # draft it
        self.assertEqual(2, len(calls))  # one more try
        self.assertIn("names 4 commands", calls[1])  # told why
        self.assertTrue((out / "drafts" / "drafts-1.md").is_file())  # kept all the same
        self.assertFalse((out / "drafts" / "drafts-1.rejected.md").exists())  # not rejected for it


class KitTest(unittest.TestCase):
    def test_drafts_join_the_kit_and_stay_out_of_the_scene_checks(self):
        """A draft is in the search view's items at once, and a second run's ids go on after it."""
        tmp, job_path = helpers.copy_workspace()  # a copy that may be written to
        self.addCleanup(shutil.rmtree, tmp)  # removed afterwards
        from interview.job import Job  # the kit's job folder
        job = Job(job_path)  # the kit
        before = len(corpus.load(job)[0])  # its items before
        folder = job.out_dir() / "drafts"  # where draft.py writes
        folder.mkdir(parents=True)  # made here
        (folder / "drafts-1.md").write_text("# drafts\n\n## Q. 용어\n\n### Q77. 새 장면 / New scene\n\n**면접관** What is it?\n**해석** 뭔가요?\n**나** A thing.\n**해석** 그것입니다.\n", encoding="utf-8")  # a passing file
        (folder / "drafts-1.rejected.md").write_text("# rejected drafts\n\n### Q78. 나쁜 장면\n", encoding="utf-8")  # a rejected one
        items, _ = corpus.load(job)  # read again
        self.assertEqual(before + 1, len(items))  # only the passing file joined
        new = next(it for it in items if it["id"] == "Q77")  # the new scene
        self.assertTrue(new["draft"])  # says so
        self.assertFalse(next(it for it in items if it["id"] != "Q77").get("draft"))  # the others do not
        self.assertNotIn("Q77", [it["id"] for it, _, _ in check.load_scenes(job)[1]])  # the scene check leaves it alone
        self.assertEqual(78, draft.next_ids(items)["Q"])  # the next scene goes on after it


class AnticipateTest(unittest.TestCase):
    def setUp(self):  # runs before each test
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-iv-out-"))  # outputs never go into the repository
        self.addCleanup(shutil.rmtree, self.out)  # removed afterwards

    def test_one_call_per_job_and_only_good_questions(self):
        """The answer is kept, bad rows are dropped, a second call asks nothing, and the map holds them."""
        job = helpers.example_job()  # the example
        calls = []  # the stand-in's calls

        def ask(task, prompt, **kw):  # the stand-in model
            calls.append(prompt)  # kept
            return {"questions": [{"kind": "scenario", "en": "A node fails at night.", "ko": "밤에 노드가 죽습니다."}, {"kind": "technical", "en": "What is a pod?", "ko": "pod가 뭔가요?"},
                                  {"kind": "technical", "en": "What is a pod?", "ko": "또 pod?"}, {"kind": "joke", "en": "Why?", "ko": "왜?"}, {"kind": "scenario", "en": "No Korean"}]}
        self.assertEqual((2, ""), plan.anticipate(job, out=str(self.out), ask=ask))  # two good questions
        self.assertEqual((2, ""), plan.anticipate(job, out=str(self.out), ask=ask))  # the same two
        self.assertEqual(1, len(calls))  # one call only
        self.assertIn("Run the", calls[0][:4000] + "Run the")  # the request was made
        rows = plan.build(job, out=str(self.out))  # the map
        got = {r["id"]: r for r in rows if r["kind"] in ("scenario", "technical")}  # the new kinds
        self.assertEqual({"s1", "k1"}, set(got))  # both, with their own ids
        self.assertEqual("밤에 노드가 죽습니다.", got["s1"]["ask"]["ko"][0])  # with their Korean

    def test_no_model_leaves_the_map_as_it_was(self):
        """With no model there is nothing to keep and the reason is given."""
        job = helpers.example_job()  # the example
        n, why = plan.anticipate(job, out=str(self.out), backend="none")  # no model
        self.assertEqual(0, n)  # nothing
        self.assertTrue(why)  # and why
        self.assertFalse((self.out / plan.ANTICIPATED).exists())  # no file

    def test_the_persons_initials_are_not_a_term(self):
        """A deck prints the person's initials on every page; nobody asks what they stand for."""
        self.assertEqual({"GDH"}, plan.name_initials({"person": {"name": "홍 길 동 (Gil-Dong Hong)"}}))  # from the Latin part
        tmp, job = workspace({"person": {"name": "Hong Gil Dong"}, "roles": [], "skills": []}, resume="- Used HGD and TCP at work on the servers\n")  # a resume with both
        self.addCleanup(shutil.rmtree, tmp)  # removed afterwards
        from interview.job import read_text  # files
        terms = [t for t, _ in plan.own_terms(job, read_text(job.submitted("resume")), "")]  # the terms
        self.assertIn("TCP", terms)  # a real term
        self.assertNotIn("HGD", terms)  # not the initials

    def test_a_page_title_is_words_not_a_running_head(self):
        """A running head in capitals with spaced-out dates gives way to the first line that reads as words."""
        page = "01 ALPHA PROJECT 02 / 03 2 0 2 3.0 1 - 2 0 2 3.0 9\nMoving the scheduler to a pair of nodes\nRole Lead and more words on this page to pass the size rule for a page\f"
        self.assertEqual("Moving the scheduler to a pair of nodes", plan.portfolio_pages(page)[0][1])  # the words


if __name__ == "__main__":  # run directly
    unittest.main()
