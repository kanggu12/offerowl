"""A script's 주의 note that names the writer's own records (the ledger "대장", the kits before "기존 키트", a rule's number
"rules 2-1") is left out of the cards whole; every other 주의 note, and a note under another label, stays (round 4, C4-08:
nine questions showed "기록은 대장에 없다" on a card). The engine's own blocks are run in node, as the kit's page and the
panel's view run them."""
import json  # the harness's data
import pathlib  # the files
import re  # the marked blocks
import shutil  # is node here
import subprocess  # node
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
BLOCK = re.compile(r"^// >>> engine:(\w+)[^\n]*\n(.*?)^// <<< engine:\1\b[^\n]*$", re.M | re.S)  # a marked block
SCENE = """**핵심** 숫자로 답한다

**면접관** How many nodes?
**해석** 노드가 몇 개였나요?
**나** About **forty** nodes.
**해석** 40개쯤입니다.

**주의** 숫자는 제출 이력서 그대로. 그 밖의 일화는 대장에 없다.
**주의** 기존 키트 W8과 같은 흐름으로 말한다.
**주의** (rules 2-1) 확인되지 않은 것은 말하지 않는다.
**주의** 처음 문장은 길게 이어 가지 않고
여기서 끊는다. 대장 3월 절 그대로.
**주의** 숫자를 부풀리지 않는다 (대장 12).
**꼬리 대비** 대장 역할을 물으면 팀 이야기로 답한다.
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class NoteRecordsTest(unittest.TestCase):
    def render(self, path):
        """The card's body for SCENE, rendered by one file's engine."""
        blocks = {m.group(1): m.group(2) for m in BLOCK.finditer(path.read_text(encoding="utf-8"))}  # the engine's blocks
        js = ("const DATA = {syn: []}, KIT = {}, STR = {labels: {}}, ITEMS = [];\n"
              "const esc = (s) => String(s).replace(/[&<>\"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;' }[c]));\n"
              "%s\n%s\nconsole.log(JSON.stringify(render(%s, false)));" % (blocks["script"], blocks["lines"], json.dumps(SCENE, ensure_ascii=False)))
        return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True, timeout=30).stdout)

    def test_a_note_on_the_writer_s_records_is_left_out(self):
        for path in (ROOT / "apps" / "panel" / "static" / "kit.js", ROOT / "src" / "interview" / "page.html"):  # the panel's view and the kit's own page
            html = self.render(path)
            text = re.sub(r"<[^>]+>", "", html)  # the words the card shows
            for gone in ("대장에 없다", "기존 키트", "rules 2-1", "여기서 끊는다"):  # each such note whole, a line that runs on under it too
                self.assertNotIn(gone, text, path.name)
            self.assertIn("숫자를 부풀리지 않는다", text, path.name)  # another 주의 note stays, its bracketed reference to the ledger taken out
            self.assertNotIn("대장 12", text, path.name)
            self.assertIn("팀 이야기로 답한다", text, path.name)  # and a note under another label
            self.assertIn("forty", text, path.name)  # the script itself


if __name__ == "__main__":
    unittest.main()
