"""A drafted resume, kept with its job: the sentences src/write_resume.py wrote from the person's evidence.

The facts stay the one source of what is true. A draft owns only the sentences it wrote: the headline, the introduction,
the cards and key projects, the competencies, the about-me, the motivation, each project's title and summary, and each
company line. Names, dates, schools and skills always come from the facts, so a fixed date reaches a drafted resume too.

    workspace/jobs/<job>/draft.json          the profile the draft returned, with an "evidence" list and "_locks"
    workspace/jobs/<job>/draft.record.json   what the run did: its counts, for the page

A job without a draft of its own uses the general edition's, which is a resume with no posting in mind.

The draft's "evidence" list has one link per sentence: {at, lang, text, ev, names}. The canvas finds a sentence's link by
its words, since a drafted summary is several linked sentences joined into one field. An edit changes the words in both
places and marks the link, and the same checks that passed the draft then look at the new words.
"""
from __future__ import annotations

import copy  # a draft is never changed by reading it
import hashlib  # which facts a draft was written from
import json  # the same hash as src/write_resume.py
import re  # sentence ids
import sys  # the engine on the import path
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules

from .workspace import read_json  # noqa: E402  the job's files

GENERAL = "-general"  # the folder of the edition with no job (app.py has the same name)
FIGURE_KEYS = ("figure", "figures", "pages")  # what the figure step adds to a project
CARD_HEADS = {"ko": {"decision": "한 일", "result": "결과"}, "en": {"decision": "What I did", "result": "Result"}}  # the deck's card heads, by the part of a sentence
PROJECT = re.compile(r"^roles\.(\d+)\.projects\.(\d+)\.summary(?:\.s(\d+))?$")  # one sentence of a project's summary


def files(job: str) -> list[str]:
    """The workspace paths of a job's draft, for one undo step."""
    return [f"jobs/{job}/draft.json", f"jobs/{job}/draft.record.json"]  # both go back together


def load(tasks, job: str | None) -> tuple[dict | None, str | None]:
    """(the draft this job draws, the job it belongs to): the job's own, else the general edition's, else (None, None).
    A job with its own edition (a resume the person wrote for it, brought in whole) draws none: it prints as written."""
    if job and getattr(tasks, "own_dir", None) and tasks.own_dir(job) is not None:  # the person's own edition
        return None, None
    for owner in ([job] if job and job != GENERAL else []) + [GENERAL]:  # its own first
        d = read_json(tasks.ws.job_dir(owner) / "draft.json", None)  # the file
        if isinstance(d, dict) and d.get("_draft"):  # a real draft
            return d, owner  # found
    return None, None  # no draft: the canvas draws the facts


def _is_draft(path: Path) -> bool:
    """The file holds a real draft (load's test), read whole: owner remembers the answer while the file is unchanged."""
    d = read_json(path, None)
    return isinstance(d, dict) and bool(d.get("_draft"))


def owner(tasks, job: str | None) -> str | None:
    """The job whose draft this job draws, as load() decides it, without reading the drafts again: the state asks this for
    every job and language at every poll, and a draft is tens of kilobytes. Each file's answer is kept while its stamp holds
    (a file written this very moment is read again)."""
    from .stamps import _cached  # the memory keyed by a file's stamp
    if job and getattr(tasks, "own_dir", None) and tasks.own_dir(job) is not None:  # the person's own edition: none
        return None
    for o in ([job] if job and job != GENERAL else []) + [GENERAL]:  # its own first, as load() looks
        if _cached("draft", tasks.ws.job_dir(o) / "draft.json", _is_draft):
            return o
    return None


def summary(tasks, owner: str, stale: bool, job: str | None) -> dict:
    """What the page says about a draft: when it was written, for which job, its counts, and whether the facts moved on."""
    rec = read_json(tasks.ws.job_dir(owner) / "draft.record.json", {}) or {}  # what the run did
    d = read_json(tasks.ws.job_dir(owner) / "draft.json", {}) or {}  # the draft itself
    return {"at": rec.get("at") or "", "general": owner == GENERAL, "own": owner == (job or GENERAL), "stale": stale, "counts": rec.get("counts") or {},  # for the band and the inspector
            "figures": has_figures(d), "drawn": rec.get("figures") or {}}  # whether the deck has its figures yet, and what that run did


def base_hash(profile: dict) -> str:
    """The hash src/write_resume.py keeps of the profile a draft was written from."""
    return hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]  # the same recipe


def with_ids(profile: dict) -> dict:
    """A copy of the profile whose projects all have an id. A project without one is named by its place, and a draft moves
    projects, so the name would stop meaning that project."""
    import write_resume as W  # the id rule of the draft
    out = copy.deepcopy(profile)  # never change the facts' profile
    for ri, r in enumerate(out.get("roles") or [], 1):  # each role
        if not isinstance(r, dict):  # a broken entry
            continue  # skipped by the draft too
        rk = W.role_key(r, ri)  # its key
        for pi, p in enumerate(r.get("projects") or [], 1):  # each project
            if isinstance(p, dict) and not p.get("id"):  # named by its place so far
                p["id"] = W.project_id(p, rk, pi)  # fixed now
    return out  # the profile to draft from


def wrote(draft: dict) -> set[str]:
    """The fields the draft wrote, from its links ("summary.headline", "project.alpha-1.summary", ...)."""
    return {str(x.get("at")) for x in draft.get("evidence") or [] if isinstance(x, dict)}  # one name per field


def merged(base: dict, draft: dict) -> dict:
    """The profile the canvas and the typesetting read: the facts' profile (or its English translation) with the fields
    the draft wrote put in. A field the draft left alone stays the base's, in the base's language."""
    import write_resume as W  # the keys of roles and projects
    out, did = copy.deepcopy(base), wrote(draft)  # the base; the draft's fields
    S, D = out.setdefault("summary", {}), draft.get("summary") or {}  # the top of the resume
    if not isinstance(S, dict):  # a broken summary
        S = out["summary"] = {}  # replaced
    for key, mark in (("headline", "summary.headline"), ("intro", "summary.intro"), ("cards", "summary.cards."), ("highlights", "summary.highlights."),  # its parts
                      ("stats", "summary.stats."), ("focus", "summary.focus."), ("contents", "summary.contents"), ("glance", "summary.glance")):  # and the deck's opening slides
        if key in D and any(a == mark or a.startswith(mark) for a in did):  # the draft wrote it
            S[key] = D[key]  # both languages
    for key in ("competencies", "about", "motivation"):  # the other parts
        if key in draft and any(a == key or a.startswith(key + ".") for a in did):  # the draft wrote it
            out[key] = draft[key]  # both languages
    theirs = {W.role_key(r, i): r for i, r in enumerate(draft.get("roles") or [], 1) if isinstance(r, dict)}  # the draft's roles
    for ri, r in enumerate(out.get("roles") or [], 1):  # each role of the facts
        if not isinstance(r, dict):  # a broken entry
            continue  # left as it is
        rk = W.role_key(r, ri)  # its key
        dr = theirs.get(rk)  # the same role in the draft
        if not dr:  # a role added after the draft
            continue  # its own sentences stay
        if f"role.{rk}.desc" in did and dr.get("desc"):  # the company line
            r["desc"] = dr["desc"]  # both languages
        ps = [p for p in r.get("projects") or [] if isinstance(p, dict)]  # the facts' projects
        ids = {id(p): W.project_id(p, rk, pi) for pi, p in enumerate(ps, 1)}  # each one's id
        mine = {W.project_id(p, rk, pi): p for pi, p in enumerate(dr.get("projects") or [], 1) if isinstance(p, dict)}  # the draft's projects by id
        rank = {pid: k for k, pid in enumerate(mine)}  # the draft's order
        for p in ps:  # each project of the facts
            q = mine.get(ids[id(p)])  # the same project in the draft
            if not q:  # added after the draft
                continue  # it stays as it is
            if f"project.{ids[id(p)]}.summary" in did:  # drafted: its title and sentences
                for key in ("title", "summary", "short"):  # the fields of an item
                    if q.get(key):  # written
                        p[key] = q[key]  # both languages
                p.pop("resume", None)  # on the resume
                p.update(slide_parts(draft, ids[id(p)], q))  # its slide: the scope on top, the rest as cards
            elif q.get("resume") is False:  # the draft left it off the resume
                p["resume"] = False  # kept in the profile for later drafts
                p["deck"] = False  # the slides follow the resume: a slide needs the sentences only a printed project has
            for key in FIGURE_KEYS:  # figures the figure step drew, drafted project or not
                if q.get(key):  # drawn
                    p[key] = q[key]  # both languages
        if dr.get("journey") and any(a.startswith(f"role.{rk}.journey.") for a in did):  # the role's station on the deck's career path
            r["journey"] = dr["journey"]  # both languages
        if r.get("desc") and not r.get("lead"):  # the company line
            r["lead"] = r["desc"]  # the chapter divider says it too
        ps.sort(key=lambda p: rank.get(ids[id(p)], len(rank)))  # the draft's order, new projects after
        r["projects"] = ps  # the new order
    out["evidence"] = draft.get("evidence") or []  # every drafted sentence with its ids
    out["_draft"] = draft.get("_draft")  # how it was made
    return out  # what is drawn and printed


def slide_parts(draft: dict, pid: str, project: dict) -> dict:
    """A drafted project's slide, from the sentences that passed the checks: the scope as its lede, and what was done and what came of it
    as its cards. No model is asked, so a slide says only what the resume says."""
    from .evidence import sentences  # the same cut the canvas makes
    lede, cards = {}, {}  # per language
    summary = project.get("summary")  # one paragraph per language
    for lang, text in (summary.items() if isinstance(summary, dict) else []):  # each language written
        said = {plain(x.get("text")): x.get("part") for x in draft.get("evidence") or []  # each sentence's part
                if isinstance(x, dict) and x.get("lang") == lang and x.get("at") == f"project.{pid}.summary"}  # of this project, in this language
        cut = sentences(text)  # as printed, with their highlights
        known = any(said.get(plain(x)) for x in cut)  # a draft from before links named their parts has none
        groups: dict[str, list] = {}  # the sentences by part, in order
        for k, x in enumerate(cut):  # each sentence
            kind = said.get(plain(x)) or "decision"  # a sentence edited since keeps to "decision"
            if not known:  # sentences come in the order scope, decision, result
                kind = "scope" if k == 0 else "result" if k == len(cut) - 1 and k >= 2 else "decision"  # by its place
            groups.setdefault(kind, []).append(x)  # kept in order
        heads = CARD_HEADS.get(lang, CARD_HEADS["en"])  # the card heads
        rows = [[heads[k], " ".join(groups[k])] for k in ("decision", "result") if groups.get(k)]  # what was done, what came of it
        if groups.get("scope") and rows:  # the scope on top, the cards under it
            lede[lang], cards[lang] = " ".join(groups["scope"]), rows  # a slide with a lede and cards
        elif len(rows) > 1:  # no scope: the first card leads
            lede[lang], cards[lang] = rows[0][1], rows[1:]  # the rest stay cards
    if not cards:  # a project of one sentence keeps its summary as the lede
        return {}
    for lang, text in (summary.items() if isinstance(summary, dict) else []):  # a language whose sentences did not split (one was dropped by a check, say)
        if lang not in cards and str(text or "").strip():  # its slide would have no words in that language, and its edition would stop
            lede[lang], cards[lang] = text, []  # its whole summary leads, with no cards
    return {"lede": lede, "cards": cards}  # every language of the summary has its slide


def moved(evmap: dict, base: dict, merged_profile: dict) -> dict:
    """The evidence map with each project under its place in the merged profile (a draft moves projects)."""
    out = dict(evmap)  # the other places stay
    for ri, r in enumerate(merged_profile.get("roles") or []):  # each role
        was = ((base.get("roles") or [])[ri:ri + 1] or [{}])[0]  # the same role in the base
        where = {p.get("id"): pi for pi, p in enumerate(was.get("projects") or []) if isinstance(p, dict)}  # where each project was
        for pi, p in enumerate(r.get("projects") or [] if isinstance(r, dict) else []):  # where each project is now
            old = where.get(p.get("id")) if isinstance(p, dict) else None  # its old place
            if old is not None:  # the map knows it
                out[f"roles.{ri}.projects.{pi}"] = evmap.get(f"roles.{ri}.projects.{old}") or []  # its facts follow it
    return out  # keyed by the new places


def plain(text) -> str:
    """A sentence's words for comparing: no marks, one space, no end mark."""
    return re.sub(r"\s+", " ", str(text or "").replace("==", "")).strip().rstrip(".").strip()  # the same text however it was joined


def links_of(draft: dict | None, lang: str) -> dict[str, dict]:
    """The sentences of one language by their words."""
    return {plain(x.get("text")): x for x in (draft or {}).get("evidence") or [] if isinstance(x, dict) and x.get("lang") == lang}  # later ones win


def link_for(links: dict[str, dict], text: str) -> dict | None:
    """The link of a sentence as the canvas cut it. An introduction is one linked text of several sentences, so a sentence
    may be a part of its link's words. Short words are no sign of that."""
    words = plain(text)  # as compared
    if words in links:  # the usual case
        return links[words]  # exact
    if len(words) < 12:  # a word or two could sit anywhere
        return None  # not drafted
    return next((x for k, x in links.items() if words in k), None)  # the longer text that holds it


def spot(draft: dict, merged_profile: dict, sid: str, lang: str):
    """Where a sentence's words live in the stored draft: (container, key, sentence number or None), or None for a
    sentence the draft does not own."""
    S = draft.get("summary") or {}  # the top of the resume
    m = PROJECT.match(sid)  # a project's sentence
    if m:  # found by its id, since the place may differ between the two profiles
        ri, pi, n = int(m.group(1)), int(m.group(2)), m.group(3)  # role, project, sentence
        try:
            pid = merged_profile["roles"][ri]["projects"][pi].get("id")  # which project
            ps = draft["roles"][ri]["projects"]  # the draft's projects of that role
        except (KeyError, IndexError, TypeError, AttributeError):  # a stale page
            return None  # not one of the draft's
        for p in ps:  # find it
            if isinstance(p, dict) and p.get("id") == pid and isinstance(p.get("summary"), (dict, str)):  # the same project
                return p, "summary", int(n) if n is not None else None  # its summary
        return None  # the draft does not have it
    m = re.match(r"^summary\.(headline|intro)(?:\.s(\d+))?$", sid)  # one text of the top
    if m and m.group(1) in S:  # the headline or the introduction
        return S, m.group(1), int(m.group(2)) if m.group(2) is not None else None  # its field
    m = re.match(r"^summary\.cards\.(\d+)$", sid)  # one card
    if m:  # cards are [title, text] per language
        rows = S.get("cards", {}).get(lang) if isinstance(S.get("cards"), dict) else None  # this language's cards
        return (rows[int(m.group(1))], 1, None) if rows and int(m.group(1)) < len(rows) else None  # the text cell
    m = re.match(r"^summary\.highlights\.(\d+)\.rows\.(\d+)$", sid)  # one row of a key project
    if m:  # rows are [label, text]
        cards = S.get("highlights", {}).get(lang) if isinstance(S.get("highlights"), dict) else None  # this language's cards
        rows = cards[int(m.group(1))].get("rows") if cards and int(m.group(1)) < len(cards) else None  # that card's rows
        return (rows[int(m.group(2))], 1, None) if rows and int(m.group(2)) < len(rows) else None  # the text cell
    m = re.match(r"^competencies\.(\d+)$", sid)  # one competency
    if m:  # {name, text} per language
        rows = draft.get("competencies", {}).get(lang) if isinstance(draft.get("competencies"), dict) else None  # this language's
        return (rows[int(m.group(1))], "text", None) if rows and int(m.group(1)) < len(rows) else None  # its text
    m = re.match(r"^about\.(\d+)(?:\.s(\d+))?$", sid)  # one sentence of the about-me
    if m:  # [title, text] per language; the quote box is a dict and has no such id
        rows = draft.get("about", {}).get(lang) if isinstance(draft.get("about"), dict) else None  # this language's
        k = int(m.group(1))  # which section
        return (rows[k], 1, int(m.group(2)) if m.group(2) is not None else None) if rows and k < len(rows) and isinstance(rows[k], list) else None  # its text
    m = re.match(r"^motivation(?:\.s(\d+))?$", sid)  # one sentence of the motivation
    if m and "motivation" in draft:  # one paragraph per language
        return draft, "motivation", int(m.group(1)) if m.group(1) is not None else None  # its field
    return None  # names, dates and lists belong to the facts


def _read(box, key, lang: str) -> str:
    """The text at a spot, in this language."""
    v = box[key]  # a plain text or one per language
    return str(v.get(lang) or "") if isinstance(v, dict) else str(v or "")  # this language's


def _write(box, key, lang: str, text: str) -> None:
    """The text at a spot, in this language."""
    if isinstance(box[key], dict):  # one per language
        box[key][lang] = text  # only this language changes
    else:  # plain
        box[key] = text  # the one text


def put_sentence(draft: dict, merged_profile: dict, sid: str, lang: str, new: str, replaced) -> bool:
    """Write new words for a sentence into the stored draft, and into its link. False when the draft does not own it.
    `replaced` is evidence.replaced: a paragraph with one sentence changed."""
    at = spot(draft, merged_profile, sid, lang)  # where it lives
    if at is None:  # a fact's words
        return False  # the caller edits the fact
    box, key, n = at  # the place
    old = _read(box, key, lang)  # the paragraph as it is
    parts = None  # the sentence being replaced
    if n is not None:  # one sentence of a paragraph
        from .evidence import sentences  # the same cut the canvas makes
        parts = sentences(old)  # its sentences
    before = parts[n] if parts and n < len(parts) else old  # the words being replaced
    if parts and n < len(parts) - 1 and not re.search(r"[.!?]$", new.replace("==", "").strip()):  # a sentence with others after it
        new = new.strip() + "."  # with no end mark it would run into the next one, and the sentence numbers would shift
    _write(box, key, lang, replaced(old, n, new))  # the paragraph with the new sentence
    from .evidence import sentences as cut  # the same cut the canvas makes
    link = own_link(draft, lang, before, sid, merged_profile)  # its link
    if link is not None:  # a drafted sentence keeps its evidence ids
        pieces = [x.replace("==", "") for x in cut(new)] if n is not None else [new.replace("==", "")]  # new words may be more than one sentence
        if plain(link.get("text")) != plain(before):  # one sentence of a longer linked text: the rest of it stays
            old_words = before.replace("==", "").strip()  # as the link holds it
            pieces = [str(link.get("text")).replace(old_words, " ".join(pieces))]  # the new words in their place
        link["text"], link["edited"] = pieces[0] if pieces else "", True  # the same checks look at it again
        for more in pieces[1:]:  # the other sentences rest on the same ids
            draft.setdefault("evidence", []).append({**link, "text": more})  # the canvas finds each by its words
    return True  # written


def own_link(draft: dict, lang: str, text: str, sid: str, merged_profile: dict) -> dict | None:
    """The link of one sentence. Two fields may say the same words (a headline and a project's first line), so the field decides."""
    field = {"motivation": "motivation", "competencies": "competencies.", "about": "about.", "summary": "summary."}.get(sid.split(".")[0], "")  # the part
    m = PROJECT.match(sid)  # a project's sentence
    if m:  # named by its project
        try:
            field = f"project.{merged_profile['roles'][int(m.group(1))]['projects'][int(m.group(2))].get('id')}.summary"  # its field
        except (KeyError, IndexError, TypeError, AttributeError):  # a stale page
            field = "project."  # any project
    mine = [x for x in draft.get("evidence") or [] if isinstance(x, dict) and x.get("lang") == lang]  # this language's
    same = [x for x in mine if plain(x.get("text")) == plain(text)] or [x for x in mine if len(plain(text)) >= 12 and plain(text) in plain(x.get("text"))]  # the same words, else the text that holds them
    return next((x for x in same if str(x.get("at") or "").startswith(field)), same[0] if same else None)  # its own field first


def same_place(sid: str, before: dict, after: dict) -> str | None:
    """A sentence's id in another profile: a project's sentences follow the project, the others keep their place."""
    m = PROJECT.match(sid)  # a project's sentence
    if not m:  # the summary, the competencies and so on
        return sid  # the same place
    ri, pi = int(m.group(1)), int(m.group(2))  # role and project
    try:
        pid = before["roles"][ri]["projects"][pi].get("id")  # which project
        for k, p in enumerate(after["roles"][ri]["projects"]):  # find it again
            if isinstance(p, dict) and p.get("id") == pid and p.get("resume") is not False:  # still printed
                return f"roles.{ri}.projects.{k}.summary" + (f".s{m.group(3)}" if m.group(3) is not None else "")  # its new id
    except (KeyError, IndexError, TypeError, AttributeError):  # the role or the project is gone
        return None  # nowhere to put it
    return None  # the new draft left the project off


def carry_figures(new: dict, *others) -> None:
    """Figures already drawn stay through a new draft: from the same job's last draft, else from the general edition's, by project."""
    drawn = {}  # project id -> its figure fields
    for d in others:  # the last draft first
        for r in (d or {}).get("roles") or []:  # each role
            for p in r.get("projects") or [] if isinstance(r, dict) else []:  # each project
                if isinstance(p, dict) and any(p.get(k) for k in FIGURE_KEYS):  # with figures
                    drawn.setdefault(p.get("id"), {k: p[k] for k in FIGURE_KEYS if p.get(k)})  # the first one found wins
    for r in new.get("roles") or []:  # the new draft's roles
        for p in r.get("projects") or [] if isinstance(r, dict) else []:  # and projects
            if isinstance(p, dict) and p.get("id") in drawn and p.get("resume") is not False:  # drawn before, and printed now
                p.update(drawn[p["id"]])  # kept


def has_figures(draft: dict | None) -> bool:
    """Has the figure step drawn anything for this draft?"""
    return any(isinstance(p, dict) and any(p.get(k) for k in FIGURE_KEYS) for r in (draft or {}).get("roles") or [] for p in (r.get("projects") or [] if isinstance(r, dict) else []))  # any project


def carry_locks(locks: dict, before: dict, old_links: dict, new: dict, base: dict, lang: str, replaced) -> dict:
    """Locked sentences of one language keep their words in a new draft. Returns {new id: words}. A lock whose place is gone
    is dropped, since nothing in the new resume says that any more."""
    kept = {}  # the locks of the new draft
    now = merged(base, new)  # the new profile, for the new ids
    for sid, text in (locks or {}).items():  # each lock
        target = same_place(sid, before, now)  # where it goes now
        if not target:  # the new draft has no such place
            continue  # the lock goes with it
        try:
            done = put_sentence(new, now, target, lang, str(text), replaced)  # its words
        except ValueError:  # the new paragraph has fewer sentences
            continue  # nowhere to put it
        if done:  # written
            link = old_links.get(plain(text))  # the evidence it had
            mine = links_of(new, lang).get(plain(text))  # the link put_sentence kept
            if mine is None:  # it replaced a sentence with another link, or none
                mine = {**(link or {"at": "locked", "names": {}, "typed": True, "ev": []}), "lang": lang, "text": str(text).replace("==", "")}  # its own link
                new.setdefault("evidence", []).append(mine)  # the canvas finds it by its words
            if link is not None:  # the ids that backed it
                mine["ev"], mine["names"] = link.get("ev") or [], link.get("names") or {}  # kept
            kept[target] = text  # still locked
    return kept  # the new draft's locks
