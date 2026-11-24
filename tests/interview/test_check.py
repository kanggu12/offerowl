"""The scene checker: the example passes, and each kind of defect planted in a copy is caught."""
import pathlib  # paths
import shutil  # clean up
import unittest  # the test runner

import helpers  # the import path and the example
from interview import check  # the checker
from interview.job import Job  # the copied job


def plant(job_dir, old, new, name="qa.md"):
    """Replace one exact piece of a scene file in a copy (it must be there exactly once)."""
    p = pathlib.Path(job_dir) / "interview" / name  # the scene file inside the copied job
    t = p.read_text(encoding="utf-8")  # its current text
    assert t.count(old) == 1, old  # a missing or repeated piece would plant nothing or too much, so stop and name it
    p.write_text(t.replace(old, new), encoding="utf-8")  # the copy now carries the defect


KOREAN_SCENE = """
### K3. 배포를 되돌릴 때 / Rolling back a release

**핵심** 되돌리기는 Git에서 한 번에

**면접관** 배포가 잘못되면 어떻게 되돌리시나요?
**해석** If a release goes wrong, how do you roll it back?
**나** Git에서 이전 버전으로 되돌리면 / ==배포 도구가 클러스터를 그 상태로 맞춥니다==.
**해석** I revert to the previous version in Git, and the deployment tool brings the cluster back to that state.
**면접관** 그 방식의 장점은요?
**해석** And what does that give you?
**나** (잠깐 쉬고) 이 방식은 되돌린 기록이 Git에 남고, TTFT(첫 토큰까지 시간)가 늘지 않습니다.
**해석** This way, every rollback stays on record in Git, and TTFT, the time to the first token, does not grow.
"""  # a scene for a Korean interview: spoken in Korean, its English under each line; "(잠깐 쉬고) 이" is "this", no particle


class CheckTest(unittest.TestCase):  # the checker on the clean example and on copies with planted defects
    def test_a_korean_scene_keeps_its_english_under_each_line(self):
        """A scene spoken in Korean passes with English under each line; Korean under a Korean line is reported, the particle
        rule reads its Korean lines, and an English scene still needs Korean under it."""
        tmp, job_dir = helpers.copy_workspace()  # a copy, so the example itself stays clean
        try:
            qa = pathlib.Path(job_dir) / "interview" / "qa.md"  # the scene file of the copy
            qa.write_text(qa.read_text(encoding="utf-8") + KOREAN_SCENE, encoding="utf-8")  # the Korean scene added at its end
            _, _, bad = check.run(Job(job_dir))  # the default checks
            self.assertNotIn("K3", {it["id"] for it, _ in bad})  # clean as written
            plant(job_dir, "**해석** I revert to the previous version in Git, and the deployment tool brings the cluster back to that state.",
                  "**해석** Git에서 이전 버전으로 되돌립니다.")  # Korean under a Korean line
            plant(job_dir, "**나** Git에서 이전 버전으로", "**나** Git 에서 이전 버전으로")  # a particle spaced after a Latin word in the Korean line
            plant(job_dir, "**해석** 저희에게 궁금한 점이 있으신가요?", "**해석** Do you have any questions?")  # K2, an English scene: English under it
            _, _, bad = check.run(Job(job_dir))  # read again with the plants
            got = {it["id"]: sorted(c for c, _ in p) for it, p in bad}  # sorted problem codes per scene id
            self.assertEqual(got["K3"], ["josa", "tr_en"])  # the line under it is not English, and the Korean line's particle is spaced
            self.assertIn("tr_ko", got["K2"])  # an English scene's line under it must still be Korean
        finally:
            shutil.rmtree(tmp)  # remove the copy even when an assertion fails

    def test_example_has_no_problems(self):
        """The fictional example passes the default checks."""
        items, scenes, bad = check.run(helpers.example_job())  # default checks on the untouched example
        self.assertEqual(len(scenes), 15)  # every scene is checked; the stories are not scenes
        self.assertEqual(bad, [])  # and none is flagged, so every finding below comes from a plant

    def test_strict_mode_finds_the_planted_number(self):
        """Strict grounding finds the rollback time that no material holds (R1 says about 5, the portfolio says 4)."""
        _, _, bad = check.run(helpers.example_job(), strict=True)  # strict mode also asks the materials for every number
        found = {it["id"]: [c for c, _ in p] for it, p in bad}  # problem codes per scene id
        self.assertEqual(found, {"R1": ["numbers"]})  # only R1's planted number is reported, with no false alarms

    def test_planted_defects(self):
        """Form, wording and grounding defects are each reported with their code."""
        tmp, job_dir = helpers.copy_workspace()  # a copy, so the example itself stays clean
        try:
            plant(job_dir, "**해석** 안녕하세요, 길동 님. 오늘 와 주셔서 감사합니다.\n", "")  # O1: a line without its 해석
            plant(job_dir, "My strength is that I **narrow down** a failure", "My strength is that I **narrow down a failure")  # A3: odd stress marks
            plant(job_dir, "I can hear you **clearly**.", "I can hear you **clearly** and robust.")  # O2: an AI-sounding word
            plant(job_dir, "I'd like to do that work / for **several stores** at once.",  # the A2 line that the pack's forbidden phrase is added to
                  "I'd like to do that work / for **several stores** at once, / all by myself.")  # A2: the pack's forbidden wording
            plant(job_dir, "Kafka 이벤트로 내보내 정산과", "Kafka 로 내보내 정산과")  # A1: a particle spaced after a Latin word
            plant(job_dir, "**나** Yes, / two questions.", "**나** Yes, / two questions — maybe.")  # K2: a banned character
            job = Job(job_dir)  # read the copy with every defect in it
            _, _, bad = check.run(job)  # the default checks, not strict
            got = {it["id"]: sorted(c for c, _ in p) for it, p in bad}  # sorted problem codes per scene id
            self.assertEqual(got["O1"], ["no_tr"])  # the dropped 해석 line is O1's only problem
            self.assertEqual(got["A3"], ["marks"])  # the unclosed stress mark is A3's only problem
            self.assertIn("banned", got["O2"])  # the AI-sounding word is caught by the banned list
            self.assertIn("forbidden", got["A2"])  # the style pack's forbidden wording is caught
            self.assertIn("josa", got["A1"])  # the spaced particle after a Latin word is caught
            self.assertIn("chars", got["K2"])  # the banned dash character is caught
        finally:
            shutil.rmtree(tmp)  # remove the copy even when an assertion fails

    def test_grow_against_a_base_copy(self):
        """With --base, a scene that got shorter is reported, and --grow asks for more length (openings excepted)."""
        tmp, job_dir = helpers.copy_workspace()  # a copy to shorten
        try:
            base = pathlib.Path(tmp) / "base"  # where the unchanged scene files are kept
            shutil.copytree(job_dir / "interview", base)  # the earlier copy
            plant(job_dir, " // I'd like to bring that work / to your **payment platform**.", "")  # A1 loses a sentence
            job = Job(job_dir)  # read the shortened copy
            _, _, bad = check.run(job, base=str(base))  # compare each scene with its earlier length
            got = {it["id"]: [c for c, _ in p] for it, p in bad}  # problem codes per scene id
            self.assertEqual(got, {"A1": ["shorter"]})  # only the shortened scene is reported
            _, _, bad = check.run(job, base=str(base), grow=1.5)  # now every scene must reach one and a half times its earlier length
            got = {it["id"]: [c for c, _ in p] for it, p in bad}  # problem codes per scene id for that run
            self.assertIn("grow", got["R1"])  # not longer than before
            self.assertNotIn("O1", got)  # openings keep their length (grow_skip)
        finally:
            shutil.rmtree(tmp)  # remove the copy

    def test_a_rewrite_may_not_bring_in_a_new_number(self):
        """Against --base, a number that the earlier files never held is reported."""
        tmp, job_dir = helpers.copy_workspace()  # a copy to rewrite
        try:
            base = pathlib.Path(tmp) / "base"  # where the earlier files are kept
            shutil.copytree(job_dir / "interview", base)  # copied before the rewrite
            plant(job_dir, "**exponential backoff** and a **cap**.\n- **해석**: 승인 기능이",  # an R1 line in deep.md, found with the 해석 after it
                  "**exponential backoff** and a **cap** of 7.\n- **해석**: 승인 기능이", name="deep.md")  # the same text with a cap of 7, a number no earlier file holds
            _, _, bad = check.run(Job(job_dir), base=str(base))  # check the rewrite against the earlier files
            got = {it["id"]: [c for c, _ in p] for it, p in bad}  # problem codes per scene id
            self.assertEqual(got, {"R1": ["numbers"]})  # the new number is reported, and nothing else
        finally:
            shutil.rmtree(tmp)  # remove the copy

    def test_a_letter_two_sections_share_is_said_without_failing(self):
        """Two differently named sections under one letter (one taken over from another kit) are named in a note line,
        and the check still passes: the scenes are sound, only their keys look alike."""
        import contextlib  # the printed lines
        import io  # caught in memory
        self.assertEqual(check.letters_twice(helpers.example_job()), [])  # the example uses each letter once
        tmp, job_dir = helpers.copy_workspace()  # a copy to rename a section in
        try:
            plant(job_dir, "## U. 이력 상세: 베타커머스", "## R. 이력 상세: 베타커머스", name="deep.md")  # U's section now says R
            job = Job(job_dir)  # read the copy
            self.assertEqual(check.letters_twice(job), [("R", [("deep.md", "이력 상세: 알파페이"), ("deep.md", "이력 상세: 베타커머스")])])
            out = io.StringIO()  # what the command prints
            with contextlib.redirect_stdout(out):
                code = check.main(job)  # the whole kit, as `offerowl interview check` runs it
            self.assertEqual(code, 0)  # a shared letter alone does not fail the check
            self.assertIn("R", [ln for ln in out.getvalue().splitlines() if "베타커머스" in ln][0])  # the note names the letter
        finally:
            shutil.rmtree(tmp)  # remove the copy


if __name__ == "__main__":  # the file can also run on its own
    unittest.main()
