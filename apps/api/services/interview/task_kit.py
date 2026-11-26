"""Tasks' part for the interview kits (apps/api/tasks.py inherits it): the interview service's long tasks and its kit servers."""
from __future__ import annotations

from collections import OrderedDict  # the deck data of the kits used last, in the order they were used
from pathlib import Path  # paths
import hashlib  # a short stamp of the kit's files
import logging  # the panel's log
import re  # names and patterns
import threading  # threads and locks
import time  # the day the talk was made, for its file names
import urllib.parse  # a job's name in an address

from ...core.workspace import read_json, write_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]  # the repository (or the app's bundle)
log = logging.getLogger("offerowl.panel")  # the panel's log
KIT_KEEP = 4  # kit servers kept for the panel's /kit/<job>/ (one per job, the most recently used); the deck data too
KIT_GRACE = 30  # seconds a kit server let go keeps answering what was already on its way
SCRIPTS_AT_ONCE = 10  # interview scripts one click writes: about ten minutes of the agent, and the likeliest questions come first
SCRIPT_WORKERS = 3  # scripts written side by side by a CLI agent



NAMES_MADE = "# the resume's English names, made again on each refresh (lines above this one are the kit's own)"  # names.txt: where the made block starts
_TRIM = []  # glibc's malloc_trim, looked up once ([None] where there is none)

class Kits:
    """Each job's interview kit: its server for the panel's /kit/<job>/, its folder and question map, and the scripts the agent
    writes for it."""

    def __init__(self):
        super().__init__()  # the other parts' own
        self.kit_srvs = {}  # job -> (its own kit server, the agent it was given) for the panel's /kit/<job>/, the most recent last (kit_url)
        self._deck_cache, self._deck_lock = OrderedDict(), threading.Lock()  # the panel's deck data per kit stamp, the least recently used first
        self.kit_lock = threading.Lock()  # one start at a time: two first requests never bind two servers for one job

    @staticmethod
    def interview_available() -> bool:
        """The interview kit (src/interview/) is there."""
        return (ROOT / "src" / "interview").is_dir()  # the kit is optional: without it there are no interview steps

    def kit_url(self, job_id: str) -> str | None:
        """The address of this job's own kit server, for the panel's /kit/<job>/ (apps/api/web.py kit_proxy): one per job, on a
        free port of this process, the last KIT_KEEP kept, so two tabs on two jobs never swap a server under each other. A
        server is made again when the agent setting changed since it started (practice talks to the agent it was given). It is
        built and stopped outside the lock, so one job's first open never holds another job's request, and a server let go
        stops after KIT_GRACE seconds, so a request already on its way to it is answered. None when src/interview/ is
        missing, the job has no kit yet, or it would not start."""
        if not self.interview_available() or not (self.ws.job_dir(job_id) / "interview").is_dir():  # nothing to serve (a talk alone has the folder: its PDFs come from this server)
            return None
        backend = self.backend()  # the agent practice would talk to now
        with self.kit_lock:
            got = self.kit_srvs.pop(job_id, None)  # taken out and put back last: the order is how recently each was used
            alive = bool(got) and getattr(got[0], "loop", None) is not None and got[0].loop.is_alive()  # its serving thread still runs (one that died answers nothing)
            if got and got[1] == backend and alive:  # running, with the agent in use
                self.kit_srvs[job_id] = got
                return f"http://127.0.0.1:{got[0].server_address[1]}/"
        if got:  # made with another agent: let go, a new one below
            self._stop_kit_later(got[0])
        from interview import dense  # the optional similarity model's setting; standard library only until it is switched on
        from interview import server as iv  # src/interview/server.py
        from interview.job import Job  # the kit's job folder
        model, problem = dense.from_setting()  # the folder OFFEROWL_SEARCH_MODEL names: the kit's page then has its similarity switch
        if problem:  # a folder without the model's files: no switch, and the log says why
            log.warning("%s: no %s in that folder; the kit searches by keywords only", dense.SETTING, problem)
        try:
            srv, _ = iv.make_server(Job(self.ws.job_dir(job_id), confined=True), port=0, host="127.0.0.1", backend=backend,  # a free port; only this process reaches it
                                    model_dir=model)  # off until the page's switch loads it; each job's kit holds its own copy while on
        except (OSError, SystemExit) as exc:  # the kit is unreadable
            log.warning("interview kit for %s did not start: %s", job_id, exc)
            return None
        srv.loop = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True, name=f"kit-{job_id}")  # kept on the server: kit_url asks it whether it still serves
        srv.loop.start()
        with self.kit_lock:
            other = self.kit_srvs.get(job_id)  # another request made one meanwhile: that one stays
            if other:
                self._stop_kit_later(srv)
                srv = other[0]
            else:
                self.kit_srvs[job_id] = (srv, backend)  # the most recent last
            while len(self.kit_srvs) > KIT_KEEP:  # the oldest beyond the few kept
                self._stop_kit_later(self.kit_srvs.pop(next(iter(self.kit_srvs)))[0])
        return f"http://127.0.0.1:{srv.server_address[1]}/"

    def kit_view(self, job_id: str, lang: str = "ko") -> dict | None:
        """What the panel's own script view reads (src/interview/server.py view_data): the job's items with their scripts,
        the phrasings, the kit's settings, the synonym groups and the view's words in the panel's language, with whether a
        similarity model can be switched on and the address its questions go to. Read from the job's own kit server, which
        keeps the parsed files until one changes. None when the job has no kit or it would not start."""
        if not (self.ws.job_dir(job_id) / "interview" / "kit.json").is_file():  # no kit: a talk's brief alone makes the folder, not the scripts (the board and the deck say the same)
            return None
        base = self.kit_url(job_id)  # this job's kit server, started when it is not up
        with self.kit_lock:
            got = self.kit_srvs.get(job_id)
        if not base or not got:
            return None
        from interview import server as iv  # src/interview/server.py
        handler = got[0].RequestHandlerClass  # the server's own index and model
        index = handler.index
        index.ensure()  # the files read again when one changed
        data = iv.view_data(index.job, index.items, index.alts, lang=lang, model=handler.dense is not None)
        data["api"] = "/kit/" + urllib.parse.quote(job_id, safe="") + "/"  # where the view asks for similarity (web.py kit_proxy)
        data["stamp"] = hashlib.sha1(repr(index.stamp).encode("utf-8")).hexdigest()[:12]  # changes when a kit file does
        return data

    def kit_scripts(self, job_id: str) -> int:
        """How many scripts the job's kit holds, counted as the board counts them (a scene or a deep dive with its dialogue):
        its printable pages wait for the first one (C4-03). Read from the job's own kit server, which keeps the parsed files
        until one changes; 0 when the job has no kit or it would not start."""
        from .studio import turns  # a scene's dialogue, as the board reads it
        if not self.kit_url(job_id):  # no kit, or it would not start
            return 0  # nothing to print
        with self.kit_lock:  # never while another request starts or takes one
            got = self.kit_srvs.get(job_id)  # its server, started above
        if not got:  # let go meanwhile
            return 0  # read as none
        index = got[0].RequestHandlerClass.index  # the server's own index
        index.ensure()  # the files read again when one changed
        return sum(1 for it in index.items if it.get("role") in ("scenes", "deep") and turns(it.get("md", "")))  # a scene or a deep dive with its dialogue

    def kit_deck(self, job_id: str, lang: str = "ko") -> dict | None:
        """What the panel's own interview deck draws (src/interview/deck.py data): the same scripts in the same order as the
        printed deck, each line as written, with the deck's words in the panel's language. None when the job has no kit."""
        if not self.interview_available() or not (self.ws.job_dir(job_id) / "interview" / "kit.json").is_file():  # nothing to draw
            return None
        from interview import deck as ivdeck  # src/interview/deck.py
        from interview.job import Job  # the kit's job folder
        try:
            job = Job(self.ws.job_dir(job_id), confined=True)  # the kit's job folder
            from interview import corpus  # the stamp of the scripts' files
            watched = [job.out_path() / "plan.json", job.dir / "status.json"]  # what else the deck reads: the map and the application's record
            key = (job_id, lang, repr(corpus.stamp(job)), tuple((f.stat().st_mtime_ns, f.stat().st_size) if f.is_file() else None for f in watched))  # changes with any file it is made from
            with self._deck_lock:  # two requests at once make it once
                for old in [k for k in self._deck_cache if k[:2] == key[:2] and k != key]:  # this kit's deck before its files changed: never read again
                    del self._deck_cache[old]  # gone
                if key not in self._deck_cache:  # 2.5 s for a kit of 600 scripts: made once per change (C3-21)
                    while len(self._deck_cache) >= KIT_KEEP:  # four kits at most: the one used longest ago goes (it went in the order made, D4-11)
                        self._deck_cache.popitem(last=False)  # the least recently used
                    self._deck_cache[key] = ivdeck.data(job, lang=lang)  # read from the files as they are now
                self._deck_cache.move_to_end(key)  # used now
                return self._deck_cache[key]
        except (OSError, SystemExit) as exc:  # the kit is unreadable: said in the log, the panel says the deck could not be read
            log.warning("interview deck for %s could not be read: %s", job_id, exc)
            return None

    @staticmethod
    def _stop_kit_later(srv) -> None:
        """Stop a kit server after KIT_GRACE seconds, off the caller's thread: a request on its way to it is answered first.
        Its parsed scripts (tens of megabytes for a large kit) then go, and the memory goes back to the system."""
        def stop():
            srv.shutdown()  # stops its loop
            srv.server_close()  # frees the port
            srv.RequestHandlerClass = None  # its index and practice, let go with it
            Kits.give_back()  # the kit's memory, to the system (the allocator kept it: D4-11)
        timer = threading.Timer(KIT_GRACE, stop)
        timer.daemon = True  # never holds the exit
        timer.start()

    @staticmethod
    def give_back() -> None:
        """Hand the memory a kit's large answer freed back to the system: Python's allocator keeps what it frees for its next
        use, so the panel grew by tens of megabytes for each kit opened and never shrank (149 to 615 MB over twenty views of
        ten kits, D4-11). glibc's malloc_trim returns it; nothing to do elsewhere (Windows and macOS give it back themselves).
        web.py calls it once a kit's view or deck is sent."""
        if not _TRIM:  # looked up once
            fn = None  # no such call here
            try:
                import ctypes  # the C library
                import sys  # which system
                if sys.platform.startswith("linux"):  # glibc's own call
                    fn = ctypes.CDLL("libc.so.6").malloc_trim  # musl has none: OSError or AttributeError below
                    fn.argtypes, fn.restype = [ctypes.c_size_t], ctypes.c_int  # a size in, a number out
            except (OSError, AttributeError):  # another C library
                fn = None  # nothing to call
            _TRIM.append(fn)  # looked up once
        if _TRIM[0]:  # glibc
            import gc  # a kit's parsed scripts hold cycles (its handler class)
            gc.collect()  # freed now, not at the collector's next turn
            _TRIM[0](0)  # every arena trimmed to what it uses

    def let_kit_go(self, job_id: str) -> None:
        """Stop the kit server a job has, so the next open reads its folder and its kit.json again (a rename, a carried kit), or
        so nothing serves a job deleted for good."""
        with self.kit_lock:  # never while another request starts or takes one
            got = self.kit_srvs.pop(job_id, None)  # (server, agent), if it runs
        if got:  # it ran: stopped once what was on its way is answered
            self._stop_kit_later(got[0])

    def ensure_kit(self, job_id: str, lang: str = "ko") -> list[dict]:
        """Make or refresh the job's interview kit folder: kit.json (company, language, the resume it reads) and the
        resume's text, then the question map (src/interview/plan.py, no model) in the kit's output folder. Returns the map."""
        from interview import plan as ivplan  # the question map
        from interview.job import Job  # the kit's job folder
        from .. import documents  # the resume's text (the documents service's)
        jd = self.ws.job_dir(job_id)  # the job's folder
        iv = jd / "interview"  # the kit's own folder
        iv.mkdir(parents=True, exist_ok=True)  # made on first use
        st = self.ws.job(job_id) or {}  # the job's card
        company = str(st.get("company") or st.get("role") or job_id)  # how the questions name the company
        kit = read_json(iv / "kit.json", {}) or {}  # earlier settings, kept
        was = kit.get("company") if isinstance(kit.get("company"), dict) else {}  # the kit's names for it so far
        latin = re.search(r"\(([A-Za-z][\w .&+-]*)\)", company)  # 감마시스(gammasys): the Latin name written beside the Korean one
        en = was["en"] if was.get("ko") == company and was.get("en") and was["en"] != company else (latin.group(1).strip() if latin else company)  # an English name written for this same company stays
        kit.update(ui=lang, company={"ko": company, "en": en}, resume="interview/resume.txt")  # what this kit needs
        names = self.english_names(job_id)  # how the resume spells names in English
        nf = iv / "names.txt"  # one pair a line; .txt, so it is not read as scenes
        own = []  # the kit's own lines, written by hand or carried from another kit: kept as they are
        for ln in nf.read_text(encoding="utf-8").splitlines() if nf.is_file() else []:
            if ln.strip() == NAMES_MADE:  # the resume's block starts here: made again below
                break
            own.append(ln)
        spelled = {ln.split(" = ", 1)[0].strip("- ").strip() for ln in own if " = " in ln}  # the names the kit spells itself
        made = [f"- {ko} = {en}" for ko, en in names.items() if ko not in spelled]  # the resume's spellings of the rest
        if made or spelled:  # the scenes' English lines take these spellings, and the checks accept them
            nf.write_text("\n".join(own + ([NAMES_MADE] + made if made else [])) + "\n", encoding="utf-8")
            kit["names"] = "interview/names.txt"  # named in the kit
        else:  # no English names known
            kit.pop("names", None)  # a name of an older run must not stay
        deck = documents.printed_file(self, job_id, lang, "deck.pdf")  # the edition's deck, once its PDF is made (the documents')
        pages = self._deck_text(deck) if deck else ""  # its pages; none before the deck is made
        if pages:  # the map asks about each page, as the interviewer would
            (iv / "portfolio.txt").write_text(pages, encoding="utf-8")  # pages split by form feeds, as the map reads them
            kit["portfolio"] = "interview/portfolio.txt"  # named in the kit
        else:  # no deck yet: no pages to ask about
            kit.pop("portfolio", None)  # a name of an older run must not stay
        write_json(iv / "kit.json", kit)  # saved
        (iv / "resume.txt").write_text(documents.resume_text(self, lang if lang == "ko" or self.profile_lang() == "en" else "ko", job_id),  # the resume's claims
                                        encoding="utf-8")  # the kit asks about each line
        job = Job(jd, confined=True)  # the kit as src/interview reads it, kept inside the workspace
        rows = ivplan.build(job)  # the map: posting lines, resume lines, terms, behavioral, company, opening
        out = job.out_dir()  # <workspace>/out/interview/<job>
        write_json(out / "plan.json", {"job": job.name, "questions": rows})  # beside the drafts, as the kit's own plan command writes it
        return rows  # for the studio

    def english_names(self, job_id: str) -> dict:
        """{Korean name: English name} the person's English documents use: what the resume draft declared, the English names of a
        ledger's roles, and the English profile's company names."""
        from .. import documents  # the draft in force (the documents service's)
        out = {}  # Korean -> English, the first spelling found wins
        d, _ = documents.load_draft(self, job_id)  # the job's own draft, else the general edition's
        for x in (d or {}).get("evidence") or []:  # every drafted sentence
            for en, ko in (x.get("names") or {}).items() if isinstance(x, dict) else []:  # the spellings it declared
                if re.search(r"[가-힣]", str(ko)) and not re.search(r"[가-힣]", str(en)):  # a Korean name written in English
                    out.setdefault(str(ko).strip(), str(en).strip())  # kept
        prof = self.facts.profile()  # the facts' profile
        for r in prof.get("roles") or []:  # each role of the ledger form
            c = r.get("career") if isinstance(r, dict) and isinstance(r.get("career"), dict) else {}  # its career block
            ko, en = c.get("ko") or {}, c.get("en") or {}  # both halves
            for k in ("name", "short"):  # the full and the short name
                if ko.get(k) and en.get(k):  # both written
                    out.setdefault(str(ko[k]).strip(), str(en[k]).strip())  # kept
        en_prof = read_json(self.english_profile(), {}) if self.english_profile() else {}  # the English profile, when one was made
        for r, r_en in zip(prof.get("roles") or [], en_prof.get("roles") or []):  # the same roles in both
            if isinstance(r, dict) and isinstance(r_en, dict) and re.search(r"[가-힣]", str(r.get("org") or "")) and r_en.get("org"):  # a translated company name
                out.setdefault(str(r["org"]).strip(), str(r_en["org"]).strip())  # kept
        return {k: v for k, v in list(out.items())[:40] if k and v and k != v}  # a short list

    @staticmethod
    def _deck_text(pdf: Path) -> str:
        """The text of the edition's deck, or "" when it is not made or nothing here can read a PDF."""
        if not pdf.is_file():  # the PDFs were not made yet
            return ""  # the question map goes without it
        import pdftools  # the page text, with poppler or PDFium
        try:
            return pdftools.text(pdf)  # each page ended by a form feed
        except Exception:  # noqa: BLE001  no reader on this PC, or a damaged file: the rest of the map still stands
            log.exception("reading the deck failed")  # the reason for the log
            return ""  # the question map goes without it

    # ---- the presentation interview (src/interview/talk.py)

    def talk_folder(self, job_id: str) -> Path:
        """Where a job's talk is written: the kit's output folder, as the command line writes it. A job with no interview
        folder at all (the general edition, a job never tailored) has none: a folder that does not exist then, so its talk
        reads as not made instead of ending the request (the kit's Job stops a command with SystemExit)."""
        from interview.job import Job  # noqa: E402
        try:
            return Job(self.ws.job_dir(job_id), confined=True).out_path() / "talk"
        except SystemExit:  # no interview folder
            return self.ws.job_dir(job_id) / "interview" / "out" / "talk"  # nothing is there

    def talk_brief(self, job_id: str) -> dict:
        """The person's brief for the job's talk, as written (jobs/<job>/interview/talk.json), {} when none."""
        f = self.ws.job_dir(job_id) / "interview" / "talk.json"
        got = read_json(f, {}) or {}
        return got if isinstance(got, dict) else {}

    def save_talk_brief(self, job_id: str, brief: dict) -> dict:
        """Keep the brief the panel's form sends: the topics in order, the minutes, the day, the format and the interviewers' words.
        Every field is checked by talk.normalize before it is kept, so a brief that cannot make a talk is refused here."""
        from interview import talk as ivtalk  # noqa: E402
        if not isinstance(brief, dict):
            raise ValueError("bad_brief")
        keep = {k: brief[k] for k in ("lang", "minutes", "qa", "when", "format", "where", "request", "topics", "pages", "challenge", "order", "headline",
                                      "theme", "company") if k in brief}  # only the brief's own keys
        m = keep.get("minutes")  # the talk's length, as the form's field allows it: never kept outside 5 to 120 (talk.normalize read 999 as 30 but the brief kept 999)
        if m is not None and not (isinstance(m, (int, float)) and not isinstance(m, bool) and 5 <= m <= 120):
            raise ValueError("talk_minutes")
        try:
            ivtalk.normalize(keep, "en" if keep.get("lang") == "en" else "ko")  # the same checks the talk runs
        except ivtalk.TalkError as e:
            raise ValueError("bad_brief") from e
        stored = self.talk_brief(job_id)  # what is kept now: keys the form does not show (pages, the theme, swaps) stay as they are
        topics = keep["topics"] if "topics" in keep else stored.get("topics")  # the topics the brief will hold: the ones sent, else the ones kept
        titled = [x for x in (topics if isinstance(topics, list) else []) if str(x.get("title") if isinstance(x, dict) else x if isinstance(x, str) else "").strip()]  # each with words
        if not titled:  # an emptied topics box ([] read as "the usual four" and was kept as no topic at all): nothing is kept
            raise ValueError("bad_brief")
        if isinstance(keep.get("topics"), list) and isinstance(stored.get("topics"), list):  # a topic's own minutes and kinds stay with its title
            old = {str(x.get("title")): x for x in stored["topics"] if isinstance(x, dict)}
            keep["topics"] = [{**old.get(str(x.get("title")), {}), **x} if isinstance(x, dict) else x for x in keep["topics"]]
        merged = {**stored, **keep}
        (self.ws.job_dir(job_id) / "interview").mkdir(parents=True, exist_ok=True)
        write_json(self.ws.job_dir(job_id) / "interview" / "talk.json", merged)  # beside kit.json
        return merged

    def talk_state(self, job_id: str) -> dict:
        """The job's talk for the panel: its brief, whether it is made, and what the checks said."""
        f = self.talk_folder(job_id) / "talk.json"
        made = read_json(f, None)
        out = {"brief": self.talk_brief(job_id), "made": bool(made), "task": f"talk:{job_id}"}
        if made:  # the summary the panel shows beside the pages
            ch = made.get("checks") or {}
            out.update(slides=len(made.get("slides") or []), seconds=made.get("seconds", 0), minutes=(made.get("brief") or {}).get("minutes"),
                       lang=(made.get("brief") or {}).get("lang"), layout=sum(len(x.get("issues") or []) for x in ch.get("layout") or []),
                       pace=len(ch.get("pace") or []), dropped=len(ch.get("dropped") or []), calls=(made.get("record") or {}).get("calls", 0),
                       at=int(f.stat().st_mtime), pdf=(self.talk_folder(job_id) / "deck.pdf").is_file(), script=(self.talk_folder(job_id) / "script.pdf").is_file())
        return out

    def talk_script(self, job_id: str) -> dict | None:
        """The talk's speaker script as the panel draws it (src/interview/talk_page.py script_data): every slide with its time,
        what to say, where to point and the questions to expect, then the questions with what backs each answer. None when
        no talk is made."""
        from interview import talk_page  # noqa: E402
        folder = self.talk_folder(job_id)  # where the talk was written
        made = read_json(folder / "talk.json", None)  # as make() wrote it
        if not isinstance(made, dict) or not made.get("slides"):  # not made yet, or being written
            return None
        try:
            out = talk_page.script_data(made, folder)  # what the printed script holds
        except (KeyError, TypeError, ValueError, AttributeError) as exc:  # a file from an older version, an edited or a planted one: said in the log
            log.warning("the talk's script for %s could not be read: %s", job_id, exc)
            return None
        out["at"] = int((folder / "talk.json").stat().st_mtime)  # the pictures' addresses change with each new talk
        return out

    def talk_slide(self, job_id: str, n: int) -> Path | None:
        """The picture of the talk's n-th slide (1 for the first), or None."""
        from interview import talk_page  # noqa: E402
        pics = talk_page.pictures(self.talk_folder(job_id))  # one per slide, in order
        return pics[n - 1] if 1 <= n <= len(pics) else None

    def make_talk(self, job_id: str, lang: str = "ko") -> bool:
        """The presentation interview's deck and script (task "talk:<job>")."""
        return self.start(f"talk:{job_id}", self._make_talk, job_id, lang)

    def _make_talk(self, job_id: str, lang: str) -> None:
        key = f"talk:{job_id}"  # this task
        from interview import talk as ivtalk  # noqa: E402  the talk
        from interview.job import Job  # noqa: E402
        self._set(key, step="talk")  # the page says what runs
        job = Job(self.ws.job_dir(job_id), confined=True)  # the kit, kept inside the workspace: its files go into the agent's prompts
        with self.turn(key, self.model_lock, self.render_lock):  # the agent's words, then the deck's printing; said while it waits
            backend = self.backend()  # which agent, 'none' when off
            try:
                summary = ivtalk.make(job, lang=lang, backend=backend, log=log.info)  # plan, write, draw, check
            except ivtalk.TalkError as e:  # the brief, the profile or the portfolio stopped it: said on the page
                self._set(key, state="error", error={"code": "talk", "detail": str(e).splitlines()[0][:200]})
                return
        self._set(key, state="done", step="", result={k: v for k, v in summary.items() if k != "folder"})  # no path of this PC on the page

    def deliver_talk(self, job_id: str) -> list:
        """The talk's two PDFs on the Desktop, read back against their bytes; the names written."""
        from .. import documents  # noqa: E402  the Desktop (the documents service's)
        folder, out = self.talk_folder(job_id), []
        made = read_json(folder / "talk.json", {}) or {}
        lang = (made.get("brief") or {}).get("lang")  # the talk's language names its files
        words = {"deck.pdf": "발표 자료" if lang != "en" else "Talk slides", "script.pdf": "발표 대본" if lang != "en" else "Talk script"}
        made_at = (folder / "talk.json").stat().st_mtime if (folder / "talk.json").is_file() else None  # the talk's record keeps no time: its file's
        day = documents.made_day({"at": time.strftime("%Y-%m-%d", time.localtime(made_at))} if made_at else None)  # the day it was made, as the names carry it
        desk = documents.desktop_dir()
        desk.mkdir(parents=True, exist_ok=True)
        for name, word in words.items():
            src = folder / name
            if not src.is_file():
                continue
            base = documents.safe_name(str(made.get("company") or "")[:60], word, day)  # a name any system takes, with the day it was made
            dst = desk / documents.free_name(desk, base, ".pdf")  # never over a file that is there
            data = src.read_bytes()
            dst.write_bytes(data)
            if dst.read_bytes() != data:  # read back: a sync folder or a full disk would leave a wrong copy
                raise OSError(f"the copy on the Desktop differs: {dst.name}")
            out.append(dst.name)
        return out

    def write_scripts(self, job_id: str, lang: str = "ko", limit: int = SCRIPTS_AT_ONCE, ids: list[str] | None = None) -> bool:
        """More scripts for a job (task "scripts:<job>"): the likeliest questions first, or the map's entries named in ids (the
        questions of an interview round that no script answers yet)."""
        return self.start(f"scripts:{job_id}", self._write_scripts, job_id, lang, limit, ids)  # one per job at a time

    def _write_scripts(self, job_id: str, lang: str, limit: int, ids: list[str] | None = None) -> None:
        key = f"scripts:{job_id}"  # this task
        self._set(key, step="scripts", done=0, total=len(ids) if ids else limit)  # the page shows the count
        self.ensure_kit(job_id, lang)  # the map is there, and sees what was drafted before
        drafted, stopped = self._draft_scenes(job_id, limit, lambda done, total: self._set(key, done=done, total=total), ids=ids)  # the counter moves as each scene is finished
        self.ensure_kit(job_id, lang)  # the map again: it now sees these drafts
        self._set(key, state="done", step="", result={"drafted": drafted, "stopped": stopped})  # what the page says at the end

    def _draft_scenes(self, job_id: str, limit: int = 5, progress=None, cancel=None, ids: list[str] | None = None) -> tuple[int, bool]:
        """New scripts for the likeliest questions no scene covers, or for the map's entries named in ids, through
        src/interview/draft.py (checked in strict mode). Returns (how many passed, whether the agent stopped)."""
        from interview import draft as ivdraft  # the scene writer
        from interview import plan as ivplan  # the question map
        from interview.job import Job  # the kit's job folder
        job = Job(self.ws.job_dir(job_id), confined=True)  # the kit, kept inside the workspace: its files go into the agent's prompts
        before = {f.name for f in job.out_dir().glob("drafts/*.md")}  # draft files before
        stopped = False  # did the agent stop part way
        with self.model_lock:  # one model task at a time
            backend = self.backend()  # which agent
            try:
                _, why = ivplan.anticipate(job, backend=backend)  # the scenario and technical questions, asked once per job
                if why:  # the agent could not answer: the rest of the map still stands
                    log.info("expected questions for %s: %s", job_id, why)  # for the log
                write_json(job.out_dir() / "plan.json", {"job": job.name, "questions": ivplan.build(job)})  # the map with them
                jobs = 1 if backend == "openai-compat" else SCRIPT_WORKERS  # a local model answers one at a time; a CLI agent can take a few
                stopped = ivdraft.main(job, ids=",".join(ids) if ids else None, limit=0 if ids else limit, backend=backend, jobs=jobs,  # the entries asked for, or the likeliest
                                       progress=progress, cancel=cancel) == 1  # writes drafts/drafts-<n>.md and .rejected.md; 1 when the model stopped
            except (SystemExit, Exception) as exc:  # a scene did not parse, or a bug
                log.info("drafting scenes for %s stopped: %s", job_id, exc)  # for the log
                stopped = True  # said on the page
        new = [f for f in job.out_dir().glob("drafts/*.md") if not f.name.endswith(".rejected.md") and f.name not in before]  # the files this run wrote
        return sum(f.read_text(encoding="utf-8").count("\n### ") for f in new), stopped  # the scenes in them, and whether it stopped
