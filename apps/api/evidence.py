"""The resume as the canvas draws it, with the evidence of every sentence (core/schema/documents/resume.schema.json).

The blocks follow the order in which src/resume_form.js prints the resume: headline, introduction, overview (cards and
key projects), career summary, education, core competencies, skills, experience, the other lists, about me and the
motivation. Each piece of text is a sentence with an id that is its place in the profile ("roles.0.projects.1.summary.s0").

A sentence's evidence comes from the evidence map (profile/evidence.json, written by facts.build_with_evidence): the
facts that made its item, each with the quote it rests on and the name of the file it was read from. Its state:
  ok           the text is the fact's own text, or a drafted sentence as the checks passed it;
  typed        the person's own words ("Your details");
  edited       changed by the person and still inside its evidence (src/factcheck.py finds nothing new);
  unsupported  it holds a number, a tool, a number word or a company the evidence does not, or it has no evidence.
An unsupported sentence is marked on the canvas and stops the export and the lock until it is fixed.

Editing a sentence writes the fact's field through the same edit files as the fact cards (one undo step), locking
keeps its words through later drafts, and regenerating asks the agent for new words from the evidence alone.

With a draft (apps/api/drafts.py), a sentence the draft wrote has its evidence from the ids the draft cited, and an edit to
it goes back into the draft.
"""
from __future__ import annotations

import json  # the themes file
import math  # JavaScript's rounding, for the list tables' column widths
import re  # sentences and marks
import sys  # the engine on the import path
from datetime import date  # tenure up to today
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parents[2]  # the repository (or the app's bundle)
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules

import factcheck  # noqa: E402  the rules that stop unsupported numbers, tools and names

from . import drafts  # noqa: E402  a job's drafted resume
from .facts import text_of  # noqa: E402  plain text

THEMES = json.loads((ROOT / "src" / "themes.json").read_text(encoding="utf-8"))  # the resume's colour packs (layout.js reads the same file)
# The section names of the printed resume, per document language (src/resume_form.js LABEL, the parts the canvas shows).
WORDS = {
    "ko": {"overview": "개요", "highlights": "대표 프로젝트", "career": "경력요약", "edu": "학력사항", "comp": "핵심역량",
           "skills": "보유기술", "detail": "상세경력사항", "about": "자기소개", "motivation": "지원 동기", "period": "기간",
           "org": "회사(소재)", "dept": "부서 / 직급", "tenure": "재직", "school": "학교", "major": "전공", "degree": "학위와 비고",
           "cat": "분류", "tech": "기술", "now": "재직 중", "phone": "연락처", "email": "이메일",
           "role": "직무(포지션)", "info": "인적사항", "location": "거주지",
           "now_edu": "재학 중", "total": "총경력",
           "resume": "이 력 서", "name": "성명", "service": "병역사항", "kind": "구분"},  # the table form's title, its name row and its service table
    "en": {"overview": "Overview", "highlights": "Selected Projects", "career": "Career Summary", "edu": "Education",
           "comp": "Core Competencies", "skills": "Technical Skills", "detail": "Professional Experience", "about": "About Me",
           "motivation": "Motivation", "period": "Period", "org": "Company (Location)", "dept": "Department / Title",
           "tenure": "Tenure", "school": "School", "major": "Major", "degree": "Degree", "cat": "Category", "tech": "Skills",
           "now": "Present", "phone": "Phone", "email": "Email",
           "role": "Role", "info": "Personal", "location": "Location", "now_edu": "Present", "total": "total",
           "resume": "Resume", "name": "Name", "service": "Military Service", "kind": "Type"},
}
# The faint English label at the right of each section, as the printed resume has it in both languages.
EN_LABEL = {"overview": "OVERVIEW", "career": "CAREER SUMMARY", "edu": "EDUCATION", "comp": "CORE COMPETENCIES",
            "skills": "TECHNICAL SKILLS", "detail": "PROFESSIONAL EXPERIENCE", "about": "ABOUT ME", "motivation": "MOTIVATION",
            "service": "MILITARY SERVICE"}
# What src/factcheck.py says (in Korean), as codes the page words in either language.
ISSUE_CODES = (("근거에 없는 숫자 낱말", "number_word"), ("근거에 없는 숫자", "number"), ("근거에 없는 영문 낱말", "latin"),
               ("근거에 없는 회사·기관 이름", "org"))  # the longer prefix first: "숫자 낱말" starts with "숫자"


def sentences(text: str) -> list[str]:
    """A paragraph cut into sentences: after a full stop, question or exclamation mark followed by a space (Korean
    and English alike), never inside a ==highlight==. A text without such a break is one sentence."""
    text = str(text or "").strip()  # plain text
    if not text:  # nothing
        return []  # no sentences
    out, buf, inside = [], "", False  # results, the sentence being read, inside ==...==
    i = 0  # position
    while i < len(text):  # one character at a time (marks are two characters)
        if text.startswith("==", i):  # a highlight mark opens or closes
            inside = not inside  # the state flips
            buf += "=="  # kept in the text
            i += 2  # past the mark
            continue  # next character
        ch = text[i]  # this character
        buf += ch  # kept
        if ch in ".!?" and not inside and (i + 1 == len(text) or text[i + 1] == " "):  # a sentence end before a space or the end
            nxt = text[i + 1:i + 3]  # what follows
            if not re.match(r"\s?\d", nxt):  # "3.5" or "v1. 2" stay together
                out.append(buf.strip())  # one sentence
                buf = ""  # the next one starts
        i += 1  # on
    if buf.strip():  # the rest
        out.append(buf.strip())  # the last sentence
    return [s for s in out if s]  # no empty ones


def role_fields(r: dict, lang: str) -> dict:
    """A role's shown fields: its plain ones, with a ledger's career block filling what is missing, as src/profile_loader.js does."""
    c = r.get("career") if isinstance(r.get("career"), dict) else {}  # a ledger's career block
    half = c.get(lang) if isinstance(c.get(lang), dict) else {}  # its language half
    full = c["full"].get(lang) if isinstance(c.get("full"), dict) and isinstance(c["full"].get(lang), dict) else {}  # a longer job title some roles carry
    own = lambda k: text_of(pick_lang(r.get(k), lang))  # noqa: E731  a field the role writes itself, once or per language (the loader's pickDeep)
    return {"org": text_of(r.get("org")) or text_of(half.get("name")) or text_of(r.get("heading")),  # the shown name
            "title": text_of(r.get("title")) or text_of(half.get("role")) or text_of(c.get("title")),  # the role in tables and bands
            # the long title the English one-column form prints (src/profile_loader.js titleLong): the role's own, a career block's full one, then the short ones
            "title_long": text_of(pick_lang(r.get("titleLong"), lang)) or text_of(full.get("role")) or text_of(c.get("title")) or text_of(r.get("title")) or text_of(half.get("role")),
            "dept": text_of(r.get("dept")) or text_of(half.get("dept")), "place": text_of(r.get("place")) or text_of(half.get("place")),  # department and place
            "note": own("note"),  # a grey second line under the name in the career table, after the place
            "sub": own("sub"), "desc": own("desc"),  # the band's underlined line and its grey line about the company
            "badge": own("badge") if "badge" in r else text_of(half.get("badge")),  # a small mark beside the name; an empty one written on the role hides the career block's
            "start": r.get("start") or c.get("start") or "", "end": r.get("end") if r.get("end") not in ("", None) else c.get("end", r.get("end"))}  # None means still there


def school_fields(e: dict, lang: str) -> dict:
    """A school's shown fields: its plain ones, or a ledger's language half, whose title is 'Degree  School' and whose sub is the major."""
    half = e.get(lang) if isinstance(e.get(lang), dict) else {}  # the ledger's language half
    parts = re.split(r"\s{2,}", text_of(half.get("title")), maxsplit=1)  # 'Degree  School'
    return {"school": text_of(pick_lang(e.get("school"), lang)) or (parts[1] if len(parts) > 1 else ""), "major": text_of(pick_lang(e.get("major"), lang)) or text_of(half.get("sub")),  # school and major
            "degree": text_of(pick_lang(e.get("degree"), lang)) or parts[0]}  # the degree


def pick_lang(v, lang: str):
    """A field that may be written per language: this language's text, else Korean, else English, else as it is."""
    if isinstance(v, dict) and ("ko" in v or "en" in v):  # per language
        return v.get(lang) or v.get("ko") or v.get("en")  # this language first
    return v  # a plain value


def join_sentences(parts: list[str]) -> str:
    """Sentences back into one paragraph, one space between them."""
    return " ".join(p.strip() for p in parts if p.strip())  # the paragraph


def issue_prefixes() -> list[tuple[str, str]]:
    """(message start, code) pairs for src/factcheck.py's lines in every language it writes, longest first."""
    out = list(ISSUE_CODES)  # the Korean messages it has always written
    for table in (getattr(factcheck, "MSG", None) or {}).values():  # its message tables, when it has them
        for code in ("number_word", "number", "latin", "org"):  # the kinds the page words
            head = str(table.get(code, "")).split("{")[0].rstrip(": ").strip()  # the text before the found words
            if head:  # a real start
                out.append((head, code))  # in that language
    return sorted(set(out), key=lambda x: -len(x[0]))  # "counted word" before "number", in either language


def issue_codes(found: list) -> list[dict]:
    """src/factcheck.py's findings as {code, words} for the page ("근거에 없는 숫자: 40%" -> number, 40%). Claim
    findings (dicts) keep their words: what the sentence says and what the evidence says."""
    out, prefixes = [], issue_prefixes()  # one per finding; the message starts
    for item in found:  # each problem
        if isinstance(item, dict):  # a claim stronger than its evidence
            out.append({"code": "claim", "words": str(item.get("word", "")), "said": str(item.get("said", ""))})  # both words
            continue  # next problem
        head, _, words = str(item).partition(":")  # the kind and the words
        code = next((c for prefix, c in prefixes if head.strip().startswith(prefix)), "other")  # its code
        out.append({"code": code, "words": words.strip()})  # the words stay as found (they are the person's own)
    return out  # for the sentence's issues


def ym_number(v) -> int | None:
    """A year and month as one number to sort by (2022.03 -> 202203), or None when unreadable (src/profile_loader.js ym)."""
    m = re.match(r"(\d{4})(?:[./-](\d{1,2}))?", str(v or ""))  # 2022.03, 2022-3, 2022
    return int(m.group(1)) * 100 + int(m.group(2) or 1) if m else None


def months_between(start: str, end) -> int | None:
    """Whole months from a start to an end ("2022.03" to "2024.06", None meaning today), or None when unreadable."""
    def ym(v):  # a year and month from the usual spellings
        m = re.match(r"(\d{4})(?:[./-](\d{1,2}))?", str(v or ""))  # 2022.03, 2022-3, 2022
        return (int(m.group(1)), int(m.group(2) or 1)) if m else None  # month 1 when only the year is known
    a = ym(start)  # the start
    b = ym(end) if end not in (None, "") else ((date.today().year, date.today().month) if end is None else None)  # None: still there
    if not a or not b:  # an unknown end or start
        return None  # no tenure shown
    return max(0, (b[0] - a[0]) * 12 + (b[1] - a[1]) + 1)  # both months counted, as the printed table does


def tenure_text(n: int | None, lang: str) -> str:
    """Months as the printed career table writes them (src/profile_loader.js tenureText): "4년 9개월", "1년", "11개월",
    "2 yrs 3 mos", "1 yr". A part that is zero is left out, as the PDF leaves it out ("1년 0개월" never prints)."""
    if not n:  # unknown, or no month at all: an empty cell, as the loader writes it
        return ""
    y, m = divmod(n, 12)  # whole years and the months left over
    if lang == "en":  # English abbreviations, singular for one
        return " ".join(x for x in (f"{y} {'yr' if y == 1 else 'yrs'}" if y else "", f"{m} {'mo' if m == 1 else 'mos'}" if m else "") if x)
    return " ".join(x for x in (f"{y}년" if y else "", f"{m}개월" if m else "") if x)  # Korean years and months


def norm_side(s, prev_year: str | None = None, first_had_day: bool = False) -> tuple[str, str | None, bool]:
    """One side of a period as the printed resume writes it (src/profile_loader.js normSide): '26.04' -> '2026.04',
    '2023.03.15' -> '2023.03', a bare year as it is, anything else as written. Returns (text, its year, whether it had a day)."""
    t = str(s or "").strip()  # the side as text
    m = re.match(r"^((?:19|20)\d{2})[.\-/](\d{1,2})(?:[.\-/]\d{1,2})?$", t)  # the four-digit year form
    if m:  # year and month, a day dropped
        return f"{m.group(1)}.{int(m.group(2)):02d}", m.group(1), bool(re.search(r"[.\-/]\d{1,2}[.\-/]\d{1,2}$", t))
    m = re.match(r"^(\d{2})[.\-/](\d{1,2})([.\-/]\d{1,2})?$", t)  # the two-part or three-part short form
    if m and first_had_day and prev_year and not m.group(3):  # MM.DD after a first side that had a day: its year
        return f"{prev_year}.{int(m.group(1)):02d}", prev_year, True
    if m:  # YY.MM(.DD)
        return f"20{m.group(1)}.{int(m.group(2)):02d}", f"20{m.group(1)}", bool(m.group(3))
    m = re.match(r"^((?:19|20)\d{2})$", t)  # a bare year
    if m:
        return m.group(1), m.group(1), False
    return t, prev_year, False  # anything else is shown as written


def norm_period(p, lang: str) -> str:
    """A written period ('26.04 ~ 26.06', '2023.08') with its sides normalized and the edition's range mark, as the printed
    resume writes a project's dates (src/profile_loader.js normPeriod)."""
    if not p:  # no period
        return ""
    p = str(p)  # as text
    if "," in p:  # several ranges are already written out: kept as given
        return p
    parts = re.split(r"\s*[~–—]\s*|\s+-\s+", p)  # split on the range mark
    a = norm_side(parts[0])  # the first side
    out = [a[0]]  # the sides as printed
    if len(parts) > 1:  # a second side may take the first side's year
        out.append(norm_side(parts[1], a[1], a[2])[0])
    if len(out) == 2 and out[0] == out[1]:  # '2026.05 ~ 2026.05' reads as one month
        out.pop()
    return (" - " if lang == "en" else " ~ ").join(out)  # the edition's range mark


def period_of(start, end, lang: str, now_word: str) -> str:
    """A role's or a school's dates as one line (src/profile_loader.js periodOf): end None means ongoing ('2022.03 ~ 재직 중'),
    an empty end is unknown and reads '2023.03 ~'; the English edition writes ' - '."""
    if not start:  # nothing known
        return ""
    mark = " - " if lang == "en" else " ~ "  # the edition's range mark
    return (norm_side(start)[0] + mark + (now_word if end is None else norm_side(end)[0] if end else "")).rstrip()  # an open end keeps its mark


CONTENT_W = 11906 - 750 - 750  # the printed page's text width in twips (src/layout.js CONTENT_W)


def auto_widths(head: list, rows: list, fixed=None) -> list[int]:
    """A list table's column widths in twips, as src/resume_form.js autoWidths gives them: the profile's own (fractions of the
    width or twips, the last column taking the rounding), else wider columns for longer text, none under 900 twips."""
    jsround = lambda x: int(math.floor(x + 0.5))  # noqa: E731  JavaScript's Math.round, not Python's even rounding
    if fixed:  # the profile gives them
        tw = [jsround(f * CONTENT_W) if f <= 1 else f for f in fixed]
        tw[-1] = CONTENT_W - sum(tw[:-1])  # the last column takes the rounding
        return tw
    span = lambda s: sum(2 if "ㄱ" <= ch <= "힣" else 1 for ch in str(s or ""))  # noqa: E731  Hangul is about two Latin letters wide
    need = [max([span(h)] + [min(60, span(r[i] if i < len(r) else "")) for r in rows]) for i, h in enumerate(head)]  # the longest cell, capped
    total = sum(need) or 1
    w = [max(900, jsround(CONTENT_W * x / total)) for x in need]  # proportional, floored
    if w:  # the floor may push the sum over the width: the widest column gives it back
        w[w.index(max(w))] -= sum(w) - CONTENT_W
    return w


def clean_name(name: str, name_en: str = "") -> tuple[str, str]:
    """A person's name as the printed resume writes it (src/profile_loader.js cleanName): a Latin name in brackets becomes the
    English name when none is given ('홍길동 (Gildong Hong)'), and Hangul syllables spaced apart are joined ('홍 길 동')."""
    n, en = str(name or "").strip(), name_en or ""  # as written
    m = re.match(r"^(.*?)\s*\(([A-Za-z][A-Za-z .,'-]+)\)$", n)  # 'Name (Latin Name)'
    if m:  # the Latin name split off
        n, en = m.group(1).strip(), en or m.group(2).strip()
    if re.fullmatch(r"[가-힣](\s[가-힣])+", n):  # '홍 길 동' -> '홍길동'
        n = n.replace(" ", "")
    return n, en


def period_text(start, end, lang: str) -> str:
    """A role's dates as one line ("2022.03 ~ 재직 중", "2019.07 ~ 2022.02"), as the printed resume writes them."""
    return period_of(start, end, lang, WORDS[lang]["now"])  # a role's ongoing word


class Resume:
    """The canvas model of one profile, built once per request: blocks, sentences and their evidence."""

    def __init__(self, prof: dict, lang: str, theme: str, *, evmap: dict, cands: list, base: dict | None, edits: dict,
                 locks: dict, details: dict, plan: dict | None = None, job: str | None = None, translated: bool = False,
                 draft: dict | None = None, live: dict | None = None):
        self.prof, self.lang, self.theme = prof, lang, theme if theme in THEMES else "navy"  # what to draw, in which colours
        self.evmap, self.base, self.edits, self.locks, self.details = evmap, base or {}, edits, locks, details  # the evidence and the edits
        self.by_cid = {c["cid"]: c for c in cands}  # facts by id
        self.plan, self.job, self.translated = plan or {}, job, translated  # the job's analysis, its id, an English profile made by the agent
        self.sent: dict[str, dict] = {}  # sentence id -> its record
        self.blocks: list[dict] = []  # the blocks in print order
        self.base_name = next((text_of((c.get("source") or {}).get("name")) for c in cands if c.get("origin") == "profile"), "")  # the imported file's name
        self.draft, self.live = draft, live  # the draft in force; the facts' profile as it is now, when the draft is older than the facts
        self.links = drafts.links_of(draft, lang)  # the draft's sentences by their words
        self.link_of: dict[str, dict] = {}  # sentence id -> its link in the draft
        self._units = self._live_units = self._ctx = self._files = None  # worked out when first needed
        self.logo_ids: dict[int, str] = {}  # a role's place in the profile -> the logo tile name overview_figures.py draws for it

    def at(self, place: str):
        """The object at a place of the profile being drawn ("summary.highlights.0"), or None."""
        item = self.prof  # walk down the profile
        for k in place.split("."):  # one level per part
            try:
                item = item[int(k)] if k.isdigit() else item[k]  # list index or key
            except (KeyError, IndexError, TypeError, ValueError):  # not there
                return None  # nothing at that place
        return item  # the item itself

    def in_base(self, place: str) -> str:
        """The text at a place of the imported profile ("" when the base has nothing there)."""
        item = self.base  # walk down the base
        for k in place.split("."):  # one level per part
            try:
                item = item[int(k)] if k.isdigit() else item[k]  # list index or key
            except (KeyError, IndexError, TypeError, ValueError):  # not there
                return ""  # nothing at that place
        return text_of(item) if not isinstance(item, dict) else " ".join(text_of(v) for v in item.values() if isinstance(v, (str, list)))  # its words

    # ---------------------------------------------------------------- evidence

    def facts_at(self, place: str) -> list:
        """The facts behind an item. The English edition looks first at the item's English place, where a list the person
        wrote apart in English keeps its own facts (apps/api/facts.py own_english)."""
        if self.lang == "en" and self.evmap.get(place + ".en"):  # the English row's own facts
            return self.evmap[place + ".en"]
        return self.evmap.get(place) or []  # the item's facts, shared by both editions

    def place_of(self, sid: str) -> str:
        """The item a sentence belongs to: the id without its field and sentence number."""
        place = re.sub(r"\.s\d+$", "", sid)  # "roles.0.projects.1.summary.s0" -> "roles.0.projects.1.summary"
        place = re.sub(r"\.(summary|rows\.\d+|text|p\d+|body\.\d+)$", "", place)  # the field names a fact covers whole
        return place  # "roles.0.projects.1", "summary.highlights.0", "summary.cards.2"

    def draft_units(self) -> dict:
        """The evidence units the draft cites: the ledger's own text, so the ids keep their meaning."""
        if self._units is None:  # first use
            import cover as C  # the units
            import write_resume as W  # the ledger's text under a draft
            self._units = C.units_of(W.ledger_view(self.draft), self.lang)  # by id
        return self._units  # the same for every sentence

    def file_of(self, uid: str) -> str:
        """The file a draft's evidence unit came from: its project's first fact with a file."""
        if self._files is None:  # first use
            self._files = {}  # project id -> file name
            for ri, r in enumerate(self.prof.get("roles") or []):  # each role
                for pi, p in enumerate(r.get("projects") or [] if isinstance(r, dict) else []):  # each project
                    for c in self.facts_at(f"roles.{ri}.projects.{pi}"):  # its facts
                        f = self.by_cid.get(c) or {}  # the fact
                        name = text_of((f.get("source") or {}).get("name")) if f.get("origin") != "typed" else ""  # a file name, never a path
                        if name and isinstance(p, dict):  # the first one speaks for the project
                            self._files.setdefault(p.get("id"), name)  # kept
        pid = (self.draft_units()["index"].get(uid) or {}).get("pid") or uid  # a whole project's id names itself
        return self._files.get(pid, "")  # "" for a company line's own unit

    def draft_evidence(self, link: dict) -> list[dict]:
        """The evidence of a drafted sentence: one entry per cited unit, quote and file name."""
        import cover as C  # the units' text
        U, out = self.draft_units(), []  # the units; the entries
        for uid in link.get("ev") or []:  # each id it cites
            if C.known_id(U, uid):  # one the ledger has
                out.append({"unit": uid, "quote": C.unit_text(U, uid).split("\n", 1)[-1][:400], "where": (U["index"].get(uid) or {}).get("head", "") or U["heads"].get(uid, ""),
                            "file": self.file_of(uid)})  # as the inspector shows a fact
        return out  # [] for a sentence with nothing behind it

    def gone(self, link: dict) -> bool:
        """Has the evidence of a drafted sentence changed since the draft? Only asked when the facts are newer than the draft."""
        if self.live is None or link.get("frame"):  # the draft is current, or the sentence claims nothing
            return False  # nothing to compare
        import cover as C  # the units
        import write_resume as W  # the ledger's text
        if self._live_units is None:  # first use
            self._live_units = C.units_of(W.ledger_view(self.live), self.lang)  # the facts as they are now
        ids = [i for i in link.get("ev") or [] if C.known_id(self.draft_units(), i)]  # what it cited
        return bool(ids) and not all(C.known_id(self._live_units, i) and C.unit_text(self._live_units, i) == C.unit_text(self.draft_units(), i) for i in ids)  # one of them changed or went

    def recheck(self, text: str, link: dict) -> list[dict]:
        """An edited drafted sentence against what it cites: the fact and claim rules of the draft, in the page's codes."""
        import write_resume as W  # the same rules that passed the draft
        if self._ctx is None:  # first use: it reads the whole profile
            self._ctx = W.Ctx(self.draft, W.load_style("default"), (self.draft.get("_draft") or {}).get("posting"))  # what every text is checked against
        found = W.text_issues(text, self.lang, link.get("ev") or [], link.get("names") or {}, self._ctx, kind=W.kind_of(str(link.get("at") or "")),  # the part's own rules
                              frame=bool(link.get("frame")), marks=(0, 9))  # marks are the person's choice here
        words = {"number": "number", "number_word": "number_word", "name": "latin", "name_src": "latin", "org": "org", "no_ev": "no_evidence",  # the page's codes
                 "unknown_id": "no_evidence", "empty": "no_evidence", "frame_where": "no_evidence"}  # what the inspector words
        out = []  # for the sentence's issues
        for i in found:  # each problem
            if i["code"] == "claim":  # stronger than the evidence
                out.append({"code": "claim", "words": str(i.get("claim", "")), "said": str(i.get("hedge", ""))})  # both words
            elif i["code"] in words:  # a fact the evidence lacks; wording is the person's to choose
                out.append({"code": words[i["code"]], "words": str(i.get("detail") or i.get("id") or "")})  # as found
        return out  # [] when the evidence still covers it

    def add_drafted(self, sid: str, text: str, link: dict) -> str:
        """Register a sentence the draft wrote: its evidence from the ids it cited, and the checks again if it was edited."""
        self.link_of[sid] = link  # for the evidence text and for edits
        issues: list[dict] = []  # what the checks found
        if link.get("typed"):  # the person's own words, locked before the draft
            state = "typed"  # they vouch for them
        elif self.gone(link):  # the fact behind it changed after the draft
            state, issues = "unsupported", [{"code": "no_evidence", "words": ""}]  # marked until it is written again
        elif link.get("edited"):  # changed by the person
            issues = self.recheck(text, link)  # the same rules
            state = "unsupported" if issues else "edited"  # inside the evidence, or not
        else:  # as the draft wrote it, after the checks
            state = "ok"  # as the evidence says
        self.sent[sid] = {"text": text, "state": state, "evidence": self.draft_evidence(link), "issues": issues, "kind": "draft",  # the record the page reads
                          "locked": sid in self.locks, "drafted": True}  # the inspector says who wrote it
        return sid  # for the block

    def evidence_of(self, sid: str) -> tuple[list[dict], str]:
        """(the evidence of a sentence, the kind of its fact): one entry per fact, quote and file name."""
        place = self.place_of(sid)  # its item
        cids = self.facts_at(place)  # the facts behind it
        out, kind = [], ""  # entries, the first fact's kind
        if not cids and self.base_name and self.in_base(place):  # an item an imported profile carried with no card of its own
            return [{"quote": self.in_base(place), "where": "profile", "file": self.base_name}], "profile"  # the imported file is its evidence
        for c in cids:  # each fact
            if c.startswith("details:"):  # the person's own words
                out.append({"quote": "", "where": "details", "file": ""})  # shown as "Your details"
                kind = kind or "typed"  # the person vouches for it
                continue  # next fact
            f = self.by_cid.get(c)  # the fact
            if not f:  # a fact that is gone (a stale map)
                continue  # nothing to show
            src = f.get("source") or {}  # where it came from
            where = " · ".join(x for x in (text_of(f.get("org")), text_of(f.get("title"))) if x)[:120]  # the company and title it names
            out.append({"unit": c, "quote": text_of(f.get("quote")), "where": where,  # the fact's own quote
                        "file": text_of(src.get("name")) if f.get("origin") != "typed" else ""})  # a file name, never a path; typed facts have none
            kind = kind or ("typed" if f.get("origin") == "typed" else text_of(f.get("kind")))  # the first fact's kind
        return out, kind  # [] when nothing backs it

    def evidence_text(self, sid: str) -> str:
        """Everything the evidence of a sentence says, as one text for src/factcheck.py: each fact's quote, its title,
        company and period, and for an imported project its original points and figure (from base.json)."""
        if sid in self.link_of:  # a drafted sentence: what it cites
            import cover as C  # the units' text
            return "\n".join(C.unit_text(self.draft_units(), i) for i in self.link_of[sid].get("ev") or [] if C.known_id(self.draft_units(), i))  # one text
        parts = []  # pieces of evidence
        for c in self.facts_at(self.place_of(sid)):  # each fact behind the sentence
            f = self.by_cid.get(c)  # the fact
            if not f:  # the person's own words, or a stale id
                continue  # nothing to add
            parts += [text_of(f.get(k)) for k in ("quote", "title", "org", "period")]  # its own words
            if f.get("origin") == "profile" and f.get("ref"):  # an imported item: its original fields in the base
                item = self.base  # walk down the base profile
                for k in f["ref"]:  # the path
                    try:
                        item = item[k]  # one level
                    except (KeyError, IndexError, TypeError):  # the path is gone
                        item = None  # nothing more
                        break  # stop walking
                parts.append(json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else text_of(item))  # every word it holds
        return "\n".join(p for p in parts if p)  # one text

    def add(self, sid: str, text: str) -> str:
        """Register one sentence with its evidence and state. Returns its id."""
        text = str(text or "").strip()  # as printed
        link = drafts.link_for(self.links, text)  # a sentence the draft wrote
        if link is not None:  # its evidence is what it cited
            return self.add_drafted(sid, text, link)  # registered
        ev, kind = self.evidence_of(sid)  # its facts
        place = self.place_of(sid)  # its item
        cids = [c for c in self.facts_at(place) if not c.startswith("details:")]  # its real facts
        edited = not self.translated and any(c in self.edits for c in cids)  # the person changed one of them (an agent's checked translation counts as its source)
        issues: list[dict] = []  # what the fact check found
        if kind == "typed" or any(e.get("where") == "details" for e in ev):  # the person's own words
            state = "typed"  # they vouch for them
        elif not ev:  # nothing backs it
            state, issues = "unsupported", [{"code": "no_evidence", "words": ""}]  # marked, and the export stops
        elif not edited:  # the fact's own text
            state = "ok"  # as the evidence says
        else:  # changed by the person: the fact check decides
            evid = self.evidence_text(sid)  # what the facts say
            found = factcheck.unsupported(text.replace("==", ""), evid, check_latin=not self.translated)  # new numbers, tools, names
            claim = getattr(factcheck, "claim_issues", None)  # the claim-strength rule, where the engine has it
            found += claim(text.replace("==", ""), evid) if claim else []  # "led" where the evidence says "helped"
            issues = issue_codes(found)  # as codes
            if re.fullmatch(r"(roles|education)\.\d+", sid):  # a company or a school named in a table row
                name = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()  # without its place in brackets
                if name and re.sub(r"\s+", "", name) not in re.sub(r"\s+", "", evid) and not any(i["code"] == "org" for i in issues):  # a name the evidence never writes
                    issues.append({"code": "org", "words": name})  # a company or school is a fact: it must come from the evidence
            state = "unsupported" if issues else "edited"  # inside the evidence, or not
        self.sent[sid] = {"text": text, "state": state, "evidence": ev, "issues": issues, "kind": kind,  # the record the page reads
                          "locked": sid in self.locks}  # later drafts keep it
        return sid  # for the block

    def paragraph(self, base_sid: str, text) -> list[str]:
        """A paragraph's sentences registered as base_sid.s0, .s1 ... Returns their ids."""
        return [self.add(f"{base_sid}.s{i}", s) for i, s in enumerate(sentences(text_of(text)))]  # one id per sentence

    # ---------------------------------------------------------------- the blocks, in print order

    def build(self) -> dict:
        """The whole model (resume.schema.json)."""
        P, L, W = self.prof, self.lang, WORDS[self.lang]  # the profile, the language, its words
        person = P.get("person") or {}  # who
        # a person's field, written once or per language; per language it is this language's only (src/profile_loader.js
        # pickDeep): an English location left empty in Korean is not printed in the Korean header
        field = lambda k: text_of(person[k].get(L) if isinstance(person.get(k), dict) else person.get(k))  # noqa: E731
        # the header's right side in the printed order (src/resume_form.js): personal details, where they live, phone, email, links
        contacts = [[W["info"], field("info")], [W["location"], field("location")], [W["phone"], field("phone")], [W["email"], field("email")]]
        contacts += [[text_of(x[0]), text_of(x[1])] for x in person.get("links") or [] if isinstance(x, (list, tuple)) and len(x) >= 2]  # links
        for k, label in (("linkedin", "LinkedIn"), ("github", "GitHub"), ("scholar", "Scholar"), ("homepage", "Web")):  # a ledger keeps these as keys
            if field(k) and not any(c[0] == label for c in contacts):  # shown without the scheme, as the loader does
                contacts.append([label, re.sub(r"^https?://(www\.)?", "", field(k))])
        name, name_en = clean_name(text_of(person.get("name")), text_of(person.get("name_en")))  # '홍 길 동 (Gildong Hong)' as the loader reads it
        head = {"name": name, "name_en": field("name_en_ko") or name_en,  # the name band: the Korean edition writes the English name as the person asked
                "tagline": field("tagline"), "contacts": [c for c in contacts if c[1]]}  # only filled contacts
        if L == "en" and name_en:  # the English edition leads with the English name, as the printed one does
            head["name"], head["name_en"] = name_en, ""  # one name
        S = P.get("summary") if isinstance(P.get("summary"), dict) else {}  # the summary block
        if text_of(pick_lang(S.get("headline"), L)):  # the headline
            self.blocks.append({"type": "headline", "sid": self.add("summary.headline", text_of(pick_lang(S.get("headline"), L)))})  # one line
        intro = S.get("intro")  # plain or per language
        intro = (intro.get(L) or intro.get("ko") or intro.get("en")) if isinstance(intro, dict) else intro  # this language's text
        if text_of(intro):  # an introduction
            self.blocks.append({"type": "intro", "sids": self.paragraph("summary.intro", intro)})  # its sentences
        cards = [r for r in self.lang_list(S.get("cards")) if isinstance(r, (list, tuple)) and r]  # [[title, text], ...]
        hls = [h for h in self.lang_list(S.get("highlights")) if isinstance(h, dict)]  # key project cards
        if cards or hls:  # the overview
            self.section("overview")  # its heading
        # a card and a key project's row print their second element only (layout.js fcards and fhighlights read [head, text]):
        # a third one is the deck's longer wording, and the canvas showed it too, so its cards ran longer than the PDF's
        second = lambda r: text_of(r[1]) if len(r) > 1 else ""  # noqa: E731
        if cards:  # two-column cards
            self.blocks.append({"type": "cards", "items": [{"title": text_of(r[0]), "sid": self.add(f"summary.cards.{i}", second(r))}
                                                           for i, r in enumerate(cards)]})  # title and text
        if hls:  # selected projects
            items = []  # one card each
            for i, h in enumerate(hls[:4]):  # four at most, as printed
                rows = [r for r in h.get("rows") or [] if isinstance(r, (list, tuple)) and r]  # [[label, text], ...]
                items.append({"title": text_of(h.get("title")), "where": text_of(h.get("where")),  # the card's head
                              "rows": [{"label": text_of(r[0]), "sid": self.add(f"summary.highlights.{i}.rows.{k}", second(r))}
                                       for k, r in enumerate(rows)]})  # its rows
            self.blocks.append({"type": "highlights", "title": W["highlights"], "items": items})  # the cards
        # employers, as src/profile_loader.js keeps them: a role with neither a name nor a career block (a ledger's note of a
        # company that is not on the resume) prints nowhere, so the canvas does not show it either. Each keeps its place in the
        # profile (its sentence ids) and the logo tile name overview_figures.py draws for it
        roles = [(ri, r) for ri, r in enumerate(P.get("roles") or []) if isinstance(r, dict) and (text_of(r.get("org")) or isinstance(r.get("career"), dict))]
        for n, (ri, r) in enumerate(roles):  # the tile's name: the role's key, else its place among the kept roles
            c = r["career"] if isinstance(r.get("career"), dict) else {}
            self.logo_ids[ri] = "role_" + re.sub(r"[^A-Za-z0-9_-]", "_", str(r.get("key") or c.get("key") or f"role{n + 1}"))
        roles.sort(key=lambda x: -(ym_number(role_fields(x[1], L)["start"]) or 0))  # newest first, as printed; equal starts keep the written order
        if roles:  # the career summary table
            self.section("career")  # its heading
            rows, months = [], 0  # one per role; the months of them all, for the total beside the heading
            for ri, r in roles:  # each employer
                f = role_fields(r, L)  # its shown fields
                org = f["org"] + (f" ({f['place']})" if f["place"] else "")  # company (place), for a reader of the model as before
                dept = " / ".join(x for x in (f["dept"], f["title"]) if x)  # department / title
                n = months_between(f["start"], f["end"])  # how long, in months (both ends counted)
                months += n or 0  # the loader sums the roles' months the same way
                rows.append({"period": period_text(f["start"], f["end"], L), "org": org, "dept": dept,  # the row's cells
                             "name": f["org"], "place": f["place"], "department": f["dept"], "role": f["title"],  # the printed table's own columns
                             "sub": ", ".join(x for x in (f["place"], f["note"]) if x),  # the grey line under the name: the place, then the note
                             "tenure": tenure_text(n, L),  # how long
                             "logo_id": self.logo_ids[ri],  # its tile
                             "sid": self.add(f"roles.{ri}", f["org"])})  # the company's name is the row's sentence: the place prints under it, the department and title beside it
            if any(r["tenure"] for r in rows) and tenure_text(months, L):  # the total, as the heading prints it when the table has a tenure column
                self.blocks[-1]["note"] = f"({W['total']} {tenure_text(months, L)})"  # "(총경력 7년 2개월)", grey after the title
            self.blocks.append({"type": "career", "rows": rows})  # the table
        edu = [e for e in P.get("education") or [] if isinstance(e, dict)]  # schools
        if edu:  # the education table
            self.section("edu")  # its heading
            # its dates as the loader writes them: an end left out is unknown ('2023.03 ~'), an empty end (None) is still there,
            # unless the timeline fades the bar out (an unfinished degree), which reads as unknown too
            ends = lambda e: "" if (e.get("fadeTo") or e.get("chart_fade_to")) and e.get("end", "") is None else e.get("end", "")  # noqa: E731
            self.blocks.append({"type": "education", "rows": [{  # one row per school
                "period": period_of(e.get("start"), ends(e), L, W["now_edu"]),  # its dates
                **school_fields(e, L),  # its cells
                "sub": text_of(pick_lang(e.get("sub"), L)), "majorSub": text_of(pick_lang(e.get("majorSub"), L)),  # the grey second lines the printed table has
                "note": text_of(pick_lang(e.get("note"), L)),
                "logo_id": "edu_" + re.sub(r"[^A-Za-z0-9_-]", "_", str(e.get("key") or ei + 1)),  # its tile, named as src/profile_loader.js names it
                "sid": self.add(f"education.{ei}", school_fields(e, L)["school"])}
                for ei, e in enumerate(edu)]})  # each school once
        comps = self.lang_list(P.get("competencies"))  # strengths
        if comps:  # core competencies
            self.section("comp")  # its heading
            weak = set(self.plan.get("competencyWeak") or [])  # strengths this job puts back
            names = {}  # a project's id and title -> the short name a competency's evidence prints (src/profile_loader.js projectIndex)
            for _, r in roles:  # every printed role's projects
                for pi, p in enumerate(r.get("projects") or []):
                    if isinstance(p, dict):
                        short = text_of(pick_lang(p.get("short"), L)) or text_of(pick_lang(p.get("title"), L))  # its short name, else its title
                        for k in (text_of(p.get("id")), text_of(pick_lang(p.get("title"), L))):
                            names.setdefault(k, short)
            items = []  # one per strength
            for i, c in enumerate(comps):  # each one
                # the pair form prints its second element (layout.js reads [name, text]); the named form its text, then its evidence
                # projects in brackets, which the canvas draws after the sentence so the sentence's own words stay as written
                headw, text = (text_of(c.get("name")), text_of(c.get("text"))) if isinstance(c, dict) else (text_of(c[0]), text_of(c[1]) if len(c) > 1 else "") if isinstance(c, (list, tuple)) and c else ("", "")  # both shapes
                ev = [names.get(text_of(e), text_of(e)) for e in (c.get("evidence") or [])] if isinstance(c, dict) else []  # its evidence projects by name
                if headw or text:  # a real entry
                    items.append({"head": headw, "sid": self.add(f"competencies.{i}", text), "weak": headw in weak,  # a job may put it back
                                  **({"evidence": f"({', '.join(ev)})"} if ev else {})})  # printed after it
            items.sort(key=lambda x: x["weak"])  # what the job puts back goes last, as printed (nothing is faded or dropped)
            self.blocks.append({"type": "competencies", "items": items})  # the bullets
        skills = [s for s in P.get("skills") or [] if isinstance(s, dict) and s.get("category") and self.for_edition(s)]  # skill groups of this edition
        if skills:  # the skills table
            self.section("skills")  # its heading
            focus = [x for x in self.plan.get("skillsFocus") or []]  # the job's leading groups
            order = sorted(range(len(skills)), key=lambda i: (focus.index(skills[i]["category"]) if skills[i]["category"] in focus else len(focus), i))  # focus first
            self.blocks.append({"type": "skills", "rows": [{"category": text_of(skills[i]["category"]),  # the group
                                                            "items": ", ".join(map(text_of, skills[i].get("items") or [])),  # its skills
                                                            "focus": skills[i]["category"] in focus,  # led with for this job
                                                            "sid": self.add(f"skills.{i}", ", ".join(map(text_of, skills[i].get("items") or [])))}
                                                           for i in order]})  # in the job's order
        if roles:  # the experience, role by role
            self.section("detail")  # its heading
            want = [x for x in self.plan.get("projectOrder") or []]  # the job's project order
            for ri, r in roles:  # each employer, newest first
                projs = [(pi, p) for pi, p in enumerate(r.get("projects") or []) if isinstance(p, dict) and p.get("resume") is not False and self.for_edition(p)]  # its projects on this edition's resume: a draft leaves some off
                projs.sort(key=lambda x: (want.index(x[1].get("id")) if x[1].get("id") in want else len(want), x[0]))  # the job's order first
                f = role_fields(r, L)  # its shown fields
                self.blocks.append({"type": "role", "org": f["org"], "title": f["title"], "title_long": f["title_long"],  # the band; the long title an English one-column line prints
                                    "dept": f["dept"], "period": period_text(f["start"], f["end"], L),  # its dates
                                    "place": f["place"], "tenure": tenure_text(months_between(f["start"], f["end"]), L),  # grey on the band's right, then the dates and (tenure)
                                    "sub": f["sub"] or " / ".join(x for x in (f["dept"], f["title"]) if x),  # the underlined line under the band, as resume_form.js writes it
                                    "desc": f["desc"], "badge": f["badge"],  # the grey line about the company; the small mark beside the name
                                    "sid": f"roles.{ri}", "logo_id": self.logo_ids[ri],  # the band's evidence is the role's; its tile
                                    "projects": [{"pid": text_of(p.get("id")), "title": text_of(pick_lang(p.get("title"), L)),  # each project
                                                  "period": norm_period(text_of(pick_lang(p.get("period"), L)), L),  # its dates, normalized as printed
                                                  "sids": self.paragraph(f"roles.{ri}.projects.{pi}.summary", pick_lang(p.get("summary"), L))}  # its sentences
                                                 for pi, p in projs]})  # in order
        skills_like = re.compile(r"^(기술\s*스택|기술|보유\s*기술|skills?|technical skills|tech stack)$", re.I)  # a list that repeats the skills table (src/profile_loader.js)
        for si, sec in enumerate(P.get("sections") or []):  # certificates, awards and other lists
            if not isinstance(sec, dict) or not self.for_edition(sec):  # a broken entry, or one written for the other language's edition
                continue  # skipped, as src/profile_loader.js skips it
            if sec.get("resume") is False:  # a list the profile keeps out of resumes: resume_form.js prints none of it
                continue
            title = text_of(pick_lang(sec.get("title"), L))  # its heading as written
            if P.get("skills") and skills_like.match(title.strip()):  # the skills table already says it once: the loader leaves it out
                continue
            groups = [self.list_group(sec, f"sections.{si}", None)]  # its own lines, as resume_form.js bodyOf prints them
            groups += [self.list_group(g, f"sections.{si}.groups.{gi}", text_of(pick_lang(g.get("title"), L)))  # then each group under its caption
                       for gi, g in enumerate(sec.get("groups") or []) if isinstance(g, dict)]
            if not any(g["items"] or g["lines"] or g["table"] or g["note"] for g in groups) and sec.get("body_md"):  # the ledger form: a text body
                import cover as C  # the same lines the checks read
                groups = [{"caption": None, "items": [{"sid": self.add(f"sections.{si}.body.{li}", b)} for li, b in enumerate(C.split_blocks(sec["body_md"])) if b],  # one sentence per line, resting on the section's card
                           "lines": [], "table": None, "note": ""}]
            groups = [g for g in groups if g["items"] or g["lines"] or g["table"] or g["note"]]  # a group with nothing to print has no caption either
            if groups:  # a list worth printing
                self.blocks.append({"type": "section", "title": title,  # its heading as resume_form.js prints it (the list's own title in either edition)
                                    "en": text_of(sec.get("title_en")).upper()})  # the faint label
                self.blocks.append({"type": "list", "groups": groups,  # captions, bullets, dated lines, tables and notes, in print order
                                    "items": [x for g in groups for x in g["items"] + g["lines"]]})  # every sentence of it, for a reader of the model as before
        sv = P.get("service") if isinstance(P.get("service"), dict) else {}  # the military service record (src/profile_loader.js service)
        sv_label = text_of(pick_lang(sv.get("label"), L)) or text_of((sv.get(L) if isinstance(sv.get(L), dict) else {}).get("chart"))  # what it was: its label, else the ledger's chart words
        if sv_label:  # only the table form prints it, after the other lists (documents.for_form)
            self.section("service")  # its heading
            self.blocks.append({"type": "service", "label": sv_label,  # one row: when, and what (printed words, as a list table's cells)
                                "period": " ~ ".join(x for x in (text_of(sv.get("start")), text_of(sv.get("end"))) if x)})  # the dates as written, joined as resume_form.js joins them
        about = self.lang_list(P.get("about"))  # about me
        if about:  # the about-me band
            self.section("about")  # its heading
            items = []  # one per paragraph group
            for i, a in enumerate(about):  # each entry
                if isinstance(a, (list, tuple)) and a:  # [title, paragraph or paragraphs]
                    body = a[1] if len(a) > 1 else ""  # one or several paragraphs
                    paras = body if isinstance(body, list) else [body]  # always a list
                    groups = [self.paragraph(f"about.{i}" + (f".p{k}" if len(paras) > 1 else ""), para) for k, para in enumerate(paras)]  # numbered per paragraph
                    items.append({"title": text_of(a[0]), "sids": [x for g in groups for x in g],  # one band, and every sentence under it
                                  "paras": [g for g in groups if g]})  # its paragraphs, each printed as its own block
            self.blocks.append({"type": "about", "items": items})  # the bands
        mot = pick_lang(P.get("motivation"), L)  # why this role
        paras = [text_of(x) for x in mot if text_of(x)] if isinstance(mot, list) else [text_of(mot)] if text_of(mot) else []  # one paragraph or several
        if paras:  # a motivation
            # a general edition prints the person's own name for it (motivationTitle, its English in motivationSub); a draft written for
            # a posting drops it (documents.drawn), and the form's own title is printed instead (src/resume_form.js)
            own = text_of(pick_lang(P.get("motivationTitle"), L))
            self.section("motivation")  # its heading
            if own:  # the person's own title, and its faint English label
                self.blocks[-1].update(title=own, en=(text_of(P.get("motivationSub")) or text_of(pick_lang(P.get("motivationTitle"), "en")) or own).upper())
            sids = self.paragraph("motivation", " ".join(paras))  # its sentences, numbered over the whole text as before
            split, at = [], 0  # the sentences of each printed paragraph
            for para in paras:  # a paragraph's own sentences, in order
                n = len(sentences(para))
                split.append(sids[at:at + n])
                at += n
            self.blocks.append({"type": "motivation", "sids": sids,  # its sentences
                                "paras": split if at == len(sids) else [sids]})  # its paragraphs, when the sentences fall on their boundaries
        counts = {"sentences": len(self.sent), "unsupported": sum(1 for s in self.sent.values() if s["state"] == "unsupported"),  # the totals
                  "edited": sum(1 for s in self.sent.values() if s["state"] == "edited"),
                  "locked": sum(1 for s in self.sent.values() if s["locked"])}  # the margin's counts
        return {"kind": "resume", "lang": L, "theme": self.theme, "job": self.job, "colors": THEMES[self.theme],  # the model
                "labels": {k: W[k] for k in ("period", "org", "dept", "role", "tenure", "school", "major", "degree", "cat", "tech", "resume", "name", "kind")},  # table heads; the table form's title and name row
                "person": head, "blocks": self.blocks, "sentences": self.sent, "counts": counts}  # the rest

    def list_group(self, g: dict, base: str, caption: str | None) -> dict:
        """One part of a list section as resume_form.js bodyOf prints it: bullets (items), dated lines ([main, org, date]: the
        line is one sentence, its parts drawn apart as printed), a table (head, rows, column widths in twips, alignment; its
        cells are printed words, not sentences) and a grey note, under a caption for a group."""
        L = self.lang  # the edition's language
        said = lambda it: text_of(it) if not isinstance(it, dict) else text_of(it.get("text") or it.get("title"))  # noqa: E731  plain or richer bullets
        items = [{"sid": self.add(f"{base}.items.{ii}", said(it))} for ii, it in enumerate(g.get("items") or []) if said(it)]  # each bullet with words
        lines = []  # the dated lines
        for li, ln in enumerate(g.get("lines") or []):  # each [main, org, date]
            ln = ln if isinstance(ln, list) else [ln]  # a plain line is its main part
            words = " ".join(text_of(x) for x in ln if text_of(x))  # the line as one sentence, as before
            if words:  # only lines with words
                lines.append({"sid": self.add(f"{base}.lines.{li}", words), "main": text_of(ln[0]),  # the line, and its parts as printed
                              "org": text_of(ln[1]) if len(ln) > 1 else "", "date": text_of(ln[2]) if len(ln) > 2 else ""})
        table = None  # a table, when the group has rows
        rows = [r for r in g.get("rows") or [] if isinstance(r, list)]  # its rows
        if rows:  # printed as a table (layout.js ftable)
            cell = lambda c: {"t": text_of(c.get("t")), "bold": bool(c.get("bold")), "accent": bool(c.get("accent"))} if isinstance(c, dict) else {"t": text_of(c)}  # noqa: E731
            head = [text_of(pick_lang(h, L)) for h in g.get("head") or []] or None  # its head row, if it has one
            table = {"head": head, "rows": [[cell(c) for c in r] for r in rows],  # the cells as printed
                     "widths": auto_widths(head or ["" for _ in rows[0]], [[cell(c)["t"] for c in r] for r in rows], g.get("widths")),  # resume_form.js autoWidths
                     "align": g.get("align") or None}  # c, l or r per column
        return {"caption": caption or None, "items": items, "lines": lines, "table": table, "note": text_of(pick_lang(g.get("note"), L))}

    def section(self, key: str) -> None:
        """A section heading in the document's language with its faint English label."""
        self.blocks.append({"type": "section", "key": key, "title": WORDS[self.lang][key], "en": EN_LABEL.get(key, "")})  # one heading

    def for_edition(self, item: dict) -> bool:
        """An item written for one language ("lang") is printed in that edition only (src/profile_loader.js does the same),
        so the canvas shows what the PDF prints."""
        return not item.get("lang") or item.get("lang") == self.lang  # no language: both editions

    def lang_list(self, v) -> list:
        """A list field that may be written per language, in the document's language (Korean as the fallback)."""
        if isinstance(v, dict):  # {ko: [...], en: [...]}
            v = v.get(self.lang) or v.get("ko") or v.get("en")  # this language first
        return v if isinstance(v, list) else []  # always a list


# ------------------------------------------------------------------------------------------- edits on the canvas

def field_for(sid: str) -> tuple[str, str, int | None]:
    """Where a sentence id's words live: (item place, field, sentence number or None).
    roles.0.projects.1.summary.s0 -> (roles.0.projects.1, statement, 0); summary.cards.2 -> (summary.cards.2, statement, None);
    summary.highlights.0.rows.2 -> (summary.highlights.0, rows.2, None); summary.intro.s1 -> (summary.intro, intro, 1)."""
    m = re.match(r"^(.*?)(?:\.s(\d+))?$", sid)  # the sentence number, when there is one
    base, n = m.group(1), (int(m.group(2)) if m.group(2) is not None else None)  # the field and the sentence
    if base.startswith("summary.headline"):  # the person's headline
        return "summary.headline", "headline", None  # a details field
    if base.startswith("summary.intro"):  # the person's introduction
        return "summary.intro", "intro", n  # a details field, by sentence
    hm = re.match(r"^(summary\.highlights\.\d+)\.rows\.(\d+)$", base)  # one row of a key project card
    if hm:  # its row
        return hm.group(1), f"rows.{hm.group(2)}", None  # the card and the row
    if base.endswith(".summary"):  # a project's summary
        return base[:-len(".summary")], "statement", n  # the project's statement, by sentence
    am = re.match(r"^(about\.\d+)(?:\.p\d+)?$", base)  # an about-me paragraph
    if am:  # its paragraph
        return am.group(1), "statement", n  # the about fact's statement
    if base == "motivation":  # why this role
        return "motivation", "statement", n  # the motivation fact
    if re.fullmatch(r"(roles|education)\.\d+", base):  # a career or education row: its sentence is the company or the school
        return base, "org", None  # the fact's org field (a school is a fact's org too)
    return base, "statement" if not base.startswith("sections.") else "title", None  # cards, competencies, list lines


def replaced(old: str, n: int | None, new: str) -> str:
    """A paragraph with sentence n replaced by new (the whole text when n is None)."""
    if n is None:  # one piece of text
        return new.strip()  # the new text
    parts = sentences(old)  # its sentences
    if n >= len(parts):  # a sentence that is gone (a stale page)
        raise ValueError("sentence")  # refused
    parts[n] = new.strip()  # the new words
    return join_sentences(parts)  # one paragraph again
