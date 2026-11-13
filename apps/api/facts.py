"""Facts: the candidates read from the material, what the person kept, dropped and edited, and the profile built
from the kept ones.

Three kinds of candidate share one list (sources/candidates.json):
- "ingest": found by src/ingest.py in a file, with the quote it rests on. Kept ones go into the profile through
  src/review.py's accept().
- "profile": an item of an imported Offerowl profile (examples/sample_ko.json is one). The imported profile is
  kept as base.json; each of its items becomes a candidate that points at it (`ref`), so the profile keeps every
  field the generators read (points, figures, highlights) while only the items the person kept go in.
- "typed": a fact the person typed in, which is its own quote.

Only kept facts reach the profile (README: "keeps only the facts you confirm"). profile/profile.json is always
rebuilt from base.json, the candidates, review.json (kept or dropped), edits.json and details.json, so an undo of any
of those files gives back exactly the profile that went with it.
"""
from __future__ import annotations

import ast  # a stored dict's text read back as a literal
import copy  # the base profile is never changed in place
import hashlib  # ids of imported items
import json  # quotes of structured items
import re  # the marks of a ledger's text
import sys  # the engine's folder on the import path
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules
import review  # noqa: E402  the merge rules of the review step

from .workspace import Workspace, read_json, write_json  # noqa: E402  files and undo

# The files a fact change touches (relative to the workspace), for Workspace.change().
FACT_FILES = ["sources/candidates.json", "sources/review.json", "sources/edits.json", "profile/details.json",  # every file a fact change can write, so one undo restores them all
              "profile/base.json", "profile/profile.json", "sources/materials.json", "profile/evidence.json",  # the evidence map follows the profile
              "sources/locks.json"]  # locked sentences: later drafts keep them
# The person's own fields, edited in "Your details" and laid over the profile.
DETAIL_KEYS = ("name", "name_en", "email", "phone", "tagline", "headline", "intro")  # the fields 'Your details' edits
PERSON_KEYS = ("name", "name_en", "email", "phone")  # who the person is: the same in every edition (an application's own edition borrows them)
# Kinds that come from an imported profile's summary and texts, beside the ingest kinds of src/ingest.py.
TEXT_KINDS = ("card", "highlight", "layer", "competency", "about", "motivation")  # the summary texts an imported profile gives as facts
# Section titles of an imported profile mapped to fact kinds (the rest are "other").
SECTION_KIND = {"자격증": "certificate", "certificates": "certificate", "수상": "award", "awards": "award", "논문": "paper",  # a list's name decides its kind chip
                "publications": "paper", "특허": "patent", "patents": "patent"}


def own_english(v) -> list:
    """(index, row) of the English rows of a per-language list ({ko, en}) that is not the Korean list row for row: a
    different count means the person wrote the English list apart, so its rows are facts of their own and an English
    sentence rests on its own row, not on the Korean row that happens to share its number. Empty for a translation (the
    same count), a plain list, or a list in one language only."""
    if not isinstance(v, dict) or not isinstance(v.get("ko"), list) or not v.get("ko") or not isinstance(v.get("en"), list):  # both languages, Korean first
        return []  # nothing apart
    return list(enumerate(v["en"])) if len(v["en"]) != len(v["ko"]) else []  # row for row means translated


def pick(v):
    """A field that may be written per language ({ko, en}): the Korean text, else the English, else as it is."""
    if isinstance(v, dict) and ("ko" in v or "en" in v):  # a per-language field
        return v.get("ko") if v.get("ko") not in (None, "") else v.get("en")  # Korean first, as the profile is written
    return v  # a plain value


def text_of(v) -> str:
    """A value as one line of text for a card (lists joined, None empty, a per-language field its Korean, else English)."""
    v = pick(v)  # {ko, en}: one language, never the dict written out as text
    if v is None:  # an absent value reads as nothing
        return ""  # nothing
    if isinstance(v, (list, tuple)):  # a paragraph list or a row
        return " ".join(text_of(x) for x in v if x not in (None, ""))  # joined with spaces
    return str(v)  # numbers and strings


def _undict(v):
    """A field an older reading stored as a per-language dict written out ("{'ko': ..., 'en': ...}"): its text, as text_of
    gives it now. Anything else as it is."""
    if isinstance(v, str) and v.startswith("{") and ("'ko'" in v or "'en'" in v):  # the shape str(dict) left
        try:
            d = ast.literal_eval(v)  # a literal only: nothing runs
        except (ValueError, SyntaxError):  # cut short or not a literal
            return v  # as it was
        if isinstance(d, dict):  # the per-language field it was
            return text_of(d)  # its Korean, else its English
    return v


def as_read_now(c: dict) -> dict:
    """A stored candidate with its text fields as a reading now writes them (read only: the file stays as it is)."""
    if not isinstance(c, dict):  # not a candidate
        return c
    return {**c, **{k: _undict(c[k]) for k in ("title", "org", "period", "statement", "quote") if k in c}}


def item_id(material: str, ref: list) -> str:
    """A stable id for an imported item: the same file and position give the same id after a reload."""
    return hashlib.sha1(("profile\x1f" + material + "\x1f" + json.dumps(ref)).encode("utf-8")).hexdigest()[:12]  # the file, the position: stable across reloads


def ledger_text(md) -> str:
    """A ledger's evidence text (body_md) as one line for a card: the sentences and the list lines, without the marks of
    headings, lists, tables or notes."""
    if not isinstance(md, str):  # absent or not text
        return ""  # nothing
    lines = []  # the lines kept
    for ln in md.splitlines():  # each line
        ln = ln.strip()  # without its indentation
        if not ln or ln.startswith(("<!--", "|---", "| ---", ">")) or set(ln) <= set("|-: "):  # blank lines, comments, table rules, quotes
            continue  # nothing a card needs
        lines.append(re.sub(r"^(?:#+|[-*+]|\d+[.)])\s+", "", ln).strip("| ").replace(" | ", " · "))  # without the leading marks, a table row as one line
    return " ".join(x for x in lines if x)  # one line


def period_of(start, end) -> str:
    """A role's or a school's dates as one line ('2022.03 ~ ', '2019.07 ~ 2022.02')."""
    s, e = str(start or ""), end  # start text; end may be None (still there)
    if not s and not e:  # neither date known
        return ""  # no dates
    return f"{s} ~ {'' if e is None else str(e)}".strip()  # 'start ~ end', or 'start ~' while still there


# ------------------------------------------------------------------------------------------- import

def import_profile(doc: dict, material: str, name: str) -> tuple[dict, list[dict]]:
    """An imported profile as (base, candidates). Every item a resume line is made of becomes one candidate."""
    base = copy.deepcopy(doc)  # kept whole: fields the cards do not show (points, figures) still reach the generators
    src = {"material": material, "name": name}  # where each fact came from
    cands = []  # one per item

    def add(kind, ref, title="", org="", period="", statement="", quote=""):
        cands.append({"cid": item_id(material, ref), "origin": "profile", "kind": kind, "ref": ref, "org": org,  # the card's fields, the path into the base
                      "period": period, "title": title, "statement": statement,
                      "quote": quote or statement or title, "source": src})  # one fact card

    for ri, r in enumerate(base.get("roles") or []):  # each job held
        if not isinstance(r, dict):  # a broken entry would break the profile
            continue  # a broken entry is left out
        c = r.get("career") if isinstance(r.get("career"), dict) else {}  # the ledger form's career block, when there is one
        half = c.get("ko") if isinstance(c.get("ko"), dict) else (c.get("en") if isinstance(c.get("en"), dict) else {})  # its Korean half, else its English one
        org = text_of(r.get("org")) or text_of(half.get("name")) or text_of(r.get("heading")) or text_of(r.get("key"))  # the company, as profile_loader.js reads it
        title = text_of(r.get("title")) or text_of(half.get("role")) or text_of(c.get("title"))  # the job title
        dept, place = text_of(r.get("dept")) or text_of(half.get("dept")), text_of(r.get("place")) or text_of(half.get("place"))  # the team and the city
        start, end = r.get("start") or c.get("start"), r.get("end") if "end" in r else c.get("end")  # the dates, from either form
        add("role", ["roles", ri], title=title, org=org,  # the job held: title, company, dates
            period=period_of(start, end),
            statement=" · ".join(x for x in (dept, place) if x),
            quote=" · ".join(x for x in (org, title, dept, period_of(start, end)) if x))
        for pi, p in enumerate(r.get("projects") or []):  # each project at that job
            if isinstance(p, dict):  # only real project entries
                body = text_of(p.get("summary")) or ledger_text(p.get("body_md"))  # a written summary, else the ledger's evidence text
                add("project", ["roles", ri, "projects", pi], title=text_of(p.get("title")), org=org,  # its title, company and period
                    period=text_of(p.get("period")), statement=body.replace("==", "")[:1000],  # the card shows it without highlight marks
                    quote=body[:199] if not p.get("summary") else text_of(p.get("summary")))  # the quote keeps the text exactly as written
    for ei, e in enumerate(base.get("education") or []):  # each school
        if isinstance(e, dict):  # only real school entries
            add("education", ["education", ei], title=" ".join(x for x in (text_of(e.get("major")), text_of(e.get("degree"))) if x),  # major and degree as one line
                org=text_of(e.get("school")), period=period_of(e.get("start"), e.get("end")))  # the school and its dates
    for si, s in enumerate(base.get("skills") or []):  # each skill group
        if isinstance(s, dict):  # only real skill groups
            add("skill", ["skills", si], title=text_of(s.get("category")), statement=", ".join(map(str, s.get("items") or [])))  # the group's name and its items
    for si, s in enumerate(base.get("sections") or []):  # certificates, awards and other lists
        if not isinstance(s, dict):  # a broken section is left out
            continue  # next section
        kind = SECTION_KIND.get(str(s.get("title") or "").strip().lower(), "other")  # by the list's name
        if isinstance(s.get("body_md"), str) and not s.get("items"):  # the ledger form: a text body, often a table, printed as it is
            import cover as C  # its lines, as the resume's checks read them
            lines = C.split_blocks(s["body_md"])  # without the notes in it
            add(kind, ["sections", si], title=text_of(s.get("title")), statement=" / ".join(lines)[:1000], quote=" / ".join(lines)[:199])  # one card for the whole section
        for ii, it in enumerate(s.get("items") or []):  # each line of the list
            add(kind, ["sections", si, "items", ii], title=text_of(it), org=text_of(s.get("title")))  # one card per line of the list
    summ = base.get("summary") if isinstance(base.get("summary"), dict) else {}  # the summary block
    # The headline and the introduction are the person's own words: they go to "Your details", not to fact cards
    for key, kind in (("cards", "card"), ("layers", "layer")):  # two-column cards and the stack layers
        rows = pick(summ.get(key))  # the list (per language or plain)
        lang = "ko" if isinstance(summ.get(key), dict) else None  # where the list sits
        for i, row in enumerate(rows if isinstance(rows, list) else []):  # each card or layer
            if isinstance(row, (list, tuple)) and row:  # [title, text, ...]
                ref = ["summary", key] + ([lang] if lang else []) + [i]  # its place
                add(kind, ref, title=text_of(row[0]), statement=text_of(row[1:]))  # the head and the rest of the row
        for i, row in own_english(summ.get(key)):  # an English list written apart: each row a fact of its own
            if isinstance(row, (list, tuple)) and row:  # [title, text, ...]
                add(kind, ["summary", key, "en", i], title=text_of(row[0]), statement=text_of(row[1:]))  # in the English list
    hl = pick(summ.get("highlights"))  # the key project cards
    hl_lang = "ko" if isinstance(summ.get("highlights"), dict) else None  # per-language list or plain
    for i, h in enumerate(hl if isinstance(hl, list) else []):  # each card
        if isinstance(h, dict):  # {title, where, rows}
            rows = [f"{text_of(r[0])}: {text_of(r[1:])}" for r in h.get("rows") or [] if isinstance(r, (list, tuple)) and r]  # label: text for each row of the card
            add("highlight", ["summary", "highlights"] + ([hl_lang] if hl_lang else []) + [i],  # its place, in the per-language list when there is one
                title=text_of(h.get("title")), org=text_of(h.get("where")), statement=" / ".join(rows))  # the title and where, the rows as one statement
    for i, h in own_english(summ.get("highlights")):  # English key project cards written apart
        if isinstance(h, dict):  # {title, where, rows}
            rows = [f"{text_of(r[0])}: {text_of(r[1:])}" for r in h.get("rows") or [] if isinstance(r, (list, tuple)) and r]  # label: text
            add("highlight", ["summary", "highlights", "en", i], title=text_of(h.get("title")), org=text_of(h.get("where")), statement=" / ".join(rows))
    comps = pick(base.get("competencies"))  # strengths
    comp_lang = "ko" if isinstance(base.get("competencies"), dict) else None  # strengths may be written per language
    for i, c in enumerate(comps if isinstance(comps, list) else []):  # each strength
        if isinstance(c, (list, tuple)) and c:  # [head, text]
            add("competency", ["competencies"] + ([comp_lang] if comp_lang else []) + [i], title=text_of(c[0]),  # its place, its head and its text
                statement=text_of(c[1:]))
    for i, c in own_english(base.get("competencies")):  # an English list of strengths written apart
        if isinstance(c, (list, tuple)) and c:  # [head, text]
            add("competency", ["competencies", "en", i], title=text_of(c[0]), statement=text_of(c[1:]))  # in the English list
    about = pick(base.get("about"))  # the about-me band
    about_lang = "ko" if isinstance(base.get("about"), dict) else None  # the about-me band may be per language
    for i, a in enumerate(about if isinstance(about, list) else []):  # each paragraph
        if isinstance(a, (list, tuple)) and a:  # [title, paragraph or paragraphs]
            add("about", ["about"] + ([about_lang] if about_lang else []) + [i], title=text_of(a[0]), statement=text_of(a[1:]))  # its place, its title and its text
    for i, a in own_english(base.get("about")):  # an English about-me written apart
        if isinstance(a, (list, tuple)) and a:  # [title, paragraph or paragraphs]
            add("about", ["about", "en", i], title=text_of(a[0]), statement=text_of(a[1:]))  # in the English list
    if text_of(pick(base.get("motivation"))):  # why this role
        add("motivation", ["motivation"], statement=text_of(pick(base.get("motivation"))))  # the one motivation text
    return base, cands  # the profile kept whole and its cards


def clean_name(name: str, name_en: str = "") -> tuple:
    """A name as a ledger may write it, '홍 길 동 (Gil-Dong Hong)', as the name and the English name a form shows: the Latin
    name in brackets goes to the English name when there is none, and Hangul syllables spaced apart are joined
    (src/profile_loader.js cleanName does the same for the documents)."""
    n, en = str(name or "").strip(), str(name_en or "").strip()
    m = re.match(r"^(.*?)\s*\(([A-Za-z][A-Za-z .,'-]+)\)$", n)  # 'Name (Latin Name)'
    if m:
        n, en = m.group(1).strip(), en or m.group(2).strip()
    if re.fullmatch(r"[가-힣](\s[가-힣])+", n):  # '홍 길 동'
        n = n.replace(" ", "")
    return n, en


def details_from(doc: dict) -> dict:
    """The person's own fields of an imported profile, for "Your details"."""
    p = doc.get("person") if isinstance(doc.get("person"), dict) else {}  # who
    s = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}  # the summary
    name, name_en = clean_name(text_of(p.get("name")), text_of(p.get("name_en")))  # as the documents print it
    return {"name": name, "name_en": name_en, "email": text_of(p.get("email")),  # what 'Your details' starts from
            "phone": text_of(p.get("phone")), "tagline": text_of(pick(p.get("tagline"))), "headline": text_of(pick(s.get("headline"))),   # the Korean side of a per-language value
            "intro": text_of(pick(s.get("intro")))}


# ------------------------------------------------------------------------------------------- building the profile

def _get(doc, ref):
    """The value at a path inside the profile, or None when the path is gone."""
    cur = doc  # walk down
    for k in ref:  # one level at a time
        try:
            cur = cur[k]  # one level
        except (KeyError, IndexError, TypeError):  # the path no longer exists
            return None  # the path does not exist (any more)
    return cur  # the value at the path


def _apply_edit(draft: dict, c: dict, e: dict) -> None:
    """Lay one edited imported fact over its item in the profile. Only the fields its card shows are written."""
    ref, kind = c["ref"], c["kind"]  # where and what
    item = _get(draft, ref)  # the item itself
    title, org, period, statement = (e.get(k, c.get(k, "")) for k in ("title", "org", "period", "statement"))  # new values
    if kind == "role" and isinstance(item, dict):  # a job held
        start, end = review.period(period)  # '2022.03 ~' -> ('2022.03', None)
        item.update(title=title, org=org, start=start or item.get("start", ""), end=end if (start or end) else item.get("end"))  # dates read the way review.py reads them
    elif kind == "project" and isinstance(item, dict):  # a project
        item.update(title=title, period=period, summary=statement if "statement" in e else item.get("summary", ""))  # the summary only when it was edited
    elif kind == "education" and isinstance(item, dict):  # a school
        start, end = review.period(period)  # dates
        if title != c.get("title"):  # the card shows "major degree" as one title: an edited title replaces both
            item.pop("degree", None)  # the degree is now inside the major's text
        item.update(school=org, major=title if title != c.get("title") else item.get("major", ""),  # the major only when the title was edited
                    start=start or item.get("start", ""), end=end or item.get("end", ""))  # dates kept unless new ones were typed
    elif kind == "skill" and isinstance(item, dict):  # a skill group
        item.update(category=title, items=[x.strip() for x in statement.split(",") if x.strip()])  # items typed as a comma list
    elif kind in ("card", "layer", "competency", "about") and isinstance(item, list):  # [head, text, ...]
        parent = _get(draft, ref[:-1])  # the list holding it
        if isinstance(parent, list):  # the row's own list
            parent[ref[-1]] = [title, statement] + (list(item[2:]) if kind == "layer" and "statement" not in e else [])  # a layer keeps its third column unless edited
    elif kind == "highlight" and isinstance(item, dict):  # a key project card: its title and where, and its rows when edited
        item.update(title=title, where=org)  # the card's head
        if isinstance(e.get("rows"), list):  # the canvas edited one row's text: the whole row list is kept as edited
            item["rows"] = [[str(x) for x in r][:3] for r in e["rows"] if isinstance(r, (list, tuple)) and r]  # [[label, text], ...]
    elif kind == "motivation":  # why this role
        draft["motivation"] = statement if not isinstance(draft.get("motivation"), dict) else {**draft["motivation"], "ko": statement}  # the motivation in the shape the profile has
    elif ref[:1] == ["sections"] and isinstance(item, dict):  # a section in the ledger form, one card for its whole text
        item["title"] = title  # its heading
        if "statement" in e:  # its lines were retyped
            item["body_md"] = "\n".join("- " + x.strip() for x in statement.split(" / ") if x.strip())  # as a list, since a table's columns are gone from the card
    elif ref[:1] == ["sections"]:  # one line of a list section
        parent = _get(draft, ref[:-1])  # the items list
        if isinstance(parent, list) and ref[-1] < len(parent):  # a line that still exists
            parent[ref[-1]] = title  # the line


def _remove(draft: dict, refs: list) -> None:
    """Take the dropped imported items out. Deeper and later paths go first, so the earlier indices stay right. A role
    whose card was dropped stays only as the holder of projects that were kept, with its own fields blanked."""
    roles_dropped = set()  # roles whose own card was dropped
    for ref in sorted(refs, key=lambda r: [str(x) if isinstance(x, str) else f"{x:06d}" for x in r], reverse=True):  # deepest and latest first, so earlier indices stay right
        if len(ref) == 2 and ref[0] == "roles":  # a role: decide after its projects
            roles_dropped.add(ref[1])  # decided after its projects
            continue  # next path
        if ref == ["motivation"]:  # why this role
            draft.pop("motivation", None)  # the generators skip a missing motivation
            continue  # next path
        parent = _get(draft, ref[:-1])  # the list holding the item
        if isinstance(parent, list) and isinstance(ref[-1], int) and ref[-1] < len(parent):  # an index that still exists
            parent.pop(ref[-1])  # out
            if ref[-2] == "ko":  # a per-language list: the English list loses the same row
                twin = _get(draft, ref[:-2] + ["en"])  # the English twin of a Korean list
                if isinstance(twin, list) and ref[-1] < len(twin):  # same row, when it exists
                    twin.pop(ref[-1])  # out of the English list too
    for ri in sorted(roles_dropped, reverse=True):  # roles last, from the end
        r = _get(draft, ["roles", ri])  # the role whose card was dropped
        if not isinstance(r, dict):  # already gone
            continue  # next role
        if r.get("projects"):  # kept projects need their company
            r.update(title="", dept="", place="", start="", end="")  # only the company name is left
        else:
            draft["roles"].pop(ri)  # nothing left of it
    draft["sections"] = [s for s in draft.get("sections") or [] if not isinstance(s, dict) or any(s.get(k) for k in ("items", "body_md", "lines", "rows", "groups"))]  # empty lists go; text bodies, dated lines, tables and groups of them stay
    draft["skills"] = [s for s in draft.get("skills") or [] if not isinstance(s, dict) or s.get("items")]  # empty groups go


def edited(c: dict, edits: dict) -> dict:
    """A candidate with the person's edits laid over it."""
    e = edits.get(c["cid"]) or {}  # the edited fields
    return {**c, **{k: v for k, v in e.items() if k in ("kind", "org", "period", "title", "statement")}}  # shown fields only


def build_with_evidence(base: dict | None, cands: list, status: dict, edits: dict, details: dict) -> tuple[dict, dict]:
    """The profile from everything kept: the imported items that were kept (edited), then the person's details, then
    each kept ingest or typed fact through review.accept(), then companies of the same name merged. Also returns the
    evidence map: for each item's place in the profile ("roles.0.projects.1", "summary.cards.2"), the ids of the facts
    it rests on. Places are found by object identity, so removals and merges that move items never confuse them."""
    draft = copy.deepcopy(base) if isinstance(base, dict) and base.get("schema") == review.SCHEMA else review.empty()  # start
    drops = []  # imported items not kept
    for c in cands:  # imported items first: their paths point into the base
        if c.get("origin") != "profile":  # only imported items point into the base
            continue  # the rest come after
        if status.get(c["cid"]) == "accepted":  # kept
            if c["cid"] in edits:  # the person's version
                _apply_edit(draft, c, edits[c["cid"]])  # the person's version
        else:
            drops.append(c["ref"])  # not kept: not in the profile
    tags, alive = {}, []  # id(object) -> fact id for the kept imported items; the objects, so no id is reused meanwhile
    texts = {}  # (list identity, text) -> fact id for items that are plain text (list lines, the motivation)
    for c in cands:  # each kept imported item, after its edit (an edit may replace a row's list)
        if c.get("origin") != "profile" or status.get(c["cid"]) != "accepted":  # only kept imported items
            continue  # dropped ones go below
        obj = _get(draft, c["ref"])  # the item as it is now
        if isinstance(obj, (dict, list)):  # a role, a project, a card row: tracked by identity
            tags[id(obj)] = c["cid"]  # where this fact lives
            alive.append(obj)  # kept alive so its id stays unique
        elif isinstance(obj, str):  # a line of a list section, or the motivation: tracked by its list and text
            holder = _get(draft, c["ref"][:-1]) if c["ref"] != ["motivation"] else draft  # the list holding it
            texts[(id(holder), obj)] = c["cid"]  # found again by the same list and the same words
            alive.append(holder)  # the list stays alive too
    _remove(draft, drops)  # after the edits, so the paths were still right while editing
    draft = review.normalize(draft)  # every key the rules below expect
    person, summ = draft["person"], draft["summary"]  # where the details go
    for k in ("name", "name_en", "email", "phone", "tagline"):  # the person's own fields
        if k in details:  # only fields the person set
            if isinstance(person.get(k), dict):  # a per-language value: the Korean side; the English one stays
                person[k] = {**person[k], "ko": details[k]}
            else:
                person[k] = details[k]  # laid over the profile
    if "headline" in details:  # an empty headline is a choice too
        if isinstance(summ.get("headline"), dict):  # a per-language headline: the Korean side; the English one stays
            summ["headline"] = {**summ["headline"], "ko": details["headline"]}
        else:
            summ["headline"] = details["headline"]  # laid over the summary
    if "intro" in details:  # the introduction (Korean, or the only text), in the shape the profile already has
        if isinstance(summ.get("intro"), dict):  # a per-language introduction
            summ["intro"]["ko"] = details["intro"]  # the Korean text; an English one stays
        else:
            summ["intro"] = details["intro"]  # a plain text stays plain
    for c in cands:  # facts read from files, and typed ones
        if c.get("origin") in ("ingest", "typed") and status.get(c["cid"]) == "accepted":  # kept facts from files or typed
            review.accept(draft, edited(c, edits), c["cid"])  # the review step's rule
    keys = [(r, r.get("key")) for r in draft["roles"]]  # the keys a profile set (logos and chapters are found by them)
    review.merge_roles(draft)  # a company typed twice is one entry (it rewrites every key to the company's name)
    for r, key in keys:  # every role that had a key
        if key:  # merge_roles replaced it with the company name
            r["key"] = key  # the profile's own key wins: profile_loader.js finds logos by it
    return draft, evidence_map(draft, tags, texts, details)  # the profile the generators read, and where each fact went


def evidence_map(draft: dict, tags: dict, texts: dict, details: dict) -> dict:
    """Place in the profile -> fact ids, for every item a kept fact made. "details:<field>" marks the person's own words."""
    out: dict[str, list] = {}  # place -> fact ids, in profile order
    add = lambda place, cid: out.setdefault(place, []).append(cid) if cid and cid not in out.get(place, []) else None  # once per place
    for ri, r in enumerate(draft.get("roles") or []):  # employers
        add(f"roles.{ri}", tags.get(id(r)) or r.get("cand"))  # the role's own card, or the file fact that made it
        for c in (r.get("filled") or {}):  # file facts that filled its title or dates
            add(f"roles.{ri}", c)  # they rest on it too
        for pi, pr in enumerate(r.get("projects") or []):  # its projects
            add(f"roles.{ri}.projects.{pi}", tags.get(id(pr)) or pr.get("cand"))  # imported or read from a file
    for ei, e in enumerate(draft.get("education") or []):  # schools
        add(f"education.{ei}", tags.get(id(e)) or e.get("cand"))  # imported or read from a file
    for si, sk in enumerate(draft.get("skills") or []):  # skill groups
        add(f"skills.{si}", tags.get(id(sk)))  # an imported group
        for owners in (sk.get("cand_items") or {}).values():  # skills read from files, each with the facts that named it
            for c in owners:  # every fact that named one of its skills
                add(f"skills.{si}", c)  # the group rests on it
    for si, sec in enumerate(draft.get("sections") or []):  # certificates, awards and other lists
        add(f"sections.{si}", tags.get(id(sec)))  # a text body rests on the section's own card
        items = sec.get("items") or []  # its lines
        by_text = {t: c for c, t in (sec.get("cand_text") or {}).items()}  # lines read from files
        for ii, it in enumerate(items):  # each line
            if isinstance(it, str):  # plain lines; richer shapes (groups of lines) rest on the section's own card
                add(f"sections.{si}.items.{ii}", texts.get((id(items), it)) or by_text.get(it))  # imported or read from a file
    summ = draft.get("summary") if isinstance(draft.get("summary"), dict) else {}  # the summary block
    for key in ("cards", "highlights", "layers"):  # summary lists (plain or per language)
        rows = summ.get(key)  # the list or {ko, en}
        for lang, lst in ((("ko", rows.get("ko")), ("en", rows.get("en"))) if isinstance(rows, dict) else ((None, rows),)):  # each language's list
            for i, row in enumerate(lst if isinstance(lst, list) else []):  # each row
                add(f"summary.{key}.{i}" + (f".{lang}" if lang == "en" else ""), tags.get(id(row)))  # the Korean list is the main one
    for key in ("competencies", "about"):  # top-level lists
        rows = draft.get(key)  # the list or {ko, en}
        lst = rows.get("ko") if isinstance(rows, dict) else rows  # the main list
        for i, row in enumerate(lst if isinstance(lst, list) else []):  # each row
            add(f"{key}.{i}", tags.get(id(row)))  # imported
        for i, row in enumerate(rows.get("en") if isinstance(rows, dict) and isinstance(rows.get("en"), list) else []):  # an English list
            add(f"{key}.{i}.en", tags.get(id(row)))  # its own facts, when it was written apart (the English edition looks here first)
    mot = draft.get("motivation")  # why this role
    if mot:  # only when there is one
        add("motivation", tags.get(id(mot)) if isinstance(mot, (dict, list)) else texts.get((id(draft), mot)))  # imported
    for k in ("headline", "intro"):  # the person's own words
        if k in details:  # typed or taken from an imported profile
            add(f"summary.{k}", f"details:{k}")  # the person vouches for them
    return out  # written beside the profile


def problems(draft: dict) -> list[str]:
    """What stops a resume from being made, as codes the panel words in either language."""
    out = []  # codes
    p = draft.get("person") or {}  # who
    if not str(p.get("name") or "").strip():  # a resume needs a name
        out.append("name_missing")  # the band offers 'Your details'
    if not str(p.get("email") or "").strip():  # and an email
        out.append("email_missing")  # the band offers 'Your details'
    if not draft.get("roles"):  # and at least one job held
        out.append("no_roles")  # the band offers the profile
    return out  # codes, worded by the page


class Facts:
    """The facts of one workspace: reading and changing them, and rebuilding the profile after every change."""

    def __init__(self, ws: Workspace):
        self.ws = ws  # the workspace

    # the files
    def candidates(self) -> list:
        kept = read_json(self.ws.path("sources", "candidates.json"), {"kept": []}).get("kept", [])  # the list
        return [as_read_now(c) for c in kept]  # a text an older reading stored as a dict written out, as a reading now gives it

    def status(self) -> dict:
        return read_json(self.ws.path("sources", "review.json"), {})  # cid -> accepted | rejected

    def edits(self) -> dict:
        return read_json(self.ws.path("sources", "edits.json"), {})  # cid -> edited fields

    def details(self) -> dict:
        return read_json(self.ws.path("profile", "details.json"), {})  # the person's own fields

    def base(self) -> dict | None:
        return read_json(self.ws.path("profile", "base.json"), None)  # the imported profile, if any

    def profile(self) -> dict:
        """The profile as last built (built now when it was never written)."""
        p = read_json(self.ws.path("profile", "profile.json"), None)  # the file
        if isinstance(p, dict):  # built before
            return p  # as it is
        with self.ws.lock:  # a page's read and a task may both find it missing: one builds it
            p = read_json(self.ws.path("profile", "profile.json"), None)  # built meanwhile by the other one?
            return p if isinstance(p, dict) else self.rebuild()  # built once when it was never written

    def rebuild(self) -> dict:
        """Build profile/profile.json and its evidence map from the fact files. Called inside every change, so undo
        restores all of them together."""
        draft, evmap = build_with_evidence(self.base(), self.candidates(), self.status(), self.edits(), self.details())  # the profile
        write_json(self.ws.path("profile", "profile.json"), draft)  # saved beside its sources
        write_json(self.ws.path("profile", "evidence.json"), evmap)  # where each fact went, for the canvas
        return draft  # for the caller, already saved

    def evidence(self) -> dict:
        """The evidence map of the profile as last built (built now when it was never written)."""
        m = read_json(self.ws.path("profile", "evidence.json"), None)  # the file
        if not isinstance(m, dict):  # an older workspace, or never built
            with self.ws.lock:  # one builder at a time
                m = read_json(self.ws.path("profile", "evidence.json"), None)  # built meanwhile?
                if not isinstance(m, dict):  # still missing
                    self.rebuild()  # writes both files
                    m = read_json(self.ws.path("profile", "evidence.json"), {})  # now it is there
        return m  # place -> fact ids

    def locks(self) -> dict:
        """Locked sentences: sentence id -> the text it was locked with."""
        return read_json(self.ws.path("sources", "locks.json"), {})  # empty when none

    def set_lock(self, sid: str, text: str | None) -> None:
        """Lock a sentence with its text, or unlock it (None)."""
        locks = self.locks()  # current
        if text is None:  # unlock
            locks.pop(sid, None)  # forgotten
        else:  # lock
            locks[sid] = str(text)[:2000]  # kept with its words
        write_json(self.ws.path("sources", "locks.json"), locks)  # saved

    def _save_cands(self, kept: list, dropped: list | None = None) -> None:
        """Write the candidate list (dropped ones kept for the record)."""
        old = read_json(self.ws.path("sources", "candidates.json"), {"kept": [], "dropped": []})  # what is there
        write_json(self.ws.path("sources", "candidates.json"),  # the list, with the record of dropped ones
                   {"kept": kept, "dropped": (old.get("dropped") or []) + (dropped or [])})  # saved

    def add_candidates(self, new: list, dropped: list | None = None) -> int:
        """Add candidates that are not there yet (by id). Returns how many were new."""
        kept = self.candidates()  # existing
        seen = {c["cid"] for c in kept}  # their ids
        fresh = [c for c in new if c["cid"] not in seen]  # only new ones
        self._save_cands(kept + fresh, dropped)  # appended in reading order
        return len(fresh)  # how many were new

    def import_profile(self, doc: dict, material: str, name: str) -> int:
        """Use an Offerowl profile file as material: its items become facts to confirm, and its own fields fill
        "Your details" where they are empty. A second profile file replaces the first one's items."""
        base, cands = import_profile(doc, material, name)  # base and its items
        kept = [c for c in self.candidates() if c.get("origin") != "profile"]  # facts from other files stay
        self._save_cands(kept + cands)  # the new items after them
        write_json(self.ws.path("profile", "base.json"), base)  # the profile they point into
        det = self.details()  # what the person typed
        where = det.get("_src") if isinstance(det.get("_src"), dict) else {}  # field -> where it came from
        for k, v in details_from(doc).items():  # fill only what is empty
            if v and not det.get(k):  # only what the person left empty
                det[k] = v  # from the profile file
                where[k] = {"file": name, "material": material, "quote": v}  # the file's own value is its evidence
        det["_src"] = where
        write_json(self.ws.path("profile", "details.json"), det)  # saved
        return len(cands)  # how many items it gave

    def ingest_candidates(self, kept: list, material_of) -> list:
        """src/ingest.py's kept candidates as panel candidates: their id is review.cid(), and their source names the
        material, not a path (no file paths on screen)."""
        out = []  # converted
        for c in kept:  # each fact found
            src = c.get("source") or {}  # {"file": path, "offset": n}
            mid, name = material_of(src.get("file", ""))  # which material it came from
            out.append({**{k: c.get(k, "") for k in ("kind", "org", "period", "title", "statement", "quote")},  # the fields a card shows
                        "cid": review.cid(c), "origin": "ingest", "org_key": c.get("org_key", ""),  # the same id rule as the review step
                        "source": {"material": mid, "name": name, "offset": src.get("offset", 0),  # a material and a name, never a path
                                   "more": max(0, len(c.get("sources") or []) - 1)}})  # the same fact elsewhere too
        return out  # in reading order

    def set_status(self, cid: str, value: str | None) -> None:
        """Keep, drop, or put back to 'to confirm' (None)."""
        st = self.status()  # current
        if value is None:  # back to 'to confirm'
            st.pop(cid, None)  # to confirm again
        else:
            st[cid] = value  # accepted or rejected
        write_json(self.ws.path("sources", "review.json"), st)  # saved

    def set_edit(self, cid: str, fields: dict) -> None:
        """The person's version of a fact (only the shown fields)."""
        ed = self.edits()  # current
        clean = {k: str(v)[:2000] for k, v in fields.items() if k in ("kind", "org", "period", "title", "statement")}  # bounded
        if isinstance(fields.get("rows"), list):  # a key project card's rows, edited on the canvas
            clean["rows"] = [[str(x)[:600] for x in r][:3] for r in fields["rows"] if isinstance(r, (list, tuple))][:8]  # bounded rows
        if clean:  # nothing to save otherwise
            ed[cid] = {**ed.get(cid, {}), **clean}  # merged with earlier edits
        write_json(self.ws.path("sources", "edits.json"), ed)  # saved

    def set_details(self, fields: dict, src: dict | None = None) -> None:
        """The person's own fields, with where each came from: src names a file and its words for fields a run found in the
        files; without it the person typed them, and the field's source says so ("_src", shown beside "Your details")."""
        det = read_json(self.ws.path("profile", "details.json"), {})  # this workspace's own file (an edition's holds only its own words)
        got = {k: str(v)[:4000] for k, v in fields.items() if k in DETAIL_KEYS}  # known fields only
        det.update(got)  # the values
        where = det.get("_src") if isinstance(det.get("_src"), dict) else {}  # field -> its source
        for k in got:  # each field set now
            where[k] = (src or {}).get(k) or {"typed": True}  # from a file, or typed by the person
        det["_src"] = where
        write_json(self.ws.path("profile", "details.json"), det)  # saved

    def add_typed(self, fields: dict) -> str:
        """A fact the person typed: its own quote, kept at once (they wrote it)."""
        c = {k: str(fields.get(k) or "")[:2000] for k in ("kind", "org", "period", "title", "statement")}  # the fields
        if c["kind"] not in ("role", "project", "education", "skill", "paper", "patent", "award", "certificate", "other"):  # only the kinds the review rules know
            c["kind"] = "other"  # unknown kinds are listed as other
        c.update(origin="typed", quote=c["statement"] or c["title"], source={"material": "", "name": ""})  # typed by them
        c["cid"] = review.cid(c)  # the same id rule as ingested facts
        self.add_candidates([c])  # listed
        self.set_status(c["cid"], "accepted")  # kept
        return c["cid"]  # the new fact's id

    def view(self) -> dict:
        """The facts as the panel shows them: each candidate with its state and edits, and the counts."""
        st, ed = self.status(), self.edits()  # states and edits
        rows = []  # one per candidate
        for c in self.candidates():  # in reading order
            e = ed.get(c["cid"]) or {}  # edited fields
            rows.append({k: c.get(k) for k in ("cid", "origin", "kind", "org", "period", "title", "statement", "quote")}  # the fields a card shows
                        | {"source": {k: (c.get("source") or {}).get(k) for k in ("material", "name", "more")},  # where it came from, by name only
                           "status": st.get(c["cid"], ""), "edited": bool(e), "edit": e})  # kept, dropped or to confirm, and edits
        counts = {"found": len(rows), "kept": sum(r["status"] == "accepted" for r in rows),  # the totals the profile view shows
                  "dropped": sum(r["status"] == "rejected" for r in rows)}  # totals
        counts["to_confirm"] = counts["found"] - counts["kept"] - counts["dropped"]  # the rest
        return {"rows": rows, "counts": counts}  # everything the profile view draws


class OwnFacts(Facts):
    """An application's own edition: the facts of a resume the person already wrote for that job, brought in whole and kept
    in the job's folder (jobs/<job>/own/, a workspace of its own) apart from the profile. The person is the same, so who they
    are (PERSON_KEYS) comes from the profile; what this edition says of them (its tagline, headline, introduction) is its own."""

    def __init__(self, ws: Workspace, main: Facts):
        super().__init__(ws)  # its own profile, evidence and decisions
        self.main = main  # the profile's facts

    def details(self) -> dict:
        main, own = self.main.details(), super().details()  # the person, as typed once; this edition's own words
        out = {**own, **{k: main[k] for k in PERSON_KEYS if main.get(k)}}  # this edition's words, the person's name and ways to reach them
        mine = own.get("_src") if isinstance(own.get("_src"), dict) else {}  # where this edition's words came from
        theirs = main.get("_src") if isinstance(main.get("_src"), dict) else {}  # where the person's came from
        where = {**mine, **{k: v for k, v in theirs.items() if k in PERSON_KEYS and main.get(k)}}  # each borrowed field with its own source
        if where:
            out["_src"] = where
        return out

    def set_details(self, fields: dict, src: dict | None = None) -> None:
        person = {k: v for k, v in fields.items() if k in PERSON_KEYS}  # typed once, for every edition
        if person:
            self.main.set_details(person, src)  # with where a run found them
        mine = {k: v for k, v in fields.items() if k not in PERSON_KEYS}  # this edition's own words
        if mine:
            super().set_details(mine, src)
