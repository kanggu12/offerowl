"""Scene checks for a job's interview kit.

A scene is an item with dialogue lines: **면접관** (the interviewer) and **나** (me) in English, each followed by its
**해석** (the Korean translation). Every scene is checked for:
  - form: it starts with 면접관; every 면접관 and 나 line has a 해석 right under it; every 해석 has Korean;
    the speech marks pair up (** and ==); ' // ' never starts or ends a line;
  - grounding: numbers and names in the English lines appear in the job's materials and the profile (the posting,
    research and submitted text, every markdown file of the kit, the stories, profile.json). By default the files as
    they are now are the reference, so a hand-written scene grounds itself; with
    --base the earlier copy of the folder is the reference, so a rewrite may not bring in new numbers or names;
    --strict uses only the materials outside the checked files (for model drafts, whose notes are drafted too);
    a draft of a question about how things work holds only its statements of what the person did to that rule, since an
    explanation of a tool may name what the person's materials never mention;
  - wording: banned words, padding phrases, forbidden wording, banned characters and particles spaced after Latin
    words, all read from the style packs (the built-in style_default.json plus the job's pack);
  - length, when asked: with --base an earlier copy of the folder, no scene's lines may get shorter, and with
    --grow F each scene's lines must reach F times their earlier length (ids or section letters in grow_skip excepted).
The verdict is the last line: "checked N scenes (of M items), problems K".
"""
import json  # style packs
import pathlib  # paths
import re  # the rules

from interview import corpus, i18n  # items; messages
from interview.job import Job, read_text  # base folders; material text

HERE = pathlib.Path(__file__).resolve().parent  # src/interview
DLG = re.compile(r"^(?:-\s+)?\*\*(면접관|나|해석)\*\*\s*[:：]?\s*(.*)$")  # a dialogue line in either file style
SPOKEN = ("면접관", "나")  # the English lines
# A Korean particle written with a space after a Latin word or a number ("Kubernetes 로" must be "Kubernetes로").
JOSA = re.compile(r"(?<=[A-Za-z0-9\)\]])\s+(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만|까지|부터|보다|처럼|이나|이고|이며|이라는|라는|에게)(?=[\s.,!?)]|$)")
# Words that start sentences or link them; capitalised, they are still not names.
COMMON = set(("i i'm i've i'd i'll at the a an and but so then when if as in on for to of with from by my our we they it its it's this "
              "that these those most first second third finally also now next well actually honestly ok okay right sure yes no not one two "
              "three four five six seven eight nine ten after before during while because which who what how why where there here each "
              "every all both either neither").split())
SPOKEN_FILLERS = {"Hmm", "Let's", "Okay", "Got", "Interesting", "Right", "Sure", "Great", "Thanks"}  # conversational openers, not names


# ---------- the style packs ----------

def style_pack(job, name=None):  # read once per run by run() and check_path()
    """The built-in rules plus the job's style pack (--style, else kit.json "style"); lists add up, other values override."""
    pack = json.loads((HERE / "style_default.json").read_text(encoding="utf-8"))  # generic rules
    name = name or job.kit.get("style")  # the job's pack, if any
    if name:  # without one, the built-in rules alone
        p = pathlib.Path(name).expanduser()  # a path, or a name in the workspace's style folder
        if not p.suffix:  # a bare name: <workspace>/style/<name>.json
            p = job.in_workspace(f"style/{name}.json")  # the workspace's style folder
        elif not p.is_absolute():  # a relative path: from the workspace (or the job without one)
            p = job.in_workspace(str(p))  # resolved against the workspace root
        else:  # an absolute path: as given, and a confined kit keeps it inside the workspace
            p = job.kept(p)
        if not p or not p.is_file():  # a named pack must exist, or its rules would silently not apply
            raise SystemExit(f"no style pack: {p}")  # stop with the path that was tried
        user = json.loads(p.read_text(encoding="utf-8"))  # the job's own rules
        pack["banned_chars"] = pack.get("banned_chars", "") + user.get("banned_chars", "")  # characters add up
        for k, v in (user.get("interview") or {}).items():  # the interview rules
            if isinstance(v, list):  # word and phrase lists
                pack["interview"][k] = pack["interview"].get(k, []) + v  # lists add up
            else:
                pack["interview"][k] = v  # switches override
    return pack  # the merged rules


def compiled(pack):  # the checks run per scene, so compile the patterns once per run
    """The pack's patterns, compiled once."""
    iv = pack["interview"]  # the interview part
    words = iv.get("banned_words") or []  # whole words, any case
    return {  # one entry per kind of wording check
        # whole words only; None turns the check off
        "banned": re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I) if words else None,
        "padding": re.compile("|".join(iv["padding"])) if iv.get("padding") else None,  # case kept: these are exact phrases
        # each forbidden form: its pattern, the reason shown, its side (en, ko, both) and the ids exempt from it
        "forbidden": [(re.compile(f["pattern"], re.I), f.get("why", ""), f.get("in", "both"), set(f.get("except", [])))
                      for f in iv.get("forbidden") or []],  # an absent list means no forbidden forms
        "chars": set(pack.get("banned_chars", "")),  # single characters, tested one by one
        "josa": bool(iv.get("spaced_josa", True)),  # on unless a pack turns it off
    }


# ---------- numbers and names ----------

def nums(s):  # the scenes and the materials are read the same way
    """Digit groups in a text ("20", "2,000", "3.5")."""
    return set(re.findall(r"\d+(?:[.,]\d+)*", s))  # separators and decimals stay in one group


def near(n, allowed):  # an answer often rounds a figure from the notes
    """A number counts as grounded when it is in the set, or rounds (within 10 percent) a grounded number of 10 or more."""
    if n in allowed:  # the exact figure
        return True
    try:
        x = float(n.replace(",", ""))  # 2,000 as a number
    except ValueError:  # a group such as 1.2.3 is not a number
        return False  # so it must match exactly
    for m in allowed:  # look for a grounded number it rounds
        try:
            y = float(m.replace(",", ""))  # the grounded figure as a number
        except ValueError:  # a version-like group cannot be rounded to
            continue
        if y >= 10 and abs(x - y) <= 0.1 * y:  # small numbers must match exactly; larger ones may be rounded
            return True
    return False  # no grounded number is close enough


def names(s):  # the default (not strict) name rule
    """Capitalised, mixed-case or numbered words in English lines: product, tool, company and project names."""
    s = re.sub(r"\([^()]*[가-힣][^()]*\)", " ", s)  # Korean stage notes are not spoken
    toks = re.findall(r"[A-Za-z][A-Za-z0-9+\-_.']*", s.replace("**", " ").replace("==", " "))  # words, marks removed
    # two capitals, a digit or camelCase, or a capitalised word that is not common sentence glue
    return {t.strip(".'") for t in toks if (re.search(r"[A-Z].*[A-Z]|\d|[a-z][A-Z]", t) or (t[0].isupper() and t.lower() not in COMMON))}


def latin_tokens(text):  # the strict pool and each strict name are split the same way
    """Lowercase Latin words, also split at . - / (strict mode compares whole words, so 'Java' is not inside 'JavaScript')."""
    out = set()  # whole words and their parts
    # Latin words with their dotted, hyphenated, slashed or quoted parts (+ and # kept for names like C++)
    for w in re.findall(r"[A-Za-z][A-Za-z0-9+#]*(?:[.\-/'][A-Za-z0-9+#]+)*", text or ""):
        out.add(w.lower())  # the whole word
        out |= {p.lower() for p in re.split(r"[.\-/']", w) if p}  # and each part on its own
    return out


def plural_ok(w, pool):  # a scene may use the plural where the notes use the singular
    """A word whose plural or singular is in the pool counts as present."""
    return w in pool or (w.endswith("s") and w[:-1] in pool) or (w + "s") in pool  # exact, minus s, or plus s


# ---------- scenes ----------

def blocks(path):  # read once per file and shared by its items
    """{line number of a heading: body lines (number, text)} for one markdown file; a body runs to the next heading."""
    lines = pathlib.Path(path).read_text(encoding="utf-8").split("\n")  # the file as it is now
    out, cur = {}, None  # heading line -> body
    for n, ln in enumerate(lines, 1):  # numbered from 1, like the items' heading lines
        if ln.startswith(("# ", "## ", "### ")):  # the same headings the corpus splits on
            cur = out.setdefault(n, [])  # a new body starts at each heading
        elif cur is not None:  # lines before the first heading belong to no item
            cur.append((n, ln))  # line numbers kept for messages
    return out


def scene_of(item, file_blocks):  # splits one item's body into spoken lines and notes
    """[(speaker, text, line number)] of an item's dialogue lines, and the item's other lines (its notes)."""
    body = file_blocks.get(item["line"], [])  # the lines under the item's heading
    dialogue, notes = [], []  # spoken lines; everything else
    for n, ln in body:  # every line under the heading
        m = DLG.match(ln.strip())  # indentation does not matter
        if m:  # a 면접관, 나 or 해석 line
            dialogue.append((m.group(1), m.group(2), n))  # speaker label, text after the colon, line number
        elif ln.strip():  # blank lines are neither
            notes.append(ln)  # stage notes, key lines and the like
    return dialogue, notes


def load_scenes(job, files=None, ids=None, drafts=False):  # --files and --ids narrow the set
    """(all items, [(item, dialogue, notes)] for the scenes to check). drafts: the agent's drafts too, for practice and for
    cue cards asked for by id; the checks leave them out (a draft passed the strict check when it was written)."""
    items, _ = corpus.load(job)  # every item of the kit
    cache = {}  # path -> blocks
    out = []  # scenes in file order
    want_files = {f.strip() for f in files.split(",")} if files else None  # --files
    want_ids = {i.strip() for i in ids.split(",")} if ids else None  # --ids
    for it in items:  # filters first, then the item's lines
        if it.get("draft") and not drafts:  # a draft passed the strict check when it was written; the rest is a person's to read
            continue
        if want_files and it["file"] not in want_files:  # not one of the asked files
            continue
        if want_ids and it["id"] not in want_ids:  # not one of the asked ids
            continue
        if it["path"] not in cache:  # each file is split once, however many items it holds
            cache[it["path"]] = blocks(it["path"])  # kept for the next item of the same file
        dialogue, notes = scene_of(it, cache[it["path"]])  # this item's lines
        if dialogue:  # only items with dialogue are scenes
            out.append((it, dialogue, notes))  # kept with its dialogue and notes
    return items, out  # all items for the summary count, the scenes for the checks


def my_words(dialogue):  # the length measure for --base and --grow
    """How many words my lines have (speech marks are not words)."""
    return len(" ".join(t for w, t, _ in dialogue if w == "나").split())  # only my lines count


# ---------- the pool of materials ----------

DATE_WORDS = set(("january february march april may june july august september october november december "
                  "monday tuesday wednesday thursday friday saturday sunday").split())  # capitalised by grammar, not names
NAME_LIKE = re.compile(r"[A-Z].*[A-Z]|\d|[a-z][A-Z]")  # two capitals, a digit or camelCase: a name wherever it stands


def strict_names(s):  # used by Pool in strict mode
    """Names for strict mode. A capitalised word counts only inside a sentence (an opener such as "Since" is an ordinary
    word); words with two capitals, digits or camelCase count anywhere. Possessives are cut, hyphenated words split."""
    s = re.sub(r"\([^()]*[가-힣][^()]*\)", " ", s)  # Korean stage notes are not spoken
    s = s.replace("**", "").replace("==", "")  # stress and key-phrase marks sit inside words' edges
    out = set()  # name-like parts
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9+\-_.']*", s):  # each Latin word, with its position for the opener test
        tok = m.group(0).strip(".'")  # the word without a trailing period or quote
        if not tok:  # a lone period or quote
            continue
        opener = m.start() == 0 or re.search(r"(?:[.?!:;\"“]|//)\s*$", s[max(0, m.start() - 8):m.start()])  # starts a sentence
        if not NAME_LIKE.search(tok):  # a plain capitalised word
            # lowercase, a sentence opener, sentence glue, a month or a weekday: not a name
            if not tok[0].isupper() or opener or tok.lower() in COMMON or tok.lower() in DATE_WORDS:
                continue
        tok = re.sub(r"'s$|s'$", "", tok)  # ClusterWare's -> ClusterWare
        for part in re.split(r"[-/]", tok):  # ECN-based -> ECN (based is lowercase)
            if len(part) >= 2 and (NAME_LIKE.search(part) or part[:1].isupper()):  # parts that still look like names
                out.add(part)  # each part is looked up on its own
    return out


class Pool:  # one per run
    """Text that grounds the scenes.

    default: the reference state of the materials, which is the current files (a hand-written scene grounds itself)
    or, with --base, the earlier copy of the interview folder together with the other materials;
    strict: the materials outside the checked files only, with whole-word name matching."""

    def __init__(self, job, strict, checked_paths, base_dir=None):  # built once per run, before any scene is checked
        self.strict = strict  # strict mode
        parts = []  # material text
        base = pathlib.Path(base_dir).resolve() if base_dir else None  # earlier copy of the interview folder
        for f in job.material_files():  # the job's posting, research, submitted text, kit files, stories and profile
            if strict and str(f) in checked_paths:  # strict: the checked files ground nothing (their notes are drafted too)
                continue
            if base and f.parent == job.interview:  # a rewrite is grounded in the files as they were
                old = base / f.name  # the same file in the earlier copy
                if old.is_file():  # a file new since then grounds nothing
                    parts.append(read_text(old))  # the earlier text
                continue  # the current text of this file is not used
            parts.append(read_text(f))  # other materials as they are now
        if base:  # files that exist only in the earlier copy still ground facts
            for old in sorted(base.glob("*.md")):  # sorted so the pool text is the same on every run
                if not (job.interview / old.name).is_file():  # files already read above are skipped
                    parts.append(read_text(old))  # a file removed or renamed since then
        self.text = "\n".join(parts)  # everything that grounds facts
        self.low = self.text.lower()  # for name lookups (substring, as before)
        self.nums = nums(self.text)  # grounded numbers
        self.tokens = latin_tokens(self.text)  # grounded words (strict mode)

    def numbers_missing(self, text):  # the grounding check for numbers
        """Numbers in a scene's English that the materials do not hold (rounded values of 10 or more pass)."""
        return sorted(n for n in nums(text) if not near(n, self.nums))  # sorted so messages are stable

    def names_missing(self, text):  # the grounding check for names
        """Names in a scene's English that the materials do not hold."""
        if self.strict:  # whole words, the parts of a hyphenated word one by one
            miss = []  # names to report
            for n in sorted(strict_names(text)):  # sorted so messages are stable
                if n in SPOKEN_FILLERS:  # conversational openers
                    continue
                if not all(plural_ok(p, self.tokens) for p in latin_tokens(n)):  # every part must be in the pool
                    miss.append(n)  # at least one part is not grounded
            return miss
        # default mode: a name is grounded when it appears anywhere in the pool, in any case
        return [n for n in sorted(names(text)) if n not in SPOKEN_FILLERS and n.lower() not in self.low]


# ---------- what the person did, and what they deny ----------

SENTENCE = re.compile(r"\s*//\s*|(?<=[.!?])\s+")  # the speech mark between sentences, with the spaces around it, and sentence ends
ADVERB = r"(?:(?:also|first|then|later|personally|once|previously|originally|already|just|only|mainly|actually|never)\s+)?"  # "I also built"
PAST_VERB = (r"(?:\w+ed|built|ran|led|made|wrote|set|did|found|took|got|had|was|were|went|kept|held|gave|saw|met|chose|drew|grew|put|sent|spent|"
             r"taught|brought|bought|hit|cut|lost|won|began|became|paid|told|knew|left|shut|split)")  # regular and common irregular past forms
# A statement of what the person did or does: a first-person past or perfect, or the verbs that say a tool is part of their work
CLAIM = re.compile(r"\b(?:I|we|We)\s+" + ADVERB + PAST_VERB + r"\b"  # "I built", "we also moved"
                   r"|\b(?:I've|we've|We've|I\s+have|we\s+have|We\s+have)\b"  # "I've used", "we have run"
                   r"|\b(?:I|we|We)\s+" + ADVERB + r"(?:use|manage|maintain|operate|own|lead|work\s+with|know)\b"  # "I use Foo every day"
                   r"|\b(?:[Mm]y|[Oo]ur)\s+\w+\s+" + PAST_VERB + r"\b"  # "my team built"
                   r"|\b(?:took|lasted|finished|completed|reached|dropped|saved|reduced|improved|increased|decreased|grew|fell|stayed)\b")  # "it took 7 weeks": a result, whoever says it
YEAR = re.compile(r"\b(?:19|20)\d\d\b")  # a year ties a sentence to something that happened
# Saying that the person has not done something: the person is the subject of the denial, or says there is no experience
DENY = re.compile(r"\b(?:I|[Ww]e)\s+(?:have\s+not|haven't|never|did\s+not|didn't|do\s+not\s+have|don't\s+have|have\s+no)\b"
                  r"|\bno\s+(?:hands-on\s+|direct\s+|real\s+)?experience\b")


def sentences(line):
    """A spoken line as sentences, without its stress, key-phrase and breath marks."""
    plain = line.replace("**", "").replace("==", "")  # the marks sit inside words' edges
    return [re.sub(r"\s/\s", " ", x).strip() for x in SENTENCE.split(plain) if x.strip()]  # breaths are not words


def claim_sentences(lines, orgs=()):
    """The sentences of my lines that state what the person did, or that tie the work to a company or a year."""
    orgs = [o for o in orgs if o]  # the person's companies
    return [s for line in lines for s in sentences(line) if CLAIM.search(s) or YEAR.search(s) or any(o in s for o in orgs)]  # the rest explains how things work


def denials(lines, own):
    """Names in my lines' sentences that say the person has not done something with a name their own documents hold."""
    out = []  # names to report
    for line in lines:  # each of my lines
        for s in sentences(line):  # sentence by sentence
            if DENY.search(s):  # the person says they have not
                out += [n for n in sorted(strict_names(s)) if n not in SPOKEN_FILLERS and all(plural_ok(p, own) for p in latin_tokens(n))]  # a name their own documents hold
    return sorted(set(out))  # each name once


TURN_WORDS, FIRST_TURN_WORDS = 110, 180  # words in one answer: about a minute aloud at a learner's pace; a self-introduction's first answer may run longer
TURN_CODE, CODE_CHARS = 3, 32  # commands in one answer, and the length of one command, that a person can still say aloud
BOLD_SHARE = 0.35  # the share of bold words past which the stress marks stop telling anything


def hard_to_say(lines):
    """What makes my lines hard to say aloud, in words the writer can act on. Empty when they are fine."""
    out = []  # the findings
    words, bold = 0, 0  # all spoken words, and the bold ones
    for k, line in enumerate(lines, 1):  # each answer
        text = re.sub(r"\s//?\s", " ", line.replace("**", "").replace("==", ""))  # without its marks
        n = len(re.sub(r"\([^()]*[가-힣][^()]*\)", " ", text).split())  # spoken words, without stage notes
        limit = FIRST_TURN_WORDS if k == 1 else TURN_WORDS  # the first answer may be a self-introduction
        if n > limit:  # too long for one breath group of answers
            out.append(f"answer {k} has {n} words; keep it under {limit} and move the rest to the next exchange")
        code = re.findall(r"`([^`]+)`", line)  # the commands it names
        if len(code) > TURN_CODE:  # a list of commands
            out.append(f"answer {k} names {len(code)} commands; name at most {TURN_CODE} and say the rest in words")
        out += [f"answer {k} reads out a long command ({c[:40]}); say what it shows in words" for c in code if len(c) > CODE_CHARS]  # nobody says these aloud
        words += n  # counted
        bold += sum(len(b.split()) for b in re.findall(r"\*\*([^*]+)\*\*", line))  # the words in bold
    if words and bold / words > BOLD_SHARE:  # most words stressed
        out.append(f"{bold} of {words} words are bold; mark one or two words in a sentence")
    return out


def person_orgs(job):
    """The names of the person's companies, as the profile writes them in English or Latin letters."""
    prof = {}  # the profile, when there is one
    path = job.profile_path  # the kit's profile file
    if path and path.is_file():  # optional
        prof = json.loads(path.read_text(encoding="utf-8"))  # the confirmed facts
    out = set()  # names
    for role in prof.get("roles") or []:  # every company
        career = role.get("career") if isinstance(role.get("career"), dict) else {}  # the ledger form
        for block in (career.get("en"), career.get("ko")):  # both languages of its names
            if isinstance(block, dict):  # written
                out.update(str(block[k]) for k in ("name", "short") if block.get(k))  # the full and the short name
        out.update(str(role[k]) for k in ("org", "heading") if role.get(k))  # the plain form
    # only the Latin part of a name: an English line never holds the Korean one ("감마랩스(Gamma Labs)" gives "Gamma Labs")
    return {m for name in out for m in re.findall(r"[A-Za-z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)*", name)}


def own_tokens(job):
    """The words of the person's own documents (profile, stories, what was sent), not the posting's or the research's."""
    parts = []  # their texts
    for f in (job.profile_path, job.stories_path, job.submitted("resume"), job.submitted("portfolio")):  # each document
        if f and f.is_file():  # optional parts
            parts.append(read_text(f))  # its text
    return latin_tokens("\n".join(parts))  # whole words and their parts


# ---------- the checks ----------

def check_scene(it, dialogue, notes, rules, pool, base_words, grow, grow_skip, orgs=None):  # one call per scene
    """Problems of one scene as (code, slots) pairs. orgs, for a draft about how things work: the person's companies, and
    only the sentences that state what the person did are grounded."""
    probs = []  # what is wrong
    if dialogue[0][0] != "면접관":  # a scene opens with the question
        probs.append(("start", {}))  # the first line is not the interviewer's
    for k, (who, txt, n) in enumerate(dialogue):  # line by line, the first form problem is enough
        # an English line must be followed by its 해석, so a scene cannot end on one
        if who in SPOKEN and (k + 1 >= len(dialogue) or dialogue[k + 1][0] != "해석"):
            probs.append(("no_tr", {"n": k}))  # n: the line's index in the scene
            break
        if who == "해석" and not re.search(r"[가-힣]", txt):  # a translation left without Korean
            probs.append(("tr_ko", {"n": k}))  # the translation is not in Korean
            break
        if who == "나" and (txt.count("**") % 2 or txt.count("==") % 2):  # an odd count leaves a mark open
            probs.append(("marks", {"n": k}))  # unpaired stress or key-phrase marks
            break
        if who in SPOKEN and re.search(r"^\s*//|//\s*$", txt):  # // sits between phrases, never at an edge
            probs.append(("slash_end", {"n": k}))  # // at the start or end of a line
            break
    en = " ".join(t for w, t, _ in dialogue if w in SPOKEN)  # everything said in English
    ko = " ".join(t for w, t, _ in dialogue if w == "해석")  # the translations
    # what must be grounded: everything said, or for an explanation of how things work only what the person says they did
    ground = en if orgs is None else " ".join(claim_sentences([t for w, t, _ in dialogue if w == "나"], orgs))
    missing = pool.numbers_missing(ground)  # grounding: numbers
    if missing:  # any number not grounded
        probs.append(("numbers", {"list": ", ".join(missing)}))  # every missing number in one message
    gone = pool.names_missing(ground)  # grounding: names
    if gone:  # any name not grounded
        probs.append(("names", {"list": ", ".join(gone[:8])}))  # at most eight, to keep the line readable
    if base_words is not None:  # length against the earlier copy
        now = my_words(dialogue)  # my words now
        if now < 0.95 * base_words:  # five percent slack for small edits
            probs.append(("shorter", {"now": now, "was": base_words}))  # both counts in the message
        # --grow: the scene must reach the factor, unless its id or its section letter is in grow_skip
        if grow and it["id"] not in grow_skip and it["id"][:1] not in grow_skip and now < grow * base_words:
            probs.append(("grow", {"now": now, "need": int(grow * base_words)}))  # need: the target word count
    m = rules["banned"].search(en) if rules["banned"] else None  # wording: AI-sounding words
    if m:  # a banned word was found
        probs.append(("banned", {"word": m.group(0)}))  # the first one is enough to report
    for rx, why, where, skip in rules["forbidden"]:  # wording: the pack's forbidden forms
        if it["id"] in skip:  # this scene is exempt from the rule
            continue
        hay = en if where == "en" else ko if where == "ko" else en + " " + ko  # the side the rule applies to
        f = rx.search(hay)  # the first match only
        if f:  # the rule matched
            # the matched text, and the pack's reason in brackets when it gives one
            probs.append(("forbidden", {"word": f.group(0), "why": f" ({why})" if why else ""}))
    m = rules["padding"].search(en) if rules["padding"] else None  # wording: filler phrases
    if m:  # a filler phrase was found
        probs.append(("padding", {"word": m.group(0)}))  # the first one is enough to report
    m = JOSA.search(ko) if rules["josa"] else None  # spelling: particles attach to Latin words
    if m:  # a spaced particle was found
        probs.append(("josa", {"word": m.group(0).strip()}))  # the particle itself, without the space before it
    bad_chars = sorted({c for c in en + ko if c in rules["chars"]})  # banned characters
    if bad_chars:  # any banned character
        probs.append(("chars", {"chars": "".join(bad_chars)}))  # every banned character once
    return probs  # an empty list means a clean scene


def base_lengths(job, base):  # used only with --base
    """{id: my words} in an earlier copy of the interview folder, read with the same kit."""
    old = Job(base, kit=job.kit_path, workspace=job.workspace, confined=job.confined)  # same sources and labels, the same reach
    _, scenes = load_scenes(old)  # every scene of the earlier copy, no filters
    return {it["id"]: my_words(d) for it, d, _ in scenes}  # keyed by id to match the current scenes


def run(job, grow=0, base=None, strict=False, style=None, files=None, ids=None):  # the whole check
    """(items, scenes, [(item, problems)]) for a job."""
    items, scenes = load_scenes(job, files, ids)  # what to check
    rules = compiled(style_pack(job, style))  # wording rules
    checked = {it["path"] for it, _, _ in scenes}  # files under test
    pool = Pool(job, strict, checked, base)  # grounding
    lengths = base_lengths(job, base) if base else {}  # earlier lengths
    skip = set(job.kit.get("grow_skip") or [])  # openings and closings keep their length
    out = []  # scenes with problems
    for it, dialogue, notes in scenes:  # every scene in file order
        # no earlier length without --base, so the length checks stay off
        probs = check_scene(it, dialogue, notes, rules, pool, lengths.get(it["id"]) if base else None, grow, skip)
        if probs:  # a clean scene is not reported
            out.append((it, probs))  # only scenes with problems are kept
    return items, scenes, out  # counts for the verdict line, problems for the report


def check_path(job, path, strict=True, style=None, orgs=None):  # drafts are checked before they join the kit
    """(scenes, [(item, problems)]) for the scenes of a file outside the kit, such as a draft (strict by default). orgs:
    the person's companies, for a draft about how things work (check_scene)."""
    path = pathlib.Path(path).resolve()  # the file under test
    items = corpus.parse_text(path.read_text(encoding="utf-8"), "draft", "D", "scenes", path.name)  # its items
    for it in items:  # parse_text leaves the path out
        it["path"] = str(path)  # the same field kit items carry
    fb = blocks(path)  # its blocks with line numbers
    scenes = [(it,) + scene_of(it, fb) for it in items]  # (item, dialogue, notes)
    scenes = [s for s in scenes if s[1]]  # items with dialogue only
    rules = compiled(style_pack(job, style))  # the job's wording rules
    pool = Pool(job, strict, {str(path)})  # the kit's materials; the file itself grounds nothing
    bad = []  # scenes with problems
    for it, dialogue, notes in scenes:  # every scene of the draft
        probs = check_scene(it, dialogue, notes, rules, pool, None, 0, set(), orgs)  # no base, no growth, no skips
        if probs:  # a clean scene is not reported
            bad.append((it, probs))  # only scenes with problems are kept
    return scenes, bad  # the caller prints its own report


def letters_twice(job):
    """[(letter, [(file, title)])] for every section letter that two differently named sections share (a section taken over
    from another job's kit, say). Their keys and their hue look alike in the search view and the contents."""
    import re  # the headings
    by = {}  # letter -> the sections that use it
    for path, _, _, role in job.sources():  # the kit's files, in its order
        if role == "reference":  # notes and stories have no lettered sections
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^##\s+([A-Z])\.\s+(.+?)\s*$", line)  # "## A. Behavioral, career"
            if m and (path.name, m.group(2)) not in by.setdefault(m.group(1), []):
                by[m.group(1)].append((path.name, m.group(2)))
    return [(k, v) for k, v in sorted(by.items()) if len({t for _, t in v}) > 1]


def main(job, grow=0, base=None, strict=False, style=None, files=None, ids=None, quiet=False):  # the check command
    """Print one line per scene with problems and the verdict line; exit 1 when any scene has a problem. A letter two
    sections share is said in a line of its own, without failing the check: the scenes are sound, their keys look alike."""
    items, scenes, bad = run(job, grow, base, strict, style, files, ids)  # every check for the job
    if not quiet and not files and not ids:  # the whole kit: its sections' letters
        for letter, where in letters_twice(job):
            print(i18n.t("check_letter_twice", letter=letter, where="; ".join(f"{f} \"{t}\"" for f, t in where)))
    if not quiet:  # quiet: only the verdict line
        for it, probs in bad:  # one line per scene with problems
            why = "; ".join(i18n.reason(code, **slots) for code, slots in probs)  # all its problems on one line
            # file, heading line and id point at the scene
            print(i18n.t("check_bad", file=it["file"], line=it["line"], id=it["id"], why=why))
    n = len(bad)  # scenes with any problem: a scene counts once, however many problems it has
    print(i18n.t("check_scene_summary", scenes=len(scenes), items=len(items), problems=n))  # the verdict line
    return 1 if n else 0  # the exit status for scripts and hooks
