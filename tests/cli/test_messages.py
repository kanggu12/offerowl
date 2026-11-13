"""Tests that every message a person can read exists in Korean and English: same keys, same {placeholders}, no blanks,
and no t("key") call anywhere that names a key the table does not have.

Run: python3 -m unittest discover -s tests/cli -v
"""
import ast  # find the keys the code asks for
import importlib.machinery  # load the launcher, a file without .py
import importlib.util  # build a module from that file
import pathlib  # paths
import re  # find {placeholders}
import sys  # module search path
import unittest  # the test framework

from support import LAUNCHER, SRC

sys.path.insert(0, str(SRC))
import check_documents  # noqa: E402  its messages
import check_render  # noqa: E402  its messages
import draft  # noqa: E402  its messages
import ingest  # noqa: E402  its messages
import llm  # noqa: E402  its messages
import ocr_selfcheck  # noqa: E402  its messages
import resume  # noqa: E402  its messages
import review  # noqa: E402  its messages


def load_launcher():
    """The launcher as a module (it has no .py suffix, so the loader is named by hand)"""
    loader = importlib.machinery.SourceFileLoader("offerowl_launcher", str(LAUNCHER))
    spec = importlib.util.spec_from_file_location("offerowl_launcher", str(LAUNCHER), loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


launcher = load_launcher()
# name -> (message table, the file whose t("...") calls use it)
TABLES = {
    "llm": (llm.MSG, SRC / "llm.py"),
    "resume": (resume.MSG, SRC / "resume.py"),
    "check_documents": (check_documents.MSG, SRC / "check_documents.py"),
    "check_render": (check_render.MSG, SRC / "check_render.py"),
    "draft": (draft.MSG, SRC / "draft.py"),
    "ingest": (ingest.MSG, SRC / "ingest.py"),
    "ocr_selfcheck": (ocr_selfcheck.MSG, SRC / "ocr_selfcheck.py"),
    "review": (review.MSG, SRC / "review.py"),
    "launcher": (launcher.MSG, LAUNCHER),
}


def placeholders(text: str) -> set:
    """The {names} in a message"""
    return set(re.findall(r"\{(\w+)\}", text))


def keys_asked_for(path: pathlib.Path) -> dict:
    """Which keys a file gives to t(...) calls, as {owner: keys}. A bare t(...) or issue(...) asks the file's own table (owner "self");
    resume.t(...) asks the table of the module named in front of the dot. Every plain-word string constant inside the
    first argument counts, so t("a" if x else "b") yields both. A constant that ends in an underscore is a prefix, as in
    t("cmd_" + name), and is skipped"""
    found: dict = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in ("t", "issue"):  # issue(): check_documents' t() that keeps the code too
            owner = "self"
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "t" and isinstance(node.func.value, ast.Name):
            owner = node.func.value.id
        else:
            continue
        for const in ast.walk(node.args[0]):
            if isinstance(const, ast.Constant) and isinstance(const.value, str) and re.fullmatch(r"[a-z][a-z0-9_]*[a-z0-9]", const.value):
                found.setdefault(owner, set()).add(const.value)
    return found


def keys_by_table() -> dict:
    """{table name: keys that some t() call asks it for}, over all three files"""
    used = {name: set() for name in TABLES}
    for name, (_, path) in TABLES.items():
        for owner, keys in keys_asked_for(path).items():
            used[name if owner == "self" else owner] |= keys
    return used


class CatalogTest(unittest.TestCase):
    def test_both_languages_have_the_same_keys(self):
        for name, (table, _) in TABLES.items():
            self.assertEqual(sorted(table["en"]), sorted(table["ko"]), name)

    def test_both_languages_use_the_same_placeholders(self):
        for name, (table, _) in TABLES.items():
            for key, text in table["en"].items():
                self.assertEqual(placeholders(text), placeholders(table["ko"][key]), f"{name}.{key}")

    def test_no_message_is_blank(self):
        for name, (table, _) in TABLES.items():
            for lang_name, messages in table.items():
                for key, text in messages.items():
                    self.assertTrue(text.strip(), f"{name}.{lang_name}.{key}")

    def test_korean_messages_hold_korean_and_english_ones_do_not(self):
        # Catches an entry pasted into the wrong language. Technical words such as flags and file names are fine in both.
        hangul = re.compile(r"[가-힣]")
        for name, (table, _) in TABLES.items():
            for key, text in table["en"].items():
                self.assertIsNone(hangul.search(text), f"{name}.en.{key} holds Hangul")
            for key, text in table["ko"].items():
                self.assertIsNotNone(hangul.search(text), f"{name}.ko.{key} holds no Hangul")

    def test_every_key_the_code_asks_for_exists(self):
        for name, keys in keys_by_table().items():
            self.assertEqual(keys - set(TABLES[name][0]["en"]), set(), f"{name}: t() asks for keys the table lacks")

    def test_computed_keys_exist(self):
        # t("cmd_" + name) and t(USAGE_KEYS[name]) cannot be found by reading the source, so check them here.
        for name in resume.COMMANDS:
            self.assertIn("cmd_" + name, resume.MSG["en"])
        for key in resume.USAGE_KEYS.values():
            self.assertIn(key, resume.MSG["en"])
        for name in list(launcher.COMPONENTS) + list(launcher.DATA_COMMANDS):  # both kinds are described in the launcher
            self.assertIn("cmd_" + name, launcher.MSG["en"])

    def test_every_message_is_used(self):
        # An unused entry is a message nobody can reach, and it would drift out of date unnoticed.
        computed = {"cmd_" + n for n in list(resume.COMMANDS) + list(launcher.COMPONENTS) + list(launcher.DATA_COMMANDS)} | set(resume.USAGE_KEYS.values())
        for name, keys in keys_by_table().items():
            unused = set(TABLES[name][0]["en"]) - keys - computed
            self.assertEqual(unused, set(), f"{name}: messages that no t() call uses")

    def test_the_language_switch_picks_the_right_text(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"OFFEROWL_LANG": "ko"}):
            self.assertEqual(llm.t("available"), llm.MSG["ko"]["available"])
        with mock.patch.dict(os.environ, {"OFFEROWL_LANG": "en"}):
            self.assertEqual(llm.t("available"), llm.MSG["en"]["available"])


if __name__ == "__main__":
    unittest.main()
