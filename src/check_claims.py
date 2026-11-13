#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phrases fixed once stay fixed in every later edition: the style pack's "claims" object (docs/WRITING.md "Phrases fixed
once"). A sentence corrected against the facts tends to come back in the next edition written from an older one, and one
edition corrected alone leaves the others saying it the old way; only a check that every edition passes keeps them together.

  retired   [old, new, why, ledger words]  a phrase taken out because it did not match the facts never comes back; new says
            what to write (may be ""), the ledger words are what the rule rests on (optional)
  shared    [topic, phrase, why, ledger words]  a general edition that speaks of the topic says it with the phrase (an edition
            rewritten for one posting words it its own way, so only general editions are held to it)
  proposal  [topic, need, why]  a sentence that speaks of work which ended as a proposal or a plan holds the word that says
            so (a proposal written as done work is a claim the facts do not carry)

Each list is one for both languages, or one per language ({"ko": [...], "en": [...]}); every pattern is a Python regular
expression. A rule that names its ledger words is held to the ledger (the person's profile): when the profile no longer has
those words, the rule is said to be stale, so a table never outlives the facts it was written from.

The words read are the document's own: the resume's Word paragraphs and the deck's page when they lie beside the PDF (no
line break or page footer cuts a phrase there), else the PDF's text, with all space made one.

  python3 src/check_claims.py <document.pdf> --style <pack> [--lang ko|en] [--ledger <profile.json>] [--general]
"""
import html  # the deck page's entities
import json  # the pack and the ledger
import pathlib  # paths
import re  # the rules
import sys  # the command line
import zipfile  # the resume's Word file

import check_lines as CL  # the Issue every check gives
import llm  # the message helper and the language setting

MSG = {  # what this check says, in both languages with the same keys
    "en": {
        "claim_retired": "a phrase taken out once is printed again: '{old}'{instead} ({why})",
        "claim_retired_instead": ", write '{new}'",
        "claim_shared": "it speaks of '{topic}' without the phrase every edition uses: '{phrase}' ({why})",
        "claim_proposal": "work that ended as a proposal is written as done: '{near}' ({why})",
        "claim_anchor": "a rule of the claims rests on words the profile no longer has: '{words}' ({rule}). Check the rule against the profile",
    },
    "ko": {
        "claim_retired": "고친 표현이 다시 찍혔다: '{old}'{instead} ({why})",
        "claim_retired_instead": ", 고쳐 쓴 말은 '{new}'",
        "claim_shared": "'{topic}'에 대해 쓰면서 판마다 같이 쓰는 문구가 없다: '{phrase}' ({why})",
        "claim_proposal": "제안으로 끝난 일을 한 일처럼 썼다: '{near}' ({why})",
        "claim_anchor": "표현 규칙이 기대는 원장 구절이 프로필에 없다: '{words}' ({rule}). 프로필과 규칙을 다시 맞춘다",
    },
}
KINDS = ("retired", "shared", "proposal")  # the three lists of the claims object
WINDOW = 120  # a sentence's reach either side of the topic when no full stop ends it first


def t(key: str, **kw) -> str:
    """A message of this check in the person's language."""
    return llm.message(MSG, key, **kw)


def issue(key: str, polish: bool = False, **kw) -> CL.Issue:
    """A problem worded in the person's language, with its code and values kept for the report."""
    out = CL.Issue(t(key, **kw))  # the words, a str to every caller
    out.code, out.values, out.polish = key, kw, polish  # and what they say
    return out


def flat(text: str) -> str:
    """Text in one line: a word joiner the typesetting puts between digits and Hangul goes, and every run of space is one."""
    return re.sub(r"\s+", " ", str(text or "").replace("\u2060", "").replace("\u00a0", " ")).strip()  # a no-break space reads as a space


def docx_text(path: pathlib.Path) -> str:
    """The paragraphs of a Word file, one per line, as written."""
    with zipfile.ZipFile(path) as z:  # a .docx is a zip of XML parts
        xml = z.read("word/document.xml").decode("utf-8")  # the body
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)  # each paragraph
    return "\n".join("".join(html.unescape(s) for s in re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)) for p in paras)  # its runs' text


def page_text(path: pathlib.Path) -> str:
    """The words of a deck's HTML page, without its scripts and styles."""
    h = path.read_text(encoding="utf-8")  # the page as printed
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S)  # code and styles are no words
    return html.unescape(re.sub(r"<[^>]+>", " ", h))  # the tags out, the entities read


def doc_text(pdf: str) -> str:
    """The words of a typeset document in one line: the Word file or the HTML page beside the PDF when there is one, else
    the PDF's text layer (a document the person made, a renderer that left neither)."""
    base = pathlib.Path(pdf)  # the files beside the PDF share its name
    try:
        if base.with_suffix(".docx").is_file():  # the resume's Word file: its paragraphs as set
            return flat(docx_text(base.with_suffix(".docx")))  # in one line
        if base.with_suffix(".html").is_file():  # the deck's page
            return flat(page_text(base.with_suffix(".html")))  # in one line
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):  # unreadable: the PDF's text still says the words
        pass  # read below
    import pdftools as P  # the PDF's text, with poppler or PDFium
    return flat(P.text(pdf))  # the text layer, in one line


def rows_of(claims: dict, kind: str, lang: str) -> list:
    """The rules of one kind that hold in this language: a list for both languages, or the language's own list."""
    v = claims.get(kind) if isinstance(claims, dict) else None  # the list, or one per language
    if isinstance(v, dict):  # one per language
        v = v.get(lang)  # this language's
    return [r for r in v or [] if isinstance(r, list) and len(r) >= 2 and all(isinstance(x, (str, list)) for x in r)]  # rows in their shape only


def find(pat: str, text: str):
    """re.search that takes a broken pattern as finding nothing (the pack's validator refuses one; an older file may hold it)."""
    try:
        return re.search(pat, text)  # the first place it stands
    except re.error:  # nothing found
        return None


def sentence(text: str, m: re.Match) -> str:
    """The sentence a match stands in: from the full stop before it to the one after it, or WINDOW letters either way."""
    left = max(text.rfind(". ", 0, m.start()), m.start() - WINDOW)  # where it starts
    ends = [x for x in (text.find(". ", m.end()),) if x >= 0] + [m.end() + WINDOW]  # where it ends
    return text[max(0, left + 1):min(ends)]  # the sentence, its full stop left out


def anchor_words(row: list) -> list:
    """The ledger words a rule names (its fourth element: one text or several)."""
    w = row[3] if len(row) > 3 else None  # a row may end without them
    return [x for x in ([w] if isinstance(w, str) else w or []) if isinstance(x, str) and x.strip()]  # one text or several


def squash(s: str) -> str:
    """For finding ledger words: no space and no emphasis marks, so a reflowed or bolded ledger still holds them."""
    return re.sub(r"\s+|\*\*|==", "", s or "")  # space, bold and highlight marks out


def check(text: str, pack: dict, lang: str, general: bool = True, blind: bool = False, ledger: str | None = None) -> list:
    """The claims problems of one document's words (text, as flat() gives it). general: a general edition, held to the
    shared phrases too; blind: a blind edition, whose bars may cover a topic's words (its shared phrases are not read);
    ledger: the profile's words, for the rules that name what they rest on (None when the check was given none)."""
    claims = pack.get("claims") if isinstance(pack.get("claims"), dict) else {}  # the pack's table
    out = []  # the findings
    for row in rows_of(claims, "retired", lang):  # a phrase fixed once
        m = find(str(row[0]), text)  # printed again?
        if m:
            new = str(row[1]) if len(row) > 1 and isinstance(row[1], str) else ""  # what the person wrote instead, if said
            out.append(issue("claim_retired", old=m.group(0), new=new, why=str(row[2]) if len(row) > 2 else "",
                             instead=t("claim_retired_instead", new=new) if new else ""))  # the words as printed, the fix and why
    if general and not blind:  # the phrases every general edition says alike
        for row in rows_of(claims, "shared", lang):  # each topic
            m = find(str(row[0]), text)  # spoken of?
            if m and not find(str(row[1]), text):  # it speaks of the topic, and not with the phrase
                out.append(issue("claim_shared", topic=m.group(0), phrase=str(row[1]), why=str(row[2]) if len(row) > 2 else ""))
    for row in rows_of(claims, "proposal", lang):  # work that ended as a proposal
        try:
            hits = list(re.finditer(str(row[0]), text))  # every place the work is spoken of
        except re.error:  # a broken pattern reads nothing
            continue
        for m in hits:  # each one
            s = sentence(text, m)  # the sentence that speaks of it
            if not find(str(row[1]), s):  # says it without the word
                out.append(issue("claim_proposal", near=" ".join(s.split())[:90], why=str(row[2]) if len(row) > 2 else ""))
    if ledger is not None:  # the rules held to the ledger they rest on
        have = squash(ledger)  # the facts' words, in the form compared
        for kind in ("retired", "shared"):  # the rows that may name what they rest on
            for row in rows_of(claims, kind, lang):
                for w in anchor_words(row):  # each of its ledger words
                    if squash(w) not in have:  # gone from the facts: the rule is stale
                        out.append(issue("claim_anchor", words=w, rule=str(row[0])[:40]))
    return out


def problems(claims) -> list:
    """What makes a claims object unusable, as short lines (the style pack's validator refuses the pack on any): a list
    that is neither a list nor one per language, a row that is not [pattern, text, why] (and the ledger words), a pattern
    that does not compile."""
    if claims is None:  # no table: nothing to refuse
        return []
    if not isinstance(claims, dict):  # the object itself in another shape
        return ["claims"]
    bad = []  # what is wrong, as short lines
    for kind in KINDS:  # retired, shared, proposal
        v = claims.get(kind, [])  # a list, or one per language
        lists = v.values() if isinstance(v, dict) else [v]  # one per language, or one for both
        if isinstance(v, dict) and set(v) - {"ko", "en"}:  # a language the editions do not have
            bad.append(f"{kind}: languages are ko and en")
        for rows in lists:  # each list
            if not isinstance(rows, list):
                bad.append(f"{kind}: not a list")
                continue
            for i, row in enumerate(rows):  # each row
                if not (isinstance(row, list) and 2 <= len(row) <= 4 and all(isinstance(x, str) for x in row[:3])):  # [pattern, text, why] and the ledger words
                    bad.append(f"{kind}:{i}: a row is [pattern, text, why]")
                    continue
                if len(row) > 3 and not (isinstance(row[3], str) or (isinstance(row[3], list) and all(isinstance(x, str) for x in row[3]))):
                    bad.append(f"{kind}:{i}: the ledger words are a text or a list of texts")
                pats = [row[0]] + ([row[1]] if kind != "retired" else [])  # the patterns of the row (a replacement is words)
                for p in pats:  # each must compile, or every later check would read nothing there
                    try:
                        re.compile(p)
                    except re.error:
                        bad.append(f"{kind}:{i}: the pattern does not compile")
    return bad


def main(argv: list) -> int:
    pdf = next((a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] not in ("--style", "--lang", "--ledger"))), "")
    if not pdf or "--style" not in argv:
        print(__doc__)
        return 1
    pack = json.loads(pathlib.Path(argv[argv.index("--style") + 1]).read_text(encoding="utf-8"))
    lang = argv[argv.index("--lang") + 1] if "--lang" in argv else "ko"
    ledger = None
    if "--ledger" in argv:  # the profile the rules rest on
        import check_ledger  # its words, as the ledger checks read them
        ledger = check_ledger.ledger_text(json.loads(pathlib.Path(argv[argv.index("--ledger") + 1]).read_text(encoding="utf-8")))
    bad = check(doc_text(pdf), pack, lang, general="--general" in argv, ledger=ledger)
    for b in bad:
        print("  - " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
