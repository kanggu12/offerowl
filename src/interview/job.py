"""Where a job's interview kit lives, and the settings it carries.

A workspace holds one person's material (see docs/ARCHITECTURE.md, "Your workspace"):

    profile/profile.json      the confirmed facts
    stories.md                behavioral stories, shared by every job
    style/<name>.json         style packs (banned words, forbidden wording)
    jobs/<job>/posting.md     the job posting
    jobs/<job>/submitted/     the resume and portfolio that were sent, as text (or PDF)
    jobs/<job>/interview/     the scene files (*.md), alts.json, eval_questions.json and kit.json

kit.json is optional. It names the scene files and their roles, the short tab names of the sections, extra
synonyms and the other per-job settings, so no job's names live in code. docs/INTERVIEW.md lists every key.
"""
import glob  # material patterns such as research/*.md
import json  # kit.json and the other JSON files
import pathlib  # paths
import re  # the number of a drafts file

# Roles a source file can have. They decide how the search page groups and ranks its items.
ROLES = ("scenes", "deep", "terms", "reference")  # scenes: question scripts; deep: resume deep dives; terms: "what is X"; reference: notes

# Settings used when kit.json leaves a key out. Paths are relative to the folder named in the comment.
DEFAULTS = {
    "ui": "ko",  # language of the page and of the messages (ko or en); OFFEROWL_LANG overrides it
    "sources": None,  # None: every *.md file in the interview folder as scenes, then the workspace stories as reference
    "sections": {},  # short tab name per section letter, e.g. {"A": "Intro"}; without one the heading text is used
    "synonyms": [],  # extra synonym groups for the keyword search, added to the built-in ones
    "strip": [],  # regular expressions (JavaScript syntax) for cross-reference notes hidden on the page
    "hidden_labels": ["사용자 원문", "근거"],  # bullets with these bold labels are notes for the writer, not for speaking
    "fallback": None,  # id of the item shown when nothing matches (a "how to answer what you do not know" scene)
    "weak_hint": None,  # {"ko": ..., "en": ...} said under the best card when nothing is close
    "examples": None,  # {"ko": ..., "en": ...} examples in the search box placeholder
    "alts": "alts.json",  # interview folder: other ways each question may be asked
    "eval": "eval_questions.json",  # interview folder: the search eval set
    "profile": "profile/profile.json",  # workspace: the confirmed facts
    "stories": "stories.md",  # workspace: behavioral stories
    "style": None,  # workspace style pack name (style/<name>.json) or a path; None: the built-in interview rules only
    "posting": "posting.md",  # job folder: the posting
    "resume": None,  # job folder: the submitted resume (None: the first submitted/*resume*.txt, .md, then .pdf)
    "portfolio": None,  # job folder: the submitted portfolio (None: the first submitted/*portfolio*.txt, .md, then .pdf)
    "materials": ["posting.md", "research/*.md", "submitted/*.txt", "submitted/*.md"],  # job folder: facts that ground the scenes
    "names": None,  # job folder: a file of "Korean = English" lines, the spellings an English line may use for a name (the panel writes it from the resume)
    "grow_skip": [],  # ids or section letters left out of the length-growth rule (openings and closings)
}


def read_json(path, default=None):
    """A JSON file, or the default when it is missing (or when no path was given: a confined kit refused it)."""
    if path is None:  # a setting the kit switched off, or a path it may not read
        return default
    p = pathlib.Path(path)  # accept str or Path
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default  # missing files are normal (optional parts)


class Job:
    """One job folder with its interview kit and the workspace it belongs to."""

    def __init__(self, path, kit=None, workspace=None, profile=None, confined=False):  # path: a job folder, its interview folder or a bare folder of scenes
        p = pathlib.Path(path).expanduser().resolve()  # the folder the user named
        if (p / "interview").is_dir():  # the job folder itself: jobs/<job>
            self.dir, self.interview = p, p / "interview"  # the job and its scene folder
        elif p.name == "interview":  # the interview folder inside a job
            self.dir, self.interview = p.parent, p  # the job is one level up
        else:  # a bare folder of scene files with no job around it
            self.dir, self.interview = p, p  # the folder is both
        if not self.interview.is_dir():  # nothing to read: stop with the path, not a stack trace
            raise SystemExit(f"no interview folder: {self.interview}")  # exit with the path
        if workspace:  # named on the command line
            self.workspace = pathlib.Path(workspace).expanduser().resolve()  # resolved like the job path
        elif self.dir.parent.name == "jobs":  # the usual layout: <workspace>/jobs/<job>
            self.workspace = self.dir.parent.parent  # two levels up from the job folder
        else:  # no workspace: only the job's own files ground the scenes
            self.workspace = None  # in_workspace then looks next to the job
        kit_path = pathlib.Path(kit).expanduser().resolve() if kit else self.interview / "kit.json"  # a kit file elsewhere is allowed
        if kit and not kit_path.is_file():  # a kit named on purpose must exist (a typo must not silently drop the settings)
            raise SystemExit(f"no kit file: {kit_path}")  # exit with the path that was named
        self.kit_path = kit_path if kit_path.is_file() else None  # where the settings came from, for messages
        raw = read_json(kit_path, {}) or {}  # the settings as written
        self.kit = {**DEFAULTS, **{k: v for k, v in raw.items() if not k.startswith("_")}}  # comments (keys with _) are not settings
        self.profile_override = pathlib.Path(profile).expanduser().resolve() if profile else None  # --profile wins over the kit
        self.name = self.dir.name  # the job's name, for output folders and messages
        # The panel's kits: every path kit.json names must stay inside the workspace (or the job's folder when there is none).
        # A kit.json can come with a restored backup, so it is not trusted to point anywhere else: a source or a material
        # outside would be shown on the panel's own address and read into the agent's prompts. The command line reads the
        # person's own kits, which may name files beside the workspace (the example's profile is ../sample_ko.json).
        self.confined = confined

    # ----- paths -----

    def kept(self, p):
        """p, or None when this kit is confined and p (links followed) leaves the workspace, or the job's folder without one."""
        if p is None or not self.confined:  # nothing to check, or the command line's own kit
            return p
        root = (self.workspace or self.dir).resolve()  # what the kit may read
        q = pathlib.Path(p).resolve()  # where it really is: "..", "~" and links all resolved
        return q if q == root or root in q.parents else None  # inside, or refused

    def in_workspace(self, rel):
        """A path the kit gives relative to the workspace, or None when there is no workspace."""
        if not rel:  # the setting is switched off
            return None
        p = pathlib.Path(rel).expanduser()  # absolute paths are allowed too
        if p.is_absolute():  # used as given (a confined kit: only inside the workspace)
            return self.kept(p)
        base = self.workspace or self.dir  # without a workspace, look next to the job
        return self.kept((base / p).resolve())  # made absolute for comparisons and messages

    def in_job(self, rel):
        """A path the kit gives relative to the job folder."""
        if not rel:  # switched off
            return None
        p = pathlib.Path(rel).expanduser()  # absolute paths are allowed (a confined kit: only inside the workspace)
        return self.kept(p if p.is_absolute() else (self.dir / p).resolve())  # relative paths start at the job folder

    def in_interview(self, rel):
        """A path the kit gives relative to the interview folder."""
        if not rel:  # switched off
            return None
        p = pathlib.Path(rel).expanduser()  # absolute paths are allowed (a confined kit: only inside the workspace)
        return self.kept(p if p.is_absolute() else (self.interview / p).resolve())  # relative paths start at the interview folder

    @property
    def profile_path(self):
        """The profile file (confirmed facts)."""
        return self.profile_override or self.in_workspace(self.kit["profile"])  # --profile first, then the kit's setting

    @property
    def stories_path(self):
        """The shared stories file, if the workspace has one."""
        p = self.in_workspace(self.kit["stories"])  # stories.md by default
        return p if p and p.is_file() else None  # a missing stories file is not an error

    def sources(self):
        """[(path, label, prefix, role)] for every scene file that exists, in the kit's order."""
        spec = self.kit["sources"]  # the kit's list, or None for the default
        if spec is None:  # default: every markdown file in the folder, then the stories
            spec = [{"file": p.name} for p in sorted(self.interview.glob("*.md"))]  # scene files in name order
            if self.stories_path:  # the workspace's stories are notes to search too
                spec.append({"file": "@stories", "role": "reference"})  # the marker is resolved in the loop below
        out = []  # resolved sources
        for s in spec:  # one source per entry
            path = self.stories_path if s["file"] == "@stories" else self.in_interview(s["file"])  # @stories names the workspace file
            if not path or not path.is_file():  # a missing file is skipped, not fatal: a kit may name files a job lacks
                continue
            label = s.get("label") or path.stem  # the label the page shows and groups by
            prefix = s.get("prefix") or path.stem[:1].upper()  # ids for items that have none of their own
            role = s.get("role", "scenes")  # how the page treats the file
            if role not in ROLES:  # a typo would silently change the ranking
                raise SystemExit(f"unknown role {role!r} for {s['file']} (use one of {', '.join(ROLES)})")
            out.append((path, label, prefix, role))  # one resolved source
        out += self.draft_sources()  # the agent's drafts join the search view and practice as soon as they are written
        return out

    def draft_files(self):
        """The drafts files that passed their checks, in the order they were written."""
        folder = self.out_path() / "drafts"  # where draft.py writes
        if not folder.is_dir():  # none yet
            return []
        def number(f):  # drafts-10 after drafts-9
            m = re.search(r"-(\d+)\.md$", f.name)  # its number
            return int(m.group(1)) if m else 0  # a file of another name goes first
        return sorted((f for f in folder.glob("drafts-*.md") if not f.name.endswith(".rejected.md")), key=number)  # a rejected scene stays out

    def draft_sources(self):
        """[(path, label, prefix, role)] for the agent's drafts."""
        label = {"ko": "초안", "en": "Drafts"}.get(self.kit.get("ui"), "Drafts")  # the page groups by this
        return [(f, label, "N", "scenes") for f in self.draft_files()]  # scenes like any other

    def alts_path(self):
        """The alternate phrasings file."""
        return self.in_interview(self.kit["alts"])  # alts.json unless the kit names another file

    def eval_path(self):
        """The search eval set."""
        return self.in_interview(self.kit["eval"])  # eval_questions.json unless the kit names another file

    def submitted(self, kind):
        """The submitted resume or portfolio text (kind: resume or portfolio), or None."""
        named = self.kit.get(kind)  # the kit may name the file
        if named:  # a named file wins over the search below
            p = self.in_job(named)  # relative to the job folder
            return p if p and p.is_file() else None  # a named file that is missing (or out of a confined kit's reach) gives None, never another file
        sub = self.dir / "submitted"  # otherwise the first matching text file in submitted/, then a PDF
        # lower case before capitalized, text before PDF
        for pat in (f"*{kind}*.txt", f"*{kind}*.md", f"*{kind.capitalize()}*.txt", f"*{kind.capitalize()}*.md",
                    f"*{kind}*.pdf", f"*{kind.capitalize()}*.pdf"):  # PDFs last, since they need a PDF reader
            hits = sorted(sub.glob(pat)) if sub.is_dir() else []  # stable order
            if hits:  # the first pattern that matches decides
                return hits[0]  # the first file in name order
        return None  # no such document was submitted

    def material_files(self):
        """Every file that grounds facts in the scenes: the kit's materials, the posting, profile and stories."""
        files = []  # in a stable order, without duplicates
        for pat in self.kit["materials"] + [self.kit["posting"]] + ([self.kit["names"]] if self.kit.get("names") else []):  # job-relative patterns, and the names file
            for f in sorted(glob.glob(str(self.dir / pat))):  # glob keeps plain names working too
                if self.kept(pathlib.Path(f)) is not None:  # a pattern of a confined kit never reaches out of the workspace ("../..")
                    files.append(pathlib.Path(f).resolve())  # absolute, so repeats compare equal
        for f in sorted(self.interview.glob("*.md")):  # every markdown file in the interview folder (notes, research, scenes)
            files.append(f.resolve())  # absolute like the others
        # the facts outside the job's patterns: profile, stories, submitted documents
        for extra in (self.profile_path, self.stories_path, self.submitted("resume"), self.submitted("portfolio")):
            if extra and extra.is_file():  # optional parts
                files.append(extra.resolve())  # absolute like the others
        seen, out = set(), []  # drop repeats, keep the first place
        for f in files:
            if f not in seen and f.is_file():  # first sighting, and still on disk
                seen.add(f)  # remember it
                out.append(f)  # kept in its first place
        return out

    def out_path(self, override=None):
        """Where generated files go, without creating the folder (the server names it at start and writes later)."""
        if override:  # the command line decides
            return pathlib.Path(override).expanduser().resolve()  # resolved like the other user paths
        if self.workspace:  # the workspace's output area
            return self.workspace / "out" / "interview" / self.name  # one folder per job
        return self.interview / "out"  # a bare job folder: next to the scenes

    def out_dir(self, override=None):
        """Where generated files go: --out, else <workspace>/out/interview/<job>, else <job>/interview/out."""
        p = self.out_path(override)  # the same rule as out_path
        p.mkdir(parents=True, exist_ok=True)  # created on first use
        return p


_PDF = {}  # (path, size, change time, layout) -> text: a PDF is converted once per run


def read_text(path, layout=True):
    """Text of a material file; PDFs are read when a PDF reader is here. layout=True keeps the columns side by
    side (the page shape the plan reads); layout=False gives reading order, where a sentence stays whole (the audit)."""
    p = pathlib.Path(path)  # accept str or Path
    if p.suffix.lower() == ".pdf":  # submitted documents are often PDFs
        import pdftools  # the text layer, with poppler or PDFium
        if not pdftools.reader():  # no reader: the caller sees empty text and says so
            return ""
        st = p.stat()  # a changed file is converted again
        key = (str(p.resolve()), st.st_size, st.st_mtime_ns, bool(layout))  # what the conversion depends on
        if key not in _PDF:  # first time in this run
            try:  # a damaged file grounds nothing
                _PDF[key] = pdftools.text(p, layout=layout)  # pages split by form feeds in both modes
            except Exception:  # noqa: BLE001  each reader has its own errors for a damaged file
                _PDF[key] = ""
        return _PDF[key]
    if p.suffix.lower() == ".json":  # the profile: every string value, one per line, so its facts read as text
        try:
            data = json.loads(p.read_text(encoding="utf-8"))  # the profile as data
        except ValueError:  # a broken file grounds nothing
            return ""
        out = []  # collected strings

        def walk(v):  # collect every string and number, depth first
            if isinstance(v, str):  # a fact or a label
                out.append(v)  # kept as is
            elif isinstance(v, dict):  # every value of an object
                for x in v.values():  # keys are field names, not facts
                    walk(x)
            elif isinstance(v, list):  # every item of a list
                for x in v:  # in list order
                    walk(x)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):  # numbers in figures count as facts too
                out.append(str(v))  # as text, so the number check can find it

        walk(data)  # from the top of the profile
        return "\n".join(out)  # one value per line
    return p.read_text(encoding="utf-8", errors="replace")  # plain text and markdown
