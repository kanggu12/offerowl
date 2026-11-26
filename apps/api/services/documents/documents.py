"""The documents of the canvas: the resume (evidence.Resume) and the cover letter (src/cover.py's cover.json), in the
document's language and colours, for the job in view. Also the edits made on the canvas: a sentence's new words, its
lock, and the text of the resume that the interview kit reads.

Every change goes through Workspace.change() with the fact files (Facts.change: an application's own edition's too, in the
workspace's one history), so one undo takes it back.
"""
from __future__ import annotations

import json  # a build's record, read without a failure
import logging  # the panel's log
import os  # a preview folder's names, read once
import re  # sentence ids
from pathlib import Path  # paths
from urllib.parse import quote  # a job's id in a picture's address

from . import drafts as D  # a job's drafted resume
from .. import applications  # a job's posting analysis
from ..profile import SECTION_LABELS, SECTION_NAMES, Resume, field_for, pick_lang, replaced, text_of  # the resume model, its section names and the sentence rules, plain text (the profile's)
from ...core.workspace import read_json, write_json  # files

log = logging.getLogger("offerowl.panel")  # the panel's log
DOC_LANGS = ("ko", "en")  # the editions
# The canvas's parts for each form, in the order src/resume_form.js prints them (the detailed form takes them all, as they come,
# but the service record, which only the table form prints)
FORM_PARTS = {"compact": ("top", "detail", "skills", "edu", "other"),
              "table": ("edu", "career", "other", "service", "skills", "detail", "about", "motivation")}
SID = re.compile(r"^[a-z][a-z0-9_.]{0,80}$")  # a sentence id as the model writes them


def profile_for(tasks, lang: str, job: str | None = None) -> tuple[dict | None, bool]:
    """(the profile to draw in this language, whether it is an agent's translation). (None, False) when the
    English edition needs a translation that was never made from this profile, or a partial one this job's draft does not complete."""
    if tasks.own_dir(job) is not None:  # the job's own edition: its words as the person wrote them, in its languages
        return (tasks.facts_for(job).profile(), False) if lang in tasks.own_langs(job) else (None, False)
    if lang == "en" and tasks.profile_lang() == "ko":  # a Korean profile drawn in English
        p = tasks.english_for(job)  # the translation of this very profile
        return (read_json(p, None), True) if p else (None, False)  # none yet: the page offers to translate
    return tasks.facts.profile(), False  # the profile itself


def drawn(tasks, prof: dict, lang: str, job: str | None) -> dict:
    """What the resume model draws from for this job: the profile, the evidence map, the locks and the draft in force."""
    facts = tasks.facts_for(job)  # the fact files: the job's own edition's when it has one
    d, owner = D.load(tasks, job)  # the job's draft, else the general edition's
    if not d or lang not in ((d.get("_draft") or {}).get("langs") or []):  # no draft in this language
        return {"prof": prof, "evmap": facts.evidence(), "locks": facts.locks(), "draft": None, "owner": None, "live": None}  # the facts as they are
    now = D.merged(prof, d)  # the draft's sentences in the facts' profile
    if owner == job and job and not job.startswith("-") and (d.get("_draft") or {}).get("posting"):  # written for this posting:
        now = {k: v for k, v in now.items() if k not in ("motivationTitle", "motivationSub")}  # its motivation prints under the form's own title, as the build's copy (tasks._edition_profile)
    current = D.with_ids(facts.profile())  # the facts as they are now
    stale = D.base_hash(current) != (d.get("_draft") or {}).get("from")  # changed since the draft
    return {"prof": now, "evmap": D.moved(facts.evidence(), prof, now), "locks": (d.get("_locks") or {}).get(lang) or {}, "draft": d, "owner": owner,  # its own locks
            "live": current if stale else None}  # compared sentence by sentence only when it changed


def for_form(blocks: list, form: str) -> list:
    """The canvas's blocks in the order a form prints them, without the parts it leaves out."""
    order = FORM_PARTS.get(form)  # what this form prints
    groups, now = {"top": []}, "top"  # the blocks by part; what comes before the first heading is the top
    for b in blocks:  # in the model's order
        if b.get("type") == "section":  # a heading starts a part
            now = b.get("key") or "other"  # a list of the profile has no key of its own
            groups.setdefault(now, [])  # its place
        groups[now].append(b)  # with its heading
    if not order:  # the detailed form: every part in the model's order, but the service record it does not print
        return [b for part, bs in groups.items() if part != "service" for b in bs]
    return [b for part in order for b in groups.get(part, [])]  # in the form's order


def resume(tasks, lang: str = "ko", theme: str = "navy", job: str | None = None) -> dict:
    """The resume model for the canvas (resume.schema.json), or {"kind": "resume", "missing": [...]} when it cannot be
    drawn yet: no facts kept, or the English profile missing."""
    from ..profile import problems  # what stops a resume
    facts = tasks.facts_for(job)  # the fact files: the job's own edition's when it has one
    prof, translated = profile_for(tasks, lang, job)  # the profile to draw
    if prof is None:  # the English edition without its translation
        return {"kind": "resume", "lang": lang, "theme": theme, "missing": ["needs_translation"], "blocks": [], "sentences": {}}  # the page offers the fix
    plan = applications.plan_of(tasks.ws, job) if job else {}  # the job's analysis, when a job is in view (the applications' plan)
    w = drawn(tasks, prof, lang, job)  # the facts, or a draft of them
    R = Resume(w["prof"], lang, theme, evmap=w["evmap"], cands=facts.candidates(), base=facts.base(),  # the model's inputs
                 edits=facts.edits(), locks=w["locks"], details=facts.details(), plan=plan, job=job, translated=translated, draft=w["draft"], live=w["live"])
    out = R.build()  # blocks, sentences, counts
    out["form"] = tasks.look()["form"]  # the form chosen in the panel
    if job and tasks.own_form(job, lang).get("tenure") is False:  # an edition made without the time at each company (own/form.json): drawn as it prints
        hide_tenure(out["blocks"])
    pictures(tasks, out, job, lang, theme)  # the photo, the figures and the logos the printed resume carries
    out["blocks"] = for_form(out["blocks"], out["form"])  # shown as it will print
    out["draft"] = D.summary(tasks, w["owner"], bool(w["live"]), job) if w["draft"] else None  # who wrote it, when, and whether the facts moved on
    out["missing"] = problems(facts.profile())  # a name, an email, one role
    out["profile_lang"] = tasks.profile_lang()  # the language the profile itself is written in
    return out  # what the canvas draws


def hide_tenure(blocks: list) -> None:
    """No time spent at each company and no total, as src/resume_form.js prints an edition made with tenure off: the career
    table's rows and the companies' bands lose their tenure, the career heading its "(총경력 …)"."""
    for i, b in enumerate(blocks):  # every block of the model
        if b.get("type") == "career":  # the career summary table
            for r in b.get("rows") or []:
                r["tenure"] = ""  # the column goes when no row has it (docs.js careerTable, as the printed table)
            if i and blocks[i - 1].get("type") == "section":  # its heading, right before it
                blocks[i - 1].pop("note", None)  # no total beside the title
        elif b.get("type") == "role":  # a company's band
            b["tenure"] = ""  # its dates alone, in the band's quiet grey (docs.js)


def pictures(tasks, out: dict, job: str | None, lang: str, theme: str) -> None:
    """The pictures of the printed resume in the canvas's model, as addresses the panel serves: the photo in the header
    (person.photo), the overview timeline and the hierarchy figure as figure blocks where src/resume_form.js prints them
    (after the overview heading, after the core competencies heading), and each company's and school's logo tile (logo
    on a career, education or role row). The detailed form prints them all; the table form its logos only (its career,
    education and experience are the detailed form's, its head has no photo, and it prints no overview or competencies,
    where the figures go); the one-column form none. A blind edition's photo is the build's to leave out, the canvas shows
    the words as they are."""
    if out["form"] not in ("detailed", "table"):  # the one-column form prints no figure, logo or photo
        return
    jid = job or D.GENERAL  # whose figures: the job in view, else the edition with no job
    q = lambda name, v: f"/api/v1/jobs/{quote(jid, safe='')}/figures/{lang}/{name}.png?theme={theme}&v={v}"  # noqa: E731  one picture's address, new with each drawing
    form = tasks.own_form(job, lang) if job else {}  # how a job's own edition was made: it may have gone without the photo or the hierarchy figure
    photo = tasks.photo_for_build() if out["form"] == "detailed" and form.get("photo") is not False else None  # the photo, when the setting puts it on the resume (the detailed form's name band only)
    if photo:  # in the name band's left cell, as printed
        out["person"]["photo"] = f"/api/v1/photo?v={int(photo.stat().st_mtime)}&w=240&theme={theme}"  # the canvas draws it 76 px wide: a small copy (the PDF reads the file itself)
    try:
        figs = tasks.resume_figures(jid, lang, theme)  # drawn from the edition's profile, kept until it changes
    except Exception as exc:  # noqa: BLE001  the canvas draws without them rather than not at all
        log.warning("resume figures failed: %s", exc)
        return
    files, v = figs.get("files") or {}, figs.get("stamp") or "0"
    for b in out["blocks"]:  # a logo beside each company and school
        for r in (b.get("rows") or []) if b.get("type") in ("career", "education") else [b] if b.get("type") == "role" else []:
            if r.get("logo_id") and f"logo_{r['logo_id']}" in files:
                r["logo"] = q(f"logo_{r['logo_id']}", v)
    blocks = out["blocks"]
    def put(kind: str, section: str, before: tuple) -> None:  # one figure, right after its section's heading
        if kind not in files:  # not drawn for this resume
            return
        w, h = int.from_bytes(files[kind][16:20], "big"), int.from_bytes(files[kind][20:24], "big")  # its size from the PNG header: the page keeps its room before it loads
        fig = {"type": "figure", "key": kind, "src": q(kind, v), "w": w, "h": h}
        at = next((i for i, b in enumerate(blocks) if b.get("type") == "section" and b.get("key") == section), None)
        if at is not None:
            blocks.insert(at + 1, fig)
            return
        # no such section yet (an overview of the timeline alone, a hierarchy without bullets): the heading and the figure go
        # where the printed resume has them, before the first of the sections that follow it
        at = next((i for i, b in enumerate(blocks) if b.get("type") == "section" and b.get("key") in before), len(blocks))
        blocks[at:at] = [{"type": "section", "key": section, "title": SECTION_NAMES[lang][section], "en": SECTION_LABELS[section]}, fig]
    put("timeline", "overview", ("career", "edu", "comp", "skills", "detail", "about", "motivation"))
    if tasks.edition_cfg(job, lang, theme).get("competencyFigure") is not False:  # an edition made without the hierarchy figure keeps going without it
        put("stack", "comp", ("skills", "detail", "about", "motivation"))


def model(tasks, lang: str = "ko", job: str | None = None) -> Resume:
    """The resume model object itself (for edits and regeneration, which need its evidence lookups)."""
    facts = tasks.facts_for(job)  # the fact files: the job's own edition's when it has one
    prof, translated = profile_for(tasks, lang, job)  # the profile in that language
    if prof is None:  # nothing to edit in that language yet
        raise ValueError("needs_translation")  # the page offers to translate
    w = drawn(tasks, prof, lang, job)  # the facts, or a draft of them
    R = Resume(w["prof"], lang, "navy", evmap=w["evmap"], cands=facts.candidates(), base=facts.base(),  # the same inputs as resume()
                 edits=facts.edits(), locks=w["locks"], details=facts.details(), translated=translated, draft=w["draft"], live=w["live"])
    R.build()  # registers every sentence
    return R  # with .sent and the evidence lookups


def edit_sentence(tasks, sid: str, text: str, lang: str = "ko", job: str | None = None) -> dict:
    """Write a sentence's new words into the fact it rests on (or into "Your details"), as one undo step. Returns the
    sentence's new record. Raises ValueError for an unknown or locked sentence, or an English sentence (the English
    edition is made from the Korean one)."""
    if not SID.match(sid or "") or not isinstance(text, str) or not text.strip():  # a made-up id or no words
        raise ValueError("sentence")  # refused
    facts = tasks.facts_for(job)  # the fact files: the job's own edition's when it has one
    ws = tasks.ws  # where the drafts are kept, and every undo step (an own edition's too: facts.change)
    R = model(tasks, lang, job)  # the sentences as they are now
    if sid not in R.sent:  # not a sentence of this resume (a stale page)
        raise ValueError("sentence")  # refused
    if sid in R.locks:  # a locked sentence keeps its words
        raise ValueError("locked")  # the page says to unlock it first
    if text.strip()[:1000] == R.sent[sid]["text"]:  # the words it has already: nothing changes, and no undo step names a change that was not made
        return R.sent[sid]  # its record as it is
    if sid in R.link_of:  # a sentence of the draft: its words live there, in this language
        d, owner = D.load(tasks, job)  # the stored draft
        with ws.change({"code": "undo_sentence", "title": R.sent[sid]["text"][:60]}, D.files(owner)):  # one undo step
            if not D.put_sentence(d, R.prof, sid, lang, text.strip()[:1000], replaced):  # found by its id
                raise ValueError("sentence")  # a stale page
            write_json(ws.job_dir(owner) / "draft.json", d)  # saved with the job
        return model(tasks, lang, job).sent.get(sid) or {}  # its new record: the same checks looked at it again
    if lang == "en" and tasks.profile_lang() == "ko":  # an English sentence of a Korean profile
        raise ValueError("edit_in_korean")  # the page says to edit the Korean sentence and translate again
    place, field, n = field_for(sid)  # where its words live
    text = text.strip()[:1000]  # bounded
    label = {"code": "undo_sentence", "title": R.sent[sid]["text"][:60]}  # the undo button's words
    with facts.change(label):  # one undo step, in the workspace's history even for an own edition's words
        if field in ("headline", "intro"):  # the person's own words
            old = text_of(facts.details().get(field)) or text_of(pick_lang(R.prof.get("summary", {}).get(field), lang))  # the paragraph as it is
            facts.set_details({field: replaced(old, n, text)})  # saved as typed
        else:  # a fact's field
            cids = [c for c in R.facts_at(place) if not c.startswith("details:")]  # the facts behind it (an English list written apart has its own)
            if not cids:  # nothing to write into: an item the imported file carried without a card
                raise ValueError("no_fact")  # the page says it can be changed in the profile view
            cid = cids[0]  # the first fact speaks for the item
            fact = R.by_cid.get(cid) or {}  # the fact
            current = {**fact, **(facts.edits().get(cid) or {})}  # its fields with earlier edits
            if field.startswith("rows."):  # one row of a key project card
                k = int(field.split(".")[1])  # which row
                item = R.at(place) or {}  # the card as the profile has it now
                rows = [list(r) for r in (current.get("rows") or (item.get("rows") if isinstance(item, dict) else []) or [])]  # its rows
                if k >= len(rows):  # a row that is gone
                    raise ValueError("sentence")  # refused
                rows[k] = [rows[k][0], text] + rows[k][2:]  # the label stays, the text changes
                facts.set_edit(cid, {"rows": rows, "statement": " / ".join(f"{r[0]}: {' '.join(map(str, r[1:]))}" for r in rows)})  # the card's rows and its one-line form
            else:  # the statement or title of the fact
                old = text_of(current.get(field)) if field != "statement" or current.get("statement") else text_of(current.get("title"))  # the field as it is
                if fact.get("kind") in ("project",) and field == "statement" and not text_of(current.get("statement")):  # a project without a summary yet
                    old = ""  # the sentence is new text
                facts.set_edit(cid, {field: replaced(old, n, text) if old else text})  # the paragraph with the sentence replaced
            facts.set_status(cid, "accepted")  # an edited fact is kept
        facts.rebuild()  # the profile follows
    R2 = model(tasks, lang, job)  # the sentences now
    return R2.sent.get(sid) or {}  # the new record (its state says whether the evidence still covers it)


def lock_sentence(tasks, sid: str, locked: bool, lang: str = "ko", job: str | None = None) -> None:
    """Lock a sentence with its words (later drafts keep it), or unlock it. One undo step."""
    R = model(tasks, lang, job)  # the sentences as they are now
    if sid not in R.sent:  # a stale page
        raise ValueError("sentence")  # refused
    if R.draft:  # the draft in force keeps its own locks, since its sentences are its own
        d, owner = D.load(tasks, job)  # the stored draft
        with tasks.ws.change({"code": "undo_lock_sentence" if locked else "undo_unlock_sentence", "title": R.sent[sid]["text"][:60]}, D.files(owner)):  # one undo step
            mine = d.setdefault("_locks", {}).setdefault(lang, {})  # this language's
            if locked:  # kept with its words
                mine[sid] = R.sent[sid]["text"]  # as printed
            else:  # forgotten
                mine.pop(sid, None)  # gone
            write_json(tasks.ws.job_dir(owner) / "draft.json", d)  # saved with the job
        return  # the facts' locks are another list
    facts = tasks.facts_for(job)  # the job's own edition's, or the profile's
    with facts.change({"code": "undo_lock_sentence" if locked else "undo_unlock_sentence", "title": R.sent[sid]["text"][:60]}):  # one undo step, the panel's undo reaches it
        facts.set_lock(sid, R.sent[sid]["text"] if locked else None)  # kept with its words, or forgotten


def resume_text(tasks, lang: str = "ko", job: str | None = None) -> str:
    """The resume's claims as plain lines (one per sentence), the text the interview kit asks about."""
    m = resume(tasks, lang, "navy", job)  # the model
    lines = []  # one per claim
    for b in m.get("blocks") or []:  # in print order
        sids = ([b["sid"]] if b.get("sid") and b["type"] in ("headline",) else []) + list(b.get("sids") or [])  # paragraph sentences
        for it in b.get("items") or []:  # cards, competencies, list lines
            if isinstance(it, dict) and it.get("sid"):  # one sentence per item
                sids.append(it["sid"])  # its sentence
            for r in (it.get("rows") or []) if isinstance(it, dict) else []:  # key project rows
                sids.append(r["sid"])  # each row
        for p in b.get("projects") or []:  # a role's projects
            sids += p.get("sids") or []  # their sentences
        for sid in sids:  # each sentence of the block
            t = (m["sentences"].get(sid) or {}).get("text", "").replace("==", "")  # its words without marks
            if t:  # only real text
                lines.append("- " + t)  # a list item: the question map reads list items
    if not lines and job:  # an edition printed as written (the person's own) has no sentences of ours: the words its PDF printed
        lines = printed_lines(tasks, job, lang)
    return "\n".join(lines) + "\n"  # one text


CONTACT = re.compile(r"@|https?://|www\.|\||(?:^|\s)\+?\d{2,4}[- ]\d{3,4}[- ]\d{4}")  # an email, a link, a row of contacts, a phone number


def printed_lines(tasks, job: str, lang: str) -> list[str]:
    """The claims of a typeset resume, from the text its build printed (resume.txt beside its PDF), the kit's language first:
    lines long enough to be a claim, without the name, the headings and the contact lines."""
    for lg in (lang, "en" if lang == "ko" else "ko"):  # the language asked for, else the other one the edition has
        f = tasks.build_dir(job, lg) / "resume.txt"  # what the PDF printed
        if not f.is_file():  # not made in this language
            continue
        out = []  # its claims
        for raw in f.read_text(encoding="utf-8").splitlines():  # one printed line each
            t = raw.strip().lstrip("-•·* ").strip()  # without a list mark
            caps = bool(re.search(r"[A-Za-z]", t)) and not re.search(r"[a-z]", t)  # a title in capitals, such as a role line
            if len(t) >= 25 and not caps and not CONTACT.search(t):  # a sentence, not a heading, a name or a contact
                out.append("- " + t)  # a list item, as the sentences above are
        if out:  # this language had some
            return out
    return []


def cover(tasks, job: str, lang: str = "ko") -> dict:
    """The cover letter of a job for the canvas: its paragraphs with each sentence's evidence, from cover.json, or
    {"state": "none"} before one was drafted."""
    d = tasks.build_dir(job, lang) / "cover"  # the letter's folder
    doc = read_json(d / "cover.json", None)  # the draft
    if not isinstance(doc, dict):  # never drafted
        return {"kind": "cover", "state": "none", "lang": lang}  # the page offers to tailor
    import cover as C  # src/cover.py: the evidence units the sentences cite
    prof = read_json(tasks.build_dir(job, lang) / "profile.json", {}) or tasks.facts_for(job).profile()  # the profile it was drafted from
    U = C.units_of(prof, lang)  # its evidence units
    paras = []  # for the canvas
    unsupported = 0  # sentences without evidence
    for p in doc.get("paragraphs") or []:  # in order
        sents = []  # its sentences
        for i, s in enumerate(p.get("sentences") or []):  # each one
            ev = [{"unit": u, "quote": C.unit_text(U, u).split("\n", 1)[-1][:400], "where": (U["index"].get(u) or {}).get("head", "")
                   or U["heads"].get(u, ""), "file": ""} for u in s.get("ev") or [] if C.known_id(U, u)]  # each cited unit
            state = "ok" if ev or s.get("frame") else "unsupported"  # a claim with no evidence is marked
            unsupported += state == "unsupported"  # counted
            sents.append({"sid": f"cover.{p.get('id')}.s{i}", "text": text_of(s.get("text")), "state": state, "evidence": ev,  # the sentence
                          "frame": bool(s.get("frame"))})  # greetings and sign-offs claim nothing
        paras.append({"id": text_of(p.get("id")), "kind": text_of(p.get("kind")), "sentences": sents})  # the paragraph
    return {"kind": "cover", "state": "drafted", "lang": lang, "job": doc.get("job") or {}, "signature": text_of(doc.get("signature")),  # the letter
            "paragraphs": paras, "counts": {"unsupported": unsupported, "sentences": sum(len(p["sentences"]) for p in paras)},  # its counts
            "pdf": (tasks.build_dir(job, lang) / "cover.pdf").is_file()}  # typeset too


PRINTED = ("resume.pdf", "deck.pdf", "cover.pdf")  # an edition's printed files, as the Library lists them and the kit reads the deck


def printed_file(tasks, job: str, lang: str, name: str) -> Path | None:
    """One of an edition's printed files (PRINTED) as its last build left it, or None when the edition has no such file."""
    f = tasks.build_dir(job, lang) / name  # jobs/<job>/resume/<lang>/<name>
    return f if name in PRINTED and f.is_file() else None  # only the printed ones, and only once made


def build_record(tasks, job: str, lang: str) -> dict:
    """An edition's record as its last build kept it (build.json), or {} when it is missing or not an object: a reader that
    only reports on a build (the autopilot's result) never fails for it."""
    try:
        got = json.loads((tasks.build_dir(job, lang) / "build.json").read_text(encoding="utf-8"))  # as written
    except (OSError, ValueError):  # missing, or cut short
        return {}
    return got if isinstance(got, dict) else {}


def editions(tasks, job: str) -> dict:
    """The typeset editions of a job per language (build.json), with their page pictures' names."""
    out = {}  # per language
    for lang in DOC_LANGS:  # each edition
        b = read_json(tasks.build_dir(job, lang) / "build.json", None)  # its record
        if isinstance(b, dict):  # made once
            prev = tasks.build_dir(job, lang) / "preview"  # its pictures
            pdfs = {"r": "resume.pdf", "d": "deck.pdf", "c": "cover.pdf"}  # each document's file
            try:  # the folder read once for the three documents (the state asks at every poll, for every job and language)
                names = [n for n in os.listdir(prev) if n.endswith(".png")]  # the engine writes them in lower case: r-1.png, d-3.png
            except OSError:  # no pictures yet
                names = []
            b["previews"] = {k: sum(1 for n in names if n.startswith(f"{k}-")) if (tasks.build_dir(job, lang) / f).is_file() else 0  # pages per document,
                             for k, f in pdfs.items()}  # and none for a document whose PDF is gone (a letter that failed this time)
            out[lang] = b  # shown in the inspector and the print view
    return out  # {} before the first one


# ---------------------------------------------------------------- the editions as the page draws them, and whether each is stale


def deck_stale(api, b: dict) -> bool:
    """An edition whose deck was written from another deck source than the one in the workspace now (one made before there
    was a source, or from a PDF, records none and stays as it was)."""
    return bool(b.get("deck_src")) and b.get("deck_src") != api.tasks.deck_stamp()


def blind_stale(api, b: dict) -> bool:
    """A blind edition made with another mask table than the one kept now: its bars are not the table's."""
    return b.get("blind") is True and b.get("blind_table", "") != api.tasks.blind_stamp()


def stale(api, jid: str, b: dict) -> bool:
    """Was this edition made from what there is now? An edition made from the job's own edition or own files follows those
    (an older build that did not record them counts as current); any other follows the profile and the draft. A blind
    edition follows its mask table too."""
    if blind_stale(api, b) or deck_stale(api, b):  # the table changed since its bars were drawn, or the deck source since it wrote the deck
        return True
    own = api.tasks.own_stamp(jid)  # the job's own things, if any
    if own:  # printed from them, not from the profile
        return b.get("own") is not None and b.get("own") != own
    return not api.facts.same_profile(b.get("profile")) or b.get("draft", "") != api.tasks.draft_stamp(jid)  # facts or the draft changed since


def job_builds(api, jid: str) -> dict:
    """A job's or a named edition's last editions, per language, each marked when what it was made from changed since."""
    builds = editions(api.tasks, jid)  # per language
    for b in builds.values():  # each edition
        b["stale"] = stale(api, jid, b)  # facts, the draft or the job's own edition changed since
    return builds


def general_view(api) -> dict:
    """The edition made with no job in view: PDFs of the profile as it is, for a person who has not picked a posting yet."""
    builds = editions(api.tasks, D.GENERAL)  # per language
    for b in builds.values():  # each edition
        b["stale"] = not api.facts.same_profile(b.get("profile")) or b.get("draft", "") != api.tasks.draft_stamp(D.GENERAL) or blind_stale(api, b) or deck_stale(api, b)  # facts, the draft, the mask table or the deck source changed since
    return {"id": D.GENERAL, "builds": builds}  # the shape of a job, as far as the Documents view reads one


def editions_view(api) -> list[dict]:
    """Every named general edition with its last PDFs (the Documents view's picker and canvas read these)."""
    out = []  # one per edition
    for st in api.ws.editions():  # oldest first
        with api.gone_meanwhile(st["id"]):  # deleted for good while this was read: left out
            builds = job_builds(api, st["id"])  # per language, each marked when facts, the draft or the job's own edition changed since
            out.append({**st, "builds": builds, "own": api.tasks.own_langs(st["id"]),  # with the languages of the resume brought in for it,
                        "own_info": api.tasks.own_info(st["id"])})  # and where it was started from (the Documents head says so)
    return out


def safe_name(name: str) -> str:
    """A file name without folders or odd characters, for a document's download name."""
    return re.sub(r'[\\/:*?"<>|]+', "_", Path(str(name)).name)[:120] or "document"  # never a path
