"""The tracker: every application as a card on a board of four columns, the same cards on a timeline, and reminders
that come due on this PC (core/schema/job.schema.json: stage, dates, next, result, reminders).

The board and the timeline are two views of the jobs' status files. A reminder is a date (and maybe a time) and a
short text on a job. The panel asks for the reminders that are due and shows them, with a notification of the browser
when the person allowed one; the desktop app can ask the same address (GET /api/v1/reminders/due).
"""
from __future__ import annotations

import datetime  # due times
import re  # reminder ids and dates

from ...core.routing import text_field  # a request's text, or refused
from ...core.workspace import STAGES, today  # the board's columns, in order, and the day a card moved

MAX_REMINDERS = 20  # per job: a card is not a calendar


def is_day(text: str) -> bool:
    """A calendar day written YYYY-MM-DD, as the board's date field sends it."""
    import datetime  # only here
    try:
        return len(text) == 10 and datetime.date.fromisoformat(text).isoformat() == text  # 2026-02-30 and abcd-efghi are not days
    except ValueError:
        return False


def mark_sent(st: dict, always: bool = True) -> None:
    """A card whose documents went out moves to submitted with today's date, as the documents' lock and a sent copy kept
    ask the board. A copy kept later (always False) moves only a card still being prepared: a later stage stays."""
    if always or st.get("stage") == "preparing":  # sent: on the board it moves on
        st["stage"] = "submitted"  # on the board
        st.setdefault("dates", {})["submitted"] = today()  # the day it was submitted


def stage_days(job: dict) -> dict:
    """The days a card reached its stages, as the board, the timeline and the counts read them. A day of a stage after the
    one it is in now is left from a move taken back and does not count (at the result every earlier step does), and a
    stage's day later than a later step's cannot be when it happened (a card added or moved after it was sent or answered,
    the day of the adding stamped on it): it does not count either. The day stays on the card, for the person to set."""
    d = job.get("dates") or {}  # as kept: a move never clears the days of the stages after it
    upto = STAGES.index(job["stage"]) if job.get("stage") in STAGES else 0  # where it is now
    out = {s: d[s] for s in STAGES[: upto + 1] if d.get(s)}  # the stages it went through
    for i, s in enumerate(STAGES):  # each step against the steps after it, as they were kept
        if s in out and any(d.get(x) and x in out and str(d[x]) < str(out[s]) for x in STAGES[i + 1:]):  # it came after a later one
            del out[s]
    return out


def batch_day(jobs: list[dict]) -> dict | None:
    """The day several applications were added at once (5 or more, as when a list is brought in) whose cards carry that day
    on a stage that a later step's earlier day shows it never had: {day, jobs: [ids]}, or None. Those days are the adding's,
    not the job hunt's. A card added by hand carries its day as its preparing day, and its later steps come after it: it is
    never counted, so a busy day of adding never asks to clear true days."""
    by = {}  # the day added -> the cards added that day whose stamp a later step's day disproves
    for j in jobs:
        if j.get("kind") == "edition" or j.get("removed"):  # editions have no stages; the trash is not the board
            continue
        made, d = str(j.get("created") or "")[:10], j.get("dates") or {}  # the day it was added, its days as kept
        if made and any(str(d.get(s) or "")[:10] == made and any(d.get(x) and str(d[x])[:10] < made for x in STAGES[i + 1:])  # a later step before it
                        for i, s in enumerate(STAGES)):
            by.setdefault(made, []).append(j["id"])
    if not by:
        return None
    day, ids = max(by.items(), key=lambda kv: len(kv[1]))  # the biggest batch
    return {"day": day, "jobs": ids} if len(ids) >= 5 else None


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
ROUND_WORDS = {  # a round's kind as a calendar entry names it: the panel's own words (views.js ROUND_KIND and i18n/ko.js)
    "en": {"call": "Recruiter call", "first": "First interview", "second": "Second interview", "third": "Third interview",
           "final": "Final interview", "coding": "Coding test", "assignment": "Assignment", "culture": "Culture fit", "other": "Other round"},
    "ko": {"call": "채용 담당 통화", "first": "1차 면접", "second": "2차 면접", "third": "3차 면접", "final": "최종 면접",
           "coding": "코딩 테스트", "assignment": "과제", "culture": "컬처핏 면접", "other": "기타 면접"},
}
MAX_ROUNDS = 20  # rounds one card keeps: more than any hiring has
ROUND_TEXT = 4000  # the questions asked, or the notes, of one round: a long debrief fits


ROUND_FIELDS = ("kind", "at", "asked", "notes")  # what a round's form shows and sends back


def _round_kept(k: str, v) -> str:
    """A round's field as set_round keeps it: the words trimmed and cut to their bound, the kind and the day as sent."""
    return str(v).strip()[:ROUND_TEXT] if k in ("asked", "notes") else str(v)  # the same shape on both sides of a comparison


def check_round_start(st: dict, req: dict) -> None:
    """A change to a round sent with `was`, the round as its form started from it ({kind, at, asked, notes}): a field another
    window has changed since, which this change would overwrite with other words, refuses the whole change (D4-06: a second
    window wiped the first one's notes and answered "Round kept."). A field already holding what is sent overwrites nothing.
    A caller that sends no `was` (the command line, an agent) changes the round as before. Raises ValueError."""
    was = req.get("was")  # the round as the form started from it, when it says
    if was is None or req.get("remove") is True or not req.get("id"):  # nothing to hold against: no start, a removal, a new round
        return
    if not isinstance(was, dict):  # a start that is not one
        raise ValueError("was")
    hit = next((r for r in st.get("rounds") or [] if r.get("id") == str(req.get("id"))), None)  # the round as it is now
    if hit is None:  # set_round says the id is unknown
        return
    for k in ROUND_FIELDS:  # field by field: a window that changed only the notes never blocks a change of the day
        if k in req and isinstance(was.get(k), str) and isinstance(req[k], str):  # both the start and the new words of this field
            now = _round_kept(k, hit.get(k) or "")  # what the round holds
            if now != _round_kept(k, was[k]) and now != _round_kept(k, req[k]):  # changed since, and this would write other words over it
                raise ValueError("round_changed")  # refused, nothing overwritten: the page says so and draws the round again


def set_round(st: dict, req: dict) -> dict | None:
    """Add, change or remove one interview round on a job's status (changed in place). A new round needs a kind and a day
    (YYYY-MM-DD, or with its time YYYY-MM-DDTHH:MM); `asked` holds the questions asked, one a line, and `notes` how it went.
    Returns the round added or changed (None once removed). Raises ValueError for a bad field or an unknown id."""
    rs = st.setdefault("rounds", [])  # the card's rounds, oldest first as added
    rid = text_field(req, "id")  # which round, as text
    hit = next((r for r in rs if r.get("id") == rid), None) if rid else None  # the round asked for
    if rid and hit is None:  # an id that is not there
        raise ValueError("id")
    for k in ("at", "asked", "notes"):  # its words: text, or refused with the field's name (a list of notes was dropped without a word)
        text_field(req, k)  # refused when sent and not text
    if hit is not None and req.get("remove") is True:  # taken off the card (undo brings it back)
        rs.remove(hit)
        return None
    if hit is not None and not any(k in req for k in ("kind", "at", "asked", "notes")):  # a change that names nothing to change (D4-07)
        raise ValueError("fields")
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


ICS_LINE = 75  # octets of one line of an iCalendar file, its line end aside (RFC 5545 3.1)


def fold(line: str) -> str:
    """One content line of an iCalendar file folded as RFC 5545 asks: no line over 75 octets of UTF-8, each further line
    started by one space (which counts), and a character never cut in two (a Korean letter is three octets). A reminder's
    long words went out on one line of hundreds of octets (B4-04), which a strict calendar reads wrongly or refuses."""
    out, cur, size = [], "", 0  # the lines made, the one being filled and its octets
    for ch in line:  # one character at a time, whole
        n = len(ch.encode("utf-8"))  # its octets
        if size + n > ICS_LINE:  # it would pass the end
            out.append(cur)  # this line is full
            cur, size = " ", 1  # the next starts with its space
        cur, size = cur + ch, size + n  # on this line
    out.append(cur)  # the last part
    return "\r\n".join(out)  # folded with the format's own line end


def ics(jobs: list[dict], lang: str = "ko") -> str:
    """Every open reminder and every interview round from today on, as an iCalendar file, so the person can put them in the
    calendar they already use. A round is named by its kind in the panel's language (lang)."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # when the file was made, in UTC (utcnow() is deprecated from 3.12)
    words = ROUND_WORDS.get(lang, ROUND_WORDS["en"])  # the rounds' names
    first_day = datetime.datetime.fromisoformat(today() + "T00:00")  # a round before today is over: not for a calendar
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//offerowl//tracker//EN", "CALSCALE:GREGORIAN"]  # the calendar's head

    def entry(uid: str, when: str, at: datetime.datetime, summary: str, before: str) -> list[str]:
        """One calendar entry with its alarm (before: how long ahead it rings, as the format writes it)."""
        summary = summary.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\r", " ").replace("\n", " ")  # escaped as the format asks, on one line
        whole_day = "T" not in when  # a day without a time is an all-day entry
        start = f"DTSTART;VALUE=DATE:{at:%Y%m%d}" if whole_day else f"DTSTART:{at:%Y%m%dT%H%M%S}"  # floating local time
        return ["BEGIN:VEVENT", f"UID:{uid}@offerowl", f"DTSTAMP:{stamp}", start, f"SUMMARY:{summary}",  # one entry
                "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{summary}", f"TRIGGER:{before}", "END:VALARM", "END:VEVENT"]

    for j in jobs:  # each job
        name = str(j.get("company") or j.get("role") or j.get("id"))  # the job's name
        for r in j.get("reminders") or []:  # each reminder
            at = parse_at(r.get("at"))  # when
            if not at or r.get("done"):  # unreadable or dealt with
                continue  # left out
            lines += entry(f"{j.get('id')}-{r.get('id')}", str(r.get("at")), at, f"{name}: {r.get('text', '')}", "PT0M")  # rings when it is due
        for r in j.get("rounds") or []:  # each interview round
            at = parse_at(r.get("at"))  # when
            if not at or at < first_day:  # unreadable, or already over
                continue  # left out
            timed = "T" in str(r.get("at"))  # a round with its hour rings half an hour ahead
            lines += entry(f"{j.get('id')}-round-{r.get('id')}", str(r.get("at")), at, f"{name}: {words.get(r.get('kind'), words['other'])}",
                           "-PT30M" if timed else "PT0M")  # an all-day round rings at the day's start
    lines.append("END:VCALENDAR")  # the end
    return "\r\n".join(fold(x) for x in lines) + "\r\n"  # the format's line ends, each line folded at 75 octets
