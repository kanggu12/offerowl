"""The talk: a presentation interview's deck and speaker script (docs/INTERVIEW.md, "The talk").

    python3 src/interview/cli.py talk --job <dir> [--lang ko|en] [--backend none] [--pdf] [--out DIR]

The person's brief, <job>/interview/talk.json, says what the interviewers asked for: the topics in their order, the minutes,
the day and the format. make() plans the slides from the brief and the job's edition (the profile and the portfolio the job's
documents were made from), fills what the documents already say, has the AI backend write the rest from the person's
evidence (talk_write.py: every sentence cites its evidence and is checked like a resume sentence), draws the deck with the
portfolio's own slides among the talk's (src/talk_slides.js), prints it, and writes the speaker script (talk_page.py): each
slide's words, its time and the running total, where to point, what to cut when time runs short and the questions to expect.
Everything goes to <out>/talk/; nothing is written into the job folder.
"""
from __future__ import annotations

import hashlib  # a staged deck source's folder name
import json  # the brief, the portfolio's slides and the deck's input
import math  # page counts from minutes
import os  # the environment of the deck's steps
import pathlib  # paths
import re  # periods, kinds and words
import shutil  # staging the person's deck source
import subprocess  # node, for the portfolio's slides and the deck
import sys  # the Python that runs the figure step

SRC = pathlib.Path(__file__).resolve().parent.parent  # src/
ROOT = SRC.parent  # the engine's folder, where the deck's pages are written
if str(SRC) not in sys.path:  # resume.py and cover.py import as top-level modules
    sys.path.insert(0, str(SRC))

TOPIC_KINDS = ("intro", "experience", "challenge", "motivation", "plan", "custom")  # what a topic of the brief can ask for
# A topic's kinds from its words, first match wins for the first three; motivation and plan may both match ("why us, and your plan")
GUESS = [("challenge", r"도전|어려웠|어려운|문제|돌파|극복|실패|갈등|위기|challeng|difficult|hardest|problem|overc|conflict|failure"),
         ("intro", r"소개|역량|강점|자기\s*자신|자신을|introduc|about you|yourself|strength|competenc"),
         ("experience", r"경험|기술|프로젝트|업무|과제|성과|경력|experience|project|work|skill|learn|career so far|walk us through|walk me through"),
         ("motivation", r"지원\s*동기|지원\s*계기|동기|계기|왜\s|motivation|why\b"),
         ("plan", r"계획|포부|비전|커리어|목표|입사\s*후|향후|plan|vision|career|goal|future|next")]
WEIGHT = {"cover": 0.5, "agenda": 0.8, "chapter": 0.35, "about": 1.8, "strengths": 1.8, "page": 1.7, "lessons": 2.0,  # minutes a slide takes, as a share of its part
          "problem": 2.6, "approach": 3.0, "result": 2.6, "story": 2.6, "why": 1.8, "plan": 2.2, "points": 2.0, "end": 0.3}
SHARE = {"intro": 0.17, "experience": 0.45, "challenge": 0.27, "motivation": 0.06, "plan": 0.08, "custom": 0.2}  # a topic's share of the talk when the brief gives no minutes
PACE = {"ko": (165, 270), "en": (110, 160)}  # spoken pace: Korean characters without spaces a minute, English words a minute
WORDS = {  # the talk's fixed words in each language
    "ko": {"topics": ["소개와 핵심 역량", "업무로 배운 경험과 기술", "가장 도전적이었던 문제", "지원 계기와 커리어 계획"],
           "short": {"intro": "소개", "experience": "경험과 기술", "challenge": "도전 문제", "motivation": "지원 계기", "plan": "계획", "custom": "주제"},
           "en": {"intro": "INTRODUCTION", "experience": "EXPERIENCE", "challenge": "CHALLENGE", "motivation": "MOTIVATION", "plan": "PLAN", "custom": "TOPIC"},
           "agenda": "발표 순서", "messages": "이 발표의 메시지", "agenda_lede": "요청하신 {n}개 항목의 순서로 약 {m}분 동안 말씀드린 뒤 질문을 받겠습니다.",
           "agenda_one": "요청하신 항목을 약 {m}분 동안 말씀드린 뒤 질문을 받겠습니다.", "both": "지원 계기와 계획", "story_rules": "{a}",
           "about": "자기소개", "about_sub": "이력서 요약", "career": "경력 요약", "education": "학력", "skills": "보유 기술",
           "strengths": "핵심 역량", "strengths_sub": "역량과 그 근거", "overview": "개요",
           "lessons": "업무에서 배운 것", "why": "지원 계기", "plan": "커리어 계획",
           "problem": "문제", "approach": "돌파", "result": "결과와 배운 것", "points": "요점", "end": "감사합니다", "end_tag": "질문을 듣겠습니다",
           "when": "일정", "format": "형식", "length": "분량", "structure": "구성", "length_v": "{n}장, 발표 약 {m}분", "request": "요청 항목",
           "part_len": "{n}장, 약 {m}분", "flow": "흐름", "time_order": "시간 순서", "note": "요점", "mine": "제 몫", "phone": "전화", "email": "이메일",
           "rule_script": "슬라이드의 글로 만든 초안입니다. 자기 말로 바꿔 쓰세요.", "top": "{company} 인터뷰 발표"},
    "en": {"topics": ["About me and my strengths", "What my work taught me", "The hardest problem I solved", "Why this role, and my plan"],
           "short": {"intro": "About", "experience": "Experience", "challenge": "Challenge", "motivation": "Why", "plan": "Plan", "custom": "Topic"},
           "en": {"intro": "INTRODUCTION", "experience": "EXPERIENCE", "challenge": "CHALLENGE", "motivation": "MOTIVATION", "plan": "PLAN", "custom": "TOPIC"},
           "agenda": "Agenda", "messages": "What this talk shows", "agenda_lede": "The {n} topics you asked for, in your order, in about {m} minutes, then your questions.",
           "agenda_one": "The topic you asked for, in about {m} minutes, then your questions.", "both": "Why and plan", "story_rules": "{a}",
           "about": "About me", "about_sub": "From my resume", "career": "Career", "education": "Education", "skills": "Skills",
           "strengths": "Strengths", "strengths_sub": "What I am good at, and where it shows", "overview": "Overview",
           "lessons": "What my work taught me", "why": "Why this role", "plan": "My plan",
           "problem": "The problem", "approach": "The way through", "result": "What came of it", "points": "Points", "end": "Thank you", "end_tag": "Your questions are welcome",
           "when": "When", "format": "Format", "length": "Length", "structure": "Structure", "length_v": "{n} slides, about {m} minutes", "request": "Asked for",
           "part_len": "{n} slides, about {m} min", "flow": "Order", "time_order": "Oldest first", "note": "Point", "mine": "My part", "phone": "Phone", "email": "Email",
           "rule_script": "A draft made from the slide's own words. Say it in your own words.", "top": "Interview presentation, {company}"},
}
OVERVIEW_ICON = [(r"직무|role|target|지향", "target"), (r"분야|focus|주력", "layers"), (r"강점|strength", "activity"),  # an overview card's icon from its title
                 (r"도메인|산업|industr|domain", "building-2"), (r"규모|scale", "gauge")]
PART_ICON = {"intro": "user-check", "experience": "activity", "challenge": "flask-conical", "motivation": "target", "plan": "route", "custom": "list"}  # a part's icon
PILLAR_ICON = ["shield-check", "activity", "workflow", "layers"]  # the strengths' icons in order


class TalkError(Exception):
    """The talk cannot be made; the message says why in the person's words."""


# ───────── the brief ─────────

def kinds_of(title: str) -> list:
    """What a topic asks for, from its words: one kind, or motivation and plan together."""
    low = str(title or "").lower()  # matched without case
    hit = [k for k, pat in GUESS if re.search(pat, low)]  # every kind its words name
    if "challenge" in hit:  # "the hardest problem" is a story even when it says "work"
        return ["challenge"]
    if "motivation" in hit and "plan" in hit:  # "why us, and your plan"
        return ["motivation", "plan"]
    if "experience" in hit and "plan" in hit and not re.search(r"계획|포부|비전|plan|vision|goal", low):  # "the project you are proudest of in your career" is work, not a plan
        return ["experience"]
    for k in ("intro", "motivation", "plan", "experience"):  # the first one that names it
        if k in hit:
            return [k]
    return ["custom"]  # a topic of the person's own


def read_brief(job) -> dict:
    """The person's brief as written (<job>/interview/talk.json), or {} when there is none."""
    p = job.in_interview("talk.json")  # beside kit.json; refused outside a confined kit's workspace
    if not p or not p.is_file():  # no brief yet: the defaults
        return {}
    try:
        got = json.loads(p.read_text(encoding="utf-8"))  # the person's file
    except (OSError, ValueError) as e:  # a broken file says so, never a stack trace
        raise TalkError(f"talk.json: {e}")
    return got if isinstance(got, dict) else {}  # anything else is no brief


def hex_colour(v) -> str | None:
    """A #rrggbb colour, or None."""
    s = str(v or "").strip()  # as written
    return s if re.fullmatch(r"#[0-9a-fA-F]{6}", s) else None  # only a full hex colour


def normalize(raw: dict, lang: str) -> dict:
    """The brief with every default filled: topics with kinds and minutes, the length, the day, the format, the theme."""
    W = WORDS[lang]  # the language's fixed words
    minutes = raw.get("minutes")  # the talk's length without the questions
    minutes = int(minutes) if isinstance(minutes, (int, float)) and 5 <= minutes <= 120 else 30  # a sane length, else half an hour
    topics = []  # the topics in the interviewers' order
    raw_topics = raw.get("topics") if isinstance(raw.get("topics"), list) else None  # a list, or the defaults
    used = set()  # the kinds earlier topics took: a second topic of a kind becomes a topic of the person's own
    for i, t in enumerate(raw_topics or [{"title": x} for x in W["topics"]]):  # the brief's, else the usual four
        if not isinstance(t, (str, dict)):  # a number or a list is no topic
            continue
        t = {"title": t} if isinstance(t, str) else dict(t)  # a bare title is a topic
        title = " ".join(str(t.get("title") or "").split())[:200]  # its words, on one line
        if not title:  # an empty topic is no topic
            continue
        given = t.get("kinds") if isinstance(t.get("kinds"), list) else ([t["kind"]] if isinstance(t.get("kind"), str) else [])  # named kinds
        ks = [k for k in given if k in TOPIC_KINDS] or kinds_of(title)  # named, else guessed
        ks = [k for k in ks if k == "custom" or k not in used] or ["custom"]  # each kind's slides once: a second one is the person's own topic
        used.update(ks)
        m = t.get("minutes")  # its minutes, when the brief gives them
        topics.append({"title": title, "kinds": ks, "minutes": float(m) if isinstance(m, (int, float)) and m > 0 else None})
    if not topics:  # every topic was empty
        raise TalkError("the brief names no topic" if lang == "en" else "발표 요청 항목이 비어 있습니다")
    given_sum = sum(t["minutes"] for t in topics if t["minutes"] is not None)  # what the brief gave out by topic
    free_n = sum(1 for t in topics if t["minutes"] is None)
    if given_sum and given_sum > minutes - free_n:  # more than the talk holds: scaled so each other topic keeps at least a minute
        k = (minutes - free_n) / given_sum
        for t in topics:
            if t["minutes"] is not None:
                t["minutes"] = round(t["minutes"] * k, 1)
    free = [t for t in topics if t["minutes"] is None]  # topics without their own minutes share what is left
    left = max(0.0, minutes - sum(t["minutes"] for t in topics if t["minutes"] is not None))  # the minutes not given out
    weights = [sum(SHARE[k] for k in t["kinds"]) for t in free]  # each by what it asks for
    for t, w in zip(free, weights):  # in proportion
        t["minutes"] = round(left * w / (sum(weights) or 1), 1) if left else 1.0
    pages = [int(n) for n in (raw.get("pages") if isinstance(raw.get("pages"), list) else []) if (isinstance(n, int) and not isinstance(n, bool) and 0 < n < 1000) or (isinstance(n, str) and n.isdigit() and len(n) < 4)]  # portfolio pages the person chose
    ch = raw.get("challenge") if isinstance(raw.get("challenge"), dict) else ({"page": raw["challenge"]} if isinstance(raw.get("challenge"), int) else {})  # the story's project
    theme = raw.get("theme") if isinstance(raw.get("theme"), dict) else {}  # the company's colours
    frame, accent = hex_colour(theme.get("frame")), hex_colour(theme.get("accent"))  # both, or neither
    return {"lang": lang, "minutes": minutes, "qa": raw.get("qa") if isinstance(raw.get("qa"), (int, float)) else None,
            "when": str(raw.get("when") or "").strip(), "format": str(raw.get("format") or "").strip(), "where": str(raw.get("where") or "").strip(),
            "request": str(raw.get("request") or "").strip()[:4000], "topics": topics, "pages": pages, "challenge": ch,
            "order": "portfolio" if raw.get("order") == "portfolio" else "time", "headline": str(raw.get("headline") or "").strip(),
            "theme": {"frame": frame, "accent": accent} if frame and accent else None, "company": str(raw.get("company") or "").strip(),
            "swaps": [[str(x[0]), str(x[1])] for x in raw["swaps"] if isinstance(x, list) and len(x) == 2 and x[0]] if isinstance(raw.get("swaps"), list) else []}


# ───────── the edition: the profile and the portfolio the job's documents come from ─────────

def edition(job, lang: str) -> dict:
    """The job's edition in a language (jobs/<job>/resume/<lang>/profile.json and job.json), else the workspace's profile with
    no settings: the portfolio is then drawn from the profile as the documents would be."""
    d = job.dir / "resume" / lang  # where the panel keeps an edition
    prof, cfg = d / "profile.json", d / "job.json"  # its profile and settings
    if prof.is_file():  # the edition the job's documents were made from
        return {"profile": prof, "job": cfg if cfg.is_file() else None, "made": True}
    base = job.profile_path  # the confirmed facts
    if base and pathlib.Path(base).is_file():  # no edition yet: the profile itself
        return {"profile": pathlib.Path(base), "job": None, "made": False}
    raise TalkError("no profile for this job" if lang == "en" else "이 지원의 프로필이 없습니다")


def stage_source(job, env: dict) -> dict:
    """The person's own deck source (<workspace>/deck with build.js) copied into the engine's folder, as the panel stages it for
    a build, and named in the steps' environment. Without one the portfolio is drawn from the profile."""
    env = dict(env)  # the caller's stays as it was
    env.pop("OFFEROWL_DECK_SOURCE", None)  # never one this process was started with
    d = (job.workspace / "deck") if job.workspace else None  # beside the profile and the jobs
    if d and (d / "build.js").is_file():  # the person keeps their own slides
        dst = ROOT / "output" / "_inputs" / (hashlib.sha1(str(d.resolve()).encode()).hexdigest()[:8] + "_talk")  # its copy for the talk
        shutil.rmtree(dst, ignore_errors=True)  # fresh: a removed file does not linger
        shutil.copytree(d, dst)
        env["OFFEROWL_DECK_SOURCE"] = dst.relative_to(ROOT).as_posix()  # repository-relative, as resume.deck_source reads it
    return env


def portfolio_info(ed: dict, env: dict) -> dict:
    """What the portfolio holds ({own, slides, view}): node src/talk_slides.js --pages, the profile as the documents read it."""
    import resume as R  # noqa: E402  the engine's helpers: Node.js and repository-relative paths
    args = [R.node(), "src/talk_slides.js", "--pages", R.rel(str(ed["profile"])), R.rel(str(ed["job"])) if ed["job"] else "", "talk_pages"]
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=R.html_env(env), timeout=600)
    if r.returncode != 0:  # the portfolio could not be drawn
        raise TalkError("the portfolio could not be read:\n" + (r.stderr or r.stdout)[-1500:])
    try:
        return json.loads(r.stdout)  # the slides and the view
    except ValueError:
        raise TalkError("the portfolio's slides came back unreadable:\n" + r.stdout[-800:])


def figures(ed: dict, env: dict, lang: str) -> str:
    """The timeline and the logo tiles the portfolio's slides show (src/overview_figures.py), drawn before its slides are; the
    output name they are drawn under."""
    import resume as R  # noqa: E402
    cfg = json.loads(ed["job"].read_text(encoding="utf-8")) if ed["job"] else {}  # the edition's settings
    out, jf = R.job_file(str(ed["profile"]), str(ed["job"]) if ed["job"] else None)  # its output name, and its settings inside the repository
    subprocess.run([sys.executable, "src/overview_figures.py", R.rel(str(ed["profile"])), out, lang, jf], cwd=ROOT, capture_output=True,
                   env=R.html_env(env, OFFEROWL_FIG_THEME=cfg.get("theme") or "navy"), timeout=600)  # a failure only leaves the tiles out
    return out


# ───────── matching the posting's words to the portfolio's pages ─────────

def words(text: str) -> list:
    """The terms of a text as the cover letter's matcher reads them (Korean particles off, both scripts)."""
    import cover as C  # noqa: E402
    return C.terms(text)


def rank(text: str, pages: list, k: int = 2) -> list:
    """The k portfolio pages whose words share the most rare terms with a text (a small BM25 over the pages)."""
    q = set(words(text))  # the text's terms
    if not q or not pages:  # nothing to match
        return []
    docs = [(p, words(p.get("title", "") + " " + p.get("tag", "") + " " + p.get("text", ""))) for p in pages]  # each page's terms
    n = len(docs)  # how many pages
    df = {}  # how many pages hold each term
    for _, ws in docs:
        for w in set(ws):
            df[w] = df.get(w, 0) + 1
    avg = sum(len(ws) for _, ws in docs) / n or 1  # the mean page length
    scored = []  # (score, page)
    for p, ws in docs:  # BM25 with the usual constants
        tf = {}
        for w in ws:
            tf[w] = tf.get(w, 0) + 1
        s = sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(ws) / avg)) for w in q if w in tf)
        if s > 0:  # shares something
            scored.append((s, p))
    scored.sort(key=lambda x: -x[0])  # the best first
    return [p for _, p in scored[:k]]


def start_of(period: str) -> int:
    """A period's first month as YYYYMM, 0 when it names none."""
    m = re.search(r"(\d{4})(?:\.(\d{1,2}))?", str(period or ""))  # 2024.05 ~ 2025.01
    return int(m.group(1)) * 100 + int(m.group(2) or 1) if m else 0


def base_title(t: str) -> str:
    """A title without its spread mark, '(1/2)'."""
    return re.sub(r"\s*\(\d+/\d+\)\s*$", "", str(t or "")).strip()


def norm(s: str) -> str:
    """A title for comparing: no spaces, no punctuation, lower case."""
    return re.sub(r"[\W_]+", "", str(s or "")).lower()


def page_of_project(pid: str, title: str, slides: list) -> list:
    """The portfolio pages that show a project: by its id when the portfolio tags its slides, else by its title."""
    hit = [s for s in slides if s.get("project") and pid and s["project"] == pid]  # the deck drawn from the profile tags them
    if hit:
        return hit
    t = norm(title)  # the person's own slides are found by their titles
    return [s for s in slides if s["kind"] == "project" and t and (norm(base_title(s["title"])) == t or (len(t) >= 6 and t in norm(s["title"])))]


# ───────── the plan ─────────

def plan(brief: dict, info: dict, posting: dict | None) -> list:
    """The slides in order: [{key, kind, part, ...}]. A part opens with its divider when the talk has more than one part."""
    view, slides = info["view"], info["slides"]  # the profile and the portfolio
    projects = [s for s in slides if s["kind"] == "project"]  # the portfolio's project pages
    out = [{"key": "cover", "kind": "cover", "part": 0}, {"key": "agenda", "kind": "agenda", "part": 0}]  # the talk opens with these
    asks_story = any("challenge" in t["kinds"] for t in brief["topics"])  # a topic asks for the hardest problem
    story_pages = story_page(brief, view, projects) if asks_story else []  # its page(s), chosen first so experience leaves them out
    for i, t in enumerate(brief["topics"]):  # the parts in the interviewers' order
        if len(brief["topics"]) > 1:  # a divider for each part
            out.append({"key": f"part{i + 1}", "kind": "chapter", "part": i})
        for k in t["kinds"]:  # what the part asks for
            if k == "intro":  # who the person is, what they are good at, and the posting against the talk
                out += [{"key": "about", "kind": "about", "part": i}]
                if view.get("competencies"):  # the edition lists strengths
                    out.append({"key": "strengths", "kind": "strengths", "part": i})
            elif k == "experience":  # the portfolio's pages, then what they taught
                room = max(2, min(12, round((t["minutes"] - WEIGHT["chapter"] - WEIGHT["lessons"]) / WEIGHT["page"])))  # pages the minutes hold
                for s in experience_pages(brief, projects, story_pages, posting, room):  # in the brief's or the time order
                    out.append({"key": f"pf{s['n']}", "kind": "page", "part": i, "n": s["n"], "title": base_title(s["title"]), "tag": s["tag"], "period": s["period"]})
                out.append({"key": "lessons", "kind": "lessons", "part": i})
            elif k == "challenge":  # the story: its project's page, then the problem, the way through and the result
                for s in story_pages:
                    out.append({"key": f"pf{s['n']}", "kind": "page", "part": i, "n": s["n"], "title": base_title(s["title"]), "tag": s["tag"], "period": s["period"]})
                out += [{"key": "problem", "kind": "problem", "part": i}, {"key": "approach", "kind": "approach", "part": i}, {"key": "result", "kind": "result", "part": i}]
            elif k in ("motivation", "plan"):  # why this job, and what comes after
                out.append({"key": "why" if k == "motivation" else "plan", "kind": "why" if k == "motivation" else "plan", "part": i})
            else:  # a topic of the person's own
                out.append({"key": f"points{i + 1}", "kind": "points", "part": i})
    out.append({"key": "end", "kind": "end", "part": len(brief["topics"]) - 1})  # the questions
    seen, uniq = set(), []  # a page shown twice keeps its first place
    for s in out:
        if s["key"] not in seen:
            seen.add(s["key"]); uniq.append(s)
    return uniq


def story_page(brief: dict, view: dict, projects: list) -> list:
    """The hardest problem's project page(s): the brief's choice, else the first selected project of the resume's summary."""
    ch = brief.get("challenge") or {}  # {page} or {project} or {title}
    if ch.get("page"):  # a page number
        hit = [s for s in projects if s["n"] == int(ch["page"])]
    elif ch.get("project") or ch.get("title"):  # a project id or title
        hit = page_of_project(str(ch.get("project") or ""), str(ch.get("title") or ""), projects)
    else:  # the resume's first selected project
        lights = (view.get("summary") or {}).get("highlights") or []  # the selected projects
        first = lights[0] if lights and isinstance(lights[0], dict) else {}
        hit = page_of_project("", str(first.get("title") or ""), projects) if first else []
        if not hit and projects:  # a summary whose titles differ from the slides': the best match for its words
            hit = rank(" ".join(str(r[1]) for r in first.get("rows", []) if isinstance(r, (list, tuple)) and len(r) > 1), projects, 1) if first else []
    if hit:  # a spread keeps its pages together
        t = norm(base_title(hit[0]["title"]))
        hit = [s for s in projects if norm(base_title(s["title"])) == t] or hit[:1]
    return hit


def experience_pages(brief: dict, projects: list, story: list, posting: dict | None, room: int) -> list:
    """The portfolio pages of the experience part: the brief's pages in its order, else the pages that match the posting best,
    in the time order (oldest first) or the portfolio's."""
    taken = {s["n"] for s in story}  # the story's pages appear once, in their own part
    if brief.get("pages"):  # the person chose
        by_n = {s["n"]: s for s in projects}
        return [by_n[n] for n in brief["pages"] if n in by_n and n not in taken]
    pool = [s for s in projects if s["n"] not in taken]  # every other project page
    groups = {}  # spreads stay together: one entry per project
    for s in pool:
        groups.setdefault(norm(base_title(s["title"])), []).append(s)
    entries = list(groups.values())  # [[page, page], [page], ...]
    if posting and posting.get("items") and len(entries) > room:  # more projects than the minutes hold: the posting decides
        text = " ".join(it["text"] for it in posting["items"])  # every line of the posting
        best = rank(text, [e[0] for e in entries], k=len(entries))  # all of them, the best first
        order = {id(e): i for i, e in enumerate(best)}
        entries.sort(key=lambda e: order.get(id(e[0]), len(entries)))
    chosen, count = [], 0  # within the room
    for e in entries:
        if count + len(e) > room and chosen:
            continue
        chosen.append(e); count += len(e)
    if brief.get("order") != "portfolio":  # the time order: where the career started first
        chosen.sort(key=lambda e: (start_of(e[0]["period"]) or 999999, e[0]["n"]))
    else:  # the portfolio's own order
        chosen.sort(key=lambda e: e[0]["n"])
    return [s for e in chosen for s in e]


def timing(slides: list, brief: dict) -> None:
    """Each slide's seconds: its part's minutes shared by the slides' weights (the cover and the agenda belong to the first part,
    the end to the last)."""
    for i, t in enumerate(brief["topics"]):  # each part
        mine = [s for s in slides if s["part"] == i]  # its slides
        total = sum(WEIGHT[s["kind"]] for s in mine) or 1  # their weights
        for s in mine:
            s["seconds"] = int(round(t["minutes"] * 60 * WEIGHT[s["kind"]] / total / 5.0) * 5)  # to five seconds


def number(slides: list) -> dict:
    """Page numbers in order; returns key -> page."""
    for n, s in enumerate(slides, 1):
        s["page"] = n
    return {s["key"]: s["page"] for s in slides}


def resolve(text, pages: dict) -> str:
    """A text with its {{key}} page marks replaced by page numbers; a mark for a slide the talk has not is dropped."""
    return re.sub(r"\{\{([\w-]+)\}\}", lambda m: str(pages.get(m.group(1), "")), str(text or ""))


def keys_to_pages(keys, pages: dict) -> list:
    """Slide keys (or page numbers) to the talk's page numbers, in order, once each."""
    out = []
    for k in keys or []:
        n = pages.get(str(k)) if not isinstance(k, int) else (k if k in pages.values() else None)
        if n and n not in out:
            out.append(n)
    return sorted(out)


# ───────── what the documents already say ─────────

def short(text: str, n: int) -> str:
    """A line cut at a word boundary to about n characters."""
    s = " ".join(str(text or "").replace("==", "").split())  # one line, no highlight marks
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]  # the last whole word
    return (cut if len(cut) >= n * 0.6 else s[:n]).rstrip(",.:;") + "…"


def one_line(text: str, n: int = 88) -> str:
    """A text's first sentence when it fits a slide's one-line lede, else nothing (the slide's cards carry it)."""
    s = " ".join(str(text or "").split())
    first = re.split(r"(?<=[.!?다])\s+", s)[0] if s else ""
    return first if len(first.replace("==", "")) <= n else ""


def plain_pairs(v) -> list:
    """[[title, text]] from the shapes an overview card list takes."""
    out = []
    for c in v or []:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            out.append([str(c[0]), str(c[1])])
        elif isinstance(c, dict) and (c.get("title") or c.get("key")):
            out.append([str(c.get("title") or c.get("key")), str(c.get("text") or c.get("ko") or c.get("en") or "")])
    return out


def tile_path(out: str, logo_id: str | None) -> str | None:
    """A logo tile the figure step drew for a role or a school, when there is one."""
    if not logo_id:
        return None
    f = ROOT / "output" / "_figures" / f"{out}_logo_{logo_id}.png"  # src/overview_figures.py names them so
    return str(f) if f.is_file() else None


def fill(slides: list, brief: dict, info: dict, posting: dict | None, figout: str, company: str) -> dict:
    """The words the documents already hold, slide by slide (no model): the cover, the agenda's frame, the about me, the
    strengths, the posting against the talk, the story from the resume's selected project, why, and the end. Page references are
    slide keys here; deck_input turns them into numbers. Returns the talk's parts."""
    W, view = WORDS[brief["lang"]], info["view"]  # the language's words and the profile
    P, S = view.get("person") or {}, view.get("summary") or {}  # the person and the summary
    shown = [s for s in slides if s["kind"] == "page"]  # the portfolio pages the talk shows
    shown_info = [{**next(x for x in info["slides"] if x["n"] == s["n"]), "key": s["key"]} for s in shown]  # with their words, for matching
    keys_for = lambda pid, title: [x["key"] for x in shown_info if x in page_of_project(pid, title, shown_info)]  # noqa: E731  a project's pages in the talk
    parts = []  # the talk's parts
    for i, t in enumerate(brief["topics"]):
        mine = [s for s in slides if s["part"] == i and s["kind"] not in ("cover", "agenda", "end", "chapter")]  # the part's own slides
        both = t["kinds"][:2] == ["motivation", "plan"]  # why and the plan in one part
        parts.append({"no": f"{i + 1:02d}", "title": t["title"], "short": W["both"] if both else W["short"][t["kinds"][0]], "en": W["en"][t["kinds"][0]] + (" & PLAN" if both else ""),
                      "minutes": round(t["minutes"]), "icon": PART_ICON[t["kinds"][0]], "what": "", "core": "", "kinds": t["kinds"], "keys": [s["key"] for s in mine]})
    lights = [x for x in (S.get("highlights") or []) if isinstance(x, dict)]  # the resume's selected projects
    for s in slides:
        k = s["kind"]
        if k == "cover":  # the poster: who, the role line, the headline and the four facts of the day
            fmt = " ".join(x for x in (brief["format"], brief["where"]) if x)  # "Presentation + Q&A, Google Meet"
            s.update(top=W["top"].format(company=company) if company else "", name=P.get("name", ""), name2=P.get("name_en_ko") or P.get("name_en", ""),
                     tag=" / ".join(x.strip() for x in str(P.get("tagline") or "").split("\n") if x.strip()), headline=brief["headline"] or S.get("headline", ""),
                     items=[x for x in ([W["when"], brief["when"], "calendar"], [W["format"], fmt, "monitor"],
                                        [W["length"], "", "timer"], [W["structure"], ", ".join(p["short"] for p in parts), "list"]) if x[1] != None and (x[1] or x[0] == W["length"])])
        elif k == "agenda":
            s.update(title=W["agenda"], lede=(W["agenda_lede"].format(n=len(parts), m=brief["minutes"]) if len(parts) > 1 else W["agenda_one"].format(m=brief["minutes"])),
                     messagesTitle=W["messages"])
        elif k == "chapter":  # the part's request, length and flow; its slides
            p = parts[s["part"]]
            kinds = p["kinds"]
            s.update(meta=[[W["request"], p["title"]], [W["length"], ""]] + ([[W["flow"], W["time_order"]]] if "experience" in kinds and brief["order"] == "time" else []),
                     lead="", noteLabel=W["note"], keys=[], name=p["title"])
        elif k == "about":  # the resume's overview, career, education and skills
            roles = [r for r in view.get("roles") or [] if r.get("org")]
            s.update(title=W["about"], sub=W["about_sub"], lede=one_line(S.get("intro", "")), careerTitle=W["career"], total=view.get("total", ""),
                     career=[{"org": r.get("short") or r.get("org"), "place": r.get("place", ""), "period": r.get("period", ""), "dept": r.get("dept", ""),
                              "role": r.get("title", ""), "tenure": r.get("tenure", ""), "months": r.get("months", 0), "tile": tile_path(figout, r.get("logoId"))} for r in roles[:6]],
                     overviewTitle=W["overview"], educationTitle=W["education"], education=[{"school": e.get("school", ""), "major": e.get("major", ""), "degree": e.get("degree", ""),
                                                                 "period": e.get("period", ""), "tile": tile_path(figout, e.get("logoId"))} for e in (view.get("education") or [])[:3]],
                     cards=[{"icon": next((ic for pat, ic in OVERVIEW_ICON if re.search(pat, a, re.I)), "circle-dot"), "title": a, "text": b} for a, b in plain_pairs(S.get("cards"))[:4]],
                     skillsTitle=W["skills"], skills=[[g.get("category", ""), short(", ".join(g.get("items") or []), 80)] for g in (view.get("skills") or [])[:5] if g.get("items")])
        elif k == "strengths":  # the edition's strengths, each with the pages that show it
            pil = []
            for j, c in enumerate((view.get("competencies") or [])[:3]):
                ev = c.get("evidence") or []  # project ids or titles
                items = []
                for e in ev[:4]:
                    ks = keys_for(str(e), str(e))  # its pages in the talk
                    t = next((x["title"] for x in shown if x["key"] in ks), "")
                    if t and not any(it["title"] == t for it in items):
                        items.append({"title": t, "text": "", "keys": ks})
                for x in ([] if items else rank(c.get("name", "") + " " + c.get("text", ""), shown_info, 2)):  # a strength the ledger ties to no page: the pages that share its words
                    items.append({"title": base_title(x["title"]), "text": "", "keys": [x["key"]]})
                pil.append({"title": c.get("name", ""), "text": c.get("text", ""), "icon": PILLAR_ICON[j % len(PILLAR_ICON)], "items": items})
            s.update(title=W["strengths"], sub=W["strengths_sub"], pillars=pil)
        elif k in ("problem", "approach", "result"):  # the resume's selected project: its problem, what was done and what came of it
            story = next((x for x in lights if norm(x.get("title")) and any(norm(x["title"]) in norm(p["title"]) or norm(p["title"]) in norm(x["title"]) for p in shown if p["part"] == s["part"])), lights[0] if lights else None)
            rows = [r for r in (story or {}).get("rows", []) if isinstance(r, (list, tuple)) and len(r) >= 2]
            idx = {"problem": 0, "approach": 1, "result": 2}[k]
            if len(rows) > idx:
                s.update(title=W[k], sub=(story or {}).get("title", ""), lede=rows[idx][1], cards=[{"title": rows[idx][0], "text": rows[idx][1]}])
        elif k == "why":  # the motivation the documents hold, as they hold it: a talk, never the posting line by line
            mot = " ".join(str(view.get("motivation") or "").replace("==", "").split())
            s.update(title=W["why"], lede=one_line(mot), cards=[{"title": W["why"], "text": mot}] if mot else [])
        elif k in ("lessons", "plan"):  # the agent writes them; their titles are known
            s.update(title=W[k])
        elif k == "points":  # a topic of the person's own, titled as the interviewers asked
            s.update(title=brief["topics"][s["part"]]["title"])
        elif k == "end":  # thanks, and how to reach the person
            links = [[l[0], l[1], l[2] if len(l) > 2 else ""] for l in (P.get("links") or []) if isinstance(l, (list, tuple)) and len(l) >= 2][:2]
            s.update(title=W["end"], tag=W["end_tag"], top=P.get("name", ""), right="Q&A",
                     contacts=[x for x in ([W["phone"], P.get("phone", ""), ""], [W["email"], P.get("email", ""), "mailto:" + P.get("email", "")]) if x[1]] + links)
    return {"parts": parts, "messages": []}


def has_content(s: dict) -> bool:
    """Does a slide have anything to show? The cover, the agenda, the dividers, the portfolio's pages and the end always do."""
    k = s["kind"]
    if k in ("cover", "agenda", "chapter", "page", "end"):
        return True
    if k == "about":
        return bool(s.get("career") or s.get("lede"))
    if k == "strengths":
        return bool(s.get("pillars"))
    if k == "lessons":
        return bool(s.get("items"))
    if k in ("problem", "approach", "result", "story", "points"):
        return bool(s.get("cards") or s.get("lede"))
    if k == "why":
        return bool(s.get("lede") or s.get("cards"))
    if k == "plan":
        return bool(s.get("phases"))
    return False


# ───────── the script without a model ─────────

def rule_script(s: dict, lang: str) -> dict:
    """A slide's words as a first draft of what to say: its title, its lede and its cards. Marked so the page says it is a draft."""
    lines = []
    for v in (s.get("lede"), *(c.get("text") for c in s.get("cards") or []), *(p.get("text") for p in s.get("pillars") or [])):
        v = " ".join(str(v or "").replace("==", "").replace("**", "").split())
        if v and v not in lines:
            lines.append(v)
    title = s.get("title") or s.get("name") or ""
    return {"lines": ([title] if title and not lines else []) + lines[:4], "cue": "", "short": "", "questions": [], "rule": True}


# ───────── checks ─────────

def spoken(text: str, lang: str) -> int:
    """How long a text is to say: Korean characters without spaces, or English words."""
    t = re.sub(r"\{\{[\w-]+\}\}", "", str(text or "")).replace("==", "").replace("**", "")
    return len(t.split()) if lang == "en" else len(re.sub(r"\s", "", t))


def pace_checks(slides: list, lang: str, pace=None) -> list:
    """Slides whose words are too few or too many for their time, at a pace a person can speak while pointing at the slide."""
    lo, hi = pace or PACE[lang]
    out = []
    for s in slides:
        sc = s.get("script") or {}
        if sc.get("rule") or s.get("seconds", 0) < 60:  # a draft from the slide, or a short slide, is not measured
            continue
        n = sum(spoken(l, lang) for l in sc.get("lines") or [])
        per = n / (s["seconds"] / 60)
        if not lo <= per <= hi:
            out.append({"page": s.get("page"), "key": s["key"], "pace": round(per), "words": n, "seconds": s["seconds"], "lo": lo, "hi": hi})
    return out


# ───────── the deck ─────────

PAGE_FIELDS = ("keys",)  # where a slide's content names other slides by key


def numbered(v, pages: dict):
    """A slide's content with every {{key}} mark and every 'keys' list turned into the talk's page numbers ('pages')."""
    if isinstance(v, dict):
        out = {k: numbered(x, pages) for k, x in v.items() if k != "keys"}
        if "keys" in v:  # the pages an item points at
            out["pages"] = keys_to_pages(v["keys"], pages)
        return out
    if isinstance(v, list):
        return [numbered(x, pages) for x in v]
    if isinstance(v, str):
        return resolve(v, pages)
    return v


def deck_input(slides: list, talk: dict, brief: dict, company: str) -> dict:
    """What src/talk_slides.js draws: the slides with page numbers, the parts with their pages, the messages, the theme."""
    pages = {s["key"]: s["page"] for s in slides}  # key -> page
    W = WORDS[brief["lang"]]
    parts = []
    for i, p in enumerate(talk["parts"]):
        mine = [s for s in slides if s["part"] == i and s["kind"] not in ("cover", "agenda", "end")]  # the part's slides, its divider first
        first = next((s["page"] for s in mine if s["kind"] == "chapter"), mine[0]["page"] if mine else 0)
        listed = [s for s in mine if s["kind"] != "chapter"]
        parts.append({**{k: v for k, v in p.items() if k not in ("keys", "kinds")}, "first": first,
                      "slides": [[s["page"], s.get("title") or s.get("name") or ""] for s in listed]})
    out = []
    for s in slides:
        x = numbered({k: v for k, v in s.items() if k != "script" and not k.startswith("_")}, pages)  # the content, page marks resolved
        if s["kind"] == "chapter":  # the part's own slides, with their pages and lines
            p = parts[s["part"]]
            listed = [y for y in slides if y["part"] == s["part"] and y["kind"] not in ("chapter", "cover", "agenda", "end")]
            x["rows"] = [{"title": y.get("title") or "", "tag": y.get("tag") or y.get("sub") or "", "note": y.get("note", ""),
                          "period": y.get("period", ""), "page": y["page"]} for y in listed]
            x["meta"] = [[a, b or W["part_len"].format(n=len(listed), m=p["minutes"])] for a, b in s.get("meta", [])]
        if s["kind"] == "cover":  # the length and the parts kept are known only now
            x["items"] = [[a, (", ".join(p["short"] for p in parts) if a == W["structure"] else b) or W["length_v"].format(n=len(slides), m=brief["minutes"]), ic]
                          for a, b, ic in s.get("items", [])]
        out.append(x)
    title = " ".join(x for x in (talk.get("person"), company, W["top"].format(company="").strip(" ,")) if x)  # the PDF's title
    return {"lang": brief["lang"], "title": title, "theme": brief["theme"], "parts": parts, "swaps": brief["swaps"],
            "messages": numbered(talk.get("messages") or [], pages), "slides": out}


def draw(inp: dict, ed: dict, env: dict, name: str) -> dict:
    """Write the deck's page with src/talk_slides.js and print it with the renderer in use: {html, pdf, probe} in output/."""
    import resume as R  # noqa: E402  the renderer's helpers
    inputs = ROOT / "output" / "_inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    f = inputs / f"{name}.talk.json"  # inside the repository, where the container finds it
    f.write_text(json.dumps(inp, ensure_ascii=False), encoding="utf-8")
    page, pdf, probe = ROOT / "output" / f"{name}.html", ROOT / "output" / f"{name}.pdf", ROOT / "output" / f"{name}.probe.json"
    for x in (page, pdf, probe):  # an old file must not pass for a new one
        x.unlink(missing_ok=True)
    prof, jf = R.rel(str(ed["profile"])), R.rel(str(ed["job"])) if ed["job"] else ""
    if R.renderer() == "html":  # the PC's own browser prints the page
        missing = R.html_missing()
        if missing:
            raise TalkError(R.t("need_html", what=R.missing_words(missing)))
        R.run_steps([[R.node(), "src/talk_slides.js", R.rel(str(f)), prof, jf, name]], R.html_env(env), "deck_failed")
        import probe_extract  # noqa: E402  the deck's own measurement, read out of the DOM
        H = R.html_renderer()
        try:
            H.html_to_pdf(page, pdf)
            probe.write_text(probe_extract.extract(H.dump_dom(page)), encoding="utf-8")
        except (RuntimeError, ValueError) as e:
            raise TalkError(R.t("deck_failed") + "\n" + str(e))
    else:  # the container prints it, as it prints the portfolio
        script = (R.FONTS + 'node src/talk_slides.js "$1" "$2" "$3" "$4" >/dev/null && '
                  + R.CHROME + '--user-data-dir=/tmp/chr --no-pdf-header-footer --print-to-pdf="output/$4.pdf" "output/$4.html" 2>/dev/null && '
                  + R.CHROME + '--user-data-dir=/tmp/chr2 --window-size=1400,900 --dump-dom "output/$4.html" 2>/dev/null > "output/$4.dom" && '
                  + 'python3 src/probe_extract.py "output/$4.dom" "output/$4.probe.json"; rc=$?; rm -f "output/$4.dom"; exit $rc')
        r = R.sh(["bash", "-c", script, "_", R.rel(str(f)), prof, jf, name], env)
        if r.returncode != 0 or not pdf.exists():
            raise TalkError(R.t("deck_failed") + "\n" + r.stdout[-1500:] + r.stderr[-1500:])
    return {"html": page, "pdf": pdf, "probe": probe}


def probe_issues(probe: pathlib.Path) -> list:
    """The deck's layout defects as the browser measured them: [{page, issues}]."""
    try:
        d = json.loads(probe.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [{"page": 0, "issues": ["no measurement"]}]
    return [{"page": s.get("n"), "issues": [str(i)[:200] for i in s.get("issues") or []]} for s in d.get("slides", []) if s.get("issues")]


def thumbs(pdf: pathlib.Path, folder: pathlib.Path) -> list:
    """A small picture of every slide, for the script: folder/slide-NN.png."""
    import pdftools  # noqa: E402  PDFium or Poppler, whichever is here
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        return [pathlib.Path(p) for p in pdftools.render_png(pdf, folder / "slide", dpi=48)]
    except Exception:  # noqa: BLE001  the script prints without pictures rather than not at all
        return []


# ───────── the whole run ─────────

def prune_parts(slides: list, talk: dict, brief: dict, record: dict) -> list:
    """Parts with no slide of their own (a topic only the agent can write, made without it) leave the talk: their dividers go,
    the rest are numbered again, their minutes go to the other parts, and the record names each with its reason."""
    content = {s["part"] for s in slides if s["kind"] not in ("cover", "agenda", "end", "chapter")}  # parts with something to show
    dead = [i for i in range(len(brief["topics"])) if i not in content]
    if not dead:
        return slides
    alive = [i for i in range(len(brief["topics"])) if i in content]
    if not alive:  # nothing at all to show
        raise TalkError("nothing to show: these topics are written by the agent" if brief["lang"] == "en" else "보여 줄 장이 없습니다. 이 요청 항목은 에이전트가 씁니다")
    for i in dead:
        record.setdefault("dropped", []).append({"at": f"part.{i + 1}", "text": brief["topics"][i]["title"],
                                                 "why": ["no slide: the agent writes this topic" if brief["lang"] == "en" else "장 없음: 이 항목은 에이전트가 씁니다"]})
    remap = {old: new for new, old in enumerate(alive)}
    out = []
    for s in slides:
        if s["kind"] == "chapter" and s["part"] in dead:  # its divider goes with it
            continue
        s["part"] = remap.get(s["part"], 0 if s["kind"] in ("cover", "agenda") else len(alive) - 1)
        out.append(s)
    talk["parts"] = [dict(talk["parts"][old], no=f"{new + 1:02d}") for new, old in enumerate(alive)]
    kept = [brief["topics"][old] for old in alive]
    total = sum(t["minutes"] for t in kept) or 1
    brief["topics"] = [dict(t, minutes=round(t["minutes"] * brief["minutes"] / total, 1)) for t in kept]  # the talk keeps its length
    for p, t in zip(talk["parts"], brief["topics"]):
        p["minutes"] = round(t["minutes"])
    return out


def llm_setting() -> str:
    """The agent the settings name (OFFEROWL_LLM), '' when none is named: then llm.run finds the signed-in one."""
    import llm  # noqa: E402
    return str(llm.setting("LLM", "") or "")


def one_story(slides: list, lang: str) -> list:
    """Without the agent the story's three slides would hold one card each: they become one slide with the three cards."""
    parts = [s for s in slides if s["kind"] in ("problem", "approach", "result") and has_content(s)]
    if not parts:
        return slides
    first = parts[0]
    cards = [c for s in parts for c in s.get("cards", [])]
    merged = {"key": "story", "kind": "story", "part": first["part"], "title": ", ".join(dict.fromkeys(str(c.get("title") or "") for c in cards if c.get("title"))) or WORDS[lang]["problem"],
              "sub": first.get("sub", ""), "lede": "", "cards": cards}
    out = []
    for s in slides:
        if s["kind"] in ("problem", "approach", "result"):
            if s is first:
                out.append(merged)
            continue
        out.append(s)
    return out


def company_of(brief: dict, posting: dict | None, job) -> str:
    """The company's name for the cover: the brief's, the kit's in the talk's language, the posting's, else none."""
    kit = job.kit.get("company") if job is not None else None  # {"ko": ..., "en": ...} or a name
    kit = kit.get(brief["lang"]) or kit.get("ko") or kit.get("en") if isinstance(kit, dict) else kit
    return brief.get("company") or (str(kit).strip() if kit else "") or (posting or {}).get("company") or ""


def make(job, *, lang: str | None = None, backend: str | None = None, out=None, pdf: bool = True, log=print) -> dict:
    """Plan, write, draw and check the talk; everything goes to <out>/talk/. Returns the summary the panel and the command show."""
    import cover as C  # noqa: E402
    from interview import talk_page  # noqa: E402  the script's page
    raw = read_brief(job)  # the person's brief, or none
    lang = lang or (raw.get("lang") if raw.get("lang") in ("ko", "en") else None) or ("en" if (job.dir / "resume" / "en").is_dir() and not (job.dir / "resume" / "ko").is_dir() else "ko")
    brief = normalize(raw, lang)  # every default filled
    folder = job.out_dir(out) / "talk"  # where everything goes
    folder.mkdir(parents=True, exist_ok=True)
    ed = edition(job, lang)  # the profile and settings the job's documents come from
    if ed["job"] is None:  # no edition in this language: the portfolio and the profile are read in the talk's language
        jf = ROOT / "output" / "_inputs" / ("talk_" + hashlib.sha1(str(job.dir.resolve()).encode()).hexdigest()[:8] + f"_{lang}.job.json")
        jf.parent.mkdir(parents=True, exist_ok=True)
        jf.write_text(json.dumps({"lang": lang}), encoding="utf-8")
        ed = {**ed, "job": jf}
    env = stage_source(job, dict(os.environ))  # the person's own slides, when they keep them
    log(f"talk: edition {'made' if ed['made'] else 'from the profile'}, deck source {'own' if env.get('OFFEROWL_DECK_SOURCE') else 'drawn from the profile'}")
    figout = figures(ed, env, lang)  # the tiles the slides show
    info = portfolio_info(ed, env)  # what the portfolio holds
    post_path = job.in_job(job.kit.get("posting", "posting.md"))  # the posting
    posting = C.parse_posting(post_path.read_text(encoding="utf-8")) if post_path and post_path.is_file() else None
    company = company_of(brief, posting, job)
    slides = plan(brief, info, posting)  # the slides in order
    talk = fill(slides, brief, info, posting, figout, company)  # what the documents already say
    talk["person"] = (info["view"].get("person") or {}).get("name", "")
    record = {"calls": 0, "backend": "none", "dropped": []}  # what the model wrote and what the checks stopped
    writer = None  # the agent's run, when there is one
    if (backend or llm_setting()).lower() != "none":  # the model writes the rest from the evidence
        from interview import talk_write  # noqa: E402
        try:
            writer = talk_write.Writer(job=job, brief=brief, info=info, posting=posting, slides=slides, talk=talk, backend=backend, log=log)
            talk_write.content(writer, slides, talk)  # the slides' own words
        except talk_write.Stopped as e:  # no backend, or it stopped: the talk is made from the documents alone
            log(f"talk: the agent stopped ({e}); the talk keeps the documents' own words")
            record["stopped"] = str(e)
            writer = None
    if writer is None:  # the documents alone tell the story in one slide
        slides = one_story(slides, lang)
    slides = [s for s in slides if has_content(s)]  # a slide with nothing to show is left out (no lessons without the agent)
    slides = prune_parts(slides, talk, brief, record)  # a part left with its divider alone leaves the talk, and the record says why
    timing(slides, brief)  # seconds per slide
    pages = number(slides)  # page numbers
    if writer is not None:  # what to say over each slide, now that every slide's words and time are known
        from interview import talk_write  # noqa: E402
        try:
            talk_write.script(writer, slides)
        except talk_write.Stopped as e:  # the script keeps the slides' own words
            log(f"talk: the agent stopped before the script ({e})")
            record["stopped"] = str(e)
        record.update(talk_write.record(writer))
    for s in slides:  # what to say over each slide
        if not s.get("script"):
            s["script"] = rule_script(s, lang)
        sc = s["script"]
        for k in ("lines", "cue", "short"):
            sc[k] = [resolve(x, pages) for x in sc.get(k) or []] if k == "lines" else resolve(sc.get(k, ""), pages)
        sc["questions"] = [{"q": resolve(q.get("q", ""), pages), "a": resolve(q.get("a", ""), pages)} for q in sc.get("questions") or []]
    name = "talk_" + hashlib.sha1(str(job.dir.resolve()).encode()).hexdigest()[:8] + "_" + lang  # the page's name in output/
    inp = deck_input(slides, talk, brief, company)  # what the deck draws
    made = draw(inp, ed, env, name)  # the page, and its PDF when printing
    issues = probe_issues(made["probe"])  # the deck's layout, as the browser measured it
    for x in ("html", "pdf", "probe"):  # into the talk's folder
        shutil.copyfile(made[x], folder / {"html": "deck.html", "pdf": "deck.pdf", "probe": "deck.probe.json"}[x])
    pics = thumbs(folder / "deck.pdf", folder / "thumbs")  # the slides' pictures for the script
    pace = pace_checks(slides, lang)  # words against time
    total = sum(s["seconds"] for s in slides)
    result = {"brief": brief, "company": company, "edition": {"made": ed["made"], "own": bool(info.get("own"))}, "slides": slides, "parts": talk["parts"],
              "messages": inp["messages"], "seconds": total, "checks": {"layout": issues, "pace": pace, "dropped": record.get("dropped", [])},
              "record": {k: v for k, v in record.items() if k != "dropped"}, "pictures": [p.name for p in pics]}
    (folder / "talk.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")  # everything, for the page and the panel
    html = talk_page.script_html(result, folder)  # the script
    (folder / "script.html").write_text(html, encoding="utf-8")
    if pdf:  # printed for the day
        talk_page.print_script(folder / "script.html", folder / "script.pdf", env)
    for x in (made["html"], made["pdf"], made["probe"]):  # the engine's output folder keeps no copy
        x.unlink(missing_ok=True)
    summary = {"folder": str(folder), "slides": len(slides), "minutes": round(total / 60, 1), "target": brief["minutes"],
               "layout": sum(len(x["issues"]) for x in issues), "pace": len(pace), "dropped": len(record.get("dropped", [])), "calls": record.get("calls", 0)}
    log("talk: " + ", ".join(f"{k} {v}" for k, v in summary.items() if k != "folder"))
    return summary
