"""The interview studio's board for a job (core/schema/documents/interview.schema.json): the question map by
category (src/interview/plan.py, kept by the tailor step in the kit's output folder) and the script cards
(src/interview/corpus.py), each turn English first with its translation below.

The search view, the practice mode and the printable cue cards are the interview kit's own pages on its own port;
the board links to them. Practice opens at "#practice" on the kit's page, and the cue cards at "/cue"; each link is
offered only when its module is there (src/interview/practice.py, src/interview/cue.py).
"""
from __future__ import annotations

import json  # the kit's health answer
import re  # dialogue lines
import shutil  # a job's kit outputs, deleted with the job
import urllib.parse  # a job's id in the kit's address
import urllib.request  # the kit's health
from collections import Counter  # questions by how the scripts cover them

from pathlib import Path  # paths

from ...core.workspace import read_json, write_json  # files

KIT = Path(__file__).resolve().parents[4] / "src" / "interview"  # the interview kit's code

KINDS = ("asked", "behavioral", "company", "scenario", "technical", "posting", "resume", "portfolio", "term", "opening")  # the map's categories, the likeliest first: what an earlier round asked before all
TURN = re.compile(r"^\*\*(면접관|나|Interviewer|Me|해석|Translation)\*\*\s*(.*)$")  # one line of a script, by its bold label
WHO = {"면접관": "interviewer", "Interviewer": "interviewer", "나": "me", "Me": "me"}  # the speakers
KIT_FILE = re.compile(r"^[\w가-힣 .()-]{1,80}\.(md|json|txt)$")  # a kit's own files: notes and tables, Hangul names too, never a path
KIT_OUT = ("deck.pdf", "deck.html", "plan.md")  # what the kit's maker writes and a person opens
KIT_MADE = ("kit.json", "names.txt", "portfolio.txt", "resume.txt")  # what the panel writes into a kit from the documents (task_kit.ensure_kit): its workings, made again each time, not a person's file
DRAFT_FILE = re.compile(r"^drafts-\d{1,4}\.md$")  # the agent's scripts, as the kit's writer names them (out/interview/<job>/drafts); never the .rejected ones


def turns(md: str) -> list[dict]:
    """A scene's dialogue as turns: {who, en, ko}, each spoken line with the translation line under it."""
    out = []  # in order
    for line in (md or "").splitlines():  # every line of the scene
        m = TURN.match(line.strip())  # a labelled line
        if not m:  # notes, headings, blank lines
            continue  # not dialogue
        label, text = m.group(1), m.group(2).strip()  # who and what
        if label in WHO:  # a spoken line
            out.append({"who": WHO[label], "en": text, "ko": ""})  # its translation follows
        elif out and not out[-1]["ko"]:  # the translation of the line above
            out[-1]["ko"] = text  # under it
    return out  # interviewer and me, in turn


def drafted_for(text: str) -> dict:
    """The questions a drafts file answers: {question id: scene id}. src/interview/draft.py ends each scene with a hidden
    "- **근거**: <question id> (<source>)" line, which names the question it was written for."""
    out = {}  # question id -> scene id
    for chunk in re.split(r"(?m)^### ", text)[1:]:  # one chunk per scene
        sid = chunk.split(".", 1)[0].strip()  # the scene's id, "P3"
        m = re.search(r"(?m)^- \*\*근거\*\*: (\S+)", chunk)  # its question
        if m and sid:  # both found
            out[m.group(1)] = sid  # the question has a draft now
    return out


def health(url: str) -> dict | None:
    """The kit's /api/health answer, or None when nothing answers."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # local: no proxy
        with opener.open(url.rstrip("/") + "/api/health", timeout=1.5) as r:  # a quick look
            return json.loads(r.read())  # its answer
    except (OSError, ValueError):  # nothing there, or not the kit
        return None  # not up


def has_kit(ws, jid: str) -> bool:
    """A kit to show: the tailor step (or the kit's own route) wrote its settings. A talk's brief alone makes the folder,
    not a kit."""
    return (ws.job_dir(jid) / "interview" / "kit.json").is_file()


def board(tasks, job_id: str, lang: str = "ko") -> dict:
    """The studio's board for one job. ready is False until the tailor step made the kit folder."""
    jd = tasks.ws.job_dir(job_id)  # the job's folder
    url = "/kit/" + urllib.parse.quote(job_id, safe="") + "/"  # the kit at the panel's own address (web.py kit_proxy), on any port the panel runs on
    ready = tasks.interview_available() and (jd / "interview" / "kit.json").is_file()  # a kit to show: the tailor step wrote its settings (a talk's brief alone makes the folder, not a kit)
    up = ready and job_id in tasks.kit_srvs  # this job's own kit server runs (tasks.kit_url); a job without a kit never asks a port
    base = {"search": {"up": bool(up), "url": url},  # the search view
            "practice": {"available": (KIT / "practice.py").is_file(), "url": url + "#practice"},  # practice opens directly at #practice
            "cue": {"available": (KIT / "cue.py").is_file(), "url": url + "cue"},  # the printable cue cards
            "deck": {"available": (KIT / "deck.py").is_file(), "url": url + "deck"}}  # the printable interview deck
    if not ready:  # no kit yet
        return {"ready": False, "categories": [], "scripts": [], "counts": {"questions": 0, "scripts": 0, "uncovered": 0}, **base}  # the page offers to make it
    from interview import corpus  # the scene files
    from interview import plan as ivplan  # the question map
    from interview.job import Job  # the kit's job folder
    job = Job(jd, confined=True)  # the kit, kept inside the workspace
    plan = read_json(job.out_dir() / "plan.json", {}) or {}  # the map the tailor step wrote
    rows = plan.get("questions") or []  # its entries
    if not rows:  # an older kit without a map
        rows = ivplan.build(job)  # made now, no model
    items, alts = corpus.load(job)  # the scenes, the agent's drafts among them
    # what the earlier rounds asked, read now from the rounds as they are (a round written, changed or undone a moment ago),
    # in place of the map's copy from when it was made; rated against the scenes only when there is a question to rate
    rows = ivplan.with_asked(job, rows, items, alts)
    cats = []  # by category
    for kind in KINDS:  # in the map's order
        qs = [{"id": r["id"], "text": r.get("text", ""), "ask_en": (r.get("ask") or {}).get("en", [""])[0],  # the line and its question
               "ask_ko": (r.get("ask") or {}).get("ko", [""])[0], "coverage": r.get("coverage", "none"),  # in both languages
               "covered_by": [str(x[0]) for x in r.get("covered_by") or []],  # the scenes that answer it
               **({"rounds": list(r.get("rounds") or []), "source": r.get("source") or ""} if kind == "asked" else {})} for r in rows if r.get("kind") == kind]  # an asked one: its rounds
        if qs:  # only categories with questions
            cats.append({"kind": kind, "questions": qs})  # one column of the board
    answered = {}  # question id -> the draft scene that answers it
    for f in job.draft_files():  # each draft file
        answered.update(drafted_for(f.read_text(encoding="utf-8")))  # the questions they were written for
    was_none = 0  # questions with no script that a draft answers now
    drafts = {it["id"] for it in items if it.get("draft")}  # the agent's scripts no person has taken over yet
    for c in cats:  # the map was made before the drafts: a question a draft answers says so
        for q in c["questions"]:  # each question
            if q["coverage"] in ("none", "weak") and q["id"] in answered:  # no scene, or one only in part (an earlier round's question), and a draft written for it now
                was_none += q["coverage"] == "none"
                q["coverage"], q["covered_by"] = "draft", [answered[q["id"]]]  # its lamp says a draft waits for review
            elif q["coverage"] in ("strong", "weak") and q["covered_by"] and q["covered_by"][0] in drafts:  # the script that answers it best is a draft
                q["coverage"] = "draft"  # never a finished script's green
    scripts = []  # the cards
    for it in items:  # each scene
        if it.get("role") not in ("scenes", "deep"):  # notes and term lists are not scripts
            continue  # skipped
        tt = turns(it.get("md", ""))  # its dialogue
        if not tt:  # a scene without dialogue
            continue  # nothing to show as a script
        scripts.append({"id": it["id"], "title_en": it.get("ten") or "", "title_ko": it.get("tko") or "",  # the card's head
                        "category": it.get("cat") or "", "key": it.get("key") or "", "note": it.get("note") or "",  # its core and caution
                        "turns": tt, "draft": bool(it.get("draft"))})  # the dialogue
    drafted = sum(1 for s in scripts if s["draft"])  # the scripts that are the agent's drafts (the page says how many of the scripts)
    counts = {"questions": len(rows), "scripts": len(scripts), "uncovered": sum(1 for r in rows if r.get("coverage") == "none") - was_none, "drafted": drafted}  # the board's totals
    if not scripts:  # a kit with no script yet: nothing to print (C3-14: "대본 0개" with a print key, a cue page of 0 cards)
        base = {**base, "cue": {**base["cue"], "available": False}, "deck": {**base["deck"], "available": False}}
    return {"ready": True, "categories": cats, "scripts": scripts, "counts": counts, **base}  # the board


KIT_CACHE: dict[tuple, tuple] = {}  # (job, kit files' times) -> coverage: the board takes seconds to read (the Insights view asks for every open job)


def kit_coverage(api, jid: str) -> tuple[dict | None, int]:
    """({strong, draft, weak, none} of the kit's likely questions, scripts) for one job's interview kit, or (None, 0). A question
    an agent's draft answers is counted as such: left out, a kit of drafts read as a map with nothing answered."""
    try:
        kd = api.ws.job_dir(jid) / "interview"                                      # the kit's notes
    except ValueError:                                                              # deleted for good while the numbers were counted
        return None, 0
    key = (jid, tuple(sorted((f.name, f.stat().st_mtime) for f in kd.iterdir() if f.is_file())) if kd.is_dir() else (), kit_stamp(api, jid))
    if key in KIT_CACHE:                                                            # nothing in the kit changed since
        return KIT_CACHE[key]
    try:
        b = board(api.tasks, jid, "ko")                                             # the questions with how the scripts cover them
    except Exception:                                                               # a kit half made: no numbers rather than no view
        return None, 0
    if not b.get("ready"):                                                          # no kit folder yet
        return None, 0
    c = Counter(q.get("coverage") or "none" for cat in b.get("categories") or [] for q in cat.get("questions") or [])
    out = ({k: c.get(k, 0) for k in ("strong", "draft", "weak", "none")}, len(b.get("scripts") or []))   # the drafts apart, as the map draws them
    for k in [k for k in KIT_CACHE if k[0] == jid]:                                 # the job's older numbers go
        del KIT_CACHE[k]
    KIT_CACHE[key] = out
    return out


# ---------------------------------------------------------------- the kit's files, as the Library opens them


def kit_file(ws, jid: str, name: str, out: bool = False) -> Path | None:
    """One file of a job's interview kit: its notes (jobs/<job>/interview) or what its maker wrote (out/interview/<job>)."""
    if out:  # the made deck and plan, and the agent's drafted scripts
        f = ws.path("out", "interview", jid, name) if name in KIT_OUT else ws.path("out", "interview", jid, "drafts", name) if DRAFT_FILE.match(name) else None
    else:  # the kit's own notes
        f = ws.job_dir(jid) / "interview" / name if KIT_FILE.match(name) and Path(name).name == name else None
    return f if f is not None and f.is_file() else None


def library_files(ws, jid: str) -> list[tuple[str, Path]]:
    """The files of a job's kit the Library lists, in its order, each with what it is: "note" for the person's scripts and
    notes (the kit's own workings stay out), "draft" for a file of scripts the agent drafted, "made" for the deck and the
    plan the kit's maker wrote. None before the kit's folder is made."""
    kd = ws.job_dir(jid) / "interview"  # the interview kit's notes
    if not kd.is_dir():
        return []
    out = [("note", f) for f in sorted(kd.iterdir()) if f.is_file() and KIT_FILE.match(f.name) and f.name not in KIT_MADE]  # the person's scripts and notes
    dd = ws.path("out", "interview", jid, "drafts")  # the scripts the agent drafted for this job
    out += [("draft", f) for f in (sorted(dd.glob("drafts-*.md")) if dd.is_dir() else []) if f.is_file() and DRAFT_FILE.match(f.name)]  # in the order they were written, never the rejected scenes beside them
    out += [("made", f) for f in (kit_file(ws, jid, name, out=True) for name in KIT_OUT) if f]  # the deck and plan the kit's maker wrote
    return out


def drop_outputs(ws, jid: str) -> None:
    """A job deleted for good: what its kit's maker wrote goes too (out/interview/<job>: the map, the drafts, the deck)."""
    shutil.rmtree(ws.path("out", "interview", jid), ignore_errors=True)  # a file held open stays: nothing else depends on it


# ---------------------------------------------------------------- scenes brought in, a kit carried, when its map was made


GENERAL = "-general"  # the edition with no job (the documents' drafts.GENERAL has the same name)
SCENE_ROLES = (("deep", "deep"), ("terms", "terms"), ("english", "reference"), ("notes", "reference"), ("research", "reference"))  # a kit file's role by the start of its name


def add_scenes(api, jid: str, name: str, data: bytes) -> dict:
    """Interview scenes written before (the kit's own markdown: "### Q1. question" headings with 핵심, 면접관 and 나 lines) into
    the job's interview folder, beside the ones the agent writes. Refused when the file holds no scene. Returns how many."""
    from interview import corpus  # src/interview/corpus.py: the scene reader the search view uses
    jid = api.need_job({"job": jid})  # which job
    try:
        text = data.decode("utf-8-sig")  # the kit's files are UTF-8
    except UnicodeDecodeError as exc:
        raise ValueError("not_scenes") from exc
    stem = re.sub(r"[^\w가-힣-]+", "_", Path(name).stem).strip("_")[:60] or "scenes"  # a safe name
    role = next((r for start, r in SCENE_ROLES if stem.lower().startswith(start)), "scenes")  # deep dives, terms and notes keep their roles
    items = corpus.parse_text(text, stem, stem[:1].upper(), role, f"{stem}.md")  # what the search view would read
    if not items:  # no scene in it
        raise ValueError("not_scenes")
    iv = api.ws.job_dir(jid) / "interview"  # the job's kit folder
    iv.mkdir(parents=True, exist_ok=True)
    dest, n = iv / f"{stem}.md", 2  # never over a file already there
    while dest.exists():
        dest, n = iv / f"{stem}-{n}.md", n + 1
    dest.write_text(text, encoding="utf-8")  # kept as written
    kit = read_json(iv / "kit.json", {}) or {}  # the kit's settings
    if kit.get("sources") is not None:  # a kit that names its files: this one joins with its role
        kit["sources"] = list(kit["sources"]) + [{"file": dest.name, "role": role}]
    elif role != "scenes":  # the default reads every file as scenes: name the roles once
        kit["sources"] = [{"file": f.name, "role": next((r for start, r in SCENE_ROLES if f.stem.lower().startswith(start)), "scenes")} for f in sorted(iv.glob("*.md"))]
        kit["sources"].append({"file": "@stories", "role": "reference"})  # the workspace's stories stay searchable
    write_json(iv / "kit.json", kit)  # saved
    api.tasks.ensure_kit(jid, "ko")  # the question map sees them
    return {"scenes": len(items), "file": dest.name}


def carry_kit(api, req: dict) -> dict:
    """Another application's interview kit into this one's (POST /api/v1/interview/carry {job, from, korean, names}):
    src/interview/carry.py. korean: true or false, or left out to follow this job's posting (a Korean posting is a Korean
    interview). Returns the carry's report and the question map's size."""
    from interview import carry as C  # src/interview/carry.py
    jid, src = api.need_job(req), api.need_job({"job": req.get("from")})
    if jid == src or jid == GENERAL:
        raise ValueError("job")
    src_iv = api.ws.job_dir(src) / "interview"
    if not src_iv.is_dir():
        raise ValueError("no_kit")
    korean = req.get("korean")
    if not isinstance(korean, bool):  # this job's posting decides: mostly Hangul is a Korean interview
        text = api.ws.posting(jid)
        letters = re.findall(r"[A-Za-z가-힣]", text)
        korean = bool(letters) and sum(1 for c in letters if "가" <= c <= "힣") / len(letters) > 0.3
    names = [str(n)[:80] for n in (req.get("names") or []) if isinstance(n, str) and n.strip()][:20]
    iv = api.ws.job_dir(jid) / "interview"  # the files a carry may write, every one of them in its undo step
    cands = [iv / "kit.json", iv / "alts.json", iv / "names.txt"]
    for s in C.kit_sources(src_iv):
        if not s["file"].startswith("@"):
            stem = Path(s["file"]).stem
            cands += [iv / s["file"], iv / f"{stem}-carried.md"] + [iv / f"{stem}-carried-{n}.md" for n in range(2, 10)]
    st = api.ws.job(jid)  # its name, for the undo key
    with api.ws.lock, api.ws.change({"code": "undo_carry", "company": st.get("company") or st.get("role")}, [str(p.relative_to(api.ws.root)) for p in cands]):   # one undo takes the carry back
        report = C.carry(src_iv, iv, korean=korean, names=names, job_from=src)
    api.tasks.let_kit_go(jid)  # its server reads the new files
    report["questions"] = len(api.tasks.ensure_kit(jid, "ko" if korean else "en"))  # the map sees them
    report["korean"] = korean
    return report


def kit_stamp(api, job_id: str) -> float:
    """When the job's interview map was last written (0 when there is no kit): the page reads the board again on a change."""
    if not (api.ws.job_dir(job_id) / "interview").is_dir():  # no kit folder
        return 0.0  # never made
    f = api.ws.path("out", "interview", job_id, "plan.json")  # where the tailor step writes the map (src/interview's out_dir)
    return round(f.stat().st_mtime, 3) if f.is_file() else 0.0  # its time, or 0 before the first map
