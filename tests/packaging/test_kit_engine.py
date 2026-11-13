"""The panel's own script view (apps/panel/static/kit.js) ranks and draws the scripts with the kit page's own engine: the lines
between "// >>> engine:NAME" and "// <<< engine:NAME" are the same in both files, byte for byte, so a question finds the same
card in the panel as on the kit's page (src/interview/page.html), and a script reads the same in both."""
import pathlib  # the two files
import re  # the marked blocks
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
PAGE = ROOT / "src" / "interview" / "page.html"  # the kit's own page, for `serve` and a saved copy
VIEW = ROOT / "apps" / "panel" / "static" / "kit.js"  # the panel's view of the same scripts
BLOCK = re.compile(r"^// >>> engine:(\w+)[^\n]*\n(.*?)^// <<< engine:\1\b[^\n]*$", re.M | re.S)  # a start line (a note may follow its name), the lines, the end line
NAMES = {"words", "rank", "script", "groups", "lines"}  # the tokenising and BM25, the fusion, the cards' markdown, the sections, the script lines


def blocks(text):
    """{name: the lines between its marks} of one file."""
    return {m.group(1): m.group(2) for m in BLOCK.finditer(text)}


class KitEngineTest(unittest.TestCase):
    def test_the_same_engine_in_the_panel_and_on_the_kit_s_page(self):
        """Every block of the engine is in both files, line for line."""
        page, view = blocks(PAGE.read_text(encoding="utf-8")), blocks(VIEW.read_text(encoding="utf-8"))
        self.assertEqual(NAMES, set(page))  # the page marks all of it
        self.assertEqual(NAMES, set(view))  # and the panel's view has all of it
        for name in sorted(NAMES):
            self.assertEqual(page[name], view[name], f"engine:{name} differs between page.html and kit.js")

    def test_each_mark_once(self):
        """A block marked twice, or a start without its end, would let a copy drift unnoticed."""
        for f in (PAGE, VIEW):
            text = f.read_text(encoding="utf-8")
            for name in NAMES:
                self.assertEqual(1, len(re.findall(rf"^// >>> engine:{name}\b", text, re.M)), f"{f.name}: {name}")
                self.assertEqual(1, len(re.findall(rf"^// <<< engine:{name}\b", text, re.M)), f"{f.name}: {name}")


if __name__ == "__main__":
    unittest.main()
