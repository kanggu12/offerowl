"""User-facing strings in Korean and English (i18n.json).

The language comes from OFFEROWL_LANG (ko or en) when it is set, else from the job's kit.json ("ui"), else Korean:
the kit is written for Korean speakers who interview in English, so its notes and translations are Korean.
"""
import json  # the string table
import os  # OFFEROWL_LANG
import pathlib  # the table's path

TABLE = json.loads((pathlib.Path(__file__).with_name("i18n.json")).read_text(encoding="utf-8"))  # loaded once
LANGS = ("ko", "en")  # the languages the table holds
_lang = None  # set by use(); None means "not decided yet"


def use(kit_lang=None):  # called by each command once the job's kit is read
    """Decide the language once per run: OFFEROWL_LANG, then the kit's choice, then Korean."""
    global _lang  # the choice is kept for the whole run
    env = (os.environ.get("OFFEROWL_LANG") or "").strip().lower()  # the user's explicit choice wins
    pick = env if env in LANGS else (kit_lang if kit_lang in LANGS else "ko")  # unknown values fall back
    _lang = pick  # remembered for lang()
    return pick  # the caller gets the choice too


def lang():  # every message lookup goes through here
    """The language in use (Korean until use() decides)."""
    return _lang or use()  # decide on first use when no command called use()


def page(code=None):  # the search page takes all its strings at once
    """Every page string in a language, as one dict for the search page."""
    return TABLE[code or lang()]["page"]  # a page may ask for another language than the run's


def t(key, **kw):  # every command message
    """One command message with its {slots} filled; an unknown key prints as itself so nothing is lost."""
    s = TABLE[lang()]["cli"].get(key) or TABLE["en"]["cli"].get(key) or key  # English when a Korean string is missing
    try:
        return s.format(**kw)  # fill the slots
    except (KeyError, IndexError, ValueError):  # a slot the caller did not give: show the raw string
        return s  # better the bare template than a crash


def reason(code, **kw):  # the checker reports codes; this turns them into text
    """The text of a checker reason code, in the language in use."""
    s = TABLE[lang()].get("reasons", {}).get(code) or TABLE["en"].get("reasons", {}).get(code) or code  # fall back to the code
    try:
        return s.format(**kw)  # fill the slots (numbers, words)
    except (KeyError, IndexError, ValueError):  # missing slot: the raw string
        return s  # the template as it is
