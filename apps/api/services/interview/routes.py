"""The interview service's endpoints, as the gateway (apps/api/routes.py) gathers them: each path or pattern with its
handler. A read answers (status, answer, content type); a write answers the fields of its {"ok": true, ...}, or None; an
upload keeps the file it was sent (core/routing.py says how a table is read)."""
from __future__ import annotations

import re  # paths and a script's ids
import urllib.parse  # job ids in paths

from ...core.routing import JSON, HeadAnswer, NotFound, Upload, cheap_head, lang_of  # the answers' shapes, a cheap HEAD, an upload's route, the request's language
from . import studio  # the interview board

PART = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/(interview|interview/view|interview/deck|talk|talk/script)$")  # its interview board, what the script view and the deck read, its talk or the talk's script
TALKSLIDE = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/talk/slides/(\d{1,3})\.png$")  # a picture of one of the talk's slides, by its place, for the script the panel draws


# ------------------------------------------------------------------ reads


def head_part(a, q, m):
    """HEAD of a job's interview parts: the job checked, and for the script view and the deck whether it has a kit, with no
    kit server started and no megabytes made (D4-04)."""
    jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
    if m.group(2) in ("interview/view", "interview/deck") and not studio.has_kit(a.ws, jid):  # no kit yet: as the GET says
        return 404, HeadAnswer(), JSON
    return 200, HeadAnswer(), JSON


@cheap_head(head_part)
def get_part(a, q, m):
    """GET /api/v1/jobs/<job>/interview, /interview/view, /interview/deck, /talk and /talk/script."""
    jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
    if m.group(2) == "interview":  # the studio's board
        return 200, studio.board(a.tasks, jid, lang_of(q.get("lang"))), JSON  # questions and scripts
    if m.group(2) == "interview/view":  # every script with its words, for the panel's own contents, search and cards
        view = a.tasks.kit_view(jid, lang_of(q.get("lang")))  # in the panel's language
        if view is None:  # no kit yet, or it would not start
            return 404, {"error": "no_kit"}, JSON
        return 200, view, JSON
    if m.group(2) == "interview/deck":  # the interview deck's scripts in its order, for the panel's own deck
        got = a.tasks.kit_deck(jid, lang_of(q.get("lang")))  # in the panel's language
        if got is None:  # no kit yet, or it could not be read
            return 404, {"error": "no_kit"}, JSON
        return 200, got, JSON
    if m.group(2) == "talk/script":  # the talk's speaker script, for the panel to draw: every slide with its time and its words
        got = a.tasks.talk_script(jid)  # as the printed script holds it
        if got is None:  # no talk made yet
            return 404, {"error": "no_talk"}, JSON
        return 200, got, JSON
    return 200, a.tasks.talk_state(jid), JSON  # the presentation interview: its brief, and the talk when it is made


def get_talk_slide(a, q, m):
    """GET /api/v1/jobs/<job>/talk/slides/<n>.png: one of the talk's slides as a picture, by its place among the talk's
    pictures, never a name from the request."""
    f = a.tasks.talk_slide(a.need_job({"job": urllib.parse.unquote(m.group(1))}), int(m.group(2)))  # the job exists, the place is a number
    if f is None:  # no talk, or no picture there
        raise NotFound(m.group(0))
    return 200, f.read_bytes(), "image/png"


# ------------------------------------------------------------------ writes


def post_carry(a, req, path):
    """POST /api/v1/interview/carry: another application's interview kit into this one's (src/interview/carry.py)."""
    return studio.carry_kit(a, req)  # what was carried, left behind and renumbered


def post_kit(a, req, path):
    """POST /api/v1/interview/kit: make the interview kit without tailoring the rest."""
    jid = a.need_job(req)  # which job
    return studio.make_map(a, jid, lang_of(req.get("lang")))  # the map's size, as an undo step of its own


def post_scripts(a, req, path):
    """POST /api/v1/interview/scripts: more scripts, the likeliest questions first, or the map's entries named in ids."""
    jid = a.need_job(req)  # which job
    ids = req.get("ids")  # a round's questions without a script, as the board names them
    if ids is not None and (not isinstance(ids, list) or not 0 < len(ids) <= 30 or not all(isinstance(x, str) and re.fullmatch(r"[a-z][a-z0-9]{0,15}", x) for x in ids)):
        raise ValueError("bad_ids")  # 400: a list of up to 30 of the map's ids
    # a submitted application still gets ready for its interview: the scripts go to the kit's own folder, and the
    # submitted copies stay as they went
    return {"started": a.tasks.write_scripts(jid, lang_of(req.get("lang")), ids=ids), "task": f"scripts:{jid}"}  # the task's key


def post_talk_brief(a, req, path):
    """POST /api/v1/interview/talk/brief: the presentation interview's brief: topics, minutes, day, format, the interviewers' words."""
    jid = a.need_job(req)  # which job
    return {"brief": a.tasks.save_talk_brief(jid, req.get("brief"))}  # as kept; a brief with no topic is refused (400 bad_brief)


def post_talk(a, req, path):
    """POST /api/v1/interview/talk: make the talk: its deck from the portfolio and its script (task talk:<job>)."""
    jid = a.need_job(req)  # which job
    return {"started": a.tasks.make_talk(jid, lang_of(req.get("lang"))), "task": f"talk:{jid}"}  # the task's key


def post_talk_deliver(a, req, path):
    """POST /api/v1/interview/talk/deliver: the talk's slides and script on the Desktop."""
    jid = a.need_job(req)  # which job
    return {"files": a.tasks.deliver_talk(jid)}  # the names written


def post_start(a, req, path):
    """POST /api/v1/interview/start: serve the kit's search view, at the panel's /kit/<job>/."""
    return {"started": bool(a.tasks.kit_url(a.need_job(req)))}  # this job's own kit server; False when it could not start


# ------------------------------------------------------------------ uploads


def upload_scenes(a, q, name, data):
    """POST /api/v1/interview/scenes?job=&join=: a file of interview scenes (the kit's markdown) into a job's interview folder;
    join names the step of the same pick's earlier file, so every file of one pick is one undo step."""
    return studio.add_scenes(a, str(q.get("job") or ""), name, data, join=str(q.get("join") or "")[:64] or None)  # the job named in the query; the page draws the new scenes


GET = (  # the reads
    (PART.match, get_part),
    (TALKSLIDE.match, get_talk_slide),
)
POST = (  # the writes
    ("/api/v1/interview/carry", post_carry),
    ("/api/v1/interview/kit", post_kit),
    ("/api/v1/interview/scripts", post_scripts),
    ("/api/v1/interview/talk/brief", post_talk_brief),
    ("/api/v1/interview/talk", post_talk),
    ("/api/v1/interview/talk/deliver", post_talk_deliver),
    ("/api/v1/interview/start", post_start),
)
UPLOADS = (  # the files sent as they are
    Upload("/api/v1/interview/scenes", upload_scenes),  # interview scripts written before
)
