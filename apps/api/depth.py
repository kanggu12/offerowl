"""The depth review of an edition (src/depth_review.py), kept with its job, and what the person does with each finding.

A review reads each project item the edition prints and each page of its last deck, and says what each leaves out: what
made the work hard, the alternative set aside, why the result came about, the names the evidence holds, and what the copy
that last went out said. Each unit the agent read has a verdict (strong, adequate or thin, by the core parts its words
state), and thin units come first: their missing parts are the procedure's gate. Each finding offers a rewrite that cites
the item's evidence (it passed the draft's own checks) or a question for the person. Nothing here changes a document by
itself, and no finding stops an export.

    workspace/jobs/<job>/depth.<lang>.json    the edition's last review in that language (a review writes only this file)
    workspace/jobs/<job>/depth.<lang>.acts.json   what the person did with each finding: used, answered, left (the undo steps
                                               take back this file, never a review)
    GET  /api/v1/jobs/<job>/depth?lang=ko      the review, thin units first, each marked when its words changed since
    POST /api/v1/jobs/depth                    {job, lang}: review the edition again (task depth:<job>)
    POST /api/v1/jobs/depth/answer             {job, lang, finding, text}: the person's answer, kept as a fact of that project
    POST /api/v1/jobs/depth/apply              {job, lang, finding}: the rewrite in place of the sentence it replaces
    POST /api/v1/jobs/depth/leave              {job, lang, finding}: left as it is, while the item's words stay the same
    offerowl depth review|show|answer|apply|leave <job> ...   the same routes from a shell, in this process (main below)

An answer goes through the fact flow: a typed fact of kind project that names its project, which the profile keeps as one
more line of that project's ledger (src/review.py accept), so the next draft can cite it and the canvas counts it as that
item's evidence. It never prints by itself: a deck page that names no project asks which project the answer belongs to, and
an answer whose project is gone is refused. A rewrite goes through the canvas's own sentence path: a drafted sentence's link takes the rewrite's ids, a
sentence of a fact records the entries it now rests on in the item's `evidence` list. Each is one undo step, with the review.
"""
from __future__ import annotations

import argparse  # the command line
import json  # the review's file and the answers printed
import uuid  # each review's own id, which the person's acts on it name
import logging  # the panel's log
import re  # the job named on the command line
import sys  # the streams the command line prints to
from pathlib import Path  # paths

if __package__ in (None, ""):  # started as a file: make the relative imports work
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repository root, which holds apps/
    __package__ = "apps.api"  # noqa: A001  the package this file belongs to
    __import__("apps.api")  # the package itself

from .facts import FACT_FILES, text_of  # noqa: E402  the fact files of one undo step, plain text
from .workspace import read_json, write_json  # noqa: E402  files

log = logging.getLogger("offerowl.panel")  # the panel's log
GENERAL = "-general"  # the edition with no job (app.py has the same name)
LANGS = ("ko", "en")  # the editions a job has
DEPTH_CALLS = 8  # model calls one review may take: a long career's items and a deck of thirty pages fit


# ---------------------------------------------------------------- where a review lives, and what it reads

def path(tasks, job: str, lang: str) -> Path:
    """The review's file."""
    return tasks.ws.job_dir(job) / f"depth.{lang}.json"  # beside the job's draft


def acts_rel(job: str, lang: str) -> str:
    """The acts file as the workspace names it (an answer's, a leave's and a rewrite's undo step takes it back)."""
    return f"jobs/{job}/depth.{lang}.acts.json"


def acts_path(tasks, job: str, lang: str) -> Path:
    """What the person did with each finding, apart from the review: a review that finishes meanwhile never writes over an act,
    and an undo of an act never brings back an older review."""
    return tasks.ws.job_dir(job) / f"depth.{lang}.acts.json"


def read_acts(tasks, job: str, lang: str) -> dict:
    """{finding id: act}: each act's state (applied, answered, left), the review it was made on (rid) and the words of its
    unit it holds for (hash), with an answer's fact and words."""
    got = read_json(acts_path(tasks, job, lang), None)  # the journal
    return got.get("acts") if isinstance(got, dict) and isinstance(got.get("acts"), dict) else {}  # a broken file holds no act


def put_act(tasks, job: str, lang: str, fid: str, act: dict) -> None:
    """One finding's act kept in the journal (inside the caller's undo step)."""
    acts = read_acts(tasks, job, lang)  # the acts so far
    acts[fid] = act  # this finding's, the latest
    write_json(acts_path(tasks, job, lang), {"schema": "offerowl-depth-acts/0.1", "acts": acts})


def with_acts(rec: dict, acts: dict) -> dict:
    """The review with the person's acts on it: an act holds on the review it was made on, and on a later review while its unit's
    words stay the ones it was made for (a gate answered or a sentence used stays done, as one left stays left)."""
    for u in rec.get("units") or []:  # every unit
        for f in u.get("findings") or []:  # every finding
            a = acts.get(f.get("id"))  # what the person did with it, if anything
            if isinstance(a, dict) and a.get("state") in ("applied", "answered", "left") and (a.get("rid") == rec.get("rid") or a.get("hash") == u.get("hash")):
                f["state"] = a["state"]  # done, as the person did it
                f.update({k: a[k] for k in ("fact", "answer") if a.get(k)})  # an answer's fact and words
    return rec


def place_of(prof: dict, pid: str) -> tuple[int, int] | None:
    """Where a project stands in a profile: (role number, project number), from 1, or None."""
    import write_resume as W  # the id rule
    for ri, r in enumerate(prof.get("roles") or [], 1):  # numbered from 1 as the draft numbers them
        for pi, q in enumerate((r.get("projects") or []) if isinstance(r, dict) else [], 1):
            if isinstance(q, dict) and W.project_id(q, W.role_key(r, ri), pi) == pid:  # the one
                return ri, pi
    return None


def source_project(tasks, job: str, lang: str, pid: str) -> tuple[str | None, dict | None, dict | None]:
    """(its id, its role, the project) in the facts this edition prints from, for a project id of the edition in this language.
    The same id first; an English edition translated from a Korean profile keeps every project at the same place, so its
    place finds the project the fact belongs to when the ids differ. (None, None, None) when the project is not there."""
    import write_resume as W  # the id rule
    src = tasks.facts_for(doc_job(job)).profile()  # the facts' own profile: where an answer's ledger line goes
    role, proj = project_of(src, pid)  # the same id
    if proj is not None:
        return pid, role, proj
    at = place_of(edition_profile(tasks, job, lang), pid)  # its place in the edition
    if at is None:  # not in the edition either: gone
        return None, None, None
    ri, pi = at
    roles = src.get("roles") or []
    r = roles[ri - 1] if ri - 1 < len(roles) and isinstance(roles[ri - 1], dict) else None  # the role at that place
    q = (r.get("projects") or [])[pi - 1] if r and pi - 1 < len(r.get("projects") or []) else None  # the project at that place
    if not isinstance(q, dict):  # the facts changed since
        return None, None, None
    return W.project_id(q, W.role_key(r, ri), pi), r, q


def doc_job(job: str) -> str | None:
    """The job as the documents' functions take it: the general edition is None there."""
    return None if job == GENERAL else job


def edition_profile(tasks, job: str, lang: str) -> dict:
    """The profile the edition prints in this language, its draft's sentences merged in, as the canvas draws it."""
    from . import documents  # the canvas's own reading
    prof, _translated = documents.profile_for(tasks, lang, doc_job(job))  # the facts' profile, its translation, or the job's own edition
    if prof is None:  # the English edition before its translation
        raise ValueError("needs_translation")  # the page offers the translation
    return documents.drawn(tasks, prof, lang, doc_job(job))["prof"]  # with the draft in force


def deck_pages(tasks, job: str, lang: str) -> tuple[list | None, str]:
    """The words of each page of the edition's last deck PDF, and when it was made; (None, "") when there is none or its
    text cannot be read (the review says it did not read the deck)."""
    out = tasks.build_dir(job, lang)  # the edition's folder
    pdf = out / "deck.pdf"  # its last deck
    if not pdf.is_file():  # never made
        return None, ""
    try:
        import depth_review as DR  # src/depth_review.py
        return DR.pages_of(pdf), str((read_json(out / "build.json", {}) or {}).get("at") or "")  # its pages, and the build's time
    except Exception as exc:  # noqa: BLE001  a PDF no reader here can read: the resume is still reviewed
        log.warning("deck of %s %s not read: %s", job, lang, exc)
        return None, ""


def went_out(tasks, job: str, lang: str) -> tuple[dict | None, dict | None]:
    """The profile of the copy of this edition that last went out, and {why, at}: the baseline an export or a lock kept
    (task_compare.keep_baseline keeps the profile beside the pages), or a lock's own frozen copy; the newer one when both."""
    found = []  # (at, why, profile)
    for blind in (False, True):  # the ordinary edition's baseline and the blind edition's
        d = tasks.baseline_dir(job, lang, blind)  # where it is kept
        rec, prof = read_json(d / "baseline.json", None), read_json(d / "profile.json", None)  # its record and its words
        if isinstance(rec, dict) and isinstance(prof, dict):  # a baseline that kept its words (0.11.0 and later)
            found.append((str(rec.get("at") or ""), str(rec.get("why") or "export"), prof))
    lock = (tasks.ws.job(job) or {}).get("locked") if job != GENERAL else None  # what a submitted application froze
    if isinstance(lock, dict) and lock.get("lang") == lang and lock.get("folder"):  # frozen in this language
        prof = read_json(tasks.ws.job_dir(job) / "submitted" / Path(str(lock["folder"])).name / "profile.json", None)  # never a path from the record
        if isinstance(prof, dict):
            found.append((str(lock.get("at") or ""), "submitted", prof))
    if not found:  # nothing went out yet
        return None, None
    at, why, prof = max(found, key=lambda x: x[0])  # the newest
    return prof, {"why": why, "at": at}


# ---------------------------------------------------------------- the review

def run(tasks, job: str, lang: str, ask=None, key: str | None = None) -> dict:
    """Review the edition now and keep it. Under the panel's one model task at a time when an agent is asked. Returns the
    review. Raises ValueError("needs_translation") for an English edition with no English profile yet."""
    import depth_review as DR  # src/depth_review.py
    import write_resume as W  # its style loader
    prof = edition_profile(tasks, job, lang)  # what the edition prints
    pages, deck_at = deck_pages(tasks, job, lang)  # its deck's words, when one was made
    old, out_info = went_out(tasks, job, lang)  # the copy that last went out
    style = W.load_style(tasks.style_spec())  # the person's rules, as every draft reads them
    if ask is None and tasks.card.chosen() == "none":  # no agent: the rule-based checks only, no lock to wait for
        rec = DR.review(prof, lang, style=style, pages=pages, old=old, backend="none")  # what the person did lives in the acts file, never here
    else:  # an agent is asked: one model task at a time
        with tasks.turn(key or f"depth:{job}", tasks.model_lock):  # the page says it waits its turn
            name = tasks.backend() if ask is None else "none"  # which agent; a test's stand-in answers instead
            rec = DR.review(prof, lang, style=style, pages=pages, old=old, ask=ask, backend=name, max_calls=DR.call_limit())  # the configured limit
    rec.update(job=job, deck_at=deck_at, went_out=out_info, rid=uuid.uuid4().hex[:12])  # which edition, which deck, what it was held against, and its own id
    write_json(path(tasks, job, lang), rec)  # kept with the job; a review is no undo step, as a build's record is none
    return rec


def summary(rec: dict) -> dict:
    """What a task's result says of a review: its counts, whether an agent read it, its calls and what it could not do."""
    return {"counts": rec.get("counts") or {}, "agent": rec.get("agent"), "calls": rec.get("calls"), "notes": rec.get("notes") or [], "lang": rec.get("lang")}


def view(tasks, job: str, lang: str) -> dict:
    """The kept review as the page reads it: {none: true} before the first one, else the review with its units thin first,
    each marked `changed` when its words are not the ones reviewed (written again since, or gone), `stale` when any is, and
    `now`: the findings still open and the thin units whose gate is still open, counted as the person acts on them."""
    import depth_review as DR  # the units and their words
    rec = read_json(path(tasks, job, lang), None)  # the kept review
    if not isinstance(rec, dict):  # never reviewed
        return {"none": True, "lang": lang, "job": job}
    try:
        items = DR.items_of(edition_profile(tasks, job, lang), lang)  # the items the edition prints now
    except ValueError:  # no profile in this language any more
        items = []
    now = {u["id"]: DR.short_hash(u.get("text")) for u in items}  # the items' words now
    rec["projects"] = [{"pid": u["pid"], "title": u.get("title", "")} for u in items]  # what an unpaired page's answer may belong to
    for u in rec.get("units") or []:  # each unit reviewed
        if u.get("kind") == "item":  # a deck page is read again with the next build
            u["changed"] = now.get(u["id"]) != u.get("hash")  # its words moved on since the review
    rec["stale"] = any(u.get("changed") for u in rec.get("units") or [])  # the page offers to review again
    with_acts(rec, read_acts(tasks, job, lang))  # what the person did with each finding, kept apart from the review
    rec["units"] = sorted(rec.get("units") or [], key=DR.order_key)  # thin first, whatever order the file kept
    rec["now"] = {"open": sum(1 for u in rec["units"] for f in u.get("findings") or [] if f.get("state") == "open"),  # what is left to act on
                  "gates": sum(1 for u in rec["units"] if DR.gate_open(u))}  # thin units with a missing part still open
    return rec


def find(rec: dict, fid: str) -> tuple[dict, dict]:
    """(the unit, the finding) of a finding's id, or ValueError("depth_finding")."""
    for u in rec.get("units") or []:  # every unit
        for f in u.get("findings") or []:  # every finding
            if f.get("id") == fid:  # the one asked for
                return u, f
    raise ValueError("depth_finding")  # a stale page, or a made-up id


def load(tasks, job: str, lang: str) -> dict:
    """The kept review with the person's acts on it, or ValueError("depth_none") before the first one."""
    rec = read_json(path(tasks, job, lang), None)  # the kept review
    if not isinstance(rec, dict):  # never reviewed
        raise ValueError("depth_none")
    return with_acts(rec, read_acts(tasks, job, lang))


def fact_rels(tasks, job: str) -> list:
    """The fact files of the facts this edition prints from, as the workspace names them: the profile's, or a job's own
    edition's under its folder (with the person's details, which an own edition writes to the profile)."""
    facts = tasks.facts_for(doc_job(job))  # the profile's facts, or the job's own edition's
    if facts is tasks.facts:  # the profile itself
        return list(FACT_FILES)
    at = facts.ws.root.resolve().relative_to(tasks.ws.root.resolve()).as_posix()  # jobs/<job>/own
    return [f"{at}/{r}" for r in FACT_FILES] + ["profile/details.json"]  # as OwnFacts.change names them


def project_of(prof: dict, pid: str) -> tuple[dict | None, dict | None]:
    """(the role, the project) of a project id in a profile, by the draft's own id rule, or (None, None)."""
    import write_resume as W  # the id rule
    for ri, r in enumerate(prof.get("roles") or [], 1):  # every role, numbered from 1 as the draft numbers them
        if not isinstance(r, dict):
            continue
        for pi, p in enumerate(r.get("projects") or [], 1):  # every project
            if isinstance(p, dict) and W.project_id(p, W.role_key(r, ri), pi) == pid:  # the one
                return r, p
    return None, None


def answer(tasks, job: str, lang: str, fid: str, text: str, project: str | None = None) -> dict:
    """The person's answer to a finding's question, kept as a fact of that project (one more line of its ledger, which the next
    draft may cite and the canvas counts as the item's evidence), and the finding marked answered. The project is the unit's
    own (an item's, or the one its deck page was paired with) or, for a page that names none, the one the request names.
    An answer never prints by itself: with no project, or one that is gone, it is refused (depth_no_project). A submitted
    application's edition is refused (locked). One undo step: the fact and the act, never the review."""
    words = " ".join(str(text or "").split())[:2000]  # one paragraph, bounded as a typed fact is
    if not words:  # nothing said
        raise ValueError("empty")
    if job != GENERAL and (tasks.ws.job(job) or {}).get("locked"):  # a submitted application stays as it went
        raise ValueError("locked")
    rec = load(tasks, job, lang)  # the kept review
    unit, f = find(rec, fid)  # the finding
    pid = str(unit.get("pid") or project or "")  # the project it is about: the unit's own first
    src_pid, role, proj = source_project(tasks, job, lang, pid) if pid else (None, None, None)  # where its ledger lives
    if proj is None:  # no project: an answer of its own would print in a section of its own
        raise ValueError("depth_no_project")
    org = text_of((role or {}).get("org")) or text_of(((role or {}).get("career") or {}).get("ko", {}).get("name")) or text_of((role or {}).get("heading"))  # the company, for the fact's card
    fields = {"kind": "project", "org": org, "title": text_of(proj.get("title")) or unit.get("title", ""),  # a fact of that project
              "period": text_of(proj.get("period")), "statement": words, "project": src_pid}  # the person's own words are its evidence
    facts = tasks.facts_for(doc_job(job))  # where the edition's words live
    with tasks.ws.change({"code": "undo_depth_answer", "title": fields["title"][:60]}, fact_rels(tasks, job) + [acts_rel(job, lang)]):  # one undo step: the fact and the act
        cid = facts.add_typed(fields)  # listed and kept
        facts.rebuild()  # the profile follows: the project's ledger has one more line
        put_act(tasks, job, lang, fid, {"state": "answered", "fact": cid, "answer": words[:400], "rid": rec.get("rid"), "hash": unit.get("hash"), "unit": unit.get("id")})
    return {"cid": cid, "finding": fid}


def leave(tasks, job: str, lang: str, fid: str) -> dict:
    """A finding the person decided to leave as it is: later reviews keep it left while the unit's words stay the same. One undo
    step: the act, never the review."""
    rec = load(tasks, job, lang)  # the kept review
    unit, f = find(rec, fid)  # the finding
    with tasks.ws.change({"code": "undo_depth_leave", "title": str(unit.get("title") or "")[:60]}, [acts_rel(job, lang)]):  # one undo step
        put_act(tasks, job, lang, fid, {"state": "left", "rid": rec.get("rid"), "hash": unit.get("hash"), "unit": unit.get("id")})  # the person's decision, kept
    return {"finding": fid}


def words_hash(tasks, job: str, lang: str, uid: str) -> str:
    """The hash of an item's words as the edition prints them now (after a rewrite went in): what a used finding holds for."""
    import depth_review as DR  # the units and their hash
    return next((DR.short_hash(u.get("text")) for u in DR.items_of(edition_profile(tasks, job, lang), lang) if u["id"] == uid), "")


def sentence_id(R, prof: dict, pid: str, replaces: str) -> tuple[str, int, str]:
    """(the canvas's id of the sentence a rewrite stands for, its number, its words): the sentence of the project that the
    rewrite names by its words, or its last sentence when the rewrite adds one. ValueError("depth_changed") when the item no
    longer prints it."""
    import depth_review as DR  # the same comparison of words
    import write_resume as W  # the id rule
    for ri, r in enumerate(prof.get("roles") or []):  # the canvas numbers roles and projects from 0
        for pi, p in enumerate((r.get("projects") or []) if isinstance(r, dict) else []):
            if not isinstance(p, dict) or W.project_id(p, W.role_key(r, ri + 1), pi + 1) != pid:  # not this project
                continue
            base = f"roles.{ri}.projects.{pi}.summary"  # its sentences are base.s0, base.s1 ...
            sids = sorted((s for s in R.sent if s.startswith(base + ".s")), key=lambda s: int(s.rsplit(".s", 1)[1]))  # in order
            if not sids:  # it prints no sentence now
                break
            if not replaces:  # a sentence added after the last one
                return sids[-1], len(sids) - 1, R.sent[sids[-1]]["text"]
            for k, s in enumerate(sids):  # the sentence it names
                if DR.plain(R.sent[s]["text"]) == DR.plain(replaces):
                    return s, k, R.sent[s]["text"]
            break
    raise ValueError("depth_changed")  # the item was written again since the review


def apply(tasks, job: str, lang: str, fid: str) -> dict:
    """The finding's rewrite in place of the sentence it replaces (or after the item's last one), through the canvas's own
    sentence path, and the finding marked applied. One undo step: the words and the act, never the review. Refused: locked (a
    submitted application), depth_no_rewrite, depth_changed (the item's words moved on since the review), edit_in_korean (an
    English sentence of a Korean profile that no draft wrote: its words are a translation, as the canvas says),
    depth_unsupported (the canvas's evidence would not hold it)."""
    import cover as C  # the units' text
    import depth_review as DR  # the sentence cut
    import factcheck  # the canvas's own fact rules
    import write_resume as W  # the ledger view
    from . import documents  # the canvas model
    from . import drafts as D  # a drafted sentence's place
    from . import evidence as E  # sentences and their replacement
    if job != GENERAL and (tasks.ws.job(job) or {}).get("locked"):  # a submitted application's sentences stay as they went
        raise ValueError("locked")
    rec = load(tasks, job, lang)  # the kept review
    unit, f = find(rec, fid)  # the finding
    rw = f.get("rewrite") if isinstance(f.get("rewrite"), dict) else None  # the words to use
    if not rw or unit.get("kind") != "item" or f.get("state") == "applied":  # a question, a deck page's words (the deck is made from its source), or used already
        raise ValueError("depth_no_rewrite")
    R = documents.model(tasks, lang, doc_job(job))  # the sentences as they are now
    sid, n, before = sentence_id(R, R.prof, unit["pid"], str(rw.get("replaces") or ""))  # the sentence it stands for
    if sid in R.locks:  # a locked sentence keeps its words
        raise ValueError("locked")
    stop = "" if re.search(r"[.!?]$", before.replace("==", "").strip()) else "."  # a Korean bullet's last sentence ends with no stop: the canvas cuts at ". "
    new = rw["text"] if rw.get("replaces") else f"{before.rstrip()}{stop} {rw['text']}"  # in its place, or after the last sentence, as its own sentence
    label = {"code": "undo_depth_apply", "title": str(unit.get("title") or "")[:60]}  # the undo key's words
    if sid in R.link_of:  # a sentence the draft wrote: its words and its link live in the draft
        d, owner = D.load(tasks, doc_job(job))  # the stored draft
        with tasks.ws.change(label, D.files(owner) + [acts_rel(job, lang)]):  # one undo step: the draft and the act, never the review
            if not D.put_sentence(d, R.prof, sid, lang, new, E.replaced):  # found by its id
                raise ValueError("depth_changed")
            mine = DR.plain(rw["text"])  # the new sentence's words
            for x in d.get("evidence") or []:  # its link now rests on what the rewrite cites
                if isinstance(x, dict) and x.get("lang") == lang and DR.plain(x.get("text")) == mine:
                    x.update(ev=list(rw.get("ev") or []), names={**(x.get("names") or {}), **(rw.get("names") or {})})  # the same checks look at it again
            write_json(tasks.ws.job_dir(owner) / "draft.json", d)  # saved with the job
            put_act(tasks, job, lang, fid, {"state": "applied", "rid": rec.get("rid"), "hash": words_hash(tasks, job, lang, unit["id"]), "unit": unit["id"]})  # used, on the words it made
        return {"sentence": sid, "finding": fid}
    if lang == "en" and tasks.profile_lang() == "ko":  # an English sentence of a Korean profile: its words are a translation (documents.edit_sentence)
        raise ValueError("edit_in_korean")  # the page says to edit the Korean sentence and translate again
    place, field, k = E.field_for(sid)  # where a fact's words live
    cids = [c for c in R.facts_at(place) if not c.startswith("details:")]  # the facts behind the item
    if not cids or field != "statement":  # nothing to write into
        raise ValueError("no_fact")
    U = C.units_of(W.ledger_view(R.prof), lang)  # the units the rewrite cites
    refs = sorted({str(i) for i in rw.get("ev") or [] if C.known_id(U, i)})  # the blocks it cites: the entries it rests on, never their whole projects
    cid = cids[0]  # the first fact speaks for the item, as an edit on the canvas writes it
    fact = R.by_cid.get(cid) or {}  # the fact
    facts = tasks.facts_for(doc_job(job))  # where its words live
    current = {**fact, **(facts.edits().get(cid) or {})}  # its fields with earlier edits
    item = R.at(place) or {}  # the item as the profile has it
    named = sorted(set(str(x) for x in (current.get("evidence") or item.get("evidence") or []) if isinstance(x, str)) | set(refs))  # what it rests on now
    held = R.evidence_text(sid) + "\n" + "\n".join(C.unit_text(U, i) for i in rw.get("ev") or [] if C.known_id(U, i))  # what the canvas will hold the words to
    if factcheck.unsupported(rw["text"].replace("==", ""), held):  # a name or a number the item's evidence would not hold
        raise ValueError("depth_unsupported")
    old = text_of(current.get("statement")) or text_of(item.get("summary") if isinstance(item, dict) else "")  # the paragraph as it is
    with tasks.ws.change(label, fact_rels(tasks, job) + [acts_rel(job, lang)]):  # one undo step: the fact and the act, never the review
        facts.set_edit(cid, {"statement": E.replaced(old, k, new) if old else new, "evidence": named})  # the paragraph with the sentence replaced, and what it rests on
        facts.set_status(cid, "accepted")  # an edited fact is kept
        facts.rebuild()  # the profile follows
        put_act(tasks, job, lang, fid, {"state": "applied", "rid": rec.get("rid"), "hash": words_hash(tasks, job, lang, unit["id"]), "unit": unit["id"]})  # used, on the words it made
    return {"sentence": sid, "finding": fid}


# ---------------------------------------------------------------- the command line

MSG = {  # what `offerowl depth` says, in both languages with the same keys
    "en": {
        "about": "Review each project item and deck page of an edition for what it leaves out, and act on what it finds, as the panel does",
        "help_review": "review the edition now (the AI backend in use, else the checks that need none)",
        "help_show": "print the edition's last review",
        "help_answer": "keep an answer to a finding's question as a fact of its project",
        "help_apply": "use a finding's rewrite in place of the sentence it replaces",
        "help_leave": "leave a finding as it is",
        "help_job": "the job's id, a named edition's id without its leading dash, or -general (general edition)",
        "help_lang": "the edition's language (default ko)",
        "help_data": "the app's data folder (default: the app's own)",
        "help_json": "print the API's own answer as JSON",
        "help_finding": "the finding's id, as show prints it",
        "help_text": "your answer, in your own words",
        "help_project": "the project the answer belongs to, for a deck page that names none (its id, as show lists the items)",
        "none": "{job} ({lang}): no review yet. Run `offerowl depth review {job}`.",
        "refused": "refused: {why}",
        "answered": "kept as a fact ({cid}): the next draft can cite it",
        "applied": "used in place of the sentence ({sid})",
        "left": "left as it is",
        "line": "  [{id}] {code} ({way}, {state}{gate}): {missing}",
        "unit": "- {mark}{title} [{where}]{parts}{changed}",
        "changed": "  (written again since the review)",
        "gates_now": "  {n} thin item(s) still miss a part: use its rewrite (apply) or answer its question (answer) first",
        "rewrite": "      rewrite: {text}",
        "question": "      question: {question}",
    },
    "ko": {
        "about": "판의 프로젝트 항목과 덱 쪽마다 빠진 것을 검토하고, 찾은 것을 패널처럼 처리한다",
        "help_review": "지금 판을 검토한다(쓰는 AI 백엔드, 없으면 모델이 필요 없는 검사만)",
        "help_show": "판의 마지막 검토를 보여 준다",
        "help_answer": "찾은 것의 질문에 대한 답을 그 프로젝트의 사실로 남긴다",
        "help_apply": "찾은 것의 고쳐 쓴 문장을 그 문장 자리에 쓴다",
        "help_leave": "찾은 것을 그대로 둔다",
        "help_job": "지원의 id, 앞 줄표를 뺀 범용판 id, 또는 -general(범용판)",
        "help_lang": "판의 언어(기본 ko)",
        "help_data": "앱의 데이터 폴더(기본: 앱의 것)",
        "help_json": "API 의 답을 JSON 으로 그대로 보여 준다",
        "help_finding": "찾은 것의 id, show 가 보여 주는 대로",
        "help_text": "답, 직접 쓴 말로",
        "help_project": "프로젝트를 짚지 못한 덱 쪽의 답이 속할 프로젝트(그 id, show 가 보여 주는 항목대로)",
        "none": "{job} ({lang}): 아직 검토가 없다. `offerowl depth review {job}` 를 먼저 돌린다.",
        "refused": "거절: {why}",
        "answered": "사실로 남겼다({cid}): 다음 초안이 근거로 쓸 수 있다",
        "applied": "문장 자리에 썼다({sid})",
        "left": "그대로 둔다",
        "line": "  [{id}] {code} ({way}, {state}{gate}): {missing}",
        "unit": "- {mark}{title} [{where}]{parts}{changed}",
        "changed": "  (검토 뒤에 다시 썼다)",
        "gates_now": "  빈약한 단위 {n}개에 아직 빠진 것이 있다: 고쳐 쓴 문장을 쓰거나(apply) 질문에 답하는(answer) 일을 먼저 한다",
        "rewrite": "      고쳐 쓴 문장: {text}",
        "question": "      질문: {question}",
    },
}


def t(key: str, **kw) -> str:
    """A line of the command line in the person's language."""
    import llm  # the language setting and the message helper
    return llm.message(MSG, key, **kw)


def resolve(api, job: str) -> str:
    """The id a job names on the command line: a named edition's id may come without its leading dash (a shell reads -name as
    an option), and the general edition is -general or 'general'."""
    if job in (GENERAL, "general"):  # the general edition
        return GENERAL
    if api.ws.job(job):  # an id as it is
        return job
    if api.ws.job("-" + job):  # a named edition's id without its dash
        return "-" + job
    return job  # the API says it is not there


def print_view(rec: dict) -> None:
    """A review as lines, thin units first: each unit with its verdict and its findings, their ids first (what answer, apply
    and leave take)."""
    import depth_review as DR  # the head line
    DR.print_review({**rec, "units": []})  # the counts and what the review could not do
    if (rec.get("now") or {}).get("gates"):  # thin units with a missing part still open: what to do first
        print(t("gates_now", n=rec["now"]["gates"]))
    for u in rec.get("units") or []:  # each unit
        if not u.get("findings"):  # nothing missing: said by the counts
            continue
        v, parts = u.get("verdict"), ", ".join(DR.t("p_" + p) for p in u.get("missing") or [])  # its verdict, and the core parts its words do not state
        print(t("unit", mark=DR.t("mark_" + v) if v else "", title=u.get("title", ""), where=u.get("where", ""), parts=DR.t("parts", parts=parts) if parts else "",
                changed=t("changed") if u.get("changed") else ""))
        for f in u["findings"]:  # each finding with its id
            print(t("line", id=f["id"], code=f["code"], way=f["way"], state=f.get("state", "open"), gate=DR.t("gate_mark") if f.get("gate") else "", missing=f.get("missing", "")))  # a thin unit's missing part says so
            if f.get("rewrite"):
                print(t("rewrite", text=f["rewrite"].get("text", "")))
            if f.get("question"):
                print(t("question", question=f["question"]))


def main(argv: list | None = None) -> int:
    """`offerowl depth review|show|answer|apply|leave JOB ...`. Exit 0 when done, 1 when the API refused (the reason on
    stderr), 2 for a wrong command line."""
    for stream in (sys.stdout, sys.stderr):  # Korean words print through any console or redirection
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="offerowl depth", description=t("about"))  # named as the launcher calls it
    sub = ap.add_subparsers(dest="cmd", required=True)  # one of five
    parsers = {name: sub.add_parser(name, help=t("help_" + name), description=t("help_" + name)) for name in ("review", "show", "answer", "apply", "leave")}
    for name, p in parsers.items():  # every command names its edition
        p.add_argument("job", help=t("help_job"))
        p.add_argument("--lang", default="ko", choices=LANGS, help=t("help_lang"))
        p.add_argument("--data", type=Path, default=None, help=t("help_data"))
        p.add_argument("--json", action="store_true", help=t("help_json"))
        if name in ("answer", "apply", "leave"):  # they act on one finding
            p.add_argument("finding", help=t("help_finding"))
        if name == "answer":  # with the person's words
            p.add_argument("text", help=t("help_text"))
            p.add_argument("--project", help=t("help_project"))  # an unpaired page's answer names its project
    a = ap.parse_args(argv)  # exits with 2 and a usage line on a wrong command line
    from .client import Client  # the API in this process, as `offerowl api` calls it
    c = Client(a.data)  # the same routes the panel calls
    job = resolve(c.api, a.job)  # the id the words mean
    try:
        if a.cmd == "review":  # the review, through the route the panel's key calls, then its result
            c.post("/api/v1/jobs/depth", {"job": job, "lang": a.lang})
            rec = c.wait(f"depth:{job}", timeout=3600)  # a long career takes several calls
            if rec.get("state") == "error":  # it could not run
                print(t("refused", why=(rec.get("error") or {}).get("code") or "error"), file=sys.stderr)
                return 1
            got = c.get(f"/api/v1/jobs/{job}/depth", lang=a.lang)  # the review as the page reads it
        elif a.cmd == "show":  # the last review
            got = c.get(f"/api/v1/jobs/{job}/depth", lang=a.lang)
            if got.get("none"):  # never reviewed: the hint names the job as a shell takes it (no leading dash)
                print(t("none", job="general" if job == GENERAL else job.lstrip("-"), lang=a.lang), file=sys.stderr)
                return 1
        else:  # one finding acted on
            body = {"job": job, "lang": a.lang, "finding": a.finding, **({"text": a.text, "project": a.project or ""} if a.cmd == "answer" else {})}
            got = c.post(f"/api/v1/jobs/depth/{a.cmd}", body)
    except RuntimeError as exc:  # refused, with the API's code
        why = json.loads(str(exc)).get("what") or json.loads(str(exc)).get("error") or ""
        print(t("refused", why=why), file=sys.stderr)
        return 1
    if a.json:  # for a script
        print(json.dumps(got, ensure_ascii=False, indent=1))
        return 0
    if a.cmd in ("review", "show"):  # the review in lines
        print_view(got)
    elif a.cmd == "answer":
        print(t("answered", cid=got.get("cid")))
    elif a.cmd == "apply":
        print(t("applied", sid=got.get("sentence")))
    else:
        print(t("left"))
    return 0


if __name__ == "__main__":  # `offerowl depth` runs this file
    sys.exit(main())
