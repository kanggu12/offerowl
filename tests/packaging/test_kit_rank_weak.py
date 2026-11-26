"""The kit's ranking says "nothing is close" for a query no script holds (round 3, C3-01): with the similarity model off, a
Korean bigram of the query found in some script is no match. The engine's own blocks are run in node, with a small kit."""
import json  # the harness's data
import pathlib  # the files
import re  # the marked blocks
import shutil  # is node here
import subprocess  # node
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
VIEW = ROOT / "apps" / "panel" / "static" / "kit.js"  # the panel's view
BLOCK = re.compile(r"^// >>> engine:(\w+)[^\n]*\n(.*?)^// <<< engine:\1\b[^\n]*$", re.M | re.S)  # a marked block


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class RankWeakTest(unittest.TestCase):
    def run_rank(self, query):
        """rank(query).weak for a three-script kit, with no similarity model."""
        blocks = {m.group(1): m.group(2) for m in BLOCK.finditer(VIEW.read_text(encoding="utf-8"))}  # the engine's blocks
        items = [{"id": "A1", "tko": "자기소개", "ten": "Introduce yourself", "key": "한 줄 소개", "text": "저는 플랫폼 엔지니어입니다. 인프라를 운영했습니다.", "role": "scenes"},
                 {"id": "A2", "tko": "장애 대응", "ten": "Incident", "key": "알림 확인", "text": "장애가 나면 먼저 알림을 확인하고 원인을 찾습니다.", "role": "scenes"},
                 {"id": "A3", "tko": "배포", "ten": "Deploy", "key": "점진 배포", "text": "카나리로 점진 배포를 했습니다. 없는 것은 없습니다.", "role": "scenes"}]
        js = ("const DATA = {syn: []}, ITEMS = %s, ALTS = {}, dense = null;\nconst clamp = (x, a, b) => Math.max(a, Math.min(b, x));\n%s\n%s\n"
              "console.log(JSON.stringify(rank(%s).weak));" % (json.dumps(items, ensure_ascii=False), blocks["words"], blocks["rank"], json.dumps(query, ensure_ascii=False)))
        return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True, timeout=30).stdout)

    def test_a_query_no_script_holds_is_weak(self):
        self.assertTrue(self.run_rank("없는단어xyzqq"))  # its bigram "없는" is in a script, its words in none
        self.assertFalse(self.run_rank("자기소개"))  # a title's own word
        self.assertFalse(self.run_rank("장애 대응"))  # two words, both held


if __name__ == "__main__":
    unittest.main()
