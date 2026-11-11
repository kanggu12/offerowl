#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The decision layer's command (docs/DECISIONS.md).

    python3 src/decide/cli.py list                         the backends, whether each can answer now, where inputs go
    python3 src/decide/cli.py run <task> <items.json> [--backend rules|agent|laya|jev] [--cache DIR]
                                                           one decision per item; items.json is a list of objects
    python3 src/decide/cli.py fetch <variant>              download one Laya variant, checked against pinned hashes

Tasks: line_kind, coverage, claim, contradiction. Messages follow OFFEROWL_LANG (ko or en).
"""
import argparse  # the command line
import json  # items in, decisions out
import pathlib  # paths
import sys  # exit codes and the import path

SRC = pathlib.Path(__file__).resolve().parent.parent  # src/, so `decide` and `llm` import the same way from anywhere
if str(SRC) not in sys.path:  # add src/ only once
    sys.path.insert(0, str(SRC))  # first on the path, so this checkout wins over an installed copy

import llm  # noqa: E402  the message helper and the language setting
import decide as D  # noqa: E402  the interface

MSG = {  # every message a person reads, in both languages with the same keys
    "en": {
        "row": "{mark} {name:6} {state:9} {where}{why}",
        "ready": "ready",
        "not_ready": "not ready",
        "stays": "inputs stay on this PC",
        "leaves": "inputs leave this PC",
        "follows": "inputs go where the AI backend is",
        "in_use": "In use: {name} (OFFEROWL_DECIDE, default rules)",
        "jev_untested": "jev was written from the gateway's documentation and has not been tested against Jev itself",
        "bad_items": "{path}: expected a JSON list of objects",
        "failed": "{backend} could not decide: {why}",
        "fetched": "Laya {variant}: {n} files in {where}",
        "fetch_failed": "Laya {variant}: download failed: {why}",
    },
    "ko": {
        "row": "{mark} {name:6} {state:9} {where}{why}",
        "ready": "쓸 수 있음",
        "not_ready": "쓸 수 없음",
        "stays": "입력이 이 PC 안에 머문다",
        "leaves": "입력이 이 PC 밖으로 나간다",
        "follows": "입력은 AI 백엔드가 있는 곳으로 간다",
        "in_use": "쓰는 것: {name} (OFFEROWL_DECIDE, 기본은 rules)",
        "jev_untested": "jev는 게이트웨이 문서로 만들었고 Jev 자체에는 시험하지 못했다",
        "bad_items": "{path}: JSON 객체의 목록이어야 한다",
        "failed": "{backend}로 판단하지 못했다: {why}",
        "fetched": "Laya {variant}: 파일 {n}개, {where}",
        "fetch_failed": "Laya {variant}: 내려받지 못했다: {why}",
    },
}


def t(key: str, **kw) -> str:
    """A message of this command in the user's language."""
    return llm.message(MSG, key, **kw)


def cmd_list(_a) -> int:
    """Each backend with its state and where its inputs go."""
    try:
        name = D.chosen()  # the backend in use
    except D.DecideUnavailable as e:  # a mistyped OFFEROWL_DECIDE
        print(e)
        name = ""
    for row in D.backend_info(llm.lang()):  # rules, agent, laya, jev
        where = t("stays") if row["local"] is True else t("leaves") if row["local"] is False else t("follows")  # the local-first fact
        why = f"  ({row['why']})" if row.get("why") else ""  # what is missing
        print(t("row", mark="*" if row["name"] == name else " ", name=row["name"], state=t("ready") if row["ready"] else t("not_ready"), where=where, why=why))
        if row["name"] == "jev":  # the notice and the untested state, every time
            print("         " + row["notice"])
            print("         " + t("jev_untested"))
    print(t("in_use", name=name or "-"))  # which one decide() would use
    return 0


def cmd_run(a) -> int:
    """Decide every item of a JSON list and print the decisions as JSON."""
    items = json.loads(pathlib.Path(a.items).read_text(encoding="utf-8"))  # the items
    if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):  # the one shape accepted
        print(t("bad_items", path=a.items))
        return 2
    try:
        out = D.decide(a.task, items, backend=a.backend, cache=a.cache)  # the decisions
    except (D.DecideUnavailable, ValueError) as e:  # a backend that cannot answer, or a wrong task
        print(t("failed", backend=a.backend or D.chosen(), why=e))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))  # readable and machine-readable
    return 0


def cmd_fetch(a) -> int:
    """Download one Laya variant on purpose."""
    from decide import laya  # the runtime
    try:
        got = laya.fetch(a.variant)  # missing files only, each checked
    except (laya.LayaUnavailable, OSError, KeyError) as e:  # a hash mismatch, no network, an unknown variant
        print(t("fetch_failed", variant=a.variant, why=e))
        return 1
    print(t("fetched", variant=a.variant, n=len(got), where=laya.model_dir()))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="decide", description=__doc__.split("\n")[0])  # the first docstring line
    sub = p.add_subparsers(dest="cmd", required=True)  # one subcommand
    sub.add_parser("list", help="backends and their state")  # no options
    r = sub.add_parser("run", help="decide the items of a JSON file")
    r.add_argument("task", choices=sorted(D.TASKS))  # the four tasks
    r.add_argument("items", help="a JSON list of objects with the task's fields")
    r.add_argument("--backend", choices=D.BACKENDS, help="default: OFFEROWL_DECIDE, else rules")
    r.add_argument("--cache", help="folder for the agent's answers, so a rerun asks nothing again")
    f = sub.add_parser("fetch", help="download one Laya variant")
    f.add_argument("variant", help="english, multilingual, typed-decisions, english-onnx or english-onnx-int8")
    a = p.parse_args(argv)  # stops with a usage message on a mistake
    return {"list": cmd_list, "run": cmd_run, "fetch": cmd_fetch}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
