"""The evidence for one planned question: the passages of the person's own materials that speak to it. No model.

Every source is cut into short passages, and the passages are ranked by the rare words they share with the question
(BM25), so a word few passages use ("Slurm") counts for much more than a word many use ("job"). Each source has its own
share of the room, so a long project body cannot crowd out the one resume line that answers the question.
"""
import collections  # word counts
import glob  # research files
import math  # the rarity weight
import pathlib  # file names
import re  # passages

from interview import plan as planmod  # the map's readers of the posting, the resume and the portfolio
from interview import text as T  # words and synonyms
from interview.job import read_json, read_text  # files

K1, B = 1.2, 0.5  # BM25's usual saturation, and a mild length penalty: a long passage is not worth less just for being long
PIECE = 700  # characters in a passage: enough for a paragraph, small enough that one question takes only what it needs
ROOM = 18000  # characters of evidence for one scene; a kit for a small local model can lower it (kit.json "evidence_chars")
# (most passages, most characters) from each source. The person's own final words come first in the prompt and have a
# share of their own, so that they always arrive.
SHARE = {"resume": (8, 1800), "confirmed": (5, 3000), "project": (10, 7000), "context": (2, 800), "skills": (3, 400),
         "story": (3, 1500), "portfolio": (2, 1500), "posting": (3, 700), "research": (2, 1200)}
# What a company question needs more of: what is known about the company
COMPANY_SHARE = {"research": (6, 4000)}
FALLBACK = 4  # passages of the person's latest work, when no project shares a word with the question
JOB_LINES = 8  # lines of the posting shown with a question that names no topic, so the answer can lean toward this job
# Kinds whose questions name no topic of their own, so the person's own choice of their strongest work has to be in front of the model
OVERVIEW_KINDS = ("behavioral", "company", "opening")
# Template kinds: the question is a fixed sentence around the line, and the sentence's words would rank passages by chance
LINE_KINDS = ("posting", "resume", "portfolio", "term")


def clean(text):
    """A material's text without writer's comments and speech marks, with its spacing squeezed."""
    text = re.sub(r"<!--.*?-->", " ", str(text or ""), flags=re.S)  # notes to the writer, which no one says aloud
    text = text.replace("==", "")  # the highlighter marks of a resume
    return re.sub(r"[ \t]{2,}", " ", text).strip()  # two-column PDF text keeps wide gaps


def pieces(text, size=PIECE):
    """A text as passages of at most about size characters, cut at paragraphs and then at sentences."""
    out, cur = [], ""  # finished passages, the one being filled
    for para in re.split(r"\n\s*\n", clean(text)):  # paragraphs first, since a paragraph is one thought
        para = para.strip()  # without its edges
        parts = [para] if len(para) <= size else re.split(r"(?<=[.!?다])\s+|\n", para)  # a long paragraph falls apart at its sentences or lines
        for part in parts:  # each piece of it
            if cur and len(cur) + len(part) > size:  # the passage is full
                out.append(cur)  # finished
                cur = ""  # the next one starts
            cur = (cur + "\n" + part).strip() if cur else part  # short paragraphs share a passage
    if cur:  # the last one
        out.append(cur)  # finished too
    return out


def named(value, lang="en"):
    """A value that may differ by language: the wanted language, else the other, else the value as text."""
    if isinstance(value, dict):  # {"ko": ..., "en": ...}
        return value.get(lang) or value.get("ko") or value.get("en") or ""  # either language beats nothing
    return value or ""  # the same text in every language


def role_head(role):
    """One line that says where and when, from either form of a role: its own fields or its career block."""
    career = role.get("career") if isinstance(role.get("career"), dict) else {}  # the ledger form keeps these in a block
    english = career.get("en") if isinstance(career.get("en"), dict) else {}  # the English names, when written
    org = role.get("org") or english.get("name") or role.get("heading") or ""  # the company
    title = role.get("title") or career.get("title") or ""  # the job title
    start = role.get("start") or career.get("start") or ""  # from
    end = role.get("end") or career.get("end") or ""  # to; empty while the job goes on
    period = f"{start} - {end}".strip(" -") or role.get("period") or ""  # a short career has only its period line
    return ", ".join(x for x in (str(org), str(title)) if x) + (f" ({period})" if period else "")  # "Alpha Pay, Backend Engineer (2022.03 - 2024.06)"


class Evidence:  # one per drafting run
    """Every passage of a job's materials, ready to be ranked against each question."""

    def __init__(self, job, stories):  # stories: the kit's reference items, already read
        self.job = job  # for the English names and the kit's settings
        self.syn = T.synonyms(job.kit.get("synonyms") or [])  # the built-in synonym groups and the job's own
        self.prof = (read_json(job.profile_path, {}) or {}) if job.profile_path else {}  # the confirmed facts
        self.scale = int(job.kit.get("evidence_chars") or ROOM) / ROOM  # the share of each source follows the room
        self.passages = []  # every passage: {source, head, group, order, text, counts, size}
        self.page_text = {}  # portfolio page number -> its text, for a question about that page
        self._read_profile()  # projects, role notes, confirmed facts, skills
        self._read_documents(stories)  # stories, resume, portfolio, posting, research
        self._index()  # the rarity of each word

    def add(self, source, head, text, group=""):  # the one way a passage enters
        """One passage. A group's passages (one project's paragraphs) are shown under one heading."""
        words = T.words(text)  # its content words, stemmed
        if words:  # a passage of only marks says nothing
            self.passages.append({"source": source, "head": head, "text": text, "group": group or head, "order": len(self.passages),  # its reading order
                                  "counts": collections.Counter(words), "size": len(words)})  # for the ranking

    def _read_profile(self):
        """The profile: each project's and each note's paragraphs, the confirmed facts, the skill groups."""
        for role in self.prof.get("roles") or []:  # every company
            where = role_head(role)  # the line that says where and when
            for note in role.get("context") or []:  # what the company and the work were
                for part in pieces(note.get("body_md", "")):  # paragraph by paragraph
                    self.add("context", f"[profile {role.get('key', '')}] {where}: {note.get('title', '')}", part)  # under its title
            for proj in role.get("projects") or []:  # every project
                body = "\n\n".join(str(x) for x in (proj.get("summary"), "\n".join(map(str, proj.get("points") or [])), proj.get("body_md")) if x)  # its words
                head = f"[profile {proj.get('id', '')}] {where}: {proj.get('title', '')}" + (f" ({proj['period']})" if proj.get("period") else "")  # the project's heading
                for part in pieces(body) or [str(proj.get("title", ""))]:  # paragraph by paragraph; a project may be only a title
                    self.add("project", head, proj.get("title", "") + "\n" + part if part != proj.get("title") else part, group=head)  # the title's words count for each paragraph
        for fact in self.prof.get("confirmed") or []:  # what the person confirmed themselves
            for part in pieces(fact.get("body_md", "")):  # paragraph by paragraph
                self.add("confirmed", f"[confirmed] {fact.get('title', '')}", part)  # under its title
        for group in self.prof.get("skills") or []:  # the skill groups: a listed skill is experience the person claims
            if isinstance(group, dict) and group.get("items"):  # the group form
                line = f"{group.get('category', '')}: " + ", ".join(map(str, group["items"]))  # one line per group
                self.add("skills", "[skills]", line, group=line)  # a group stands alone

    def _read_documents(self, stories):
        """What was sent and what was found: the stories, the resume, the portfolio, the posting, the research."""
        for it in stories:  # the person's own stories
            for part in pieces(it.get("text", "")):  # paragraph by paragraph
                self.add("story", f"[story {it['id']}] {it.get('tko') or it.get('ten') or ''}", part)  # under its title
        rp, pp = self.job.submitted("resume"), self.job.submitted("portfolio")  # the documents that were sent
        for _, line in planmod.resume_lines(read_text(rp)) if rp else []:  # one line at a time, since each is a claim of its own
            self.add("resume", "[resume]", clean(line), group=line)  # stands alone
        for page, title, body in planmod.portfolio_pages(read_text(pp)) if pp else []:  # one page at a time
            self.page_text[page] = clean(body)  # asked for whole when the question is about this page
            for part in pieces(body):  # and searchable by paragraph for the others
                self.add("portfolio", f"[portfolio page {page}] {title}", part)  # under its page
        posting = self.job.in_job(self.job.kit["posting"])  # the posting
        for _, _, line in planmod.posting_lines(read_text(posting)) if posting and posting.is_file() else []:  # its duties and requirements
            self.add("posting", "[posting]", clean(line), group=line)  # stands alone
        for pat in self.job.kit.get("research") or ["research/*.md"]:  # the company research files
            for f in sorted(glob.glob(str(self.job.dir / pat))):  # sorted, so a run is the same as the last
                for part in pieces(pathlib.Path(f).read_text(encoding="utf-8")):  # paragraph by paragraph
                    self.add("research", f"[research {pathlib.Path(f).name}]", part)  # under its file

    def _index(self):
        """How rare each word is across every passage, and the average passage length."""
        n = max(1, len(self.passages))  # how many passages the counts cover
        df = collections.Counter()  # word -> passages that hold it
        for p in self.passages:  # each passage counts once per word
            df.update(p["counts"].keys())  # its distinct words
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}  # rarer words weigh more
        self.avg = sum(p["size"] for p in self.passages) / n  # BM25's length norm

    def score(self, passage, query):
        """BM25 of a passage for the question's words. A synonym of a question word counts as that word."""
        total = 0.0  # the sum over the question's words
        norm = K1 * (1 - B + B * passage["size"] / max(self.avg, 1))  # a longer passage needs more hits for the same weight
        for w in query:  # each word of the question counts once
            best = 0.0  # the word itself or its best synonym
            for c in {w} | self.syn.get(w, set()):  # the word and the words that mean the same
                tf = passage["counts"].get(c, 0)  # how often this passage says it
                if tf:  # it does
                    best = max(best, self.idf.get(c, 0.0) * tf * (K1 + 1) / (tf + norm))  # BM25's weight for this word
            total += best  # one word's weight at most
        return total

    def query(self, entry):
        """The words a question is about: the line itself, and for a question with its own sentence that sentence in both languages."""
        ask = entry.get("ask") or {}  # the questions in English and Korean
        parts = [entry.get("text", "")]  # the line or the question
        if entry.get("kind") not in LINE_KINDS:  # a real sentence, not a template around a line
            parts += list(ask.get("en") or []) + list(ask.get("ko") or [])  # the Korean sentence reaches the Korean materials
        return set(T.words(" ".join(parts)))  # each word once

    def top(self, source, query, kind):
        """The passages of one source for a question, best first, within the source's share of the room."""
        limit, room = {**SHARE, **(COMPANY_SHARE if kind == "company" else {})}[source]  # how many and how much
        room = int(room * self.scale)  # a kit with less room gives each source less
        ranked = sorted((p for p in self.passages if p["source"] == source), key=lambda p: (-round(self.score(p, query), 9), p["order"]))  # the same order on every run
        out, used = [], 0  # chosen passages, characters so far
        for p in ranked[:limit]:  # at most this many
            if self.score(p, query) <= 0:  # the rest share nothing with the question
                break
            if used + len(p["text"]) > room and out:  # no room left, and at least one was kept
                break
            out.append(p)  # chosen
            used += len(p["text"])  # counted
        return out

    def block(self, chosen):
        """Chosen passages as text: one heading per group, its passages in reading order."""
        groups = {}  # group -> its passages, in the order the groups were ranked
        for p in chosen:  # best first
            groups.setdefault(p["group"], []).append(p)  # a project's paragraphs stay together
        lines = []  # the text
        for parts in groups.values():  # each group
            parts = sorted(parts, key=lambda p: p["order"])  # a project reads from its start
            if parts[0]["head"] in ("[resume]", "[posting]", "[skills]"):  # one line each, no heading of its own
                lines += [f"{p['head']} {p['text']}" for p in parts]  # labeled line by line
            else:  # a heading, then its paragraphs
                lines.append(parts[0]["head"])  # where it comes from
                lines += [re.sub(r"\n+", " ", p["text"]) for p in parts]  # each paragraph on one line
        return lines

    def overview(self):
        """The person's own summary and their chosen representative work: what to reach for when a question names no topic."""
        summary = self.prof.get("summary") if isinstance(self.prof.get("summary"), dict) else {}  # the ledger form
        lines = []  # the text
        intro = clean(named(summary.get("intro")))  # the summary paragraph, in English when written
        if intro:  # when the profile has one
            lines.append("[profile summary] " + intro)  # labeled
        for card in named(summary.get("highlights")) or []:  # the representative projects the person picked
            rows = "; ".join(f"{r[0]}: " + " ".join(map(str, r[1:])) for r in card.get("rows") or [] if isinstance(r, (list, tuple)) and len(r) > 1)  # problem, what was done, result
            lines.append(clean(f"[representative work] {card.get('title', '')} ({card.get('where', '')}). {rows}"))  # one line per card
        return lines

    def names(self):
        """The English spellings of names, when the kit has them: the same line for every scene."""
        path = self.job.in_job(self.job.kit["names"]) if self.job.kit.get("names") else None  # the kit's file
        if not path or not path.is_file():  # no spellings known
            return []
        pairs = [ln.strip("- ").strip() for ln in path.read_text(encoding="utf-8").splitlines() if " = " in ln]  # "Korean = English"
        return ["[English names] " + "; ".join(pairs[:40])] if pairs else []  # a short line

    def around(self, said):
        """The evidence around what a drafted scene says: the same sources, ranked by the scene's own words. A scene can say more
        than its question asked, and what qualifies a claim ("proposed", "a maintenance window") may sit in another passage."""
        query = set(T.words(said))  # the words the scene uses
        lines = []  # the text
        for source in ("resume", "confirmed", "project", "context", "skills", "story", "portfolio"):  # the person's own sources
            lines += self.block(self.top(source, query, ""))  # each within its share
        return "\n".join(lines)  # one block per line

    def collect(self, entry):
        """The evidence for one entry of the question map, as text blocks labeled with their sources."""
        kind = entry.get("kind", "")  # what sort of question
        query = self.query(entry)  # its words
        lines = [f"[question source] {entry.get('source', '')}: {entry.get('text', '')}"]  # the planned line itself
        page = re.search(r":page (\d+)$", str(entry.get("source", "")))  # a question about one portfolio page
        if page and self.page_text.get(int(page.group(1))):  # the page as it was sent
            lines.append(f"[this portfolio page] {re.sub(chr(10) + '+', ' ', self.page_text[int(page.group(1))])}")  # whole, since that page is the subject
        matched = kind in OVERVIEW_KINDS  # no topic of its own, so the person's strongest work has to be in view
        if kind != "opening":  # small talk needs no projects
            for source in ("resume", "confirmed", "project", "context", "skills", "story", "portfolio", "posting", "research"):  # the person's final words first
                chosen = self.top(source, query, kind)  # within its share
                if source == "project" and not chosen:  # a posting line in one language and a profile in another may share no word
                    chosen = [p for p in self.passages if p["source"] == "project"][:FALLBACK]  # the person's latest work, since a scene needs something real to stand on
                    matched = True  # and the person's own choice of their strongest work too
                lines += self.block(chosen)  # the source's lines
        if matched:  # the summary and the representative work, and what this job asks for, which the question itself does not say
            lines += self.overview() + [f"[this job] {p['text']}" for p in [q for q in self.passages if q["source"] == "posting"][:JOB_LINES]]  # one line each
        return "\n".join(lines + self.names())  # one block per line, the spellings last
