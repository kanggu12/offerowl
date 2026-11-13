#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measure the decision backends on graded sets (docs/DECISIONS.md).

    python3 tests/decide/evaluate.py --out DIR [--private sets.json] [--backends rules,agent,laya:multilingual,...]
    python3 tests/decide/evaluate.py --out DIR --report          tables from the results already in DIR

Every backend runs in a process of its own, so its peak memory is its own. The sets:
  public    the repository's fictional examples: posting lines by section (line_kind), the example kit's answer key
            and the reviewed cover plans (coverage), the planted claim cases of tests/write and a fictional set
            (claim), and fictional statement pairs (contradiction)
  private   a JSON list in the same form, naming files you keep outside the repository, such as your own kit and
            its answer key, a posting, or statement pairs

Results go to DIR: sets.json (the built items), raw-<backend>.json (every decision), results.json and results.md.
The agent's answers are cached in DIR/agent_cache, so a rerun asks the model nothing again.
"""
import argparse  # the command line
import importlib.util  # read the planted cases of tests/write without running that test
import json  # sets and results
import os  # the environment of the child processes
import pathlib  # paths
import re  # Hangul and word tests
import statistics  # medians
import subprocess  # one process per backend
import sys  # the import path and this Python
import time  # wall time

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
import cover  # noqa: E402  posting parser, profile units and word matching
import decide as D  # noqa: E402  the interface

HANGUL = re.compile(r"[가-힣]")  # Korean letters

# The public sets: (name, task, how to build it, its sources relative to the repository)
PUBLIC = [
    {"name": "kind-example-en", "task": "line_kind", "build": "postings",
     "files": ["examples/cover/posting_en.md", "examples/interview/jobs/gamma-platform/posting.md", "tests/write/fixtures/posting_en.md"]},
    {"name": "kind-example-ko", "task": "line_kind", "build": "postings",
     "files": ["examples/cover/posting_ko.md", "tests/app/fixtures/posting_ko.md"]},
    {"name": "coverage-kit-example", "task": "coverage", "build": "kit",
     "job": "examples/interview/jobs/gamma-platform", "key": "examples/interview/jobs/gamma-platform/expected_findings.json"},
    {"name": "coverage-plan-example-en", "task": "coverage", "build": "plan", "profile": "examples/sample_ko.json",
     "plan": "examples/cover/plan_en.json", "posting": "examples/cover/posting_en.md"},
    {"name": "coverage-plan-example-ko", "task": "coverage", "build": "plan", "profile": "examples/sample_ko.json",
     "plan": "examples/cover/plan_ko.json", "posting": "examples/cover/posting_ko.md"},
    {"name": "claim-planted", "task": "claim", "build": "cases", "file": "tests/write/test_claims.py"},
    {"name": "claim-example", "task": "claim", "build": "json", "file": "tests/decide/fixtures/claims_example.json"},
    {"name": "pairs-example", "task": "contradiction", "build": "json", "file": "tests/decide/fixtures/pairs_example.json"},
]
# Cases of tests/write/test_claims.py that sit outside its CASES list (the message, blocks and no-claim tests)
EXTRA_CLAIMS = [("Built the user dashboard.", "동료가 만든 대시보드 구축을 도왔다", True),
                (" Built the user dashboard.", ["사용자 대시보드를 구축했다", "로그 수집은 팀과 함께 진행했다"], False),
                ("Wrote down the on-call steps.", "팀이 온콜을 맡았다", False)]
GAP = {"weak", "none"}  # coverage ratings that flag a posting line as a gap
POSITIVE = {"line_kind": None, "coverage": "gap", "claim": "overclaim", "contradiction": "contradiction"}  # the class a binary F1 is about


def lang_of(*texts) -> str:
    """en, ko, or ko-en for a mix (a Korean side and an English side)."""
    has = [bool(HANGUL.search(str(t or ""))) for t in texts]  # which sides hold Korean
    return "ko" if all(has) else "en" if not any(has) else "ko-en"


def path(p, base=ROOT) -> pathlib.Path:
    """A source path: absolute as given, else relative to the repository."""
    q = pathlib.Path(p).expanduser()  # ~ works in a private manifest
    return q if q.is_absolute() else base / q


# ---------------------------------------------------------------- building the sets

def build_postings(spec) -> list:
    """One item per posting line, labelled by the section heading the parser found; the backends see the line alone."""
    out = []  # items
    for f in spec["files"]:  # each posting
        for i, it in enumerate(cover.parse_posting(path(f).read_text(encoding="utf-8"))["items"]):  # lines with their kinds
            out.append({"id": f"{pathlib.Path(f).parent.name}/{pathlib.Path(f).stem}#{i + 1}", "gold": it["kind"], "lang": lang_of(it["text"]),
                        "input": {"text": it["text"]}})
    return out


def build_kit(spec) -> list:
    """One item per posting line of a kit: the line, its closest scenes (the audit judge's candidates), the answer
    key's verdict (gap or covered) and the audit rule's rating over the whole kit. Scenes named in `exclude` are left
    out of the kit first: they were written after the person's audit, so the key does not know them."""
    from interview import audit, corpus  # the kit, the audit and its coverage rule
    from interview.job import Job  # the job folder
    job = Job(str(path(spec["job"])), kit=str(path(spec["kit"])) if spec.get("kit") else None)  # the kit's settings
    skip = set(spec.get("exclude") or [])  # scenes the key predates
    items, alts = corpus.load(job)  # every item of the kit
    items = [it for it in items if it["id"] not in skip]  # the kit as the person audited it
    rows = [(n, line, rating, by) for n, _sec, line, rating, by in audit.coverage(job, items, alts)]  # the audit's rule over the kit as audited
    answers = {k: v for k, v in audit.scene_answers(job).items() if k not in skip}  # my lines of every scene
    real = {it["id"] for it in items if it.get("role") in ("scenes", "deep")}  # items that can answer a line
    idx = audit.Related({i: answers[i][1] for i in real if i in answers})  # rare-word index, as the judge builds it
    key = json.loads(path(spec["key"]).read_text(encoding="utf-8"))  # the person's findings
    gaps = [set(audit._words(g.get("posting_line", ""))) for g in key.get("coverage_gaps") or []]  # each key line's words
    out = []  # items
    for n, line, rating, by in rows:  # each posting line
        ids = [i for i, _ in by if i in real][:2]  # the rule's covering scenes first
        near = sorted(idx.best(line, 8), key=lambda x: (-x[1], str(x[0])))  # the closest by rare words; ties by id, so every run builds the same set
        ids += [i for i, _ in near if i not in ids][:4 - len(ids)]  # after the rule's own
        ev = [f"Q: {audit.first_question(answers[i][0])} A: {answers[i][1][:500]}" for i in ids if i in answers]  # question and answer, as the judge sees them
        words = set(audit._words(line))  # the line's words, for the key match
        gap = any(g and len(g & words) / len(g) >= 0.6 for g in gaps)  # the key's 60 percent rule
        out.append({"id": f"line{n}", "gold": "gap" if gap else "covered", "lang": lang_of(line), "input": {"line": line, "evidence": ev},
                    "ref": "gap" if rating in GAP else "covered", "candidates": ids})
    return out


def build_plan(spec) -> list:
    """One item per line of a reviewed cover plan: the line, the profile's closest entries by word matching (not the
    plan's own evidence, which would give the answer away), the reviewed strength, and the planner's rating without
    a model."""
    profile = json.loads(path(spec["profile"]).read_text(encoding="utf-8"))  # the person
    plan = json.loads(path(spec["plan"]).read_text(encoding="utf-8"))  # the reviewed plan
    U = cover.units_of(profile, plan.get("lang") or "ko")  # citable units in the plan's language
    lex = cover.Lex(U)  # word matching over them
    words_plan = cover.plan(profile, path(spec["posting"]).read_text(encoding="utf-8"), lang=plan.get("lang"), backend="none")  # the rule's own plan
    ref = {l["id"]: l["strength"] for l in words_plan["lines"]}  # its rating per line id
    out = []  # items
    for l in plan["lines"]:  # each reviewed line
        ids = [pid for pid, _ in lex.rank(l["text"], 4)]  # the four closest entries
        ev = [cover.unit_text(U, pid)[:700] for pid in ids]  # their text, capped
        out.append({"id": l["id"], "gold": l["strength"], "lang": lang_of(l["text"]), "input": {"line": l["text"], "evidence": ev},
                    "ref": ref.get(l["id"]), "candidates": ids})
    return out


def build_cases(spec) -> list:
    """The planted claim cases of tests/write/test_claims.py (read as data, the test is not run), and the three more
    that its other tests use."""
    mod_spec = importlib.util.spec_from_file_location("claims_cases", str(path(spec["file"])))  # the test file
    mod = importlib.util.module_from_spec(mod_spec)  # a module object for it
    mod_spec.loader.exec_module(mod)  # defines CASES; the tests themselves only run under unittest
    out = []  # items
    for i, (sentence, evidence, flagged) in enumerate(list(mod.CASES) + EXTRA_CLAIMS):  # every planted row
        out.append({"id": f"case{i + 1}", "gold": "overclaim" if flagged else "supported", "lang": lang_of(sentence, evidence),
                    "input": {"claim": sentence.strip(), "evidence": evidence}})
    return out


def build_json(spec) -> list:
    """A labelled set kept as JSON: {"items": [{"id", "gold", "input", ...}]}; the language is read from the input."""
    data = json.loads(path(spec["file"]).read_text(encoding="utf-8"))  # the file
    out = []  # items
    for it in data["items"]:  # each one
        out.append(dict(it, lang=it.get("lang") or lang_of(*it["input"].values())))  # the language unless the file gives it
    return out


BUILDERS = {"postings": build_postings, "kit": build_kit, "plan": build_plan, "cases": build_cases, "json": build_json}


def build_sets(specs: list, scope: str) -> list:
    """Every set of a list, built."""
    return [dict(s, scope=scope, items=BUILDERS[s["build"]](s)) for s in specs]


# ---------------------------------------------------------------- running one backend

def probe_agent(sets: list, out_file: pathlib.Path, cache: pathlib.Path) -> None:
    """One call per task with a single item: the time a decision takes when it is asked on its own, as a panel would
    ask while a person types. Cached like every agent answer, so a rerun makes no call."""
    rec = {"backend": "agent-probe", "probe": {}}  # seconds per task
    for task in D.TASKS:  # each task once
        s = next((x for x in sets if x["task"] == task and x["items"]), None)  # the first set of this task
        if s is None:  # no set of this task was built
            continue
        got = D.decide(task, [dict(s["items"][0]["input"])], backend="agent", cache=str(cache / "probe"))  # a batch of one
        rec["probe"][task] = {"sec": got[0]["call_sec"], "label": got[0]["label"], "gold": s["items"][0]["gold"], "set": s["name"]}
    out_file.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def run_one(spec: str, sets_file: pathlib.Path, out_file: pathlib.Path, cache: pathlib.Path, batch_chars: int) -> None:
    """Every set through one backend in this process; writes every decision, the time, and the peak memory."""
    from decide import laya  # peak memory helper; loads nothing by itself
    import resource  # the agent's CLI runs as a child process
    sets = json.loads(sets_file.read_text(encoding="utf-8"))  # the built sets
    if spec == "agent-probe":  # single-item calls only
        return probe_agent(sets, out_file, cache)
    name, _, variant = spec.partition(":")  # laya:multilingual -> laya, multilingual
    opts = {"variant": variant} if name == "laya" and variant else {}  # the Laya variant, or auto routing
    if name == "vega":  # the reader: vega is the setting's (default 0.8B), vega:4b names one
        opts = {"reader_name": variant} if variant else {}
    if name == "agent":  # cached answers, so a rerun costs nothing
        opts.update(cache=str(cache), batch_chars=batch_chars)  # fuller calls mean fewer calls
    rec = {"backend": spec, "sets": {}, "errors": {}}  # the record
    t_all = time.time()  # wall time of the whole run
    for s in sets:  # each set
        items = [dict(it["input"]) for it in s["items"]]  # the inputs only
        try:
            got = D.decide(s["task"], items, backend=name, **opts)  # the decisions
        except (D.DecideUnavailable, ValueError) as e:  # the backend could not answer this set
            rec["errors"][s["name"]] = str(e)
            continue
        rec["sets"][s["name"]] = got  # in item order
    rec["wall_sec"] = round(time.time() - t_all, 1)  # including model loads
    rec["peak_rss_mb"] = laya.peak_rss_mb()  # this process
    rec["child_peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1)  # the agent's CLI
    rec["loads"] = {v: round(m.load_sec, 1) for v, m in laya._LOADED.items()}  # Laya variants loaded and their load times
    from decide import vega  # Vega's readers loaded, if any; imports nothing of the maker's by itself
    rec["loads"].update({f"vega:{vega.name_of(r)}": round(sec, 1) for r, (_, sec) in vega._LOADED.items()})
    out_file.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- scoring

def outcome(task: str, label: str) -> str:
    """The label a set's gold is written in: coverage kits are scored as gap or covered."""
    if task == "coverage-kit" and label not in ("gap", "covered"):  # a rating; the pipeline's own rule is already written as gap or covered
        return "gap" if label in GAP else "covered"
    return label


def f1(gold: list, pred: list, positive: str) -> float | None:
    """F1 of one class."""
    tp = sum(1 for g, p in zip(gold, pred) if g == p == positive)  # found
    fp = sum(1 for g, p in zip(gold, pred) if p == positive and g != positive)  # false alarms
    fn = sum(1 for g, p in zip(gold, pred) if g == positive and p != positive)  # missed
    return round(2 * tp / (2 * tp + fp + fn), 3) if tp + fp + fn else None


def macro_f1(gold: list, pred: list) -> float:
    """The mean F1 over the classes present in the gold labels."""
    vals = [f1(gold, pred, c) or 0.0 for c in sorted(set(gold))]  # each class
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def score(task: str, items: list, labels: list, ms: list) -> dict:
    """Accuracy, F1, the same by language, and time per decision."""
    kit = task == "coverage" and items and items[0]["gold"] in ("gap", "covered")  # a kit set is scored as gap or covered
    pred = [outcome("coverage-kit" if kit else task, x) for x in labels]  # in the gold's terms
    gold = [it["gold"] for it in items]  # the answers
    pos = "gap" if kit else None if task == "coverage" else POSITIVE.get(task)  # the class of interest; three-class sets take the macro F1
    out = {"n": len(items), "acc": round(sum(g == p for g, p in zip(gold, pred)) / len(items), 3) if items else None,
           "f1": f1(gold, pred, pos) if pos else macro_f1(gold, pred), "f1_of": pos or "macro"}
    by = {}  # per language
    for lg in sorted({it["lang"] for it in items}):  # en, ko, ko-en
        sel = [i for i, it in enumerate(items) if it["lang"] == lg]  # its items
        by[lg] = {"n": len(sel), "acc": round(sum(gold[i] == pred[i] for i in sel) / len(sel), 3)}
    out["by_lang"] = by
    if ms:  # time per decision
        out["ms_mean"], out["ms_p50"] = round(sum(ms) / len(ms), 1), round(statistics.median(ms), 1)
    if task == "coverage" and not kit:  # the reviewed plans have three classes; also strong against the rest
        out["acc_strong_vs_rest"] = round(sum((g == "strong") == (p == "strong") for g, p in zip(gold, pred)) / len(items), 3)
    if kit:  # a key lists the gaps a person found, so lines it leaves out are not proven covered: report what holds anyway
        out["gaps_found"] = f"{sum(1 for g, p in zip(gold, pred) if g == p == 'gap')}/{gold.count('gap')}"  # the key's gaps the backend flags
        out["flagged"] = pred.count("gap")  # lines the backend flags in all
        with_ev = [i for i, it in enumerate(items) if it["input"]["evidence"]]  # lines the retrieval found any scene for
        out["acc_with_evidence"] = round(sum(gold[i] == pred[i] for i in with_ev) / len(with_ev), 3) if with_ev else None
        out["n_with_evidence"] = len(with_ev)
    return out


def s_task(sets: list, name: str) -> str:
    """The task of a set by its name."""
    return next(x["task"] for x in sets if x["name"] == name)


def agreement(a: list, b: list, task: str, kit: bool) -> float | None:
    """The share of items two backends label the same (in the gold's terms)."""
    if not a or len(a) != len(b):  # nothing to compare
        return None
    norm = (lambda x: outcome("coverage-kit", x)) if kit else (lambda x: x)  # noqa: E731  kits compare as gap or covered
    return round(sum(norm(x) == norm(y) for x, y in zip(a, b)) / len(a), 3)


def report(out_dir: pathlib.Path) -> dict:
    """Score every raw result in the folder against the built sets; write results.json and results.md."""
    sets = json.loads((out_dir / "sets.json").read_text(encoding="utf-8"))  # the built sets
    results = {"sets": {s["name"]: {"task": s["task"], "scope": s["scope"], "n": len(s["items"]),
                                    "langs": sorted({it["lang"] for it in s["items"]})} for s in sets}, "backends": {}}
    for f in sorted(out_dir.glob("raw-*.json")):  # each backend's run
        raw = json.loads(f.read_text(encoding="utf-8"))
        if "probe" in raw:  # the agent's single-item calls are a time, not a score
            results["agent_single_item_sec"] = {k: v["sec"] for k, v in raw["probe"].items()}
            continue
        rows = {}  # per set
        for s in sets:  # each set this backend answered
            got = raw["sets"].get(s["name"])
            if got is None:  # not run, or failed
                if s["name"] in raw.get("errors", {}):
                    rows[s["name"]] = {"error": raw["errors"][s["name"]][:200]}
                continue
            ms = [d["ms"] for d in got]  # time per decision; a cached agent answer keeps the time its call took
            rows[s["name"]] = score(s["task"], s["items"], [d["label"] for d in got], ms)
            if raw["backend"] == "agent":  # how the time was spent: calls and items per call
                calls = {(d.get("call_sec"), d.get("batch")) for d in got}  # one entry per call
                rows[s["name"]]["agent_calls"] = len(calls)
                rows[s["name"]]["agent_cached"] = all(d.get("cached") for d in got)
        results["backends"][raw["backend"]] = {"sets": rows, "peak_rss_mb": raw.get("peak_rss_mb"), "child_peak_rss_mb": raw.get("child_peak_rss_mb"),
                                               "wall_sec": raw.get("wall_sec"), "loads": raw.get("loads")}
    labels_by = {}  # (backend, set) -> labels, for the agreement with the agent
    for f in sorted(out_dir.glob("raw-*.json")):  # read again for the labels
        raw = json.loads(f.read_text(encoding="utf-8"))
        for name, got in (raw.get("sets") or {}).items():
            labels_by[(raw["backend"], name)] = [d["label"] for d in got]
    for s in sets:  # the existing pipelines' own rules, where a set carries them
        if any("ref" in it for it in s["items"]):
            labels = [it.get("ref") or "none" for it in s["items"]]  # the pipeline's rating
            labels_by[("rules:pipeline", s["name"])] = labels
            results["backends"].setdefault("rules:pipeline", {"sets": {}})["sets"][s["name"]] = score(s["task"], s["items"], labels, [])
    for (b, name), labels in labels_by.items():  # every backend against the agent on the same items
        ag = labels_by.get(("agent", name))  # the agent's labels for this set
        r = results["backends"].get(b, {}).get("sets", {}).get(name)
        if ag and r and b != "agent" and "error" not in r:
            kit = any(it["gold"] in ("gap", "covered") for it in next(x for x in sets if x["name"] == name)["items"])  # scored as gap or covered
            r["agree_with_agent"] = agreement(labels, ag, s_task(sets, name), kit)
    (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out_dir / "results.md").write_text(markdown(results), encoding="utf-8")
    return results


def markdown(results: dict) -> str:
    """The results as tables: one row per set and backend."""
    lines = ["# Decision backends on the graded sets", "",
             "| set | task | n | backend | accuracy | F1 | agrees with agent | by language | ms per decision (mean, p50) | key gaps found, lines flagged |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, meta in results["sets"].items():  # set by set
        for b, rec in results["backends"].items():  # each backend that answered it
            r = rec["sets"].get(name)
            if not r:
                continue
            if "error" in r:  # could not answer
                lines.append(f"| {name} | {meta['task']} | {meta['n']} | {b} | error | | | | {r['error'][:60]} | |")
                continue
            langs = ", ".join(f"{k} {v['acc']:.2f} ({v['n']})" for k, v in r["by_lang"].items())  # accuracy per language
            t = f"{r['ms_mean']}, {r['ms_p50']}" if "ms_mean" in r else "-"  # time, when measured
            kit = f"{r['gaps_found']}, {r['flagged']} (acc on {r['n_with_evidence']} lines with evidence {r['acc_with_evidence']})" if "gaps_found" in r else ""  # kit sets only
            agree = r.get("agree_with_agent")  # None for the agent itself
            lines.append(f"| {name} | {meta['task']} | {meta['n']} | {b} | {r['acc']:.2f} | {r['f1'] if r['f1'] is not None else '-'} ({r['f1_of']}) | "
                         f"{agree if agree is not None else '-'} | {langs} | {t} | {kit} |")
    lines += ["", "| backend | peak memory MB (process) | peak memory MB (child process) | wall s | model loads s |", "|---|---|---|---|---|"]
    for b, rec in results["backends"].items():  # memory per backend
        if "peak_rss_mb" in rec:
            lines.append(f"| {b} | {rec['peak_rss_mb']} | {rec.get('child_peak_rss_mb')} | {rec.get('wall_sec')} | {json.dumps(rec.get('loads'))} |")
    if results.get("agent_single_item_sec"):  # one decision asked on its own
        lines += ["", "Agent, one item per call (seconds): " + ", ".join(f"{k} {v}" for k, v in results["agent_single_item_sec"].items())]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", required=True, help="results folder")
    p.add_argument("--private", help="JSON list of private sets (same keys as PUBLIC, absolute paths)")
    p.add_argument("--only", help="comma list of set names to keep")
    p.add_argument("--backends", default="rules", help="comma list: rules, agent, agent-probe, laya, laya:<variant>, vega, vega:<reader>")
    p.add_argument("--threads", default="8", help="CPU threads for Laya")
    p.add_argument("--agent-batch-chars", type=int, default=40000, help="characters of items per agent call")
    p.add_argument("--report", action="store_true", help="only score what is in --out")
    p.add_argument("--one", help=argparse.SUPPRESS)  # the child process: run one backend
    a = p.parse_args(argv)
    out = pathlib.Path(a.out).expanduser()  # the results folder
    out.mkdir(parents=True, exist_ok=True)
    if a.one:  # inside the child process
        run_one(a.one, out / "sets.json", out / f"raw-{a.one.replace(':', '_')}.json", out / "agent_cache", a.agent_batch_chars)
        return 0
    if not a.report:  # build the sets, then run each backend in its own process
        sets = build_sets(PUBLIC, "public")  # the repository's fictional sets
        if a.private:  # sets from outside the repository
            sets += build_sets(json.loads(pathlib.Path(a.private).read_text(encoding="utf-8")), "private")
        if a.only:  # a subset by name
            keep = set(a.only.split(","))
            sets = [s for s in sets if s["name"] in keep]
        (out / "sets.json").write_text(json.dumps(sets, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        env = dict(os.environ, OFFEROWL_LAYA_THREADS=a.threads, OMP_NUM_THREADS=a.threads, PYTHONHASHSEED="0")  # the thread cap for the model; a fixed hash order
        for b in [x.strip() for x in a.backends.split(",") if x.strip()]:  # each backend in turn
            t0 = time.time()  # how long it took
            r = subprocess.run([sys.executable, __file__, "--out", str(out), "--one", b, "--agent-batch-chars", str(a.agent_batch_chars)], env=env)  # its own process
            print(f"{b}: exit {r.returncode}, {time.time() - t0:.0f} s", flush=True)
    res = report(out)  # score everything in the folder
    print(f"report: {len(res['sets'])} sets, {len(res['backends'])} backends -> {out / 'results.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
