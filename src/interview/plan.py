"""The question map: every question the interview is likely to bring, from the job's own text files.

Deterministic extraction (no model):
  - the questions asked in the earlier rounds, as the person wrote them down after each one (the panel's rounds, kept in
    the job's status.json), first: the next round may ask them again or go deeper;
  - one entry per line of the posting (its list items, or its sentences when it has no lists);
  - "tell me about this line" for each line of the submitted resume;
  - follow-ups for each page of the submitted portfolio (pages split by form feeds, as pdftotext writes them, or by
    markdown headings);
  - every abbreviation in the person's own documents (resume, portfolio, profile) and every skill in the profile;
  - behavioral and company questions (questions.json), one more per heading of the company research files;
  - the opening logistics (greeting, sound check, camera, sharing the portfolio).
Every entry gets rule-made questions in English and Korean and the scenes that already cover it (cover.py).
The model is optional: --phrase asks it to phrase the questions naturally, one small call per kind, and --anticipate
asks it once for the scenario and technical questions that no line of a document shows; those are kept in
anticipated.json and join every later map. Writes plan.json and plan.md to the output folder.
"""
import glob  # research files
import hashlib  # an asked question's id, from its words
import json  # the map
import pathlib  # paths
import re  # line rules

from interview import corpus, cover, i18n  # items, coverage, messages
from interview import text as T  # lines, words, abbreviations
from interview.job import read_json, read_text  # files

HERE = pathlib.Path(__file__).resolve().parent  # src/interview
STD = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))  # standard questions and templates
KINDS = ("asked", "posting", "resume", "portfolio", "term", "behavioral", "company", "scenario", "technical", "opening")  # the kinds of the map, in its order
META = re.compile(r"^[\w ./-]{1,24}:\s")  # "Location: ..." style metadata lines of a posting
# Words that name a duty or requirement section, in English and Korean; a posting without lists is read only there
DUTY = re.compile(r"responsib|qualif|requir|prefer|what you|you will|you'll|duties|skills|about the role|자격|우대|업무|담당|요건|역할|필수", re.I)
# Mail, links and phone numbers: resume lines that hold contact details, not claims to ask about
CONTACT = re.compile(r"@|https?://|www\.|linkedin|github\.com|\+\d{2}\s?\d|\b\d{2,4}-\d{3,4}-\d{4}\b", re.I)


def posting_lines(text):
    """[(line number, section, line)] of a posting: its list items, or the sentences of its duty sections."""
    rows, section = [], ""  # results; the heading above the current line
    lines = T.doc_lines(text)  # content lines with marks stripped
    has_bullets = any(b for _, _, b, _ in lines)  # list items decide when there are any
    for n, s, is_bullet, is_head in lines:  # walk the posting in order, so each line knows its section
        if is_head or (not is_bullet and len(s.split()) <= 6 and (s.endswith(":") or s.isupper())):  # a section heading
            section = s.rstrip(":").strip()  # remembered as the section of the lines below it
            continue
        if META.match(s) and not is_bullet:  # Location:, Date Posted: and the like
            continue
        if has_bullets:  # the posting has lists, so only list items become questions
            if is_bullet and len(s.split()) >= 3:  # shorter items are labels, not duties
                rows.append((n, section, s))  # the item with its line number and section
        elif DUTY.search(section):  # no lists: the sentences under duty and requirement sections
            for sent in re.split(r"(?<=[.!?])\s+", s):  # one paragraph line can hold several sentences
                if len(sent.split()) >= 4:  # very short fragments do not make a question
                    rows.append((n, section, sent.strip()))  # one entry per sentence, all on the same line number
    return rows


def resume_lines(text):
    """[(line number, line)] of a resume: list items and full sentences, without contact lines and headings."""
    rows = []  # results
    for n, s, is_bullet, is_head in T.doc_lines(text):  # content lines of the resume, with their line numbers
        if is_head or CONTACT.search(s):  # headings and contact details are not claims
            continue
        s = re.sub(r"\s{3,}", "  ", s).strip()  # two-column PDF text keeps wide gaps
        if (is_bullet and len(s.split()) >= 3) or len(s.split()) >= 8:  # a list item, or a line long enough to be a sentence
            rows.append((n, s))  # a line the interviewer may ask about
    return rows


def portfolio_pages(text):
    """[(page number, title, text)]: pages split at form feeds, else at markdown headings of level one or two."""
    if "\f" in text:  # pdftotext output
        chunks = text.split("\f")  # one chunk per PDF page
    else:  # a markdown or plain export
        chunks = re.split(r"(?m)^(?=#{1,2} )", text)  # one chunk per top heading, the heading kept at its start
    pages = []  # results
    for k, c in enumerate(chunks, 1):  # pages counted from one, as a reader counts them
        body = [s for _, s, _, _ in T.doc_lines(c)]  # content lines
        if len(" ".join(body).split()) < 12:  # a cover, a divider or an empty page
            continue
        physical = [re.sub(r"^#+\s*", "", x).strip() for x in c.splitlines() if x.strip()]  # the page's own lines
        # its first line that reads as words: a running head in capitals with its page count and spaced-out dates is not a title
        title = next((x for x in physical if len(x.split()) >= 2 and re.search(r"[a-z가-힣]{2}", x)), None) or next((x for x in physical if len(x.split()) >= 2), physical[0])
        pages.append((k, re.sub(r"\s{2,}", " ", title)[:120], "\n".join(body)))  # the title squeezed and capped for tables
    return pages


def own_terms(job, resume, portfolio):
    """[(term, count)] of abbreviations in the documents the interviewer has (the submitted resume and portfolio) and the
    profile's skills, in order of first use. The rest of the profile is evidence, not something the interviewer reads."""
    prof = read_json(job.profile_path, {}) if job.profile_path else {}  # the confirmed facts
    texts = [resume or "", portfolio or ""]  # what was sent
    seen = dict(T.abbreviations("\n".join(texts)))  # term -> count, first use first (one text, so the capitals rule sees every document)
    for s in (prof or {}).get("skills") or []:  # every listed skill is a term the interviewer may ask about
        for item in (s.get("items") if isinstance(s, dict) else []) or []:  # a skill group lists its items; other shapes are skipped
            name = str(item).strip()  # the skill as the profile writes it
            if name and name not in seen and 1 <= len(name.split()) <= 3:  # new and short; long phrases are not terms
                seen[name] = 1  # counted once, after the abbreviations
    initials = name_initials(prof)  # the person's own initials, printed on a deck's every page, are not a term
    lower = {}  # one entry per spelling, ignoring case (K8S and K8s)
    for a, k in seen.items():  # merge spellings that differ only in case
        if a in initials:  # nobody asks what your initials stand for
            continue
        lower.setdefault(a.lower(), (a, 0))  # the first spelling seen is the one shown
        lower[a.lower()] = (lower[a.lower()][0], lower[a.lower()][1] + k)  # add this spelling's count to it
    return list(lower.values())  # (term, count) pairs in order of first use


def name_initials(prof):
    """The initials of the person's name, from the Latin part of the name in the profile: {"GDH"} for Gil-Dong Hong."""
    person = (prof or {}).get("person") if isinstance((prof or {}).get("person"), dict) else {}  # the person's block
    english = person.get("en") if isinstance(person.get("en"), dict) else {}  # some profiles keep the English name apart
    out = set()  # initials
    for name in (person.get("name"), person.get("name_en"), english.get("name")):  # every place a name may be
        words = re.findall(r"[A-Za-z]+", str(name or ""))  # its Latin words ("Jin", "Gu", "Kang")
        if len(words) >= 2:  # a name of two words or more
            out.add("".join(w[0].upper() for w in words))  # "GDH"
    return out


def research_headings(job):
    """[(file, line, heading)] of the company research files (kit "research", default research/*.md)."""
    out = []  # results
    for pat in job.kit.get("research") or ["research/*.md"]:  # the kit's file patterns, or the default folder
        for f in sorted(glob.glob(str(job.dir / pat))):  # sorted, so the ids stay the same from run to run
            # every line with its number, for the source column of the map
            for n, ln in enumerate(pathlib.Path(f).read_text(encoding="utf-8").splitlines(), 1):
                m = re.match(r"^#{2,3}\s+(.+)$", ln)  # second and third level headings name the topics
                if m:  # a heading line
                    # the file name, the line, and the heading without its "1." numbering
                    out.append((pathlib.Path(f).name, n, re.sub(r"^\d+\.\s*", "", m.group(1)).strip()))
    return out


LIST_MARK = re.compile(r"^\s*(?:(?:[-*\u2022\u00b7]|\d{1,2}[.)]|Q\d{0,2}[.):])\s*)+", re.I)  # "- ", "1. ", "Q3: " (or "- Q3: ") in front of a question written down


def asked_lines(job):
    """[{id, text, source, rounds}] from the job's interview rounds (status.json beside the kit, as the panel keeps it): each
    round in the order it happened, one question a line, list marks dropped. A question asked again is one entry, its source
    the first round ("YYYY-MM-DD kind") and its rounds every round that asked it. The id comes from the question's words
    (a1b2c3), so a draft written for it stays its draft when lines are added above it or a later round asks it again."""
    st = read_json(job.dir / "status.json", {}) or {}  # the panel's record of the job; a kit outside the panel has none
    out, by = [], {}  # the questions in the order first asked; their words, folded -> the entry
    for r in sorted((r for r in st.get("rounds") or [] if isinstance(r, dict)), key=lambda r: str(r.get("at") or "")):  # in the order they happened
        label = f'{str(r.get("at") or "")[:10]} {r.get("kind") or ""}'.strip()  # its day and kind, as the source column says it
        for line in str(r.get("asked") or "").splitlines():  # one question a line
            q = LIST_MARK.sub("", line).strip()  # the words without a list mark
            key = re.sub(r"\W+", " ", q).strip().lower()  # the same question with other spacing or marks is one question
            if len(key) < 3:  # a stray mark, not a question
                continue
            if key not in by:  # first asked here
                by[key] = {"id": "a" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:6], "text": q, "source": label, "rounds": []}
                out.append(by[key])
            if str(r.get("id") or "") not in by[key]["rounds"]:  # this round asked it too
                by[key]["rounds"].append(str(r.get("id") or ""))
    return out


def asked_rows(job, cov, lines=None):
    """The map's entries for what the earlier rounds asked (asked_lines, or the lines given), rated against the scenes as
    they are now (cover.Coverage)."""
    rows = []  # in the order they were first asked
    for a in asked_lines(job) if lines is None else lines:
        rating, by, _ = cov.rate(a["text"])  # does a scene already answer it?
        rows.append({"id": a["id"], "kind": "asked", "source": a["source"], "section": "", "text": a["text"], "ask": {"en": [a["text"]], "ko": [a["text"]]},  # in the words written down, either language
                     "coverage": rating, "covered_by": [[i, s] for i, s in by], "rounds": a["rounds"]})  # and the rounds that asked it
    return rows


def fill(template, **kw):
    """A template from questions.json with its slots filled."""
    # a list template gives several questions, a single string gives one; both come back as a list
    return [t.format(**kw) for t in template] if isinstance(template, list) else [template.format(**kw)]


def build(job, out=None):
    """The question map as a list of entries (no model). out: the folder that may hold anticipated.json."""
    items, alts = corpus.load(job)  # the scenes, for coverage
    cov = cover.Coverage(items, alts, job.kit)  # coverage rules
    company = job.kit.get("company") or STD["company_default"]  # the company's name for the templates
    company = company if isinstance(company, dict) else {"en": company, "ko": company}  # one name serves both languages
    posting_path = job.in_job(job.kit["posting"])  # posting.md
    posting = read_text(posting_path) if posting_path and posting_path.is_file() else ""  # empty when the file is missing
    rp, pp = job.submitted("resume"), job.submitted("portfolio")  # the documents that were sent
    resume = read_text(rp) if rp else ""  # no resume sent, no resume questions
    portfolio = read_text(pp) if pp else ""  # the same for the portfolio
    rows = []  # the map

    def add(kind, pid, source, txt, ask, section=""):  # one map entry, rated for coverage on its own text
        rating, by, _ = cov.rate(txt)  # does a scene already answer it?
        # the entry: its id, where it came from, the line, the questions, and the scenes that cover it
        rows.append({"id": pid, "kind": kind, "source": source, "section": section, "text": txt, "ask": ask,
                     "coverage": rating, "covered_by": [[i, s] for i, s in by]})  # (id, share) pairs as plain lists

    rows += asked_rows(job, cov)  # what the earlier rounds asked, first
    for k, (n, sec, line) in enumerate(posting_lines(posting), 1):  # one entry per posting line, ids p1, p2, ...
        add("posting", f"p{k}", f"{posting_path.name}:{n}", line,  # the source is the posting file and line number
            {"en": fill(STD["posting"]["en"], text=line), "ko": fill(STD["posting"]["ko"], text=line)}, sec)  # with its section
    for k, (n, line) in enumerate(resume_lines(resume), 1):  # one entry per resume line, ids r1, r2, ...
        # the source is the resume file and line; the questions ask the person to explain the line
        add("resume", f"r{k}", f"{rp.name}:{n}", line, {"en": fill(STD["resume"]["en"], text=line), "ko": fill(STD["resume"]["ko"], text=line)})
    for k, (page, title, body) in enumerate(portfolio_pages(portfolio), 1):  # one entry per portfolio page, ids f1, f2, ...
        rating_text = title + "\n" + body  # a page is covered by what it shows, not only its title
        rating, by, _ = cov.rate(rating_text)  # rated on the whole page, which is why add() is not used here
        # the entry shows only the page title, with the file and page number as its source
        rows.append({"id": f"f{k}", "kind": "portfolio", "source": f"{pp.name}:page {page}", "section": "", "text": title,
                     # follow-up questions about the page, named by its title
                     "ask": {"en": fill(STD["portfolio"]["en"], title=title), "ko": fill(STD["portfolio"]["ko"], title=title)},
                     "coverage": rating, "covered_by": [[i, s] for i, s in by]})  # the same shape add() writes
    for k, (term, count) in enumerate(own_terms(job, resume, portfolio), 1):  # one entry per term, ids t1, t2, ...
        # the source column shows how often the term appears in the documents
        add("term", f"t{k}", f"{count}x", term, {"en": fill(STD["term"]["en"], term=term), "ko": fill(STD["term"]["ko"], term=term)})
    for k, q in enumerate(STD["behavioral"], 1):  # the standard behavioral questions, ids b1, b2, ...
        # already written in both languages; the topic goes in the section column
        add("behavioral", f"b{k}", "questions.json", q["en"], {"en": [q["en"]], "ko": [q["ko"]]}, q["topic"])
    k = 0  # company questions: the standard ones, then one per research heading
    for q in STD["company"]:  # the standard company questions
        k += 1  # one id counter across both groups
        en, ko = q["en"].format(company=company["en"]), q["ko"].format(company=company["ko"])  # the name in each language
        add("company", f"c{k}", "questions.json", en, {"en": [en], "ko": [ko]}, q["topic"])  # the topic as the section
    for f, n, head in research_headings(job):  # one more company question per research heading
        k += 1  # the next company id
        # the questions ask about the heading's topic; the source is the research file and line
        add("company", f"c{k}", f"{f}:{n}", head, {"en": fill(STD["research"]["en"], title=head), "ko": fill(STD["research"]["ko"], title=head)})
    counts = {"scenario": 0, "technical": 0}  # ids count per kind
    for q in (read_json(job.out_path(out) / ANTICIPATED, {}) or {}).get("questions") or []:  # what the model expected to be asked, once written
        counts[q["kind"]] += 1  # the next id of this kind
        # ids s1, s2, ... for scenarios and k1, k2, ... for technical questions
        add(q["kind"], f"{'s' if q['kind'] == 'scenario' else 'k'}{counts[q['kind']]}", ANTICIPATED, q["en"], {"en": [q["en"]], "ko": [q["ko"]]})
    for k, q in enumerate(STD["opening"], 1):  # greeting, sound check and the other opening steps, ids o1, o2, ...
        # already written in both languages; the topic goes in the section column
        add("opening", f"o{k}", "questions.json", q["en"], {"en": [q["en"]], "ko": [q["ko"]]}, q["topic"])
    return rows


ANTICIPATED = "anticipated.json"  # the model's expected questions, kept beside the map so that remaking the map costs no call
ANTICIPATE_PROMPT = (HERE / "prompts" / "anticipate.md").read_text(encoding="utf-8")  # the request
ANTICIPATE_SYSTEM = "You are an experienced technical interviewer. You list the questions you would really ask. Return only JSON."  # short, as the request holds the rules


def anticipate(job, out=None, backend=None, count=24, ask=None):
    """Ask the model once for the scenario and technical questions of this job, and keep them in the output folder.
    Returns (how many questions the folder now holds, why the model could not answer or ''). A second call asks nothing."""
    path = job.out_dir(out) / ANTICIPATED  # beside the map
    kept = read_json(path, {}) or {}  # an earlier answer
    if kept.get("questions"):  # one call per job: the same questions serve every later map
        return len(kept["questions"]), ""
    posting_path = job.in_job(job.kit["posting"])  # the posting
    posting = read_text(posting_path) if posting_path and posting_path.is_file() else ""  # empty when the file is missing
    rp = job.submitted("resume")  # the resume that was sent
    if not posting.strip():  # nothing to draw duties from
        return 0, ""
    prompt = ANTICIPATE_PROMPT.format(posting=posting[:8000], resume=(read_text(rp) if rp else "")[:6000], count=count)  # small enough for any backend
    import llm  # src/llm.py, the one door to a model
    try:
        answer = (ask or llm.run)("interview-anticipate", prompt, system=ANTICIPATE_SYSTEM, want_json=True, required=("questions",), backend=backend, timeout=300)  # one JSON answer
    except (llm.LLMUnavailable, ValueError) as e:  # no model, or an answer that never had the right form: the map goes on without them
        return 0, str(e)
    rows, seen = [], set()  # the questions that have the right form, each once
    for q in answer.get("questions") or []:  # as answered
        en, ko, kind = str(q.get("en", "")).strip(), str(q.get("ko", "")).strip(), q.get("kind")  # its parts
        if en and ko and kind in ("scenario", "technical") and en.lower() not in seen:  # both languages, a known kind, not seen before
            seen.add(en.lower())  # each question once
            rows.append({"kind": kind, "en": en, "ko": ko})  # kept
    path.write_text(json.dumps({"questions": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # kept for every later map
    return len(rows), ""


# The system prompt of --phrase: keep the meaning and every name, short spoken English, natural Korean, JSON only
PHRASE_SYSTEM = ("You phrase interview questions. Keep each question's meaning and every name in it. Plain spoken English, short; "
                 "natural Korean. Return only JSON.")


def phrase_questions(rows, backend=None):
    """Let the model phrase the questions of each kind in one call; (count phrased, why it stopped or '')."""
    import llm  # src/llm.py, the one door to a model
    done = 0  # entries phrased
    for kind in ("posting", "resume", "portfolio", "term"):  # the kinds made from templates; the others are already phrased
        group = [r for r in rows if r["kind"] == kind]  # one call per kind keeps calls few and small
        if not group:  # nothing of this kind, so no call
            continue
        lines = "\n".join(f'{r["id"]}\t{r["text"]}' for r in group[:60])  # the first 60 of a kind at most
        # the task: one question per id in both languages, returned as JSON keyed by id
        prompt = (f"Each line is an id, a tab, and a line from a candidate's {kind}. Write the question an interviewer would ask "
                  "about it, in English and in Korean. Return {\"<id>\": {\"en\": \"...\", \"ko\": \"...\"}, ...} for every id.\n\n" + lines)
        try:
            # one JSON answer for the whole kind; the task name says which kind it was
            out = llm.run(f"interview-plan-{kind}", prompt, system=PHRASE_SYSTEM, want_json=True, backend=backend, timeout=240)
        except llm.LLMUnavailable as e:  # no model: the rule-made questions stay
            return done, str(e)
        except ValueError as e:  # the answer never had the right form
            return done, str(e)
        for r in group:  # merge the answer back into each entry
            q = out.get(r["id"]) if isinstance(out, dict) else None  # this entry's phrasing, if the model gave one
            if isinstance(q, dict) and q.get("en") and q.get("ko"):  # only when both languages came back
                r["ask_rule"] = r["ask"]  # keep the rule-made questions next to the phrased ones
                # the phrased question goes first; the other rule-made questions stay after it
                r["ask"] = {"en": [str(q["en"])] + r["ask"]["en"][1:], "ko": [str(q["ko"])] + r["ask"]["ko"][1:]}
                done += 1  # one more entry phrased
    return done, ""  # every kind went through


def write_md(rows, path):
    """A readable table of the map, grouped by kind."""
    out = ["# Question map", ""]  # markdown lines
    for kind in KINDS:  # the order the map is built in
        group = [r for r in rows if r["kind"] == kind]  # the entries of this kind
        if not group:  # no table for an empty kind
            continue
        # a heading with the count, then the table header
        out += [f"## {kind} ({len(group)})", "", "| id | coverage | covered by | question |", "|---|---|---|---|"]
        for r in group:  # one table row per entry
            by = ", ".join(i for i, _ in r["covered_by"]) or "-"  # the covering scene ids, or a dash for none
            # the first question, with pipes swapped so they do not break the table
            out.append(f'| {r["id"]} | {r["coverage"]} | {by} | {r["ask"]["en"][0].replace("|", "/")} |')
        out.append("")  # a blank line after each table
    path.write_text("\n".join(out), encoding="utf-8")  # the whole report in one write


def main(job, out=None, phrase=False, backend=None, expect=False):
    """Build the map, optionally phrase it, write plan.json and plan.md, and print the summary line. expect: first ask the
    model once for the scenario and technical questions."""
    if expect:  # the optional call that adds questions
        n, why = anticipate(job, out, backend)  # how many, and why not
        print(i18n.t("plan_expected", n=n) if not why else i18n.t("plan_unphrased", why=why))  # say which
    rows = build(job, out)  # the rule-made map
    if phrase:  # the optional model step
        n, why = phrase_questions(rows, backend)  # how many were phrased, and why it stopped if it did
        # how many were phrased, or why the model step stopped
        print(i18n.t("plan_phrased", n=n, backend=backend or "default") if not why else i18n.t("plan_unphrased", why=why))
    d = job.out_dir(out)  # the output folder
    # the whole map with the job name, as readable UTF-8 JSON for draft.py and for people
    (d / "plan.json").write_text(json.dumps({"job": job.name, "questions": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_md(rows, d / "plan.md")  # the same map as tables for reading
    # entries per kind, for the summary line
    count = {k: sum(1 for r in rows if r["kind"] == k) for k in KINDS}
    # the summary line; behavioral and company questions are reported together as general ones
    if count["asked"]:  # what the earlier rounds asked, said first
        print(i18n.t("plan_asked", n=count["asked"]))
    print(i18n.t("plan_summary", posting=count["posting"], resume=count["resume"], portfolio=count["portfolio"], terms=count["term"],
                 general=count["behavioral"] + count["company"], expected=count["scenario"] + count["technical"], opening=count["opening"], out=d / "plan.json"))
    return 0
