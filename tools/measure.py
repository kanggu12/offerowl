#!/usr/bin/env python3
"""Measure Offerowl on the public fictional example and write the numbers behind the pictures in the docs.

Every number in the README's pictures comes from this script (CONTRIBUTING.md, "Real numbers only"). It runs the
engine on the fictional person of examples/sample_ko.json, the fictional posting of examples/cover/ and the fictional
interview kit of examples/interview/, and writes one JSON file per part to docs/assets/data/:

  drafts.json      the fact check on drafted text: per task, the sentences drafted, kept, rewritten and dropped, and why
  evidence.json    printed sentences that cite their evidence
  firstrun.json    the panel's first run, timed from the page's load to the PDFs on the Desktop, with one file dropped and no AI
  build.json       the documents one profile makes, and the time to typeset each
  interview.json   the example kit: search hit rate, card defects, scene checks, audits against the answer key

Drafting needs a model's words. They come from docs/assets/data/recorded/, the answers of one run of the AI backend
on the example, so a rerun calls no model and gives the same counts:

  python3 tools/measure.py                       every part, from the recorded answers
  python3 tools/measure.py --only drafts,interview
  python3 tools/measure.py --record              ask the AI backend again and keep its answers (about 15 calls)
  python3 tools/measure.py --record --tapes interview,audit   record only the tasks whose prompts changed; the others play back

Timings (firstrun, build) are measured afresh on each run and move a little from run to run; the counts do not.
docs/assets/build.py draws the pictures from these files.
"""
from __future__ import annotations  # `str | None` hints on Python 3.10

import argparse  # the command line
import contextlib  # quiet stdout while the engine prints its own progress
import datetime  # the date of a measurement
import hashlib  # fingerprints of prompts, so a replay can say whether a prompt changed since recording
import io  # the captured progress text
import json  # every data file is JSON
import os  # environment for the child processes
import pathlib  # paths
import platform  # the machine a timing was taken on
import re  # verdict lines and words
import shutil  # temporary folders
import statistics  # the median of repeated timings
import subprocess  # the engine's own commands, as a person runs them
import sys  # the import path and the interpreter
import tempfile  # scratch folders outside the repository
import time  # timings

ROOT = pathlib.Path(__file__).resolve().parent.parent  # the repository
DATA = ROOT / "docs" / "assets" / "data"  # where the numbers go
TAPES = DATA / "recorded"  # the AI backend's recorded answers
EXAMPLE = ROOT / "examples" / "sample_ko.json"  # the fictional person
POSTING = ROOT / "examples" / "cover" / "posting_en.md"  # a fictional posting, with lines the person cannot claim (Rust, CISSP)
PLAN = ROOT / "examples" / "cover" / "plan_en.json"  # the reviewed letter plan for that posting
COVER_STYLE = ROOT / "examples" / "cover" / "style.json"  # the example's style pack for letters
JOB = ROOT / "examples" / "interview" / "jobs" / "gamma-platform"  # the fictional interview kit
KEY = JOB / "expected_findings.json"  # the fictional answer key for its audits
SCENES_TO_DRAFT = 6  # interview scenes drafted per run: enough to see the checks work, few enough to keep calls small
AUDIT_CALLS = 2  # consistency batches of 12 scenes: two cover the example's 15 scenes
FIRST_RUNS = 3  # the first run is timed this many times and the median is kept
SCHEMA = "offerowl-measure/0.1"  # the shape of the data files

sys.path[0:0] = [str(ROOT / "src"), str(ROOT)]  # the engine's flat modules (src/) and the packages under the root (apps/)
os.environ["OFFEROWL_LANG"] = "en"  # the engine's messages in English, so the verdict lines in the data read the same everywhere
import llm  # noqa: E402  the one door to a model; the tape below stands in front of it


# small helpers

def say(msg: str) -> None:
    """One progress line on stderr, so stdout stays for the summary."""
    print(msg, file=sys.stderr, flush=True)  # flushed at once: the heavy parts take minutes


def run(args: list, env: dict | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    """A command of the engine, run from the repository root as the docs show it, in English, at a low priority."""
    full = ["nice", "-n", "15"] + args if shutil.which("nice") else args  # the measurement must not crowd out other work on the PC
    env = {**os.environ, "OFFEROWL_LANG": "en", "PYTHONDONTWRITEBYTECODE": "1", **(env or {})}  # English verdict lines, no .pyc files in the repository
    return subprocess.run(full, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)  # output kept for the verdicts


def last_line(text: str) -> str:
    """The last non-empty line of a command's output: where the engine's commands print their verdict."""
    lines = [x for x in (text or "").splitlines() if x.strip()]  # blank lines carry nothing
    return lines[-1].strip() if lines else ""  # empty output gives an empty verdict


def sha(text: str) -> str:
    """A short fingerprint of a text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]  # sixteen hex digits are plenty to tell prompts apart


def meta(**extra) -> dict:
    """When and where a measurement was taken, kept beside its numbers."""
    return {"schema": SCHEMA, "date": datetime.date.today().isoformat(),  # the date the numbers were taken
            "machine": f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs, Python {platform.python_version()}",  # what the timings ran on
            **extra}  # anything the part adds (renderer, backend)


def save(name: str, data: dict) -> pathlib.Path:
    """Write one data file, sorted and indented so a rerun's changes read well in a diff."""
    DATA.mkdir(parents=True, exist_ok=True)  # the first run makes the folder
    path = DATA / f"{name}.json"  # one file per part
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # readable, with a final newline
    return path


def quiet(fn, *args, **kw):
    """Call an engine function with its progress lines captured; returns (result, captured text)."""
    buf = io.StringIO()  # the engine's prints land here
    with contextlib.redirect_stdout(buf):  # the summary of this script stays readable
        res = fn(*args, **kw)  # the engine's own function
    return res, buf.getvalue()  # the caller may read the verdict from the text


# the recorded answers

class Tape:
    """The AI backend's answers for one task, in front of llm.run(). Recording asks the real backend and keeps every
    answer; playing back serves the kept answers in order, task by task, and calls nothing. It replaces llm.run on the
    module, so every drafting step of the engine (resume, cover letter, interview) goes through it unchanged."""

    def __init__(self, name: str, record: bool):  # one tape per task
        self.name, self.record = name, record  # which task; recording or playing back
        self.path = TAPES / f"{name}.json"  # where the answers live
        self.answers = [] if record else self.load()  # a recording starts empty
        self.queue = list(self.answers)  # what is left to serve in a playback
        self.served = 0  # answers given out
        self.same_prompt = 0  # of them, answers whose prompt is the one recorded
        self.seconds = 0.0  # the backend's time, while recording
        self.real = None  # llm.run as it was before the tape went in

    def load(self) -> list:
        """The recorded answers; a missing tape stops with the command that makes it."""
        if not self.path.is_file():  # nothing was recorded yet
            raise SystemExit(f"no recorded answers in {self.path.relative_to(ROOT)}: run `python3 tools/measure.py --record` once")
        return json.loads(self.path.read_text(encoding="utf-8"))["answers"]  # the answers in the order they were given

    def run(self, task: str, prompt: str, **kw):
        """The stand-in for llm.run: same arguments, same results, and the same two errors."""
        if self.record:  # ask the real backend and keep its answer
            t0 = time.time()  # the call's own time
            try:
                out = self.real(task, prompt, **kw)  # the engine's own call, with its retries and JSON checks
            except ValueError as e:  # it answered, but never in the required shape: the engine handles that
                self.answers.append({"task": task, "prompt": sha(prompt), "error": str(e)[:300]})  # kept, so a playback fails the same way
                raise  # the engine carries on as it would
            finally:
                self.seconds += time.time() - t0  # failures take time too
            self.answers.append({"task": task, "prompt": sha(prompt), "answer": out})  # kept in order
            self.save()  # after every answer, so a stop part way keeps what came back
            return out
        for i, a in enumerate(self.queue):  # playback: the next kept answer of this task
            if a["task"] == task:  # tasks are served in their own order, as the engine's replay does
                self.queue.pop(i)  # each answer is used once
                self.served += 1  # counted for the report
                self.same_prompt += a["prompt"] == sha(prompt)  # an unchanged prompt means the replay is exact
                if "error" in a:  # the backend failed here when it was recorded
                    raise ValueError(a["error"])  # the engine sees the same failure
                return a["answer"]
        raise llm.LLMUnavailable(f"no recorded answer left for {task}")  # the engine stops this task as it would without a model

    def save(self) -> None:
        """Write the recording, with the backend that gave it."""
        TAPES.mkdir(parents=True, exist_ok=True)  # the first recording makes the folder
        name, _why = llm.chosen()  # the backend in use (the default order or OFFEROWL_LLM)
        body = {"schema": SCHEMA, "task": self.name, "backend": name, "recorded": datetime.date.today().isoformat(),  # who answered, and when
                "seconds": round(self.seconds, 1), "answers": self.answers}  # the backend's time and every answer
        self.path.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # readable in a review

    def __enter__(self):  # the tape goes in front of llm.run for one task
        self.real, llm.run = llm.run, self.run  # every module calls llm.run by attribute, so this reaches all of them
        return self

    def __exit__(self, *exc):  # and comes out again
        llm.run = self.real  # the real door is back
        if self.record:  # a recording is written even when the task failed part way
            self.save()
        return False  # errors are not swallowed

    def report(self) -> dict:
        """What the tape did, for the data file."""
        body = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}  # the recording's own facts
        return {"backend": body.get("backend"), "recorded": body.get("recorded"), "calls": len(self.answers),  # who answered, when, how often
                "model_seconds": body.get("seconds"),  # the backend's time when it was recorded
                "served": self.served if not self.record else len(self.answers),  # answers used in this run
                "same_prompt": self.same_prompt if not self.record else len(self.answers)}  # prompts unchanged since the recording


# why a draft was stopped

# The checks' codes, grouped into the reasons the pictures show. The codes come from src/write_resume.py (resume),
# src/cover.py (cover letter) and src/interview/check.py (interview scenes).
REASONS = {
    "number": "number", "number_word": "number", "numbers": "number",  # a number or a counted amount the evidence does not state
    "name": "name", "org": "name", "name_src": "name", "names": "name",  # a name the evidence does not hold (tools are split off below)
    "gap_term": "tool",  # a tool the posting asks for and the profile never shows
    "claim": "claim",  # a part stronger than the evidence ("led" where it says "helped")
    "no_ev": "evidence", "unknown_id": "evidence", "frame_where": "evidence", "frame_ev": "evidence", "empty": "evidence",  # no usable evidence id
    "start": "form", "no_tr": "form", "tr_ko": "form", "marks": "form", "slash_end": "form",  # a scene's dialogue form
}
FACT_REASONS = ("number", "name", "tool", "claim", "evidence")  # the reasons that mean "not supported by the evidence"
ORDER = ("number", "name", "tool", "claim", "evidence", "style", "form")  # the order the pictures list them in


def tool_words() -> set:
    """Lowercase words that name a tool: cover.py's list of known tools and the example profile's own skills."""
    import cover as C  # the engine's list of tool names
    words = {w.lower() for w in C.TOOLS}  # the known tools
    prof = json.loads(EXAMPLE.read_text(encoding="utf-8"))  # the example's skills name its tools
    for row in prof.get("skills") or []:  # each skills row
        for item in (row.get("items") if isinstance(row, dict) else row[1:] if isinstance(row, list) else []) or []:  # its items
            words |= {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*", str(item))}  # each Latin word of an item
    return words


TOOLS: set = set()  # filled once the engine is importable


def reason(code: str, detail: str = "") -> str:
    """The reason group of one issue: a name that is a tool counts as a tool, style codes as style."""
    kind = REASONS.get(code)  # the fact and form codes
    if kind == "name":  # a name: a tool when its words are tool names
        words = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*", detail or "")}  # the words the issue names
        return "tool" if words & TOOLS else "name"
    return kind or "style"  # every other code of the checks is about wording (banned words, length, highlights)


# part: drafts

def draft_resume(tape: Tape) -> tuple[dict, dict, dict]:
    """The resume draft of the example for the posting, through src/write_resume.py. Returns (counts, record, new profile)."""
    import write_resume as W  # the drafting step
    prof = json.loads(EXAMPLE.read_text(encoding="utf-8"))  # the fictional person, never changed
    with tape:  # the model's words come from the tape
        new, rec = W.draft(prof, posting_text=POSTING.read_text(encoding="utf-8"), style=W.load_style(None), langs=("ko", "en"))  # every part, both languages
    out = {"task": "resume", "unit": "sentences", "drafted": 0, "kept": 0, "rewritten": 0, "dropped": 0, "stopped": 0,  # the counts the chart draws
           "unsupported": 0, "reasons": {k: 0 for k in ORDER}, "checked": 0}  # stopped for a fact; why texts were stopped; checks that ran
    for e in rec["texts"]:  # every text the model wrote, in both languages
        first = e.get("first") or e  # the first round's text and issues (a repaired text keeps them under "first")
        codes = [(i["code"], i.get("detail", "")) for i in first["issues"] if i["code"] in W.FACT_CODES | W.STYLE_CODES | W.CLAIM_CODES]  # polish never stops a text
        out["drafted"] += 1  # one text drafted
        out["checked"] += 2 if e.get("first") else 1  # a rewritten text was checked twice
        kinds = {reason(c, d) for c, d in codes}  # each reason once per text
        if codes:  # the first version was stopped
            out["stopped"] += 1  # it never reached the page as written
            out["unsupported"] += bool(kinds & set(FACT_REASONS))  # stopped for a fact the evidence lacks, not for wording
            for k in kinds:
                out["reasons"][k] += 1
        if e.get("gone"):  # still failing after the repair round: not printed
            out["dropped"] += 1
        elif codes:  # stopped, then rewritten from the same evidence and passed
            out["rewritten"] += 1
        else:  # passed as the model first wrote it
            out["kept"] += 1
    out["calls"] = rec["calls"]  # model calls the draft made
    return out, rec, new


def draft_cover(tape: Tape) -> tuple[dict, dict]:
    """The cover letter of the example for the posting's reviewed plan, through src/cover.py. Returns (counts, letter)."""
    import cover as C  # the cover letter
    prof = json.loads(EXAMPLE.read_text(encoding="utf-8"))  # the same person
    plan = json.loads(PLAN.read_text(encoding="utf-8"))  # the reviewed plan of the posting
    with tape:  # the model's words come from the tape
        cov = C.draft(prof, plan, style=C.load_style(str(COVER_STYLE)))  # the letter, its dropped sentences and its stats
    firsts = [a["answer"] for a in tape.answers if a["task"] == "cover-draft" and isinstance(a.get("answer"), dict)]  # the first draft as the model wrote it
    repairs = [a["answer"] for a in tape.answers if a["task"] == "cover-repair" and isinstance(a.get("answer"), dict)]  # the repair round's answer
    count = lambda ans: sum(len(C.as_list(p.get("sentences"))) for a in ans for p in C.as_list(a.get("paragraphs")) if isinstance(p, dict))  # sentences in answers
    out = {"task": "cover", "unit": "sentences", "drafted": count(firsts[:1]), "rewritten_drafted": count(repairs[:1]),  # first draft and repair round
           "reasons": {k: 0 for k in ORDER}, "trimmed": 0, "stopped": 0, "unsupported": 0}  # why sentences were stopped; cut for length
    for d in cov["dropped"]:  # every sentence that did not make it
        if d.get("round") == "trim":  # cut to fit one page, not stopped by a check
            out["trimmed"] += 1
            continue
        kinds = {reason(i["code"], i.get("detail", "")) for i in d["issues"]}  # each reason once per sentence
        out["stopped"] += 1  # stopped by the fact or style check
        out["unsupported"] += bool(kinds & set(FACT_REASONS))  # stopped for a fact the evidence lacks
        for k in kinds:
            out["reasons"][k] += 1
    out["printed"] = sum(len(p["sentences"]) for p in cov["paragraphs"])  # sentences printed: a repair round may write more than it replaces
    out["kept"] = out["drafted"] - out["stopped"]  # of the first draft, what passed as written (the chart's bar adds up to what was drafted)
    out["checked"] = out["drafted"] + out["rewritten_drafted"]  # every sentence of both rounds was checked
    out["unresolved"] = len(cov.get("unresolved") or [])  # what the letter still lacks (check fails on these)
    out["calls"] = cov.get("stats", {}).get("calls")  # model calls the letter made
    return out, cov


def draft_scenes(tape: Tape, out_dir: pathlib.Path) -> dict:
    """Interview scenes for the example kit's uncovered questions, through src/interview/draft.py. Returns the counts.
    The reasons are read from the checks themselves: check.check_path and factcheck.claim_issues are watched while
    each drafted scene is checked, and their results are kept as they are. A scene can be checked more than once (written
    again after a failed check, or after the second reading), so the checks are grouped by the scene's id, and whether it
    was kept or dropped is read from the files the command wrote."""
    from interview import check as K, draft as D, i18n as I  # the checker, the writer, the messages
    from interview.job import Job  # the job folder
    import factcheck as F  # the claim-strength check the scene drafts use
    job = Job(str(JOB))  # the fictional kit
    I.use("en")  # English messages, whatever the kit's own language
    seen = {}  # scene id -> [[(code, detail)] per check, in order]
    last = []  # the id of the scene checked last, for the claim check that follows it
    real_check, real_claims = K.check_path, F.claim_issues  # the checks as they are

    def check_path(j, f, *a, **kw):  # the same function, watched
        scenes, bad = real_check(j, f, *a, **kw)  # the real result
        if pathlib.Path(f).name == "scene.md":  # one drafted scene checked on its own (the combined file comes later)
            m = re.search(r"^### (\S+?)\.", pathlib.Path(f).read_text(encoding="utf-8"), re.M)  # its id
            sid = m.group(1) if m else f"?{len(seen)}"  # a scene with no heading still counts once
            codes = [(c, str(s.get("list") or s.get("word") or "")) for _, probs in bad for c, s in probs]  # its codes and the words they name
            seen.setdefault(sid, []).append(codes if scenes else [("start", "no dialogue")])  # a scene with no dialogue fails on its form
            last[:] = [sid]  # the claim check that follows belongs to it
        return scenes, bad

    def claim_issues(text, blocks):  # the same function, watched
        res = real_claims(text, blocks)  # the real result
        if last:  # the claim check follows the scene's own check
            seen[last[0]][-1] += [("claim", c.get("claim", "")) for c in res]  # one claim issue per overclaim
        return res

    K.check_path, F.claim_issues = check_path, claim_issues  # watched for this task only
    try:
        with tape:  # the model's words come from the tape
            _, text = quiet(D.main, job, out=str(out_dir), limit=SCENES_TO_DRAFT)  # the uncovered questions, a few
    finally:
        K.check_path, F.claim_issues = real_check, real_claims  # the checks as they were
    files = sorted((out_dir / "drafts").glob("drafts-*.md"))  # what the command wrote
    ids_in = lambda rejected: {m for f in files if f.name.endswith(".rejected.md") == rejected  # noqa: E731
                               for m in re.findall(r"^### (\S+?)\.", f.read_text(encoding="utf-8"), re.M)}  # the scenes of each kind of file
    kept_ids, dropped_ids = ids_in(False), ids_in(True)  # passed, and rejected
    for sid in dropped_ids - set(seen):  # an answer that never had a scene's shape is rejected unchecked
        seen[sid] = [[("start", "no scene")]]
    out = {"task": "interview", "unit": "scenes", "drafted": len(kept_ids | dropped_ids), "kept": 0, "rewritten": 0, "dropped": 0, "stopped": 0,  # scenes, not sentences:
           "unsupported": 0, "reasons": {k: 0 for k in ORDER}, "checked": len(kept_ids | dropped_ids),  # a scene is kept or rejected whole
           "verdict": last_line(text).replace(str(out_dir), "<out>")}  # the command's own summary, without the scratch path
    for sid in sorted(kept_ids | dropped_ids):  # each drafted scene
        checks = seen.get(sid, [[]])  # its checks in order
        kinds = {reason(c, d) for codes in checks for c, d in codes}  # each reason once per scene
        if any(checks):  # some check stopped it
            out["stopped"] += 1  # stopped at least once
            out["unsupported"] += bool(kinds & set(FACT_REASONS))  # stopped for a fact the evidence lacks
            for k in kinds:
                out["reasons"][k] += 1
        if sid in dropped_ids:  # rejected: it goes to the rejected file, not the kit
            out["dropped"] += 1
        elif any(checks):  # stopped, then written again and kept
            out["rewritten"] += 1
        else:
            out["kept"] += 1  # passed every check as first written
    out["calls"] = tape.served if not tape.record else len(tape.answers)  # the writing calls and the second readings
    return out


def audit_scenes(tape: Tape, out_dir: pathlib.Path) -> dict:
    """The example kit's audits with the model's consistency pass, scored against the answer key."""
    from interview import audit as A, i18n as I  # the audits, the messages
    from interview.job import Job  # the job folder
    job = Job(str(JOB))  # the fictional kit
    I.use("en")  # English messages
    with tape:  # the model's words come from the tape
        _, text = quiet(A.main, job, out=str(out_dir), consistency=True, calls=AUDIT_CALLS, key=str(KEY))  # coverage, claims, consistency, scored
    rec = json.loads((out_dir / "recall.json").read_text(encoding="utf-8"))  # the score against the key
    verdict = next((x.strip() for x in text.splitlines() if "answer key" in x), last_line(text))  # the line that scores the audit
    return {"found": rec["recall"]["found"], "key": rec["recall"]["key"], "flags": rec["precision"]["findings"], "verdict": verdict,  # how many of the key's findings the audit found, and how much it flags
            "parts": {k: {"key": v.get("key"), "found": v.get("found")} for k, v in rec["parts"].items() if "key" in v}}


def part_drafts(record: bool, tapes_to_record=None) -> None:
    """The fact check on drafted text, the evidence of printed sentences, and the audit with the model's pass.
    tapes_to_record: with record, only these tasks ask the backend again; the others play back."""
    TOOLS.update(tool_words())  # the tool names, now that the engine is importable
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-measure-"))  # interview outputs stay out of the repository
    try:
        tapes = {n: Tape(n, record and (not tapes_to_record or n in tapes_to_record)) for n in ("resume", "cover", "interview", "audit")}  # one tape per task
        say("drafts: resume")
        resume, rec, new = draft_resume(tapes["resume"])  # the resume draft
        say("drafts: cover letter")
        cover, cov = draft_cover(tapes["cover"])  # the cover letter
        say("drafts: interview scenes")
        scenes = draft_scenes(tapes["interview"], tmp / "draft")  # the interview scenes
        say("drafts: interview audit")
        audit = audit_scenes(tapes["audit"], tmp / "audit")  # the audit with the model's pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # nothing is left behind
    tasks = [resume, cover, scenes]  # the chart's rows, in the order of an application
    calls = {n: t.report() for n, t in tapes.items()}  # what each tape did
    checked = sum(t["checked"] for t in tasks)  # every check that ran on drafted text
    stopped = sum(t["stopped"] for t in tasks)  # stopped for any reason
    unsupported = sum(t["unsupported"] for t in tasks)  # stopped for a fact the evidence lacks
    save("drafts", {"meta": meta(), "tasks": tasks, "checked": checked, "stopped": stopped,  # the chart and the stats strip
                    "unsupported": unsupported, "tapes": calls, "audit": audit})
    linked = rec["check"]  # the independent check of the drafted profile (write_resume.check_profile)
    cover_ev = sum(1 for p in cov["paragraphs"] for s in p["sentences"] if s.get("ev"))  # letter sentences that cite evidence
    cover_frame = sum(1 for p in cov["paragraphs"] for s in p["sentences"] if not s.get("ev") and s.get("frame"))  # framing sentences (opening, closing)
    cover_all = sum(len(p["sentences"]) for p in cov["paragraphs"])  # every printed sentence of the letter
    save("evidence", {"meta": meta(), "resume": {"fields": linked["fields"], "sentences": linked["sentences"],  # printed fields and their linked sentences
                                                 "unlinked": len(linked["unlinked"]), "fact_flags": len(linked["facts"]),  # text no sentence covers; facts the evidence lacks
                                                 "claim_flags": len(linked["claims"]), "ok": linked["ok"]},
                      "cover": {"sentences": cover_all, "with_evidence": cover_ev, "framing": cover_frame},  # the letter's sentences
                      "printed": linked["sentences"] + cover_all, "with_evidence": linked["sentences"] + cover_ev})  # both together
    say(f"drafts: {checked} checks, {stopped} stopped, {unsupported} unsupported; resume {linked['sentences']} linked sentences")


# part: interview

def part_interview() -> None:
    """The example kit, measured as a person would: scene checks, search hit rate, card defects, the rule audits."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-measure-iv-"))  # the commands' outputs stay out of the repository
    cli = [sys.executable, "src/interview/cli.py"]  # the kit's own command
    job = ["--job", str(JOB.relative_to(ROOT)), "--out", str(tmp)]  # the example job, outputs to the scratch folder
    try:
        say("interview: check")
        chk = run(cli + ["check"] + job)  # the scene checks
        m = re.search(r"checked (\d+) scenes \(of (\d+) items\), problems (\d+)", chk.stdout)  # the documented verdict line
        if not m:  # a changed verdict line must not pass silently
            raise SystemExit("interview check gave no verdict: " + last_line(chk.stdout + chk.stderr))
        say("interview: eval")
        ev = run(cli + ["eval"] + job)  # the search hit rate in the real page
        e = json.loads((tmp / "eval.json").read_text(encoding="utf-8"))  # its numbers
        say("interview: cards")
        cards = run(cli + ["cards", "--size", "2560x1300", "--size", "1440x900", "--size", "390x844"] + job)  # card defects at a wide screen, a laptop and a phone
        c = json.loads((tmp / "cards.json").read_text(encoding="utf-8"))  # per size
        say("interview: plan and audit")
        run(cli + ["plan"] + job)  # the question map
        plan = json.loads((tmp / "plan.json").read_text(encoding="utf-8"))  # its questions
        au = run(cli + ["audit", "--key", str(KEY.relative_to(ROOT))] + job, env={"OFFEROWL_LLM": "none"})  # coverage and claims, rules only
        rec = json.loads((tmp / "recall.json").read_text(encoding="utf-8"))  # scored against the key
        a = json.loads((tmp / "audit.json").read_text(encoding="utf-8"))  # the coverage table
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # nothing is left behind
    rows = a["coverage"]["rows"] if isinstance(a.get("coverage"), dict) and "rows" in a["coverage"] else a.get("coverage", [])  # the posting lines and their rating
    rating = [r.get("rating") or r.get("level") for r in rows if isinstance(r, dict)]  # strong, weak or none per line
    kinds = {}  # questions per kind in the map
    for q in plan.get("questions", []):  # each planned question
        kinds[q["kind"]] = kinds.get(q["kind"], 0) + 1
    save("interview", {"meta": meta(), "scenes": int(m.group(1)), "items": int(m.group(2)), "problems": int(m.group(3)),  # the scene checks
                       "eval": {"n": e["n"], "top1": e["top1"], "top3": e["top3"], "size": e.get("size")},  # search hit rate
                       "cards": [{"w": s["w"], "h": s["h"], "cards": s["cards"], "bad": len(s["bad"])} for s in c["sizes"]],  # card defects per window size
                       "plan": {"questions": len(plan.get("questions", [])), "kinds": kinds},  # the question map
                       "coverage": {"lines": len(rating), "strong": rating.count("strong"), "weak": rating.count("weak"), "none": rating.count("none")},
                       "key": {"found": rec["recall"]["found"], "key": rec["recall"]["key"], "flags": rec["precision"]["findings"]},  # the rule audits against the answer key, and how much they flag
                       "verdicts": {"check": last_line(chk.stdout), "eval": last_line(ev.stdout), "cards": [x for x in cards.stdout.splitlines() if " cards " in x],
                                    "audit": next((x.strip() for x in au.stdout.splitlines() if "answer key" in x), "")}})  # the line that scores the audit
    say(f"interview: {m.group(1)} scenes, eval top-1 {e['top1']}/{e['n']}, top-3 {e['top3']}/{e['n']}")


# part: the first run

def first_run_once(pw) -> dict:
    """One timed first run in a fresh data folder: the panel opens, the example's file is dropped, and the run makes the
    PDFs and copies them to the Desktop, with no AI. Timed from the page's load to the run's end."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-measure-panel-"))  # a fresh data folder and home: a true first run
    data, home = tmp / "data", tmp / "home"  # the panel's folder; a home with no agent login in it
    data.mkdir(parents=True)  # made before the server starts, so the setting below is read
    home.mkdir()  # nothing in it: no agent signs in
    (data / "settings.json").write_text(json.dumps({"backend": "none"}), encoding="utf-8")  # the AI off, as the measured claim says
    env = {**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1",  # the panel's world
           "OFFEROWL_DESKTOP": str(tmp / "Desktop")}  # the run's PDFs land here, never on the person's own Desktop
    for k in ("OFFEROWL_PANEL_AGENT", "OFFEROWL_PANEL_BACKEND", "OFFEROWL_LLM"):  # nothing from the caller's shell may turn an agent on
        env.pop(k, None)
    srv = subprocess.Popen([sys.executable, str(ROOT / "apps" / "panel" / "server.py"), "--port", "0", "--data", str(data)],
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")  # its first printed line is the address
    try:
        base = srv.stdout.readline().strip()  # the panel's address
        browser = pw.chromium.launch()  # headless: no window on the desktop
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR",  # a laptop window, a Korean browser
                                  bypass_csp=True)  # the waits evaluate their conditions; the panel itself allows no eval
        page = ctx.new_page()  # one tab
        t0 = time.time()  # the clock starts at the page's load
        page.goto(base + "?lang=ko")  # the panel opens on making
        page.wait_for_selector(".make-in .drop")  # the place to drop files
        page.set_input_files("#filepick", str(EXAMPLE))  # the example's file, as if dropped: the one action
        page.wait_for_function("S && (S.runs || []).length > 0 && S.tasks.autopilot && S.tasks.autopilot.state !== 'running'",
                               timeout=600000, polling=100)  # the run ended
        seconds = time.time() - t0  # from the page's load to the PDFs on the Desktop
        run = page.evaluate("S.runs[0]")  # what it made
        facts = page.evaluate("S.facts && S.facts.counts ? S.facts.counts : null")  # the facts the file gave
        browser.close()
        return {"seconds": round(seconds, 2), "actions": 1, "files": len(run.get("files") or []), "state": run.get("state"), "facts": facts}
    finally:
        srv.terminate()  # the panel stops
        srv.wait(10)
        shutil.rmtree(tmp, ignore_errors=True)  # and its folder goes


def part_firstrun() -> None:
    """The panel's first run, timed a few times; the median is the number shown."""
    from playwright.sync_api import sync_playwright  # the browser driver (pip install playwright)
    runs = []  # one result per run
    with sync_playwright() as pw:  # one driver for every run
        for i in range(FIRST_RUNS):  # fresh data each time
            say(f"firstrun: run {i + 1} of {FIRST_RUNS}")
            runs.append(first_run_once(pw))
    secs = [r["seconds"] for r in runs]  # the timings
    save("firstrun", {"meta": meta(backend="none"), "runs": secs, "median": round(statistics.median(secs), 1),  # the number the stats strip shows
                      "actions": runs[0]["actions"], "files": runs[0]["files"], "state": runs[0]["state"], "facts": runs[0]["facts"]})  # one drop, the PDFs it put on the Desktop
    say(f"firstrun: median {statistics.median(secs):.1f} s over {len(secs)} runs, {runs[0]['actions']} actions")


# part: build

def part_build() -> None:
    """Everything one profile makes, typeset with the renderer in use, each timed: the resume (DOCX, PDF), the deck
    (PDF), the cover letter (DOCX, PDF) and the interview kit's cue cards (PDF)."""
    import resume as R  # the build functions of `offerowl build`
    renderer = R.renderer()  # container (the default) or html
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-measure-build-"))  # job files and the kit's output
    docs = []  # one row per document

    def timed(kind, fn):  # one document, timed; returns its result
        t0 = time.time()
        res = fn()
        docs.append({"kind": kind, "seconds": round(time.time() - t0, 1)})
        return res

    try:
        job = tmp / "job.json"  # the output name keeps the measurement apart from other builds in output/
        job.write_text(json.dumps({"out": "measure_resume_ko", "lang": "ko"}), encoding="utf-8")
        say(f"build: resume ({renderer})")
        pdf = timed("resume", lambda: R.build(str(EXAMPLE), str(job)))  # the resume, DOCX then PDF
        docs[-1]["files"] = [p.name for p in (pdf.with_suffix(".docx"), pdf) if p.exists()]
        docs[-1]["pages"] = pdf_pages(pdf)
        say("build: deck")
        deck = timed("deck", lambda: R.build_deck(str(EXAMPLE), str(job)))  # the 16:9 deck
        docs[-1]["files"] = [deck.name] if deck.exists() else []
        docs[-1]["pages"] = pdf_pages(deck)
        say("build: cover letter")
        import cover as C  # the cover letter's build
        cjob = tmp / "cover_job.json"  # the letter's settings: the example's own, with an output name of this script
        cjob.write_text(json.dumps({**json.loads((ROOT / "examples" / "cover" / "job_en.json").read_text(encoding="utf-8")), "out": "measure_cover_en"}), encoding="utf-8")
        info, _ = timed("cover", lambda: quiet(C.build, str(EXAMPLE), str(ROOT / "examples" / "cover" / "cover_en.json"), str(cjob), str(tmp / "cover")))
        docs[-1]["files"] = [pathlib.Path(info["docx"]).name, pathlib.Path(info["pdf"]).name]
        docs[-1]["pages"] = info["pages"]
        say("build: interview cue cards")
        cue = timed("interview", lambda: run([sys.executable, "src/interview/cli.py", "cue", "--job", str(JOB.relative_to(ROOT)), "--out", str(tmp / "kit"), "--pdf"]))
        docs[-1]["files"] = [p.name for p in sorted((tmp / "kit").glob("cue_cards.*")) if p.suffix in (".html", ".pdf")]
        docs[-1]["pages"] = pdf_pages(tmp / "kit" / "cue_cards.pdf")
        docs[-1]["verdict"] = last_line(cue.stdout.replace(str(tmp), "<out>"))
        say("build: the document check of the resume and the deck")
        rc, check_text = quiet(R.check, str(EXAMPLE), str(job), pdf, deck)  # the same check `offerowl build` runs after building
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # the scratch folder goes; the PDFs stay in output/ (ignored by git)
    files = sum(len(d["files"]) for d in docs)  # every file made
    save("build", {"meta": meta(renderer=renderer), "documents": docs, "kinds": len(docs), "files": files,  # the stats strip and the build chart
                   "seconds": round(sum(d["seconds"] for d in docs), 1), "check": last_line(check_text), "check_exit": rc})
    say(f"build: {len(docs)} kinds, {files} files, {sum(d['seconds'] for d in docs):.0f} s with the {renderer} renderer")


def pdf_pages(path: pathlib.Path) -> int | None:
    """Pages of a PDF, read from its page objects (no external tool needed)."""
    if not path or not pathlib.Path(path).is_file():  # nothing was made
        return None
    raw = pathlib.Path(path).read_bytes()  # the file as bytes
    n = len(re.findall(rb"/Type\s*/Page[^s]", raw))  # one page object per page
    return n or None  # a compressed object stream hides them: unknown rather than wrong


# command line

PARTS = {"drafts": part_drafts, "interview": part_interview, "firstrun": part_firstrun, "build": part_build}  # in the order they run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="measure.py", description="Measure Offerowl on the fictional example and write docs/assets/data/*.json.")
    ap.add_argument("--only", default="", help="parts to run, comma separated: " + ", ".join(PARTS))  # a part at a time
    ap.add_argument("--record", action="store_true", help="ask the AI backend again for the drafts and keep its answers")  # the only mode that calls a model
    ap.add_argument("--tapes", default="", help="with --record, only these tasks ask again: resume, cover, interview, audit")  # a prompt change touches one task, not all four
    a = ap.parse_args(argv)
    names = [x.strip() for x in a.only.split(",") if x.strip()] or list(PARTS)  # every part by default
    bad = [x for x in names if x not in PARTS]  # a typo stops here
    if bad:
        ap.error("unknown part: " + ", ".join(bad))
    if a.record and "drafts" not in names:  # recording only makes sense for the drafts
        ap.error("--record goes with the drafts part")
    tapes = [x.strip() for x in a.tapes.split(",") if x.strip()]  # the tasks to record again
    if [x for x in tapes if x not in ("resume", "cover", "interview", "audit")] or (tapes and not a.record):  # a typo, or a choice that records nothing
        ap.error("--tapes takes resume, cover, interview or audit, together with --record")
    t0 = time.time()
    for name in names:  # each part writes its own file
        if name == "drafts":
            part_drafts(a.record, tapes)
        else:
            PARTS[name]()
    print(f"measure: {', '.join(names)} written to {DATA.relative_to(ROOT)} in {time.time() - t0:.0f} s")  # the verdict line
    return 0


if __name__ == "__main__":
    sys.exit(main())
