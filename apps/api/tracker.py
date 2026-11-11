"""The tracker: every application as a card on a board of four columns, the same cards on a timeline, and reminders
that come due on this PC (core/schema/job.schema.json: stage, dates, next, result, reminders).

The board and the timeline are two views of the jobs' status files. A reminder is a date (and maybe a time) and a
short text on a job. The panel asks for the reminders that are due and shows them, with a notification of the browser
when the person allowed one; the desktop app can ask the same address (GET /api/v1/reminders/due).
"""
from __future__ import annotations

import datetime  # due times
import re  # reminder ids and dates

from .workspace import STAGES  # the board's columns, in order

MAX_REMINDERS = 20  # per job: a card is not a calendar


def stage_days(job: dict) -> dict:
    """The days a card reached its stages, as the board, the timeline and the counts read them. A day of a stage after the
    one it is in now is left from a move taken back and does not count (at the result every earlier step does), and a
    "preparing" day later than a later step's (a card added after it was sent) is not when it was prepared."""
    d = job.get("dates") or {}  # as kept: a move never clears the days of the stages after it
    upto = STAGES.index(job["stage"]) if job.get("stage") in STAGES else 0  # where it is now
    out = {s: d[s] for s in STAGES[: upto + 1] if d.get(s)}  # the stages it went through
    if out.get("preparing") and any(v < out["preparing"] for s, v in out.items() if s != "preparing"):  # prepared after it was sent
        del out["preparing"]
    return out


def timeline(jobs: list[dict]) -> list[dict]:
    """Every dated step of every job, oldest first: one entry per stage a card entered (stage_days), and each reminder."""
    out = []  # the entries
    for j in jobs:  # each job on the board
        name = j.get("company") or j.get("role") or j.get("id")  # how the timeline names it
        days = stage_days(j)  # the days that count
        for r in j.get("rounds") or []:  # each interview round, on its day
            out.append({"job": j["id"], "name": name, "kind": "round", "id": r.get("id"), "round": r.get("kind"), "at": r.get("at")})
        for stage in STAGES:  # the columns in order
            day = days.get(stage)  # the day it entered that column
            if day:  # only dated steps
                out.append({"job": j["id"], "name": name, "kind": "stage", "stage": stage, "at": day})  # one entry
        for r in j.get("reminders") or []:  # its reminders
            out.append({"job": j["id"], "name": name, "kind": "reminder", "id": r.get("id"), "at": r.get("at"),  # one entry
                        "text": r.get("text", ""), "done": bool(r.get("done"))})  # its words and whether it was dealt with
    return sorted(out, key=lambda e: (str(e["at"]), e["kind"] != "stage"))  # by date; on one day the stage first


def due(jobs: list[dict], now: datetime.datetime | None = None) -> list[dict]:
    """The reminders that are due now and not done: a date alone is due from the start of that day. An application that
    reached its result asks nothing more: its reminders stay on its page and in the calendar file, and no longer come due."""
    now = now or datetime.datetime.now()  # local time, as the person set them
    out = []  # due reminders
    for j in jobs:  # each job
        if j.get("stage") == "result":  # ended: "check the result" and the like are answered
            continue
        for r in j.get("reminders") or []:  # its reminders
            if r.get("done"):  # already dealt with
                continue  # not due
            at = parse_at(r.get("at"))  # when
            if at and at <= now:  # its time has come
                out.append({"job": j["id"], "name": j.get("company") or j.get("role") or j["id"], "id": r["id"],  # what the panel shows
                            "at": r["at"], "text": r.get("text", "")})  # and its words
    return out  # oldest first by the job order, then as written


def parse_at(text) -> datetime.datetime | None:
    """A reminder's time: "2026-11-05" (the start of that day) or "2026-11-05T09:30". None when unreadable."""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(text or "")):  # a day
            return datetime.datetime.fromisoformat(str(text) + "T00:00")  # from its start
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", str(text or "")):  # a day and a time
            return datetime.datetime.fromisoformat(str(text))  # exactly then
    except ValueError:  # 2026-13-40
        return None  # unreadable
    return None  # any other shape


def add_reminder(st: dict, at: str, text: str) -> dict:
    """Add a reminder to a job's status (changed in place). Returns it. Raises ValueError for a bad date or text."""
    if parse_at(at) is None:  # not a day or a day and a time
        raise ValueError("at")  # refused
    text = str(text or "").strip()[:1000]  # bounded, room for a meeting's long link
    if not text:  # a reminder needs words
        raise ValueError("text")  # refused
    rs = st.setdefault("reminders", [])  # the job's reminders
    if len(rs) >= MAX_REMINDERS:  # enough on one card
        raise ValueError("too_many")  # refused
    n = 1 + max([int(r["id"][1:]) for r in rs if re.fullmatch(r"r\d+", str(r.get("id")))] or [0])  # the next id
    rec = {"id": f"r{n}", "at": at, "text": text, "done": False}  # the reminder
    rs.append(rec)  # on the card
    return rec  # for the answer


ROUND_KINDS = ("call", "first", "second", "third", "final", "coding", "assignment", "culture", "other")  # an interview round's kind
MAX_ROUNDS = 20  # rounds one card keeps: more than any hiring has
ROUND_TEXT = 4000  # the questions asked, or the notes, of one round: a long debrief fits


def set_round(st: dict, req: dict) -> dict | None:
    """Add, change or remove one interview round on a job's status (changed in place). A new round needs a kind and a day
    (YYYY-MM-DD, or with its time YYYY-MM-DDTHH:MM); `asked` holds the questions asked, one a line, and `notes` how it went.
    Returns the round added or changed (None once removed). Raises ValueError for a bad field or an unknown id."""
    rs = st.setdefault("rounds", [])  # the card's rounds, oldest first as added
    rid = str(req.get("id") or "")
    hit = next((r for r in rs if r.get("id") == rid), None) if rid else None  # the round asked for
    if rid and hit is None:  # an id that is not there
        raise ValueError("id")
    if hit is not None and req.get("remove") is True:  # taken off the card (undo brings it back)
        rs.remove(hit)
        return None
    rec = dict(hit) if hit is not None else {}  # what is changed, or a new one
    if hit is None or "kind" in req:  # a new round names its kind
        if req.get("kind") not in ROUND_KINDS:
            raise ValueError("kind")
        rec["kind"] = req["kind"]
    if hit is None or "at" in req:  # and its day
        if parse_at(req.get("at")) is None:
            raise ValueError("at")
        rec["at"] = str(req["at"])
    for k in ("asked", "notes"):  # its words, as typed
        if isinstance(req.get(k), str):
            rec[k] = req[k].strip()[:ROUND_TEXT]
    if hit is None:  # a new one: its id
        if len(rs) >= MAX_ROUNDS:
            raise ValueError("too_many")
        n = 1 + max([int(r["id"][1:]) for r in rs if re.fullmatch(r"i\d+", str(r.get("id")))] or [0])
        rec["id"] = f"i{n}"
        rs.append(rec)
    else:
        rs[rs.index(hit)] = rec
    rs.sort(key=lambda r: r.get("at") or "")  # in the order they happen
    return rec


def set_reminder(st: dict, rid: str, done: bool | None = None, remove: bool = False) -> None:
    """Mark a reminder done (or not), or remove it. Raises ValueError for an unknown id."""
    rs = st.get("reminders") or []  # the job's reminders
    hit = next((r for r in rs if r.get("id") == rid), None)  # the one asked for
    if hit is None:  # not on this card
        raise ValueError("reminder")  # refused
    if remove:  # taken off
        rs.remove(hit)  # gone
    elif done is not None:  # dealt with, or not after all
        hit["done"] = bool(done)  # the new state


def ics(jobs: list[dict]) -> str:
    """Every open reminder as an iCalendar file, so the person can put them in the calendar they already use."""
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")  # when the file was made
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//offerowl//tracker//EN", "CALSCALE:GREGORIAN"]  # the calendar's head
    for j in jobs:  # each job
        for r in j.get("reminders") or []:  # each reminder
            at = parse_at(r.get("at"))  # when
            if not at or r.get("done"):  # unreadable or dealt with
                continue  # left out
            name = str(j.get("company") or j.get("role") or j.get("id"))  # the job's name
            summary = f"{name}: {r.get('text', '')}".replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", " ")  # escaped as the format asks
            whole_day = "T" not in str(r.get("at"))  # a day without a time is an all-day entry
            start = f"DTSTART;VALUE=DATE:{at:%Y%m%d}" if whole_day else f"DTSTART:{at:%Y%m%dT%H%M%S}"  # floating local time
            lines += ["BEGIN:VEVENT", f"UID:{j.get('id')}-{r.get('id')}@offerowl", f"DTSTAMP:{stamp}", start,  # one entry
                      f"SUMMARY:{summary}", "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{summary}", "TRIGGER:PT0M", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")  # the end
    return "\r\n".join(lines) + "\r\n"  # the format's line ends
