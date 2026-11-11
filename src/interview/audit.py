"""Audits of a job's interview kit, and a score against a person's own audit.

Coverage (no model): every posting line is rated strong, weak or none by cover.py, with the items that cover it.
With --judge, one model call reads each line with its closest scenes and says whether one of them really answers it:
a strong line that no scene answers drops to weak, and a weak line that a scene answers rises to strong.

Portfolio claims (no model): the lines of the portfolio an interviewer may ask about that no scene speaks to. The
portfolio is read in reading order, one paragraph or label at a time. A line is unanswered when it holds a phrase no
scene says: a number with its unit ("42 minutes"), a name ("Argo CD"), or two content words in a row ("idempotency
key"). Lines are ranked by how rare their missing phrases are and by how short they are (headlines and badges
first), and the first CLAIMS are listed.

Consistency (--consistency, model-assisted): each scene's English is compared with the submitted resume, the
portfolio and the other scenes. The documents are split into paragraphs; for each scene the paragraphs and the other
scenes' sentences that share its rarest words go with it (inverse document frequency, no model). Scenes are ranked by
risk: how often the scene limits its own scope ("already existed", "a colleague's"), claims in the first person
("I founded", "I ported"), gives dates or titles, and how closely it touches the documents. With --calls N only the N
riskiest batches go to the model. The model lists disagreements with an exact quote from each side; a flag is kept
only when both quotes are found in the texts, and the others are counted as dropped.

Answer key (--key): the findings of a person's own audit (docs/INTERVIEW.md, "Answer keys"), scored as recall (how
many of the key's findings the audit made) and precision (how many of the audit's findings are in the key).

Writes audit.json and audit.md, and recall.json with --key, to the output folder.
"""
import json  # the record
import math  # inverse document frequency
import pathlib  # paths
import re  # quote matching and the risk signals

from interview import check, corpus, cover, i18n  # scenes, items, coverage, messages
from interview import plan as planmod  # posting lines
from interview import text as T  # words
from interview.job import read_text  # files

HERE = pathlib.Path(__file__).resolve().parent  # src/interview
PROMPT = (HERE / "prompts" / "consistency.md").read_text(encoding="utf-8")  # the consistency rules
JUDGE = (HERE / "prompts" / "coverage_judge.md").read_text(encoding="utf-8")  # the coverage judge's rules
CLAIMS_JUDGE = (HERE / "prompts" / "claims_judge.md").read_text(encoding="utf-8")  # the portfolio claims judge's rules
SYSTEM = "You check interview scripts against submitted documents. Quote exactly. Return only JSON."  # exact quotes can be verified
BATCH = 4  # scenes per model call when no budget is given: small calls
BATCH_BUDGET = 12  # scenes per model call when a budget is given: fewer, fuller calls reach more scenes
MAX_SCENE_CHARS = 6000  # a scene's answer is cut to this many characters in the prompt: a drafted scene of five exchanges fits whole
CLAIMS = 30  # portfolio lines listed as unanswered
JUDGE_POOL = 1300  # candidate lines the claims judge chooses from in its one call (every candidate of a 32-page portfolio)
CLAIMS_JUDGED = 40  # lines the claims judge keeps: a person reads them in a few minutes, and an interviewer's next question is often among the later ones
K_RESUME, K_PORTFOLIO, K_SCENES = 6, 6, 6  # paragraphs of each document and sentences of other scenes sent with a scene: a disagreement needs its other side in view
# The JSON shape of the answer: a list of flags, each with the scene id, both quotes, the document, the kind and the reason
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["flags"],
          "properties": {"flags": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                             "required": ["id", "scene_quote", "doc", "doc_quote", "kind", "why"],
                                                             "properties": {k: {"type": "string"} for k in ("id", "scene_quote", "doc", "doc_quote", "kind", "why")}}}}}
CLAIMS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["picks"],  # the claims judge's answer
                 "properties": {"picks": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["n", "why"],
                                                                    "properties": {"n": {"type": "string"}, "why": {"type": "string"}}}}}}
JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lines"],  # the judge's answer
                "properties": {"lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                   "required": ["n", "verdict", "id", "why"],
                                                                   "properties": {"n": {"type": "string"}, "verdict": {"type": "string"},
                                                                                  "id": {"type": "string"}, "why": {"type": "string"}}}}}}

# ---------- risk signals (English scenes) ----------

# a scene that limits its own part: the documents may claim more than the scene says, or the other way round
HEDGE = re.compile(r"already existed|existed (?:at|before)|was (?:already )?there|from launch|before I (?:came|joined|arrived)|"
                   r"my part was|\bcolleague|the team's|team's own|not built|wasn't built|a proposal|proposed|I can't say|"
                   r"I won't claim|I didn't|I haven't|I have not|honestly|to be clear|on scope|not exactly|correction|"
                   r"only touched|not in my records|isn't in my records|I don't have|after I left|my scope", re.I)
# a first-person claim: the documents may give the same work to the team
CLAIM = re.compile(r"\bI (?:also |first |then |later |personally )?(?:founded|co-founded|led|built|designed|architected|owned|"
                   r"created|ported|drove|ran|launched|started|wrote|developed|implemented|managed|migrated|moved|made)\b", re.I)
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"  # month names
DATE = re.compile(r"\b(?:(?:%s)\s+(?:19|20)\d\d|(?:early|mid|late)[- ](?:19|20)\d\d|(?:19|20)\d\d\.\d\d|(?:19|20)\d\d)\b" % MONTHS, re.I)  # a date or a year
TITLE = re.compile(r"\b(?:as|was|am|I'm)\s+(?:an?\s+|the\s+|our\s+)?(?:[\w-]+\s+){0,2}(?:lead|manager|head|director|owner|architect|"
                   r"PM|PL|PO|founder|co-founder|intern|researcher)\b", re.I)  # a title the person gives themselves


def norm(s):
    """Text for quote matching: no speech marks, one space, lowercase, plain quotes and hyphens."""
    s = re.sub(r"\*\*|==|`", "", s or "")  # stress, key phrase and code marks
    s = re.sub(r"\s/{1,2}\s", " ", s)  # breath and sentence marks
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-")  # typographic quotes and dashes
    return re.sub(r"\s+", " ", s).strip().lower()  # one space and lowercase, so spacing and case never decide a match


def spoken(s):
    """What a line says aloud: no marks, no Korean stage notes."""
    s = re.sub(r"\([^()]*[가-힣][^()]*\)", " ", s or "")  # (웃으며) and the like are not said
    s = re.sub(r"\s/{1,2}\s|\s/{1,2}$", " ", s)  # breath and sentence marks
    return re.sub(r"\s+", " ", s.replace("**", "").replace("==", "").replace("`", "")).strip()  # one space


# ---------- coverage ----------

def coverage(job, items, alts):
    """[(posting line number, section, line, rating, [(id, share)])]."""
    cov = cover.Coverage(items, alts, job.kit)  # the rules
    p = job.in_job(job.kit["posting"])  # the posting
    rows = []  # results
    for n, sec, line in planmod.posting_lines(read_text(p)) if p and p.is_file() else []:  # no rows when the posting is missing
        rating, by, _ = cov.rate(line)  # strong, weak or none, with the covering items
        rows.append((n, sec, line, rating, by))  # one row per posting line
    return rows


def scene_answers(job):
    """{id: (item, my English lines, every English line)} of the scenes; my lines are what the person says."""
    _, scenes = check.load_scenes(job)  # every scene with its dialogue
    out = {}  # by id
    for it, dialogue, _ in scenes:  # file order
        mine = spoken(" ".join(t for w, t, _ in dialogue if w == "나"))  # my lines only
        both = spoken(" ".join(t for w, t, _ in dialogue if w in ("면접관", "나")))  # the whole English scene
        out[it["id"]] = (it, mine, both)  # kept with the item
    return out


def judge_coverage(rows, answers, items, ask):
    """One model call: for each posting line, does one of its closest scenes really answer it? Returns (changed rows,
    verdicts, why it stopped or '')."""
    real = {it["id"]: it for it in items if it.get("role") in ("scenes", "deep")}  # the items that can answer a posting line
    idx = Related({i: answers[i][1] for i in real if i in answers})  # my lines of every real scene, for finding candidates
    blocks = []  # one block per posting line
    cands = {}  # line number -> candidate ids
    for n, sec, line, rating, by in rows:  # each posting line
        ids = [i for i, _ in by if i in real][:2]  # the rule's covering scenes first
        ids += [i for i, _ in idx.best(line, 4) if i not in ids][:4 - len(ids)]  # then the closest by rare words
        cands[str(n)] = ids  # remembered for the answer
        parts = [f"  [{i}] Q: {first_question(answers[i][0])} A: {answers[i][1][:900]}" for i in ids]  # each candidate's question and my answer, long enough to reach what it says about the line
        blocks.append(f"Line {n}: {line}\n" + "\n".join(parts))  # the line with its candidates
    try:
        res = ask(JUDGE.format(lines="\n\n".join(blocks)), list(cands))  # one call for every line
    except Exception as e:  # noqa: BLE001  no model, a timeout or a bad answer: the rule's ratings stand
        return rows, [], str(e)
    verdicts = {str(v.get("n")): v for v in (res or {}).get("lines", []) if isinstance(v, dict)}  # by line number
    out = []  # the rows after the judge
    for n, sec, line, rating, by in rows:  # each posting line
        v = verdicts.get(str(n))  # the judge's word on it
        if not v:  # the judge skipped it: the rule's rating stands
            out.append((n, sec, line, rating, by))
            continue
        verdict = str(v.get("verdict", "")).lower()  # yes, partly or no
        new = rating  # unchanged unless the judge disagrees
        if rating == "strong" and verdict in ("partly", "no"):  # the closest scenes do not answer it after all
            new = "weak"
        elif rating != "strong" and verdict == "yes" and v.get("id") in cands.get(str(n), []):  # a candidate does answer it
            new = "strong"
        out.append((n, sec, line, new, by if new == rating or new != "strong" else [(v["id"], 1.0)] + [x for x in by if x[0] != v["id"]]))
    return out, list(verdicts.values()), ""


def first_question(it):
    """The first interviewer line of an item (its question), without marks."""
    return spoken(cover.first_question(it))  # the same rule the coverage uses


# ---------- rare-word matching ----------

class Related:  # one per audit run
    """Texts indexed by their rare words: best(query) gives the texts that share the most inverse document frequency."""

    def __init__(self, texts, extra_df=None):  # {key: text}
        self.keys = list(texts)  # in the given order
        self.sets = {k: set(T.words(t)) for k, t in texts.items()}  # each text's content words
        df = dict(extra_df or {})  # document frequency, counted over these texts and any others the caller adds
        for s in self.sets.values():  # each text counts once per word
            for w in s:
                df[w] = df.get(w, 0) + 1
        n = max(1, len(self.sets) + int((extra_df or {}).get("__n__", 0)))  # how many texts the frequencies count
        self.idf = {w: math.log(1 + n / c) for w, c in df.items() if w != "__n__"}  # rarer words weigh more
        self.post = {}  # word -> keys holding it (an inverted index, so a query reads only its own words' lists)
        for k, s in self.sets.items():
            for w in s:
                self.post.setdefault(w, []).append(k)

    def best(self, query, k=3, skip=(), min_shared=2, min_score=0.0):
        """[(key, score)] of the k texts that share the most rare words with the query (at least min_shared words)."""
        q = set(T.words(query))  # the query's content words
        score, shared = {}, {}  # key -> summed weight, key -> shared count
        for w in q:  # only the query's words are looked up
            for key in self.post.get(w, ()):  # the texts that hold this word
                if key in skip:  # the scene itself, for example
                    continue
                score[key] = score.get(key, 0.0) + self.idf.get(w, 0.0)  # its rarity
                shared[key] = shared.get(key, 0) + 1  # and one more shared word
        # best first; rounding and the key settle ties the same way in every run, whatever order the query's words came in
        top = sorted((x for x in score.items() if shared[x[0]] >= min_shared and x[1] >= min_score), key=lambda x: (-round(x[1], 9), str(x[0])))
        return top[:k]


def paragraphs(text, cap=420, merge=False, min_words=3):
    """A document in reading order, as paragraphs of at most about cap characters (long ones cut at sentences).
    merge joins a short paragraph (a company name, a date line, a title) to the paragraph after it, so a header stays
    with what it heads: in reading order a resume's "Acme", "Seoul 2019.03 - 2022.06" and its title are three
    paragraphs, and a date is only useful next to its name."""
    out = []  # results
    for page in (text or "").split("\f"):  # pdftotext ends each page with a form feed
        head = ""  # short paragraphs waiting for the paragraph they head
        for block in re.split(r"\n\s*\n", page):  # paragraphs are separated by blank lines
            b = re.sub(r"\s+", " ", block).strip()  # one line
            if not b:  # an empty block
                continue
            if merge and len(b.split()) < 12 and len(head) + len(b) < cap:  # a header: kept for the next paragraph
                head = (head + " " + b).strip()
                continue
            b = (head + " " + b).strip() if merge else b  # the header goes first
            head = ""  # used
            if len(b.split()) < min_words and not re.search(r"\d", b):  # a stray label without a number
                continue
            if len(b) <= cap:  # short enough
                out.append(b)
                continue
            buf = ""  # sentences packed up to the cap
            for sent in re.split(r"(?<=[.!?])\s+", b):  # sentence ends
                if buf and len(buf) + len(sent) > cap:  # this sentence would overflow
                    out.append(buf); buf = sent  # close and start again
                else:
                    buf = (buf + " " + sent).strip()  # keep packing
            if buf:  # the rest
                out.append(buf)
        if head:  # headers at the end of a page stand alone
            out.append(head)
    return out


def docs(job):
    """{"resume": (text, [paragraphs]), "portfolio": (text, [paragraphs])} of the submitted documents that exist, in
    reading order (sentences stay whole there, which the quotes need), with short headers kept with what they head."""
    out = {}  # only the documents that exist
    for kind in ("resume", "portfolio"):  # the documents that were sent
        p = job.submitted(kind)  # its file
        if p:  # it was sent
            t = read_text(p, layout=False)  # reading order
            out[kind] = (t, paragraphs(t, merge=True))  # the whole text for quotes, its paragraphs for matching
    return out


# ---------- portfolio claims ----------

PHRASE_STOP = set("page slide role context stack result results before after challenge action overview figure table team "
                  "project projects".split())  # layout words, not claims
QUANTITY = r"dozens|hundreds|hundred|thousands|thousand|millions|tens"  # numbers written as words, which a badge uses as often as digits
FUNC = set("a an the of to in on for and or is are was were be by with as at from that this into than then it its i we my our "
           "so but not no only".split())  # function words: a line with several of them reads as a sentence, not a list


def claim_phrases(par):
    """The phrases of a portfolio paragraph that a scene could say: numbers with units, names, pairs of content words."""
    out = []  # (kind, phrase, words)
    num = r"(\d[\d,.]*\s*(?:\+|%|[kKmM]\b\+?)?|(?i:" + QUANTITY + r"))"  # a number, or a quantity word
    for m in re.finditer(num + r"\s*(?:of\s+)?([A-Za-z][A-Za-z-]+)(?:\s+([A-Za-z][A-Za-z-]+))?", par):  # "40+ services", "Dozens of teams"
        unit = [w for w in (m.group(2), m.group(3)) if w and w.lower() not in T.STOP_EN]  # the words after the number
        n = re.sub(r"[^\d.]", "", m.group(1)).rstrip(".") or m.group(1).lower()  # digits, or the quantity word itself
        if unit and plain_number(n, par, m.start()):  # an amount with a unit (not a year or a label)
            out.append(("number", m.group(0).strip(), [n, T.stem_en(unit[0].lower())]))
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9]*(?:[A-Z0-9][A-Za-z0-9]*)+\b|\b[A-Z][a-z]{2,}\b", par):  # MoAI, KohakuHub, Codex
        w = m.group(0)  # the name
        if m.start() == 0 or par[max(0, m.start() - 2):m.start()].strip() in (".", ":", ""):  # a capital at a sentence start is not a name
            if not re.search(r"[A-Z].*[A-Z]|\d", w):  # unless it is a name by its shape
                continue
        if w.lower() in T.STOP_EN or w.lower() in PHRASE_STOP or w.lower() in FUNC:  # an ordinary word
            continue
        out.append(("name", w, [w.lower()]))
    toks = [t for t in re.findall(r"[A-Za-z][A-Za-z-]+", par)]  # the words in order
    for a, b in zip(toks, toks[1:]):  # neighbouring words
        la, lb = a.lower(), b.lower()  # compared without case
        if la in T.STOP_EN or lb in T.STOP_EN or la in PHRASE_STOP or lb in PHRASE_STOP or la in FUNC or lb in FUNC or len(la) < 3 or len(lb) < 3:  # function words
            continue
        out.append(("pair", f"{a} {b}", [T.stem_en(la), T.stem_en(lb)]))
    return out


MAGNITUDE = {"tens": (10, 99), "dozens": (12, 99), "hundred": (100, 999), "hundreds": (100, 999), "thousand": (1000, 9999),
             "thousands": (1000, 9999), "millions": (10 ** 6, 10 ** 9 - 1)}  # the range a quantity word stands for


def same_number(a, b):
    """Do two numbers (digits or quantity words) say the same amount? "1000" and "thousand" do; "hundreds" and "dozens" do not."""
    if a == b:  # written the same way
        return True

    def span(x):  # the range a number stands for
        if x in MAGNITUDE:  # a quantity word
            return MAGNITUDE[x]
        try:
            v = float(x)  # digits
        except ValueError:  # neither
            return None
        return (v, v)  # one value
    sa, sb = span(a), span(b)  # both ranges
    return bool(sa and sb) and sa[0] <= sb[1] and sb[0] <= sa[1]  # the ranges overlap


def plain_number(n, text, start):
    """Is this number an amount? A year (2024) or a zero-padded label (02 CHAPTER) is not."""
    if re.fullmatch(r"(?:19|20)\d\d", n):  # a year
        return False
    return not re.fullmatch(r"0\d", text[start:start + 2])  # "02" is a page or chapter label


def number_units(text):
    """{(number, unit stem)} of a text: digits or quantity words with the content word after them."""
    out = set()  # pairs
    for m in re.finditer(r"(\d[\d,.]*|(?i:" + QUANTITY + r"))\s*\+?\s*(?:of\s+)?([A-Za-z][A-Za-z-]+)", text or ""):  # "about 40 services", "dozens of teams"
        n = re.sub(r"[^\d.]", "", m.group(1)).rstrip(".") or m.group(1).lower()  # digits, or the quantity word
        if plain_number(n, text, m.start()):  # years and labels are not amounts
            out.add((n, T.stem_en(m.group(2).lower())))  # the number with its unit
    return out


def page_titles(text):
    """{page number: title} of a portfolio in reading order: the first line of four words or more on each page."""
    out = {}  # by page
    for k, pg in enumerate((text or "").split("\f"), 1):  # pages from one
        for ln in pg.splitlines():  # its lines in reading order
            if len(re.findall(r"[A-Za-z가-힣]{2,}", ln)) >= 4:  # a line of words, not a page number or a label
                out[k] = ln.strip()[:120]  # the title, capped for tables
                break
    return out


def portfolio_claims(job, answers, limit=CLAIMS):
    """[{page, title, text, missing: [phrases], score}] of the portfolio paragraphs with phrases no scene says, best
    first (limit 0: every one)."""
    p = job.submitted("portfolio")  # the portfolio that was sent
    if not p:  # nothing to read
        return []
    text = read_text(p, layout=False)  # reading order
    said = " ".join(a[1] for a in answers.values() if a[0].get("role") in ("scenes", "deep"))  # every answer of every real scene
    seq = [T.stem_en(w) for w in re.findall(r"[a-z][a-z-]+", said.lower())]  # the scenes' words in order, stemmed
    pairs = set(zip(seq, seq[1:]))  # every pair of neighbouring words the scenes say
    units = number_units(said)  # every number the scenes say with its unit
    low = said.lower()  # for names inside longer tokens
    titles = page_titles(text)  # the page each claim stands on
    df = {}  # how many paragraphs of the portfolio hold each word, for rarity
    pars = [(k, u) for k, pg in enumerate(text.split("\f"), 1) for b in paragraphs(pg, min_words=2)  # (page, one claim); a two-word label ("Helm values") is a claim too
            for u in re.split(r"(?<=[.!?])\s+", b) if u.strip()]  # a sentence is one claim; a badge or a label is one too
    for _, b in pars:  # count words once per claim
        for w in set(T.words(b)):
            df[w] = df.get(w, 0) + 1
    n = max(1, len(pars))  # paragraphs counted
    rare = lambda w: math.log(1 + n / df.get(w, 1))  # noqa: E731  the rarity of a word in the portfolio
    out, seen = [], set()  # results; texts already listed (a badge repeats on several pages)
    for page, b in pars:  # each paragraph
        miss, score, other = [], 0.0, []  # phrases no scene says, their weight, and the scenes' own numbers for the same units
        for kind, phrase, ws in claim_phrases(b):  # each phrase the paragraph holds
            if kind == "number":  # a number with its unit: said when a scene says the same amount with the same unit
                said_same = [x for x, u in units if u == ws[1]]  # the scenes' amounts for this unit
                ok = any(same_number(x, ws[0]) for x in said_same)  # the same amount, in digits or in words
                if not ok:  # the scenes may give the same unit another amount ("dozens of teams" against "Hundreds")
                    other += [f"{x} {ws[1]}" for x in sorted(said_same)][:2]
            elif kind == "name":  # a name: said anywhere
                ok = ws[0] in low
            else:  # two content words in a row
                ok = (ws[0], ws[1]) in pairs
            if not ok:  # no scene says it
                weight = max([rare(w) for w in T.words(phrase)] or [1.0])  # the rarest word of the phrase sets its weight
                miss.append((weight, phrase))  # kept for the report
                score += weight  # rarer phrases weigh more
        if not miss:  # every phrase is answered somewhere
            continue
        key = b.lower()  # repeated badges are listed once
        if key in seen:
            continue
        seen.add(key)
        toks = re.findall(r"[A-Za-z']+", b)  # its words
        funcs = sum(1 for t in toks if t.lower() in FUNC)  # function words
        listy = b.count(",") >= 2 and funcs <= 1  # a stack of tool names, not a claim
        shape = (0.4 if listy else 1.5 if funcs >= 2 or len(toks) <= 6 else 1.0)  # sentences and badges are claims; lists are not
        score = score / max(1, len(miss)) * min(3, len(miss)) * shape / (1 + 0.03 * max(0, len(toks) - 15))  # long body text weighs less
        top = [ph for _, ph in sorted(miss, key=lambda x: -x[0])][:6]  # the rarest phrases first: they say most about what is unanswered
        score *= 2.0 if other else 1.0  # two numbers for one thing is a question waiting to be asked
        out.append({"page": page, "title": titles.get(page, ""), "text": b, "missing": top, "scenes_say": other[:2], "score": round(score, 2)})
    out.sort(key=lambda r: -r["score"])  # the most notable first
    return out[:limit] if limit else out


def judge_claims(claims, ask, keep=CLAIMS_JUDGED):
    """One model call: which of the candidate lines would an interviewer ask about? Returns (the chosen claims in the
    judge's order, why it stopped or '')."""
    lines = "\n".join(f"{k}\tp{c['page']}\t{c['text'][:160]}\t[{'; '.join(m[:30] for m in c['missing'][:3])}]"
                      + (f"\t(the answers say: {'; '.join(c['scenes_say'])})" if c.get("scenes_say") else "") for k, c in enumerate(claims))  # one short line each
    try:
        res = ask(CLAIMS_JUDGE.format(keep=keep, lines=lines), [str(k) for k in range(len(claims))])  # one call for every candidate
    except Exception as e:  # noqa: BLE001  no model or a bad answer: the rule's order stands
        return claims[:keep], str(e)
    picked = []  # in the judge's order
    for v in (res or {}).get("picks", []) if isinstance(res, dict) else []:  # each pick
        try:
            k = int(str(v.get("n") if isinstance(v, dict) else v).strip())  # the candidate's number
        except ValueError:  # not a number
            continue
        if 0 <= k < len(claims) and claims[k] not in picked:  # a real candidate, once
            c = dict(claims[k]); c["why"] = str(v.get("why", "")) if isinstance(v, dict) else ""  # with the judge's reason
            picked.append(c)
    return (picked[:keep] or claims[:keep]), ""


# ---------- consistency ----------

def risk(en, top_doc):
    """How likely a scene is to disagree with the documents: its scope limits, first-person claims, dates and titles,
    weighted by how closely it touches the documents (top_doc: its best paragraph's shared rarity)."""
    h, c = len(HEDGE.findall(en)), len(CLAIM.findall(en))  # scope limits and claims
    d, t = len(DATE.findall(en)), len(TITLE.findall(en))  # dates and titles
    signal = 1.0 * min(h, 4) + 1.0 * min(c, 4) + 0.6 * min(d, 4) + 0.8 * min(t, 2)  # each kind counts up to a point
    return round(signal * (0.5 + min(top_doc, 40) / 40), 2)  # a scene far from the documents matters less


def plan_consistency(job, answers, documents, ids=None):
    """[(risk, item, my lines, [(doc, paragraph)], [(scene id, sentence)])] of the scenes that touch the documents, the
    riskiest first."""
    chunks = {(d, i): c for d, (_, cs) in documents.items() for i, c in enumerate(cs)}  # every paragraph of every document
    sents = {}  # (scene id, k) -> sentence of a scene, for comparing scenes with each other
    for sid, (it, mine, _) in answers.items():  # every scene
        for k, s in enumerate(re.split(r"(?<=[.!?])\s+", mine)):  # its sentences
            if len(s.split()) >= 5:  # a fragment says too little to compare
                sents[(sid, k)] = s
    docs_idx = Related({k: v for k, v in chunks.items()})  # the documents' paragraphs
    scene_idx = Related(sents)  # the scenes' sentences
    want = {i.strip() for i in ids.split(",")} if ids else None  # --ids
    out = []  # results
    for sid, (it, mine, _) in answers.items():  # file order
        if want is not None and sid not in want:  # not asked for
            continue
        if not mine:  # an interviewer-only scene claims nothing
            continue
        rel = docs_idx.best(mine, K_RESUME + K_PORTFOLIO + 6, min_shared=3)  # the closest paragraphs of both documents
        res = [k for k, _ in rel if k[0] == "resume"][:K_RESUME]  # the resume's
        por = [k for k, _ in rel if k[0] == "portfolio"][:K_PORTFOLIO]  # the portfolio's
        if not res and not por:  # a scene that touches no document needs no call
            continue
        others = []  # other scenes' sentences on the same facts
        for s in re.split(r"(?<=[.!?])\s+", mine):  # each sentence of this scene
            if DATE.search(s) or HEDGE.search(s) or CLAIM.search(s) or TITLE.search(s) or re.search(r"\d", s):  # a sentence that states a fact
                for key, sc in scene_idx.best(s, 2, skip={k for k in sents if k[0] == sid}, min_shared=3, min_score=12):  # the closest sentences elsewhere
                    others.append((sc, key))
        seen, cross = set(), []  # one sentence each, the closest first
        for sc, key in sorted(others, key=lambda x: -x[0]):
            if key not in seen:
                seen.add(key); cross.append((key[0], sents[key]))
        top = rel[0][1] if rel else 0.0  # how closely it touches the documents
        out.append((risk(mine, top), it, mine, [(k[0], chunks[k]) for k in res + por], cross[:K_SCENES]))
    out.sort(key=lambda x: -x[0])  # the riskiest first
    return out


def consistency_flags(job, scenes, documents, ask, batch=BATCH, answers=None, calls=0, ids=None):
    """(kept flags, dropped flags, scenes sent, why it stopped or '', scenes that touch the documents).

    scenes is the list check.load_scenes gives (kept for older callers); the work list comes from
    plan_consistency, the riskiest scenes first, and with calls > 0 only that many batches are sent."""
    import llm  # LLMUnavailable
    answers = answers or scene_answers(job)  # my lines of every scene
    allowed = {it["id"] for it, _, _ in scenes}  # the scenes the caller chose (--ids, --limit)
    work = [w for w in plan_consistency(job, {k: v for k, v in answers.items() if k in allowed}, documents, ids) ]  # riskiest first
    size = BATCH_BUDGET if calls else batch  # fuller calls when the budget is fixed
    touching = len(work)  # every scene that touches the documents
    if calls:  # only the riskiest batches
        work = work[:calls * size]
    texts = {k: v[1] for k, v in answers.items()}  # every scene's lines, for quotes from another scene
    kept, dropped, sent, why = [], [], 0, ""  # results
    for i in range(0, len(work), size):  # one model call per batch of scenes
        part = work[i:i + size]  # a few scenes per call
        blocks = []  # one prompt block per scene
        for r, it, en, chunks, cross in part:  # each scene of the batch
            ctx = "\n".join(f"  [{d}] {c}" for d, c in chunks)  # the closest document text
            other = "\n".join(f"  [scene {s}] {t}" for s, t in cross)  # what other scenes say on the same facts
            blocks.append(f"### Scene {it['id']}\nAnswer: {en[:MAX_SCENE_CHARS]}\nDocuments:\n{ctx}" + (f"\nOther scenes:\n{other}" if other else ""))
        try:
            res = ask(PROMPT.format(scenes="\n\n".join(blocks)), [it["id"] for _, it, _, _, _ in part])  # the batch's ids go along too
        except llm.LLMUnavailable as e:  # no model: stop, keep what was found
            why = str(e)  # reported by main()
            break  # no point asking again
        except ValueError as e:  # the answer never had the right form: count the batch as unchecked
            why = str(e)  # remembered; the next batch still runs
            continue
        sent += len(part)  # scenes that really got an answer
        by_id = {it["id"]: en for _, it, en, _, _ in part}  # the scenes of this batch
        for f in (res or {}).get("flags", []) if isinstance(res, dict) else []:  # each flag raised; none when the answer is not a dict
            sid, doc = str(f.get("id", "")), str(f.get("doc", ""))  # which scene and which document the flag names
            en = by_id.get(sid, "")  # the scene's answer; empty when the id is not in this batch
            m = re.match(r"scene\s*:?\s*(\S+)", doc, re.I)  # another scene named as the other side
            src = texts.get(m.group(1).strip("[]"), "") if m else documents.get(doc, ("", []))[0]  # that scene's lines, or the document's text
            # kept only when the scene is known and both quotes are found in the normalized texts
            ok = bool(en) and norm(f.get("scene_quote")) and norm(f.get("scene_quote")) in norm(en) \
                and norm(f.get("doc_quote")) and norm(f.get("doc_quote")) in norm(src)  # both quotes are really there
            (kept if ok else dropped).append(f)  # verified flags kept, the others counted as dropped
    return kept, dropped, sent, why, touching


CACHE_KEEP = 400  # cached model answers kept; the oldest beyond this are removed


def model_ask(backend, task="interview-consistency", schema=SCHEMA, required=("flags",), cache=None):
    """The real model through src/llm.py run(). With cache (a folder), each answer is kept under a hash of the backend,
    the task and the prompt, so a rerun over the same scenes asks the model nothing again."""
    import hashlib  # the cache key
    import llm  # the one door to a model

    def ask(prompt, ids):  # the same signature as a test stand-in; the ids are not needed here
        name = llm.chosen(backend)[0]  # the backend that would answer
        key = hashlib.sha256("\n".join((name, task, SYSTEM, prompt)).encode("utf-8")).hexdigest()[:20]  # what the answer depends on
        f = pathlib.Path(cache) / f"{task}-{key}.json" if cache else None  # where it is kept
        if f is not None and f.is_file():  # asked before: the same answer, no call
            return json.loads(f.read_text(encoding="utf-8"))
        # the answer as JSON; a missing key makes llm.run ask again
        out = llm.run(task, prompt, system=SYSTEM, want_json=True, required=required, backend=backend,
                      timeout=600, schema=schema)  # a full batch takes longer than a short call
        if f is not None:  # kept for the next run
            f.parent.mkdir(parents=True, exist_ok=True)  # created on first use
            f.write_text(json.dumps(out, ensure_ascii=False) + "\n", encoding="utf-8")  # the answer as JSON
            old = sorted(f.parent.glob("*.json"), key=lambda x: x.stat().st_mtime)  # oldest first
            for x in old[:-CACHE_KEEP] if len(old) > CACHE_KEEP else []:  # the folder stays bounded
                x.unlink(missing_ok=True)
        return out
    return ask  # called once per batch


# ---------- the answer key ----------

KEY_STOP = {"versus", "vs", "page", "on", "the", "of", "by", "a", "an"}  # words of a key's description that name no fact
# words every description and every flag use, which therefore tell nothing about which problem a flag is
TOPIC_STOP = {"resume", "portfolio", "scene", "answer", "say", "says", "said", "document", "candidate", "while", "but", "versus",
              "per", "other", "another", "differ", "different", "flag", "claim", "date", "title", "scope", "number"}


def _words(s):  # a key description and an audit finding are compared on these
    """Stemmed content words, with number-and-unit marks dropped ("500+" -> "500")."""
    return [w for w in T.words(re.sub(r"(\d)\+", r"\1", s or "")) if w not in KEY_STOP]


def score_key(key, rows, claims, kept):
    """Recall and precision of the audit against an answer key, per part and overall."""
    out = {"parts": {}, "found": [], "missed": []}  # per part, and the key items found or missed
    # coverage: a key line is found when the audit rates the same posting line weak or none
    flagged = [r for r in rows if r[3] != "strong"]  # the lines the audit flags
    hits = 0  # flagged lines that are in the key
    gaps = key.get("coverage_gaps") or []  # the key's lines
    used = set()  # flagged lines matched to a key line
    for g in gaps:  # each key line
        want = set(_words(g.get("posting_line", "")))  # its words
        match = [r for r in rows if want and len(want & set(_words(r[2]))) / len(want) >= 0.6]  # the same posting line
        ok = any(r[3] != "strong" for r in match)  # rated weak or none
        (out["found"] if ok else out["missed"]).append({"part": "coverage", "item": g.get("posting_line"),
                                                        "audit": [(r[2][:80], r[3]) for r in match]})
        used |= {r[0] for r in match if r[3] != "strong"}  # this key line accounts for those flags
    hits = sum(1 for r in flagged if r[0] in used)  # flagged lines the key holds
    out["parts"]["coverage"] = {"key": len(gaps), "found": sum(1 for f in out["found"] if f["part"] == "coverage"),
                                "flagged": len(flagged), "flagged_in_key": hits}
    # contradictions: a key item is found when a kept flag is on the same scene and is about the same problem: the flag's
    # quotes and reason share two content words with the key's description. Which document the flag quotes does not
    # decide it (a person may file under the resume what the model shows from the portfolio). "same scene" alone also
    # counts flags about another problem of that scene; that looser count is reported beside it
    topic = lambda f: set(_words(" ".join(str(f.get(x, "")) for x in ("scene_quote", "doc_quote", "why")))) - TOPIC_STOP  # noqa: E731  what a flag is about
    matched = set()  # kept flags that match some key item
    for part, doc in (("resume_contradictions", "resume"), ("portfolio_contradictions", "portfolio")):
        items = key.get(part) or []  # the key's items
        loose = 0  # key items with some flag on the same scene
        for k in items:  # each one
            same = [f for f in kept if str(f.get("id")) == str(k.get("id"))]  # flags on the same scene, against any document or scene (the topic decides)
            want = set(_words(str(k.get("what", "")))) - TOPIC_STOP  # the key's words for the problem
            fl = [f for f in same if len(want & topic(f)) >= 2]  # flags about the same problem
            loose += bool(same)  # counted either way in the looser number
            matched |= {id(f) for f in fl}  # these flags are in the key
            (out["found"] if fl else out["missed"]).append({"part": part, "item": f"{k.get('id')}: {k.get('what')}", "audit": [f"{f.get('kind')}: {f.get('why')}" for f in fl],
                                                            "same_scene": [f"{f.get('kind')}: {f.get('why')}" for f in same if f not in fl]})
        out["parts"][part] = {"key": len(items), "found": sum(1 for f in out["found"] if f["part"] == part), "same_scene": loose}
    in_key = len(matched)  # kept flags about a problem the key holds
    out["parts"]["consistency"] = {"flags": len(kept), "flags_in_key": in_key}
    # portfolio claims: a key phrase is found when a listed claim holds most of its words
    phrases = key.get("portfolio_claims_without_answer") or []  # the key's phrases
    claim_hits = set()  # listed claims that match some key phrase
    for ph in phrases:  # each phrase
        want = set(_words(ph))  # its words
        names = set(_words(" ".join(re.findall(r"\b(?:[A-Z][A-Za-z0-9]*|\d[\d,.]*)\b", ph))))  # its names and numbers ("Kafka", "AWS", "500")
        # claims that hold half of the words or more, and one of the names when the phrase has any ("Kafka events" is not "billing events")
        need = min(2, len(want))  # a phrase of two words or more needs two of them ("deploy platform" is not "Platform team")
        m = [k for k, c in enumerate(claims) if want and len(want & set(_words(c["text"]))) >= need
             and len(want & set(_words(c["text"]))) / len(want) >= 0.5 and (not names or names & set(_words(c["text"])))]
        (out["found"] if m else out["missed"]).append({"part": "portfolio_claims", "item": ph, "audit": [claims[k]["text"][:100] for k in m[:2]]})
        claim_hits |= set(m)  # these claims are in the key
    out["parts"]["portfolio_claims"] = {"key": len(phrases), "found": sum(1 for f in out["found"] if f["part"] == "portfolio_claims"),
                                        "listed": len(claims), "listed_in_key": len(claim_hits)}
    total = sum(p.get("key", 0) for p in out["parts"].values())  # every key item
    found = len(out["found"])  # found ones
    findings = len(flagged) + len(kept) + len(claims)  # everything the audit reported
    in_key_all = hits + in_key + len(claim_hits)  # of which the key holds
    out["recall"] = {"found": found, "key": total, "share": round(found / total, 3) if total else 0}  # how much of the key the audit found
    out["precision"] = {"in_key": in_key_all, "findings": findings, "share": round(in_key_all / findings, 3) if findings else 0}  # how much of the audit the key holds
    return out


# ---------- the report ----------

def write_md(rows, kept, dropped, path, claims=None, verdicts=None, scored=None):
    """A readable audit report."""
    # the title, then the header of the coverage table
    out = ["# Interview kit audit", "", "## Posting coverage", "", "| line | rating | covered by | posting line |", "|---|---|---|---|"]
    for n, sec, line, rating, by in rows:  # one table row per posting line
        # the covering items with their shares, or a dash; pipes in the line swapped so the table holds
        out.append(f"| {n} | {rating} | {', '.join(f'{i} ({s})' for i, s in by) or '-'} | {line.replace('|', '/')} |")
    if verdicts:  # the judge's reasons
        out += ["", "The judge's reasons:", ""] + [f"- line {v.get('n')}: {v.get('verdict')} ({v.get('id') or '-'}) {v.get('why')}" for v in verdicts]
    out += ["", "## Portfolio lines no scene answers", ""]  # the second section
    if claims:  # the unanswered portfolio lines
        out += ["| page | line | phrases no scene says |", "|---|---|---|"]
        out += [f"| {c['page']} | {c['text'][:160].replace('|', '/')} | {', '.join(c['missing']).replace('|', '/')} |" for c in claims]
    else:
        out.append("None found.")  # nothing unanswered
    out += ["", "## Consistency with the submitted documents", ""]  # the third section
    if kept:  # a table only when some flags were verified
        out += ["| scene | kind | scene says | document says | why |", "|---|---|---|---|---|"]  # the table header
        # one row per kept flag: both quotes side by side, with the reason
        out += [f"| {f.get('id')} | {f.get('kind')} | {f.get('scene_quote')} | [{f.get('doc')}] {f.get('doc_quote')} | {f.get('why')} |" for f in kept]
    else:
        out.append("No verified flags.")  # a plain line in place of an empty table
    if dropped:  # say how many flags were thrown away
        # the count only; the dropped flags themselves stay in audit.json
        out += ["", f"{len(dropped)} flags were dropped because a quote was not found in the texts."]
    if scored:  # the score against an answer key
        r, p = scored["recall"], scored["precision"]  # the two headline numbers
        out += ["", "## Against the answer key", "", f"Recall {r['found']}/{r['key']} ({r['share']:.0%}), precision {p['in_key']}/{p['findings']} ({p['share']:.0%}).", ""]
        out += [f"- {k}: {json.dumps(v)}" for k, v in scored["parts"].items()]  # per part
        out += ["", "Missed:", ""] + [f"- [{m['part']}] {m['item']}" for m in scored["missed"]]  # what the audit did not find
    path.write_text("\n".join(out) + "\n", encoding="utf-8")  # the report ends with a newline


def main(job, out=None, consistency=False, backend=None, ids=None, limit=0, ask=None, calls=0, judge=False, key=None,
         judge_ask=None):
    """Run the audits, print the coverage table and summaries, write audit.json and audit.md."""
    items, alts = corpus.load(job)  # the kit
    rows = coverage(job, items, alts)  # the posting coverage, no model
    answers = scene_answers(job)  # my lines of every scene
    cache = job.out_path(out) / "model_cache"  # the model's answers, reused by a rerun over the same scenes
    verdicts, judge_why = [], ""  # the judge's word on each line
    if judge:  # one call checks the rule's ratings
        rows, verdicts, judge_why = judge_coverage(rows, answers, items, judge_ask or model_ask(backend, "interview-coverage-judge", JUDGE_SCHEMA, ("lines",), cache))
        if judge_why:  # the model did not answer: the rule's ratings stand
            print(i18n.t("audit_judge_skipped", why=judge_why))
    for n, sec, line, rating, by in rows:  # print the coverage table line by line
        # the rating, the line, and the covering items or a dash
        print(i18n.t("audit_cover_line", rating=rating, line=line, items=", ".join(f"{i} {s}" for i, s in by) or "-"))
    count = {k: sum(1 for r in rows if r[3] == k) for k in ("strong", "weak", "none")}  # how many lines got each rating
    print(i18n.t("audit_cover_summary", n=len(rows), **count))  # the coverage summary line
    claims = portfolio_claims(job, answers, limit=JUDGE_POOL if judge else CLAIMS)  # portfolio lines no scene answers, no model
    if judge and claims:  # one call picks the lines an interviewer would ask about
        claims, why = judge_claims(claims, judge_ask or model_ask(backend, "interview-claims-judge", CLAIMS_SCHEMA, ("picks",), cache))
        if why:  # the model did not answer: the rule's order stands
            print(i18n.t("audit_judge_skipped", why=why))
    print(i18n.t("audit_claims_summary", n=len(claims)))  # how many were listed
    kept, dropped, sent, considered = [], [], 0, 0  # consistency results
    if consistency:  # the model-assisted part
        documents = docs(job)  # what was sent
        if not documents:  # nothing to compare against
            print(i18n.t("audit_consist_skipped", why="no submitted resume or portfolio text"))  # say why it was skipped
        else:
            _, scenes = check.load_scenes(job, ids=ids)  # the scenes to compare
            if limit:  # --limit keeps only the first few scenes
                scenes = scenes[:limit]
            # the model compares; a test may pass its own ask
            kept, dropped, sent, why, considered = consistency_flags(job, scenes, documents, ask or model_ask(backend, cache=cache), answers=answers, calls=calls)
            if why and not sent:  # the model never answered, so there is nothing to report
                print(i18n.t("audit_consist_skipped", why=why))  # say why
            else:
                for f in kept:  # each verified flag
                    # the scene quote against the document quote, with the reason
                    print(f"  {f.get('id')} [{f.get('kind')}] \"{f.get('scene_quote')}\" <> [{f.get('doc')}] \"{f.get('doc_quote')}\": {f.get('why')}")
                # how many scenes were sent, and how many flags were raised, kept and dropped
                print(i18n.t("audit_consist_summary", scenes=sent, flags=len(kept) + len(dropped), kept=len(kept), dropped=len(dropped)))
                if calls and considered > sent:  # the budget left scenes unchecked: say how many
                    print(i18n.t("audit_consist_budget", sent=sent, considered=considered, calls=calls))
    d = job.out_dir(out)  # the output folder
    scored = None  # the score against an answer key
    if key:  # --key: a person's own findings
        kp = pathlib.Path(key).expanduser()  # the key file
        if not kp.is_file():  # a key named on purpose must exist
            raise SystemExit(f"no answer key: {kp}")
        scored = score_key(json.loads(kp.read_text(encoding="utf-8")), rows, claims, kept)  # recall and precision
        (d / "recall.json").write_text(json.dumps(scored, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # the details
        r, p = scored["recall"], scored["precision"]  # the headline numbers
        print(i18n.t("audit_key_summary", found=r["found"], total=r["key"], recall=round(r["share"] * 100), in_key=p["in_key"], findings=p["findings"], precision=round(p["share"] * 100)))
    # the full record as readable UTF-8 JSON: coverage rows, the claims, then the consistency results
    (d / "audit.json").write_text(json.dumps({
        "coverage": [{"line": n, "section": s, "text": ln, "rating": r, "covered_by": [[i, x] for i, x in by]} for n, s, ln, r, by in rows],
        "judge": verdicts, "portfolio_claims": claims,
        "consistency": {"scenes": sent, "considered": considered, "calls": calls, "kept": kept, "dropped": dropped}}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_md(rows, kept, dropped, d / "audit.md", claims, verdicts, scored)  # the same as a readable report
    print(i18n.t("audit_written", out=d / "audit.md"))  # where the report went
    return 0
