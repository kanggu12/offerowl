"""Tasks' part for the profile (apps/api/tasks.py inherits it): the person's files read into facts (src/ingest.py), the
English profile (src/draft.py task_translate) and the language the profile is written in, the kept facts as lines of text
an answer is written from, and the profile's own files every document reads: the style pack in use, the mask table of the
blind edition, the photo, and the pictures a profile names relative to its folder."""
from __future__ import annotations

import json  # the language's count and a profile file read
import logging  # the panel's log
import re  # a style pack's name
from pathlib import Path  # paths

from ...core.stamps import content_hash, file_hash, file_stamp  # what an English profile was made from, and the profile's stamp
from ...core.workspace import read_json, write_json  # files
from .facts import FACT_FILES  # the files a reading's undo step covers

log = logging.getLogger("offerowl.panel")  # the panel's log


class FactTasks:
    """The profile's tasks and the files of it the documents read."""

    def __init__(self):
        super().__init__()  # the other parts' own
        self.read_texts = {}  # material id -> the text its last reading found (the run's contact step looks for the name in it)
        self._lang = (None, "")  # (the profile file's stamp, its language): profile_lang reads the profile again only when it changed
        self.unstick()  # a file left "reading" by a reading that never ended (the app was closed, or it broke)

    def ingest(self, mids: list[str]) -> bool:
        """Read the listed materials and add the facts found (task "ingest")."""
        return self.start("ingest", self._ingest, list(mids))  # a copy of the ids: the caller's list may change

    def unstick(self, mids=None) -> None:
        """Files still marked "reading" go back to "new" (all of them, or those named): no reading is running for them, and
        the row would otherwise turn forever. They can be read again."""
        for m in self.ws.all_materials():  # every record, removed ones too
            if m.get("state") == "reading" and (mids is None or m.get("id") in mids):
                self.ws.update_material(m["id"], state="new")  # not read

    def _ingest(self, mids: list[str], stop=None) -> None:
        try:
            self._read(mids, stop)  # the reading itself
        except BaseException:  # it broke or was stopped hard: no file of it stays "reading"
            self.unstick(mids)
            raise  # the task records the error as before

    def _read(self, mids: list[str], stop=None) -> None:
        import ingest  # src/ingest.py
        recs = {m["id"]: m for m in self.ws.materials() if m["id"] in mids}  # the materials asked for
        fresh = {mid for mid, m in recs.items() if m.get("state") == "new" and "removed" not in m}  # added for this reading (never read, never put back): its undo takes them off the list
        profiles = [m for m in recs.values() if m["kind"] == "profile"]  # Offerowl profile files
        files = [m for m in recs.values() if m["kind"] != "profile"]  # everything else goes to the agent
        for m in recs.values():  # every file shows that it is being read
            self.ws.update_material(m["id"], state="reading", error="")  # shown at once
        by_mid, errors = {}, []  # imported profiles per material, problems
        for m in profiles:  # read as they are: no agent
            try:
                doc = json.loads(self.ws.material_path(m).read_text(encoding="utf-8"))  # the profile
                import review  # the profile's shape rules
                review.normalize(json.loads(json.dumps(doc)))  # a broken profile stops here, not at the build
                by_mid[m["id"]] = ("profile", doc)  # imported below, inside the undo step
            except (OSError, ValueError) as exc:  # unreadable or not the profile shape
                log.warning("profile %s unreadable: %s", m["id"], exc)  # the reason for the log
                self.ws.update_material(m["id"], state="error", error="profile_invalid")  # the page names the problem and offers removal
        texts, paths = {}, []  # converted text per file, files that have text
        self._set("ingest", step="reading_files")  # the step the page shows
        for m in files:  # turn each file into text first: empty ones need no agent
            p = self.ws.material_path(m)  # its file
            try:
                texts[str(p)] = ingest.to_text(p)  # PDF, Word, slides, text; images and scans through OCR
            except Exception as exc:  # a broken file
                log.warning("material %s unreadable: %s", m["id"], exc)  # the reason for the log
                texts[str(p)] = ""  # treated as a file without text
            self.read_texts[m["id"]] = texts[str(p)]  # kept for the run's contact step
            if texts[str(p)].strip():  # only files with text go to the agent
                paths.append(p)  # to the agent
            else:
                self.ws.update_material(m["id"], state="no_text")  # nothing to read in it
        asked_stop = stop  # the person's stop, from a run (autopilot.py)
        kept, dropped, stop = [], [], None  # facts found, facts without a quote, why the agent stopped
        if paths:  # no file with text: no model call
            self._set("ingest", step="asking_agent", files=len(paths))  # the pill says the agent is reading
            with self.model_lock:  # one model task at a time
                backend = self.backend()  # which agent
                try:
                    kept, dropped = ingest.extract(paths, backend=backend, texts=texts, stop=asked_stop)  # quotes checked against the text
                except ingest.Partial as exc:  # the agent stopped part way, or was never there, or the person stopped it
                    kept, dropped = exc.kept, exc.dropped  # what was read so far stays
                    stop = "stopped" if str(exc) == "stopped" else ("agent_unavailable" if not exc.asked else "agent_stopped")  # none asked: no agent; some asked: it stopped
                    log.info("ingest stopped: %s", exc)  # the reason for the log
        name_of = {str(self.ws.material_path(m)): (m["id"], m["name"]) for m in files}  # file -> material
        new = self.facts.ingest_candidates(kept, lambda f: name_of.get(f, ("", "")))  # panel candidates
        with self.ws.change({"code": "undo_add_material", "n": len(recs)}, FACT_FILES, adopt={"sources/materials.json": fresh}):  # one undo takes it all back, the new files' rows too
            alive = {m["id"] for m in self.ws.materials()}  # a source taken off while it was read brings nothing in
            by_mid = {mid: v for mid, v in by_mid.items() if mid in alive}
            new = [c for c in new if c["source"]["material"] in alive]
            dropped = [d for d in dropped if name_of.get(str((d.get("source") or {}).get("file", "")), ("", ""))[0] in alive | {""}]  # one of no known source stays
            files = [m for m in files if m["id"] in alive]
            count = 0  # facts added
            for mid, (_, doc) in by_mid.items():  # the profile files read earlier
                n = self.facts.import_profile(doc, mid, recs[mid]["name"])  # its items as facts to confirm
                self.ws.update_material(mid, state="done", facts=n)  # its count shows on its row
                count += n  # for the task's total
            count += self.facts.add_candidates(new, dropped)  # facts found by the agent
            for m in files:  # each file's own count and state
                if str(self.ws.material_path(m)) not in [str(p) for p in paths]:  # a file without text was marked already
                    continue  # no text: already marked
                n = sum(1 for c in new if c["source"]["material"] == m["id"])  # its facts
                state = "done" if not stop or n else ("needs_agent" if stop == "agent_unavailable" else "stopped")  # the file's own outcome
                self.ws.update_material(m["id"], state=state, facts=n)  # shown on its row
            self.facts.rebuild()  # the profile follows the facts
        if stop and stop != "stopped":  # an agent problem is the task's error; a stop the person asked for is not
            errors.append(stop)  # kept for the error band
        self._set("ingest", state="error" if errors else "done", step="", added=count,  # the task's end and how many facts came in
                  error={"code": errors[0]} if errors else None)  # the error band's code

    def translate(self, job_id: str | None = None) -> bool:
        """Write the English profile for English editions (task "translate"). When the job's resume draft holds English, only
        what the draft does not hold is translated."""
        return self.start("translate", self._translate, job_id)  # one translation at a time

    def _translate(self, job_id: str | None = None) -> None:
        import draft  # src/draft.py
        src = self.ws.path("profile", "profile.json")  # the Korean profile
        prof = self.facts.profile()  # as it is now
        partial = self.drafted_english(job_id)  # the draft writes most of the words already
        self._set("translate", step="asking_agent")  # the step the page shows
        with self.model_lock:  # one model task at a time
            if self.backend() == "none":  # no agent: say so without calling
                self._set("translate", state="error", error={"code": "agent_unavailable"})  # the band offers to turn the agent on
                return  # nothing else to do
            try:
                new, steps = draft.task_translate(prof, draft.style_pack(self.style_spec()), skip_drafted=partial)  # every field that passes the checks
            except draft.Stopped as exc:  # stopped part way: what was done is kept
                new, steps = exc.result, exc.log  # what was translated before it stopped
                if not steps:  # nothing at all came back
                    self._set("translate", state="error", error={"code": "agent_unavailable"})  # the same band as with no agent
                    return  # nothing else to do
        new["_from"] = content_hash(src)  # which Korean profile it was made from: its content, so writing it again the same changes nothing
        if partial:  # the draft's parts were not asked for
            new["_partial"] = True  # an edition without such a draft asks for the rest
        write_json(self.ws.path("profile", "profile.en.json"), new)  # beside the Korean one
        kept = sum(1 for s in steps if s.get("kept"))  # fields translated
        self._set("translate", state="done", step="", result={"fields": kept, "skipped": len(steps) - kept})  # how many fields made it through the checks

    def profile_lang(self) -> str:
        """The language the profile itself is written in: Korean when Hangul makes up a fair share of its text. Remembered while
        the profile file is unchanged: the state asks several times a poll, and counting the letters is most of its time."""
        stamp = file_stamp(self.ws.path("profile", "profile.json"))  # None: missing (built now) or written just now
        lang = self._lang  # one read of the pair: another thread may replace it meanwhile
        if stamp is not None and lang[0] == stamp:  # the same file as last time
            return lang[1]
        text = json.dumps(self.facts.profile(), ensure_ascii=False)  # every word of it
        han = sum(1 for ch in text if "\uac00" <= ch <= "\ud7a3")  # Hangul syllables
        latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())  # Latin letters
        out = "ko" if han * 3 >= latin * 0.5 and han > 20 else "en"  # a syllable carries more than a letter
        if stamp is not None:  # a version that can be told again: remembered
            self._lang = (stamp, out)
        return out

    def english_profile(self) -> Path | None:
        """The English profile when it was made from the profile as it is now, else None. A profile written in English
        is its own English profile."""
        if self.profile_lang() == "en":  # nothing to translate
            return self.ws.path("profile", "profile.json")  # the profile itself
        p = self.ws.path("profile", "profile.en.json")  # the translation
        if not p.is_file():  # never translated
            return None  # the English edition must ask for it
        src, made = self.ws.path("profile", "profile.json"), read_json(p, {}).get("_from")  # the profile, and the one it was made from
        return p if made and made in (content_hash(src), file_hash(src)) else None  # only a translation of this very profile (an older one names its bytes)

    def blind_path(self) -> Path:
        """Where the person's own mask table is kept (the workspace's blind.json), whether or not there is one: a build's
        clean-up names its staged copy by it."""
        return self.ws.path("blind.json")  # beside the profile and the jobs, never in the repository

    def blind_file(self) -> Path | None:
        """The person's own mask table (the workspace's blind.json, masks.set_blind), or None: then src/blind.json, which covers
        nothing."""
        f = self.blind_path()  # beside the profile and the jobs, never in the repository
        return f if f.is_file() else None

    def blind_table(self) -> dict:
        """The table a blind edition is made and checked with now: the person's own over the shipped one (src/blind.py)."""
        import blind  # src/blind.py: the merge and the patterns
        f = self.blind_file()  # their table, if any
        mine = read_json(f, {}) if f else {}  # as kept
        return blind.merged(mine if isinstance(mine, dict) else {})

    def blind_stamp(self) -> str:
        """What the person's table is now (a short hash of its content, "" for none): a blind edition made with another table is
        stale."""
        f = self.blind_file()  # their table, if any
        return content_hash(f) if f else ""

    def photo_paths(self) -> tuple:
        """Where the resume's photo may be kept: profile/photo.jpg and profile/photo.png, there or not (a build's clean-up names
        their staged copies by them)."""
        return self.ws.path("profile", "photo.jpg"), self.ws.path("profile", "photo.png")

    def studio_paths(self) -> tuple:
        """Where a cut-out photo's studio copies are kept, one per colour pack (out/_photo/studio_<theme>.jpg), there or not
        (a build's clean-up names their staged copies by them)."""
        from .evidence import THEMES  # src/themes.json's packs
        return tuple(self.ws.path("out", "_photo", f"studio_{t}.jpg") for t in THEMES if not t.startswith("_"))

    def photo_in(self, photo: Path, theme: str) -> Path:
        """The photo as a resume in this colour pack prints it: a cut-out PNG on the pack's studio backdrop (photo.studio: the
        name band's colour lit from behind the head), made again when the photo is newer; any other photo as it is."""
        from . import photo as P  # the backdrop
        from .evidence import THEMES  # the packs' name-band colours
        fill = (THEMES.get(theme) or {}).get("nameFill") if isinstance(THEMES.get(theme), dict) else None
        if not fill or photo.suffix.lower() != ".png":  # an unknown pack, or a photo with its own backdrop
            return photo
        f = self.ws.path("out", "_photo", f"studio_{theme}.jpg")  # this pack's copy
        try:
            if f.is_file() and f.stat().st_mtime_ns >= photo.stat().st_mtime_ns:  # made from this photo already
                return f
            made = P.studio(photo.read_bytes(), fill)  # None: nothing see-through, or no Pillow
            if not made:
                return photo
            f.parent.mkdir(parents=True, exist_ok=True)
            write_bytes = f.with_name(f.name + ".tmp")  # whole or not at all
            write_bytes.write_bytes(made)
            write_bytes.replace(f)
            return f
        except OSError:  # a folder that cannot be written: the photo as it is
            return photo

    def photo_for_build(self):
        """The resume's photo (the workspace's profile/photo.jpg or .png) when the setting puts it on the resume, else None."""
        if self.card.settings_fn().get("photo", True) is False:  # taken off the resume
            return None
        return next((f for f in self.photo_paths() if f.is_file()), None)

    def style_spec(self) -> str:
        """The style pack every draft and check uses: "default", or the path of the person's own pack in the workspace's
        style/ folder, chosen in the panel (the inspector's Style tab). A pack that has gone counts as the default."""
        name = str(self.card.settings_fn().get("style") or "default")  # the choice
        f = self.ws.path("style", f"{name}.json")  # where a person's pack lives
        return str(f) if name != "default" and re.fullmatch(r"[\w가-힣.-]{1,60}", name) and f.is_file() else "default"  # only a pack that is there

    def _place_pictures(self, prof: dict) -> dict:
        """A profile's pictures named relative to the workspace's profile/ folder (a company's, a school's or a project's logo,
        the portfolio PDF), made absolute in the edition's copy: the typesetting finds them wherever the edition's folder is, and
        the workspace stays whole when it is moved (its pictures live inside it). A path that is absolute, or names no file
        there, is left as it is."""
        base = self.ws.path("profile")  # where a relative picture path starts
        place = lambda p: str((base / p).resolve()) if isinstance(p, str) and p and not Path(p).is_absolute() and (base / p).is_file() else p  # noqa: E731
        holders = list(prof.get("roles") or []) + list(prof.get("education") or [])  # companies and schools
        holders += [x for r in prof.get("roles") or [] if isinstance(r, dict) for x in r.get("projects") or []]  # and projects
        for h in holders:
            if isinstance(h, dict) and isinstance(h.get("logo"), str):
                h["logo"] = place(h["logo"])
        deck = prof.get("deck")  # the portfolio the person made, one for both languages or one each
        if isinstance(deck, dict) and deck.get("pdf"):
            deck["pdf"] = {k: place(v) for k, v in deck["pdf"].items()} if isinstance(deck["pdf"], dict) else place(deck["pdf"])
        return prof

    def answer_facts(self, notes: bool = False) -> list[dict]:
        """The kept facts as an application's answers are written and checked from them (the applications' answers task):
        id, then its company, title, period and words. A project brought in with a profile file gives its whole text (its
        summary and the ledger's evidence under it): its card shows the first part only, and a detail further down (a tool, a
        system) is as much a fact as the start. With
        notes, also the profile file's own notes that are no fact card (a role's context tables, the confirmed notes): an
        answer the person wrote is checked against all of it, while the writing draws on the cards alone."""
        from .facts import _get, ledger_text, text_of  # an imported item, and its words
        st = self.facts.status()  # which were kept
        base = self.facts.base() or {}  # the imported profile, whole
        out = []  # one per kept fact
        for c in self.facts.candidates():  # every fact
            if st.get(c["cid"]) != "accepted":  # only what the person kept
                continue
            head = " · ".join(x for x in (c.get("org"), c.get("title"), c.get("period")) if x)  # whose and when
            body = str(c.get("statement") or c.get("quote") or "").strip()  # its words
            if c.get("origin") == "profile" and c.get("kind") == "role" and isinstance(c.get("ref"), list):  # an imported role: its description and department line too
                try:
                    item = _get(base, c["ref"])  # the role as the file has it
                except (KeyError, IndexError, TypeError):  # the file changed since
                    item = None
                if isinstance(item, dict):  # the lines under the company's name
                    body = " ".join(x for x in (body, text_of(item.get("sub")), text_of(item.get("desc"))) if x)
            if c.get("origin") == "profile" and c.get("kind") == "project" and isinstance(c.get("ref"), list):  # an imported project
                try:
                    item = _get(base, c["ref"])  # the project as the file has it
                except (KeyError, IndexError, TypeError):  # the file changed since: the card's words stand
                    item = None
                if isinstance(item, dict):  # its summary, then the ledger's evidence text
                    whole = " ".join(x for x in (text_of(item.get("summary")), ledger_text(item.get("body_md"))) if x).replace("==", "").strip()
                    body = whole if len(whole) > len(body) else body  # never less than the card
            out.append({"id": c["cid"], "text": (f"{head}: {body}" if body else head)[:4000]})  # bounded: one long project never fills an answer's room
        if notes:  # the profile file's notes that no card carries
            for ri, r in enumerate(base.get("roles") or []):  # each role's context tables (who ordered the work, the periods)
                for ci, cx in enumerate(r.get("context") or []):
                    words = ledger_text(cx.get("body_md")) if isinstance(cx, dict) else ""
                    if words:
                        out.append({"id": f"context:{ri}.{ci}", "text": f"{text_of(r.get('org')) or r.get('key') or ''}: {words}"[:4000]})
            for ni, n in enumerate(base.get("confirmed") or []):  # the notes the person confirmed
                words = ledger_text(n.get("body_md")) if isinstance(n, dict) else ""
                if words:
                    out.append({"id": f"confirmed:{ni}", "text": f"{text_of(n.get('title'))}: {words}"[:4000]})
        return out
