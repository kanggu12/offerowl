"""Job ids in ASCII and a kit carried from one application to another (0.15.0).

A job's id names it in every address (the panel's ?job=, /kit/<job>/), so a new one is ASCII: the Latin name written beside a
Korean one, else the Korean romanized. A workspace from before names jobs in Hangul: renamed once at the start, with the old
names kept as aliases and the undo steps following. A kit carried into another application keeps that application's own ids,
leaves behind the scenes about the earlier interview and, for a Korean interview, turns English scenes round.

    python3 -m unittest tests/app/test_job_ids_and_carry.py -v
"""
import json  # the files on disk
import pathlib  # paths
import shutil  # clean up
import sys  # the import path
import tempfile  # a workspace per test
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
for p in (ROOT, ROOT / "src"):  # apps/ and the interview package
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from apps.api.workspace import Workspace, romanize, slug  # noqa: E402
from interview import carry as C  # noqa: E402
from interview import check  # noqa: E402
from interview.job import Job  # noqa: E402


def write(path, data):
    """A file with its folders: JSON for a dict or a list, else text."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) if isinstance(data, (dict, list)) else data, encoding="utf-8")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-ids-"))  # never the repository
        self.addCleanup(shutil.rmtree, self.root, True)


class SlugTest(unittest.TestCase):
    def test_a_new_job_id_is_ascii(self):
        """The Latin name beside a Korean one wins, a legal form goes, Hangul is romanized, and nothing else changes."""
        self.assertEqual("gammasys", slug("주식회사 감마시스(gammasys)"))  # the name the company writes in Latin itself
        self.assertEqual("gammakeulraudeu", slug("감마클라우드"))  # romanized, syllable by syllable
        self.assertEqual("delta-pay", slug("Delta Pay"))  # Latin as before
        self.assertEqual("job", slug(""))  # never empty
        self.assertEqual("geulrobeol-tim", slug("(주) 글로벌 팀"))  # the legal form is no part of the name
        self.assertTrue(slug("가" * 40).isascii())
        self.assertLessEqual(len(slug("가" * 40)), 32)
        self.assertEqual("hangeul abc", romanize("한글 abc"))  # every other character as it is


class RenameTest(Tmp):
    def make_job(self, ws, jid, company):
        write(ws.root / "jobs" / jid / "status.json", {"id": jid, "company": company, "stage": "preparing"})
        write(ws.root / "jobs" / jid / "posting.md", "공고")

    def test_rename_moves_the_folder_and_everything_that_names_it(self):
        """The folder, the record's id, the kit's output, the job in view, the undo steps and an alias for the old id."""
        ws = Workspace(self.root / "ws")
        self.make_job(ws, "감마클라우드", "감마클라우드")
        write(ws.root / "out" / "interview" / "감마클라우드" / "map.json", {"q": 1})  # the kit's output
        ws.set_prefs(job="감마클라우드")
        write(ws.root / ".history" / "000001.json", {"t": 1.0, "label": {"code": "undo_board"}, "coalesce": None,
                                                    "files": {"jobs/감마클라우드/status.json": '{\n "id": "감마클라우드"\n}'}, "made": {}})
        self.assertEqual("gamma", ws.rename_job("감마클라우드", "gamma"))
        self.assertTrue((ws.root / "jobs" / "gamma" / "posting.md").is_file())
        self.assertFalse((ws.root / "jobs" / "감마클라우드").exists())
        self.assertEqual("gamma", ws.job("gamma")["id"])
        self.assertTrue((ws.root / "out" / "interview" / "gamma" / "map.json").is_file())
        self.assertEqual("gamma", ws.prefs()["job"])
        self.assertEqual("gamma", ws.resolve_job("감마클라우드"))  # an old address still finds it
        step = json.loads((ws.root / ".history" / "000001.json").read_text(encoding="utf-8"))
        self.assertEqual(['jobs/gamma/status.json'], list(step["files"]))  # an undo writes where the job lives now
        self.assertIn('"id": "gamma"', step["files"]["jobs/gamma/status.json"])

    def test_rename_refuses_what_it_must(self):
        """A taken id, a non-ASCII one, and a job made an edition (or the other way) are refused, and nothing moves."""
        ws = Workspace(self.root / "ws")
        self.make_job(ws, "alpha", "Alpha")
        self.make_job(ws, "beta", "Beta")
        for bad in ("beta", "감마", "Alpha", "-alpha", ""):
            with self.assertRaises(ValueError, msg=bad):
                ws.rename_job("alpha", bad)
        self.assertTrue((ws.root / "jobs" / "alpha").is_dir())

    def test_a_workspace_from_before_is_made_ascii_once(self):
        """Every Hangul job id gets an ASCII one at the start; an edition stays an edition; a second start moves nothing."""
        ws = Workspace(self.root / "ws")
        self.make_job(ws, "감마클라우드", "감마클라우드")
        self.make_job(ws, "델타", "델타페이(Delta Pay)")
        write(ws.root / "jobs" / "-최신-꼴" / "status.json", {"id": "-최신-꼴", "kind": "edition"})
        self.make_job(ws, "omega", "Omega")
        moved = ws.ascii_job_ids()
        self.assertEqual({"감마클라우드": "gammakeulraudeu", "델타": "delta-pay", "-최신-꼴": "-choesin-kkol"}, moved)
        self.assertTrue(all(p.name.isascii() for p in (ws.root / "jobs").iterdir()))
        self.assertEqual({}, ws.ascii_job_ids())  # once


SRC_QA = """# Gamma kit

## R. About me

### R1. Tell me about yourself / Tell me about yourself

**핵심** 소개

**면접관** Tell me about **yourself**.
**해석** 자기소개 부탁드립니다.
**나** I build **GPU clusters** / and run them.
**해석** 저는 GPU 클러스터를 만들고 운영합니다.

### R2. Why Gamma / Why Gamma?

**핵심** 이 회사

**면접관** Why Gamma Cloud?
**해석** 왜 감마클라우드인가요?
**나** Because Gamma Cloud runs GPUs.
**해석** 감마클라우드가 GPU를 운영하기 때문입니다.

## C. Short cues

- **Slurm**: two controllers
- **Ansible**: code only
- **Alerts**: trusted alerts
"""

DST_QA = """# Delta kit

## C. 회사

### C1. 델타에 대해 아는 것 / About Delta

**핵심** 회사

**면접관** 저희 회사에 대해 아세요?
**해석** What do you know about us?
**나** 네, 결제 회사로 알고 있습니다.
**해석** Yes, I know you as a payments company.

### R1. 자기소개 / Tell me about yourself

**핵심** 소개

**면접관** 자기소개 해 주세요.
**해석** Please introduce yourself.
**나** 저는 플랫폼 엔지니어입니다.
**해석** I'm a platform engineer.
"""


class CarryTest(Tmp):
    def kits(self):
        src = self.root / "jobs" / "gamma" / "interview"
        dst = self.root / "jobs" / "delta" / "interview"
        write(src / "qa.md", SRC_QA)
        write(src / "kit.json", {"company": {"ko": "감마클라우드", "en": "Gamma Cloud"}, "sources": [{"file": "qa.md", "role": "scenes"}]})
        write(src / "alts.json", {"R1": ["Introduce yourself"], "R2": ["Why us?"]})
        write(dst / "qa.md", DST_QA)
        write(dst / "kit.json", {"company": {"ko": "델타", "en": "Delta"}, "sources": [{"file": "qa.md", "role": "scenes"}]})
        return src, dst

    def test_a_kit_carried_keeps_the_targets_ids_and_leaves_the_old_interview_behind(self):
        """The scene about the earlier company stays behind; an id the target uses moves to the hundreds; a bullet list gets
        ids of its own; the target's own file and ids are untouched; kit.json names the carried file after its own."""
        src, dst = self.kits()
        report = C.carry(src, dst, korean=False)
        self.assertEqual(["Why Gamma / Why Gamma?"], report["left"])
        self.assertEqual({"R1": "R101"}, report["moved"])
        carried = (dst / "qa-carried.md").read_text(encoding="utf-8")
        self.assertIn("### R101. Tell me about yourself", carried)
        self.assertIn("### C101. Slurm", carried)  # never C1, the target's own
        self.assertEqual(DST_QA, (dst / "qa.md").read_text(encoding="utf-8"))  # the target's own file as it was
        kit = json.loads((dst / "kit.json").read_text(encoding="utf-8"))
        self.assertEqual(["qa.md", "qa-carried.md"], [s["file"] for s in kit["sources"]])
        self.assertEqual("gamma", kit["carried"][0]["from"])
        alts = json.loads((dst / "alts.json").read_text(encoding="utf-8"))
        self.assertEqual({"R101": ["Introduce yourself"]}, alts)  # under its new id, and nothing for the scene left behind
        ids = [it["id"] for it in __import__("interview.corpus", fromlist=["load"]).load(Job(dst.parent))[0]]
        self.assertEqual(len(ids), len(set(ids)))  # no id twice in the kit, so no "-2" ever renames the target's own

    def test_for_a_korean_interview_an_english_scene_is_turned_round(self):
        """The checked Korean goes on top, spoken; the English goes under it, plain; the kit reads as spoken in Korean."""
        src, dst = self.kits()
        C.carry(src, dst, korean=True)
        carried = (dst / "qa-carried.md").read_text(encoding="utf-8")
        self.assertIn("**나** 저는 GPU 클러스터를 만들고 운영합니다.\n**해석** I build GPU clusters and run them.", carried)
        self.assertNotIn("**", carried.split("**해석** I build")[1].split("\n")[0])  # no stress marks left in the English
        self.assertEqual("ko", check.speaks(Job(dst.parent)))
        _, _, bad = check.run(Job(dst.parent))  # the checker reads the turned scenes as Korean scenes
        self.assertEqual([], [(it["id"], p) for it, p in bad if it["id"] == "R101"])


if __name__ == "__main__":
    unittest.main()
