#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests of src/figure_draft.py with a stand-in for the model (no model is ever called here).

  python3 tests/deck/test_figure_draft.py     -> one line per failed check, then "figure draft tests: N passed, M failed"

The stand-in answers like a model would: one proposal that keeps to the evidence, and proposals with an invented value, an invented
date, a name the evidence does not have, an unknown template, a side figure too wide for the side, and text too long for its box.
The checks must keep the first and flag every other one; review must refuse to accept a flagged proposal; apply must write a new file,
add only accepted figures, and check them again against the profile it writes into.
"""
import copy  # the input profile must stay unchanged
import json  # profiles and proposals
import pathlib  # paths
import subprocess  # the command line
import sys  # the interpreter
import tempfile  # a scratch folder

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
sys.path.insert(0, str(ROOT / "src"))  # the module under test
import figure_draft as FD  # noqa: E402
import llm  # noqa: E402

PASS, FAIL = [0], [0]  # counters


def ok(name, cond, detail=""):
    """Count one check and print it when it fails"""
    if cond:  # a pass
        PASS[0] += 1  # is only counted
    else:
        FAIL[0] += 1  # a failure is counted
        print(f"FAIL {name}" + (f": {detail}" if detail else ""))  # and printed with its detail


# A fictional bilingual profile: two companies, three deck projects, and a research chapter. Evidence numbers: 14 scripts, 1 path,
# 42 and 9 minutes, 8 GPU nodes, dates 2023.03 and 2023.05
PROFILE = {
    "schema": "resume-profile/0.1",  # the profile format the loader reads
    "person": {"name": "홍길동", "email": "gildong@example.com"},  # a fictional person
    "roles": [  # one company chapter
        {"key": "alpha", "org": {"ko": "알파페이", "en": "Alpha Pay"}, "start": "2022.03", "end": None,  # a current role (no end)
         "context": [{"title": "환경", "body_md": "Kubernetes 클러스터, GPU 노드 8대"}],  # the chapter's facts hold the 8 GPU nodes
         "projects": [  # four projects, each testing one rule
             # Project a1: the evidence-rich one the good proposals rest on
             {"id": "a1", "title": {"ko": "배포 플랫폼 구축", "en": "Deployment platform build"}, "period": "2023.01 ~ 2023.09",
              "summary": {"ko": "팀마다 다르던 배포 스크립트 14개를 Argo CD 공용 경로 1개로 모았다. 배포가 42분에서 9분이 됐다.",  # 14 scripts, 1 path, 42 and 9 minutes
                          # The same facts in English
                          "en": "Gathered 14 team deploy scripts into 1 shared Argo CD path; a deploy went from 42 to 9 minutes."},
              # Cards whose heads the prompt numbers
              "cards": {"ko": [["공용 경로", "Argo CD와 Helm"], ["배포 시간", "같은 변경 크기"]], "en": [["Shared path", "Argo CD and Helm"], ["Deploy time", "Same change size"]]},
              "notes": "파일럿 2023.03, 전환 2023.05"},  # the two dates a timeline may use
             # Project a2: the stand-in answers it with invented facts
             {"id": "a2", "title": {"ko": "GPU 학습 환경", "en": "GPU training setup"}, "period": "2024.01 ~ 2024.06",
              "summary": {"ko": "GPU 노드 8대를 학습 큐로 묶었다.", "en": "Grouped 8 GPU nodes into a training queue."}},  # 8 nodes, so 16 is invented
             {"id": "a3", "title": {"ko": "이미 그림이 있는 과제", "en": "A project with figures"}, "deck": True,  # a3 already has two figures, so it is not asked about
              "figure": {"type": "bars", "rows": [["a", 1]]}, "figures": [{"type": "bars", "rows": [["b", 1]]}]},  # a main and a side figure
             {"id": "a4", "title": {"ko": "덱에 없는 과제", "en": "Off the deck"}, "deck": False}]},  # a4 is off the deck, so it is not asked about either
    ],
    "chapters": [{"key": "research", "name": {"ko": "연구", "en": "Research"}, "projects": [  # a chapter that is not a company
        # Project r1: the stand-in answers it with a new name and a wide side figure
        {"id": "r1", "title": {"ko": "센서망 연구", "en": "Sensor network research"}, "summary": {"ko": "교통량에 맞춘 주기", "en": "Cycles that follow traffic"}}]}],
}

# A proposal that keeps to the evidence: deploy time from 42 to 9 minutes
GOOD = {"type": "metric", "caption": {"ko": "**배포 시간** 같은 변경 크기", "en": "**Deploy time** Same change size"}, "unit": {"ko": "분", "en": " min"},
        "rows": [[{"ko": "배포", "en": "Deploy"}, 42, 9]]}   # every value is in the evidence
# A side figure of 14 scripts to 1, both in the evidence
GOOD_SIDE = {"type": "bars", "caption": {"ko": "**스크립트**", "en": "**Scripts**"}, "rows": [[{"ko": "전", "en": "Before"}, 14], [{"ko": "후", "en": "After"}, 1]]}
INVENTED = {"type": "bars", "caption": {"ko": "**노드 수**", "en": "**Nodes**"}, "rows": [[{"ko": "GPU 노드", "en": "GPU nodes"}, 16]]}   # 16 is not in the evidence
# A side timeline whose dates the evidence lacks
BAD_DATE = {"type": "timeline", "caption": {"ko": "**전환**", "en": "**Rollout**"}, "phases": [[{"ko": "파일럿", "en": "Pilot"}, "2023.03", "2023.04"]],
            "milestones": [[{"ko": "전환", "en": "Cutover"}, "2023.07"]]}   # 2023.04 and 2023.07 are not in the evidence
NEW_NAME = {"type": "pipeline", "caption": {"ko": "**경로**", "en": "**Path**"}, "steps": [[{"ko": "Jenkins 빌드", "en": "Jenkins build"}], [{"ko": "배포", "en": "Deploy"}]]}   # Jenkins is not in the evidence
UNKNOWN = {"type": "pie", "slices": [1, 2]}   # no such template
WIDE_SIDE = {"type": "architecture", "zones": [{"title": {"ko": "가", "en": "A"}, "nodes": [{"id": "x", "title": {"ko": "가", "en": "A"}}]}]}   # not a side type
# A step name far too long for a side box, six times over
LONG = {"type": "pipeline", "steps": [[{"ko": "아주 길게 늘어진 단계 이름이라 좁은 칸에 도저히 들어가지 않는 경우를 일부러 만든 것", "en": "A deliberately overlong step name that cannot fit any narrow box of a six step row at all"}]] * 6}

CALLS = []  # prompts the stand-in saw


def stand_in(prompt: str) -> dict:
    """Answers like a model, per project id mentioned in the prompt"""
    CALLS.append(prompt)  # the tests read the prompts later
    out = []  # one entry per project the prompt names
    if "Project a1:" in prompt:  # the prompt's project heading
        out.append({"id": "a1", "why": "summary numbers", "pages": [{"page": 0, "main": GOOD, "side": GOOD_SIDE}]})  # a1 gets the two good proposals
    if "Project a2:" in prompt:  # a2 gets
        out.append({"id": "a2", "pages": [{"page": 0, "main": INVENTED, "side": BAD_DATE}]})  # an invented value and invented dates
    if "Project r1:" in prompt:  # r1 gets
        # A new name, a wide side figure, and a page it does not have
        out.append({"id": "r1", "pages": [{"page": 0, "main": NEW_NAME, "side": WIDE_SIDE}, {"page": 3, "main": GOOD}]})
    return {"projects": out}  # the shape call_model requires


def statuses(doc):
    """proposal id -> (status, checks)"""
    return {f["n"]: (f["status"], f["checks"]) for e in doc["projects"] for f in e["figures"]}  # every proposal of every project


# A project whose text holds numbers of one kind, and one with too few to compare
MEASURED_PROFILE = {
    "schema": "resume-profile/0.1", "person": {"name": "홍길동", "email": "gildong@example.com"},
    "roles": [{"key": "alpha", "org": {"ko": "알파페이", "en": "Alpha Pay"}, "start": "2022.03", "end": None, "projects": [
        {"id": "m1", "title": {"ko": "응답 개선", "en": "Faster answers"}, "period": "2023.01 ~ 2023.09",
         "summary": {"ko": "응답 시간이 144초에서 6.4초가 됐고, 재시도는 52% 줄었다.", "en": "Answers went from 144 seconds to 6.4 seconds, and retries fell by 52%."}},
        {"id": "m2", "title": {"ko": "숫자 없는 일", "en": "Work without numbers"}, "period": "2024.01 ~ 2024.06",
         "summary": {"ko": "팀 3곳의 배포를 하나로 모았다.", "en": "Gathered the deploys of 3 teams into one."}}]}],
}
STEPS = {"type": "pipeline", "caption": {"ko": "**단계**", "en": "**Steps**"}, "steps": [[{"ko": "분석", "en": "Measure"}], [{"ko": "전환", "en": "Switch"}]]}  # the easy default
CHART = {"type": "metric", "caption": {"ko": "**응답 시간**", "en": "**Answer time**"}, "unit": {"ko": "초", "en": " s"}, "rows": [[{"ko": "응답", "en": "Answer"}, 144, 6.4]]}  # both numbers are in the text
MADE_UP = {"type": "metric", "caption": {"ko": "**응답 시간**", "en": "**Answer time**"}, "unit": {"ko": "초", "en": " s"}, "rows": [[{"ko": "응답", "en": "Answer"}, 144, 77]]}  # 77 is not in the text


def measured_answer(chart):
    """A stand-in: the first step draws steps for every project, and the question about numbers answers with this chart."""
    asked = []  # the prompts of the question about numbers

    def ask(prompt):  # one call
        if prompt.startswith("Some numbers in these projects"):  # the measured step
            asked.append(prompt)  # kept for the test
            return {"projects": [{"id": "m1", "page": 0, "figure": chart, "why": "the two times"}]}  # the chart, or null
        out = [{"id": i, "pages": [{"page": 0, "main": copy.deepcopy(GOOD_MAIN), "side": copy.deepcopy(STEPS)}]} for i in ("m1", "m2") if f"Project {i}:" in prompt]  # the easy default
        return {"projects": out}  # the shape call_model requires
    return ask, asked


GOOD_MAIN = {"type": "pipeline", "caption": {"ko": "**전체**", "en": "**Overall**"}, "steps": [[{"ko": "분석", "en": "Measure"}], [{"ko": "전환", "en": "Switch"}], [{"ko": "확인", "en": "Check"}]]}  # a main figure with no number


def side_types(doc, pid):
    """The side figures proposed for a project."""
    e = next(x for x in doc["projects"] if x["id"] == pid)  # the project's proposals
    return [f["figure"].get("type") for f in e["figures"] if f["slot"] == "side"]  # their types


def measured_step():
    """The numbers get a question of their own, and only a chart that passes takes a place."""
    prof = copy.deepcopy(MEASURED_PROFILE)  # the profile
    ask, asked = measured_answer(CHART)  # a grounded chart
    doc = FD.propose(prof, ask=ask)  # both steps
    ok("the numbers get a question of their own", len(asked) == 1 and "Project m1:" in asked[0], str(len(asked)))  # one call, about the project with numbers
    ok("a project with too few numbers is not asked about", "Project m2:" not in asked[0])  # one number is nothing to compare
    ok("the question holds only the lines with numbers", "144" in asked[0] and "팀 3곳" not in asked[0])  # nothing else competes
    ok("the question says what the page's figure already shows", "its figure already shows" not in asked[0].split("Project m1:")[1].split("Lines:")[0])  # the main figure here shows no number
    ok("a Latin unit in the Korean half becomes the Korean word", FD.korean_units({"type": "metric", "unit": {"ko": "s", "en": " s"}})["unit"] == {"ko": "초", "en": " s"})
    ok("the numbers of a figure are found in its values and labels", sorted(FD.numbers_in({"rows": [["HDR 200G", 200], ["a", 1.5]], "on": True})) == [1.5, 200, 200], str(FD.numbers_in({"rows": [["HDR 200G", 200], ["a", 1.5]]})))
    ok("a chart that passes takes the side from a drawn sequence", side_types(doc, "m1") == ["metric"], str(side_types(doc, "m1")))  # the pipeline gave way
    ok("the other project keeps its side figure", side_types(doc, "m2") == ["pipeline"], str(side_types(doc, "m2")))  # not asked about
    FD.review(doc, accept=["all"])  # accepted
    new, _, _ = FD.apply(doc, prof)  # applied
    m1 = new["roles"][0]["projects"][0]  # the project
    ok("the chart reaches the profile", [f.get("type") for f in m1.get("figures") or []] == ["metric"], str(m1.get("figures")))  # as the later figure
    ask, _ = measured_answer(MADE_UP)  # a number the text does not hold
    doc = FD.propose(copy.deepcopy(MEASURED_PROFILE), ask=ask)  # both steps
    ok("a chart with an invented number goes and the sequence stays", side_types(doc, "m1") == ["pipeline"], str(side_types(doc, "m1")))  # what was there stands
    ok("and the note says why", any("m1#0.measured" in str(x) for x in doc["errors"]), str(doc["errors"]))  # not dropped silently
    small = {"type": "metric", "caption": {"ko": "**시간**", "en": "**Time**"}, "unit": {"ko": "초", "en": " s"}, "rows": [[{"ko": "응답", "en": "Answer"}, 144, 3]]}  # 3 stands only in a date
    ok("the month of a date is no measurement", any("value 3 " in x for x in FD.check_facts(small, "응답 144초. 기간 2022.03", ["ko"])), str(FD.check_facts(small, "응답 144초. 기간 2022.03", ["ko"])))  # a chart cannot draw it
    ask, _ = measured_answer(None)  # no chart in these numbers
    doc = FD.propose(copy.deepcopy(MEASURED_PROFILE), ask=ask)  # both steps
    ok("no chart is an honest answer", side_types(doc, "m1") == ["pipeline"], str(side_types(doc, "m1")))  # nothing changed
    ask, asked = measured_answer(CHART)  # the chart again
    FD.propose(copy.deepcopy(MEASURED_PROFILE), ask=ask, measured_calls=0)  # the step off
    ok("the step can be turned off", asked == [], str(len(asked)))  # no call
    two = copy.deepcopy(MEASURED_PROFILE)  # a page that already has its two figures
    two["roles"][0]["projects"][0].update(figure=GOOD_MAIN, figures=[STEPS])  # a main and a drawn sequence
    ask, _ = measured_answer(CHART)  # the chart
    doc = FD.propose(two, ask=ask)  # both steps
    FD.review(doc, accept=["all"])  # accepted
    new, _, _ = FD.apply(doc, two)  # applied
    ok("an earlier sequence of steps gives way on apply", [f.get("type") for f in new["roles"][0]["projects"][0]["figures"]] == ["metric"], str(new["roles"][0]["projects"][0]["figures"]))
    hand = copy.deepcopy(MEASURED_PROFILE)  # a page with someone's other view
    hand["roles"][0]["projects"][0].update(figure=GOOD_MAIN, figures=[{"type": "tree", "root": "x"}])  # not a sequence of steps
    ask, _ = measured_answer(CHART)  # the chart
    doc = FD.propose(hand, ask=ask)  # both steps
    ok("someone's other side figure is not taken away", not any(f.get("measured") for e in doc["projects"] for f in e["figures"]), str(doc["errors"]))  # the chart goes


def main():  # every check in order; the exit code for run.py
    prof = copy.deepcopy(PROFILE)  # a copy, so a later check can tell it was not changed
    # Which projects are asked about: deck projects short of two figures (a3 has two, a4 is off the deck)
    doc = FD.propose(prof, ask=stand_in, max_calls=8)
    asked = [e["id"] for e in doc["projects"]]  # the projects the proposals cover
    ok("asks about deck projects short of figures", asked == ["a1", "a2", "r1"], str(asked))  # a3 and a4 left out, deck order kept
    ok("the profile's two languages are used", doc["langs"] == ["ko", "en"], str(doc["langs"]))  # pair titles make the profile bilingual
    ok("small chapters share a call", doc["calls"] == 1, str(doc["calls"]))   # alpha's two projects and the research project fit one batch
    CALLS.clear()  # count this run's calls alone
    split = FD.propose(copy.deepcopy(PROFILE), ask=stand_in, per_call=1)  # one project per call
    ok("batches follow the size per call", split["calls"] == 3 and len(CALLS) == 3, str(split["calls"]))  # three projects, three calls
    first = CALLS[0]  # the first prompt
    # The catalog's lines, the project's summary and its chapter's facts
    ok("the prompt carries the catalog and the evidence", "architecture:" in first and "42분에서 9분" in first and "GPU 노드 8대" in first)
    ok("the prompt asks for language pairs", '{"ko": "...", "en": "..."}' in first)  # the bilingual rule
    st = statuses(doc)  # the first run's results by proposal
    # A metric of evidence numbers passes every check
    ok("a supported figure passes", st.get("a1#0.main", ("",))[0] == "ok", json.dumps(st.get("a1#0.main"), ensure_ascii=False)[:300])
    # So does the side bar chart
    ok("a supported side figure passes", st.get("a1#0.side", ("",))[0] == "ok", json.dumps(st.get("a1#0.side"), ensure_ascii=False)[:300])
    ok("an invented value is flagged", st["a2#0.main"][0] == "flagged" and any("16" in x for x in st["a2#0.main"][1]["facts"]))  # 16 is named in the facts findings
    # The invented end date is named
    ok("an invented date is flagged", st["a2#0.side"][0] == "flagged" and any("2023.04" in x or "4" in x for x in st["a2#0.side"][1]["facts"]))
    # The tool name the evidence lacks is named
    ok("a name not in the evidence is flagged", st["r1#0.main"][0] == "flagged" and any("jenkins" in x.lower() for x in st["r1#0.main"][1]["facts"]))
    # An architecture figure in the side slot is a shape finding
    ok("a wide figure is refused in the side slot", st["r1#0.side"][0] == "flagged" and any("side figure" in x for x in st["r1#0.side"][1]["shape"]))
    ok("a page the project does not have is ignored", "r1#3.main" not in st)  # page 3 of a one-page project
    # Shape and drawing checks on their own
    bad = FD.propose(copy.deepcopy(PROFILE), only={"a2"}, ask=lambda p: {"projects": [{"id": "a2", "pages": [{"page": 0, "main": UNKNOWN, "side": LONG}]}]})
    s2 = statuses(bad)  # their results
    # The library's own message names the type
    ok("an unknown template is refused", s2["a2#0.main"][0] == "flagged" and any("unknown figure type" in x for x in s2["a2#0.main"][1]["shape"]))
    # Layout findings for the text that does not fit
    ok("text too long for its box is flagged", s2["a2#0.side"][0] == "flagged" and any(s2["a2#0.side"][1]["layout"].values()))
    # No backend: stop with a note, keep what was proposed

    def none(_p):
        raise llm.LLMUnavailable("none: no backend")  # what llm.run raises without a backend
    stopped = FD.propose(copy.deepcopy(PROFILE), ask=none)  # every call fails this way
    ok("no backend stops with a note", stopped["calls"] == 0 and any("stopped" in e for e in stopped["errors"]))  # no call is counted, the note says stopped
    # A small budget: every project still asked about, in at most that many calls
    CALLS.clear()
    tight = FD.propose(copy.deepcopy(PROFILE), ask=stand_in, max_calls=1)  # all three projects, one call allowed
    ok("a budget of one call", len(CALLS) == 1 and [e["id"] for e in tight["projects"]] == ["a1", "a2", "r1"], str(len(CALLS)))  # one call, and still every project
    # Repair: one more call with the findings; a fixed figure passes the same checks and the first version is kept
    fixdoc = FD.propose(copy.deepcopy(PROFILE), only={"a2"}, ask=stand_in)
    sent = []  # the repair prompts the stand-in sees
    # The stand-in fixes a2's main figure with the evidence's 8 nodes
    fixed = FD.repair(fixdoc, copy.deepcopy(PROFILE), ask=lambda pr: (sent.append(pr), {"fixes": [{"n": "a2#0.main", "figure": {**INVENTED, "rows": [[{"ko": "GPU 노드", "en": "GPU nodes"}, 8]]}}]})[1])
    rf = {f["n"]: f for e in fixed["projects"] for f in e["figures"]}  # the repaired proposals by id
    ok("repair sends the findings and the evidence", len(sent) == 1 and "16" in sent[0] and "GPU 노드 8대" in sent[0])  # one call, with the finding and the evidence
    # It passes, is marked repaired, and keeps the model's first version
    ok("a repaired figure passes the same checks", rf["a2#0.main"]["status"] == "ok" and rf["a2#0.main"].get("repaired") and rf["a2#0.main"]["first"] == INVENTED)
    ok("an unrepaired figure stays flagged", rf["a2#0.side"]["status"] == "flagged")  # the side figure had no fix
    # Review: flagged proposals cannot be accepted, rejections are recorded
    lines = FD.review(doc, accept={"all"})
    dec = {f["n"]: f.get("decision") for e in doc["projects"] for f in e["figures"]}  # each proposal's decision
    # The passing ones are accepted, a flagged one stays undecided
    ok("review accepts only checked proposals", dec["a1#0.main"] == "accepted" and dec["a1#0.side"] == "accepted" and dec["a2#0.main"] is None)
    ok("review lists every proposal with its reasons", len(lines) == 6 and any("<-" in ln for ln in lines))  # six proposals; flagged lines carry their reasons
    FD.review(doc, reject={"a1#0.side"})  # reject one that was accepted
    # The rejection replaces the acceptance
    ok("review records a rejection", next(f for e in doc["projects"] for f in e["figures"] if f["n"] == "a1#0.side")["decision"] == "rejected")
    # Apply: a new profile with the accepted figures; the input is unchanged; the checks run again on the target profile
    before = json.dumps(prof, sort_keys=True)
    new, added, notes = FD.apply(doc, prof)  # the accepted figures into a new profile
    # One figure added (the side was rejected): the metric as a1's main
    ok("apply adds accepted figures", added == 1 and new["roles"][0]["projects"][0].get("figure", {}).get("type") == "metric", f"{added} {notes}")
    ok("apply leaves the input alone", json.dumps(prof, sort_keys=True) == before)  # the input serializes exactly as before
    # Cards get the numbers of the figure parts that show them
    page = {"cards": {"ko": [["가", "나"], ["다", "라"], ["마", "바"]], "en": [["a", "b"], ["c", "d"], ["e", "f"]]}}
    # Panels marked 1 and 3, so cards 1 and 3 get numbers
    FD.number_cards(page, FD.marks_in({"type": "panels", "panels": [{"mark": 1, "figure": {}}, {"mark": 3, "figure": {}}]}))
    # Card 2 stays unnumbered; both languages get the same numbers
    ok("cards numbered after the figure's marks", page["cards"]["en"] == [["a", "b", 1], ["c", "d"], ["e", "f", 3]] and page["cards"]["ko"][2] == ["마", "바", 3])
    # A proposal whose notes overflow its panel stands in lighter: the notes of that panel go, the model's version is kept
    note = {"ko": "아주 길게 늘어진 설명이 좁은 칸을 넘치도록 일부러 길게 쓴 문장입니다 여러 줄로 이어집니다", "en": "A deliberately long note that overflows a narrow box over several lines on purpose and more"}
    # Ten steps, each with that note
    steps = {"type": "pipeline", "steps": [[{"ko": "설계", "en": "Design"}, note], [{"ko": "검증", "en": "Check"}, note], [{"ko": "전환", "en": "Cutover"}, note], [{"ko": "운영", "en": "Run"}, note], [{"ko": "정리", "en": "Wrap up"}, note]] * 2}
    # Three stacked panels of those steps, marked 1 to 3
    crowded = {"type": "panels", "layout": "3v", "panels": [{"title": {"ko": k, "en": e}, "mark": i + 1, "figure": steps} for i, (k, e) in enumerate([("설계", "Design"), ("검증", "Check"), ("전환", "Cutover")])]}
    # Only a1, with the crowded figure as its main
    lite = FD.propose(copy.deepcopy(PROFILE), only={"a1"}, ask=lambda p: {"projects": [{"id": "a1", "pages": [{"page": 0, "main": crowded}]}]})
    lf = lite["projects"][0]["figures"][0]  # its one proposal
    # It passes with notes dropped, the model's version kept in proposed
    ok("a crowded proposal stands in lighter", lf["status"] == "ok" and lf.get("fitted", "").startswith("notes dropped") and lf.get("proposed") == crowded, f"{lf['status']} {lf.get('fitted')} {lf['checks']['layout']}")
    # The forms of a three-panel composite
    forms = [n for n, _ in FD.lighter({"type": "panels", "panels": [{"figure": crowded}, {"figure": GOOD}, {"figure": GOOD_SIDE}]})]
    # One panel at a time from the last, the first panel alone at the end
    ok("lighter forms go panel by panel first", forms[:3] == ["notes dropped in panel 3", "notes dropped in panel 2", "notes dropped in panel 1"] and forms[-1] == "notes dropped, only the first panel kept", str(forms))
    # Then two panels at a time, later panels first, before every note goes; fewer panels keep their notes before losing them
    ok("lighter forms drop notes in growing sets", forms[3:7] == ["notes dropped in panels 2 and 3", "notes dropped in panels 1 and 3", "notes dropped in panels 1 and 2", "notes dropped"]
       and forms.index("panels after 2 left out") < forms.index("notes dropped, panels after 2 left out"), str(forms))
    # A link's label is a note: the lighter form keeps the link and its kind, without the label
    arch = {"type": "architecture", "zones": [{"title": "A", "nodes": [{"id": "a", "title": "A", "sub": "note"}]}, {"title": "B", "nodes": [{"id": "b", "title": "B"}]}], "links": [["a", "b", "HTTP", "mine"]]}
    plain = dict(FD.lighter(arch))["notes dropped"]  # the form without notes
    ok("link labels count as notes", plain["links"] == [["a", "b", "", "mine"]] and "sub" not in plain["zones"][0]["nodes"][0], json.dumps(plain))
    # The prompt names each page's side room, so the side figure can be sized to it: a room, cards that fill the column, no cards
    pages = [{"cards": ["1. c"], "have": 0, "room": 150}, {"cards": ["1. c"], "have": 0, "room": 60}, {"cards": [], "have": 0, "room": None}]
    text = FD.prompt_for([{"id": "x", "title": "t", "evidence": "e", "pages": pages}], ["ko", "en"], {"pipeline": {"use": "u", "shape": "{}"}})
    ok("the prompt gives each page's side room", "side room 150 px" in text and "no side figure (the cards fill the column)" in text and "no side column" in text, text[-400:])
    other = copy.deepcopy(PROFILE)  # a profile whose evidence changes
    other["roles"][0]["projects"][0]["summary"] = {"ko": "숫자가 없는 요약", "en": "A summary without numbers"}   # the evidence changed
    _, added2, notes2 = FD.apply(json.loads(json.dumps(doc)), other)  # a fresh copy of the reviewed proposals
    # The metric's numbers are gone: nothing applied, a note says why
    ok("apply checks again against the profile it writes", added2 == 0 and any("a check failed" in n for n in notes2), str(notes2))
    # The command line end to end, with canned answers
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)  # the scratch folder
        (t / "p.json").write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")  # the profile file
        # Two canned answers: a1 and a2 in one, r1 in the other
        (t / "answers.json").write_text(json.dumps([stand_in("Project a1: Project a2:"), stand_in("Project r1:")], ensure_ascii=False), encoding="utf-8")
        # The command run with this interpreter
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "src" / "figure_draft.py"), *a], capture_output=True, text=True)
        r1 = run("propose", str(t / "p.json"), "--stand-in", str(t / "answers.json"))  # propose with the canned answers
        # The proposals file is written and two pass
        ok("command line propose", r1.returncode == 0 and (t / "p.figures.json").exists() and "2 passed every check" in r1.stdout, r1.stdout + r1.stderr[-300:])
        r2 = run("review", str(t / "p.figures.json"), "--accept", "all")  # accept everything that may be accepted
        ok("command line review", r2.returncode == 0 and "2 accepted" in r2.stdout, r2.stdout[-300:])  # only the two that passed
        r3 = run("apply", str(t / "p.figures.json"), str(t / "p.json"))  # apply into the default new file
        newp = json.loads((t / "p.figs.json").read_text(encoding="utf-8")) if (t / "p.figs.json").exists() else {}  # the new profile, read when it exists
        # Two figures added to a1
        ok("command line apply", r3.returncode == 0 and "2 figure(s) added" in r3.stdout and newp["roles"][0]["projects"][0].get("figures"), r3.stdout[-300:])
        r4 = run("apply", str(t / "p.figures.json"), str(t / "p.json"), "--out", str(t / "p.json"))  # --out naming the input itself
        ok("apply never overwrites its input", r4.returncode == 1)  # refused with exit 1
    # Figures drawn before a check existed: prune takes out the ones today's checks turn down, and keeps the rest
    crossing = {"type": "architecture", "caption": {"ko": "**교차**", "en": "**Crossing**"},  # two arrows that cross between the second and third zones
                "zones": [{"title": {"ko": "가", "en": "A"}, "nodes": [{"id": "a", "title": {"ko": "가", "en": "A"}}]},
                          {"title": {"ko": "나", "en": "B"}, "nodes": [{"id": "b1", "title": {"ko": "나1", "en": "B1"}}, {"id": "b2", "title": {"ko": "나2", "en": "B2"}}]},
                          {"title": {"ko": "다", "en": "C"}, "nodes": [{"id": "c1", "title": {"ko": "다1", "en": "C1"}}, {"id": "c2", "title": {"ko": "다2", "en": "C2"}}]}],
                "links": [["a", "b1"], ["b1", "c2"], ["b2", "c1"]]}
    old = copy.deepcopy(PROFILE)  # a profile whose a1 has a good figure and a3 a crossing one
    old["roles"][0]["projects"][0]["figure"] = GOOD  # a figure that passes
    old["roles"][0]["projects"][2]["figure"] = crossing  # one that does not, today
    pruned, gone = FD.prune(old)  # today's checks over every figure
    drawn = FD.check_drawing([(crossing, "main", "en")])[0]  # the crossing figure alone
    if drawn.get("issues"):  # the library drew the links across each other
        ok("prune takes out a figure today's checks turn down", [g[0] for g in gone] == ["a3"] and crossing not in FD.figures_of(pruned["roles"][0]["projects"][2])[0], str(gone))  # its other figure takes the main slot
    else:  # the library routed them apart: nothing to take out
        ok("prune keeps figures that pass", gone == [] or all(g[0] != "a1" for g in gone), str(gone))
    ok("prune keeps a figure that passes", pruned["roles"][0]["projects"][0].get("figure") == GOOD)  # a1's figure stays
    ok("prune does not change its input", old["roles"][0]["projects"][2]["figure"] == crossing)  # the caller's profile stays
    simple = json.loads((ROOT / "examples" / "sample_ko.json").read_text(encoding="utf-8"))  # the example: flow, compare and layers figures
    kept, gone2 = FD.prune(simple)  # none of them is the library's to judge
    ok("prune leaves the deck's simple templates alone", gone2 == [], str(gone2))
    measured_step()  # the question about numbers alone
    print(f"figure draft tests: {PASS[0]} passed, {FAIL[0]} failed")  # the summary line run.py reads
    return 1 if FAIL[0] else 0  # any failure fails the run


if __name__ == "__main__":  # run as a command
    sys.exit(main())  # main's return value is the exit code
