"""One action from the person's files to finished documents, with nothing to click in between.

The person drops files or folders, or pastes their paths, and may add a posting. The run then reads every file through
the agent, keeps the facts whose quotes are found in their files, writes the resume, makes the English edition, draws
the deck's figures, typesets both languages, and for a posting tailors the resume and writes the cover letter and the
first interview scripts. The PDFs land on the Desktop. Each step is one of the panel's own tasks, run in turn, so what
the run makes is what the buttons would have made, with every check they have.

A posting alone, once a career is kept, starts the same run without reading anything again: the documents for that
posting come from the facts already kept.

A step that fails does not stop the ones that do not need it: the figures may fail and the PDFs still come out.
Without an agent only a profile file can be read, and the run says so before it starts.
"""
import json  # the list of runs
import os  # the home folder
import re  # paths written the Windows way
import sys  # the platform
import time  # the clock of each step
from collections import Counter  # the address a person's files write most
from pathlib import Path  # paths

from .drafts import GENERAL as GENERAL_EDITION  # the edition with no job
from .tasks import log  # the panel's log

# Files the readers turn into text: documents, slides, notes, a profile, and pictures of documents (through OCR)
READABLE = {".pdf", ".docx", ".pptx", ".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".zip"}  # a zip is opened into its files
# Folders that hold no one's career: code dependencies, version control, caches, build output
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "site-packages", "dist", "build", "target", "out", "tmp", "temp", "cache", "caches",
             # and the folders a system keeps for its programs: a home folder pasted whole must not send their settings to the agent
             "appdata", "application data", "local settings", "library", "programdata", "program files", "program files (x86)",
             "windows", "$recycle.bin", "system volume information"}
MAX_FILES = 80  # files one run reads: a career's documents fit, a whole drive does not
MAX_SEEN = 4000  # files looked at under the paths of one run: a career's folders hold far fewer, and a whole drive stops here
RANK = {".pdf": 0, ".docx": 0, ".pptx": 0, ".md": 1, ".txt": 1, ".json": 1, ".yaml": 2, ".yml": 2, ".csv": 2}  # documents first, then notes; pictures last
MAX_FILE_BYTES = 60_000_000  # bytes of one file, the same cap as an upload
SCRIPTS = 10  # interview scripts one run writes for a posting: the likeliest questions
LANGS = ("ko", "en")  # both editions: a Korean resume and an English one
EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")  # an address as written
NOT_A_PERSON = re.compile(r"^(?:git|noreply|no-reply|donotreply|do-not-reply)@|@(?:[\w-]+\.)*(?:github\.com|gitlab\.com|bitbucket\.org)$"
                          r"|\.(?:png|jpe?g|gif|svg|webp|pdf|md|txt|json)$", re.I)  # a clone address, a robot's, or a picture's name (logo@2x.png)
HEAD = 1500  # characters at the start of a file: where a resume writes its owner's name and contact
PHONE = re.compile(r"(?<![\d+])(?:\+82[-.\s]?1[016789]|01[016789])[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")  # a mobile number as Korean resumes write it
NAME_PROMPT = """The text below is the start of each of a person's career documents (a resume, notes, a portfolio).

<<<
{text}
>>>

Whose documents are these? Give the person's own name exactly as the text writes it, and its Latin spelling only when
the text writes one too. Never guess, and never give a company's or another person's name: give "" when the text does
not write the person's name.

Return JSON: {{"name": "...", "name_en": "..."}}"""  # one small question of its own: a new form inside the reading prompt would make the reading worse


def local_path(text: str) -> Path:
    """A path as the person pasted it, in this machine's form. Under WSL a Windows path (C:\\Users\\...) and a path into
    the Linux side (\\\\wsl.localhost\\<distro>\\root\\...) are turned into the paths this server sees."""
    s = text.strip().strip('"').strip("'")  # quotes from a copied path
    m = re.match(r"^\\\\(?:wsl\$|wsl\.localhost)\\[^\\]+\\(.*)$", s, re.I)  # \\wsl.localhost\Ubuntu\root\x
    if m:  # a path into this Linux system, seen from Windows
        return Path("/" + m.group(1).replace("\\", "/"))  # /root/x
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)  # C:\Users\x or C:/Users/x
    if m and sys.platform != "win32" and Path("/mnt", m.group(1).lower()).is_dir():  # a Windows drive, seen from WSL
        return Path("/mnt", m.group(1).lower(), m.group(2).replace("\\", "/"))  # /mnt/c/Users/x
    return Path(os.path.expanduser(s))  # a path of this machine; ~ is the home folder


def collect(texts: list[str]) -> tuple[list[Path], list[dict]]:
    """The readable files under the paths the person gave, in a stable order, and what was left out and why. A folder
    is walked with its subfolders, past hidden folders and the folders that hold code or caches."""
    files, skipped, seen = [], [], set()  # results, notes, files already taken
    looked = [0]  # files looked at: the walk stops at MAX_SEEN

    def take(p: Path) -> None:  # one file, if it is readable and not too large
        looked[0] += 1  # one more looked at
        if p.suffix.lower() not in READABLE:  # not a kind the readers know
            return
        try:
            size = p.stat().st_size  # its size
        except OSError:  # gone or not readable
            skipped.append({"path": str(p), "why": "unreadable"})
            return
        if size == 0 or size > MAX_FILE_BYTES:  # empty, or larger than an upload may be
            skipped.append({"path": str(p), "why": "empty" if size == 0 else "too_large"})
            return
        key = p.resolve()  # one file under two paths is read once
        if key not in seen:  # new
            seen.add(key)
            files.append(p)

    for text in texts:  # each path the person gave
        if not str(text).strip():  # an empty line
            continue
        p = local_path(str(text))  # in this machine's form
        if p.is_file():  # one file
            take(p)
        elif p.is_dir():  # a folder: everything under it
            for root, dirs, names in os.walk(p):  # top down, so folders can be pruned
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in SKIP_DIRS)  # past hidden, code and system folders
                for n in sorted(names):  # files in name order
                    if looked[0] >= MAX_SEEN:  # a whole drive: what was found so far is enough
                        break
                    if not n.startswith(("~$", ".")):  # Office lock files and hidden files
                        take(Path(root) / n)
                if looked[0] >= MAX_SEEN:  # and no other folder either
                    dirs[:] = []  # no deeper
                    break  # and no further
        else:  # nothing there
            skipped.append({"path": str(text).strip(), "why": "not_found"})
        if looked[0] >= MAX_SEEN:  # the paths after this one are not walked either
            skipped.append({"path": str(text).strip(), "why": "too_many"})
            break
    if len(files) > MAX_FILES:  # more than a run reads: documents before notes before pictures, each kind in walk order
        best = sorted(range(len(files)), key=lambda i: (RANK.get(files[i].suffix.lower(), 3), i))[:MAX_FILES]  # the ones to read
        skipped.append({"path": f"{len(files) - MAX_FILES} more", "why": "too_many"})
        files = [files[i] for i in sorted(best)]  # back in walk order
    return files, skipped


def pick_contact(texts: list[str], rx: re.Pattern, key: str) -> str:
    """The email or the phone a person's files write most, read from the start of each file (where a resume writes its
    owner's) and, when no start has one, from the whole text. A clone address, a robot's address or a picture's name is
    never taken. Ties go to the one written first. Returns it as first written, or ""."""
    def found(parts):  # the values in these texts, in order
        out = []
        for x in parts:  # each text
            for m in rx.finditer(re.sub(r"\s+", " ", x)):  # each match, however the line was wrapped
                v = m.group(0).strip()  # as written
                if key == "email" and NOT_A_PERSON.search(v):  # git@github.com, noreply@..., logo@2x.png
                    continue
                out.append(v)
        return out
    got = found([x[:HEAD] for x in texts]) or found(texts)  # the starts first
    if not got:
        return ""
    norm = (lambda v: re.sub(r"\D", "", v)) if key == "phone" else str.lower  # 010-1234-5678 and 01012345678 are one number
    counts = Counter(norm(v) for v in got)  # how often each is written
    best = max(counts.values())  # the most
    return next(v for v in got if counts[norm(v)] == best)  # the first of the most written, as written


def read_questions(api, jid: str) -> list[dict]:
    """A job's application questions as kept (apps/api/answers.py), none when it has none."""
    return (json.loads((api.ws.job_dir(jid) / "questions.json").read_text(encoding="utf-8")).get("questions") or []) if (api.ws.job_dir(jid) / "questions.json").is_file() else []


def estimate(n_files: int, with_job: bool, agent: bool = True) -> dict:
    """About how many agent calls and minutes a run takes, for the page to say before it starts. With no agent nothing is
    written by a model: the run is the typesetting, a minute or two, and saying seven minutes for it read as a wrong clock."""
    if not agent:  # profile files read as they are, then the PDFs
        return {"calls": 0, "minutes": 2}
    calls = n_files + 6 + 3 + 7 + (1 + 3 + 1 + 2 * SCRIPTS if with_job else 0)  # reading, writing, English, figures, then the posting's analysis, letter, map and scripts
    return {"calls": calls, "minutes": max(5, round(calls * 0.45))}  # about half a minute a call, seen on real runs


def read_json_file(path: Path) -> dict:
    """A JSON object from a file, or {} when it is missing or not an object (the result's sentence is never worth a failed run)."""
    try:
        got = json.loads(Path(path).read_text(encoding="utf-8"))  # as written
    except (OSError, ValueError):  # missing, or cut short
        return {}
    return got if isinstance(got, dict) else {}


RUNS_KEPT = 12  # finished runs the page lists, newest first


def runs(ws) -> list[dict]:
    """The runs that finished, newest first: when, the job, the files on the Desktop, or why it stopped."""
    try:
        got = json.loads(ws.path("out", "runs.json").read_text(encoding="utf-8"))  # kept with the workspace
    except (OSError, ValueError):  # none yet, or a file that is not JSON
        return []
    return [r for r in got if isinstance(r, dict)][:RUNS_KEPT] if isinstance(got, list) else []  # the list, bounded


def keep_run(ws, end: dict) -> None:
    """One finished run at the head of the list (out/runs.json), so the page shows what was made after a restart too."""
    rec = {"at": round(time.time()), "state": end.get("state"), **(end.get("result") or {}), "error": (end.get("error") or {}).get("code")}  # one line of the list
    f = ws.path("out", "runs.json")  # beside the interview kit's outputs
    f.parent.mkdir(parents=True, exist_ok=True)  # a new workspace has no out/ yet
    f.write_text(json.dumps([rec] + runs(ws)[: RUNS_KEPT - 1], ensure_ascii=False, indent=1), encoding="utf-8")  # newest first


def chain(api, mids: list[str], paths: list[str], posting: str, url: str, again: str = "", theme: str = "navy", max_pages: int = 3, job: str = "") -> None:
    """The task: one run, then the one asked for while it ran (a posting pasted during the reading, say). The ending and
    the start of the next run are written in one step under the tasks' lock, so a request that arrives meanwhile is
    either queued here or starts a task of its own, never both and never lost."""
    t = api.tasks  # the panel's tasks
    args = (mids, paths, posting, url, again, theme, max_pages, job)  # this run
    while True:
        end = Run(api).go(*args)  # the steps as it goes; how it ended
        keep_run(api.ws, end)  # listed on the page
        with t.state_lock:  # the end and the next start together
            nxt, t.autopilot_next = t.autopilot_next, None  # what was asked meanwhile
            rec = t.tasks.setdefault("autopilot", {})  # this task's record
            if not nxt:  # nothing waiting (a stop empties what waited: see routes.py)
                rec.update(end, step="", t=time.time())  # done or error, for the page
                return
            t.autopilot_stop.clear()  # asked after the stop, so it runs
            rec.update(state="running", step="queued", result=None, error=None, problems=[], steps=[], job=None, t=time.time())  # the next run on the same card, its job not known yet
        args = nxt  # and on


class Run:
    """One run: its steps in order, its state for the page, and a stop the person can ask for."""

    def __init__(self, api, key: str = "autopilot"):
        self.api, self.t, self.key = api, api.tasks, key  # the panel, its tasks, this task's key
        self.steps = []  # [{id, state, detail}] in order
        self.problems = []  # steps that failed, with their reason

    def plan(self, with_job: bool, fresh: bool = True, again: bool = False, analyze: bool = True, answers: bool = False) -> None:
        """The steps this run will take. Without new files (fresh False) a posting is tailored from the facts already kept;
        again makes one edition's PDFs once more (after the person filled in a missing name, say); a job already added and
        read (analyze False) goes straight to the writing."""
        ids = ["typeset", "export"] if again else (["collect", "read", "keep", "contact"] if fresh else []) + (["analyze"] if with_job and analyze else []) + \
            ["write", "english", "figures"] + (["answers"] if answers else []) + ["typeset"] + (["interview"] if with_job else []) + ["export"]
        self.steps = [{"id": s, "state": "waiting", "detail": ""} for s in ids]  # all waiting
        self.show(started=time.time())  # the page's clock counts from here

    def show(self, **values) -> None:
        """The task's state for the page: the steps and anything else."""
        self.t._set(self.key, steps=[dict(s) for s in self.steps], problems=list(self.problems), **values)

    def step(self, sid: str, state: str, detail: str = "") -> None:
        """One step's state: running, done, failed or skipped."""
        for s in self.steps:  # find it
            if s["id"] == sid:
                s.update(state=state, detail=detail)
        if state == "failed":  # kept for the summary
            self.problems.append({"step": sid, "why": detail})
        self.show(step=sid if state == "running" else "")

    def task_result(self, key: str, fn) -> dict:
        """Run a step that reports through its own task record, and read how it ended: {state: done} or {state: <error code>}."""
        for _ in range(1800):  # the same task started from the page (its own button): this step waits for it, up to 15 minutes
            if (self.t.state().get(key) or {}).get("state") != "running":  # free
                break
            time.sleep(0.5)  # and again
        self.t._set(key, state="running", error=None)  # an earlier run's ending must not be read as this one's
        try:
            fn()  # the step
        except (Exception, SystemExit) as exc:  # a bug, or the engine stopping with a message (resume.py exits so): its key must not stay running, or its button refuses until a restart
            self.t._set(key, state="error", error={"code": "unexpected", "detail": type(exc).__name__})
            raise  # the caller says which step failed
        got = self.t.state().get(key) or {}  # how it ended
        if got.get("state") in ("done", "running"):  # running: it set nothing, which counts as done
            return {"state": "done"}
        err = got.get("error") or {}  # the task's own reason: its code, and the cleaned detail some codes carry
        return {"state": err.get("code") or "failed", "detail": str(err.get("detail") or "")[:200]}

    def stopped(self) -> bool:
        """The person asked the run to stop."""
        return self.t.autopilot_stop.is_set()

    def find_contact(self, mids: list[str]) -> list[str]:
        """Step 4: the person's name, email and phone from the files just read, for the fields "Your details" does not
        have yet. The email and the phone are found by their shape; the name is asked of the agent in a question of its
        own and kept only when the files write it. Returns the fields filled in."""
        import llm  # src/llm.py: the one door to a model
        api, t = self.api, self.t  # short names
        person, det = api.facts.profile().get("person") or {}, api.facts.details()  # what the profile has now
        have = lambda k: str(det.get(k) or person.get(k) or "").strip()  # noqa: E731  a field already filled
        texts = [t.read_texts.get(m, "") for m in mids if t.read_texts.get(m, "").strip()]  # the text of each file read
        flat = re.sub(r"\s+", " ", "\n".join(texts))  # one line, to find a name however it was wrapped
        found = {}  # field -> value
        for key, rx in (("email", EMAIL), ("phone", PHONE)):  # by their shape
            if not have(key):  # only what the person left empty
                got = pick_contact(texts, rx, key)  # the one a person's own files write most
                if got:
                    found[key] = got
        if not have("name") and texts and t.backend() != "none":  # the name needs a reader
            head = "\n\n".join(x.strip()[:1500] for x in texts)[:6000]  # the start of each file: where a name is written
            try:
                with t.model_lock:  # one model task at a time
                    out = llm.run("panel-name", NAME_PROMPT.format(text=head), want_json=True, required=("name",), backend=t.backend(), timeout=120)  # one small call
            except (llm.LLMUnavailable, ValueError):  # no answer, or never the right form
                out = {}  # the person fills it in later
            for key in ("name", "name_en"):  # each, only as the files write it
                v = re.sub(r"\s+", " ", str((out or {}).get(key) or "")).strip()  # the answer
                if v and len(v) <= 40 and v in flat and not have(key):  # written in the files, and not set by the person
                    found[key] = v
        if found:  # into "Your details" (one undo step), with the file and the words each value was found in
            names = {m.get("id"): m.get("name") for m in api.ws.materials()}  # material id -> its file name
            src = {}
            for key, v in found.items():
                for m in mids:  # the first file that writes it
                    text = t.read_texts.get(m, "")
                    at = text.find(v)
                    if at >= 0:
                        src[key] = {"file": names.get(m) or "", "material": m, "quote": re.sub(r"\s+", " ", text[max(0, at - 40):at + len(v) + 40]).strip()}   # the words around it
                        break
                else:  # written in another shape (a phone's spaces): found in these files, the place not kept
                    src[key] = {"file": names.get(mids[0]) or "", "material": mids[0], "quote": ""}
            api.details({"fields": found, "src": src})
        return sorted(found)  # the fields filled

    def read_files(self, mids: list[str], paths: list[str]) -> dict | None:
        """Steps 1 to 3: the files into the workspace, read by the agent, and every fact whose quote checked out kept.
        How the run ends when it cannot go on (nothing to read, no agent, no job held in what was read), else None."""
        api, t = self.api, self.t  # short names
        # 1. the files: the ones the page uploaded, and the ones under the paths
        self.step("collect", "running")
        api.drop_example()  # the fictional example leaves first: its facts and details must not mix with the person's own
        files, skipped = collect(paths)  # the files under the paths
        for f in files:  # each into the workspace's sources, as an upload would be
            try:
                mids.extend(m["id"] for m in api.ws.add_materials(f.name, f.read_bytes()))  # its id; a zip gives one per file in it
            except OSError as exc:  # unreadable after all
                skipped.append({"path": str(f), "why": "unreadable"})
                log.info("autopilot: %s unreadable: %s", f, exc)
        if not mids:  # nothing to read
            self.step("collect", "failed", "no_files")
            return {"state": "error", "error": {"code": "no_files"}, "skipped": skipped}
        self.step("collect", "done", str(len(mids)))
        self.show(skipped=skipped)
        if self.stopped():  # the person stopped it: the files stay listed, unread
            return None
        # 2. reading: the agent finds fact candidates, each with a quote that must be in its file
        self.step("read", "running", str(len(mids)))
        self.task_result("ingest", lambda: t._ingest(mids, stop=self.stopped))  # the panel's own reading, shown as reading on every view
        got = t.state().get("ingest") or {}  # how it ended
        if (got.get("error") or {}).get("code") == "agent_unavailable":  # no agent: nothing more can be written
            self.step("read", "failed", "agent_unavailable")
            return {"state": "error", "error": {"code": "agent_unavailable"}}
        self.step("read", "done" if got.get("state") == "done" else "failed", str(got.get("added", 0)) if got.get("state") == "done" else (got.get("error") or {}).get("code", ""))
        if self.stopped():  # stopped while it read: what was read waits in the profile to be confirmed by hand
            return None
        # 3. keeping: every fact whose quote checked out
        self.step("keep", "running")
        kept = api.keep_all()  # the panel's own "keep all"
        if not api.facts.profile().get("roles"):  # no job held in what was read: a resume needs one
            self.step("keep", "failed", "no_roles")
            return {"state": "error", "error": {"code": "no_roles"}}
        self.step("keep", "done", str(kept))
        return None

    def go(self, mids: list[str], paths: list[str], posting: str, url: str, again: str = "", theme: str = "navy", max_pages: int = 3, job: str = "") -> dict:
        """The whole run. Each step's own task keeps its details; this one keeps the order and the summary. Returns how
        it ended ({state, result} or {state, error}); the caller writes it, together with the next run's start."""
        api, t = self.api, self.t  # short names
        if again:  # one edition's PDFs once more
            return self.again(again, theme, max_pages)
        with_job = bool(job or posting.strip() or url.strip())  # a posting, or a job already added, turns on the job's steps
        fresh = bool(mids or paths)  # new files to read; without them the facts already kept are tailored to the posting
        asks = bool(job) and any(q.get("text") for q in read_questions(api, job))  # a job added earlier may carry the application's own questions
        self.plan(with_job, fresh, analyze=not job, answers=asks)
        t0 = time.time()  # the run's clock
        if fresh:  # 1 to 3: the files read and their facts kept
            end = self.read_files(mids, paths)  # how the run ends early, if it does
            if end:  # nothing can be written
                return end
            if not self.stopped():  # 4. the name, email and phone
                self.step("contact", "running")
                try:
                    got = self.find_contact(mids)  # the fields filled
                    self.step("contact", "done", str(len(got)))
                except Exception as exc:  # noqa: BLE001  a missing name is said at the PDFs, with a field to fill
                    log.exception("autopilot contact failed")
                    self.step("contact", "failed", type(exc).__name__)
        elif not api.facts.profile().get("roles"):  # a posting alone, and no job kept yet to tailor
            return {"state": "error", "error": {"code": "no_roles"}}
        jid = job or GENERAL_EDITION  # the job asked for, else the edition with no job, unless a posting came
        if with_job and not job and not self.stopped():  # 4. the posting: its card, then the agent's reading of it
            self.step("analyze", "running")
            try:
                jid = api.add_job({"posting": posting, "url": url}, select=False)  # its folder and card; the job in view stays, so an edit in progress lands where it began
                t._analyze(jid)  # what the posting asks for, by the agent
                self.step("analyze", "done")
            except ValueError as exc:  # a link that did not open, or an empty posting
                self.step("analyze", "failed", str(exc))
                jid = GENERAL_EDITION  # the general documents still come out
        self.show(job=jid)  # the application this run makes: its Documents tab says so while it runs
        for sid, fn in (("write", lambda: t._write(jid, "ko")), ("english", lambda: self.task_result("translate", lambda: t._translate(None if jid == GENERAL_EDITION else jid))),
                        ("figures", lambda: t._figures(jid, "ko"))):  # 5 to 7: the words, the English, the figures
            if self.stopped():  # the person asked to stop
                break
            self.step(sid, "running")
            try:
                res = fn() or {}  # the panel's own step: {state, ...}
                ok = res.get("state") == "done"  # anything else is a reason
                self.step(sid, "done" if ok else "failed", "" if ok else str(res.get("state") or ""))
            except Exception as exc:  # noqa: BLE001  one step's failure leaves the others to run
                log.exception("autopilot step %s failed", sid)
                self.step(sid, "failed", type(exc).__name__)
        if asks and not self.stopped():  # the application's own questions, answered within their limits
            self.step("answers", "running")
            try:
                res = self.task_result(f"answers:{jid}", lambda: t._answers(jid))  # the panel's own task
                bad = sum(1 for q in read_questions(api, jid) if q.get("issues"))  # answers still to fix
                self.step("answers", "done" if res.get("state") == "done" and not bad else "failed",
                          str(len(read_questions(api, jid))) if res.get("state") == "done" and not bad else ("answers_need_attention" if bad else res.get("state", "")))
            except Exception as exc:  # noqa: BLE001  the documents still come out
                log.exception("autopilot answers failed")
                self.step("answers", "failed", type(exc).__name__)
        made = self.typeset(jid, with_job, theme, max_pages) if not self.stopped() else []  # 8. typesetting, both languages; the letter with them when there is a posting
        if with_job and jid != GENERAL_EDITION and not self.stopped():  # 9. the interview kit: its question map and the first scripts
            self.step("interview", "running")
            try:
                t.ensure_kit(jid, "ko")  # the question map
                n, stopped = t._draft_scenes(jid, SCRIPTS, cancel=self.stopped)  # the likeliest questions first; a stop ends it after the scripts in progress
                t.ensure_kit(jid, "ko")  # the map sees the drafts
                self.step("interview", "done" if n and not stopped else "failed", str(n))
            except Exception as exc:  # noqa: BLE001
                log.exception("autopilot interview failed")
                self.step("interview", "failed", type(exc).__name__)
        written = self.export(jid, made) if not self.stopped() else []  # 10. the Desktop
        return self.ending(jid, written, t0, made)

    def typeset(self, jid: str, with_cover: bool, theme: str, max_pages: int) -> list[str]:
        """Step 8: both languages typeset by the panel's own build; a reason per language that failed. Returns the
        languages made by this run: only those are copied and shown, never an older edition left in the folder."""
        self.step("typeset", "running")
        made = []  # the languages made
        for lang in LANGS:  # Korean, then English
            try:
                res = self.task_result(f"build:{jid}", lambda: self.t._build(jid, lang, theme, max_pages, with_cover=with_cover, write_cover=with_cover))  # the panel's own build
                if res.get("state") == "done":  # typeset and checked
                    made.append(lang)
                else:  # the build's own reason, such as a missing name or translation, with its detail for the result's sentence
                    self.problems.append({"step": "typeset", "why": res.get("state"), "lang": lang, **({"detail": res["detail"]} if res.get("detail") else {})})
            except (Exception, SystemExit) as exc:  # noqa: BLE001  one language may fail alone, also when the engine exits with a message
                log.exception("autopilot typeset %s failed", lang)
                self.problems.append({"step": "typeset", "why": type(exc).__name__, "lang": lang})
        if with_cover:  # a posting's run writes its letter with the build: one that did not come out is said on the result, not left for the person to find missing
            for lang in made:  # each edition made
                letter = (read_json_file(self.t.build_dir(jid, lang) / "build.json").get("cover")) or None  # the build's record of its letter (None: no letter step on this PC)
                if letter and letter.get("state") not in ("done", "drafted"):  # written and typeset, or written with no typesetting here: anything else was not written
                    self.problems.append({"step": "cover", "why": letter.get("error") or letter.get("state") or "failed", "lang": lang})
        self.step("typeset", "done" if made else "failed", ", ".join(made) if made else next((p["why"] for p in self.problems if p["step"] == "typeset"), ""))
        return made  # for the copies and the tiles

    def export(self, jid: str, langs: list[str]) -> list[str]:
        """Step 10: the editions this run made, copied to the Desktop under readable names."""
        self.step("export", "running")
        written = []  # the names
        for lang in langs:  # each edition made by this run
            refused = []  # a Word or PowerPoint file kept home by its own check
            try:
                written += self.t.export(jid, lang, refused)  # readable names, never overwriting
            except ValueError as exc:  # it failed its checks, changed after them, or its copy did not read back: said on the result
                self.problems.append({"step": "export", "why": str(exc), "lang": lang})
            except Exception as exc:  # noqa: BLE001  an edition that was not made has nothing to copy
                log.info("autopilot export %s: %s", lang, exc)
            self.problems += [{"step": "export", "why": r["why"], "lang": lang} for r in refused]  # said on the result too, with why
        if jid != GENERAL_EDITION:  # a job's answers, as one text file beside its documents
            try:
                written += self.t.export_answers(jid)  # none when there are no questions
            except ValueError as exc:  # an answer still to fix: said on the result
                self.problems.append({"step": "export", "why": str(exc)})
        self.step("export", "done" if written else "failed", str(len(written)))
        return written

    def ending(self, jid: str, written: list[str], t0: float, made: list[str] | None = None) -> dict:
        """How the run ended, for the chain to write: the job, the editions it made, the files, the time and what went wrong."""
        for s in self.steps:  # what never ran because the person stopped it
            if s["state"] == "waiting":
                s["state"] = "skipped"
        self.show(step="")  # the steps as they ended
        return {"state": "done", "result": {"job": jid, "langs": list(made or []), "files": written, "seconds": round(time.time() - t0), "stopped": self.stopped(),
                                            "problems": self.problems[:12]}}

    def again(self, jid: str, theme: str, max_pages: int) -> dict:
        """One edition's PDFs once more, and their copies on the Desktop (the person filled in what was missing)."""
        self.plan(False, again=True)
        t0 = time.time()  # the run's clock
        made = self.typeset(jid, jid != GENERAL_EDITION, theme, max_pages)  # the letter too, for a job
        written = self.export(jid, made) if not self.stopped() else []
        return self.ending(jid, written, t0, made)
