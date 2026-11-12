"""The interview deck: one printable deck per application, on 16:9 pages, made from the kit's question map and its scripts.

The cover names the company and the role. Next comes the posting, line by line, with the script that answers each line and
how well it answers it, so the whole interview shows on one page. Then the likeliest questions in the order an interview
runs (the opening minutes, the introduction and the questions about you, why this company, the posting's lines, the resume,
the portfolio, the expected situations, the technical questions, and the questions you ask at the end), one script each:
  - the question as the interviewer asks it, with the script's own title and id;
  - the dialogue first: the interviewer's lines small and grey, mine at full size, with the cue cards' speech marks
    (' / ' a breath, ' // ' a new line, **stress** in bold, the ==key phrase== on the highlighter, Korean stage notes in grey);
  - the translation after the dialogue as one note, never line by line between the spoken lines;
  - the notes written under the script (the key line, what to say if they dig further);
  - the other questions the same script answers: a script prints once.
A kit whose scripts are in English ends with the lines that ask again and buy time.

The search view serves it at /deck (?kinds=posting,resume  ?ids=A1,B2  ?n=6  ?lang=ko), and the browser's print dialog
saves it as a PDF. `deck --pdf` writes the same page to deck.pdf with Playwright's Chromium.
"""
import datetime  # the day it was made
import html  # escaping
import json  # the map and the job's record
from pathlib import Path  # a script's file name
import re  # marks in the notes

from interview import check, corpus, i18n  # scenes, items, strings
from interview import plan as ivplan  # the question map when none was written
from interview.cue import PRINT_KEY, PRINT_SCRIPT, _unref, line_html  # the cue cards' cross-reference filter, speech and print key marks

ORDER = ("opening", "asked", "behavioral", "company", "posting", "resume", "portfolio", "scenario", "technical", "closing")  # as an interview runs, what an earlier round asked right after the greeting
PER_KIND = {"opening": 2, "asked": 10, "behavioral": 6, "company": 2, "posting": 8, "resume": 5, "portfolio": 4,  # scripts per part by default:
            "scenario": 5, "technical": 5, "closing": 1}  # the likeliest of each, so the deck stays one sitting's reading
CLOSING = "your questions"  # the behavioral topic asked at the end, which closes the deck
NOTE_HEAD = re.compile(r"^(?:-\s+)?\*\*([^*]{1,12})\*\*\s*[:：]?\s*")  # a note line's own label, such as **핵심** or **주의**
# The lines that ask again and buy time in an English interview, in order with the page strings' deck_stall_uses
STALL = ["Sorry, / ==could you say that **again**==, / a bit more **slowly**?",
         "Sorry, / the audio **cut out** for a second. / Could you repeat the **last part**?",
         "==Just to make sure I **understood**==, / you're asking how I would **handle** ..., / **right**?",
         "**Good** question. // ==Let me take a **second** / to organize my thoughts==.",
         "==Let me put it **simply**==. // In **other** words, / ...",
         "I'm not sure of the **exact** word, / but it's the part that ...",
         "Honestly, / I haven't used that **directly**. // ==The **closest** thing I've done is== ...",
         "So, / that's the **short** version. // ==Would you like more **detail** / on any part==?"]


def rows_of(job):
    """The question map's entries: the one the tailor step wrote beside the drafts, else made now (no model)."""
    p = job.out_path() / "plan.json"  # where the panel and the plan command write it
    try:  # a file being written can be half there
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}  # the written map
    except (OSError, ValueError):  # unreadable: made again below
        data = {}
    rows = data.get("questions")  # as written
    return ivplan.with_asked(job, rows) if rows else ivplan.build(job)  # the rounds' questions read now; made without a model when none was written


def kind_of(row):
    """A row's part of the deck: the behavioral question asked at the end closes it."""
    if row.get("kind") == "behavioral" and (row.get("section") or "") == CLOSING:  # "Do you have any questions for us?"
        return "closing"  # printed last
    return row.get("kind") or ""  # the map's own kind


def scenes_of(job):
    """{id: (item, [(speaker, line, translation)], notes)} for every item with a dialogue, the agent's drafts among them."""
    items, _ = corpus.load(job)  # every item of the kit
    hidden = [re.escape(x) for x in job.kit.get("hidden_labels") or []]  # notes for the writer (근거: the question a draft was written for)
    secret = re.compile(r"^\s*(?:-\s*)?\*\*(?:" + "|".join(hidden) + r")\*\*") if hidden else None
    cache, out = {}, {}  # file -> its blocks; id -> scene
    for it in items:  # in file order
        if it["path"] not in cache:  # each file is split once
            cache[it["path"]] = check.blocks(it["path"])  # its headings and bodies
        dialogue, notes = check.scene_of(it, cache[it["path"]])  # the spoken lines and the rest
        pairs = []  # (speaker, line, translation)
        for who, txt, _ in dialogue:  # in order
            if who == "해석" and pairs and not pairs[-1][2]:  # the translation of the line above
                pairs[-1] = (pairs[-1][0], pairs[-1][1], txt)  # kept with it
            elif who in ("면접관", "나"):  # a spoken line
                pairs.append((who, txt, ""))  # its translation may follow
        if secret:  # never on the page, as the search view leaves them out
            notes = [ln for ln in notes if not secret.match(ln)]
        if pairs:  # only items with a dialogue are scripts
            out[it["id"]] = (it, pairs, notes)  # by id, as the map names them
    return out


ROLE_ORDER = {"scenes": 0, "deep": 1, "terms": 2, "reference": 3}  # the question scripts first, a resume's deep dive next


WORD = re.compile(r"[0-9A-Za-z가-힣]{2,}")  # a word of a question or a title


def words(text):
    """The words of a text, lower case, for comparing a question with a script's title."""
    return {w.lower() for w in WORD.findall(text or "")}


def line_coverage(row, scenes, sid):
    """How well a posting line is answered, as the deck says it: the map's rating, except that a term's entry, a note or a story
    explains a word and never answers a line in full ("Open-source contributions" was shown as answered by "What is Kubernetes")."""
    cov = row.get("coverage") or "none"  # the map's rating
    if cov == "strong" and sid and scenes[sid][0].get("role") not in ("scenes", "deep"):  # the script shown is not a question's script
        return "weak"  # in part
    return cov


def best(row, scenes):
    """The script that answers a question: among those the map found, a question script before a deep dive or a note; then
    the one whose title shares the most words with the question ("1분 자기소개" for "자기소개 부탁드립니다"); then the map's
    own order (how much of the question it covers)."""
    found = [str(x[0]) for x in row.get("covered_by") or [] if str(x[0]) in scenes]  # the map's order
    asked = words(" ".join([row.get("text") or ""] + [a for v in (row.get("ask") or {}).values() for a in v]))  # the question in both languages
    def key(sid):  # lower is better
        it = scenes[sid][0]  # the script
        shared = len(asked & words((it.get("ten") or "") + " " + (it.get("tko") or "")))  # its title's words in the question
        return (ROLE_ORDER.get(it.get("role"), 4), -shared, found.index(sid))
    return min(found, key=key, default=None)  # the role, the title, then the map's order


CLOSING_TITLE = re.compile(r"역질문|questions for", re.I)  # the scene that holds your own questions at the end


def closing_scene(scenes):
    """The script whose title says it holds the questions you ask at the end, a question script first."""
    found = [sid for sid, (it, _, _) in scenes.items() if CLOSING_TITLE.search((it.get("tko") or "") + " " + (it.get("ten") or ""))]
    return min(found, key=lambda sid: ROLE_ORDER.get(scenes[sid][0].get("role"), 4), default=None)  # in file order within a role


def pick(rows, scenes, kinds=None, ids=None, n=None):
    """[[part, [rows], scene id]] in the deck's order: each script once, with every question it answers."""
    chosen, seen = [], {}  # the pages; scene id -> its page
    for part in ORDER:  # as an interview runs
        if kinds and part not in kinds:  # a part left out on request
            continue
        cap, taken = (n or PER_KIND.get(part, 4)), 0  # how many scripts this part prints
        for r in rows:  # the map's order: the posting's lines in order, the standard questions in theirs
            if kind_of(r) != part:  # another part's question
                continue
            sid = (part == "closing" and closing_scene(scenes)) or best(r, scenes)  # the script that answers it
            if not sid or (ids is not None and sid not in ids):  # no script yet, or not one of those asked for
                continue
            if sid in seen:  # printed already: this question joins its page
                seen[sid][1].append(r)  # named under it
                continue
            if ids is None and taken >= cap:  # this part is full
                continue
            page = [part, [r], sid]  # a new page
            chosen.append(page)  # in order
            seen[sid] = page  # found again by the next question it answers
            taken += 1  # one more in this part
    return chosen


TIED_KINDS = ("opening", "asked", "behavioral", "company", "closing")  # the questions a file-order deck names under a script


def file_order(rows, scenes, files=None):
    """[[part, [rows], scene id]] for a kit written for one call: every question script once, in the file's own order,
    under its file's heading; the questions the map ties to a script follow its own first question."""
    tied = {}  # scene id -> the map's questions that lead to it
    for r in rows:  # every question of the map
        sid = (kind_of(r) == "closing" and closing_scene(scenes)) or best(r, scenes)  # the script that answers it
        score = dict((c[0], c[1]) for c in r.get("covered_by") or []).get(sid, 0)  # how well the map thinks it answers
        if sid and kind_of(r) in TIED_KINDS and score >= 0.75 and len(tied.get(sid, [])) < 4:  # a sure match among the common questions, a few
            tied.setdefault(sid, []).append(r)  # named under it
    chosen = []  # the pages
    for sid, (it, pairs, _) in scenes.items():  # in file order
        if it.get("role") != "scenes":  # deep dives, terms and references are looked up, not rehearsed
            continue
        if files and Path(str(it.get("path") or "")).name not in files:  # kit.json "deck": {"files": [...]}: only the call's own scripts
            continue
        first = next((en for who, en, _ in pairs if who == "면접관"), "")  # the script's own question
        own = {"text": re.sub(r"\*\*|==", "", first) or it.get("ten") or it.get("tko") or sid}  # as the writer put it
        part = re.sub(r"^[A-Z]{1,2}\.\s*", "", it.get("cat") or "")  # the file's heading, without its letter
        chosen.append([part, [own] + tied.get(sid, []), sid])  # the script and what else it answers
    return chosen


def is_english(scenes):
    """True when the scripts are spoken in English: their lines carry a translation."""
    return any(tr for _, pairs, _ in scenes.values() for _, _, tr in pairs)  # any translated line


def ask_of(row, lang):
    """The question as the interviewer asks it, in a language."""
    a = (row.get("ask") or {}).get(lang) or []  # the map's phrasings
    return (a[0] if a else "") or row.get("text") or ""  # the first, else the line itself


def note_html(line):
    """One note line: its label in bold, **stress** and ==marks== as on the cards, `code` in its own letters."""
    t = html.escape(line.strip(), quote=False)  # escaped first
    t = re.sub(r"^-\s+", "", t)  # a list mark is not part of the note
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)  # labels and stress
    t = re.sub(r"==(.+?)==", r'<mark class="hl">\1</mark>', t)  # a key phrase
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", t)  # commands and file names


CSS = """
@font-face { font-family: "Pretendard Variable"; src: url("{fonts}/PretendardVariable.woff2") format("woff2-variations"); font-weight: 45 920; }
:root { --ink: #1d1c1d; --ink-2: #3f3e3f; --off: #6e6e73; --rule: #d4d6db; --navy: #1b2e4b; --hl: rgba(242, 199, 68, .9); --well: #f3f4f6; }
* { box-sizing: border-box; }
html { background: #e9eaed; }
html.embedded { background: transparent; }   /* inside the Offerowl panel (?embed=1): its desk shows through and the pages stand on it, as its documents do */
html.embedded .bar { display: none; }   /* the panel names the deck and has the key that prints it */
body { margin: 0; padding: 16px; color: var(--ink); font: 400 10pt/1.55 "Pretendard Variable", Pretendard, "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
  word-break: keep-all; overflow-wrap: break-word; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.bar { display: flex; align-items: center; gap: 12px; max-width: 297mm; margin: 0 auto 12px; font-size: 10pt; color: var(--ink-2); }
.bar h1 { margin: 0; font-size: 13pt; font-weight: 750; }
.bar .n { color: var(--off); }
.bar button { margin-left: auto; height: 32px; padding: 0 14px; border: 1px solid rgba(0, 0, 0, .14); border-radius: 5px; cursor: pointer;
  background: linear-gradient(#fff, rgba(255, 255, 255, .6)); box-shadow: 1px 2px 3px rgba(0, 0, 0, .18), inset 0 1px 0 #fff; font: inherit; font-weight: 650; }
.pg { width: 297mm; min-height: 167mm; margin: 0 auto 8mm; padding: 9mm 11mm; background: #fff; box-shadow: 0 1px 3px rgba(0, 0, 0, .12); }
.pg + .pg { break-before: page; }
.flow { min-height: 0; }   /* the scripts, one after another: a page holds as many as fit, so no page ends half empty */
.scene { min-width: 0; }   /* a script runs on to the next page rather than leave this one half empty */
.scene header { break-after: avoid; break-inside: avoid; }   /* its question never stands alone at a page's foot */
.scene + .scene { margin-top: 6mm; }   /* space between scripts; a line here would hang at a page's top */
.cover { page: cover; display: grid; grid-template-rows: auto 1fr auto; padding: 0; }
.cover .band { padding: 16mm 14mm 11mm; background: var(--navy); color: #fff; }
.cover .band p { margin: 0 0 3mm; font-size: 11pt; font-weight: 600; opacity: .85; }
.cover .band h1 { margin: 0; font-size: 30pt; line-height: 1.15; font-weight: 800; }
.cover .band h2 { margin: 3mm 0 0; font-size: 14pt; font-weight: 600; }
.cover .what { padding: 10mm 14mm; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4mm 8mm; align-content: start; }
.cover .what div { border-top: 1.5px solid var(--rule); padding-top: 2.5mm; }
.cover .what b { display: block; font-size: 16pt; font-weight: 750; color: var(--navy); }
.cover .what span { font-size: 9pt; color: var(--off); }
.cover footer { padding: 0 14mm 9mm; font-size: 9pt; color: var(--off); }
h2.sec { display: flex; align-items: baseline; gap: 3mm; margin: 0 0 3mm; padding-bottom: 2mm; border-bottom: 1.5px solid var(--navy); font-size: 13pt; font-weight: 750; color: var(--navy); }
table.lines { width: 100%; border-collapse: collapse; font-size: 9pt; }
table.lines th { text-align: left; font-weight: 700; color: var(--off); padding: 1.2mm 2mm; border-bottom: 1px solid var(--rule); }
table.lines td { padding: 1.4mm 2mm; border-bottom: 1px solid var(--well); vertical-align: top; }
table.lines tr { break-inside: avoid; }
table.lines td.by { width: 34%; } table.lines td.lamp { width: 13%; white-space: nowrap; }
.lamp i { display: inline-block; width: 7px; height: 7px; margin-right: 5px; border-radius: 50%; vertical-align: 1px; box-shadow: inset 0 0 0 1.5px #9a9aa0; }
.lamp.strong i { background: #13966b; box-shadow: none; } .lamp.weak i { background: #ecb22e; box-shadow: none; } .lamp.draft i { background: #e2702a; box-shadow: none; }
.id { flex: none; padding: 0 4px; border-radius: 2px; font-size: 8.5pt; font-weight: 700; color: var(--navy); background: rgba(27, 46, 75, .09); }
.scene header { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 1mm 6mm; align-items: start; margin-bottom: 3mm; padding-bottom: 2.5mm; border-bottom: 1.5px solid var(--navy); }
.scene header .part { font-size: 9pt; font-weight: 700; color: var(--navy); }
.scene header h2 { margin: .5mm 0 0; font-size: 13pt; line-height: 1.35; font-weight: 750; }
.scene header .q-ko { margin: .5mm 0 0; font-size: 9pt; color: var(--off); }
.scene header .ref { display: flex; gap: 2mm; align-items: baseline; justify-content: end; max-width: 90mm; font-size: 9pt; color: var(--ink-2); text-align: right; }
.scene header .draft { font-size: 8.5pt; font-weight: 700; color: #b5541a; }
.cols { column-count: 2; column-gap: 9mm; column-fill: balance; }   /* both columns filled, the last lines shared out */
.talk p { margin: 0 0 2mm; }
.talk .iv { font-size: 9pt; color: var(--off); }
.talk .iv b, .note p b.who { font-weight: 700; margin-right: 1.5mm; }
.talk .me { font-size: 10pt; }
.talk b, .note b { font-weight: 750; }
mark.hl { color: inherit; padding: 0 .1em; background: linear-gradient(180deg, transparent 58%, var(--hl) 58%); font-weight: 750; }
.br { color: var(--off); font-weight: 400; }   /* ' / ' marks a breath: faint beside the words, yet readable when rehearsing (5.1:1 on the page) */
.dir { color: var(--off); font-style: italic; font-size: .92em; }
code { font: 500 .92em/1 "JetBrains Mono", Consolas, monospace; }
.note { margin: 1mm 0 3mm; padding: 2.5mm 3mm; background: var(--well); border-radius: 3px; font-size: 9pt; color: var(--ink-2); }
.note h3 { margin: 0 0 1.5mm; font-size: 9pt; font-weight: 750; color: var(--navy); break-after: avoid; }
.note p { margin: 0 0 1.4mm; } .note p:last-child { margin-bottom: 0; }
.note p.iv { color: var(--off); }
.note ul { margin: 0; padding-left: 4mm; } .note li { margin: 0 0 1mm; }
.note.memo, .note.also { break-inside: avoid; }   /* a short note is never cut between two columns; the translation may be */
.stall { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 3mm 9mm; }
.stall div { break-inside: avoid; border-top: 1px solid var(--rule); padding-top: 2mm; }
.stall p { margin: 0; } .stall div > span { display: block; margin-top: 1mm; font-size: 9pt; color: var(--off); }
.empty { max-width: 297mm; margin: 40px auto; color: var(--off); }
@page { size: 297mm 167.06mm; margin: 9mm 11mm; }
@page cover { margin: 0; }
@media print { html, body { background: #fff; padding: 0; } .bar { display: none; }
  .pg { width: auto; min-height: 0; margin: 0; padding: 0; box-shadow: none; }
  .cover { height: 167mm; } }
@media screen and (max-width: 1100px) { body { padding: 8px; } .pg { width: auto; min-height: 0; } .cols { column-count: 1; } .cover .what { grid-template-columns: 1fr 1fr; } }
"""


def scene_page(part, rows, item, pairs, notes, s, english, unref):
    """One script's page: the question, the dialogue, the translation as one note, the notes, the other questions."""
    lead = rows[0]  # the question that put the script in the deck
    ask = ask_of(lead, "en" if english else "ko")  # as the interviewer asks it
    sub = ask_of(lead, "ko") if english else ""  # its Korean under it in an English deck
    title = unref(item.get("tko") or item.get("ten") or "").replace("**", "").replace("==", "")  # the script's own title
    talk = []  # the spoken lines
    for who, en, _ in pairs:  # in order
        if who == "면접관":  # the interviewer: small and grey
            talk.append(f'<p class="iv"><b>{html.escape(s["labels"].get("면접관", "면접관"))}</b>{line_html(unref(en))}</p>')
        else:  # my line at full size
            talk.append(f'<p class="me">{line_html(unref(en))}</p>')
    tr = [(who, ko) for who, _, ko in pairs if ko]  # the translated lines
    trans = ""  # the translation as one note, after the dialogue
    if tr:  # an English script
        body = "".join(f'<p class="{"iv" if who == "면접관" else "me"}"><b class="who">{html.escape(s["labels"].get(who, who))}</b>'
                       f'{line_html(unref(ko))}</p>' for who, ko in tr)  # each line with who says it
        trans = f'<div class="note tr"><h3>{html.escape(s["deck_translation"])}</h3>{body}</div>'  # under the dialogue
    kept = [ln for ln in notes if ln.strip() and not ln.strip().startswith("#")]  # the notes written under the script
    memo = (f'<div class="note memo"><h3>{html.escape(s["deck_notes"])}</h3>'
            + "".join(f"<p>{note_html(unref(ln))}</p>" for ln in kept) + "</div>") if kept else ""  # what to say if they dig further
    also = ""  # the other questions this script answers
    if len(rows) > 1:  # it answers more than the one that put it here
        lis = "".join(f"<li>{html.escape(ask_of(r, 'en' if english else 'ko'))}</li>" for r in rows[1:])  # each as it is asked
        also = f'<div class="note also"><h3>{html.escape(s["deck_also"])}</h3><ul>{lis}</ul></div>'  # named under it
    draft = f'<span class="draft">{html.escape(s["deck_draft"])}</span>' if item.get("draft") else ""  # an agent's draft says so
    return (f'<section class="scene" data-id="{html.escape(item["id"])}"><header><div>'
            f'<div class="part">{html.escape(s["deck_parts"].get(part, part))}</div><h2>{html.escape(ask)}</h2>'
            + (f'<p class="q-ko">{html.escape(sub)}</p>' if sub and sub != ask else "")
            + f'</div><div class="ref">{draft}<span>{html.escape(title)}</span><span class="id">{html.escape(item["id"])}</span></div></header>'
            f'<div class="cols"><div class="talk">{"".join(talk)}</div>{trans}{memo}{also}</div></section>')


def posting_page(rows, scenes, s, english, unref):
    """The posting line by line, with the script that answers each line and how well."""
    lines = [r for r in rows if kind_of(r) == "posting"]  # every posting line, in order
    if not lines:  # a job with no posting text
        return ""
    trs = []  # table rows
    for r in lines:  # one per line
        sid = best(r, scenes)  # its script
        cov = line_coverage(r, scenes, sid)  # how well a script answers it
        by = (f'<span class="id">{html.escape(sid)}</span> {html.escape(unref(scenes[sid][0].get("tko") or scenes[sid][0].get("ten") or ""))}'
              if sid else html.escape(s["deck_none"]))  # the script, or that there is none yet
        trs.append(f'<tr><td>{html.escape(r.get("text") or "")}</td><td class="by">{by}</td>'
                   f'<td class="lamp {html.escape(cov)}"><i></i>{html.escape(s["deck_cov"].get(cov, cov))}</td></tr>')
    head = "".join(f"<th>{html.escape(x)}</th>" for x in s["deck_posting_cols"])  # the column heads
    return (f'<section class="pg"><h2 class="sec">{html.escape(s["deck_posting_title"])}</h2>'
            f'<table class="lines"><thead><tr>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table></section>')


def cover_page(job, pages, rows, s, company, role):
    """The cover: the company and the role on the documents' navy band, then what the deck holds."""
    parts = {}  # part -> scripts printed
    for part, _, _ in pages:  # each page
        parts[part] = parts.get(part, 0) + 1  # counted
    asked = sum(len(p[1]) for p in pages)  # the questions the printed scripts answer
    cells = [f'<div><b>{len(pages)}</b><span>{html.escape(s["deck_scripts"])}</span></div>',  # how many scripts
             f'<div><b>{asked}</b><span>{html.escape(s["deck_questions"])}</span></div>']  # and questions
    cells += [f'<div><b>{n}</b><span>{html.escape(s["deck_parts"].get(p, p))}</span></div>' for p, n in parts.items()]  # per part
    made = datetime.date.today().isoformat()  # the day it was made
    return (f'<section class="pg cover"><div class="band"><p>{html.escape(s["deck_title"])}</p><h1>{html.escape(company)}</h1>'
            + (f"<h2>{html.escape(role)}</h2>" if role else "")
            + f'</div><div class="what">{"".join(cells)}</div><footer>{html.escape(s["deck_made"].format(date=made))}</footer></section>')


def stall_page(s):
    """The lines that ask again and buy time, for an English interview."""
    cells = "".join(f'<div><p>{line_html(en)}</p><span>{html.escape(use)}</span></div>' for en, use in zip(STALL, s["deck_stall_uses"]))  # each with its use
    return f'<section class="pg"><h2 class="sec">{html.escape(s["deck_stall_title"])}</h2><div class="stall">{cells}</div></section>'


def record(job):
    """The application's own record (company, role) from the job folder, when the panel keeps one there."""
    try:  # the panel's status file; a bare kit has none
        st = json.loads((job.dir / "status.json").read_text(encoding="utf-8"))  # its record
    except (OSError, ValueError):  # no record
        st = {}
    return st if isinstance(st, dict) else {}


def asked_first(pages, rows, scenes, n=None):
    """A deck in the file's order with what the earlier rounds asked right after its first part (the greeting): each such
    question's script moves there from its place in the file, its page keeping the questions it had, so it prints once.
    A file holds the call's own scripts in order, and the drafts written for asked questions come last in it."""
    lead, moved = [], {}  # the asked part's pages; script id -> its page there
    old = {sid: rs for _, rs, sid in pages}  # each printed script's questions
    for r in rows:
        if kind_of(r) != "asked":
            continue
        by = [str(x[0]) for x in r.get("covered_by") or [] if str(x[0]) in scenes]  # the map's match: its own script by title first
        sid = by[0] if by else None
        if not sid:  # no script answers it yet
            continue
        if sid in moved:  # a script that answers two asked questions: one page
            moved[sid][1].insert(len([x for x in moved[sid][1] if kind_of(x) == "asked"]), r)
            continue
        if len(lead) >= (n or PER_KIND["asked"]):  # the part is full
            continue
        page = ["asked", [r] + [x for x in old.get(sid, []) if x is not r], sid]  # the asked question leads; what the script answered stays with it
        moved[sid] = page
        lead.append(page)
    if not lead:
        return pages
    rest = [pg for pg in pages if pg[2] not in moved]  # each script once
    first = rest[0][0] if rest else None  # the first part: the opening minutes in a kit for a call
    cut = next((i for i, pg in enumerate(rest) if pg[0] != first), len(rest))
    return rest[:cut] + lead + rest[cut:]


def select(job, kinds=None, ids=None, n=None):
    """What a deck holds, for the printed page and for the panel alike: (pages, scenes, rows, kinds asked for, ids asked for).
    pages is [[part, [rows], scene id]] in the deck's order; kinds and ids are None when not asked for."""
    scenes = scenes_of(job)  # every script
    rows = rows_of(job)  # the question map
    want_kinds = {k.strip() for k in kinds.split(",") if k.strip()} if kinds else None  # parts asked for
    want_ids = {i.strip() for i in ids.split(",") if i.strip()} if ids else None  # scripts asked for
    in_file_order = (job.kit.get("deck") or {}).get("order") == "file" and not want_kinds and not want_ids  # kit.json "deck": {"order": "file"}
    if in_file_order:  # the call's own scripts first, as written
        files = (job.kit.get("deck") or {}).get("files")  # only these files lead, when named
        pages = file_order(rows, scenes, files)  # in the file's order
        if files:  # the kit's other scripts follow as the map ranks them, as in a deck made from the map alone
            printed = {sid for _, _, sid in pages}  # already in
            pages += [pg for pg in pick(rows, scenes, None, None, n) if pg[2] not in printed]  # the posting, the resume, the technical questions
        pages = asked_first(pages, rows, scenes, n)  # what an earlier round asked, right after the greeting
    else:  # the map's likeliest questions, part by part
        pages = pick(rows, scenes, want_kinds, want_ids, n)  # what the deck prints
    return pages, scenes, rows, want_kinds, want_ids


def company_role(job):
    """(company, role) as the cover names them: the panel's record of the application, else the kit's own company name."""
    st = record(job)  # the application's record
    co = job.kit.get("company") or {}  # the kit's company name
    company = st.get("company") or (co.get("ko") or co.get("en") if isinstance(co, dict) else str(co)) or job.name  # how the cover names it
    return company, st.get("role") or ""


def data(job, kinds=None, ids=None, n=None, lang=None):
    """The deck as data, for the Offerowl panel, which draws it with its own parts: the same scripts in the same order as the
    printed page, each line as written (its speech marks are drawn by the panel), and the deck's words in the language asked."""
    s = i18n.page(lang)  # the deck's words
    unref = _unref(job.kit)  # the writer's cross-references are removed, as on the page
    pages, scenes, rows, want_kinds, want_ids = select(job, kinds, ids, n)  # what the page prints
    english = is_english(scenes)  # spoken in English: the question is asked in English, with its Korean under it
    company, role = company_role(job)  # as the cover names them
    plain = lambda x: unref(x or "").replace("**", "").replace("==", "")  # noqa: E731  a title without the writer's marks
    out = []  # the scripts, in the deck's order
    for part, rs, sid in pages:  # each script once
        item, pairs, notes = scenes[sid]  # its dialogue and the notes under it
        ask = ask_of(rs[0], "en" if english else "ko")  # the question that put it in the deck, as the interviewer asks it
        sub = ask_of(rs[0], "ko") if english else ""  # its Korean under it in an English deck
        out.append({"id": item["id"], "part": part, "ask": ask, "sub": sub if sub != ask else "", "title": plain(item.get("tko") or item.get("ten")),
                    "draft": bool(item.get("draft")),  # an agent's draft says so
                    "turns": [{"who": "interviewer" if who == "면접관" else "me", "en": unref(en), "ko": unref(ko)} for who, en, ko in pairs],  # spoken lines, each with its translation
                    "notes": [re.sub(r"^-\s+", "", unref(ln).strip()) for ln in notes if ln.strip() and not ln.strip().startswith("#")],  # what to say if they dig further
                    "also": [ask_of(r, "en" if english else "ko") for r in rs[1:]]})  # the other questions it answers
    posting = []  # the posting line by line, as the page's second page
    if pages and not want_ids and (not want_kinds or "posting" in want_kinds):  # the page prints it on the same terms
        for r in rows:  # in the map's order
            if kind_of(r) != "posting":  # another part's question
                continue
            sid = best(r, scenes)  # the script that answers the line
            posting.append({"text": r.get("text") or "", "script": sid or "", "title": plain(scenes[sid][0].get("tko") or scenes[sid][0].get("ten")) if sid else "",
                            "coverage": line_coverage(r, scenes, sid)})  # how well a script answers it
    parts = {}  # part -> scripts in it
    for part, _, _ in pages:  # in order
        parts[part] = parts.get(part, 0) + 1  # counted
    stall = [{"en": en, "use": use} for en, use in zip(STALL, s["deck_stall_uses"])] if pages and english and not want_ids else []  # the lines that buy time
    words = {k[len("deck_"):]: s[k] for k in ("deck_title", "deck_translation", "deck_notes", "deck_also", "deck_draft", "deck_none", "deck_posting_title",
                                             "deck_posting_cols", "deck_cov", "deck_parts", "deck_scripts", "deck_questions", "deck_stall_title", "deck_empty")}  # the deck's own words
    return {"company": company, "role": role, "english": english, "lang": s["lang"], "words": words,
            "counts": {"scripts": len(pages), "questions": sum(len(p[1]) for p in pages), "parts": [{"part": p, "n": k} for p, k in parts.items()]},
            "posting": posting, "scenes": out, "stall": stall}


def page(job, kinds=None, ids=None, n=None, lang=None, fonts="fonts", embedded=False):
    """The deck as one HTML page. embedded: shown inside the Offerowl panel, which names it and prints it itself."""
    s = i18n.page(lang)  # the page's language
    unref = _unref(job.kit)  # the writer's cross-references are removed, as on the search view
    pages, scenes, rows, want_kinds, want_ids = select(job, kinds, ids, n)  # what the deck prints
    english = is_english(scenes)  # spoken in English
    company, role = company_role(job)  # how the cover names them
    body = []  # the pages
    if pages:  # anything to print
        body.append(cover_page(job, pages, rows, s, company, role))  # the cover
        if not want_ids and (not want_kinds or "posting" in want_kinds):  # the whole interview on one page, unless only some scripts were asked for
            body.append(posting_page(rows, scenes, s, english, unref))  # the posting line by line
        flow = [scene_page(part, rs, *scenes[sid], s, english, unref) for part, rs, sid in pages]  # each script once
        body.append(f'<div class="pg flow">{"".join(flow)}</div>')  # one after another, as many to a page as fit
        if english and not want_ids:  # an English interview
            body.append(stall_page(s))  # the lines that buy time
    sheet = "".join(body) if body else f'<p class="empty">{html.escape(s["deck_empty"])}</p>'  # the deck, or why there is none
    count = s["deck_count"].format(n=len(pages))  # how many scripts it holds
    look = ' class="embedded"' if embedded else ""  # inside the panel: no bar of its own, the panel's desk behind the pages
    return (f'<!doctype html><html lang="{s["lang"]}"{look}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(s["deck_title"] + " " + company)}</title><style>{CSS.replace("{fonts}", fonts)}</style></head><body>'
            f'<div class="bar"><h1>{html.escape(s["deck_title"])}</h1><span class="n">{html.escape(count)}</span>'
            f'{PRINT_KEY.format(label=html.escape(s["deck_print"]))}</div>{sheet}{PRINT_SCRIPT}</body></html>')


def main(job, kinds=None, ids=None, n=None, out=None, pdf=False, lang=None):
    """Write deck.html (and deck.pdf with --pdf) to the output folder."""
    from pathlib import Path  # the fonts' folder for a file opened from disk
    fonts = (Path(__file__).resolve().parent / "fonts").as_uri()  # a written file has no server to ask for /fonts
    text = page(job, kinds, ids, n, lang, fonts)  # the page
    d = job.out_dir(out)  # the output folder
    f = d / "deck.html"  # the file a browser prints
    f.write_text(text, encoding="utf-8")  # written in one go
    pages = text.count('<section class="scene"')  # the scripts it holds
    print(i18n.t("deck_written", n=pages, out=f))  # where it went
    if pdf:  # printed with the browser engine
        from interview import browser  # Playwright, optional
        pw = browser.playwright_or_none()  # installed?
        if pw is None:  # no browser engine
            print(i18n.t("need_playwright"))  # how to get it
            return 2
        import asyncio  # Playwright's async API

        async def to_pdf():  # the page's own @page rules decide the paper
            async with pw() as p:  # the driver
                b = await p.chromium.launch()  # headless
                pg = await b.new_page()  # one page
                await pg.goto(f.as_uri(), wait_until="load")  # the written file
                await pg.pdf(path=str(d / "deck.pdf"), prefer_css_page_size=True, print_background=True)  # 16:9 from @page
                await b.close()  # done
        asyncio.run(to_pdf())  # run it
        print(i18n.t("deck_written", n=pages, out=d / "deck.pdf"))  # the PDF too
    return 0
