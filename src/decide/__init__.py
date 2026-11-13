# -*- coding: utf-8 -*-
"""Typed decisions for Offerowl's decision steps, with a choice of backend (docs/DECISIONS.md).

Many steps of Offerowl decide rather than write: the kind of a posting line, how strongly evidence covers a posting
line, whether a sentence claims more than its evidence, whether two statements contradict each other. This package
answers those questions through one call:

    decide(task, items, backend=None) -> [{"label", "confidence", "scores", "backend", "ms"}]

Backends:
  rules   the rule-based checks Offerowl already has (default; no model, always available)
  agent   the chosen AI backend of src/llm.py, asked for typed JSON under a schema, many items per call
  laya    a small decision model on this PC (src/decide/laya.py), on the CPU
  vega    the decision engine Laya's maker published next, on this PC through the maker's package (src/decide/vega.py)
  jev     a hosted decision model reached through a gateway key; off unless switched on, and its inputs leave this PC

The backend comes from the argument, else OFFEROWL_DECIDE, else rules. Writing never goes through this package, so the
one chosen AI backend still writes everything a person reads. Today this package is a measuring bench: no step of the
pipeline calls it, because no decision model has passed the measurement (the verdict is in docs/DECISIONS.md).
"""
import os  # settings

# The decision tasks. Each has its labels in a fixed order, the fields an item carries, and one question with a
# description per label. The rules, the agent, Laya, Vega and Jev all answer the same question.
TASKS = {
    "line_kind": {
        "labels": ("duty", "requirement", "preferred"),  # what a posting line is
        "fields": ("text",),  # the line
        "question": "This is one line of a job posting. What kind of line is it?",
        "options": {"duty": "a task the hired person will do in the job",
                    "requirement": "a qualification the applicant must already have",
                    "preferred": "a qualification that is a plus but not required"},
    },
    "coverage": {
        "labels": ("strong", "weak", "none"),  # how well the evidence shows the line
        "fields": ("line", "evidence"),  # a posting line and a list of evidence texts (the closest candidates)
        "question": "Does the evidence show that the person has done what this job posting line asks for?",
        "options": {"strong": "yes, the evidence shows this work directly",
                    "weak": "only part of it, or only a related topic",
                    "none": "no, the evidence is about something else"},
    },
    "claim": {
        "labels": ("overclaim", "supported"),  # is a sentence stronger than its evidence
        "fields": ("claim", "evidence"),  # the sentence and the evidence it cites
        "question": ("Does the claim give the person a bigger part than the evidence does (for example led, designed, built or "
                     "owned, where the evidence says helped, proposed, took part, or did it with the team or a colleague)?"),
        "options": {"overclaim": "yes, the claim is stronger than the evidence",
                    "supported": "no, the evidence supports the claim as written"},
    },
    "contradiction": {
        "labels": ("contradiction", "consistent"),  # do two statements disagree
        "fields": ("a", "b"),  # two statements about the same work
        "question": ("Do these two statements about the same person's work contradict each other (a different number, date, "
                     "title, place, or a different share of the work)?"),
        "options": {"contradiction": "yes, both cannot be true",
                    "consistent": "no, both can be true"},
    },
}
BACKENDS = ("rules", "agent", "laya", "vega", "jev")  # the names a person can choose
LOCAL = {"rules": True, "agent": None, "laya": True, "vega": True, "jev": False}  # does the input stay on this PC (None: it follows src/llm.py's backend)


class DecideUnavailable(RuntimeError):
    """The chosen backend cannot answer (missing model, missing key, no consent). The caller keeps its own path."""


def chosen(backend: str | None = None) -> str:
    """The backend to use: the argument, else OFFEROWL_DECIDE, else rules."""
    name = (backend or os.environ.get("OFFEROWL_DECIDE", "") or "rules").strip().lower()  # an empty setting means the default
    if name not in BACKENDS:  # a typo must not pass for the rules
        raise DecideUnavailable(f"unknown decision backend {name} (choices: {', '.join(BACKENDS)})")
    return name


def check_items(task: str, items: list) -> list:
    """The items as dicts that carry the task's fields; a wrong task or a missing field stops here."""
    if task not in TASKS:  # an unknown task name
        raise ValueError(f"unknown decision task {task} (choices: {', '.join(TASKS)})")
    out = []  # the checked items, in order
    for i, it in enumerate(items):  # each item
        if not isinstance(it, dict) or any(f not in it for f in TASKS[task]["fields"]):  # every field must be there
            raise ValueError(f"{task} item {i} needs the fields {', '.join(TASKS[task]['fields'])}")
        out.append(it)
    return out


def result(task: str, label: str, scores: dict | None, backend: str, ms: float, **extra) -> dict:
    """One decision in the common shape. confidence is the chosen label's probability when the backend gives
    probabilities, and None when it does not (the rules)."""
    if label not in TASKS[task]["labels"]:  # a backend must never hand back a label the task does not have
        raise ValueError(f"{backend} gave {label!r} for {task}")
    scores = scores or {}  # rules give no probabilities
    return dict({"label": label, "confidence": scores.get(label), "scores": scores, "backend": backend, "ms": round(ms, 1)}, **extra)


def decide(task: str, items: list, *, backend: str | None = None, **opts) -> list:
    """One typed decision per item, in order. opts go to the backend (agent: cache, llm_backend, batch_chars;
    laya: variant, batch; vega: reader_name; jev: none). Raises DecideUnavailable when the backend cannot answer."""
    items = check_items(task, items)  # the shape first, so every backend gets the same input
    name = chosen(backend)  # which backend
    if not items:  # nothing to decide
        return []
    if name == "rules":  # the checks Offerowl already has
        from decide import rules  # imported on use: no backend costs anything until it is chosen
        return rules.decide(task, items)
    if name == "agent":  # the chosen AI backend of src/llm.py
        from decide import agent  # imported on use
        return agent.decide(task, items, **opts)
    if name == "laya":  # the local decision model
        from decide import laya  # imported on use; it imports numpy and the runtimes only when a model loads
        return laya.decide(task, items, **opts)
    if name == "vega":  # the maker's next engine, through its own package
        from decide import vega  # imported on use; the package and the reader load only when a decision needs them
        return vega.decide(task, items, **opts)
    from decide import jev  # the hosted decision model, only with a key and consent
    return jev.decide(task, items, **opts)


def backend_info(lang: str = "en") -> list:
    """For the panel and the command line: each backend, whether it can answer now, and whether its input leaves this PC."""
    from decide import jev, laya, vega  # the ones that need a check
    rows = [{"name": "rules", "ready": True, "local": True, "why": ""}]  # always there
    try:
        import llm  # the one door to a model
        name, _ = llm.chosen()  # the backend src/llm.py would use
        ok, why = llm.available().get(name, (False, name))  # can it run now
        rows.append({"name": "agent", "ready": bool(ok) and name != "none", "local": name == "openai-compat", "why": f"{name}: {why}"})
    except Exception as e:  # noqa: BLE001  a broken setting must not hide the other rows
        rows.append({"name": "agent", "ready": False, "local": None, "why": str(e)})
    rows.append(dict({"name": "laya", "local": True}, **laya.status()))  # files and libraries on this PC
    rows.append(dict({"name": "vega", "local": True}, **vega.status()))  # the maker's package and the reader on this PC
    rows.append(dict({"name": "jev", "local": False}, **jev.status(lang)))  # key, consent, and where the inputs go
    return rows
