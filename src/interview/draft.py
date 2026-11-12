"""New scenes for planned questions, written by the model and checked before anyone reads them.

For each chosen entry of the question map (plan.json), the evidence is collected without the model (evidence.py: the
passages of the person's own materials that share the question's rare words). The writing rules (prompts/draft_scene.md
and prompts/draft_depth.json, with the style pack's banned and forbidden wording filled in) and the evidence go to the
model through src/llm.py run(); the answer comes back as JSON and is written in the kit's scene format.

Each scene is checked in strict mode (check.py). What the person says they did must be grounded in the materials; in an
explanation of how something works, a name the person's documents never mention is fine, and a scene that denies
experience the person's own documents show is not. A scene that fails is written once more with the reasons in hand.
With a real model, a scene that passes is then read against the evidence around what it says (prompts/verify_scene.md),
since what qualifies a claim may sit in a passage its question did not reach, and is written once more if that finds
something it told wrongly.
Passing scenes go to a new file drafts/drafts-<n>.md in the output folder, as they are finished, and join the kit's
search view and practice at once; failing ones go to drafts-<n>.rejected.md with their reasons. Nothing is ever
overwritten: the files are new, and new ids continue after the highest id of their section letter. By default only
questions that no scene covers are drafted, the likeliest kinds first; --ids picks entries by hand.
"""
import concurrent.futures  # several scenes at a time
import json  # the depth of each kind
import pathlib  # paths
import re  # ids
import sys  # the console's encoding, for the summary line
import tempfile  # one scene at a time for the check
import threading  # the scenes finish in any order

from interview import check, corpus, i18n  # the checker, items, messages
from interview import plan as planmod  # the question map


def say(text: str) -> None:
    """A line for the person running it. The panel calls main() in its own process, so a line in Korean printed through a
    console or a pipe in another code page (cp1252 on Windows) is printed with the odd letters replaced: it never stops the
    drafting it reports."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, "replace").decode(enc))
from interview.evidence import Evidence  # what each scene may say
from interview.job import read_json  # files

HERE = pathlib.Path(__file__).resolve().parent  # src/interview
PROMPT = (HERE / "prompts" / "draft_scene.md").read_text(encoding="utf-8")  # the writing rules
VERIFY = (HERE / "prompts" / "verify_scene.md").read_text(encoding="utf-8")  # the second reading
VERIFY_SYSTEM = "You check what a job candidate says against the evidence about them. Quote exactly. Return only JSON."  # the quotes are checked
DEPTH = json.loads((HERE / "prompts" / "draft_depth.json").read_text(encoding="utf-8"))  # how deep each kind goes
# The facts about the person come from the evidence; how things work may come from the model's own knowledge
SYSTEM = "You write interview scenes. Facts about the candidate come only from the given evidence. Return only JSON."
REPAIR = ("\n\n## Your last answer was rejected\nThe checks found: {reasons}\nWrite the whole scene again and fix these, keeping what was good. A name that is "
          "not in the evidence cannot be in a sentence about what the candidate did; say how it works in the present tense instead, or leave it out.")
# Default sections of each kind of question
LETTERS = {"asked": "L", "posting": "P", "resume": "R", "portfolio": "F", "term": "Q", "behavioral": "D", "company": "C", "opening": "O", "scenario": "E", "technical": "T"}
# Names of the kinds, for the heading of a section the kit does not have yet
KIND_NAMES = {"ko": {"asked": "지난 면접에서 받은 질문", "posting": "공고 줄마다", "resume": "이력서 줄마다", "portfolio": "포트폴리오 장마다", "term": "용어",
                     "behavioral": "인성", "company": "회사", "opening": "첫 인사", "scenario": "상황 대응", "technical": "기술 질문"},
              "en": {"asked": "Asked in earlier rounds", "posting": "Posting lines", "resume": "Resume lines", "portfolio": "Portfolio pages", "term": "Terms",
                     "behavioral": "Behavioral", "company": "Company", "opening": "Opening", "scenario": "Scenarios", "technical": "Technical"}}  # headings of new sections
# The likeliest questions first, so a few scenes already cover what nearly every interview asks; terms come last, there are many.
# What an earlier round really asked comes before all of them: the next round may ask it again or go deeper.
ORDER = ("asked", "behavioral", "company", "scenario", "technical", "posting", "resume", "portfolio", "opening", "term")
# Kinds about how things work: a sentence that explains may name what the person's documents never mention. Every other
# kind is about the person's own work or about the company, so everything in it stays grounded.
EXPLAINING = ("scenario", "technical", "term", "asked")  # a question really asked may be about how a thing works
# The JSON shape of one drafted scene: two titles, the key line, the caution, and the dialogue as [label, text] pairs
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["title_ko", "title_en", "key", "lines", "caution"],
          "properties": {"title_ko": {"type": "string"}, "title_en": {"type": "string"}, "key": {"type": "string"},
                         "caution": {"type": "string"},
                         "lines": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}}}  # for backends that take one


def depth_of(kind):
    """How deep a scene of this kind goes: its own rules, and the length of a detailed answer except in small talk."""
    rules = DEPTH.get(kind) or DEPTH["technical"]  # a kind from a kit's own map reads like a technical question
    return rules if kind == "opening" else rules + "\n" + DEPTH["long"]  # small talk stays short


def ranked(rows):
    """The questions in the order they should be written: by kind, and among the terms those the documents use most."""
    def uses(r):  # how often a term appears, from its "3x" source
        m = re.match(r"(\d+)x$", str(r.get("source", "")))  # only terms have this source
        return int(m.group(1)) if m else 0  # the others keep their map order
    return sorted(rows, key=lambda r: (ORDER.index(r["kind"]) if r["kind"] in ORDER else len(ORDER), -uses(r)))  # stable: the map's order within a kind


def answered(folder):
    """The questions the drafts in a folder already answer: {question id}."""
    done = set()  # question ids
    for f in sorted(pathlib.Path(folder).glob("drafts-*.md")):  # every drafts file of earlier runs
        if not f.name.endswith(".rejected.md"):  # a rejected scene answers nothing
            done.update(re.findall(r"^- \*\*근거\*\*: (\S+) ", f.read_text(encoding="utf-8"), flags=re.M))  # draft.py ends each scene with this line
    return done


def next_ids(items):
    """{letter: next free number} from the kit's ids (D7 -> D8)."""
    top = {}  # letter -> highest number used
    for it in items:  # every item of the kit
        m = re.fullmatch(r"([A-Z])(\d+)[a-z]?(?:-\d+)?", it["id"])  # a letter, a number and an optional suffix (D7, D7a, D7-2)
        if m:  # ids of other shapes take no part
            top[m.group(1)] = max(top.get(m.group(1), 0), int(m.group(2)))  # keep the highest number per letter
    return {k: v + 1 for k, v in top.items()}  # one past the highest, so no id is reused


def asked_letter(job, cats, kit_letters, id_letters=()):
    """The section the scenes for questions of earlier rounds join: the kit's own choice in draft_sections, the section an
    earlier run made for them, else L, or the first letter that no section, no item's id and no other kind uses (a kit of
    its own may already have an L about something else, and a new scene there would sit under the wrong heading)."""
    if "asked" in (job.kit.get("draft_sections") or {}):  # the kit says where
        return kit_letters["asked"]
    names = {n["asked"] for n in KIND_NAMES.values()}  # the heading a run before gave them, in either language
    for letter, head in cats.items():
        if head.split(". ", 1)[-1] in names:  # "L. 지난 면접에서 받은 질문"
            return letter
    taken = set(cats) | set(id_letters) | {v for k, v in kit_letters.items() if k != "asked"}  # the kit's sections, its ids' letters, the other kinds' letters
    return next((c for c in "LABCDEFGHIJKMNOPQRTUVWXYZ" if c not in taken), "X")  # S is a stories file's own; X when all are taken


def categories(items):
    """{letter: the section heading the kit already uses for it} ("Q" -> "Q. 꼬리 질문: 줄임말과 용어")."""
    out = {}  # letter -> heading
    for it in items:  # every item of the kit
        m = re.match(r"^([A-Z])\.\s", it["cat"])  # a section heading that starts with its letter, as in "Q. ..."
        if m and m.group(1) not in out:  # the first heading seen for a letter wins
            out[m.group(1)] = it["cat"]  # new scenes of that letter join this heading
    return out


def scene_md(sid, res):
    """A drafted scene in the kit's format (heading, key line, dialogue, caution, hidden evidence note)."""
    title_ko = re.sub(r"\s*/\s*", ", ", str(res.get("title_ko", "")).strip()) or sid  # the separator " / " belongs to the heading
    title_en = re.sub(r"\s+/\s+", ", ", str(res.get("title_en", "")).strip())  # the same for the English title, which may be empty
    out = [f"### {sid}. {title_ko}" + (f" / {title_en}" if title_en else ""), ""]  # the heading, the English title only when given
    if res.get("key"):  # the key line is optional
        out += [f"**핵심** {str(res['key']).strip()}", ""]  # the 핵심 line under the heading
    for pair in res.get("lines") or []:  # the dialogue, one [label, text] pair per line
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:  # a malformed line is left out (the check then sees the gap)
            continue
        who, txt = pair  # the speaker label and what is said
        if who in ("면접관", "나", "해석"):  # only the three labels of the format
            line = " ".join(str(txt).split())  # one line: newlines and runs of spaces collapse
            out.append(f"**{who}** {line}")  # the label in bold, as the scene format writes it
    out.append("")  # a blank line closes the dialogue
    if str(res.get("caution", "")).strip():  # the caution is optional too
        out += [f"**주의** {str(res['caution']).strip()}", ""]  # the 주의 line after the dialogue
    return "\n".join(out)  # the scene as one markdown text


def model_ask(backend):
    """The real model: one llm.run() call per scene through src/llm.py."""
    import llm  # the one door to a model

    def ask(prompt, entry):  # the same signature as a test stand-in; the entry is not needed here
        # one JSON scene; a missing required key makes llm.run ask again
        return llm.run("interview-draft", prompt, system=SYSTEM, want_json=True, required=("title_ko", "title_en", "key", "lines"),
                       backend=backend, timeout=300, schema=SCHEMA)  # a whole scene takes longer than a short call
    return ask  # main() calls it once per scene


def free_path(d, stem):
    """The first drafts-<n>.md in a folder that does not exist yet (never overwrite)."""
    n = 1  # the first number to try
    while (d / f"{stem}-{n}.md").exists() or (d / f"{stem}-{n}.rejected.md").exists():  # taken when either file exists
        n += 1  # try the next number
    return d / f"{stem}-{n}.md", d / f"{stem}-{n}.rejected.md"  # the drafts file and its rejected twin share the number


def judge(job, letter, md, res, ev_text, kind, orgs, own):
    """Every reason a drafted scene is not kept; an empty list when it passes."""
    with tempfile.TemporaryDirectory() as tmp:  # check this one scene on its own, strictly
        f = pathlib.Path(tmp) / "scene.md"  # a scratch file for the checker
        f.write_text(f"## {letter}. check\n\n" + md, encoding="utf-8")  # under a section heading, as the checker expects
        scenes, bad = check.check_path(job, f, strict=True, orgs=orgs if kind in EXPLAINING else None)  # the parsed scenes and the problems found
    # every problem as a readable reason; no parsed scene at all means the dialogue was missing
    reasons = [i18n.reason(c, **s) for _, probs in bad for c, s in probs] if scenes else ["no dialogue"]
    if scenes:  # a parsed scene: also hold my lines to the evidence
        import factcheck  # the shared claim-strength check, the one resume and cover letter drafts use
        mine = [str(txt) for who, txt in (res.get("lines") or []) if who == "나"]  # only what I would say
        reasons += [factcheck.claim_text(c) for c in factcheck.claim_issues(" ".join(mine), ev_text.splitlines())]  # one reason per overclaim ("led" against "helped")
        gone = check.denials(mine, own)  # a scene must not deny what the person's own documents show
        if gone:  # it does
            reasons.append(i18n.reason("denial", list=", ".join(gone[:8])))  # the names it denies
    return reasons


def model_verify(backend):
    """The real second reading: one llm.run() call for a scene that passed its checks."""
    import llm  # the one door to a model

    def verify(prompt):  # returns {"problems": [...]}
        return llm.run("interview-verify", prompt, system=VERIFY_SYSTEM, want_json=True, required=("problems",), backend=backend, timeout=300)  # shorter than writing
    return verify  # called once per scene


def wrong_claims(verify, source, res):
    """What the second reading found in a scene, each with a quote that is really in it: [{quote, why, fix}]."""
    mine = [str(txt) for who, txt in (res.get("lines") or []) if who == "나"]  # what I would say
    plain = " ".join(" ".join(check.sentences(x)) for x in mine)  # without its speech marks
    around = source.around(plain)  # the evidence around it, as the scene says it
    found = (verify(VERIFY.format(scene=plain, evidence=around)) or {}).get("problems") or []  # the second reading's list
    squeeze = lambda s: re.sub(r"\W+", " ", str(s)).strip().lower()  # noqa: E731  quotes are compared without marks or case
    # a finding whose quote is not in the scene is the model's mistake, not the scene's
    return [x for x in found if isinstance(x, dict) and squeeze(x.get("quote")) and squeeze(x.get("quote")) in squeeze(plain)], around


def main(job, out=None, ids=None, limit=0, backend=None, plan_file=None, ask=None, jobs=1, progress=None, verify=None, cancel=None):
    """Draft scenes; print one line per skipped or rejected entry and the summary. Exit 1 when the model stopped. jobs:
    how many scenes at a time. progress(done, total) is called as each scene is finished. verify: the second reading,
    which defaults to the real model's and is off with a stand-in writer, unless a test passes its own."""
    import llm  # LLMUnavailable
    verify = verify or (model_verify(backend) if ask is None else None)  # a stand-in writer has nothing real to read back
    d = job.out_dir(out)  # the output folder
    pf = pathlib.Path(plan_file) if plan_file else d / "plan.json"  # the question map
    rows = (read_json(pf, {}) or {}).get("questions") if pf.is_file() else planmod.build(job)  # build it when it is missing
    items, _ = corpus.load(job)  # the kit's items
    want = [x.strip() for x in ids.split(",")] if ids else None  # entries picked by hand
    dd = d / "drafts"  # drafts live in the output folder
    done = answered(dd) if dd.is_dir() and not want else set()  # a second run goes on with the questions the first did not reach
    # by default, what no scene or draft covers, the likeliest first
    chosen = [r for r in rows if r["id"] in want] if want else ranked([r for r in rows if r["coverage"] == "none" and r["id"] not in done])
    if limit:  # --limit keeps only the first few
        chosen = chosen[:limit]
    if not chosen:  # nothing to draft
        say(i18n.t("draft_nothing"))  # say so
        return 0  # not an error
    ask = ask or model_ask(backend)  # the model, or a stand-in from a test
    pack = check.style_pack(job)  # the wording rules go into the prompt
    # the banned words as plain words: the regex endings are cut so the model can read them
    banned = ", ".join(w.replace("\\w*", "").replace("(?:e|es|ed|ing)", "e") for w in pack["interview"].get("banned_words", []))
    # the forbidden patterns with their reasons, or "none"
    forbidden = "; ".join(f'{f["pattern"]} ({f.get("why", "")})' for f in pack["interview"].get("forbidden", [])) or "none"
    stories = [it for it in items if it.get("role") == "reference"]  # stories and notes
    source = Evidence(job, stories)  # every passage of the materials, read once
    orgs = check.person_orgs(job)  # a sentence about these companies is a statement of what the person did
    own = check.own_tokens(job)  # the words of the person's own documents, for scenes that deny experience
    nxt, cats = next_ids(items), categories(items)  # new ids and the headings they join
    kit_letters = {**LETTERS, **(job.kit.get("draft_sections") or {})}  # the kit may move kinds to other letters
    kit_letters["asked"] = asked_letter(job, cats, kit_letters, nxt)  # a section of their own, never another one's letter
    lang = i18n.lang()  # headings of new sections in the message language
    planned = []  # (entry, letter, id) in writing order
    for entry in chosen:  # ids are given out first, so they do not depend on which scene finishes first
        letter = kit_letters.get(entry["kind"], "X")  # the section the scene joins
        planned.append((entry, letter, f"{letter}{nxt.get(letter, 1)}"))  # the next free id there
        nxt[letter] = nxt.get(letter, 1) + 1  # the next scene of this letter takes the following number
    dd.mkdir(parents=True, exist_ok=True)  # made on the first run
    path, rpath = free_path(dd, "drafts")  # new files only
    results = {}  # id -> (md, reasons), filled as scenes finish
    stop, lock = threading.Event(), threading.Lock()  # the model stopped; one writer at a time
    why_stopped = []  # why, once
    finished = [0]  # scenes finished, for the progress callback

    def heading(letter):  # the kit's own heading for the letter, else a new one named after the kind that maps to it
        return cats.get(letter) or f"{letter}. {KIND_NAMES[lang].get(next((k for k, v in kit_letters.items() if v == letter), ''), letter)}"

    def save():  # the passing scenes so far, in writing order, so a run that stops part way keeps them
        groups = {}  # letter -> its scenes
        for _, letter, sid in planned:  # in writing order
            md, reasons = results.get(sid, ("", ["waiting"]))  # finished or not
            if not reasons:  # passed
                groups.setdefault(letter, []).append(md)  # grouped by section
        if groups:  # a drafts file only when something passed
            parts = [f"## {heading(letter)}\n\n" + "\n".join(mds) for letter, mds in groups.items()]  # a heading and its scenes
            path.write_text("# drafts\n\n" + "\n".join(parts), encoding="utf-8")  # the whole file each time: it is short, and always whole

    def write(job_entry):  # one scene, in a worker
        entry, letter, sid = job_entry  # which question
        if stop.is_set() or (cancel and cancel()):  # the model stopped for another scene, or the person stopped the run
            return  # not asked again
        ev_text = source.collect(entry)  # computed once: the prompt and the claim check both use it
        # the writing rules with this entry's question, source, evidence and wording rules filled in
        prompt = PROMPT.format(kind=entry["kind"], question=entry["ask"]["en"][0], source=entry["source"], evidence=ev_text, depth=depth_of(entry["kind"]),
                               banned=banned or "none", forbidden=forbidden)  # "none" so no slot is left empty
        md, reasons, tell = f"### {sid}. (no scene)\n", ["no answer"], []  # until the model answers; what the second try is told
        try:
            for attempt in (1, 2):  # a scene that fails is written once more with the reasons in hand
                res = ask(prompt if attempt == 1 else prompt + REPAIR.format(reasons="; ".join(tell)), entry)  # one model call for this scene
                md = scene_md(sid, res) + f"- **근거**: {entry['id']} ({entry['source']})\n"  # the source of the question, hidden on the page
                reasons = judge(job, letter, md, res, ev_text, entry["kind"], orgs, own)  # what the checks say
                # hard to say aloud: worth one more try, but no reason to throw away a true scene
                hard = check.hard_to_say([str(txt) for who, txt in (res.get("lines") or []) if who == "나"]) if attempt == 1 else []
                if not reasons and not hard:  # it passed
                    break
                if attempt == 1:  # the second try is told all of it
                    tell = reasons + hard  # for the request
            if not reasons and verify:  # it passed: read it once against the evidence around what it says
                wrong, around = wrong_claims(verify, source, res)  # what it told wrongly, and the wider evidence
                if wrong:  # something to put right
                    told = "; ".join(f'"{x.get("quote")}": {x.get("why", "")} {x.get("fix", "")}'.strip() for x in wrong)  # each with what the evidence backs
                    fixed = ask(prompt + "\n\n## More evidence\n" + around + REPAIR.format(reasons=told), entry)  # the whole scene again, with the wider evidence
                    fixed_md = scene_md(sid, fixed) + f"- **근거**: {entry['id']} ({entry['source']})\n"  # in the kit's format
                    if not judge(job, letter, fixed_md, fixed, ev_text + "\n" + around, entry["kind"], orgs, own):  # it still passes the checks
                        md = fixed_md  # the corrected scene stands
        except llm.LLMUnavailable as e:  # no model or it stopped: keep what was written
            with lock:  # one reason is enough
                why_stopped.append(str(e))  # reported after the loop
            stop.set()  # no point asking again
            return
        except ValueError as e:  # the answer never had the right form
            md, reasons = f"### {sid}. (no scene)\n", [str(e)]  # a placeholder heading with the reason
        with lock:  # the scenes finish in any order
            results[sid] = (md, reasons)  # kept
            save()  # on disk at once
            finished[0] += 1  # one more
            if progress:  # the panel shows it
                progress(finished[0], len(planned))

    if jobs > 1:  # several at a time
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:  # threads, since each only waits for a model
            list(pool.map(write, planned))  # every scene; an error in a worker comes out here
    else:  # one at a time, in order
        for job_entry in planned:  # each scene
            write(job_entry)  # the same work
    rejected = [(results[sid][0], results[sid][1]) for _, _, sid in planned if sid in results and results[sid][1]]  # [(md, reasons)]
    for _, _, sid in planned:  # the rejected ones in writing order
        if sid in results and results[sid][1]:  # it failed the check
            say(i18n.t("draft_reject", id=sid, why="; ".join(results[sid][1])))  # one line per rejected scene
    written = sum(1 for _, _, sid in planned if sid in results and not results[sid][1])  # scenes that passed
    problems = 0  # the final check of the written file
    if written:  # a drafts file only when something passed
        # the whole file checked once more for its form and wording, as it will be read; grounding was judged scene by scene
        _, bad = check.check_path(job, path, strict=True, orgs=orgs)
        problems = len(bad)  # scenes with problems in the combined file
    if rejected:  # a rejected file only when something failed
        # each rejected scene with its reasons in an HTML comment above it
        rpath.write_text("# rejected drafts\n\n" + "\n".join(f"<!-- {'; '.join(r)} -->\n{md}" for md, r in rejected), encoding="utf-8")
    if why_stopped:  # the model stopped part way
        say(i18n.t("draft_stopped", why=why_stopped[0]))  # say why
    # the summary: scenes written and where, rejected entries, and problems in the final check
    say(i18n.t("draft_summary", written=written, out=path if written else dd, skipped=len(rejected), problems=problems))
    return 1 if why_stopped else 0  # a stopped model is a failure for scripts
