"""Mock interview practice: questions from the question map, feedback on each answer, and sessions kept on this PC.

The page asks a question; you answer aloud or type; only after you finish does it show the feedback and your own
scene. Nothing listens unless you press record, and nothing suggests what to say while you answer.

Questions. The question map (plan.py) holds what an interviewer has in front of them: what the earlier rounds asked,
posting lines, resume lines, portfolio pages, behavioral and company questions. Every topic that a scene covers becomes
one question. The fixed list asks it with the scene's own first interviewer line (a question an earlier round asked, in
the words it was asked in), and the scene's later interviewer lines are its follow-ups. With an agent (src/llm.py run()),
one call per session phrases the questions as an interviewer would (never the ones asked before), and one call per answer
asks a follow-up about what you actually said.

Feedback, without a model:
  - length: words (and seconds, when spoken) against the scene's answer for that turn;
  - pauses: silences of LONG_PAUSE seconds or more inside a spoken answer, from the page's microphone levels, or from
    the speech model's word times when one is installed;
  - fillers: um, uh, you know and the rest of the style pack's list;
  - departures: a number changed against the same unit in the scene, numbers and names found neither in the scene nor
    in the evidence, and claims stronger than the scene's ("I led" where the scene says the team did);
  - the key phrase: the scene's ==key phrase==, landed or missed, when it belongs to the turn.
With an agent, the follow-up call also lists departures; each is kept only when both of its quotes are found.

Sessions are kept in <out>/practice/<id>.json, one file per session with every turn and its summary; only the newest
KEEP files are kept.
"""
import datetime  # session ids and times
import json  # session files
import pathlib  # paths
import random  # the order of the questions
import re  # text rules
import secrets  # the random part of a session id
import threading  # one plan build at a time

from interview import check, corpus, i18n  # scenes and grounding helpers; items; messages
from interview import text as T  # words and synonyms
from interview.job import read_text  # material files

HERE = pathlib.Path(__file__).resolve().parent  # src/interview
RATE_WPS = 2.3  # words per second of calm interview English (about 140 words a minute): turns a word target into seconds
LONG_PAUSE = 2.5  # seconds of silence inside an answer that count as a long pause
SHORT, LONG = 0.6, 1.5  # an answer under 60 percent or over 150 percent of the scene's length is flagged
DEFAULT_WORDS = 70  # the target when a question has no scene: two to four sentences of 18 to 35 words
KEY_SHARE = 0.6  # share of the key phrase's content words an answer needs for the phrase to count as landed
KEEP = 500  # session files kept; the oldest beyond this are removed, so the folder never grows without end
MAX_TEXT = 6000  # longest answer text accepted, in characters (a ten-minute answer is far shorter)
KINDS = ("asked", "posting", "resume", "portfolio", "behavioral", "company", "scenario", "technical", "opening", "term")  # the map's kinds
DEFAULT_KINDS = ("asked", "posting", "resume", "portfolio", "behavioral", "company", "scenario", "technical")  # what an interviewer asks; terms and openings are opt-in
SID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")  # a session id: date, time and four hex digits (nothing else may name a file)
# The one call per session that phrases the questions, and the one call per answer that asks a follow-up
# The interview is in English, whatever language the agent usually answers its user in, so both prompts say so
PHRASE_SYSTEM = ("You are a job interviewer. Rephrase each question the way you would ask it aloud: one short sentence of "
                 "plain spoken English, keeping every name. Write every question in English. Return only JSON.")
FOLLOW_SYSTEM = ("You are a job interviewer in a practice interview held in English. Ask one natural follow-up question, in "
                 "English, about what the candidate actually said, and list facts in the answer that differ from the "
                 "candidate's own notes. Quote exactly. Return only JSON.")
FOLLOW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["followup", "departures"],  # for backends that take a schema
                 "properties": {"followup": {"type": "string"},  # the next question
                                "departures": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                          "required": ["said", "fact", "why"],
                                                                          "properties": {k: {"type": "string"} for k in ("said", "fact", "why")}}}}}

# ---------- spoken text ----------

NUM_WORDS = {w: i for i, w in enumerate(("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                          "fourteen fifteen sixteen seventeen eighteen nineteen").split())}  # 0 to 19
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i >= 2}  # 20 to 90
SCALE = {"hundred": 100, "thousand": 1000, "million": 1000000}  # the multipliers a spoken number may carry
NUMBER_RUN = re.compile(r"\b(?:(?:%s)(?:[\s-]+(?:and[\s-]+)?)?)+\b" % "|".join(list(NUM_WORDS) + list(TENS) + list(SCALE)), re.I)  # a run of number words


def _run_value(run):  # one run of number words, such as "two hundred and twenty five"
    """The value of a run of number words, or None when it is not a number ("and" alone)."""
    total, cur, seen = 0, 0, False  # the finished part, the part being built, whether any number word was read
    for w in re.findall(r"[a-z]+", run.lower()):  # each word of the run
        if w in NUM_WORDS:  # a unit or teen
            cur += NUM_WORDS[w]; seen = True  # added to the part being built
        elif w in TENS:  # a ten
            cur += TENS[w]; seen = True  # added the same way
        elif w in SCALE:  # hundred, thousand, million
            cur = max(cur, 1) * SCALE[w]; seen = True  # "hundred" alone means one hundred
            if SCALE[w] > 100:  # thousand and million close a group
                total, cur = total + cur, 0  # the group is finished
    return total + cur if seen else None  # "and" alone is no number


def digits(text):
    """Number words written as digits ("four minutes" -> "4 minutes"), so scenes and answers compare the same way."""
    def swap(m):  # one run of number words
        v = _run_value(m.group(0))  # its value
        tail = " " if m.group(0).endswith((" ", "-")) else ""  # keep the space the run swallowed
        return f"{v}{tail}" if v is not None else m.group(0)  # unchanged when it was not a number
    return NUMBER_RUN.sub(swap, text or "")  # every run in the text


def spoken(text):
    """What a line says aloud: no speech marks, no Korean stage notes, one space."""
    s = re.sub(r"\([^()]*[가-힣][^()]*\)", " ", text or "")  # Korean stage notes such as (웃으며) are not spoken
    s = re.sub(r"\s/{1,2}\s", " ", s)  # breath and sentence marks
    s = re.sub(r"\s/{1,2}\s*$", " ", s)  # a mark at the very end
    s = s.replace("**", "").replace("==", "").replace("`", "")  # stress, key phrase and code marks
    return re.sub(r"\s+", " ", s).strip()  # one space


def count_words(text):
    """Words in a spoken text (digits count as words; marks do not)."""
    return len(re.findall(r"[A-Za-z0-9가-힣]+(?:['’.\-][A-Za-z0-9]+)*", spoken(text)))  # contractions and 3.5 stay one word


def key_phrases(text):
    """The ==key phrases== of a line, without their marks."""
    return [spoken(p) for p in re.findall(r"==(.+?)==", text or "")]  # the text between each pair of marks


# ---------- scenes ----------

def turns(dialogue, title=""):
    """[{q, q_ko, a, a_ko, raw}] of a scene: each interviewer line with my lines up to the next interviewer line.
    raw keeps my lines with their marks, for the key phrase."""
    out, cur, last = [], None, ""  # turns; the turn being built; the speaker of the last English line
    for who, txt, _ in dialogue:  # (speaker, text, line number) in file order
        if who == "면접관":  # a new question opens a turn
            cur = {"q": spoken(txt), "q_ko": "", "a": "", "a_ko": "", "raw": ""}  # its question, answers to come
            out.append(cur)  # kept in order
        elif who == "나":  # my line belongs to the open turn
            if cur is None:  # a scene that opens with my line: its title is the question
                cur = {"q": title, "q_ko": "", "a": "", "a_ko": "", "raw": ""}  # a turn with the title as its question
                out.append(cur)  # kept in order
            cur["a"] = (cur["a"] + " " + spoken(txt)).strip()  # several of my lines join into one answer
            cur["raw"] = (cur["raw"] + " " + txt).strip()  # the marked text, for the key phrase
        elif who == "해석" and cur is not None:  # a translation of the line above it
            key = "q_ko" if last == "면접관" else "a_ko"  # it translates whoever spoke last
            cur[key] = (cur[key] + " " + spoken(txt)).strip()  # joined like the English
        if who in ("면접관", "나"):  # remember who spoke, for the next 해석
            last = who
    return [t for t in out if t["q"] or t["a"]]  # empty turns say nothing


# ---------- the rules ----------

def fillers(text, pack):
    """[(filler, count)] of the fillers in an answer, most frequent first."""
    iv = (pack or {}).get("interview", {})  # the merged interview rules
    s = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "  # padded, so every word has a space or comma on both sides
    found = {}  # filler -> count
    for f in iv.get("fillers") or []:  # whole words or phrases
        f = f.lower()  # the list is matched without case
        if f == "like":  # "like" is only a filler between commas ("it was, like, slow")
            n = len(re.findall(r",\s*like\s*,|\blike,\s", s))
        elif f in ("kind of", "sort of"):  # "what kind of" is a real phrase, "it was kind of slow" is a filler
            n = len(re.findall(r"(?<!what )(?<!which )(?<!this )(?<!that )(?<!the )(?<!a )(?<!any )(?<!some )(?<!every )\b%s\b" % f, s))
        elif re.match(r"[가-힣]", f):  # Korean fillers stand alone between spaces or commas
            n = len(re.findall(r"(?<=[\s,])%s(?=[\s,.])" % re.escape(f), s))
        else:  # um, uh, you know and the rest: whole words, a long "ummm" too
            n = len(re.findall(r"\b%s\b" % re.sub(r"([a-z])$", r"\1+", re.escape(f)), s))
        if n:  # only the fillers that were used
            found[f] = found.get(f, 0) + n  # a filler listed twice adds up
    return sorted(found.items(), key=lambda x: -x[1])  # most frequent first


def unit_pairs(text):
    """{(number, unit word)} of a text: each number with the content word after it ("4 minutes" -> ("4", "minute"))."""
    out = set()  # pairs
    for m in re.finditer(r"(\d+(?:[.,]\d+)*)\s*(%|[A-Za-z]+(?:-[A-Za-z]+)?)?", digits(spoken(text))):  # a number and the word after it
        unit = (m.group(2) or "").lower()  # the unit word, if any
        if unit in ("to", "or", "and", "of", "a", "an", "the", "in", "on", "at", "by", "for", "from", "percent"):  # not a unit
            unit = "%" if unit == "percent" else ""  # percent is the one word that is a unit
        out.add((m.group(1).replace(",", ""), T.stem_en(unit) if unit not in ("", "%") else unit))  # 2,000 and 2000 meet
    return out


CLAIM = re.compile(r"\bI(?:'ve| have| had)?\s+(?:\w+\s+){0,2}?(led|founded|built|designed|architected|owned|created|ported|"
                   r"drove|ran|launched|started|wrote|developed|implemented|managed|migrated|automated)\b", re.I)  # "I <strong verb>"
TEAM = re.compile(r"\b(we|our team|the team|team's|my colleagues?|a colleague|colleague's|helped|supported|proposed|"
                  r"took part|contributed|already existed|was there)\b", re.I)  # the scene giving the work to others or to a proposal


def claims(answer, scene_text):
    """[(said, note code)] of claims stronger than the scene's: "I <verb>" where the scene never says "I <verb>"."""
    out = []  # (the words said, the reason code)
    mine = {m.group(1).lower() for m in CLAIM.finditer(scene_text or "")}  # the strong verbs the scene itself uses with I
    team = bool(TEAM.search(scene_text or ""))  # does the scene give the work to the team, a colleague or a proposal
    for m in CLAIM.finditer(answer or ""):  # each strong claim in the answer
        verb = m.group(1).lower()  # the verb
        if verb not in mine:  # the scene does not say it in the first person
            out.append((m.group(0), "claim_team" if team else "claim_new"))  # stronger than the scene
    return out


def departures(answer, turn_answer, scene_text, pool):
    """[{kind, said, fact}] of the facts in an answer that the scene and the evidence do not hold.

    changed: the answer gives another number for a unit the scene uses ("5 minutes" where the scene says 4);
    number:  a number found neither in the scene nor in the evidence;
    name:    a name found neither in the scene nor in the evidence;
    claim:   "I <verb>" where the scene does not say it in the first person."""
    out = []  # the departures, in a stable order
    said = digits(spoken(answer))  # the answer with number words as digits
    scene_all = digits(spoken(scene_text))  # the whole scene the same way
    mine = unit_pairs(answer)  # (number, unit) pairs of the answer
    theirs = unit_pairs(turn_answer or scene_text)  # the turn's own pairs, or the scene's when the turn has none
    scene_nums = check.nums(scene_all)  # every number of the scene
    for n, unit in sorted(mine):  # each number the answer gives with its unit
        if not unit or (n, unit) in theirs:  # no unit to compare, or the same fact
            continue
        same = sorted(x for x, u in theirs if u == unit)  # the scene's numbers for this unit
        if same and n not in scene_nums:  # the scene has another number for this unit
            out.append({"kind": "changed", "said": f"{n} {unit}".strip(), "fact": ", ".join(f"{x} {unit}" for x in same)})
    known = {d["said"].split()[0] for d in out}  # numbers already reported as changed
    for n in sorted(check.nums(said)):  # each number of the answer
        if n in known or check.near(n, scene_nums):  # reported above, or in the scene (rounded counts too)
            continue
        if pool is not None and check.near(n, pool.nums):  # not in the scene, but in the evidence
            continue
        out.append({"kind": "number", "said": n, "fact": ""})  # in neither
    scene_low = scene_all.lower()  # for name lookups
    unknown = set()  # name-like words found neither in the scene nor in the evidence
    for name in check.strict_names(said):  # each name-like word of the answer
        low = name.lower()  # names are compared without case
        if low in scene_low or (pool is not None and (low in pool.tokens or low in pool.low)):  # in the scene or the evidence
            continue
        if re.fullmatch(r"\d+(?:[.,]\d+)*", name):  # a bare number is the number rule's business
            continue
        unknown.add(name)  # in neither
    for words in name_runs(said, unknown):  # neighbouring words of one name ("Zeta Corp") are reported once
        out.append({"kind": "name", "said": words, "fact": ""})
    for words, code in claims(spoken(answer), spoken(scene_text)):  # claims stronger than the scene
        out.append({"kind": "claim", "said": words, "fact": code})  # the code says whether the scene names others
    return out


def name_runs(text, names):
    """The unknown names in reading order, with neighbouring ones joined ("Zeta", "Corp" -> "Zeta Corp")."""
    runs, cur = [], []  # finished runs; the run being built
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9+\-_.']*", text or ""):  # the answer's words in order
        t = tok.strip(".'")  # as strict_names cuts them
        if t in names:  # part of a name
            cur.append(t)  # the run goes on
        elif cur:  # a run ends
            runs.append(" ".join(cur)); cur = []  # kept
    if cur:  # a run at the very end
        runs.append(" ".join(cur))
    return list(dict.fromkeys(runs))  # each name once, first use first


def key_check(raw_turn, answer, syn):
    """{phrase, landed} for the scene's key phrase in this turn, or None when the turn has none."""
    phrases = key_phrases(raw_turn)  # the turn's ==marked== phrases
    if not phrases:  # the key phrase belongs to another turn
        return None
    phrase = phrases[0]  # one key phrase per scene
    want = list(dict.fromkeys(T.words(digits(phrase))))  # its content words
    have = set(T.words(digits(spoken(answer))))  # the answer's content words
    if not want:  # a phrase of filler words only: compare the text itself
        return {"phrase": phrase, "landed": phrase.lower() in spoken(answer).lower(), "share": 0}
    hit = sum(1 for w in want if w in have or (syn.get(w, set()) & have))  # words said, or a synonym of them
    share = hit / len(want)  # the share of the phrase that was said
    return {"phrase": phrase, "landed": share >= KEY_SHARE, "share": round(share, 2)}


def long_pauses(pauses=None, words=None):
    """[(start, seconds)] of the long silences inside an answer: from the speech model's word times when there are
    any, else from the page's microphone levels."""
    if words:  # word times: the gaps between consecutive words
        gaps = []  # (start, length)
        for a, b in zip(words, words[1:]):  # each pair of neighbouring words
            gap = float(b.get("start", 0)) - float(a.get("end", 0))  # the silence between them
            if gap >= LONG_PAUSE:  # only long ones
                gaps.append((round(float(a.get("end", 0)), 1), round(gap, 1)))  # where it started and how long it was
        return gaps
    out = []  # from the page's measure
    for p in pauses or []:  # [start, length] pairs
        try:
            start, length = float(p[0]), float(p[1])  # numbers from JSON
        except (TypeError, ValueError, IndexError):  # a malformed pair is ignored
            continue
        if length >= LONG_PAUSE:  # the page sends every silence over a second; only long ones count
            out.append((round(start, 1), round(length, 1)))  # rounded for reading
    return out


def feedback(answer, turn, scene_text, pool, pack, syn, seconds=None, speech_seconds=None, pauses=None, words=None, spoken_answer=False):
    """The rule-made feedback on one answer to one turn (turn may be None for a question without a scene).
    spoken_answer says the answer was recorded, so its time is speaking time (a typed answer's time is typing time)."""
    said = spoken(answer)  # the answer without marks
    n = count_words(said)  # its words
    target = count_words(turn["a"]) if turn and turn.get("a") else DEFAULT_WORDS  # the scene's length, or the default
    ratio = round(n / target, 2) if target else 0  # how long it was against the scene
    verdict = "short" if ratio < SHORT else "long" if ratio > LONG else "ok"  # the length verdict
    talk = float(speech_seconds or seconds or 0) if spoken_answer else 0  # the time spent speaking (the page measures the voiced span)
    length = {"words": n, "target_words": target, "ratio": ratio, "verdict": verdict,  # the length part
              "seconds": round(float(seconds), 1) if seconds else None,  # the answer's time, when timed
              "target_seconds": round(target / RATE_WPS),  # the scene's length spoken at a calm pace
              "wpm": round(n / talk * 60) if talk > 1 and n else None}  # the speaking rate, when spoken
    gaps = long_pauses(pauses, words)  # the long silences
    used = fillers(said, pack)  # the fillers
    minutes = max(talk, n / RATE_WPS, 1) / 60  # the answer's length in minutes, for the filler rate
    return {
        "length": length,
        "pauses": {"long": gaps, "count": len(gaps), "longest": max((g for _, g in gaps), default=0),
                   "measured": bool(spoken_answer)},  # a typed answer has no pauses to measure
        "fillers": {"used": used, "count": sum(c for _, c in used), "per_min": round(sum(c for _, c in used) / minutes, 1)},
        "departures": departures(said, turn["a"] if turn else "", scene_text, pool),  # facts the scene and the evidence do not hold
        "key": key_check(turn["raw"], said, syn) if turn else None,  # the key phrase of this turn
    }


# ---------- the evidence ----------

class Evidence:  # built once, on the first answer
    """The job's materials as one grounding pool (check.Pool in its default mode), built in the background."""

    def __init__(self, job):  # the job whose materials ground the answers
        self.job, self.pool, self.lock = job, None, threading.Lock()  # built on first use

    def get(self):  # every answer needs it
        """The pool, built on first use (the materials include the submitted PDFs, so it takes a second or two)."""
        with self.lock:  # one build at a time
            if self.pool is None:  # first use
                self.pool = check.Pool(self.job, strict=False, checked_paths=set())  # every material file
            return self.pool


# ---------- sessions ----------

def now():  # one clock for the session files
    """The local time, to the second."""
    return datetime.datetime.now().replace(microsecond=0)


def summarize(s):
    """A session's summary from its turns."""
    done = [t for t in s.get("turns", []) if t.get("feedback")]  # the answered turns
    fb = [t["feedback"] for t in done]  # their feedback
    keyed = [f["key"] for f in fb if f.get("key")]  # turns that held the key phrase
    secs = [f["length"]["seconds"] for f in fb if f["length"].get("seconds")]  # timed answers
    ratios = [f["length"]["ratio"] for f in fb]  # length against the scene
    return {
        "answers": len(done),  # how many answers were given
        "questions": len({t["qid"] for t in done}),  # how many questions they answered
        "answer_seconds": round(sum(secs), 1),  # time spent answering
        "session_seconds": s.get("seconds", 0),  # the session's clock
        "ratio_mean": round(sum(ratios) / len(ratios), 2) if ratios else 0,  # mean length against the scene
        "short": sum(1 for f in fb if f["length"]["verdict"] == "short"),  # answers flagged short
        "long": sum(1 for f in fb if f["length"]["verdict"] == "long"),  # answers flagged long
        "long_pauses": sum(f["pauses"]["count"] for f in fb),  # long silences in all answers
        "fillers": sum(f["fillers"]["count"] for f in fb),  # fillers in all answers
        "departures": sum(len(f["departures"]) for f in fb) + sum(len(t.get("agent_departures") or []) for t in done),  # rule and agent departures
        "keys_landed": sum(1 for k in keyed if k["landed"]),  # key phrases landed
        "keys_asked": len(keyed),  # key phrases there were to land
    }


class Store:  # one per server
    """Session files in one folder: create, update, list, and keep only the newest KEEP."""

    def __init__(self, folder):  # <out>/practice
        self.dir = pathlib.Path(folder)  # created on the first session, not before
        self.lock = threading.Lock()  # one write at a time

    def path(self, sid):  # every read and write goes through here
        """The file of a session id; an id of any other shape names no file."""
        if not SID.match(str(sid or "")):  # nothing but a well-formed id may become a path
            raise KeyError(sid)
        return self.dir / f"{sid}.json"  # inside the folder, always

    def new(self, data):  # a new session
        """Save a new session and return it with its id."""
        t = now()  # its start
        data = dict(data, id=f"{t:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}", started=t.isoformat(), turns=[])  # id, start and no turns yet
        self.save(data)  # written at once, so a crash loses nothing
        self.prune()  # keep the folder bounded
        return data

    def load(self, sid):  # every update reads the file first
        """A saved session."""
        p = self.path(sid)  # raises on a bad id
        if not p.is_file():  # an unknown session
            raise KeyError(sid)
        return json.loads(p.read_text(encoding="utf-8"))  # the session as saved

    def save(self, data):  # after every change
        """Write a session (whole file, through a temporary name, so a reader never sees half a file)."""
        with self.lock:  # one writer at a time
            self.dir.mkdir(parents=True, exist_ok=True)  # created on first use
            p = self.path(data["id"])  # the session's file
            tmp = p.with_suffix(".tmp")  # written beside it first
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # readable UTF-8
            tmp.replace(p)  # an atomic swap

    def prune(self):  # after each new session
        """Remove the oldest session files beyond KEEP."""
        files = self._by_time()  # oldest first
        for f in files[:-KEEP] if len(files) > KEEP else []:  # everything older than the newest KEEP
            f.unlink(missing_ok=True)  # removed

    def _by_time(self):  # prune() and list() share the order
        """The session files, oldest first (two sessions can start in the same second, so the write time decides)."""
        files = list(self.dir.glob("*.json")) if self.dir.is_dir() else []  # every session file
        return sorted(files, key=lambda f: (f.stat().st_mtime_ns, f.name))  # by when it was last written

    def list(self, limit=50):  # the history on the page
        """The newest sessions' summaries, newest first."""
        out = []  # rows
        for f in self._by_time()[::-1][:limit]:  # newest first
            try:
                s = json.loads(f.read_text(encoding="utf-8"))  # the session
            except (OSError, ValueError):  # a damaged file is skipped, not fatal
                continue
            out.append({"id": s.get("id"), "started": s.get("started"), "interviewer": s.get("interviewer"),
                        "summary": s.get("summary") or summarize(s)})  # the saved summary, or one made now
        return out


# ---------- the practice service ----------

class Practice:  # one per server
    """The practice API behind the page: setup, start, answer, follow-up, end and history."""

    def __init__(self, job, out_dir, backend=None, ask=None, stt=None):  # ask and stt let tests stand in for the model and the speech model
        self.job = job  # the job being practised
        self.store = Store(pathlib.Path(out_dir) / "practice")  # sessions on this PC
        self.backend = backend  # the model backend; None: OFFEROWL_LLM or the default order
        self.ask = ask  # a stand-in for the model: ask(task, prompt, system) -> dict
        self.stt = stt  # a stand-in for the speech model, or None for transcribe.py
        self.evidence = Evidence(job)  # the grounding pool, built on the first answer
        self.lock = threading.Lock()  # one plan build at a time
        self._plan, self._stamp, self._scenes, self._agent = None, None, {}, None  # caches
        pack = check.style_pack(job)  # the built-in rules and the job's style pack
        self.pack = pack  # fillers come from here
        self.syn = T.synonyms(job.kit.get("synonyms"))  # synonym groups, for the key phrase

    # ----- what is available -----

    def agent(self):
        """The model backend practice would use, or '' when none is connected (decided once per server)."""
        if self._agent is None:  # first call
            if self.ask is not None:  # a test's stand-in counts as connected
                self._agent = "stand-in"
            else:
                import llm  # src/llm.py
                name, _ = llm.chosen(self.backend)  # the backend run() would pick
                ok = name in llm.available() and llm.available()[name][0] and name != "none"  # installed and not switched off
                self._agent = name if ok else ""  # '' means the fixed list
        return self._agent

    def setup(self):
        """What the page needs before a session: the interviewer, the speech model, the kinds, recent sessions."""
        from interview import transcribe  # the optional speech model
        stt_ok, stt_why = (True, "stand-in") if self.stt else transcribe.available()  # is a speech model installed
        return {"agent": self.agent(), "stt": stt_ok, "stt_why": stt_why, "kinds": list(KINDS), "default_kinds": list(DEFAULT_KINDS),
                "long_pause": LONG_PAUSE, "history": self.store.list(10)}

    # ----- the questions -----

    def scenes(self):
        """{id: (item, turns)} of every scene, rebuilt when a source file changes."""
        status = self.job.dir / "status.json"  # the rounds' questions (plan.asked_lines) are kept there
        stamp = corpus.stamp(self.job) + ([(str(status), status.stat().st_mtime_ns, status.stat().st_size)] if status.is_file() else [])  # sizes and change times of the sources
        with self.lock:  # one build at a time
            if stamp != self._stamp:  # a scene file changed, or the first call
                from interview import plan  # the question map
                _, sc = check.load_scenes(self.job, drafts=True)  # every scene with its dialogue, the agent's drafts too: a run that wrote only drafts can still be practised
                self._scenes = {it["id"]: (it, turns(d, it.get("ten") or it.get("tko") or "")) for it, d, _ in sc}  # turns per scene
                self._plan = plan.build(self.job)  # the map, with the scenes that cover each entry
                self._stamp = stamp  # up to date
            return self._scenes

    def questions(self, n=8, kinds=None, seed=None):
        """Up to n questions from the map, each with the scene that covers it; one per scene, kinds taken in turn."""
        scenes = self.scenes()  # also builds the map
        kinds = [k for k in (kinds or DEFAULT_KINDS) if k in KINDS]  # unknown kinds are ignored
        rnd = random.Random(seed)  # a seed makes a session repeatable (tests)
        pools = {k: [] for k in kinds}  # candidates per kind
        for r in self._plan or []:  # each entry of the map
            if r["kind"] not in pools:  # a kind that was not asked for
                continue
            ok = [i for i, _ in r["covered_by"] if i in scenes and scenes[i][1]]  # covering scenes with dialogue, best first
            real = [i for i in ok if scenes[i][0].get("role") != "terms"]  # a "what is X" entry answers a term, not a posting line
            sid = (real or (ok if r["kind"] == "term" else []) or [None])[0]  # the best real scene; a term entry only for a term question
            if sid:  # a question without a scene gets no feedback against a scene, so it is left out
                pools[r["kind"]].append((r, sid))  # a candidate
        for k in pools:  # shuffle within each kind
            rnd.shuffle(pools[k])
        out, used = [], set()  # questions; scenes already asked
        while len(out) < n and any(pools.values()):  # kinds in turn until enough or none left
            for k in kinds:  # one of each kind per round
                while pools[k]:  # the next unused scene of this kind
                    r, sid = pools[k].pop()  # a candidate
                    if sid in used:  # one question per scene
                        continue
                    used.add(sid)  # taken
                    it, tt = scenes[sid]  # the scene and its turns
                    asked = r["text"] if r["kind"] == "asked" else tt[0]["q"]  # a question an earlier round asked comes in the words it was asked in
                    out.append({"qid": f"q{len(out) + 1}", "kind": r["kind"], "topic": "" if r["kind"] == "asked" else r["text"], "source": r["source"],  # an asked question is its own topic
                                "scene": sid, "title": it.get("ten") or it.get("tko"), "ask": asked, "ask_ko": tt[0]["q_ko"],
                                "fixed": tt[0]["q"], "turns": len(tt), "draft": bool(it.get("draft"))})  # the scene's own line asks the rest; a draft says so on the page
                    break  # one per kind per round
                if len(out) >= n:  # enough
                    break
        return out

    def phrase(self, qs):
        """Let the agent phrase the questions in one call; returns why it did not, or ''."""
        lines = "\n".join(f'{q["qid"]}\t{q["kind"]}\t{q["topic"][:200]}\t{q["fixed"][:300]}' for q in qs)  # id, kind, topic, the scene's line
        company = self.job.kit.get("company") or ""  # the company's name, when the kit gives one
        company = company.get("en", "") if isinstance(company, dict) else str(company)  # its English name
        prompt = ("Each line is a question id, its kind, the topic from the candidate's documents or the job posting, and the "
                  f"candidate's own version of the question, separated by tabs.{' The company is ' + company + '.' if company else ''} "
                  "Rephrase each question as you would ask it in the interview. Return {\"<id>\": \"<question>\", ...} for every id.\n\n" + lines)
        try:
            out = self._ask("interview-practice-ask", prompt, PHRASE_SYSTEM, None)  # one call for the whole session
        except Exception as e:  # noqa: BLE001  no model, a timeout or a wrong answer: the fixed list stays
            return str(e)
        for q in qs:  # merge the phrasing back
            if q["kind"] == "asked":  # asked before, in these words: kept as they were
                continue
            v = out.get(q["qid"]) if isinstance(out, dict) else None  # this question's new wording
            if isinstance(v, str) and 3 <= len(v.split()) <= 60:  # a real question, not a fragment or an essay
                q["ask"] = v.strip()  # the agent's wording; the scene's line stays in "fixed"
        return ""

    def _ask(self, task, prompt, system, schema, required=()):  # the one door to the model in this file
        """A JSON answer from the model (or the test's stand-in)."""
        if self.ask is not None:  # a test stands in for the model
            return self.ask(task, prompt, system)
        import llm  # src/llm.py run()
        return llm.run(task, prompt, system=system, want_json=True, required=required, backend=self.backend, timeout=180, schema=schema)

    # ----- the session -----

    def start(self, n=8, kinds=None, agent=True, seed=None):
        """A new session with its questions, saved at once."""
        qs = self.questions(max(1, min(int(n or 8), 30)), kinds, seed)  # between one and thirty questions
        if not qs:  # no script to practise with: nothing is saved, or the list of earlier sessions fills with empty ones
            return {"id": "", "questions": []}
        who = self.agent() if agent else ""  # the agent, when connected and wanted
        why = self.phrase(qs) if who and qs else ""  # one call phrases them all
        return self.store.new({"job": self.job.name, "interviewer": who or "fixed", "phrase_error": why, "questions": qs})

    def _question(self, s, qid):  # used by answer() and followup()
        """A session's question by id."""
        for q in s.get("questions", []):  # the session's questions
            if q["qid"] == qid:  # found
                return q
        raise KeyError(qid)

    def answer(self, sid, qid, turn=0, text="", typed=True, seconds=None, speech_seconds=None, pauses=None, words=None,
               question=None):
        """Feedback on one answer, saved into the session."""
        s = self.store.load(sid)  # the session as saved
        q = self._question(s, qid)  # the question answered
        scenes = self.scenes()  # the scenes, current
        it, tt = scenes.get(q["scene"], (None, []))  # its scene
        turn = max(0, int(turn or 0))  # which exchange: 0 the question, then the follow-ups
        fixed = s.get("interviewer") in ("fixed", "")  # the fixed list asks the scene's own follow-ups, in order
        t = tt[turn] if turn < len(tt) and (turn == 0 or fixed) else None  # an agent's follow-up has no turn of the scene to match
        scene_text = " ".join(x["a"] for x in tt)  # every answer of the scene: the facts it holds
        text = str(text or "")[:MAX_TEXT]  # a bounded answer
        fb = feedback(text, t, scene_text, self.evidence.get(), self.pack, self.syn,
                      seconds=seconds, speech_seconds=speech_seconds, pauses=pauses, words=words,
                      spoken_answer=not typed)  # the rule-made feedback
        if t is None and turn > 0:  # a follow-up with no turn of the scene: no length target to hold it to
            fb["length"]["verdict"] = "ok" if fb["length"]["verdict"] != "long" else "long"  # only a very long answer is flagged
        rec = {"qid": qid, "turn": turn, "question": str(question or (t["q"] if t else q["ask"]))[:600], "answer": text,
               "typed": bool(typed), "feedback": fb, "at": now().isoformat()}  # the turn as kept
        s["turns"] = [x for x in s["turns"] if not (x["qid"] == qid and x["turn"] == turn)] + [rec]  # an answer given again replaces the old one
        s["summary"] = summarize(s)  # kept current, so a session closed by the browser still has its summary
        self.store.save(s)  # written at once
        scene = {"id": q["scene"], "turn": t, "turns": len(tt)}  # what the page shows after the answer
        return {"feedback": fb, "scene": scene, "summary": s["summary"]}

    def followup(self, sid, qid, turn=0):
        """The next question about this answer: the agent's (one call), else the scene's next interviewer line."""
        s = self.store.load(sid)  # the session
        q = self._question(s, qid)  # the question
        it, tt = self.scenes().get(q["scene"], (None, []))  # its scene
        turn = max(0, int(turn or 0))  # the turn just answered
        rec = next((x for x in s["turns"] if x["qid"] == qid and x["turn"] == turn), None)  # that answer
        nxt = tt[turn + 1]["q"] if turn + 1 < len(tt) else ""  # the scene's own follow-up
        if not (s.get("interviewer") not in ("fixed", "") and rec):  # the fixed list, or nothing answered yet
            return {"followup": nxt, "from": "scene" if nxt else "", "departures": []}
        t = tt[turn] if turn < len(tt) else None  # the scene's turn, for the notes
        notes = "\n".join(f"- {x['q']} / {x['a']}" for x in tt)[:4000]  # the scene: questions and my prepared answers
        prompt = (f"Question asked: {rec['question']}\n\nCandidate's answer: {rec['answer']}\n\n"
                  f"Candidate's own notes for this topic (question / prepared answer):\n{notes}\n\n"
                  + (f"A follow-up the candidate prepared for: {nxt}\n\n" if nxt else "")
                  + "Return {\"followup\": \"<one question in English>\", \"departures\": [{\"said\": \"<exact words from the answer>\", "
                  "\"fact\": \"<exact words from the notes>\", \"why\": \"<short reason>\"}]}. List a departure only when the "
                  "answer states a number, date, name or scope (who did it) that the notes state differently.")
        try:
            out = self._ask("interview-practice-followup", prompt, FOLLOW_SYSTEM, FOLLOW_SCHEMA, ("followup",))  # one call per answer
        except Exception as e:  # noqa: BLE001  no model or a bad answer: the scene's follow-up stands in
            return {"followup": nxt, "from": "scene" if nxt else "", "departures": [], "error": str(e)[:200]}
        from interview import audit  # the same quote normaliser as the consistency audit
        ans, ref = audit.norm(rec["answer"]), audit.norm(notes)  # both sides, normalised
        kept = [d for d in (out.get("departures") or []) if isinstance(d, dict)
                and audit.norm(d.get("said")) and audit.norm(d.get("said")) in ans
                and audit.norm(d.get("fact")) and audit.norm(d.get("fact")) in ref]  # only quotes that are really there
        rec["agent_departures"] = kept  # kept with the answer
        s["summary"] = summarize(s)  # the count of departures changed
        self.store.save(s)  # written at once
        fu = str(out.get("followup") or "").strip()  # the agent's question
        if not re.search(r"[A-Za-z]{3}", fu) or re.search(r"[가-힣]", fu):  # empty, or not in English: the interview is in English
            return {"followup": nxt, "from": "scene" if nxt else "", "departures": kept}  # the scene's own follow-up stands in
        return {"followup": fu[:400], "from": "agent", "departures": kept}

    def end(self, sid, seconds=None):
        """Close a session: its clock and its summary."""
        s = self.store.load(sid)  # the session
        if seconds:  # the page's session timer
            s["seconds"] = round(float(seconds), 1)
        s["ended"] = now().isoformat()  # when it closed
        s["summary"] = summarize(s)  # the final summary
        self.store.save(s)  # written
        path = self.store.path(sid)  # where it was kept
        return {"id": sid, "summary": s["summary"], "file": f"{path.parent.name}/{path.name}"}  # practice/<id>.json, in the job's output: never the PC's own path (its user name) on a page

    def transcribe(self, audio, mime=""):
        """The transcript of one recorded answer: {text, words, seconds, language} or {error}."""
        if self.stt is not None:  # a test's stand-in
            return self.stt(audio, mime)
        from interview import transcribe  # the optional speech model
        return transcribe.transcribe(audio, mime)  # runs in a separate process
