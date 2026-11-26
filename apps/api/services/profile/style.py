"""The person's own writing rules: the style packs kept in the workspace's style/ folder (docs/WRITING.md), each checked
before it is kept so a broken pattern can never stop a check later, the pack in use as written, and one correction of the
person's kept as a row of that pack's claims (docs/WRITING.md "Phrases fixed once"), in one undo step."""
from __future__ import annotations

import json  # a pack's size
import re  # the names of style packs, and each pattern compiled once
from pathlib import Path  # paths

from ...core.routing import text_field  # a request's text, or refused
from ...core.workspace import read_json, write_json  # files

ROOT = Path(__file__).resolve().parents[4]  # the repository (or the app's bundle): the shipped pack


def style_names(api) -> list[str]:
    """The person's own style packs, kept in the workspace's style/ folder (docs/WRITING.md)."""
    folder = api.ws.path("style")  # where they live
    return sorted(f.stem for f in folder.glob("*.json")) if folder.is_dir() else []  # by name


def add_style(api, req: dict, step: bool = True) -> str:
    """A person's own style pack into the workspace's style/ folder, checked first, so a broken pattern can never stop a
    check later. {name, pack}: the pack is the JSON of docs/WRITING.md. Returns the name it is kept under. A pack kept over one of
    the same name is one undo step (D3-01), so the old rules come back with Undo; `step` is False for a caller that makes the
    step itself (add_rule)."""
    name = re.sub(r"[^\w가-힣.-]+", "-", text_field(req, "name").strip())[:60].strip("-.") or "mine"  # a safe file name
    if name == "default":  # the shipped pack keeps its name
        name = "mine"
    pack = req.get("pack")  # the rules
    if not isinstance(pack, dict) or not pack or len(json.dumps(pack, ensure_ascii=False)) > 200_000:  # a JSON object of a sane size
        raise ValueError("style")  # the page says it is not a style pack
    if not isinstance(pack.get("banned_chars", ""), str) or any(not isinstance(pack.get(k, {}), dict) for k in ("resume", "cover")):  # the shapes the checks read
        raise ValueError("style")
    words = lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)  # noqa: E731  a list of words or rules
    each = lambda v: words(v) or (isinstance(v, dict) and all(words(x) for x in v.values()))  # noqa: E731  one list, or one per language
    res, cov = pack.get("resume") or {}, pack.get("cover") or {}  # the two objects the writers read
    if not each(res.get("rules", [])) or not each(res.get("banned_words", [])) or not words(cov.get("banned_words", [])):  # the lists the prompts and the checks walk
        raise ValueError("style")
    if not isinstance(pack.get("banned_patterns", []), list):  # a list of [pattern, why]
        raise ValueError("style")
    printed = pack.get("printed", {})  # the rules for printed words (docs/WRITING.md "Printed words")
    if not isinstance(printed, dict) or not words(printed.get("colloquial", [])) or not words(printed.get("highlight_names", [])) \
            or printed.get("lines", "polish") not in ("fail", "polish") or not isinstance(printed.get("editing_notes", []), list) \
            or not (printed.get("not_a_but_b") is None or (isinstance(printed.get("not_a_but_b"), int) and not isinstance(printed.get("not_a_but_b"), bool))):
        raise ValueError("style")
    import check_parity  # src/check_parity.py: the parity object's own shape (docs/DOCUMENTS.md "Checks across documents")
    if check_parity.pack_problem(pack):  # aliases, glossary, deck_only, whole_period, newest_first, terms
        raise ValueError("style")
    for row in [*(pack.get("banned_patterns") or []), *printed.get("editing_notes", []), *[[p, ""] for p in printed.get("colloquial", [])]]:  # each pattern must compile, or every check would stop on it
        if not (isinstance(row, list) and len(row) == 2 and all(isinstance(x, str) for x in row)):  # [pattern, why]
            raise ValueError("style")
        try:
            re.compile(row[0])  # a broken pattern is refused here, not at the next check
        except re.error as exc:
            raise ValueError("style") from exc
    import check_claims  # src/check_claims.py: the phrases fixed once (docs/WRITING.md "Phrases fixed once")
    import check_ledger  # src/check_ledger.py: the edition against the profile, and the shape kept
    import check_pages  # src/check_pages.py: what the pages show
    if check_claims.problems(pack.get("claims")) or check_ledger.problems(pack) or check_pages.problems(pack):  # a shape they cannot read, a pattern that does not compile
        raise ValueError("style")  # refused here, never at the next build's check
    import tempfile  # the pack read once by the writers' own loader before it is kept
    import write_resume  # src/write_resume.py: its loader reads the cover options too (src/cover.py)
    with tempfile.TemporaryDirectory() as tmp:  # never in the style folder, where the panel lists the packs
        trial = Path(tmp) / f"{name}.json"  # the pack as it would be kept
        write_json(trial, pack)
        try:
            write_resume.load_style(str(trial))  # an unknown numbers policy, say, stops every later draft: stopped here instead
        except (SystemExit, Exception) as exc:  # the loader's message, or a value it cannot use
            raise ValueError("style") from exc
    if step:  # the pack replaced or added as one undo step
        with api.ws.change({"code": "undo_style", "title": name[:60]}, [f"style/{name}.json"]):
            write_json(api.ws.path("style", f"{name}.json"), pack)  # kept with the workspace (and its backups)
    else:  # the caller's own step holds it
        write_json(api.ws.path("style", f"{name}.json"), pack)
    return name  # the page selects it


def style_read(api) -> dict:
    """The writing rules in use (GET /api/v1/style): their name ("default" for Offerowl's own), whether they are the
    person's own, and the pack as written, its claims included: what an agent reads before it adds a correction."""
    spec = api.tasks.style_spec()  # "default", or the path of the person's pack
    f = ROOT / "src" / "style" / "default.json" if spec == "default" else Path(spec)  # the file
    pack = read_json(f, {})  # as written
    return {"style": "default" if spec == "default" else f.stem, "own": spec != "default", "pack": pack if isinstance(pack, dict) else {}}


def add_rule(api, req: dict) -> dict:
    """One correction of the person's kept as a row of the claims of the pack in use (docs/WRITING.md "Phrases fixed once"),
    so a draft never writes it again and every build holds the documents to it: {list: retired | shared | proposal, row:
    [pattern, text, why] (and the ledger words), lang: ko | en | both}. While Offerowl's own pack is in use the row goes into
    the person's own pack "rules" (made from it the first time), which is chosen from then on. The whole pack is checked as
    a new one is (add_style), so a pattern that does not compile is refused here. One undo step. Returns {style, list, lang,
    rows}: the pack's name and the rows that list holds now in that language."""
    import copy  # the pack is changed on a copy
    kind, lang, row = text_field(req, "list"), text_field(req, "lang", "both") or "both", req.get("row")  # what is asked
    if kind not in ("retired", "shared", "proposal") or lang not in ("ko", "en", "both"):  # the lists and languages there are
        raise ValueError("rule")
    if not (isinstance(row, list) and 2 <= len(row) <= 4 and all(isinstance(x, str) and len(x) <= 400 for x in row[:3])
            and str(row[0]).strip() and (len(row) < 4 or isinstance(row[3], (str, list)))):  # [pattern, text, why] and the ledger words
        raise ValueError("rule")
    row = [str(x).strip() if isinstance(x, str) else x for x in row]  # no edge spaces in a pattern
    cur = style_read(api)  # the pack in use
    name = cur["style"] if cur["own"] else "rules"  # the person's own pack, or the one made for their rules
    base = cur["pack"] if cur["own"] else (read_json(api.ws.path("style", "rules.json"), None) or cur["pack"])  # what the row joins
    pack = copy.deepcopy(base)  # changed on a copy: the file is written only once the whole pack passed
    claims = pack.setdefault("claims", {}) if isinstance(pack.get("claims", {}), dict) else {}  # the table
    pack["claims"] = claims  # a broken value is replaced, never kept
    have = claims.get(kind)  # one list for both languages, one per language, or none
    if lang == "both":  # the rule holds in either edition
        if isinstance(have, dict):  # kept per language: the row joins each
            for k in ("ko", "en"):
                have.setdefault(k, [])
                if row not in have[k]:
                    have[k].append(row)
        else:  # one list
            claims[kind] = (have or []) + ([row] if row not in (have or []) else [])
    else:  # one language
        if isinstance(have, list):  # one list for both: it stays for both, and the row joins one side
            claims[kind] = {k: list(have) + ([row] if k == lang and row not in have else []) for k in ("ko", "en")}
        else:  # per language already, or none yet
            side = (have or {}).setdefault(lang, []) if isinstance(have, dict) else None
            if side is None:
                claims[kind] = {lang: [row]}
            elif row not in side:
                side.append(row)
    with api.ws.change({"code": "undo_rule", "title": row[0][:60]}, [f"style/{name}.json"]):  # one undo step
        name = add_style(api, {"name": name, "pack": pack}, step=False)  # checked as a new pack is, and kept in this step
    api.set_settings({"style": name})  # in use from now on
    now = (pack["claims"].get(kind) or [])  # the list as kept
    n = len(now.get("ko" if lang == "both" else lang) or []) if isinstance(now, dict) else len(now)  # its rows in that language
    return {"style": name, "list": kind, "lang": lang, "rows": n}
