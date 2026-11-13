#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Figure drafts for the portfolio deck: figure data proposed from each project's evidence, checked, reviewed, then applied.

It draws on the figure library of src/deck_figures.js: a main figure (often several panels whose numbers match the project's cards) and a side figure per slide.

  python3 src/figure_draft.py propose <profile.json> [--only id,id] [--langs ko,en] [--max-calls 8] [--per-call N] [--out file]
        asks the AI backend (src/llm.py run) for figures for every deck project that has fewer than two, batched per chapter so that
        no more than --max-calls calls are made, and writes <profile>.figures.json with every proposal and its checks
  python3 src/figure_draft.py review <proposals.json> [--accept all|ids] [--reject ids]
        without flags prints the review list; with flags records decisions. A proposal that failed a check cannot be accepted
  python3 src/figure_draft.py repair <proposals.json> <profile.json>
        one more call: the proposals that failed a check go back with their findings, and the answers are checked again
  python3 src/figure_draft.py apply <proposals.json> <profile.json> [--out new.json]
        writes a new profile with the accepted figures (the input profile is never overwritten)

The checks run on every proposal before anyone sees it, and again on apply:
  shape   the library's data check (types, list sizes, numbers where numbers belong) and a drawing at the size of its slot, in every
          language the profile has, with the static audit (text outside the canvas, over text, across a box edge) and the cut notes
  facts   every number, date and name in the figure must be in that project's evidence (src/factcheck.py rules): values, counts,
          YYYY.MM dates, numbers inside labels, Latin names in Korean text, proper names in English text, Korean company names
  style   the style pack's banned characters and patterns
Tests use a stand-in for the model (propose(..., ask=fn)) or --stand-in answers.json; nothing here calls a model on its own.
"""
import copy  # profiles are never changed in place
import itertools  # the sets of panels whose notes the fit step drops
import json  # profiles, proposals, the model's answers
import pathlib  # paths
import re  # dates, names
import subprocess  # the drawing check runs in node
import sys  # arguments
import tempfile  # figures handed to node

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
sys.path.insert(0, str(ROOT / "src"))  # the sibling modules
import factcheck as F  # noqa: E402  the one fact-check rule set
import llm  # noqa: E402  the one place that talks to a model

SCHEMA = "offerowl-figure-proposals/1"  # the proposals file's format
SLOTS = {"main": (760, 570), "side": (470, 240)}  # the canvas each slot is drawn on in the chapter deck (src/deck_slides.js)
MEASURED = ("metric", "bars", "columns", "trend", "cluster")  # the views that show numbers
# A number with a unit of measure, not a year or a version: what a chart could show
MEASURE = re.compile(r"(?<![\d.])\d[\d,.]*\s*(?:%|배|ms|초|분|시간|일|주|개월|대|장|개|명|건|GB|TB|PB|Gbps|kW|MW|억|만|천|달|회|x\b|times\b|nodes?\b|GPUs?\b|hours?\b|seconds?\b|minutes?\b|days?\b|weeks?\b|months?\b)")
MEASURED_LEAST = 3  # numbers a project's own text must hold before it is asked about: two rarely make a chart
MEASURED_PER_CALL = 4  # projects in one call of the measured step
SIDE_TYPES = ("metric", "bars", "columns", "trend", "cluster", "phases", "pipeline")  # templates that fit the side column; the prompt lists them in this order, the measured views first
# The system prompt: evidence only, structure over invented numbers, JSON back
SYSTEM = ("You turn a person's evidence into figure data for portfolio slides. Use only facts in the evidence: never add numbers, "
          "dates, tools, products, clients or results that are not there. Prefer structure (zones, steps, phases, before and after) "
          "over numbers when the evidence has few numbers. Return only JSON.")


# ---------------------------------------------------------------- profile reading

def pick(v, lang):
    """The text of one language from a language pair {ko, en}; other values as they are"""
    if isinstance(v, dict) and v and set(v) <= {"ko", "en"}:  # a pair
        return v.get(lang) if lang in v else None  # a pair without this language shows nothing
    return v  # other values as they are


def texts(v) -> list:
    """Every string inside a value (both halves of language pairs, list items, nested objects)"""
    if isinstance(v, str):  # a plain string
        return [v]  # is one text
    if isinstance(v, list):  # list items in order
        return [t for x in v for t in texts(x)]  # flattened, nested lists included
    if isinstance(v, dict):  # objects and language pairs
        return [t for x in v.values() for t in texts(x)]  # every value, both halves of a pair
    return []  # numbers, booleans and None hold no text


def widen_dates(text: str) -> str:
    """Add the four-digit form of short dates ('24.02' -> '2024.02') so a figure's YYYY.MM dates match a ledger's short periods"""
    extra = re.findall(r"(?<![\d.])(\d{2})\.(\d{2})(?![\d])", text or "")  # YY.MM forms
    return text + ("\n" + " ".join(f"20{a}.{b}" for a, b in extra) if extra else "")  # the long forms appended; the text itself is unchanged


# Project fields whose words count as its evidence
PROJECT_TEXT = ("title", "short", "tagline", "summary", "lede", "role", "context", "stack", "chips", "points", "notes", "body_md", "cards", "period")
# Chapter fields whose words count as evidence for its projects
ROLE_TEXT = ("org", "heading", "short", "title", "desc", "lead", "clients", "stack", "context", "career", "funder", "name", "period", "start", "end", "place")


def deck_projects(prof: dict) -> list:
    """Every project that goes on the deck: (where, chapter, project). Company projects first, then chapters that are not companies"""
    out = []  # (where, chapter, project) in deck order
    for ri, r in enumerate(prof.get("roles") or []):  # company chapters
        for pi, p in enumerate(r.get("projects") or []):  # each project of the company
            if isinstance(p, dict) and p.get("deck") is not False:  # deck: false keeps a project off the deck
                out.append((f"roles[{ri}].projects[{pi}]", r, p))  # the path names the project in notes
    for ci, c in enumerate(prof.get("chapters") or []):  # research and other chapters
        for pi, p in enumerate((c or {}).get("projects") or []):  # each project of the chapter
            if isinstance(p, dict) and p.get("deck") is not False:  # the same deck rule
                out.append((f"chapters[{ci}].projects[{pi}]", c, p))  # its path among the chapters
    return out  # company projects first, as the deck orders them


def evidence_of(prof: dict, chapter: dict, proj: dict) -> str:
    """The evidence of one project: its own text, the text of the projects it names as evidence (evidence: [ids], such as the ledger
    entries behind a deck project), and its chapter's facts. Both languages are kept; short dates are widened"""
    index = {p.get("id"): p for _, _, p in deck_projects(prof)}  # projects by id, deck or not
    # Company projects off the deck too, so evidence ids reach ledger entries
    index.update({p.get("id"): p for r in prof.get("roles") or [] for p in r.get("projects") or [] if isinstance(p, dict)})
    parts = [t for k in PROJECT_TEXT for t in texts(proj.get(k))]  # the project's own words
    for pg in proj.get("pages") or []:  # a project over several slides has cards per page
        parts += [t for k in ("lede", "cards") for t in texts(pg.get(k))]  # each page's lede and cards
    for e in proj.get("evidence") or []:  # linked evidence (ids of other entries)
        if e in index:  # an unknown id adds nothing
            parts += [t for k in PROJECT_TEXT for t in texts(index[e].get(k))]  # the linked entry's own words
    parts += [t for k in ROLE_TEXT for t in texts(chapter.get(k))]  # the chapter's facts (scale, clients, stack)
    return widen_dates("\n".join(parts))  # one text, short dates widened


def figures_of(proj: dict) -> list:
    """The figures a project already has, per page (a project with pages has its figures on the pages)"""
    pages = proj.get("pages") or [proj]  # a project without pages is its own page
    # Per page the main figure, then the others, without empty slots
    return [[f for f in ([pg.get("figure")] if pg.get("figure") else []) + list(pg.get("figures") or []) if f] for pg in pages]


def cards_of(page: dict, lang: str) -> list:
    """The card heads of a page in one language, numbered as the deck numbers them"""
    cards = pick(page.get("cards"), lang) or []  # the cards in this language
    return [f"{i + 1}. {c[0] if isinstance(c, list) else c.get('head', '')}" for i, c in enumerate(cards)]  # '1. head' from a list card or an object's head


# ---------------------------------------------------------------- the model

def catalog() -> dict:
    """The figure templates, their use and data shape, from the library itself (one source for the prompt and the docs)"""
    # Node prints the library's CATALOG as JSON
    r = subprocess.run(["node", "-e", "process.stdout.write(JSON.stringify(require('./src/deck_figures').CATALOG))"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)  # a failure raises: the prompt needs the catalog
    return json.loads(r.stdout)  # type -> { use, shape }


def prompt_for(batch: list, langs: list, cat: dict) -> str:
    """One question for a batch of projects. Every text field is a language pair when the profile has two languages"""
    pair = len(langs) > 1  # bilingual text in every label
    # The task first, then the template list
    lines = ["Propose figure data for portfolio slides, one entry per project below.", "",
             "Templates (type: use -> data shape):"]
    lines += [f"- {t}: {c['use']} -> {c['shape']}" for t, c in cat.items()]  # one line per template: what it is for and its data shape
    # The rules every proposal is checked against later
    lines += ["", "Rules:",
              "- Per project page, give a main figure and, when the page has room for one and the evidence holds a second view, a side figure.",
              "- The main figure is usually 'panels' with 2 to 4 sub-figures; give each panel a short title and the number (mark) of the card it explains.",
              # The view follows what the work was; a pipeline is the easy default, so it is held to real sequences
              "- Pick the view that shows the work: a system as zones of nodes (architecture; give a node 'units' when the evidence states how many "
              "GPUs or servers it holds), a cluster or a data center as racks (rack), an organization or a stack as a hierarchy (tree), options "
              "against criteria (matrix), a schedule (timeline, gantt), a change (beforeAfter), measured numbers (metric, bars, columns, trend). "
              "A pipeline is for a real sequence of steps: at most one per page.",
              # A pipeline is the easy answer: without this a page whose evidence has numbers still drew its steps
              "- Where the evidence states measured numbers, show them: a before and an after under stated conditions is a metric, one number "
              "per item is bars, numbers per group are columns, numbers over ordered points are a trend, counts of nodes per role are a cluster. "
              "A page whose evidence has two or more numbers of one kind draws them, as its side figure or as a panel, before any pipeline.",
              # What a half frame holds, so that a composite draws with its notes instead of being thinned by the fit step
              "- The main figure is 760 x 570, and a panel gets about half of it. A sub-figure in 'panels' holds at most: architecture 3 zones of "
              "1 to 3 nodes, beforeAfter 3 items a side, pipeline 5 steps, matrix 5 rows and 4 columns, tree 4 children with 2 items each.",
              f"- A side figure is one of: {', '.join(SIDE_TYPES)}. It is 470 wide and as high as the page's side room below: one row of at "
              "most 4 steps whose titles are one or two words, or at most 5 bars, rows or periods.",
              "- Kinds give color a meaning: mine = the person's own part, key = core or outcome, old = before, ext = external or customer, data = data or storage, plan = proposed. Mark 'mine' only where the evidence says the person did it.",
              "- Every number and date (YYYY.MM) must appear in that project's evidence. No estimates, no invented values or scales. Without numbers, draw structure.",
              "- Labels are short: titles up to 4 words, notes up to 7 words. Captions are '**Title** one short line'.",
              "- Keep tool and product names as written in the evidence. Write labels in sentence case: capitals only on names."]
    if pair:  # two languages: every label as a pair
        # So one proposal serves both editions
        lines.append('- Write every shown text as a pair {"ko": "...", "en": "..."} (Korean and English), the same facts in both.')
    else:
        lines.append(f"- Write the text in {'Korean' if langs[0] == 'ko' else 'English'}.")  # one language: plain strings in it
    # The answer's shape, the keys call_model requires
    lines += ["", 'Return JSON: {"projects": [{"id": "...", "pages": [{"page": 0, "main": {...}, "side": {...} or null}], "why": "which evidence each figure rests on"}]}', ""]
    for b in batch:  # one block per project
        lines.append(f"### Project {b['id']}: {b['title']}")  # the id the answer must echo
        for k, pg in enumerate(b["pages"]):  # each slide page of the project
            room = pg.get("room")  # the side room the deck leaves on this page (None: no cards, so no side column)
            side = "no side column" if room is None else "no side figure (the cards fill the column)" if room < 110 else f"side room {int(min(300, room))} px"
            # The card heads, how many figures the page already has, and the room for a side figure
            lines.append(f"Page {k}: cards: " + ("; ".join(pg["cards"]) or "none") + (f" (has {pg['have']} figure(s) already)" if pg["have"] else "") + f"; {side}")
        lines.append("Evidence:\n<<<\n" + b["evidence"][:12000] + "\n>>>\n")  # the evidence, fenced and capped so one project cannot crowd the prompt
    return "\n".join(lines)  # one prompt for the batch


def numbers_in(v) -> list:
    """Every number a figure shows, in its values and in the numbers inside its labels."""
    if isinstance(v, bool):  # a switch, not a number
        return []
    if isinstance(v, (int, float)):  # a value
        return [v]
    if isinstance(v, str):  # a label may hold numbers ("200G")
        return [float(x) if "." in x else int(x) for x in re.findall(r"\d+(?:\.\d+)?", v)]
    if isinstance(v, dict):  # every field
        return [n for x in v.values() for n in numbers_in(x)]
    if isinstance(v, list):  # every item
        return [n for x in v for n in numbers_in(x)]
    return []


KOREAN_UNITS = {"s": "초", "sec": "초", "secs": "초", "seconds": "초", "min": "분", "mins": "분", "minutes": "분", "h": "시간", "hr": "시간",
                "hours": "시간", "x": "배", "×": "배", "times": "배"}  # a unit a model writes in Latin letters inside the Korean half


def korean_units(fig):
    """A chart whose Korean unit is a Latin abbreviation ("s") gets the Korean word for it, which the facts check reads as a unit."""
    if isinstance(fig, dict) and isinstance(fig.get("unit"), dict) and isinstance(fig["unit"].get("ko"), str):  # a language pair
        word = fig["unit"]["ko"].strip()  # the Korean half
        if word.lower() in KOREAN_UNITS:  # an abbreviation the check would read as a name
            fig = {**fig, "unit": {**fig["unit"], "ko": KOREAN_UNITS[word.lower()]}}  # the Korean word
    return fig


def measure_lines(text: str) -> list:
    """The lines of a text that hold a number with a unit of measure."""
    return [ln.strip() for ln in re.split(r"\n+|(?<=[.!?다])\s+", text) if MEASURE.search(ln)]  # line by line, then sentence by sentence


def measured_prompt(batch: list, langs: list, cat: dict) -> str:
    """One question about the numbers alone. Asked together with the other views, a model draws the sequence of steps it can see
    at once and leaves the numbers in the text, so they get a question of their own."""
    lines = ["Some numbers in these projects can be shown as a chart. For each project below, look only at its measured numbers, and draw the "
             "ones that belong together as one figure.", "", "Templates (type: use -> data shape):"]  # the task, then the views it may use
    lines += [f"- {t}: {cat[t]['use']} -> {cat[t]['shape']}" for t in MEASURED if t in cat]  # only the measured views
    lines += ["", "Rules:", "- Every number must appear in the project's lines below, as written. No sums, ratios, estimates or rounding of your own.",  # the facts check holds it to this
              "- One figure shows one kind of thing in one unit. Numbers in different units, or about different things, do not share a figure.",
              "- A metric is one thing before and after, with its conditions in the caption or the labels. Bars need at least two items a reader would compare.",
              "- Keep the comparison honest: numbers measured under different conditions say so in their labels, or stay out of the figure.",
              "- A chart compares results: one thing before and after, one option against another, or a result per item measured the same way. "
              "Settings, specifications, sizes, intervals that were tried, and the two ends of a range are not results, and a chart of them says nothing.",
              "- Give figure: null when the numbers do not compare results, or when the page's figure already shows them. Most projects have no chart.",
              "- The figure is 470 wide and as high as the page's side room: at most 5 bars, rows or periods. Labels are short, and captions are '**Title** one short line'.",
              "- A unit in Korean text is written in Korean (초, 분, 시간, 배), never as a Latin letter alone.",
              '- Write every shown text as a pair {"ko": "...", "en": "..."} (Korean and English), the same facts in both.' if len(langs) > 1 else f"- Write the text in {'Korean' if langs[0] == 'ko' else 'English'}.",  # as in the main request
              "", 'Return JSON: {"projects": [{"id": "...", "page": 0, "figure": {...} or null, "why": "which lines it rests on"}]}', ""]  # the answer's shape
    for b in batch:  # one block per project
        lines.append(f"### Project {b['id']}: {b['title']}")  # the id the answer must echo
        lines += [f"Page {k}: cards: " + ("; ".join(pg["cards"]) or "none") + (f"; its figure already shows: {', '.join(pg['shown'])}" if pg.get("shown") else "") for k, pg in enumerate(b["pages"])]  # which page says what, and the numbers its figure already shows
        lines.append("Lines:\n<<<\n" + "\n".join(b["lines"])[:4000] + "\n>>>\n")  # only the lines with numbers, so nothing else competes for attention
    return "\n".join(lines)  # one prompt for the batch


def ask_measured(prof: dict, doc: dict, only, langs: list, cat: dict, rooms: dict, ask, max_calls: int) -> None:
    """The measured step: for each project whose own text holds numbers and which shows none yet, one question about them. The answers
    join the proposals as side figures; settle_measured() decides, after the checks, which of them stand."""
    entries = {e["id"]: e for e in doc["projects"]}  # the proposals so far, by project
    todo = []  # the projects to ask about
    for where, ch, p in deck_projects(prof):  # in deck order
        if only and p.get("id") not in only:  # --only limits the projects
            continue
        pid = p.get("id") or where  # its id
        shown = [f for pg in figures_of(p) for f in pg] + [f["figure"] for f in (entries.get(pid) or {}).get("figures") or []]  # what it has and what was just proposed
        if any(isinstance(f, dict) and f.get("type") in MEASURED for f in shown):  # it already shows numbers
            continue
        own = "\n".join(t for k in PROJECT_TEXT for t in texts(p.get(k)))  # the project's own words, not its chapter's scale
        got = measure_lines(own)  # the lines with numbers
        if sum(len(MEASURE.findall(ln)) for ln in got) < MEASURED_LEAST:  # too few to compare
            continue
        pages = p.get("pages") or [p]  # the slides of the project
        proposed = {f["page"]: f["figure"] for f in (entries.get(pid) or {}).get("figures") or [] if f["slot"] == "main"}  # the main figures just proposed
        shown_at = lambda k, pg: sorted({str(v) for v in numbers_in(proposed.get(k) or (figures_of(p)[k][:1] or [None])[0])})[:12]  # noqa: E731  the numbers a page's main figure shows
        todo.append({"id": pid, "where": where, "chapter": ch, "project": p, "title": pick(p.get("title"), langs[0]), "lines": got,
                     "pages": [{"cards": cards_of(pg, langs[0]), "shown": shown_at(k, pg)} for k, pg in enumerate(pages)]})  # asked about
    for i in range(0, min(len(todo), max_calls * MEASURED_PER_CALL), MEASURED_PER_CALL):  # at most this many calls
        batch = todo[i:i + MEASURED_PER_CALL]  # a few projects per call
        try:  # a missing backend and a bad answer are told apart
            ans = ask(measured_prompt(batch, langs, cat))  # one call
            doc["calls"] += 1  # counted with the others
        except llm.LLMUnavailable as e:  # no backend: the figures so far stand
            doc["errors"].append(f"measured: stopped: {e}")  # the note says why
            return  # no later batch is tried
        except ValueError as e:  # the answer did not have the right shape
            doc["calls"] += 1  # a bad answer still spent a call
            doc["errors"].append(f"measured {[t['id'] for t in batch]}: {e}")  # named in the note
            continue  # the next batch still gets its call
        got = {str(x.get("id")): x for x in (ans.get("projects") or []) if isinstance(x, dict)}  # the answer's entries by id
        for t in batch:  # each project asked about
            a = got.get(str(t["id"])) or {}  # its answer
            if not isinstance(a.get("figure"), dict):  # no chart in these numbers: an honest answer
                continue
            k = a.get("page", 0) if isinstance(a.get("page", 0), int) and 0 <= a.get("page", 0) < len(t["pages"]) else 0  # the page it goes on
            entry = entries.get(t["id"])  # the project's proposals
            if entry is None:  # it was not asked about before: every page had its two figures
                entry = {"id": t["id"], "where": t["where"], "title": t["title"], "why": "", "figures": []}  # its entry
                doc["projects"].append(entry)  # in the file
                entries[t["id"]] = entry  # found next time
            entry["_evidence"] = entry.get("_evidence") or evidence_of(prof, t["chapter"], t["project"])  # what the checks hold it to
            entry["figures"].append({"n": f"{t['id']}#{k}.measured", "page": k, "slot": "side", "figure": korean_units(a["figure"]), "measured": True})  # the chart


def settle_measured(doc: dict, prof: dict) -> None:
    """After the checks: a chart that passed takes the side slot of its page from a drawn sequence of steps, and one that failed
    goes, leaving what was there. A person's or an earlier run's other figures are not taken away."""
    index = {p.get("id") or w: p for w, _, p in deck_projects(prof)}  # the profile's projects by id
    for e in doc["projects"]:  # every project
        for f in [x for x in e["figures"] if x.get("measured")]:  # its charts
            if f["status"] != "ok":  # it failed a check
                doc["errors"].append(f"{f['n']}: not used: " + "; ".join(f["checks"]["shape"] + f["checks"]["facts"][:2]))  # why, for the record
                e["figures"].remove(f)  # the other figures stand
                continue
            rivals = [x for x in e["figures"] if x is not f and x["page"] == f["page"] and x["slot"] == "side"]  # a side figure proposed for the same page
            pg = ((index.get(e["id"]) or {}).get("pages") or [index.get(e["id"]) or {}])  # the project's pages
            page = pg[f["page"]] if f["page"] < len(pg) else {}  # its page in the profile
            kept = page.get("figures") or []  # the later figures it already has
            if kept and any(isinstance(x, dict) and x.get("type") not in ("pipeline", "phases") for x in kept):  # someone's other view is there
                doc["errors"].append(f"{f['n']}: not used: the page keeps its side figure")  # said, not dropped silently
                e["figures"].remove(f)  # the chart goes
                continue
            if kept:  # only a drawn sequence of steps: the numbers say more
                f["replaces"] = True  # apply() takes it away
            for r in rivals:  # the sequence proposed just now
                e["figures"].remove(r)  # gives way


def call_model(prompt: str) -> dict:
    """One call to the chosen backend (src/llm.py): JSON with a projects list. No retry inside: propose() spends the call budget"""
    # The task name goes to the call log; an answer without projects raises ValueError, which propose() counts
    return llm.run("draft-figures", prompt, system=SYSTEM, want_json=True, required=("projects",), timeout=900, retries=0)


# ---------------------------------------------------------------- checks

# Keys that steer the drawing; their values are not facts to check
NON_FACT_KEYS = {"type", "layout", "kind", "unitKinds", "better", "scheme", "mark", "split", "delta", "id", "legend", "_w", "_h", "_lang"}
# Words that are drawing instructions where they stand in a list: a kind after a label ([title, sub, "mine"]), a matrix cell mark
NON_FACT_WORDS = {"mine", "key", "old", "ext", "data", "plan", "stop", "hl", "off", "yes", "partial", "no", ""}


def facts_in(fig, lang, path="figure"):
    """(strings, numbers) a figure shows in one language, without layout fields (types, kinds, marks) and without the index pairs
    that place bands over steps or columns. Link ends are node ids, not shown text"""
    strs, nums = [], []  # (path, value) pairs

    def walk(v, p, key=None):  # v at path p, under key when it is a field
        v = pick(v, lang)  # a language pair becomes its language's text
        if key in NON_FACT_KEYS or v is None:  # layout fields and missing values
            return  # are not shown facts
        if isinstance(v, bool):  # flags such as flow: true
            return  # draw nothing
        if isinstance(v, (int, float)):  # a drawn number
            nums.append((p, v))  # must be in the evidence
        elif isinstance(v, str):  # a shown text
            if key is None and v in NON_FACT_WORDS:  # a kind or a mark inside a list is not shown text
                return  # skipped
            strs.append((p, v))  # its numbers and names are checked
        elif isinstance(v, list):  # list items, by index
            for i, x in enumerate(v):  # each item
                walk(x, f"{p}[{i}]")  # no key: a word in a list may be a kind
        elif isinstance(v, dict):  # an object, maybe a sub-figure
            if v.get("type") in ("pipeline", "matrix") and isinstance(v.get("groups"), list):  # bands: [label, from index, to index]
                v = {**v, "groups": [[g[0]] if isinstance(g, list) else g for g in v["groups"]]}  # the band label stays, its indexes go
            if v.get("type") == "matrix" and isinstance(v.get("highlight"), (int, float)):  # a column index, not a value
                v = {k: x for k, x in v.items() if k != "highlight"}  # the index is dropped
            if v.get("type") == "architecture" and isinstance(v.get("links"), list):  # link ends are ids; the label is shown
                v = {**v, "links": [lk[2:3] if isinstance(lk, list) else [lk.get("label")] for lk in v["links"]]}  # only the label stays
            for k, x in v.items():  # each field
                walk(x, f"{p}.{k}", k)  # with its key, so layout keys are skipped

    walk(fig, path)  # from the figure's root
    return strs, nums  # every shown text and number


def english_names(text: str) -> set:
    """Name-like words of an English text: capitalized words that do not start a sentence, words with digits or inner capitals"""
    out = set()  # lowercased names
    for sent in re.split(r"(?<=[.!?:;])\s+|\s{2,}|,\s*", text):  # sentences and list parts
        words = re.findall(r"[A-Za-z][A-Za-z0-9+#.\-/]*", sent)  # Latin words, with the characters tool names use
        for i, w in enumerate(words):  # i: the word's place in its sentence
            for k, w0 in enumerate(x for x in re.split(r"[-/]", w.strip(".-/")) if x):  # each part of 'kW-range' or 'CI/CD' on its own
                if re.search(r"\d|[a-z][A-Z]|^[A-Z]{2,}", w0) or ((i > 0 or k > 0) and w0[:1].isupper()):  # S3, gRPC, AWS, a capital mid-sentence
                    out.add(w0.lower())  # compared without case
    return out - F.COMMON_EN  # common words are not names


def check_facts(fig: dict, evidence: str, langs: list) -> list:
    """Problems with the facts of one figure: numbers, dates, names that its project's evidence does not hold"""
    bad, ev_nums = [], {v for v, _ in F.number_tokens(evidence, date_parts=False)}  # findings, and every number the evidence states; the month of a date measures nothing
    ev_latin = F.latin_tokens(evidence)  # the evidence's Latin words, for plural matching
    for lang in langs:  # each language's text is checked on its own
        strs, nums = facts_in(fig, lang)  # what the figure shows in it
        for p, v in nums:  # values drawn as bars, counts, points
            if float(v) not in ev_nums:  # compared as numbers, so 9 and 9.0 match
                bad.append(f"{lang} {p}: the value {v:g} is not in the evidence")  # the path says where the value sits
        for p, s in strs:  # each shown text
            if lang == "ko" or re.search(r"[가-힣]", s):  # Korean text: the rule set of the other drafts
                bad += [f"{lang} {p}: {w}" for w in F.unsupported(s.replace("**", "").replace("==", ""), evidence)]  # markup removed before the check
            else:  # English text: numbers and number words as in Korean, names must be in the evidence
                why = F.unsupported(s.replace("**", "").replace("==", ""), evidence, check_latin=False)  # Latin words are checked as names below instead
                # Names neither in the evidence nor plurals of its words
                new = sorted(w for w in english_names(s) if not F.plural_ok(w, ev_latin) and w not in evidence.lower())
                if new:  # one finding lists them
                    why.append("names not in the evidence: " + ", ".join(new[:5]))  # five at most, enough to fix
                bad += [f"{lang} {p}: {w}" for w in why]  # each with its language and path
    return sorted(set(bad))  # each finding once, in a stable order


def check_style(fig: dict, langs: list, style: dict) -> list:
    """The style pack's banned characters and patterns in the figure's text"""
    text = " ".join(s for lang in langs for _, s in facts_in(fig, lang)[0])  # every shown text in every language
    bad = [f"banned character '{c}'" for c in style.get("banned_chars", "") if c in text]  # characters the style pack forbids
    return bad + [why for pat, why in style.get("banned_patterns", []) if re.search(pat, text)]  # and patterns, with the pack's own reason


def localize(v, lang):
    """A figure in one language (language pairs collapsed), as the deck's loader would give it to the template"""
    v = pick(v, lang)  # a pair becomes this language's text
    if isinstance(v, list):  # lists item by item
        return [localize(x, lang) for x in v]  # nested pairs too
    if isinstance(v, dict):  # objects field by field
        return {k: localize(x, lang) for k, x in v.items()}  # keys stay as they are
    return v  # plain values unchanged


def side_rooms(prof: dict) -> dict:
    """The canvas height the deck leaves for a side figure on every project page (project id -> one height per page, the smaller of
    the two languages), from the deck's own estimate (node src/deck_slides.js --rooms), so the review draws side figures where they go"""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as t:  # node reads the profile from a file
        json.dump(prof, t, ensure_ascii=False)  # written as UTF-8 text
    out = {}  # project id -> rooms per page
    try:  # the temporary file goes even when node fails
        for lang in profile_langs(prof):  # the room differs by language (text widths)
            r = subprocess.run(["node", "src/deck_slides.js", "--rooms", t.name, lang], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")  # the deck's own estimate
            if r.returncode != 0:  # the profile does not load for the deck: the default side size stands
                continue  # this language adds no rooms
            for k, v in json.loads(r.stdout).items():  # each project's rooms in this language
                old = out.get(k, v)  # what the other language gave, or this one
                # Per page the smaller room, ignoring a language that had none
                out[k] = [min(x for x in (a, b) if x is not None) if (a is not None or b is not None) else None for a, b in zip(old, v)]
    finally:  # always clean up
        pathlib.Path(t.name).unlink(missing_ok=True)  # the temporary profile
    return out  # rooms per project


def prune(prof: dict, langs: list | None = None, only=None) -> tuple:
    """The profile without the figures whose drawing today's checks turn down at their slot (a figure drawn before a check was
    added, or after its slide changed): a page's first figure is drawn at the main size, a later side-type figure at the side
    size. A figure of the deck's simple templates (flow, compare, layers) is not the library's to draw, and a later figure of
    another type joins the main one as a panel on the slide: neither is judged here. Returns (new profile, [(project id, page,
    caption)] taken out). A later propose() asks again for the gaps this leaves."""
    new = copy.deepcopy(prof)  # the input is never changed
    langs = langs or profile_langs(new)  # every language the deck prints
    lib = set(catalog())  # the types the library draws and audits
    spots, items = [], []  # (project, page, figure) of every figure, and what check_drawing draws
    for _w, _c, p in deck_projects(new):  # every deck project
        if only and p.get("id") not in only:  # a run limited to some projects
            continue
        for k, figs in enumerate(figures_of(p)):  # page by page
            for i, f in enumerate(figs):  # the main figure first
                if not isinstance(f, dict) or f.get("type") not in lib or (i > 0 and f.get("type") not in SIDE_TYPES):  # not drawn where this would draw it
                    continue  # the deck's own probe judges it on the printed slide
                spots.append((p, k, f))  # where it is
                items += [(f, "main" if i == 0 else "side", lang) for lang in langs]  # drawn in every language
    if not items:  # nothing drawn yet
        return new, []
    drawn, per = check_drawing(items), len(langs)  # one node run; drawings per figure
    bad, gone = set(), []  # the figures turned down, and their record
    for n, (p, k, f) in enumerate(spots):  # each figure
        if any(d.get("error") or d.get("issues") or d.get("cut") for d in drawn[n * per:(n + 1) * per]):  # the review would flag it today
            bad.add(id(f))  # turned down
            gone.append((p.get("id"), k, re.sub(r"[*]", "", str(pick(f.get("caption"), langs[0]) or f.get("type")))[:40]))  # named for the record
    for p, k in {(id(p), k): (p, k) for p, k, f in spots if id(f) in bad}.values():  # each page that loses a figure
        page = (p.get("pages") or [p])[k]  # the page
        keep = [f for f in figures_of(p)[k] if id(f) not in bad]  # the figures that stay, in slot order
        page.pop("figure", None)  # laid out again
        page.pop("figures", None)
        if keep:  # the first one takes the main slot
            page["figure"] = keep[0]
        if keep[1:]:  # the others follow
            page["figures"] = keep[1:]
    return new, gone


def check_drawing(items: list) -> list:
    """Draw every (figure, slot or (width, height), lang) with the library; per item {ok, issues, cut, error} (one node run for all)"""
    size = lambda slot: SLOTS[slot] if isinstance(slot, str) else slot  # noqa: E731  a slot name or an explicit size
    # Each figure in one language, carrying its size and language for the command
    figs = [{**localize(f, lang), "_w": size(slot)[0], "_h": size(slot)[1], "_lang": lang} for f, slot, lang in items]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as t:  # node reads the figures from a file
        json.dump(figs, t, ensure_ascii=False)  # written as UTF-8 text
    r = subprocess.run(["node", "src/deck_figures.js", "--audit", t.name], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")  # one node run audits every item
    pathlib.Path(t.name).unlink(missing_ok=True)  # not needed after the run
    if r.returncode != 0:  # node itself failed: every item fails with its message
        return [{"ok": False, "error": (r.stderr.strip().splitlines() or ["node failed"])[-1]} for _ in items]  # the last line of node's error
    return json.loads(r.stdout)  # one result per item, in order


def review_one(fig, slot: str, evidence: str, langs: list, style: dict, drawn: list, room=None) -> dict:
    """All checks of one proposal; drawn holds its drawing results per language, room the side room of its page (None: unknown)"""
    shape = [d.get("error") for d in drawn if d.get("error")]  # data the library refused
    if slot == "side" and room is not None and room < 110:  # the deck has no side figure on this page: its cards fill the column
        # Worded so repair() can tell it apart and not send it again
        shape.append(f"no room for a side figure on this page (the cards leave {int(room)} px); it would have to join the main figure")
    # Per language the audit findings and the cut notes of its drawing
    layout = {lang: (d.get("issues") or []) + (d.get("cut") or []) for lang, d in zip(langs, drawn) if not d.get("error")}
    if slot == "side" and isinstance(fig, dict) and fig.get("type") not in SIDE_TYPES:  # too wide for the right column
        shape.append(f"a side figure must be one of {', '.join(SIDE_TYPES)}")  # the finding names the allowed types
    facts = check_facts(fig, evidence, langs) if isinstance(fig, dict) else ["not a figure"]  # an answer that is not an object cannot be checked
    # Every kind of finding, kept apart for the review
    checks = {"shape": sorted(set(shape)), "layout": layout, "facts": facts, "style": check_style(fig, langs, style) if isinstance(fig, dict) else []}
    ok = not checks["shape"] and not facts and not checks["style"] and not any(layout.values())  # ok only when every check is empty
    return {"checks": checks, "status": "ok" if ok else "flagged"}  # a flagged proposal cannot be accepted


# ---------------------------------------------------------------- the three steps

def style_pack(name: str = "default") -> dict:
    """The style pack (src/style/<name>.json)"""
    f = ROOT / "src" / "style" / f"{name}.json"  # the pack's file
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}  # no pack: no style rules


def profile_langs(prof: dict) -> list:
    """The languages the profile's text is written in: both when any project text is a language pair"""
    pairs = any(isinstance(p.get("title"), dict) for _, _, p in deck_projects(prof))  # a pair title means a bilingual profile
    # Otherwise the one language of the titles: Korean when any has Hangul
    return ["ko", "en"] if pairs else ["ko" if any(re.search(r"[가-힣]", str(p.get("title"))) for _, _, p in deck_projects(prof)) else "en"]


def propose(prof: dict, *, only=None, langs=None, max_calls=8, per_call=None, ask=None, style=None, measured_calls=4) -> dict:
    """Ask for figures for every deck project short of two per page, then ask about the measured numbers of the projects that hold
    some (measured_calls more calls at most), check each proposal, and return the proposals document.
    ask(prompt) -> answer dict is the model call (llm.run by default; tests pass a stand-in)"""
    ask = ask or call_model  # the model call, unless a test passes a stand-in
    langs = langs or profile_langs(prof)  # the profile's languages unless given
    style = style if style is not None else style_pack()  # an empty pack given on purpose is kept
    todo = []  # projects to ask about, in deck order
    rooms = side_rooms(prof)  # the side room of every page, so the prompt can size the side figures
    for where, ch, p in deck_projects(prof):  # in deck order
        if only and p.get("id") not in only:  # --only limits the projects
            continue  # not asked about
        have = figures_of(p)  # figures per page
        if all(len(f) >= 2 for f in have):  # every page already has two figures
            continue  # nothing to ask
        pages = p.get("pages") or [p]  # the slides of the project
        # Where it is, its chapter, the project, its id (or path) and title
        todo.append({"where": where, "chapter": ch, "project": p, "id": p.get("id") or where, "title": pick(p.get("title"), langs[0]),
                     "evidence": evidence_of(prof, ch, p),  # the facts every proposal must keep to
                     # Each page's card heads, figure count and side room
                     "pages": [{"cards": cards_of(pg, langs[0]), "have": len(have[k]), "room": ((rooms.get(p.get("id")) or [])[k:k + 1] or [None])[0]}
                               for k, pg in enumerate(pages)]})
    # Batches: projects of one chapter together (shared facts), up to three a call (longer prompts lose detail), more when the budget
    # needs it, so that the calls stay within max_calls
    per = per_call or max(3, -(-len(todo) // max(1, max_calls)))
    batches, cur = [], []                                    # the batches, and the one being filled
    size = {}                                                # projects per chapter
    for t in todo:                                           # count the projects of each chapter
        size[id(t["chapter"])] = size.get(id(t["chapter"]), 0) + 1  # keyed by identity: a chapter dict cannot be a key
    for t in todo:                                           # fill the batches in deck order
        new_ch = cur and cur[-1]["chapter"] is not t["chapter"]   # a chapter starts: split unless it fits the batch whole
        # Close the batch when it is full or a chapter would not fit whole, while calls remain
        if cur and (len(cur) >= per or (new_ch and len(cur) + size[id(t["chapter"])] > per)) and len(batches) + 1 < max_calls:
            batches.append(cur)                              # the batch is done
            cur = []                                         # start the next
        cur.append(t)                                        # this project joins the open batch
    if cur:                                                  # the last batch
        batches.append(cur)                                  # is kept too
    cat = catalog()                                          # the template list, read once for every prompt
    doc = {"schema": SCHEMA, "langs": langs, "calls": 0, "projects": [], "errors": []}  # the proposals file being built
    for bi, batch in enumerate(batches):                     # one call per batch, a second only after a bad answer
        ans, stop = None, False                              # the answer, and whether the backend is gone
        for _attempt in range(2):                            # a wrong answer is asked again only while the budget allows
            if _attempt and doc["calls"] >= max_calls:      # no budget left for a second try
                break                                        # keep the budget for later batches
            try:                                             # a missing backend and a bad answer are told apart
                ans = ask(prompt_for(batch, langs, cat))     # one call
                doc["calls"] += 1                            # counted against max_calls
                break                                        # a good answer ends the tries
            except llm.LLMUnavailable as e:                  # no backend: stop here and keep what was proposed so far
                doc["errors"].append(f"stopped: {e}")        # the note says why the run stopped
                stop = True                                  # no later batch is tried
                break                                        # out of the tries
            except ValueError as e:                          # the answer did not have the right shape
                doc["calls"] += 1                            # a bad answer still spent a call
                doc["errors"].append(f"batch {[t['id'] for t in batch]}: {e}")  # the batch's projects named in the note
                if doc["calls"] + (len(batches) - bi - 1) >= max_calls:   # a retry would leave a later batch without a call
                    break                                    # no retry
        if stop:  # the backend is gone
            break  # keep what was proposed so far
        if ans is None:  # both tries failed
            continue  # the next batch still gets its call
        got = {str(x.get("id")): x for x in (ans.get("projects") or []) if isinstance(x, dict)}  # the answer's entries by id, compared as text
        for t in batch:  # every project asked about gets an entry
            a = got.get(str(t["id"]))  # its answer, if any
            # The project's entry, with the model's reason
            entry = {"id": t["id"], "where": t["where"], "title": t["title"], "why": (a or {}).get("why", ""), "figures": []}
            if not a:  # the model skipped this project
                doc["errors"].append(f"{t['id']}: no proposal in the answer")  # noted; the entry stays empty
            for pg in (a or {}).get("pages") or []:  # each page the answer covers
                k = pg.get("page", 0) if isinstance(pg.get("page", 0), int) else 0  # the page index, 0 when missing or not a number
                if k >= len(t["pages"]):  # a page the project does not have
                    continue  # its figures have nowhere to go
                for slot in ("main", "side"):  # the two slots of a page
                    if pg.get(slot) and len(entry["figures"]) < 2 * len(t["pages"]):  # a given figure, two per page at most
                        # The n field names it project#page.slot, as review flags expect
                        entry["figures"].append({"n": f"{t['id']}#{k}.{slot}", "page": k, "slot": slot, "figure": pg[slot]})
            doc["projects"].append(entry)  # in deck order
            entry["_evidence"] = t["evidence"]  # kept for the checks, dropped from the file
    stopped = any(str(x).startswith("stopped:") for x in doc["errors"])  # the backend went away during the first step
    if measured_calls and not stopped:  # the numbers get a question of their own
        ask_measured(prof, doc, only, langs, cat, rooms, ask, measured_calls)  # at most this many calls
    recheck(doc, style, prof)  # every check on every proposal, lighter forms included
    settle_measured(doc, prof)  # which charts stand
    for e in doc["projects"]:  # the evidence was only for the checks
        e.pop("_evidence", None)  # the file stays small and free of copied text
    return doc  # the proposals document


def lighter(fig: dict) -> list:
    """Lighter forms of a figure that did not fit its slot, lightest change first: (what was dropped, figure). Notes go first (box
    subs, step notes, side notes, panel notes): in a composite the notes of one panel, then of two, and so on, before every note;
    then the last panels, down to two (with their notes, then without), and last the first panel alone. Titles, values and
    structure stay, so a lighter form never says more than the proposal did"""
    def no_notes(v):  # v without its notes, at every depth
        if isinstance(v, dict):  # an object: a figure or a part of one
            t = v.get("type")  # the template, when v is a figure
            # Every field except notes (a number under those keys is data and stays)
            out = {k: no_notes(x) for k, x in v.items() if not (k in ("sub", "note", "conditions") and not isinstance(x, (int, float)))
                   and not (k == "groups" and t == "pipeline")}  # step notes, side notes, and the bands over steps
            for key in ("steps", "items"):  # [title, note, kind, mark]: keep the title and the drawing fields
                if isinstance(out.get(key), list):  # only when the field is a list
                    out[key] = [[it[0], "", *it[2:]] if isinstance(it, list) and len(it) > 1 else it for it in out[key]]  # the note slot emptied, kind and mark kept
            if t in ("phases", "timeline") and isinstance(out.get("rows" if t == "phases" else "phases"), list):   # [name, start, end, note, kind]
                key = "rows" if t == "phases" else "phases"  # the field that holds them
                # The fourth slot (the note) emptied, the dates and kind kept
                out[key] = [[r[0], r[1], r[2], "", *r[4:]] if isinstance(r, list) and len(r) > 3 else r for r in out[key]]
            if t == "architecture" and isinstance(out.get("links"), list):  # [from, to, label, kind]: the label is a link's note
                # The label emptied, the ends and the kind kept (an object link loses its label field)
                out["links"] = [[lk[0], lk[1], "", *lk[3:]] if isinstance(lk, list) and len(lk) > 2 else
                                {k: x for k, x in lk.items() if k != "label"} if isinstance(lk, dict) else lk for lk in out["links"]]
            if t == "beforeAfter":  # its items sit inside the two sides
                for side in ("before", "after"):  # each side
                    if isinstance(out.get(side), dict) and isinstance(out[side].get("items"), list):  # only a side with an item list
                        # Item notes emptied, as for steps
                        out[side]["items"] = [[it[0], "", *it[2:]] if isinstance(it, list) and len(it) > 1 else it for it in out[side]["items"]]
            return out  # the object without notes
        if isinstance(v, list):  # lists item by item
            return [no_notes(x) for x in v]  # sub-figures in panels too
        return v  # plain values unchanged
    forms = []  # (what was dropped, figure), lightest first
    ps = (fig.get("panels") or []) if fig.get("type") == "panels" else []  # the panels of a composite
    if len(ps) > 1:  # the notes of some panels first: one panel, then two, and so on, the later panels before the earlier
        for size in range(1, len(ps)):  # how many panels lose their notes, fewer first
            # Every set of that size, the sets of later panels first (the first panel is usually the slide's main view)
            for ks in sorted(itertools.combinations(range(len(ps)), size), key=lambda c: [-k for k in reversed(c)]):
                which = " and ".join(str(k + 1) for k in ks)  # the panels named in the note, in order
                forms.append((f"notes dropped in panel{'s' if size > 1 else ''} {which}", {**fig, "panels": [no_notes(x) if i in ks else x for i, x in enumerate(ps)]}))
    forms.append(("notes dropped", no_notes(fig)))  # then every note at once
    if ps:  # a composite can also lose panels
        light = no_notes(fig)  # the form without notes
        for k in range(len(ps) - 1, 1, -1):  # fewer panels, down to two: with their notes first, then without
            forms.append((f"panels after {k} left out", {**fig, "panels": ps[:k]}))  # the first k panels kept as proposed
            forms.append((f"notes dropped, panels after {k} left out", {**light, "panels": light["panels"][:k]}))  # the first k panels without notes
        if isinstance(ps[0].get("figure"), dict):  # last, the first panel's figure alone, with the frame to itself
            for label, src in (("only the first panel kept", fig), ("notes dropped, only the first panel kept", light)):   # with its notes, then without
                first = src["panels"][0]  # the first panel of that form
                # Its figure alone, with the composite's caption and the panel's mark
                forms.append((label, {**first["figure"], "caption": src.get("caption"), "mark": first.get("mark")}))
    return forms  # tried in this order


def recheck(doc: dict, style: dict, prof: dict | None = None) -> dict:
    """Run every check on every proposal (after propose, and again before apply with the profile's evidence). A proposal that does
    not fit its slot gets its lighter forms tried in turn (lighter()), and the first one that passes every check stands in for it,
    with the change recorded in 'fitted' and the model's own version kept in 'proposed'"""
    langs = doc["langs"]  # the languages the proposals were made in
    index = {p.get("id") or w: (ch, p) for w, ch, p in deck_projects(prof)} if prof else {}  # projects by id (or path), to find their evidence
    # Each project's evidence: kept from propose, else from the profile, else none
    evs = {e["id"]: e.get("_evidence") or (evidence_of(prof, *index[e["id"]]) if e["id"] in index else "") for e in doc["projects"]}
    figs = [(e, f) for e in doc["projects"] for f in e["figures"]]  # every proposal with its project
    for _e, f in figs:  # start from the model's version each time (apply checks again on its own profile)
        if f.get("proposed"):  # a lighter form stood in last time
            f["figure"] = f.pop("proposed")  # back to the model's version
        f.pop("fitted", None)  # the old fit note goes with it

    rooms = side_rooms(prof) if prof else {}  # the side room of each page, as the deck computes it

    def room_of(f, e_id):  # the side room of the proposal's page, None when the deck did not say
        r = rooms.get(e_id) or []  # the project's rooms per page
        return r[f["page"]] if f["page"] < len(r) else None  # None when the page has no estimate

    def slot_of(f, e_id):  # the size to draw at: a side figure at its page's room (within the deck's 110 to 300), else the slot's size
        room = room_of(f, e_id)  # the page's side room
        return (SLOTS["side"][0], max(110, min(300, room))) if f["slot"] == "side" and room else f["slot"]  # an explicit size, or the slot's name

    def run(cands):  # check a list of (proposal, figure) in one drawing pass; returns the reviews
        ids = [owner[id(f)] for f, _ in cands]  # each candidate's project id
        items = [(fig, slot_of(f, e_id), lang) for (f, fig), e_id in zip(cands, ids) for lang in langs]  # one drawing per candidate and language
        drawn = check_drawing(items) if items else []  # one node run for all of them
        # Each candidate's checks, with its slice of the drawings
        return [review_one(fig, f["slot"], evs[e_id], langs, style, drawn[i * len(langs):(i + 1) * len(langs)], room_of(f, e_id))
                for i, ((f, fig), e_id) in enumerate(zip(cands, ids))]  # i picks the candidate's drawings

    owner = {id(f): e["id"] for e, f in figs}  # proposal (by identity) -> project id
    for (_e, f), r in zip(figs, run([(f, f["figure"]) for _e, f in figs])):  # the first pass: every proposal as it stands
        f.update(r)  # its checks and status
    # Lighter forms, one round per step, for the proposals whose only trouble is the layout
    rounds = {id(f): lighter(f["figure"]) for _e, f in figs
              # Flagged for the layout alone: shape, facts and style all clean
              if f["status"] != "ok" and isinstance(f["figure"], dict) and not f["checks"]["shape"] and not f["checks"]["facts"] and not f["checks"]["style"]}
    # (a side figure with no room on its page stays flagged: no lighter form makes room)
    step = 0
    while rounds:  # until every candidate fits or runs out of forms
        cands = [(f, rounds[id(f)][step][1]) for _e, f in figs if id(f) in rounds and step < len(rounds[id(f)])]  # each one's next lighter form
        if not cands:  # no forms left to try
            break  # the rest stay flagged
        for (f, fig), r in zip(cands, run(cands)):  # this round's forms, checked in one pass
            if r["status"] == "ok":  # this form fits: it stands in for the proposal
                f["proposed"], f["figure"], f["fitted"] = f["figure"], fig, rounds[id(f)][step][0]  # the model's version kept, what was dropped recorded
                f.update(r)  # the form's checks
                rounds.pop(id(f))  # done with this proposal
        step += 1  # the next lighter form
    return doc  # the same document, updated


def repair(doc: dict, prof: dict, *, ask=None, style=None, max_calls=1) -> dict:
    """One more call for the proposals that failed a check: each goes back with its findings, its slot's size and its project's
    evidence, and the answer goes through every check again. A repaired figure stands in for the proposal ('repaired' records it,
    'proposed' keeps the model's first version). A side figure with no room on its page is not sent: no data makes room"""
    # The repair call by default: its own task name, the same system prompt, one try
    ask = ask or (lambda prompt: llm.run("repair-figures", prompt, system=SYSTEM, want_json=True, required=("fixes",), timeout=900, retries=0))
    style = style if style is not None else style_pack()  # an empty pack given on purpose is kept
    index = {p.get("id") or w: (ch, p) for w, ch, p in deck_projects(prof)}  # projects by id, for their evidence
    rooms = side_rooms(prof)  # the side room of every page, for the sizes in the prompt
    todo = [(e, f) for e in doc["projects"] for f in e["figures"] if f["status"] != "ok" and e["id"] in index  # the flagged proposals of projects still in the profile
            and not any("no room for a side figure" in x for x in f["checks"]["shape"])]  # except a side figure with no room on its page
    if not todo or max_calls < 1:  # nothing to repair, or no call allowed
        return doc  # unchanged
    # What to fix and how, then one block per proposal
    lines = ["These figure proposals failed checks. Fix each one so that it passes, and return every one.",
             "- Facts: use only what the project's evidence says; drop a value, date or name the findings name.",
             "- Layout: make it lighter until it fits its size: fewer items, shorter labels (titles up to 3 words, notes up to 5), "
             "at most 3 panels in a main figure, at most 4 nodes in a zone, at most 4 steps in a side figure. A side figure is short: one row of "
             "steps whose titles are one or two short words, or a chart. Keep the type and the marks when you can.",
             "- A link crossing: change the order of the nodes in their zones so that the links run without crossing.",
             "- Keep the language pairs {\"ko\": ..., \"en\": ...} as they are.",
             'Return JSON: {"fixes": [{"n": "<proposal id>", "figure": {...}}]}', ""]
    for e, f in todo:  # one block per proposal
        # The page's side room, None when the deck gave none
        room = (rooms.get(e["id"]) or [None] * (f["page"] + 1))[f["page"]] if f["page"] < len(rooms.get(e["id"]) or [None] * (f["page"] + 1)) else None
        size = "760 x 570" if f["slot"] == "main" else f"470 x {int(max(110, min(300, room or 240)))}"  # the size the slot is drawn at, as the checks draw it
        c = f["checks"]  # its findings
        # The findings to send, capped so the prompt stays short
        # The height a figure needs comes first among the layout findings: it says how much lighter the figure must get
        found = c["shape"] + c["facts"][:6] + c["style"] + [f"{k}: {x}" for k, v in c["layout"].items() for x in sorted(v, key=lambda m: "needs" not in m)[:4]]
        # The proposal's id, slot, size, findings, figure and evidence
        lines += [f"### Proposal {f['n']} ({f['slot']} figure, drawn at {size})", "Findings: " + "; ".join(found)[:1500],
                  "Figure: " + json.dumps(f.get("proposed") or f["figure"], ensure_ascii=False),
                  "Evidence:\n<<<\n" + evidence_of(prof, *index[e["id"]])[:5000] + "\n>>>", ""]
    try:  # a missing backend or a bad answer leaves the proposals as they were
        ans = ask("\n".join(lines))  # the one repair call
        doc["calls"] = doc.get("calls", 0) + 1  # counted with the proposal calls
    except (llm.LLMUnavailable, ValueError) as err:  # no answer: the proposals stay as they were
        doc.setdefault("errors", []).append(f"repair: {err}")  # the note says why
        return doc  # nothing changed
    fixes = {str(x.get("n")): x.get("figure") for x in (ans.get("fixes") or []) if isinstance(x, dict)}  # fixes by proposal id
    for _e, f in todo:  # each proposal that was sent
        if isinstance(fixes.get(f["n"]), dict):  # only an answer that is a figure
            f["first"] = f.get("proposed") or f["figure"]   # the model's first version, kept for the review
            f.pop("proposed", None)  # first now holds the model's version
            f.pop("fitted", None)  # an old fit note no longer applies
            f["figure"], f["repaired"] = fixes[f["n"]], True  # the fix stands in, and the review says so
    return recheck(doc, style, prof)  # every proposal checked again (a repaired one may still need a lighter form)


def review(doc: dict, accept=None, reject=None) -> list:
    """Record decisions and return the review lines. Only proposals that passed every check can be accepted"""
    out = []  # one review line per proposal
    for e in doc["projects"]:  # every project
        for f in e["figures"]:  # every proposal
            if reject and (f["n"] in reject or "all" in reject):  # a rejection applies to any proposal
                f["decision"] = "rejected"  # recorded
            elif accept and (f["n"] in accept or "all" in accept):  # an acceptance is asked for
                f["decision"] = "accepted" if f["status"] == "ok" else f.get("decision")  # a flagged proposal stays undecided
            fig = f["figure"] if isinstance(f["figure"], dict) else {}  # a figure that is not an object still gets a line
            cap = pick(fig.get("caption"), doc["langs"][0]) or ""  # the caption in the first language
            why = "; ".join(f["checks"]["shape"] + f["checks"]["facts"][:3] + f["checks"]["style"] +  # the reasons, a few of each kind
                            [f"{k}: {x}" for k, v in f["checks"]["layout"].items() for x in v[:2]])  # two layout findings per language
            # A fixed-width line: id, slot, type, status, decision
            out.append(f"{f['n']:<28} {f['slot']:<4} {fig.get('type', '?'):<12} {f['status']:<8} {f.get('decision') or '-':<9} "
                       f"{re.sub(r'[*=]', '', str(cap))[:40]}" + (f"  ({f['fitted']})" if f.get("fitted") else "") + (f"  <- {why}" if why else ""))  # then the caption, the fit note and the reasons
    return out  # the review lines, in proposal order


def marks_in(v) -> set:
    """The figure-to-card numbers a figure shows (marks on panels, zones, nodes, steps or sides)"""
    if isinstance(v, dict):  # an object may carry a mark
        own = {v["mark"]} if isinstance(v.get("mark"), int) and not isinstance(v.get("mark"), bool) else set()  # an integer mark (True is not a number here)
        return own.union(*[marks_in(x) for x in v.values()]) if v else own  # plus the marks inside it
    if isinstance(v, list):  # lists item by item
        return set().union(*[marks_in(x) for x in v]) if v else set()  # every item's marks
    return set()  # plain values carry none


def number_cards(page: dict, marks: set) -> None:
    """Give card n the number n when a figure on its page shows the badge n (cards keep a number they already have). Cards may be a
    list of [head, text] or a language pair of such lists; both halves get the same numbers"""
    def mark_list(cards):  # numbers one list of cards
        if not isinstance(cards, list):  # not a list
            return cards  # left as it is
        out = []  # the numbered cards
        for i, c in enumerate(cards):  # card i + 1
            if isinstance(c, list) and len(c) == 2 and (i + 1) in marks:  # [head, text] -> [head, text, n]
                c = [*c, i + 1]  # the number as the third element
            elif isinstance(c, dict) and "mark" not in c and (i + 1) in marks:  # an object card without a number
                c = {**c, "mark": i + 1}  # gets mark
            out.append(c)  # numbered or not, in order
        return out  # the same cards, some numbered
    cards = page.get("cards")  # the page's cards
    if isinstance(cards, dict) and set(cards) <= {"ko", "en"}:  # a language pair
        page["cards"] = {k: mark_list(v) for k, v in cards.items()}  # both halves get the same numbers
    elif cards:  # a plain list
        page["cards"] = mark_list(cards)  # numbered in place of the old list


def apply(doc: dict, prof: dict, style: dict | None = None) -> tuple:
    """The profile with the accepted figures added (main first, then side), after the checks ran again on this profile's evidence.
    Returns (new profile, number added, notes)"""
    new = copy.deepcopy(prof)  # the input profile is never changed
    recheck(doc, style if style is not None else style_pack(), new)  # the checks again, with this profile's evidence and rooms
    index = {p.get("id") or w: p for w, _, p in deck_projects(new)}  # the copy's projects by id
    added, notes = 0, []  # the count and the notes for the command line
    for e in doc["projects"]:  # every project in the proposals
        p = index.get(e["id"])  # the same project in the copy, if it is still there
        for f in sorted(e["figures"], key=lambda x: (x["page"], x["slot"] != "main")):  # page by page, the main slot first
            if f.get("decision") != "accepted":  # only accepted figures
                continue  # are applied
            if f["status"] != "ok" or p is None:  # a check failed on this profile: never applied
                notes.append(f"{f['n']}: not applied ({'project not found' if p is None else 'a check failed'})")  # the note says which reason
                continue  # the next proposal
            page = (p.get("pages") or [p])[f["page"]]  # the page the figure belongs to
            fig = {k: v for k, v in f["figure"].items() if not k.startswith("_")}  # private keys (such as _w, _h, _lang) stay out of the profile
            if f["slot"] == "main" and page.get("figure"):  # the page kept its main figure: a second one would crowd the slide
                notes.append(f"{f['n']}: not applied (the page has its main figure)")  # said, never dropped silently
                continue  # the next proposal
            if f.get("replaces"):  # a chart takes the place of a drawn sequence of steps
                page["figures"] = [x for x in page.get("figures") or [] if not (isinstance(x, dict) and x.get("type") in ("pipeline", "phases"))]  # the sequence goes
            number_cards(page, marks_in(fig))  # the cards show the badges their figure parts show
            if not page.get("figure"):  # the main slot first
                page["figure"] = fig  # the main figure
            else:
                page.setdefault("figures", []).append(fig)  # a further figure
            added += 1  # counted for the summary
    return new, added, notes  # the new profile, how many were added, and why others were not


# ---------------------------------------------------------------- command line

def main(argv=None) -> int:  # the command line; argv lets tests call it
    a = list(sys.argv[1:] if argv is None else argv)  # the arguments as a list
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else d  # noqa: E731  a flag's value
    if a and a[0] == "repair" and len(a) > 2:  # repair <proposals.json> <profile.json>: one more call for the flagged proposals
        f = pathlib.Path(a[1])  # the proposals file
        doc = json.loads(f.read_text(encoding="utf-8"))  # read
        before = sum(1 for e in doc["projects"] for x in e["figures"] if x["status"] == "ok")  # passing proposals before the repair
        repair(doc, json.loads(pathlib.Path(a[2]).read_text(encoding="utf-8")), style=style_pack(opt("--style", "default")))  # the call, with the profile's evidence
        f.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # written back to the same proposals file
        after = sum(1 for e in doc["projects"] for x in e["figures"] if x["status"] == "ok")  # passing proposals after it
        # The gain, the total and the calls spent
        print(f"repair: {after - before} more proposal(s) pass every check ({after} in all), {doc.get('calls', 0)} call(s) so far")
        return 0  # done
    if not a or a[0] not in ("propose", "review", "apply"):  # an unknown command
        print(__doc__)  # prints the usage
        return 1  # and fails
    if a[0] == "propose" and len(a) > 1:  # propose <profile.json>
        src = pathlib.Path(a[1])  # the profile
        prof = json.loads(src.read_text(encoding="utf-8"))  # read
        stand = json.loads(pathlib.Path(opt("--stand-in")).read_text(encoding="utf-8")) if opt("--stand-in") else None  # canned answers for tests
        answers = iter(stand or [])  # handed out one per call
        doc = propose(prof, only=set(opt("--only").split(",")) if opt("--only") else None,  # --only ids
                      langs=opt("--langs").split(",") if opt("--langs") else None, max_calls=int(opt("--max-calls", 8)),  # --langs and the call budget
                      per_call=int(opt("--per-call")) if opt("--per-call") else None,  # projects per call
                      # The stand-in answers in order (an empty answer when they run out), and the style pack
                      ask=(lambda _p: next(answers, {"projects": []})) if stand is not None else None, style=style_pack(opt("--style", "default")))
        dst = pathlib.Path(opt("--out") or src.with_name(src.stem + ".figures.json"))  # next to the profile unless --out
        dst.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # the proposals file
        n = sum(len(e["figures"]) for e in doc["projects"])  # proposals made
        okn = sum(1 for e in doc["projects"] for f in e["figures"] if f["status"] == "ok")  # proposals that passed
        # Calls, proposals, projects, passed and flagged on one line
        print(f"figures: {doc['calls']} call(s), {n} proposal(s) for {len(doc['projects'])} project(s), {okn} passed every check, "
              f"{n - okn} flagged -> {dst}")  # and where the file went
        for err in doc["errors"][:5]:  # the first notes
            print("  note: " + err)  # indented under the summary
        return 0 if not doc["errors"] or n else 2  # 2: notes and nothing proposed
    if a[0] == "review" and len(a) > 1:  # review <proposals.json>
        f = pathlib.Path(a[1])  # the proposals file
        doc = json.loads(f.read_text(encoding="utf-8"))  # read
        # Decisions from --accept and --reject, both optional
        lines = review(doc, set(opt("--accept").split(",")) if opt("--accept") else None, set(opt("--reject").split(",")) if opt("--reject") else None)
        print("\n".join(lines))  # the review list
        if opt("--accept") or opt("--reject"):  # decisions were given
            f.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # recorded in the file
        acc = sum(1 for e in doc["projects"] for x in e["figures"] if x.get("decision") == "accepted")  # accepted so far
        print(f"review: {len(lines)} proposal(s), {acc} accepted")  # the summary line
        return 0  # done
    if a[0] == "apply" and len(a) > 2:  # apply <proposals.json> <profile.json>
        doc = json.loads(pathlib.Path(a[1]).read_text(encoding="utf-8"))  # the proposals
        src = pathlib.Path(a[2])  # the profile
        new, added, notes = apply(doc, json.loads(src.read_text(encoding="utf-8")))  # the checks run again inside apply
        dst = pathlib.Path(opt("--out") or src.with_name(src.stem + ".figs.json"))  # a new file next to the profile unless --out
        if dst.resolve() == src.resolve():  # the input profile is never overwritten
            print("apply: --out must name a new file")  # says what to change
            return 1  # and fails
        dst.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # the new profile
        for n in notes:  # figures that were not applied
            print("  note: " + n)  # with the reason
        print(f"apply: {added} figure(s) added -> {dst}")  # the summary line
        return 0  # done
    print(__doc__)  # a command without its files
    return 1  # fails with the usage


if __name__ == "__main__":  # run as a command
    sys.exit(main())  # main's return value is the exit code
