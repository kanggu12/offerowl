#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A decision model as the interview kit's search (docs/DECISIONS.md, Search).

The kit's search ranks its cards for a typed question in the page. A decision model could take part in two ways:
pick the card that answers the question out of every card of the kit, or put the first three cards a search showed
in a new order. This script measures both on a question set, beside the search's own runs:

    python3 src/interview/cli.py eval --job examples/interview/jobs/gamma-platform \\
        --questions tests/decide/fixtures/kit_questions_reworded.json --out DIR/keywords
    python3 tests/decide/kit_search.py --backend laya --runs keywords=DIR/keywords/eval.json

--backend is laya (the multilingual checkpoint, src/decide/laya.py) or vega, vega:4b (src/decide/vega.py); the model
must be on this PC already (`python3 src/decide/cli.py fetch ...`). Each --runs file is an eval.json of the search,
whose first three cards per question are put in a new order. Writes the decisions to --out when given.
"""
import argparse  # the command line
import json  # sets, runs and results
import pathlib  # paths
import sys  # the import path
import time  # time per question

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
from interview import corpus  # noqa: E402  the kit's cards, as the search reads them
from interview.job import Job  # noqa: E402  the kit's job folder

JOB = ROOT / "examples" / "interview" / "jobs" / "gamma-platform"  # the fictional example kit
SET = ROOT / "tests" / "decide" / "fixtures" / "kit_questions_reworded.json"  # its cards asked in other words
ASK = "An interviewer asked the question in the state. Which prepared answer card answers it?"  # the one question


def cards_of(job_dir: pathlib.Path) -> dict:
    """Each card's id and the line a model reads for it: its title and, when it has one, its key line."""
    items, _ = corpus.load(Job(job_dir))  # the cards in kit order
    return {it["id"]: it["title"] + (" — " + it["key"] if it.get("key") else "") for it in items}


def asker(spec: str):
    """A function (question, card ids) -> {card id: probability} for the backend named."""
    name, _, reader = spec.partition(":")  # vega:4b -> vega, 4b
    if name == "laya":  # the multilingual checkpoint, since half the questions are Korean
        from decide import laya
        model = laya.Model("multilingual").load()  # loaded once

        def ask(state, q):
            return model.ask(state, q)["probabilities"]
    elif name == "vega":  # the maker's next engine, through its package
        from decide import vega
        agent = vega.load(reader)  # loaded once

        def ask(state, q):
            return agent.predict(state, {"pick": q})["answers"]["pick"]["probabilities"]
    else:
        raise SystemExit(f"unknown backend {spec} (laya, vega, vega:4b)")
    return ask


def score(rows: list) -> str:
    """First card right, and one of the first three, as counts."""
    top1 = sum(bool(r["got"]) and r["got"][0] in r["want"] for r in rows)  # the first card is an answer
    top3 = sum(any(g in r["want"] for g in r["got"][:3]) for r in rows)  # an answer among the first three
    return f"first card {top1}/{len(rows)}, first three {top3}/{len(rows)}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--backend", required=True, help="laya, vega or vega:4b")
    p.add_argument("--job", default=str(JOB), help="the kit's job folder (default: the fictional example)")
    p.add_argument("--questions", default=str(SET), help="the question set (default: the example's cards in other words)")
    p.add_argument("--runs", nargs="*", default=[], help="name=eval.json of a search run, whose first three cards are reordered")
    p.add_argument("--out", help="a JSON file for every decision")
    a = p.parse_args(argv)
    cards = cards_of(pathlib.Path(a.job))  # id -> what the model reads
    qs = json.loads(pathlib.Path(a.questions).read_text(encoding="utf-8"))["questions"]  # [question, [ids]]
    ask = asker(a.backend)  # the model, loaded

    def ranked(q, ids):  # the ids in the model's order, most likely first
        pr = ask(q, {"type": "choice", "instructions": ASK, "criteria": {i: cards[i] for i in ids}})
        return sorted(pr, key=pr.get, reverse=True)

    res = {"backend": a.backend, "pick": [], "reorder": {}}  # every decision
    t0 = time.time()  # the time of the picks
    for q, want in qs:  # every card of the kit is an option
        res["pick"].append({"q": q, "want": want, "got": ranked(q, list(cards))[:3]})
    res["pick_ms"] = round((time.time() - t0) * 1000 / max(1, len(qs)))  # per question
    print(f"{a.backend}: picking from all {len(cards)} cards: {score(res['pick'])} ({res['pick_ms']} ms a question)")
    for spec in a.runs:  # a search's own first three, put in a new order
        name, _, path = spec.partition("=")
        rows = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))["rows"]  # what the search showed first
        res["reorder"][name] = [{"q": r["q"], "want": r["want"], "got": ranked(r["q"], r["got"]) if len(r["got"]) > 1 else r["got"]}
                                for r in rows]
        print(f"{name}: as the search ranked them: {score(rows)}; in the order of {a.backend}: {score(res['reorder'][name])}")
    if a.out:  # the record
        pathlib.Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
