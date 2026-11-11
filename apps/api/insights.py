"""Offerowl's API, the numbers of the Insights view. Three questions, each counted from the files as they are now:
where the applications stand (stages, results, the weeks they moved in, how far each got), what the evidence holds
(facts by kind and by company, the spans of the career), and where the postings ask for more than the evidence shows
(every requirement line of every posting, as the fit rated it, gathered by area). Read only: nothing here writes, so
the view and GET /api/v1/insights say the same at every moment, and an agent reads what the person sees."""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

# A result's own words, read for what happened. The person writes them freely ("탈락", "closed after the second
# round"), so the first kind whose words appear names it; a rejection is read before an offer, because
# "서류 합격 뒤 탈락" passed one round and still ended in a rejection.
RESULT_KINDS = (("rejected", re.compile(r"탈락|불합격|미합격|불합|합격\s*(?:하지\s*)?(?:못|안\s*됨|아님)|오퍼\s*(?:없|무산|취소)|reject|declin|not selected|no offer|"
                                       r"not (?:moving|proceed)|hired (?:someone|another)", re.I)),
                ("closed", re.compile(r"종료|정리|마감|철회|취소|포기|withdr|closed|ended|cancel", re.I)),
                ("offer", re.compile(r"합격|오퍼|입사|offer|accepted|hired", re.I)))

# The areas a requirement line is sorted into, in the order a tie is settled. Each lists the words a posting uses for
# it in the two languages a posting is read in; a Latin word is matched at a word's start ("monitor" answers to
# "monitoring"), and a short one as a whole word ("ai", "sql"). The person's own skill groups add their tools to the
# area their group's name belongs to ("Cluster/HPC" brings Slurm and xCAT to GPU & HPC), so a posting that names a
# tool the person listed lands where the person would put it.
AREAS = (("Linux & systems", ("linux", "kernel", "operating system", "unix", "shell", "bash", "systemd", "rhel", "ubuntu", "리눅스", "커널", "운영체제")),
         ("Cloud & containers", ("cloud", "aws", "gcp", "azure", "kubernetes", "k8s", "container", "docker", "openshift", "virtualiz", "terraform",
                                 "infrastructure as code", "iac", "클라우드", "쿠버네티스", "컨테이너", "가상화")),
         ("GPU & HPC", ("gpu", "hpc", "cuda", "rocm", "accelerator", "nvidia", "amd", "npu", "silicon", "chip", "cluster", "slurm", "supercomput",
                        "data center", "datacenter", "가속기", "클러스터", "슈퍼컴퓨터", "반도체", "데이터센터")),
         ("Networking", ("network", "rdma", "infiniband", "roce", "tcp", "protocol", "load balanc", "네트워크", "통신")),
         ("Storage & databases", ("storage", "file system", "filesystem", "lustre", "ceph", "nfs", "database", "sql", "postgres", "mysql", "redis",
                                  "스토리지", "파일 시스템", "데이터베이스")),
         ("Automation & CI/CD", ("automat", "ci/cd", "pipeline", "ansible", "gitops", "argocd", "jenkins", "helm", "deploy", "rollout", "release",
                                 "자동화", "배포", "파이프라인")),
         ("Observability & reliability", ("monitor", "observab", "prometheus", "grafana", "alert", "incident", "on-call", "after hours", "sre", "reliab",
                                          "uptime", "availability", "troubleshoot", "failure", "recovery", "capacity", "모니터링", "장애", "안정성", "가용성", "관측")),
         ("ML & LLM", ("machine learning", "ml", "llm", "~(?<!business )(?<!operating )model", "inference", "training", "pytorch", "tensorflow", "mlops", "rag", "genai", "generative", "ai",
                       "~(?<!비즈니스 )(?<!사업 )모델", "추론", "~(?:모델|머신러닝|딥러닝|분산)\\s*학습|학습\\s*(?:데이터|파이프라인|클러스터|인프라|작업)", "머신러닝", "딥러닝", "인공지능")),
         ("Data & analytics", ("~(?<![a-z0-9])data(?!\\s?cent)", "analytic", "analysis", "statistic", "kpi", "a/b", "experiment", "insight", "~데이터(?!\\s?센터)", "분석", "통계", "실험", "지표")),
         ("Software engineering", ("software", "code", "coding", "program", "api", "backend", "frontend", "full-stack", "python", "golang", "java",
                                   "typescript", "schema", "개발", "코드", "소프트웨어", "프로그래밍", "백엔드", "프론트엔드", "서버")),
         ("Security", ("security", "access control", "iam", "compliance", "encrypt", "보안", "인증", "권한")),
         ("Communication", ("english", "communicat", "written", "verbal", "presentation", "document", "영어", "커뮤니케이션", "소통", "발표", "문서")),
         ("Customers & business", ("customer", "client", "stakeholder", "pre-sales", "presales", "sales", "partner", "business", "billing", "payment",
                                   "고객", "영업", "파트너", "비즈니스", "사업")),
         ("Leadership & ownership", ("lead", "mentor", "ownership", "result driven", "~(?<![a-z])driv(?:e|en|ing)(?![a-z])", "리드", "리더", "주도", "멘토")),
         ("Experience & education", ("years", "track record", "proven", "degree", "bachelor", "master", "phd", "certificat",
                                     "경력", "년 이상", "학위", "학사", "석사", "박사", "전공", "자격증")))

# A posting's lines about the hiring itself (how to apply, the rounds, a reference check): not a requirement, so they are
# left out of every area and counted apart, as lines no area was found for are.
PROCESS = re.compile(r"접수|전형|채용|평판|지원서|서류|면접|보훈|장애인|screening|reference check|(?<![a-z])interview(?![a-z])|"
                     r"talent acquisition|how to apply|application process|hiring process|^\s*\d+\s*min\b", re.I)   # "45min culture interview" is a round, not a skill

SOFT = {"Communication", "Customers & business", "Leadership & ownership", "Experience & education"}   # the areas of any trade, drawn apart from the craft's own

# Words of a tool's name too common to say which area a line is about ("Apache Impala" is about Impala, "Envoy
# Gateway" about Envoy): a tool's whole name still matches, only these words alone do not.
STOP = {"apache", "scale", "stack", "gateway", "native", "actions", "archive", "store", "open", "with", "and", "cloud", "data", "storage"}

WEEKS = 10                                                                          # how many weeks the activity columns cover, this one last
EVENT_KINDS = ("submitted", "interview", "result")                                  # the dates a week counts: what moved, not when a card was made


def result_kind(stage: str, words: str) -> str:
    """What an application's end was: offer, rejected, closed, none (ended with no words for it) or open (not ended)."""
    if stage != "result":                                                           # still going
        return "open"
    for kind, rx in RESULT_KINDS:                                                   # the first whose words appear
        if rx.search(words or ""):
            return kind
    return "none"                                                                   # ended, and the person wrote no result


def days_of(job: dict) -> dict:
    """The days that count for a job (tracker.stage_days): kept on the panel's jobs as `days`, worked out otherwise."""
    from .tracker import stage_days                                                 # none left from a move taken back
    return job.get("days") if isinstance(job.get("days"), dict) else stage_days(job)


def reached(job: dict) -> dict:
    """How far one application got, as its dates and stage say: submitted, interviewed, offered."""
    d, st = days_of(job), job.get("stage")                                          # the days that count by stage, and where it is
    end = result_kind(st, job.get("result") or "")                                  # how it ended, if it did
    interview = bool(d.get("interview")) or st == "interview" or end == "offer" or bool(job.get("rounds"))   # an interview date, the card there, a round recorded, or an offer that followed one
    submitted = interview or bool(d.get("submitted")) or st == "submitted" or end in ("rejected", "offer")   # a rejection or an offer answers a submission
    return {"submitted": submitted, "interview": interview, "offer": end == "offer"}


def plain_org(org) -> str:
    """A company's name as one string: a fact can carry {'ko': .., 'en': ..}, and the facts view prints it as text."""
    if isinstance(org, dict):                                                       # both languages
        return str(org.get("ko") or org.get("en") or next(iter(org.values()), ""))  # the Korean name, as the profile is written first
    s = str(org or "").strip()                                                      # a plain name
    if s.startswith("{"):                                                           # the dict, printed
        try:
            return plain_org(ast.literal_eval(s))                                   # read back; literal_eval runs nothing
        except (ValueError, SyntaxError):                                           # not a dict after all
            return s
    return s


TOKEN = re.compile(r"(?<!\d)(\d{4}|\d{2})(?:\s*[.\-/년]\s*(0?[1-9]|1[0-2])(?!\d))?(?!\d)")   # a year, and its month when one follows it
OPEN = re.compile(r"(?:~|–|—|-|\bto\b)\s*(?:현재|재직\s*중|present|now|current|today)?\s*$", re.I)   # a range that runs on: nothing, or "now", after its mark


def span(period: str, today: date) -> tuple[date, date, bool] | None:
    """(start, end, ongoing) of a period written "2026.04 ~ 2026.08", "26.04 ~", "2019.07 ~ 현재", "2016-2019", "99.03 ~ 03.02";
    None when it names no year. A year alone runs January to December; a period runs on only when it says so."""
    found = [(m.group(1), m.group(2)) for m in TOKEN.finditer(period or "")]          # its years, with their months
    if not found:                                                                   # "three years": not a span to draw
        return None
    def year(y: str) -> int:                                                        # a two-digit year: this century's, unless that is in the future
        if len(y) == 4:
            return int(y)
        v = 2000 + int(y)
        return v - 100 if v > today.year else v
    def at(tok, first: bool) -> date:                                               # a year's first or last month when no month is given
        y, m = tok
        return date(year(y), int(m) if m else (1 if first else 12), 1)
    start = at(found[0], True)
    if len(found) > 1:                                                              # it says where it ended
        end = at(found[1], False)
        return (start, end, False) if end >= start else (start, start, False)
    if OPEN.search(period or ""):                                                   # "2023.03 ~", "2019.07 ~ 현재": until now
        return start, date(today.year, today.month, 1), True
    return start, at(found[0], False) if not found[0][1] else start, False          # one month, or one year


def months(a: date, b: date) -> int:
    """Whole months from a to b, the month of b counted (2026.04 ~ 2026.08 is five months, as a resume counts it)."""
    return max(0, (b.year - a.year) * 12 + b.month - a.month + 1)


DICT_TEXT = re.compile(r"\{'ko':\s*'([^']*)'(?:,\s*'en':\s*'[^']*')?\}")      # a {'ko': .., 'en': ..} the facts view printed as text


def plain_text(v) -> str:
    """A fact's words as one string: a two-language value printed as a dict reads as its Korean words."""
    if isinstance(v, dict):                                                         # both languages
        return str(v.get("ko") or v.get("en") or "")
    return re.sub(r"\s+", " ", DICT_TEXT.sub(lambda m: m.group(1), str(v or ""))).strip()


def word_rx(word: str) -> re.Pattern:
    """A matcher for one keyword in a lowercased line. A Latin word starts at a word's start ("go" is not in "google")
    and, when it is short, ends at one too; Hangul has no spaces to lean on and is matched where it stands."""
    if word.startswith("~"):                                                        # a word written as its own pattern: "data" but not "data center"
        return re.compile(word[1:])
    w = re.escape(word)                                                             # C/C++ and the like are literal
    if re.search(r"[a-z0-9]", word):                                                # a Latin name
        tail = r"(?![a-z0-9])" if len(word) <= 3 else ""                            # "go", "sql", "aws": whole words only
        return re.compile(r"(?<![a-z0-9])" + w + tail)
    return re.compile(w)                                                            # Hangul: anywhere


def group_words(title: str, items: list[str]) -> tuple[list[str], list[str]]:
    """(name words, tool words) of a skill group: its name's parts ("Cluster/HPC" is cluster and hpc), and every tool in
    it with a long tool name's own words ("NVIDIA HGX" also answers to "nvidia"), less the common words of STOP."""
    name = [p.strip().lower() for p in re.split(r"[/&]", str(title)) if len(p.strip()) >= 2]   # the name's parts, whole
    tools: list[str] = []                                                           # in order, once each
    for piece in items:                                                             # every tool
        for part in re.split(r"[/(),]", str(piece)):                                # "IBM Storage Scale(GPFS)", "NCCL/RCCL"
            part = part.strip().lower()                                             # matched lowercased
            cands = [part] + [w for w in part.split() if len(w) >= 4] if " " in part else [part]
            for w in cands:                                                         # the whole name, then its words
                if len(w) >= 2 and w not in STOP and w not in tools:
                    tools.append(w)
    return name, tools


def skill_groups(rows: list[dict]) -> list[tuple[str, list[str]]]:
    """[(name, tools)] of the profile's skill groups, in the profile's order, each name once (the Korean and English
    profiles list the same groups; the second adds only the groups the first lacks)."""
    groups: dict[str, list[str]] = {}                                               # name -> its tools
    for r in rows:                                                                  # the facts
        if r.get("kind") != "skill" or r.get("status") != "accepted":               # kept skill groups only
            continue
        name = str(r.get("title") or "").strip()                                    # "Languages", "Cluster/HPC"
        items = [x.strip() for x in re.split(r",|·|\n", str(r.get("statement") or "")) if x.strip()]   # "Python, Go, C/C++"
        if name and name not in groups:                                             # the first time it is named
            groups[name] = items
    return list(groups.items())


class Areas:
    """Sorts a line of text into one area: the area with the most of its words in it, a tie settled by AREAS' order.
    The same sorting reads the postings' lines and the facts, so both sides of the persona map are counted by the same
    words. A line that names only the hiring itself is "process"; one that names no area is "Other"."""

    def __init__(self, groups: list[tuple[str, list[str]]]):
        words = {n: list(ws) for n, ws in AREAS}                                    # the general words of each area
        rx = {n: [word_rx(w) for w in ws] for n, ws in AREAS}                       # matchers for a group's name
        for title, items in groups:                                                 # the person's groups: their tools join the area of their name
            name, tools = group_words(title, items)
            low = " ".join(name)                                                    # "cluster hpc"
            home = next((n for n, _ in AREAS if any(r.search(low) for r in rx[n])), None)   # the first area its name belongs to
            if home:                                                                # a group of no area ("Collaboration") adds nothing
                words[home] += [w for w in tools if w not in words[home]]
        self.areas = [(n, [word_rx(w) for w in words[n]]) for n, _ in AREAS]        # in AREAS' order

    def hits(self, text: str) -> list[tuple[str, int]]:
        """[(area, words found)] of every area the text names, most words first, AREAS' order on a tie."""
        low = (text or "").lower()                                                  # matched lowercased
        found = [(n, sum(1 for r in rxs if r.search(low))) for n, rxs in self.areas]
        return sorted((f for f in found if f[1]), key=lambda f: -f[1])              # sorted() is stable: a tie keeps the order

    def of(self, text: str) -> str:
        """The one area a requirement line is about, "process" for a line about the hiring itself, or "Other"."""
        if PROCESS.search(text or ""):                                              # the rounds, how to apply: read first, "장애인" is not an outage
            return "process"
        h = self.hits(text)                                                         # the areas it names
        return h[0][0] if h else "Other"


KIT_CACHE: dict[tuple, tuple] = {}                                                  # (job, kit files' times) -> coverage: the board takes seconds to read


def week_start(d: date) -> date:
    """The Monday of a date's week."""
    return d - timedelta(days=d.weekday())


def parse_day(s) -> date | None:
    """A 'YYYY-MM-DD' date, or None for anything else."""
    try:
        return date.fromisoformat(str(s)[:10])                                      # the stage dates are written this way
    except ValueError:
        return None


def summary(api, today: date | None = None) -> dict:
    """Every number the Insights view draws, from the jobs, their fits, the facts and the interview kits."""
    today = today or date.today()                                                   # what "this week" and "until now" mean
    jobs = api.jobs_view()                                                          # every application with its fit's summary (cached fits)
    rows = [{**r, **(r.get("edit") or {})} for r in api.facts.view()["rows"]]      # every fact with its state, as the person edited it
    kept = [r for r in rows if r.get("status") == "accepted"]                       # what the documents are made from

    # ---- where the applications stand
    stages = Counter(j.get("stage") for j in jobs)                                  # cards per column
    ends = Counter(result_kind(j.get("stage"), j.get("result") or "") for j in jobs if j.get("stage") == "result")   # how the ended ones ended
    far = [reached(j) for j in jobs]                                                # how far each got
    funnel = {"added": len(jobs), "submitted": sum(f["submitted"] for f in far),   # every step's count, each a subset of the one before
              "interview": sum(f["interview"] for f in far), "offer": sum(f["offer"] for f in far)}
    this_week = week_start(today)                                                   # the last column
    weeks = [this_week - timedelta(weeks=WEEKS - 1 - i) for i in range(WEEKS)]      # oldest first
    per_week = {w: Counter() for w in weeks}                                        # events per kind per week
    for j in jobs:                                                                  # every application
        for kind in EVENT_KINDS:                                                    # its moves
            d = parse_day(days_of(j).get(kind))                                     # when it made that move (a day left from a move taken back is none)
            if d and week_start(d) in per_week:                                     # inside the window
                per_week[week_start(d)][kind] += 1
    gaps_days = [(parse_day(days_of(j).get("interview")) - parse_day(days_of(j).get("submitted"))).days   # submission to interview
                 for j in jobs if parse_day(days_of(j).get("submitted")) and parse_day(days_of(j).get("interview"))]
    gaps_days = sorted(g for g in gaps_days if g >= 0)                              # a date typed later than the next one is no wait

    # ---- the fit of every posting, line by line
    groups = skill_groups(rows)                                                     # the person's own areas
    areas = Areas(groups)                                                           # the sorter
    by_area: dict[str, dict] = defaultdict(lambda: {"strong": 0, "weak": 0, "none": 0, "jobs": set(), "lines": []})
    fits = []                                                                       # one dot per posting with lines
    unsorted = Counter()                                                            # lines of no area, and lines about the hiring itself
    for j in jobs:                                                                  # every application
        f = api.fit(j["id"])                                                        # cached since jobs_view
        if not f.get("lines"):                                                      # no posting, or no profile: nothing was rated
            continue
        fits.append({"job": j["id"], "company": j.get("company") or j["id"], "role": j.get("role") or "", "stage": j.get("stage"),
                     "score": f["score"], "counts": f["counts"], "end": result_kind(j.get("stage"), j.get("result") or "")})
        for line in f["lines"]:                                                     # each requirement
            where = areas.of(line.get("text") or "")                                # its area
            if where in ("Other", "process"):                                       # no area to count it in
                unsorted[where] += 1
                continue
            a = by_area[where]
            rating = line.get("rating") if line.get("rating") in ("strong", "weak", "none") else "none"   # a line the fit could not rate is unmet
            a[rating] += 1
            a["jobs"].add(j["id"])                                                  # how many postings ask for the area
            if rating != "strong":                                                  # what to work on: the lines not met in full
                a["lines"].append({"text": (line.get("text") or "")[:200], "rating": rating, "kind": line.get("kind"), "job": j["id"],
                                   "company": j.get("company") or j["id"]})

    # ---- what the evidence holds, by the same areas
    supply = Counter()                                                              # facts per area
    for r in kept:                                                                  # every kept fact but the skill lists themselves
        if r.get("kind") == "skill":                                                # a list of tools says the area exists, not that it was done
            continue
        text = " ".join(str(r.get(k) or "") for k in ("title", "statement", "quote"))   # everything it says
        for name, _ in areas.hits(text):                                            # every area it backs, not only the first
            supply[name] += 1
    area_rows = []                                                                  # one row per area that a posting asks for or a fact backs
    for n, _ in AREAS:                                                              # in a fixed order, so an area keeps its place and its colour
        a = by_area.get(n)                                                          # the postings' side
        demand = (a["strong"] + a["weak"] + a["none"]) if a else 0                  # requirement lines about it
        if not demand and not supply.get(n):                                        # neither asked for nor backed
            continue
        lines = sorted((a or {}).get("lines", []), key=lambda l: (l["rating"] != "none", len(l["text"])))   # unmet first, the short ones read first
        area_rows.append({"area": n, "soft": n in SOFT, "demand": demand, "postings": len((a or {}).get("jobs", ())),
                          "strong": (a or {}).get("strong", 0), "weak": (a or {}).get("weak", 0), "none": (a or {}).get("none", 0),
                          "evidence": supply.get(n, 0), "met": round(100 * ((a or {}).get("strong", 0) + 0.5 * (a or {}).get("weak", 0)) / demand) if demand else None,
                          "unmet": lines[:4]})                                      # a few lines to show, not all

    # ---- the evidence itself
    kinds = Counter(r.get("kind") or "other" for r in kept)                         # facts by kind
    orgs = Counter(plain_org(r.get("org")) or "" for r in kept)                     # facts by company ("" for the ones of no company)
    lanes = []                                                                      # the career's spans, one per role, and the schools'
    for r in kept:
        if r.get("kind") not in ("role", "education"):                              # roles and schools have periods to draw
            continue
        s = span(str(r.get("period") or ""), today)                                 # where it starts and ends
        if not s:                                                                   # no month in it
            continue
        org = plain_org(r.get("org")) or plain_text(r.get("title"))                 # whose
        lanes.append({"org": org, "title": plain_text(r.get("title"))[:80], "kind": r.get("kind"), "start": s[0].isoformat()[:7],
                      "end": s[1].isoformat()[:7], "ongoing": s[2], "months": months(s[0], s[1]), "facts": orgs.get(org, 0)})
    lanes.sort(key=lambda l: l["start"])                                            # oldest first, as a timeline reads
    career = sum(l["months"] for l in lanes if l["kind"] == "role")                 # each role's months added, as the resume's total counts them

    # ---- the interviews ahead: how ready each open application is
    ready = []                                                                      # one row per open application
    order = {"interview": 0, "submitted": 1, "preparing": 2}                        # the nearest interview first
    for j in sorted((j for j in jobs if j.get("stage") in order), key=lambda j: (order[j["stage"]], j.get("seq") or 0)):
        qs = j.get("questions") or []                                               # the application's own questions
        cov, scripts = None, 0                                                      # the kit's answers to the likely questions
        if j.get("kit"):                                                            # a kit was made
            cov, scripts = kit_coverage(api, j["id"])
        ready.append({"job": j["id"], "company": j.get("company") or j["id"], "role": j.get("role") or "", "stage": j.get("stage"),
                      "fit": (j.get("fit") or {}).get("score") if (j.get("posting_chars") or 0) else None, "kit": bool(j.get("kit")),
                      "coverage": cov, "scripts": scripts, "answered": sum(1 for q in qs if str(q.get("answer") or "").strip()),
                      "questions": len(qs), "next": j.get("next") or "", "interview": days_of(j).get("interview") or ""})

    # ---- who the evidence says the person is
    d = api.facts.details() or {}                                                   # the details card: name, tagline, headline
    cards = []                                                                      # the profile's own summary cards: aim, focus, strengths
    for r in kept:
        if r.get("kind") == "card" and r.get("title") and all(c["title"] != r["title"] for c in cards):
            cards.append({"title": str(r["title"])[:40], "text": str(r.get("statement") or "")[:240]})
    comps = []                                                                      # the competencies, by their heads
    for r in kept:
        if r.get("kind") == "competency" and r.get("title") and r["title"] not in comps:
            comps.append(str(r["title"])[:60])

    fit_scores = [f["score"] for f in fits]                                         # one per rated posting
    return {
        "today": today.isoformat(),
        "kpi": {"applications": len(jobs), "open": sum(stages.get(s, 0) for s in ("preparing", "submitted", "interview")),
                "interview_rate": round(100 * funnel["interview"] / funnel["submitted"]) if funnel["submitted"] else None,
                "fit_avg": round(sum(fit_scores) / len(fit_scores)) if fit_scores else None, "fit_best": max(fits, key=lambda f: f["score"]) if fits else None,
                "facts": len(kept), "projects": kinds.get("project", 0), "career_months": career,
                "companies": len({l["org"] for l in lanes if l["kind"] == "role"}),
                "wait_days": gaps_days[len(gaps_days) // 2] if gaps_days else None},     # the median wait from submission to interview
        "stages": {s: stages.get(s, 0) for s in ("preparing", "submitted", "interview", "result")},
        "results": {k: ends.get(k, 0) for k in ("offer", "rejected", "closed", "none")},
        "funnel": funnel,
        "weeks": [{"week": w.isoformat(), **{k: per_week[w].get(k, 0) for k in EVENT_KINDS}} for w in weeks],
        "fits": sorted(fits, key=lambda f: -f["score"]),
        "areas": area_rows,
        "unsorted": {"other": unsorted.get("Other", 0), "process": unsorted.get("process", 0)},
        "evidence": {"kinds": dict(kinds.most_common()), "orgs": [{"org": o, "facts": n} for o, n in orgs.most_common() if o],
                     "unattached": orgs.get("", 0), "lanes": lanes},
        "ready": ready,
        "persona": {"name": d.get("name", ""), "tagline": d.get("tagline", ""), "headline": d.get("headline", ""), "cards": cards[:4], "competencies": comps[:8]},
    }


def kit_coverage(api, jid: str) -> tuple[dict | None, int]:
    """({strong, weak, none} of the kit's likely questions, scripts) for one job's interview kit, or (None, 0)."""
    from . import studio                                                            # the interview board
    try:
        kd = api.ws.job_dir(jid) / "interview"                                      # the kit's notes
    except ValueError:                                                              # deleted for good while the numbers were counted
        return None, 0
    key = (jid, tuple(sorted((f.name, f.stat().st_mtime) for f in kd.iterdir() if f.is_file())) if kd.is_dir() else (), api.kit_stamp(jid))
    if key in KIT_CACHE:                                                            # nothing in the kit changed since
        return KIT_CACHE[key]
    try:
        b = studio.board(api.tasks, jid, "ko")                                      # the questions with how the scripts cover them
    except Exception:                                                               # a kit half made: no numbers rather than no view
        return None, 0
    if not b.get("ready"):                                                          # no kit folder yet
        return None, 0
    c = Counter(q.get("coverage") or "none" for cat in b.get("categories") or [] for q in cat.get("questions") or [])
    out = ({k: c.get(k, 0) for k in ("strong", "weak", "none")}, len(b.get("scripts") or []))
    for k in [k for k in KIT_CACHE if k[0] == jid]:                                 # the job's older numbers go
        del KIT_CACHE[k]
    KIT_CACHE[key] = out
    return out
