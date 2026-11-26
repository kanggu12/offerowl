"""The applications service's endpoints, as the gateway (apps/api/routes.py) gathers them: each path or pattern with its
handler. A read answers (status, answer, content type); a write answers the fields of its {"ok": true, ...}, or None; an
upload keeps the file it was sent (core/routing.py says how a table is read)."""
from __future__ import annotations

import re  # paths
import urllib.parse  # job ids in paths

from ...core.routing import JSON, FileAnswer, NotFound, Upload, lang_of  # the answers' shapes, an upload's route, a request's language
from . import answers, jobs, materials, postings, tracker  # the form's answers, the jobs, a job's own materials, where its posting is kept, the board

JOB = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)$")  # one job, with its posting
FIT = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/fit$")  # its fit, line by line
MATERIAL = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/materials(?:/(m\d{1,6})(?:/(preview|pages/(\d{1,4})\.png))?)?$")  # a job's materials, one of them, its preview or a page picture of it


# ------------------------------------------------------------------ reads


def get_jobs(a, q, m):
    """GET /api/v1/jobs: every job, with fits and editions."""
    return 200, {"jobs": jobs.jobs_view(a)}, JSON  # with fits and editions


def get_material(a, q, m):
    """GET /api/v1/jobs/<job>/materials[/<id>[/preview|/pages/<n>.png]]: the list, one file, its preview or one of its page pictures."""
    jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
    if not m.group(2):  # the list
        return 200, {"materials": materials.listing(a.ws, jid)}, JSON  # in the order they came
    rec = materials.find(a.ws, jid, m.group(2))  # still on the list
    if not rec:  # taken off, or never there
        raise NotFound(m.group(0))  # 404
    if m.group(3) == "preview":  # what the page shows of it
        return 200, materials.preview(a.tasks, jid, rec), JSON  # pages, text, blocks, a frame or a picture
    if m.group(4):  # one page picture of its preview
        f = materials.page_file(a.ws, jid, rec, int(m.group(4)))  # only a page made from this very file
        if not f:  # not made, or past its last page
            raise NotFound(m.group(0))  # 404
        return 200, f.read_bytes(), "image/png"  # the picture
    data, ctype, headers = materials.answer(a.ws, jid, rec)  # the file byte for byte, with its type and name
    return 200, FileAnswer(data, headers), ctype  # web.py adds the headers


def get_job(a, q, m):
    """GET /api/v1/jobs/<job>: one job's card with the summary, and its posting."""
    jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
    job = next((j for j in jobs.jobs_view(a) if j["id"] == jid), None)  # its card with the summary
    if job is None:  # the general edition or a named one: an edition, not an application with a card
        raise NotFound(m.group(0))
    return 200, {**job, "posting": postings.posting_file(a.ws, jid).read_text(encoding="utf-8")}, JSON  # and the posting


def get_fit(a, q, m):
    """GET /api/v1/jobs/<job>/fit: the fit, line by line."""
    jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
    return 200, jobs.fit_of(a, jid), JSON  # cached until something changes


def get_tracker(a, q, m):
    """GET /api/v1/tracker: the board, the timeline and what is due."""
    cards = jobs.jobs_view(a)  # every job
    return 200, {"stages": ["preparing", "submitted", "interview", "result"], "jobs": cards,  # the columns and cards
                 "timeline": tracker.timeline(cards), "due": tracker.due(cards)}, JSON  # the timeline and the due reminders


def get_due(a, q, m):
    """GET /api/v1/reminders/due: the reminders due and not done (the desktop app and the panel ask this)."""
    return 200, {"due": tracker.due(jobs.jobs_view(a))}, JSON  # due and not done


def get_ics(a, q, m):
    """GET /api/v1/reminders.ics[?job=<job>&lang=ko|en]: the open reminders and the rounds from today on, for the person's
    calendar: one application's with job, every application's without; the rounds named in lang (the panel's language)."""
    cards = jobs.jobs_view(a)  # every job
    if q.get("job"):  # one application's, from its Progress tab
        jid = a.need_job({"job": str(q.get("job"))})  # it exists (an id from before a rename finds it)
        cards = [c for c in cards if c["id"] == jid]  # that one only
    return 200, tracker.ics(cards, lang_of(q.get("lang"))).encode("utf-8"), "text/calendar; charset=utf-8"  # a file to open


# ------------------------------------------------------------------ writes


def post_job(a, req, path):
    """POST /api/v1/jobs: a pasted posting or a link."""
    jid = jobs.add_job(a, req)  # its folder and card
    a.tasks.analyze(jid, agent=False, step=False)  # the analysis starts at once, by words: adding a job sends nothing to the agent; the add's step holds its plan
    return {"job": jid}  # the new job's id


def post_select(a, req, path):
    """POST /api/v1/jobs/select: another job in view."""
    a.ws.set_prefs(job=a.need_job(req))  # remembered with the workspace
    return None  # the new state is the whole answer


def post_rename(a, req, path):
    """POST /api/v1/jobs/rename: a job's id (its folder and every address) changed: ASCII, unused; the old one stays an alias."""
    return {"job": jobs.rename_job(a, req)}  # the new id


def post_analyze(a, req, path):
    """POST /api/v1/jobs/analyze: analyze the posting again."""
    return {"started": a.tasks.analyze(a.need_job(req))}  # False when one already runs


def post_posting(a, req, path):
    """POST /api/v1/jobs/posting: a job's posting written again (the part with the duties pasted in), read again at once."""
    jid = a.need_job(req)  # which job
    jobs.set_posting(a, jid, str(req.get("posting") or ""))  # one undo step
    return {"job": jid, "started": a.tasks.analyze(jid, agent=False, step=False)}  # by words: nothing goes to the agent; the paste's step holds the plan


def post_remove(a, req, path):
    """POST /api/v1/jobs/remove: off the board, or a named edition off the list (undo or the Removed list brings it back)."""
    jobs.board(a, {"job": a.need_job(req), "removed": True})  # through the board: one undo step
    return None  # the new state is the whole answer


def post_edit(a, req, path):
    """POST /api/v1/tracker/edit: a card moved or edited."""
    jobs.board(a, req)  # one undo step
    return None  # the new state is the whole answer


def post_clear_day(a, req, path):
    """POST /api/v1/tracker/clear_day: the day a batch of applications was added, off their stages."""
    return {"cleared": jobs.clear_batch_day(a, str(req.get("day") or ""))}  # the cards changed; the new state is drawn


def post_next(a, req, path):
    """POST /api/v1/tracker/next: a card's move-on button."""
    jobs.next_stage(a, a.need_job(req))  # one column right
    return None  # the new state is the whole answer


def post_reminder(a, req, path):
    """POST /api/v1/reminders: add, finish or remove a reminder."""
    return {"reminder": jobs.reminder(a, req)}  # the new one, if any


def post_round(a, req, path):
    """POST /api/v1/tracker/round: add, change or remove an interview round: its kind, day, the questions asked, notes."""
    return {"round": jobs.set_round(a, req)}  # the round as kept, or null once removed


def post_material_remove(a, req, path):
    """POST /api/v1/jobs/materials/remove: a job's material off its list (its file stays, and undo brings it back)."""
    materials.remove(a.ws, a.need_job(req), str(req.get("id") or ""))  # one undo step
    return None  # the new state is the whole answer


def post_material_export(a, req, path):
    """POST /api/v1/jobs/materials/export: a copy of a job's material on the Desktop, byte for byte."""
    return {"exported": materials.export(a.ws, a.need_job(req), str(req.get("id") or ""))}  # the name written, for the page's message


def post_questions(a, req, path):
    """POST /api/v1/jobs/questions: a job's application questions, in order."""
    answers.set_questions(a, req)  # checked and kept
    return None  # the new state is the whole answer


def post_paste(a, req, path):
    """POST /api/v1/jobs/questions/paste: a form's questions pasted as it shows them, read with their limits."""
    return {"added": answers.paste_questions(a, req)}  # how many came in


def post_write(a, req, path):
    """POST /api/v1/jobs/questions/write: their answers, by the agent."""
    return {"started": a.tasks.answers(a.need_job(req), [str(x) for x in req.get("ids") or []] or None)}  # False when they are being written


def post_answer(a, req, path):
    """POST /api/v1/jobs/questions/edit: the person's own words for one answer."""
    answers.edit_answer(a, req)  # checked and kept
    return None  # the new state is the whole answer


def post_answers_export(a, req, path):
    """POST /api/v1/jobs/questions/export: the questions and answers as a text file on the Desktop."""
    return {"exported": a.tasks.export_answers(a.need_job(req))}  # the name written


# ------------------------------------------------------------------ uploads


def upload_questions(a, q, name, data):
    """POST /api/v1/jobs/questions/file?job=: a picture or a file of an application form, its questions read (OCR for a picture) and added."""
    return {"added": answers.questions_from_file(a, str(q.get("job") or ""), name, data)}  # read and added; the page draws them


def upload_material(a, q, name, data):
    """POST /api/v1/jobs/materials?job=: one file for a job's own materials (a deck, notes, a brief, an answer, a solution),
    kept byte for byte. A kind a job does not keep is refused with material_kind; the name comes whole (its extension is its
    kind: materials.add shortens it)."""
    return {"material": materials.add(a.ws, a.ws.resolve_job(str(q.get("job") or "")), name, data)}  # the job named in the query (an id from before a rename finds it, as on every other route)


GET = (  # the reads
    ("/api/v1/jobs", get_jobs),
    (MATERIAL.match, get_material),
    (JOB.match, get_job),
    (FIT.match, get_fit),
    ("/api/v1/tracker", get_tracker),
    ("/api/v1/reminders/due", get_due),
    ("/api/v1/reminders.ics", get_ics),
)
POST = (  # the writes
    ("/api/v1/jobs", post_job),
    ("/api/v1/jobs/select", post_select),
    ("/api/v1/jobs/rename", post_rename),
    ("/api/v1/jobs/analyze", post_analyze),
    ("/api/v1/jobs/posting", post_posting),
    ("/api/v1/jobs/remove", post_remove),
    ("/api/v1/tracker/edit", post_edit),
    ("/api/v1/tracker/clear_day", post_clear_day),
    ("/api/v1/tracker/next", post_next),
    ("/api/v1/reminders", post_reminder),
    ("/api/v1/tracker/round", post_round),
    ("/api/v1/jobs/materials/remove", post_material_remove),
    ("/api/v1/jobs/materials/export", post_material_export),
    ("/api/v1/jobs/questions", post_questions),
    ("/api/v1/jobs/questions/paste", post_paste),
    ("/api/v1/jobs/questions/write", post_write),
    ("/api/v1/jobs/questions/edit", post_answer),
    ("/api/v1/jobs/questions/export", post_answers_export),
)
UPLOADS = (  # the files sent as they are
    Upload("/api/v1/jobs/questions/file", upload_questions),  # a screenshot, a PDF or a saved page of the form
    Upload("/api/v1/jobs/materials", upload_material, cap=lambda: materials.MAX_BYTES, whole_name=True),  # under the materials' own cap, read at each upload
)
