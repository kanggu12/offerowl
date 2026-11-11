"""Every endpoint of Offerowl's API in one table, with no HTTP in it: handle(method, path, query, body) returns
(status, answer, content type). The panel's server and `python3 -m apps.api` put it behind HTTP with the safety rules
of web.py; the command line can call it in this process (client.py). docs/ARCHITECTURE.md lists the same table in words.

Writes answer {"ok": true, ...} with the whole new state under "state" (the panel redraws from it), unless the query
has state=0. Errors answer {"error": code, "what": detail}: 400 for a refused request, 404 for an unknown path or
file, 500 for a bug (logged, never shown).
"""
from __future__ import annotations

import json  # schema files
import logging  # bugs go to the log
import re  # paths
import urllib.parse  # job ids in paths

from . import documents, materials, studio, tracker  # the canvas, a job's own materials, the interview board, the tracker
from .app import Api  # the API object
from .tasks import LANGS, THEMES, desktop_dir, open_in_files  # options and the file manager

log = logging.getLogger("offerowl.api")  # the API's log
JSON = "application/json; charset=utf-8"  # most answers
FILE = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/files/(ko|en)/(preview/[rdc]-\d+\.png|resume\.pdf|resume\.txt|deck\.pdf|cover\.pdf)$")  # an edition's files
DECK = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/deck/(ko|en)$")  # a job's deck as it will print, for the canvas
FIGURE = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/figures/(ko|en)/(timeline|stack|logo_[A-Za-z0-9_-]{1,80})\.png$")  # a picture the printed resume carries, for the canvas
JOBFILE = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/(posting|sent/[A-Za-z0-9_.-]{1,80}|kit/(?:out/)?[A-Za-z0-9_.%()-]{1,240})$")  # a job's posting, a copy that went out, a file of its interview kit
SOURCE = re.compile(r"^/api/v1/materials/(m\d{1,6})$")  # a file brought in for the profile, as it came
JOBPART = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)(?:/(fit|interview|talk))?$")  # one job, its fit, its interview board or its talk
MATERIAL = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/materials(?:/(m\d{1,6})(?:/(preview|pages/(\d{1,4})\.png))?)?$")  # a job's materials, one of them, its preview or a page picture of it


class NotFound(Exception):
    """A path the API does not have (a KeyError from a bug must stay a 500)."""


class FileAnswer(bytes):
    """A file's bytes with headers of its own (web.py sends them): its name for a browser's Save as, and for a web page a
    sandbox, so it runs nothing at the panel's address."""

    def __new__(cls, data: bytes, headers: dict):
        obj = super().__new__(cls, data)  # the bytes themselves, unchanged
        obj.headers = dict(headers)  # what the answer adds
        return obj


def lang_of(v) -> str:
    """A document language from a request: ko or en, Korean when unknown."""
    return v if v in LANGS else "ko"  # only the editions there are


def theme_of(v) -> str:
    """A colour pack from a request: navy, teal or mono, navy when unknown."""
    return v if v in THEMES else "navy"  # only the packs there are


def pages_of(v) -> int:
    """A page limit from a request: 1 to 7, three when unreadable. A long career's English description runs to seven."""
    return max(1, min(int(v), 7)) if str(v or "").isdigit() else 3  # digits only


class Router:
    """The API's table. One per running API."""

    def __init__(self, api: Api):
        self.api = api  # the state and the actions

    def handle(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> tuple[int, object, str]:
        """One request. `query` maps names to values (the first of each), `body` is a write's JSON object."""
        query = query or {}  # no query
        try:
            if method == "GET":  # reads
                return self.get(path, query)  # status, answer, type
            if method == "POST":  # writes
                self.api.ws.forget_mine()  # this request's own undo step, if it makes one, is named in its answer
                out = self.post(path, body or {})  # the action
                if out is not None and not isinstance(out, dict):  # a raw answer (never for writes today)
                    return 200, out, JSON  # as it is
                answer = {"ok": True, **(out or {})}  # the action's own fields
                if self.api.ws.mine() and "step" not in answer:  # the undo step this write made: {"only": step} takes back that one alone
                    answer["step"] = self.api.ws.mine()
                if str(query.get("state", "1")) != "0":  # the panel redraws from the state
                    answer["state"] = self.api.state()  # the whole new state
                return 200, answer, JSON  # done
            return 405, {"error": "method"}, JSON  # only GET and POST
        except NotFound:  # no such path or file
            return 404, {"error": "not_found"}, JSON  # an unknown path
        except PermissionError as exc:  # refused by a rule (a locked job), or the system refusing a file
            if exc.errno is not None:  # the system's own refusal (a folder that cannot be written): its words hold the path
                log.exception("%s %s", method, path)  # the path goes to the log, never to the page
                return 500, {"error": "unexpected"}, JSON  # the page shows a general error
            return 403, {"error": str(exc)}, JSON  # names the rule
        except ValueError as exc:  # an action refused the request
            return 400, {"error": "bad_request", "what": str(exc)}, JSON  # "what" names the check
        except Exception:  # a bug: logged, answered
            log.exception("%s %s", method, path)  # the traceback goes to the log, not the page
            return 500, {"error": "unexpected"}, JSON  # the page shows a general error

    # ------------------------------------------------------------------ reads

    def get(self, path: str, q: dict) -> tuple[int, object, str]:
        """The read routes."""
        a = self.api  # the API object
        if path in ("/api/v1/health", "/health"):  # liveness: "app" tells Offerowl from another server on the port
            return 200, {"ok": True, "app": "offerowl", "api": 1}, JSON  # the desktop app's check reads it
        if path == "/api/v1/state":  # everything the panel draws
            return 200, a.state(), JSON  # read fresh on every call
        if path == "/api/v1/photo":  # the resume's photo, for the details card
            f = a.photo_file()  # the file, if any
            if not f:  # none kept
                raise NotFound(path)  # 404
            if q.get("w"):  # ?w=240: the panel's small copy, a fraction of the bytes the page would decode to draw it 120 px wide
                from . import photo  # the copy is made there
                w = int(q["w"]) if str(q["w"]).isdigit() else 0  # a width in pixels
                small = photo.thumbnail(f, max(16, min(w, photo.THUMB_MAX))) if w else None  # None: no Pillow, or small already
                if small:
                    return 200, small[0], small[1]  # JPEG, or PNG for one with see-through parts
            return 200, f.read_bytes(), "image/jpeg" if f.suffix == ".jpg" else "image/png"  # as it was sent
        if path == "/api/v1/blind":  # the blind edition's mask table: the person's own, else the shipped one
            return 200, a.blind_read(), JSON  # {table, own, counts, stamp}
        if path == "/api/v1/agent":  # the agent card, read again now
            return 200, a.card.refresh(force=str(q.get("refresh", "0")) == "1"), JSON  # ?refresh=1 skips the cache
        if path == "/api/v1/profile":  # the profile, its readiness and its schema check
            from core.schema import validate  # the data model
            prof = a.facts.profile()  # as built from the kept facts
            from .facts import problems  # readiness
            return 200, {"profile": prof, "problems": problems(prof), "schema": validate.check("profile", prof)}, JSON  # shape problems too
        if path == "/api/v1/facts":  # the facts with their states
            return 200, a.facts.view(), JSON  # rows and counts
        if path == "/api/v1/documents/resume":  # the canvas's resume
            job = q.get("job") or None  # the job in view, if any
            if job:  # a job's order applies
                a.need_job({"job": job})  # it exists
            return 200, documents.resume(a.tasks, lang_of(q.get("lang")), theme_of(q.get("theme")), job), JSON  # blocks and sentences
        if path == "/api/v1/documents/cover":  # the canvas's cover letter
            jid = a.need_job({"job": q.get("job")})  # its job
            return 200, documents.cover(a.tasks, jid, lang_of(q.get("lang"))), JSON  # paragraphs and sentences
        if path == "/api/v1/jobs":  # every job
            return 200, {"jobs": a.jobs_view()}, JSON  # with fits and editions
        m = MATERIAL.match(path)  # a job's own materials
        if m:  # the list, one file, its preview or one of its page pictures
            jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
            if not m.group(2):  # the list
                return 200, {"materials": materials.listing(a.ws, jid)}, JSON  # in the order they came
            rec = materials.find(a.ws, jid, m.group(2))  # still on the list
            if not rec:  # taken off, or never there
                raise NotFound(path)  # 404
            if m.group(3) == "preview":  # what the page shows of it
                return 200, materials.preview(a.tasks, jid, rec), JSON  # pages, text, blocks, a frame or a picture
            if m.group(4):  # one page picture of its preview
                f = materials.page_file(a.ws, jid, rec, int(m.group(4)))  # only a page made from this very file
                if not f:  # not made, or past its last page
                    raise NotFound(path)  # 404
                return 200, f.read_bytes(), "image/png"  # the picture
            data, ctype, headers = materials.answer(a.ws, jid, rec)  # the file byte for byte, with its type and name
            return 200, FileAnswer(data, headers), ctype  # web.py adds the headers
        m = FIGURE.match(path)  # one of the resume's pictures: its timeline, its hierarchy figure, a logo tile
        if m:  # drawn from the edition's profile, as the PDF has it
            jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
            f = a.tasks.resume_figures(jid, m.group(2), theme_of(q.get("theme")))["files"].get(m.group(3))  # kept until the profile changes
            if not f:  # this resume has no such picture
                raise NotFound(path)  # 404
            return 200, f, "image/png"  # the picture
        m = DECK.match(path)  # the live deck
        if m:  # the job in view, or the general edition
            return 200, a.tasks.deck_live(a.need_job({"job": urllib.parse.unquote(m.group(1))}), m.group(2), theme_of(q.get("theme"))), JSON  # a page, or why there is none yet
        m = JOBFILE.match(path)  # the Library's files of one job
        if m:  # the posting, a sent copy, a kit's file
            from . import library  # the Library's file rules
            jid, part = a.need_job({"job": urllib.parse.unquote(m.group(1))}), m.group(2)  # it exists
            if part == "posting":  # the posting as it was read
                f, name = a.ws.job_dir(jid) / "posting.md", "posting.md"
            elif part.startswith("sent/"):  # only a copy the lock recorded
                f, name = library.sent_file(a.ws, jid, part[5:]), part[5:]
            else:  # kit/<name> or kit/out/<name>
                rest = urllib.parse.unquote(part[4:])  # after "kit/": a Hangul name comes percent-encoded
                f = library.kit_file(a.ws, jid, rest[4:], out=True) if rest.startswith("out/") else library.kit_file(a.ws, jid, rest)
                name = rest.rsplit("/", 1)[-1]
            if not f or not f.is_file():  # not there, or not one of its files
                raise NotFound(path)  # 404
            data, ctype, headers = library.answer(f, name)  # with its type and its name
            return 200, FileAnswer(data, headers), ctype
        m = SOURCE.match(path)  # a file brought in for the profile
        if m:
            from . import library  # the Library's file rules
            found = library.source_file(a.ws, m.group(1))  # listed, not taken off
            if not found:
                raise NotFound(path)  # 404
            data, ctype, headers = library.answer(*found)  # byte for byte, under the name it came with
            return 200, FileAnswer(data, headers), ctype
        m = JOBPART.match(path)  # one job
        if m:  # /jobs/<id>, /jobs/<id>/fit, /jobs/<id>/interview
            jid = a.need_job({"job": urllib.parse.unquote(m.group(1))})  # it exists
            if m.group(2) == "fit":  # the fit, line by line
                return 200, a.fit(jid), JSON  # cached until something changes
            if m.group(2) == "interview":  # the studio's board
                return 200, studio.board(a.tasks, jid, lang_of(q.get("lang"))), JSON  # questions and scripts
            if m.group(2) == "talk":  # the presentation interview: its brief, and the talk when it is made
                return 200, a.tasks.talk_state(jid), JSON
            job = next(j for j in a.jobs_view() if j["id"] == jid)  # its card with the summary
            return 200, {**job, "posting": (a.ws.job_dir(jid) / "posting.md").read_text(encoding="utf-8")}, JSON  # and the posting
        m = FILE.match(path)  # an edition's PDF or page picture
        if m:  # fixed names only; the id is checked by job_dir()
            jid = urllib.parse.unquote(m.group(1))  # the job id (Hangul is percent-encoded)
            f = a.tasks.build_dir(jid, m.group(2)) / m.group(3)  # inside the job's folder
            if f.is_file():  # an edition not made yet answers 404
                return 200, f.read_bytes(), {".png": "image/png", ".txt": "text/plain; charset=utf-8"}.get(f.suffix, "application/pdf")  # a page picture, the plain text or a PDF
            raise NotFound(path)  # not made
        if path == "/api/v1/ask":  # the command bar: what was asked and answered, and whether an ask runs now
            from . import ask  # read on demand
            return 200, {"history": ask.history(a), "running": a.tasks.busy("ask")}, JSON
        if path == "/api/v1/insights":  # the Insights view's numbers: progress, evidence, fit by area, readiness
            from . import insights  # counted on demand
            return 200, insights.summary(a), JSON
        if path == "/api/v1/library":  # every file brought in or made, with what can be done to each
            from . import library  # listed on demand
            return 200, library.listing(a), JSON
        if path == "/api/v1/removed":  # what was taken off, to put back or delete for good, and the folders restores kept aside
            from . import removed  # listed on demand
            return 200, removed.listing(a), JSON
        if path == "/api/v1/tracker":  # the board, the timeline and what is due
            jobs = a.jobs_view()  # every job
            return 200, {"stages": ["preparing", "submitted", "interview", "result"], "jobs": jobs,  # the columns and cards
                         "timeline": tracker.timeline(jobs), "due": tracker.due(jobs)}, JSON  # the timeline and the due reminders
        if path == "/api/v1/reminders/due":  # the desktop app and the panel ask this
            return 200, {"due": tracker.due(a.jobs_view())}, JSON  # due and not done
        if path == "/api/v1/workspace/backup":  # the whole workspace as one file
            from . import backup  # only when asked
            return 200, backup.write(a.ws), "application/zip"  # a file to save
        if path == "/api/v1/reminders.ics":  # every open reminder for the person's calendar
            return 200, tracker.ics(a.jobs_view()).encode("utf-8"), "text/calendar; charset=utf-8"  # a file to open
        if path == "/api/v1/history":  # the undo steps
            return 200, {"steps": a.ws.history()}, JSON  # newest first
        m = re.fullmatch(r"/api/v1/schema/([a-z]+)", path)  # the data model, for tools
        if m:  # one schema by name
            from core.schema import validate  # the names
            if m.group(1) not in validate.NAMES:  # unknown name
                raise NotFound(path)  # 404
            return 200, validate.load(validate.NAMES[m.group(1)])[0], JSON  # the schema itself
        raise NotFound(path)  # no route matched

    # ------------------------------------------------------------------ writes

    def post(self, path: str, req: dict) -> dict | None:
        """The JSON writes. Each returns extra fields for the answer, or None."""
        a = self.api  # the API object
        t = a.tasks  # long tasks
        if path == "/api/v1/autopilot":  # files or folders in, finished documents out
            return a.autopilot(req)  # the run's key, the files it found and its estimate
        if path == "/api/v1/autopilot/stop":  # the person stops a run; the step in progress finishes first
            with t.state_lock:  # together with the chain's look at what waits
                t.autopilot_next = None  # a stop is for everything asked so far: what waited goes too
                t.autopilot_stop.set()
            return None  # the new state is the whole answer
        if path == "/api/v1/materials/read":  # read the listed materials
            return {"started": t.ingest([str(x) for x in req.get("ids") or []])}  # False when a reading already runs
        if path == "/api/v1/materials/remove":  # take a file and its facts out
            a.remove_material(str(req.get("id") or ""))  # undoable
            return None  # the new state is the whole answer
        if path == "/api/v1/example":  # the fictional example person, for a first look
            return {"material": a.add_example(req.get("lang"))}  # read at once, in the page's language
        if path == "/api/v1/facts/decide":  # keep, drop, edit or put back one fact
            a.fact(req)  # one undo step
            return None  # the new state is the whole answer
        if path == "/api/v1/facts/keep-all":  # keep every fact still to confirm
            return {"kept": a.keep_all(str(req.get("material") or "") or None)}  # how many (one material's, when named)
        if path == "/api/v1/facts/add":  # a fact the person typed
            return {"cid": a.add_fact(req)}  # its id
        if path == "/api/v1/details":  # "Your details", autosaved while typing
            a.details(req)  # one undo step per field and pause
            return None  # the new state is the whole answer
        if path == "/api/v1/sentences/edit":  # new words for one sentence of the canvas
            return {"sentence": documents.edit_sentence(t, str(req.get("sid") or ""), req.get("text"), lang_of(req.get("lang")), a.job_in(req))}  # its new state
        if path == "/api/v1/sentences/lock":  # keep a sentence through later drafts
            documents.lock_sentence(t, str(req.get("sid") or ""), req.get("locked") is not False, lang_of(req.get("lang")), a.job_in(req))  # one undo step
            return None  # the new state is the whole answer
        if path == "/api/v1/sentences/regenerate":  # new words from the evidence (the agent)
            sid = str(req.get("sid") or "")  # which sentence
            if not documents.SID.match(sid):  # a made-up id
                raise ValueError("sentence")  # refused
            return {"started": t.regen(sid, lang_of(req.get("lang")), a.job_in(req), str(req.get("way") or "")), "task": f"regen:{sid}"}  # the task's key, in the direction picked
        if path == "/api/v1/undo":  # the undo button; {"only": id} from a toast takes back that step only
            with a.ws.lock:  # the newest step is looked at and taken back in one go
                if req.get("only") is not None and str(req["only"]) != a.ws.newest()[0]:  # another change came after it (or it was undone)
                    return {"undone": None, "moved": True}  # nothing is taken back: the page says the change is in the history
                label = a.ws.undo()  # the files back
            if label is not None:  # something was undone
                a.facts.rebuild()  # the profile follows the restored facts
            return {"undone": label}  # the page says what came back
        if path == "/api/v1/history/undo":  # back to an earlier point of the history
            n = max(1, min(int(req.get("steps") or 1), 50)) if str(req.get("steps") or "1").isdigit() else 1  # 1 to 50 steps
            done = []  # the labels taken back
            for _ in range(n):  # one step at a time
                label = a.ws.undo()  # the newest step
                if label is None:  # nothing left
                    break  # stop
                done.append(label)  # remembered
            if done:  # the profile follows
                a.facts.rebuild()  # once
            return {"undone": done}  # what came back
        if path == "/api/v1/jobs":  # a pasted posting or a link
            jid = a.add_job(req)  # its folder and card
            t.analyze(jid, agent=False)  # the analysis starts at once, by words: adding a job sends nothing to the agent
            return {"job": jid}  # the new job's id
        if path == "/api/v1/jobs/select":  # another job in view
            a.ws.set_prefs(job=a.need_job(req))  # remembered with the workspace
            return None  # the new state is the whole answer
        if path == "/api/v1/jobs/write":  # the resume's sentences from the evidence (the agent)
            jid = a.need_job(req)  # which job, or the general edition
            return {"started": t.write_resume(jid, lang_of(req.get("lang"))), "task": f"write:{jid}"}  # the task's key
        if path == "/api/v1/jobs/figures":  # the deck's figures from the evidence (the agent)
            jid = a.need_job(req)  # which job, or the general edition
            return {"started": t.draw_figures(jid, lang_of(req.get("lang"))), "task": f"figures:{jid}"}  # the task's key
        if path == "/api/v1/jobs/analyze":  # analyze the posting again
            return {"started": t.analyze(a.need_job(req))}  # False when one already runs
        if path == "/api/v1/jobs/tailor":  # resume, cover letter and interview kit together
            jid = a.need_job(req)  # which job
            if (a.ws.job(jid) or {}).get("locked"):  # submitted copies are frozen
                raise ValueError("locked")  # a submitted application is not made again
            return {"started": t.tailor(jid, lang_of(req.get("lang")), theme_of(req.get("theme")), pages_of(req.get("maxPages")),  # the task
                                        req.get("cover") is not False, req.get("typeset") is True), "task": f"tailor:{jid}"}  # its key
        if path == "/api/v1/jobs/build":  # the typeset PDFs
            jid = a.need_job(req)  # which job
            if (a.ws.job(jid) or {}).get("locked"):  # its submitted copies are frozen
                raise ValueError("locked")  # a submitted application is not made again
            return {"started": t.build(jid, lang_of(req.get("lang")), theme_of(req.get("theme")), pages_of(req.get("maxPages")),  # 1 to 7 pages
                                       req.get("cover") is not False,  # the letter too unless asked not to; the agent is not asked
                                       req["blind"] if isinstance(req.get("blind"), bool) else None)}  # a blind edition or an ordinary one; unsaid, as it was
        if path in ("/api/v1/jobs/export", "/api/v1/jobs/lock"):  # copy to the Desktop, or freeze what was submitted
            jid, lang = a.need_job(req), lang_of(req.get("lang"))  # which job and edition
            sent = (a.ws.job(jid) or {}).get("locked") or {}  # what was submitted, if it was
            if path.endswith("/export") and isinstance(sent, dict) and sent.get("lang") == lang:  # submitted in this language: the copies that went out, as they went
                return {"exported": t.export(jid, lang)}  # the names written
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
        if path == "/api/v1/editions":  # a named general edition (no posting, off the board)
            return {"job": a.add_edition(req)}  # its id: the other job routes take it
        if path == "/api/v1/jobs/own":  # a resume the person already wrote for this job, brought in whole
            return a.own_edition(req)  # how many facts it gave
        if path == "/api/v1/jobs/remove":  # off the board, or a named edition off the list (undo or the Removed list brings it back)
            a.board({"job": a.need_job(req), "removed": True})  # through the board: one undo step
            return None  # the new state is the whole answer
        if path == "/api/v1/removed/restore":  # one thing taken off, put back
            from . import removed  # the Removed list
            return removed.restore(a, str(req.get("id") or ""))  # what came back, and whether a source is to be read again
        if path == "/api/v1/removed/delete":  # deleted for good: one thing taken off, or every one ({"all": true})
            from . import removed  # the Removed list
            return removed.delete(a, str(req.get("id") or ""), every=req.get("all") is True)  # the ids that went
        if path == "/api/v1/tracker/edit":  # a card moved or edited
            a.board(req)  # one undo step
            return None  # the new state is the whole answer
        if path == "/api/v1/tracker/next":  # a card's move-on button
            a.next_stage(a.need_job(req))  # one column right
            return None  # the new state is the whole answer
        if path == "/api/v1/reminders":  # add, finish or remove a reminder
            return {"reminder": a.reminder(req)}  # the new one, if any
        if path == "/api/v1/tracker/round":  # add, change or remove an interview round: its kind, day, the questions asked, notes
            return {"round": a.round(req)}  # the round as kept, or null once removed
        if path == "/api/v1/interview/kit":  # make the interview kit without tailoring the rest
            jid = a.need_job(req)  # which job
            return {"questions": len(t.ensure_kit(jid, lang_of(req.get("lang"))))}  # the map's size
        if path == "/api/v1/interview/scripts":  # more scripts, the likeliest questions first
            jid = a.need_job(req)  # which job
            # a submitted application still gets ready for its interview: the scripts go to the kit's own folder, and the
            # submitted copies stay as they went
            return {"started": t.write_scripts(jid, lang_of(req.get("lang"))), "task": f"scripts:{jid}"}  # the task's key
        if path == "/api/v1/interview/talk/brief":  # the presentation interview's brief: topics, minutes, day, format, the interviewers' words
            jid = a.need_job(req)  # which job
            return {"brief": t.save_talk_brief(jid, req.get("brief"))}  # as kept; a brief with no topic is refused (400 bad_brief)
        if path == "/api/v1/interview/talk":  # make the talk: its deck from the portfolio and its script (task talk:<job>)
            jid = a.need_job(req)  # which job
            return {"started": t.make_talk(jid, lang_of(req.get("lang"))), "task": f"talk:{jid}"}  # the task's key
        if path == "/api/v1/interview/talk/deliver":  # the talk's slides and script on the Desktop
            jid = a.need_job(req)  # which job
            return {"files": t.deliver_talk(jid)}  # the names written
        if path == "/api/v1/interview/start":  # serve the kit's search view, at the panel's /kit/<job>/
            return {"started": bool(t.kit_url(a.need_job(req)))}  # this job's own kit server; False when it could not start
        if path == "/api/v1/jobs/materials/remove":  # a job's material off its list (its file stays, and undo brings it back)
            materials.remove(a.ws, a.need_job(req), str(req.get("id") or ""))  # one undo step
            return None  # the new state is the whole answer
        if path == "/api/v1/ask":  # the command bar: the person's words to the agent, which acts through Offerowl's own tools
            from . import ask  # the agent's run
            return {"started": ask.start(a, str(req.get("text") or ""))}  # False while an ask still runs
        if path == "/api/v1/ask/clear":  # the command bar's history emptied
            from . import ask  # its file
            return {"cleared": ask.clear(a)}  # how many asks went
        if path == "/api/v1/library/export":  # one Library row's file on the Desktop, exactly that file
            from . import library  # the Library's file rules
            return {"exported": [library.export(a, str(req.get("id") or ""))]}  # the name written
        if path == "/api/v1/jobs/materials/export":  # a copy of a job's material on the Desktop, byte for byte
            return {"exported": materials.export(a.ws, a.need_job(req), str(req.get("id") or ""))}  # the name written, for the page's message
        if path == "/api/v1/translate":  # the English profile for English editions
            return {"started": t.translate(a.job_in(req))}  # False when one already runs; the job's draft decides how much is asked
        if path == "/api/v1/engine/setup":  # install the typesetting libraries
            return {"started": t.setup_engine()}  # False when one already runs
        if path == "/api/v1/settings":  # the settings menu
            a.set_settings(req)  # each value checked
            return None  # the new state is the whole answer
        if path == "/api/v1/jobs/questions":  # a job's application questions, in order
            a.set_questions(req)  # checked and kept
            return None  # the new state is the whole answer
        if path == "/api/v1/jobs/questions/paste":  # a form's questions pasted as it shows them, read with their limits
            return {"added": a.paste_questions(req)}  # how many came in
        if path == "/api/v1/jobs/questions/write":  # their answers, by the agent
            return {"started": t.answers(a.need_job(req), [str(x) for x in req.get("ids") or []] or None)}  # False when they are being written
        if path == "/api/v1/jobs/questions/edit":  # the person's own words for one answer
            a.edit_answer(req)  # checked and kept
            return None  # the new state is the whole answer
        if path == "/api/v1/jobs/questions/export":  # the questions and answers as a text file on the Desktop
            return {"exported": t.export_answers(a.need_job(req))}  # the name written
        if path == "/api/v1/photo/remove":  # the resume's photo removed: it waits in the Trash, which puts it back or deletes it for good
            return {"removed": a.remove_photo(keep=True)}  # its id in the Trash, for the note's Undo (/api/v1/removed/restore)
        if path == "/api/v1/blind":  # the person's own mask table for the blind edition, replaced or taken away
            return {"blind": a.set_blind(req)}  # the new summary
        if path == "/api/v1/style":  # a person's own writing rules, added and chosen
            name = a.add_style(req)  # checked and kept
            a.set_settings({"style": name})  # in use from now on
            return {"style": name}  # the name it is kept under
        if path == "/api/v1/onboarding":  # where the first run stands
            a.set_onboarding(req)  # kept with the workspace
            return None  # the new state is the whole answer
        if path == "/api/v1/agent/login":  # the agent card's sign-in button
            return {"started": a.card.start_login()}  # False when no CLI is on this PC
        if path == "/api/v1/agent/refresh":  # the agent card's check-again
            a.card.refresh(force=True)  # the CLIs are asked now
            return None  # the new state is the whole answer
        if path == "/api/v1/open":  # show a folder in the file manager (the folder's path never reaches the page)
            where = {"workspace": a.ws.root, "desktop": desktop_dir()}.get(req.get("what"))  # only these two, named by a word
            if where is None:  # any other word
                raise ValueError("what")  # answered as bad_request
            return {"opened": open_in_files(where)}  # False when this system has no file manager
        raise NotFound(path)  # an unknown write


def dumps(obj) -> bytes:
    """An answer as UTF-8 JSON bytes."""
    return obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")  # Korean stays readable
