"""The panel's stylesheets hold together: every comment is closed and every brace has its pair. An unclosed comment in
skin.css once swallowed the rules after it, silently (2026-11-09); a browser says nothing about it."""
import pathlib  # the files
import re  # comments
import unittest  # the runner

STATIC = pathlib.Path(__file__).resolve().parents[2] / "apps" / "panel" / "static"  # the panel's own files


class StylesheetsTest(unittest.TestCase):
    def test_comments_close_and_braces_pair(self):
        files = sorted(STATIC.glob("*.css"))  # tokens, components, app, skin
        self.assertTrue(files)  # there are stylesheets to look at
        for f in files:
            text = f.read_text(encoding="utf-8")
            pos, line = 0, 1
            while True:  # each comment, in order
                a = text.find("/*", pos)
                if a < 0:
                    break
                b = text.find("*/", a + 2)  # where it ends
                nxt = text.find("/*", a + 2)  # where the next begins
                self.assertTrue(b >= 0 and (nxt < 0 or nxt > b), f"{f.name}: a comment opened on line {text[:a].count(chr(10)) + 1} is not closed before the next")
                pos = b + 2
            bare = re.sub(r"/\*.*?\*/", "", text, flags=re.S)  # the rules without their comments
            bare = re.sub(r'"[^"]*"|\'[^\']*\'', "", bare)  # and without strings (an svg in a data address)
            self.assertEqual(bare.count("{"), bare.count("}"), f"{f.name}: braces do not pair")


if __name__ == "__main__":
    unittest.main()
