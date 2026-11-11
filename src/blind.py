# -*- coding: utf-8 -*-
"""The blind edition's table on the Python side. blind.js reads the same table for the documents; this module reads it for
the figures (overview_figures.py), the page-1 band (blind_banner.py), the document check, and the panel: the checks a
person's own table passes before it is kept, and the check of a blind edition's PDFs before they are exported.

The table is src/blind.json, or the file OFFEROWL_BLIND_TABLE names (the panel keeps a person's own table in the
workspace, stages it where the typesetting reads it and names it there). A person's table goes over src/blind.json key by
key, so a table with only "mask" keeps the band's words and colours. The mask lists hold regular expressions as JavaScript
reads them with no flags, which is how blind.js uses them, so \\w, \\d and \\b are ASCII here too (re.ASCII). The leak list
holds words as written (leak_found): "500+" is five hundred and more, never a pattern.

    python3 src/blind.py check <table.json>      the table's problems, one per line (exit 1 when there are any)
"""
import functools  # one compiled pattern set per table
import json  # the tables
import os  # the switches
import pathlib  # paths
import re  # the patterns
import sys  # the command line

ROOT = pathlib.Path(__file__).resolve().parent.parent  # the repository root, one level above src/
DEFAULT = ROOT / "src" / "blind.json"  # the shipped table: generic and empty, so it covers nothing
LISTS = ("mask", "mask_whole", "leak")  # the lists: two of patterns, then the words that must never show
MAX_PATTERNS = 500  # patterns in one list: a long career's names and figures run to a hundred or so
MAX_PATTERN = 300  # characters in one pattern
MAX_TABLE = 200_000  # characters of a whole table as JSON, the style pack's cap
MAX_WORDS = 60  # characters of a word the documents print (the footer label, the band's two parts, a contact's label)
COLOR = re.compile(r"[0-9A-Fa-f]{6}")  # a colour as the documents write it (no #): it goes into the Word file's XML and the deck's CSS
GROUPS = ("(?:", "(?=", "(?!", "(?<=", "(?<!")  # the only group forms that JavaScript and Python read alike
ESCAPES = set("aAZzUNG")  # letter escapes that Python reads as one thing and JavaScript as another (or not at all)


def on(env=None) -> bool:
    """Is this run making a blind edition (OFFEROWL_BLIND=1)? env: the environment the run was given, else this process's."""
    return (os.environ if env is None else env).get("OFFEROWL_BLIND") == "1"


def lang(env=None) -> str:
    """The edition's language for the band and the label (OFFEROWL_BLIND_LANG), Korean unless it says English."""
    return "en" if (os.environ if env is None else env).get("OFFEROWL_BLIND_LANG") == "en" else "ko"


def path(env=None) -> pathlib.Path:
    """The table this run reads: the file OFFEROWL_BLIND_TABLE names (relative to the repository, as the container sees it),
    else the shipped one."""
    named = (os.environ if env is None else env).get("OFFEROWL_BLIND_TABLE", "").strip()  # a person's own table, when one is named
    if not named:  # none: the shipped table
        return DEFAULT
    p = pathlib.Path(named)  # as given
    return p if p.is_absolute() else ROOT / p  # the staged copy is named relative to the repository


def merged(mine: dict) -> dict:
    """A person's table over the shipped one: what it leaves out keeps the shipped value, and the band's and the label's words
    are merged per language, so a table that sets only Korean keeps the English."""
    base = json.loads(DEFAULT.read_text(encoding="utf-8"))  # the shipped table
    out = {**base, **{k: v for k, v in (mine or {}).items() if v is not None}}  # theirs over it
    for k in ("footer", "banner"):  # per language
        out[k] = {**(base.get(k) or {}), **((mine or {}).get(k) or {})}
    return out


def load(env=None) -> dict:
    """The table this run reads, merged over the shipped one. A table that is named but cannot be read stops the run: a blind
    edition never falls back to a table that covers nothing."""
    p = path(env)  # which file
    try:
        mine = json.loads(p.read_text(encoding="utf-8"))  # its content
    except (OSError, ValueError) as exc:  # missing or broken
        raise SystemExit(f"blind table unreadable: {p.name}") from exc
    if not isinstance(mine, dict):  # a list or a number is not a table
        raise SystemExit(f"blind table unreadable: {p.name}")
    return merged(mine)


# ---------------------------------------------------------------- the checks a table passes before it is kept


def js_problem(p: str) -> str:
    """Why JavaScript would read a pattern otherwise than Python does ("" when both read it alike). It is a cheap scan, not a
    parser: it refuses the forms where the two differ (Python's named groups, inline flags and comments, \\A \\Z \\N \\U,
    back references, {,n}, possessive quantifiers, a class that starts with ]), and Python's compile refuses the rest of
    what JavaScript reads alone ([^], \\p{...}, \\k<...>, (?<name>...))."""
    i, in_class = 0, False  # where the scan is, and whether it is inside [...]
    while i < len(p):  # one character or escape at a time
        c = p[i]  # this character
        if c == "\\":  # an escape: the next character is taken with it
            nxt = p[i + 1:i + 2]  # the escaped character
            if nxt in ESCAPES:  # \A, \Z, \N{...} and \U........ mean other things in JavaScript
                return "escape"
            if nxt.isdigit() and nxt != "0" and not in_class:  # a back reference: joined patterns number their groups anew
                return "backreference"
            i += 2  # past the escape
            continue
        if in_class:  # inside a class only its end matters
            in_class = c != "]"  # a ] ends it
        elif c == "[":  # a class starts
            j = i + 1 + (p[i + 1:i + 2] == "^")  # past a negation
            if p[j:j + 1] == "]":  # Python reads []a] as a class holding ], JavaScript as an empty class
                return "class"
            in_class, i = True, j  # inside it, from its first member
            continue
        elif c == "(" and p[i + 1:i + 2] == "?" and not p.startswith(GROUPS, i):  # (?P<, (?i), (?#, (?> and the like
            return "group"
        elif c == "{" and p[i + 1:i + 2] == ",":  # Python reads {,3} as up to three, JavaScript as the text
            return "quantifier"
        elif c in "*+?}" and p[i + 1:i + 2] == "+":  # a possessive quantifier (Python 3.11 and later), an error in JavaScript
            return "quantifier"
        i += 1  # the next character
    return ""


def pattern_problem(p) -> str:
    """Why a pattern cannot be used ("" when it can): not text, too long, read otherwise by one of the two languages, broken,
    or matching the empty text (it would match everywhere and cover nothing)."""
    if not isinstance(p, str) or not p.strip() or len(p) > MAX_PATTERN:  # text of a sane length
        return "text"
    why = js_problem(p)  # a form the two read differently
    if why:
        return why
    try:
        rx = re.compile(p, re.ASCII)  # as Python reads it, with JavaScript's ASCII classes
    except (re.error, RecursionError, OverflowError):  # broken, or too deep to compile
        return "broken"
    return "empty" if rx.fullmatch("") else ""  # a pattern that matches nothing at all


def word_problem(w) -> str:
    """Why a leak word cannot be used ("" when it can): it is matched as written, so only its shape counts."""
    return "" if isinstance(w, str) and w.strip() and len(w) <= MAX_PATTERN else "text"


def problems(table) -> list:
    """What stops a table from being kept, as "where:why" codes ([] for a table that can be used): an object of a sane size, its
    pattern lists (each pattern read alike by Python and JavaScript), colours of six hex digits, and short words for the band,
    the label and the contacts to unlink."""
    if not isinstance(table, dict):  # an object, as src/blind.json is
        return ["table:shape"]
    try:
        size = len(json.dumps(table, ensure_ascii=False))  # its size as a file
    except (TypeError, ValueError):  # not JSON at all
        return ["table:shape"]
    if size > MAX_TABLE:  # far larger than any table a person writes
        return ["table:size"]
    out = []  # the problems found
    for k in LISTS:  # mask, mask_whole, leak
        v = table.get(k, [])  # absent means empty
        if not isinstance(v, list) or len(v) > MAX_PATTERNS:  # a list of a sane length
            out.append(f"{k}:shape")
            continue
        check = word_problem if k == "leak" else pattern_problem  # leak words are matched as written; the others are patterns
        out += [f"{k}:{n}:{why}" for n, p in enumerate(v, 1) for why in [check(p)] if why]  # 1-based, as a person counts
    for k in ("mask_fill", "mark_fill"):  # the bar's and the band's colours
        if k in table and not (isinstance(table[k], str) and COLOR.fullmatch(table[k])):
            out.append(f"{k}:shape")
    unlink = table.get("contacts_unlink", [])  # contact labels whose link goes
    if not isinstance(unlink, list) or len(unlink) > 50 or not all(isinstance(x, str) and len(x) <= MAX_WORDS for x in unlink):
        out.append("contacts_unlink:shape")
    if not isinstance(table.get("logo_mask", {}), (dict, list)):  # kept for the shape of the shipped table; nothing reads it yet
        out.append("logo_mask:shape")
    footer = table.get("footer", {})  # the label in every footer, per language
    if not isinstance(footer, dict) or any(k not in ("ko", "en") or not isinstance(v, str) or not v.strip() or len(v) > MAX_WORDS for k, v in footer.items()):
        out.append("footer:shape")
    banner = table.get("banner", {})  # the band's two parts, per language
    if not isinstance(banner, dict) or any(k not in ("ko", "en") or not isinstance(v, list) or len(v) != 2
                                           or not all(isinstance(x, str) and x.strip() and len(x) <= MAX_WORDS for x in v) for k, v in banner.items()):
        out.append("banner:shape")
    return out


def kept(table: dict) -> dict:
    """The keys of a table that are kept (what a person's file holds beyond them stays out of the workspace)."""
    keys = ("_comment",) + LISTS + ("mask_fill", "mark_fill", "contacts_unlink", "logo_mask", "footer", "banner")  # src/blind.json's keys
    return {k: table[k] for k in keys if k in table}


def counts(table: dict) -> dict:
    """How many patterns each list holds: the panel's summary of a table."""
    return {k: len(table.get(k) or []) for k in LISTS}


# ---------------------------------------------------------------- where the patterns match


def nbsp(p: str) -> str:
    """A pattern whose plain spaces also match the no-break space the documents put between words (blind.js nbsp, the same
    rule): a space outside a character class becomes a class of both spaces."""
    out, cls, i = [], False, 0  # the pattern rewritten; inside [...] or not; where we are
    while i < len(p):
        c = p[i]
        if c == "\\":  # an escape stays whole (\s, \., \[)
            out.append(p[i:i + 2])
            i += 2
            continue
        if c == "[":  # into a class
            cls = True
        elif c == "]":  # out of it
            cls = False
        out.append("[ \u00a0]" if c == " " and not cls else c)  # a space outside a class: either space
        i += 1
    return "".join(out)


@functools.lru_cache(maxsize=8)
def _compiled(mask: tuple, whole: tuple):
    """The mask patterns joined into one, as blind.js joins them (the first that matches at a place wins), and the whole-value
    patterns, each anchored at both ends. None for no patterns."""
    rx = re.compile("|".join(f"(?:{nbsp(p)})" for p in mask), re.ASCII) if mask else None  # one pass over a text
    return rx, [re.compile(f"(?:{nbsp(p)})", re.ASCII) for p in whole]  # fullmatch anchors them


def flags(text: str, table: dict) -> list:
    """One flag per character of text: True where a bar covers it. The spaces inside a matched phrase stay uncovered, so the
    bar is cut at each word as blind.js cuts it, unless a mask_whole pattern takes the whole match (a contact value)."""
    rx, whole = _compiled(tuple(table.get("mask") or ()), tuple(table.get("mask_whole") or ()))  # compiled once per table
    out = [False] * len(text)  # nothing covered yet
    if rx is None:  # an empty table covers nothing
        return out
    for m in rx.finditer(text):  # every match, left to right
        if not m.group(0):  # an empty match covers nothing (blind.js skips it too)
            continue
        one = any(w.fullmatch(m.group(0)) for w in whole)  # a value covered with its spaces by one bar
        for i in range(m.start(), m.end()):  # its characters
            out[i] = one or not text[i].isspace()  # a space between words stays, unless the whole value goes
    return out


def segments(text: str, table: dict, fl: list | None = None) -> list:
    """[(piece, covered)] of a text, in order: the runs of characters that share one flag."""
    fl = flags(text, table) if fl is None else fl  # the flags, unless the caller has them (a shortened label keeps its full label's)
    out = []  # the runs
    for ch, f in zip(text, fl):  # each character with its flag
        if out and out[-1][1] == f:  # the same as the run before
            out[-1][0] += ch
        else:  # a new run
            out.append([ch, f])
    return [(s, f) for s, f in out]


def hits(text: str, table: dict) -> bool:
    """Does any mask pattern cover a part of this text?"""
    return any(flags(str(text or ""), table))


def plain(text: str, table: dict) -> str:
    """A text with what the table covers taken out, on one line: what a blind edition may say where no bar can stand (a file's
    title, author and name)."""
    t = str(text or "")  # the text
    return " ".join("".join(c for c, f in zip(t, flags(t, table)) if not f).split())  # the uncovered characters, spaces made single


def title(text: str, table: dict, lang_: str) -> str:
    """A blind edition's own title: the text without what the table covers, then the edition's label (the footer's words)."""
    label = (table.get("footer") or {}).get(lang_) or ""  # "블라인드 버전", "Blind version"
    return " ".join(x for x in (plain(text, table), f"({label})" if label else "") if x)


def leak_found(word: str, text: str) -> bool:
    """Does a leak word show in a text? As written, never as a pattern ("500+" is not found in a patent number's 50000). A word
    that starts with a Latin letter counts only on its own, with no Latin letter on either side ("NCI" is not found in
    COMPETENCIES, "KT" not in "KTX"); any other word counts wherever it stands."""
    if re.match(r"[A-Za-z]", word):  # a Latin word: on its own only
        return re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", text) is not None
    return word in text  # Hangul, digits, signs: anywhere


def leaks(text: str, table: dict) -> list:
    """The leak words and mask patterns that show in a text (a blind edition's text layer, its title, its links): [] when the
    text shows nothing the table hides. Each is looked for in the text as it is and with its spaces and line ends made
    single, so a name broken over two lines is found too."""
    t = str(text or "")  # the text
    flat = " ".join(t.split())  # its words on one line
    found = [w for w in table.get("leak") or [] if any(leak_found(w, s) for s in (t, flat))]  # the words that must not show
    for p in table.get("mask") or []:  # then the patterns that cover: a match left in the text is a name the bars missed
        rx = re.compile(nbsp(p), re.ASCII)  # as blind.js reads it
        if any(m.group(0) for s in (t, flat) for m in rx.finditer(s)):  # a match that holds a character
            found.append(p)
    return list(dict.fromkeys(found))  # each once, in the table's order


# ---------------------------------------------------------------- drawing: a figure's text with its bars


def bar_box(font) -> tuple:
    """The top and bottom of a bar for a face at its size, as offsets from where its text is drawn: the ink of the square glyph
    (U+25A0) the documents' bars are made of, so a figure's bars stand as high as the page's."""
    box = font.getbbox("■")  # the square's ink, from the drawing origin
    return box[1], box[3]  # its top and bottom


def draw(d, xy, text: str, font, fill, table: dict, fl: list | None = None, bar=None) -> None:
    """Draw a text at xy (the top-left anchor ImageDraw.text uses) with what the table covers drawn as bars of the text's own
    width in the table's mask_fill, never as the words. fl: the flags, when the caller has them; bar: the bars' colour."""
    x, y = xy  # where the text starts
    color = bar or "#" + str(table.get("mask_fill") or "8B1A1A")  # the bars' red
    top, bottom = bar_box(font)  # how high a bar stands
    at = 0  # characters drawn so far
    for piece, covered in segments(text, table, fl):  # each run
        x0 = x + font.getlength(text[:at])  # where the run starts, as the whole text lays it out
        x1 = x + font.getlength(text[:at + len(piece)])  # and where it ends
        if covered:  # a bar of the run's width, never its words
            d.rounded_rectangle([x0, y + top, max(x0 + 1, x1), y + bottom], radius=max(1, (bottom - top) // 8), fill=color)
        else:  # the words as they are
            d.text((x0, y), piece, fill=fill, font=font)
        at += len(piece)  # the next run


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)  # the arguments
    if len(a) == 2 and a[0] == "check":  # a table's problems
        try:
            table = json.loads(pathlib.Path(a[1]).read_text(encoding="utf-8"))  # the file
        except (OSError, ValueError):  # not there, or not JSON
            print("table:shape")
            return 1
        found = problems(table)  # what stops it
        print("\n".join(found) or "ok")
        return 1 if found else 0
    print(__doc__.strip().splitlines()[-1].strip())  # the usage line
    return 2


if __name__ == "__main__":
    sys.exit(main())
