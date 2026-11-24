"""The documents service's endpoints, as the gateway (apps/api/routes.py) gathers them: each path or pattern with its
handler. A read answers (status, answer, content type); a write answers the fields of its {"ok": true, ...}, or None; an
upload keeps the file it was sent (core/routing.py says how a table is read)."""
from __future__ import annotations

import re  # paths
import urllib.parse  # job ids in paths

from ...core.routing import JSON, NotFound, Upload, lang_of  # the answers' shapes, an upload's route, the request's language
from . import documents, editions, task_export  # the canvas's models and its edits, own and named editions, the copies that went out
from .delivery import desktop_dir, open_in_files  # the Desktop and the file manager
from .task_build import THEMES  # the colour packs a build takes

FILE = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/files/(ko|en)/(preview/[rdc]-\d+\.png|preview/changes\.png|resume\.pdf|resume\.txt|deck\.pdf|cover\.pdf)$")  # an edition's files, and the picture of what it changed since its baseline
DECK = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/deck/(ko|en)$")  # a job's deck as it will print, for the canvas
FIGURE = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/figures/(ko|en)/(timeline|stack|logo_[A-Za-z0-9_-]{1,80})\.png$")  # a picture the printed resume carries, for the canvas
DEPTH = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/depth$")  # an edition's depth review


def unlocked(a, jid: str | None) -> str | None:
    """The job a write names, refused once it was submitted and locked: its sentences, its letter and its deck stay as they
    went out (tailoring and building it again are refused the same way). The general edition (None) is never locked."""
    if jid and (a.ws.job(jid) or {}).get("locked"):  # submitted: the copies that went out are kept as they went
        raise ValueError("locked")  # the page says the application was submitted and locked
    return jid  # free to change


def theme_of(v) -> str:
    """A colour pack from a request: one of src/themes.json's (task_build.THEMES), navy when unknown."""
    return v if v in THEMES else "navy"  # only the packs there are


def pages_of(v) -> int:
    """A page limit from a request: 1 to 7, three when unreadable. A long career's English description runs to seven."""
    return max(1, min(int(v), 7)) if str(v or "").isdigit() else 3  # digits only


# ------------------------------------------------------------------ reads


def get_resume(a, q, m):
    """GET /api/v1/documents/resume: the canvas's resume."""
    job = q.get("job") or None  # the job in view, if any
    if job:  # a job's order applies
        a.need_job({"job": job})  # it exists
    return 200, documents.resume(a.tasks, lang_of(q.get("lang")), theme_of(q.get("theme")), job), JSON  # blocks and sentences


def get_cover(a, q, m):
    """GET /api/v1/documents/cover: the canvas's cover letter."""
    jid = a.need_job({"job": q.get("job")})  # its job
    return 200, documents.cover(a.tasks, jid, lang_of(q.get("lang"))), JSON  # paragraphs and sentences


def get_editions(a, q, m):
    """GET /api/v1/editions: the editions with words of their own, to start a job's edition from (editions.py)."""
    job = a.need_job({"job": q["job"]}) if q.get("job") else None  # the job to leave out and describe, when one is named
    return 200, editions.listing(a, job), JSON  # the named editions first, then the applications


def get_figure(a, q, m):
    """GET /api/v1/jobs/<job>/figures/<lang>/<name>.png: one of the resume's pictures (its timeline, its hierarchy figure, a
    logo tile), drawn from the edition's profile, as the PDF has it."""
    jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
    f = a.tasks.resume_figures(jid, m.group(2), theme_of(q.get("theme")))["files"].get(m.group(3))  # kept until the profile changes
    if not f:  # this resume has no such picture
        raise NotFound(m.group(0))  # 404
    return 200, f, "image/png"  # the picture


def get_deck(a, q, m):
    """GET /api/v1/jobs/<job>/deck/<lang>: the live deck of the job in view, or of the general edition."""
    return 200, a.tasks.deck_live(a.need_job({"job": urllib.parse.unquote(m.group(1))}), m.group(2), theme_of(q.get("theme"))), JSON  # a page, or why there is none yet


def get_depth(a, q, m):
    """GET /api/v1/jobs/<job>/depth: the edition's depth review (depth.py), each unit marked when its words changed since."""
    jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
    from . import depth  # read on demand
    return 200, depth.view(a.tasks, jid, lang_of(q.get("lang"))), JSON


def get_file(a, q, m):
    """GET /api/v1/jobs/<job>/files/<lang>/<name>: an edition's PDF or page picture, fixed names only (the id is checked by
    job_dir)."""
    jid = urllib.parse.unquote(m.group(1))  # the job id (Hangul is percent-encoded)
    f = a.tasks.build_dir(jid, m.group(2)) / m.group(3)  # inside the job's folder
    if f.is_file():  # an edition not made yet answers 404
        return 200, f.read_bytes(), {".png": "image/png", ".txt": "text/plain; charset=utf-8"}.get(f.suffix, "application/pdf")  # a page picture, the plain text or a PDF
    raise NotFound(m.group(0))  # not made


# ------------------------------------------------------------------ writes


def post_sentence_edit(a, req, path):
    """POST /api/v1/sentences/edit: new words for one sentence of the canvas."""
    return {"sentence": documents.edit_sentence(a.tasks, str(req.get("sid") or ""), req.get("text"), lang_of(req.get("lang")), unlocked(a, a.job_in(req)))}  # its new state


def post_sentence_lock(a, req, path):
    """POST /api/v1/sentences/lock: keep a sentence through later drafts."""
    documents.lock_sentence(a.tasks, str(req.get("sid") or ""), req.get("locked") is not False, lang_of(req.get("lang")), unlocked(a, a.job_in(req)))  # one undo step
    return None  # the new state is the whole answer


def post_regenerate(a, req, path):
    """POST /api/v1/sentences/regenerate: new words from the evidence (the agent)."""
    sid = str(req.get("sid") or "")  # which sentence
    if not documents.SID.match(sid):  # a made-up id
        raise ValueError("sentence")  # refused
    jid = unlocked(a, a.job_in(req))  # a submitted application's sentences stay as they went
    return {"started": a.tasks.regen(sid, lang_of(req.get("lang")), jid, str(req.get("way") or "")), "task": f"regen:{sid}"}  # the task's key, in the direction picked


def post_write(a, req, path):
    """POST /api/v1/jobs/write: the resume's sentences from the evidence (the agent)."""
    jid = unlocked(a, a.need_job(req))  # which job, or the general edition; a submitted one is not written again
    return {"started": a.tasks.write_resume(jid, lang_of(req.get("lang"))), "task": f"write:{jid}"}  # the task's key


def post_figures(a, req, path):
    """POST /api/v1/jobs/figures: the deck's figures from the evidence (the agent)."""
    jid = unlocked(a, a.need_job(req))  # which job, or the general edition; a submitted one keeps its deck
    return {"started": a.tasks.draw_figures(jid, lang_of(req.get("lang"))), "task": f"figures:{jid}"}  # the task's key


def post_tailor(a, req, path):
    """POST /api/v1/jobs/tailor: resume, cover letter and interview kit together."""
    jid = a.need_job(req)  # which job
    if (a.ws.job(jid) or {}).get("locked"):  # submitted copies are frozen
        raise ValueError("locked")  # a submitted application is not made again
    return {"started": a.tasks.tailor(jid, lang_of(req.get("lang")), theme_of(req.get("theme")), pages_of(req.get("maxPages")),  # the task
                                      req.get("cover") is not False, req.get("typeset") is True), "task": f"tailor:{jid}"}  # its key


def post_build(a, req, path):
    """POST /api/v1/jobs/build: the typeset PDFs."""
    jid = a.need_job(req)  # which job
    if (a.ws.job(jid) or {}).get("locked"):  # its submitted copies are frozen
        raise ValueError("locked")  # a submitted application is not made again
    return {"started": a.tasks.build(jid, lang_of(req.get("lang")), theme_of(req.get("theme")), pages_of(req.get("maxPages")),  # 1 to 7 pages
                                     req.get("cover") is not False,  # the letter too unless asked not to; the agent is not asked
                                     req["blind"] if isinstance(req.get("blind"), bool) else None)}  # a blind edition or an ordinary one; unsaid, as it was


def post_export_or_lock(a, req, path):
    """POST /api/v1/jobs/export and /api/v1/jobs/lock: copy to the Desktop, or freeze what was submitted."""
    t = a.tasks  # long tasks
    jid, lang = a.need_job(req), lang_of(req.get("lang"))  # which job and edition
    sent = (a.ws.job(jid) or {}).get("locked") or {}  # what was submitted, if it was
    if path.endswith("/export") and isinstance(sent, dict) and sent.get("lang") == lang:  # submitted in this language: the copies that went out, as they went
        return {"exported": t.export(jid, lang)}  # the names written
    if path.endswith("/lock") and sent:  # locked already: a second lock (a double click, another tab) made another frozen copy each time
        raise ValueError("locked")
    model = documents.resume(t, lang, "navy", jid)  # its sentences
    letter = documents.cover(t, jid, lang)  # the cover letter's, when one was drafted
    bad = (model.get("counts") or {}).get("unsupported", 0) + (letter.get("counts") or {}).get("unsupported", 0)  # sentences without evidence in either
    if bad:  # a sentence without evidence is never exported
        raise ValueError(f"unsupported:{bad}")  # the page shows them
    if path.endswith("/export"):  # copy the PDFs
        refused = []  # a Word or PowerPoint file that failed its own check stays home, with why
        return {"exported": t.export(jid, lang, refused), "refused": refused}  # the names written, for the page's message
    rec = t.lock(jid, lang)  # the frozen copies
    if rec is None:  # that edition was never made
        raise ValueError("not_built")  # nothing to freeze
    return {"locked": rec}  # the frozen files and their hashes


def post_depth(a, req, path):
    """POST /api/v1/jobs/depth: the depth review of an edition: what each project item and deck page leaves out (depth.py)."""
    jid = a.need_job(req)  # which job, or -general and a named edition; a submitted one may be read too (its words inform the next)
    return {"started": a.tasks.depth(jid, lang_of(req.get("lang"))), "task": f"depth:{jid}"}  # the task's key


def post_finding(a, req, path):
    """POST /api/v1/jobs/depth/answer, /apply and /leave: what the person does with one finding."""
    from . import depth  # the finding's actions
    jid, lang, fid = a.need_job(req), lang_of(req.get("lang")), str(req.get("finding") or "")  # which edition and which finding
    if path.endswith("/answer"):  # an answer to its question, kept as a fact of its project (a page that names none says which): one undo step
        return depth.answer(a.tasks, jid, lang, fid, req.get("text"), str(req.get("project") or "") or None)
    if path.endswith("/apply"):  # its rewrite in place of the sentence it replaces: one undo step (refused once submitted)
        return depth.apply(a.tasks, jid, lang, fid)
    return depth.leave(a.tasks, jid, lang, fid)  # left as it is: one undo step


def post_baseline(a, req, path):
    """POST /api/v1/jobs/baseline: the edition's last build kept as the pages later builds are compared with (task_compare.py)."""
    jid = a.need_job(req)  # which job, or -general and a named edition
    return {"baseline": a.tasks.accept_baseline(jid, lang_of(req.get("lang")))}  # when, and how many pages of each document


def post_edition(a, req, path):
    """POST /api/v1/editions: a named general edition (no posting, off the board)."""
    return {"job": editions.add_edition(a, req)}  # its id: the other job routes take it


def post_own(a, req, path):
    """POST /api/v1/jobs/own: a resume the person already wrote for this job, brought in whole."""
    return editions.own_edition(a, req)  # how many facts it gave


def post_own_copy(a, req, path):
    """POST /api/v1/jobs/own/copy: this job's own edition started from another edition's words (editions.py)."""
    return editions.copy(a, req)  # one undo step: the job, the source, the languages, whether it replaced words, the files that stay


def post_setup(a, req, path):
    """POST /api/v1/engine/setup: install the typesetting libraries."""
    return {"started": a.tasks.setup_engine()}  # False when one already runs


def post_open(a, req, path):
    """POST /api/v1/open: show a folder in the file manager (the folder's path never reaches the page)."""
    where = {"workspace": a.ws.root, "desktop": desktop_dir()}.get(req.get("what"))  # only these two, named by a word
    if where is None:  # any other word
        raise ValueError("what")  # answered as bad_request
    return {"opened": open_in_files(where)}  # False when this system has no file manager


# ------------------------------------------------------------------ uploads


def upload_own_file(a, q, name, data):
    """POST /api/v1/jobs/own-file?job=&lang=&kind=: a document the person made for an edition, kept as it is."""
    return editions.keep_own_file(a, str(q.get("job") or ""), str(q.get("lang") or ""), str(q.get("kind") or ""), name, data)  # what was kept


def upload_sent_file(a, q, name, data):
    """POST /api/v1/jobs/sent-file?job=&lang=&kind=: a file that went out with an application, kept as its submitted copy."""
    return task_export.keep_sent_file(a, str(q.get("job") or ""), str(q.get("lang") or ""), str(q.get("kind") or ""), name, data)  # what was kept


GET = (  # the reads
    ("/api/v1/documents/resume", get_resume),
    ("/api/v1/documents/cover", get_cover),
    ("/api/v1/editions", get_editions),
    (FIGURE.match, get_figure),
    (DECK.match, get_deck),
    (DEPTH.match, get_depth),
    (FILE.match, get_file),
)
POST = (  # the writes
    ("/api/v1/sentences/edit", post_sentence_edit),
    ("/api/v1/sentences/lock", post_sentence_lock),
    ("/api/v1/sentences/regenerate", post_regenerate),
    ("/api/v1/jobs/write", post_write),
    ("/api/v1/jobs/figures", post_figures),
    ("/api/v1/jobs/tailor", post_tailor),
    ("/api/v1/jobs/build", post_build),
    (("/api/v1/jobs/export", "/api/v1/jobs/lock"), post_export_or_lock),
    ("/api/v1/jobs/depth", post_depth),
    (("/api/v1/jobs/depth/answer", "/api/v1/jobs/depth/apply", "/api/v1/jobs/depth/leave"), post_finding),
    ("/api/v1/jobs/baseline", post_baseline),
    ("/api/v1/editions", post_edition),
    ("/api/v1/jobs/own", post_own),
    ("/api/v1/jobs/own/copy", post_own_copy),
    ("/api/v1/engine/setup", post_setup),
    ("/api/v1/open", post_open),
)
UPLOADS = (  # the files sent as they are
    Upload("/api/v1/jobs/own-file", upload_own_file),  # it stands for the typeset one
    Upload("/api/v1/jobs/sent-file", upload_sent_file),  # a submitted copy
)
