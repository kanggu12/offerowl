"""The jobs on the board, as the panel's keys change them: one added from a pasted posting or a link, its posting
replaced, its id changed, its card moved and edited (and taken off), the days a batch was added cleared, its interview
rounds and reminders; and each job as the page draws it (its analysis, its fit's summary, its editions, its questions,
its materials, its kit), with the one in view. The rules of the board are tracker.py's."""
from __future__ import annotations

import os  # the links a test may fetch from this PC
import re  # a role's words read from the posting

from .. import documents, interview  # a job's editions, and when its interview kit's map was made
from ...core.workspace import STAGES, today, write_json, write_text  # the board's columns, the day, files
from . import materials, tracker  # a job's own materials, the board's rules
from .answers import questions_of  # its questions as the page shows them
from .task_analyze import plan_of  # its posting analysis

GENERAL = "-general"  # the edition with no job (the documents' drafts.GENERAL has the same name)


def fit_of(api, job_id: str, posting: str | None = None) -> dict:
    """The fit of the profile to a job's posting, made now when it is not cached (the panel's one Fits)."""
    return api.fits.fit(job_id, posting)


def jobs_view(api) -> list[dict]:
    """Every job with its analysis, its fit's summary and its last editions."""
    out = []  # one per job
    for st in api.ws.jobs():  # oldest first
        with api.gone_meanwhile(st["id"]):  # deleted for good while this was read: left out
            out.append(job_view(api, st))
    return out  # in the board's order


def job_view(api, st: dict) -> dict:
    """One job as the page draws it: its analysis, its fit's summary and its last editions."""
    plan = plan_of(api.ws, st["id"])  # the posting analysis
    builds = documents.job_builds(api, st["id"])  # per language, each marked when facts, the draft or the job's own edition changed since
    posting = api.ws.posting(st["id"])  # empty when it is gone
    f = api.fits.fit_summary(st["id"], posting, st.get("stage") == "result")  # the fit (cached; after a change of the profile, the last one while the new one is made)
    return {**st, "plan": {k: plan.get(k) for k in ("skillsFocus", "competencyWeak", "projectOrder", "at", "by")},  # only what the page shows
            "questions": questions_of(api, st["id"]),  # the application's own questions and their answers
            "materials": materials.listing(api.ws, st["id"]),  # the decks, notes and briefs brought in for its interview
            "builds": builds, "posting_chars": len(posting),  # its editions and the posting's size
            "posting_head": posting.strip().splitlines()[0][:120] if posting.strip() else "",  # its first line, for the card
            "fit": {"score": f["score"], "counts": f["counts"], "gaps": len(f["gaps"])},  # the fit's summary
            "days": tracker.stage_days(st),  # the days of the stages it went through, as the board and the timeline show them
            "kit": interview.kit_stamp(api, st["id"]),  # when the interview kit's map was last made (0: never)
            "own": api.tasks.own_langs(st["id"]),  # the languages of the resume the person brought in for it, if any
            "own_info": api.tasks.own_info(st["id"])}  # its day, the edition it was started from, its edits and its files (null: none)


def job_in_view(pick: str | None, jobs: list[dict], editions: list[dict]) -> str | None:
    """The job in view: the one chosen (prefs' job), the general edition when it was chosen, or the newest job when the chosen
    one is gone."""
    return pick if pick == GENERAL or any(j["id"] == pick for j in jobs + editions) else (jobs[-1]["id"] if jobs else None)


def set_posting(api, jid: str, posting: str) -> None:
    """A job's posting replaced by the text the person pasted (a posting whose duties the reading missed): one undo step."""
    posting = str(posting or "").strip()[:200000]  # the text, bounded as a posting
    if len(posting) < 20:  # too short to be a posting
        raise ValueError("posting")  # nothing to analyze
    job = api.ws.job(jid) or {}  # its card, for the undo key's words
    # the plan too: the analysis that follows writes it with no step of its own, so one undo takes both back
    with api.ws.change({"code": "undo_posting", "company": job.get("company") or job.get("role") or jid}, [f"jobs/{jid}/posting.md", f"jobs/{jid}/plan.json"]):
        write_text(api.ws.job_dir(jid) / "posting.md", posting + "\n")  # as pasted


ROLE_WORDS = re.compile(r"(엔지니어|개발자|매니저|디자이너|연구원|리서처|사이언티스트|분석가|아키텍트|운영자|담당자|기획자|\b(?:PM|PO|SRE|DevOps|MLOps)\b|"
                        r"engineer|developer|manager|designer|scientist|researcher|architect|analyst|lead\b)", re.I)  # words that name a role
COMPANY_FORM = re.compile(r"(^\(주\)|^㈜|\(주\)$|㈜$|(?:랩스|랩|테크|소프트|시스템즈|코리아|컴퍼니|그룹|증권|은행|카드|생명|화재|전자|바이오|헬스케어|모빌리티|게임즈|"
                          r"스튜디오|파트너스|네트웍스|솔루션즈|인베스트먼트|에이아이)$|^[A-Za-z][\w&.-]*(?:Labs?|AI|Inc\.?|Corp\.?|Tech|Technologies|Systems|Software)$)")  # a company's name by its form


def add_job(api, req: dict, select: bool = True) -> str:
    """A job from a pasted posting or a link: its folder, the posting, its card on the board. Returns its id. With
    select False (a run adds it) the job in view stays as it is."""
    posting = str(req.get("posting") or "").strip()  # the posting
    url = str(req.get("url") or "").strip()  # or the link it lives at
    if not posting and url:  # a link alone: fetch the page's text once
        from . import postings  # the fetch
        got = postings.fetch(url, allow_local=os.environ.get("OFFEROWL_ALLOW_LOCAL_LINKS") == "1")  # raises ValueError with a code
        posting = got["text"]  # the posting's text
    company, role = str(req.get("company") or "").strip()[:80], str(req.get("role") or "").strip()[:80]  # both optional, bounded
    if len(posting) < 20:  # too short to be a posting
        raise ValueError("posting")  # nothing to analyze
    if not company and not role:  # nothing typed: the posting's own words name it
        from . import fit as F  # the posting parser
        f = F.compute({"schema": "resume-profile/0.1", "roles": [{"org": "-", "projects": [{"id": "x", "title": "-", "summary": "-"}]}]}, posting)  # parse only
        company = (f.get("company") or "")[:80]  # the company the posting names
        role = f.get("role") or posting.splitlines()[0]  # its title, else its first line
        role = re.sub(r"\s*[(\[].*?[)\]]\s*", " ", role.lstrip("# ")).strip()  # a note in brackets ("(가상의 예제)")
        role = re.sub(r"\s*(?:채용\s*공고|채용|모집|공고|job posting|hiring)\s*$", "", role, flags=re.I).strip()  # the posting's own word for itself
        if company and role.startswith(company):  # the company named twice
            role = role[len(company):].strip(" -·|,")
        if not company:  # no company the parser could name: a first line "가나다랩스 플랫폼 엔지니어" starts with it (B3-16)
            head, _, rest = role.partition(" ")  # its first word, and the rest
            if rest and ROLE_WORDS.search(rest) and COMPANY_FORM.search(head):  # the rest names the role, the first word reads as a company (never "플랫폼", "Senior")
                company, role = head.strip("|,·-")[:80], rest.strip()
        role = role[:80]  # bounded
    with api.ws.lock:  # the folder name picked and its job written in one go: two adds at once never share a folder
        jid = _add_job_locked(api, company, role, posting, url)
    if select:  # the person added it: in view
        api.ws.set_prefs(job=jid)
    return jid  # the route starts its analysis


def _add_job_locked(api, company: str, role: str, posting: str, url: str) -> str:
    """add_job's writing, under the workspace's lock: the folder's name and the job's files."""
    jid = api.ws.new_job_id(company, role or posting.splitlines()[0])  # its folder name
    n = len(api.ws.jobs(removed=True)) + 1  # a counter for the order of jobs made the same day
    # undo takes the job away, the questions a posting brought along with it
    with api.ws.change({"code": "undo_add_job", "company": company or role}, api.ws.job_files(jid) + [f"jobs/{jid}/questions.json"]):
        write_text(api.ws.job_dir(jid) / "posting.md", posting + "\n")  # the posting as pasted
        from . import answers as A  # a posting that lists the form's questions brings them along
        asked = A.parse_questions(posting, strict=True)  # only questions with a limit, or under a questions heading
        if asked:  # nobody types them again
            write_json(api.ws.job_dir(jid) / "questions.json", {"questions": A.clean_questions(asked, [])})
        api.ws.save_job({"id": jid, "company": company, "role": role, "created": today(), "seq": n,  # its card, first column
                          "stage": "preparing", "dates": {"preparing": today()}, "next": "", "result": "",
                          **({"url": url[:2000]} if url else {})})  # where it was read from
    return jid


def rename_job(api, req: dict) -> str:
    """A job's id changed (POST /api/v1/jobs/rename {job, id}): ASCII, unused; the folder, its kit's output, the job in view
    and the undo steps follow, and the old id stays an alias. Returns the new id."""
    jid = api.need_job(req)
    if jid == GENERAL:  # the general edition's folder has a fixed name
        raise ValueError("job")
    api.tasks.let_kit_go(jid)  # its kit server named the old folder
    return api.ws.rename_job(jid, str(req.get("id") or "").strip())


def board(api, req: dict) -> None:
    """Move a job on the board or change its date, next step or result. Taking it off ({"removed": true}) records the
    day, for the Removed list; undo or that list puts it back."""
    with api.ws.lock:  # looked up and changed in one step: a job deleted for good meanwhile is refused, never half written
        jid = api.need_job(req)  # which job
        st = api.ws.job(jid)  # its status
        off = req.get("removed") is True and not st.get("removed")  # taken off now (only an explicit true removes)
        days = [req.get("date")] + (list(req["dates"].values()) if isinstance(req.get("dates"), dict) else [])  # every day sent
        if any(isinstance(d, str) and d and not tracker.is_day(d) for d in days):  # 2026-02-30: refused in words, never answered ok with nothing done
            raise ValueError("date")  # as a reminder's bad day is refused
        # one undo step per change of the card; a removal says so on the undo key, an edition in its own words
        code = ("undo_remove_edition" if st.get("kind") == "edition" else "undo_remove_job") if off else "undo_board"
        with api.ws.change({"code": code, "company": st.get("company") or st.get("role") or st.get("name")}, api.ws.job_files(jid),
                            coalesce=f"board:{jid}:{','.join(sorted(k for k in req if k != 'job'))}"):  # typing in the same fields merges
            st = api.ws.job(jid)  # read again inside the step
            if req.get("stage") in STAGES and req["stage"] != st.get("stage"):  # a move
                st["stage"] = req["stage"]  # the new column
                dates = st.setdefault("dates", {})
                if not dates.get(req["stage"]):  # the day it first reached that stage stays: moving back and forth never rewrites it
                    dates[req["stage"]] = today()  # the day it moved
            if isinstance(req.get("date"), str) and (not req["date"] or tracker.is_day(req["date"])):  # a real day (YYYY-MM-DD), or empty to clear
                st.setdefault("dates", {})[st["stage"]] = req["date"]  # the date of the stage it is in
            for stage, day in (req.get("dates") or {}).items() if isinstance(req.get("dates"), dict) else ():  # any stage's day, as the progress tab edits them
                if stage in STAGES and isinstance(day, str) and (not day or tracker.is_day(day)):  # a real day, or empty to clear
                    st.setdefault("dates", {})[stage] = day
            for k in ("next", "result", "company", "role"):  # the card's free text fields
                if isinstance(req.get(k), str):  # only the fields that were sent
                    st[k] = req[k].strip()[:1000 if k in ("next", "result") else 200]  # trimmed and bounded: a next step may hold a meeting's long link whole
            if off:  # off the board: undo, or the Removed list, brings it back
                st["removed"], st["removed_at"] = True, today()  # with the day the list shows (a job's card keeps a day: core/schema/job.schema.json)
            api.ws.save_job(st)  # one write for every change


def clear_batch_day(api, day: str) -> list[str]:
    """The stage days that equal the day a batch of applications was added (tracker.batch_day), cleared on those cards in
    one undo step: the day of the adding was stamped on them, not the day they were sent or answered. The ids changed."""
    with api.ws.lock:  # read and written in one step
        jobs = api.ws.jobs()  # every card on the board, as kept
        batch = tracker.batch_day(jobs)  # found again here, never taken from the page
        if not batch or batch["day"] != day:  # the page's batch is not the one there is now
            return []
        ids = batch["jobs"]
        files = [f for jid in ids for f in api.ws.job_files(jid)]  # every card it changes
        with api.ws.change({"code": "undo_board_days", "n": len(ids)}, files):  # one step for all of them
            for jid in ids:
                st = api.ws.job(jid)
                st["dates"] = {k: v for k, v in (st.get("dates") or {}).items() if str(v)[:10] != day}  # that day, gone
                api.ws.save_job(st)
        return ids


def next_stage(api, jid: str) -> None:
    """Move a job one column to the right."""
    with api.ws.lock:  # looked up and moved in one step (board takes the same lock again)
        st = api.ws.job(jid)  # its status
        if not st:  # no such job
            raise ValueError("job")  # answered as bad_request
        i = STAGES.index(st.get("stage", "preparing")) if st.get("stage") in STAGES else 0  # an unknown stage counts as the first
        board(api, {"job": jid, "stage": STAGES[min(i + 1, len(STAGES) - 1)]})  # through board(): undo and the date


def set_round(api, req: dict) -> dict | None:
    """Add, change or remove an interview round on a job (tracker.set_round). One undo step."""
    with api.ws.lock:  # looked up and changed in one step: a job deleted for good meanwhile is refused
        jid = api.need_job(req)  # which job
        st = api.ws.job(jid)  # its status
        with api.ws.change({"code": "undo_round", "company": st.get("company") or st.get("role")}, api.ws.job_files(jid)):  # one undo step
            rec = tracker.set_round(st, req)  # checked (a round never moves the card: a recruiter's call is a round too)
            api.ws.save_job(st)  # saved
    return rec  # the round as kept


def reminder(api, req: dict) -> dict | None:
    """Add a reminder to a job, or mark one done or remove it. One undo step."""
    with api.ws.lock:  # looked up and changed in one step: a job deleted for good meanwhile is refused
        jid = api.need_job(req)  # which job
        st = api.ws.job(jid)  # its status
        how = "remove" if req.get("id") and req.get("remove") is True else "change" if req.get("id") else "add"  # what the undo key says
        with api.ws.change({"code": "undo_reminder", "company": st.get("company") or st.get("role"), "how": how}, api.ws.job_files(jid)):  # one undo step
            if req.get("id"):  # an existing reminder
                tracker.set_reminder(st, str(req["id"]), done=req.get("done") if isinstance(req.get("done"), bool) else None,
                                     remove=req.get("remove") is True)  # done, not done, or removed
                rec = None  # nothing new
            else:  # a new one
                rec = tracker.add_reminder(st, str(req.get("at") or ""), str(req.get("text") or ""))  # checked
            api.ws.save_job(st)  # saved
    return rec  # the new reminder, for the answer
