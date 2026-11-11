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
import urllib.parse  # a job's id in the kit's address
import urllib.request  # the kit's health

from pathlib import Path  # paths

from .workspace import read_json  # files

KIT = Path(__file__).resolve().parents[2] / "src" / "interview"  # the interview kit's code

KINDS = ("behavioral", "company", "scenario", "technical", "posting", "resume", "portfolio", "term", "opening")  # the map's categories, the likeliest first
TURN = re.compile(r"^\*\*(면접관|나|Interviewer|Me|해석|Translation)\*\*\s*(.*)$")  # one line of a script, by its bold label
WHO = {"면접관": "interviewer", "Interviewer": "interviewer", "나": "me", "Me": "me"}  # the speakers


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


def board(tasks, job_id: str, lang: str = "ko") -> dict:
    """The studio's board for one job. ready is False until the tailor step made the kit folder."""
    jd = tasks.ws.job_dir(job_id)  # the job's folder
    url = "/kit/" + urllib.parse.quote(job_id, safe="") + "/"  # the kit at the panel's own address (web.py kit_proxy), on any port the panel runs on
    ready = tasks.interview_available() and (jd / "interview").is_dir()  # a kit to show: the tailor step made its folder
    up = ready and job_id in tasks.kit_srvs  # this job's own kit server runs (tasks.kit_url); a job without a kit never asks a port
    base = {"search": {"up": bool(up), "url": url},  # the search view
            "practice": {"available": (KIT / "practice.py").is_file(), "url": url + "#practice"},  # practice opens directly at #practice
            "cue": {"available": (KIT / "cue.py").is_file(), "url": url + "cue"},  # the printable cue cards
            "deck": {"available": (KIT / "deck.py").is_file(), "url": url + "deck"}}  # the printable interview deck
    if not ready:  # no kit yet
        return {"ready": False, "categories": [], "scripts": [], "counts": {"questions": 0, "scripts": 0, "uncovered": 0}, **base}  # the page offers to make it
    from interview import corpus  # the scene files
    from interview.job import Job  # the kit's job folder
    job = Job(jd, confined=True)  # the kit, kept inside the workspace
    plan = read_json(job.out_dir() / "plan.json", {}) or {}  # the map the tailor step wrote
    rows = plan.get("questions") or []  # its entries
    if not rows:  # an older kit without a map
        from interview import plan as ivplan  # the question map
        rows = ivplan.build(job)  # made now, no model
    cats = []  # by category
    for kind in KINDS:  # in the map's order
        qs = [{"id": r["id"], "text": r.get("text", ""), "ask_en": (r.get("ask") or {}).get("en", [""])[0],  # the line and its question
               "ask_ko": (r.get("ask") or {}).get("ko", [""])[0], "coverage": r.get("coverage", "none"),  # in both languages
               "covered_by": [str(x[0]) for x in r.get("covered_by") or []]} for r in rows if r.get("kind") == kind]  # the scenes that answer it
        if qs:  # only categories with questions
            cats.append({"kind": kind, "questions": qs})  # one column of the board
    items, _ = corpus.load(job)  # the scenes, the agent's drafts among them
    answered = {}  # question id -> the draft scene that answers it
    for f in job.draft_files():  # each draft file
        answered.update(drafted_for(f.read_text(encoding="utf-8")))  # the questions they were written for
    for c in cats:  # the map was made before the drafts: a question a draft answers says so
        for q in c["questions"]:  # each question
            if q["coverage"] == "none" and q["id"] in answered:  # no scene yet, a draft now
                q["coverage"], q["covered_by"] = "draft", [answered[q["id"]]]  # its lamp says a draft waits for review
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
    drafted = sum(1 for c in cats for q in c["questions"] if q["coverage"] == "draft")  # questions a draft answers
    counts = {"questions": len(rows), "scripts": len(scripts), "uncovered": sum(1 for r in rows if r.get("coverage") == "none") - drafted, "drafted": drafted}  # the board's totals
    return {"ready": True, "categories": cats, "scripts": scripts, "counts": counts, **base}  # the board
