# -*- coding: utf-8 -*-
"""The rules backend: each decision made by the rule-based checks Offerowl already has, so the other backends are
measured against the same input the rules see.

  line_kind      the posting parser decides a line's kind by its section heading; a line on its own has no heading,
                 so this backend reads the line's own words (a "nice to have" or 우대 cue, a qualification cue such as
                 "experience", "years" or 경험, else a duty)
  coverage       the interview audit's term rule (src/interview/cover.py) on the given evidence: strong when one text
                 holds at least 60 percent of the line's content words, weak at 30 percent, else none
  claim          factcheck.claim_issues: a claim of leading, designing, building or owning that the evidence qualifies
  contradiction  the audit's and the practice feedback's signals on the pair: a number with the same unit but another
                 value, another month of the same year, or a first-person claim against a scope limit on the other side
"""
import re  # every rule here is a pattern
import time  # time per decision

import factcheck as F  # claim strength
from interview import audit as A  # scope limits (HEDGE) and first-person claims (CLAIM)
from interview import practice as P  # number words as digits, as the practice feedback reads them
from interview import text as T  # content words and synonyms

PREFERRED = re.compile(r"\b(?:preferred|nice[- ]to[- ]have|a plus|bonus|ideally|desirable)\b|우대|있으면 좋|가산점|플러스", re.I)  # a "plus" line
QUALIFICATION = re.compile(  # a line that names something the applicant has, not a task
    r"^(?:experience|\d+\s*\+?\s*years?|bachelor|master|ph\.?d|degree|ability|able to|strong|solid|proven|familiar|familiarity|"
    r"knowledge|understanding|proficien|fluent|excellent|outstanding|hands-on|working knowledge|certif|expertise|background)"
    r"|\b(?:experience (?:with|in|of|running|building|designing|managing)|years of|degree in|certification|certified|"
    r"familiarity with|proficiency in|fluency in|skills?\b)"
    r"|경험|경력|이상|능력|학위|자격|역량|이해|능숙|숙련|전공", re.I)
SYN = None  # synonym groups, loaded once on first use
NUMBER_UNIT = re.compile(r"(\d+(?:[.,]\d+)*)\s*(%|[A-Za-z]+|[가-힣]{1,2})")  # a number with the word or Korean unit after it
SKIP_UNIT = {"to", "or", "and", "of", "a", "an", "the", "in", "on", "at", "by", "for", "from", "with", "than"}  # words after a number that are not units
MONTH = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november december".split())}  # month names
YEAR_MONTH = re.compile(r"\b((?:19|20)\d\d)[.\-/](\d{1,2})\b|\b(" + "|".join(MONTH) + r")\s+((?:19|20)\d\d)\b|((?:19|20)\d\d)년\s*(\d{1,2})월", re.I)  # 2021.08, August 2021, 2021년 8월


def line_kind(text: str) -> str:
    """duty, requirement or preferred from the line's own words."""
    if PREFERRED.search(text or ""):  # the line says it is a plus
        return "preferred"
    if QUALIFICATION.search((text or "").strip()):  # the line names something the applicant has
        return "requirement"
    return "duty"  # everything else is work to do


def terms_share(line: str, text: str) -> float:
    """The share of the line's content words that a text uses: the word, a synonym, or all syllable pairs of a long
    Korean word (the audit's coverage rule)."""
    global SYN  # loaded once
    if SYN is None:
        SYN = T.synonyms()  # the shared groups of src/interview/synonyms.json
    terms = list(dict.fromkeys(T.words(line)))  # unique content words of the line
    if not terms:  # nothing to look for
        return 0.0
    bag = set(T.words(text))  # the text's content words
    pairs = {w[i:i + 2] for w in bag if re.match(r"[가-힣]", w) for i in range(len(w) - 1)}  # Korean syllable pairs
    hits = 0  # terms the text uses
    for t in terms:  # each term of the line
        if t in bag or (SYN.get(t, set()) & bag):  # the word or a synonym
            hits += 1
        elif re.match(r"[가-힣]{3,}$", t) and {t[i:i + 2] for i in range(len(t) - 1)} <= pairs:  # a long Korean compound written apart
            hits += 1
    return hits / len(terms)  # the share


def coverage(line: str, evidence) -> str:
    """strong, weak or none by the best evidence text's share of the line's words."""
    ev = evidence if isinstance(evidence, list) else [evidence]  # one text or a list
    best = max((terms_share(line, str(e)) for e in ev), default=0.0)  # the text that covers most
    return "strong" if best >= 0.6 else "weak" if best >= 0.3 else "none"  # the audit's thresholds


def claim(sentence: str, evidence) -> str:
    """overclaim when factcheck finds a claim stronger than the evidence, else supported."""
    return "overclaim" if F.claim_issues(sentence, evidence) else "supported"


def unit_pairs(text: str) -> set:
    """{(number, unit)} of a text, in English and Korean ("4 minutes", "4분"); years are left to the date rule."""
    out = set()  # pairs
    for m in NUMBER_UNIT.finditer(P.digits(text or "")):  # every number with what follows it; "three approvals" reads as "3 approvals"
        n, unit = m.group(1).replace(",", ""), m.group(2).lower()  # 2,000 and 2000 meet
        if re.fullmatch(r"(?:19|20)\d\d", n) or unit in SKIP_UNIT:  # a year, or a joining word
            continue
        out.add((n, T.stem_en(unit) if unit.isascii() else unit))  # minutes and minute meet
    return out


def year_months(text: str) -> set:
    """{(year, month)} of a text."""
    out = set()  # pairs
    for m in YEAR_MONTH.finditer(text or ""):  # every date with a month
        if m.group(1):  # 2021.08
            out.add((int(m.group(1)), int(m.group(2))))
        elif m.group(3):  # August 2021
            out.add((int(m.group(4)), MONTH[m.group(3).lower()]))
        else:  # 2021년 8월
            out.add((int(m.group(5)), int(m.group(6))))
    return {(y, mo) for y, mo in out if 1 <= mo <= 12}  # a real month only


def contradiction(a: str, b: str) -> str:
    """contradiction when the two statements give the same unit another number, the same year another month, or one
    side claims the work in the first person while the other limits the person's part."""
    pa, pb = unit_pairs(a), unit_pairs(b)  # numbers with their units
    for n, unit in pa:  # each number of the first statement
        other = {x for x, u in pb if u == unit}  # the second statement's numbers for the same unit
        if other and n not in other and n not in {x for x, _ in pb}:  # a different amount of the same thing
            return "contradiction"
    da, db = year_months(a), year_months(b)  # dates with a month
    for y in {y for y, _ in da} & {y for y, _ in db}:  # a year both name
        if not ({m for yy, m in da if yy == y} & {m for yy, m in db if yy == y}):  # no month in common for that year
            return "contradiction"
    claims_a, claims_b = bool(F.claims_of(a)) or bool(A.CLAIM.search(a)), bool(F.claims_of(b)) or bool(A.CLAIM.search(b))  # led, built, designed ...
    hedge_a, hedge_b = bool(A.HEDGE.search(a) or F.hedges_of(a)), bool(A.HEDGE.search(b) or F.hedges_of(b))  # already existed, a colleague, proposed ...
    if (claims_a and hedge_b and not hedge_a) or (claims_b and hedge_a and not hedge_b):  # one side claims what the other limits
        return "contradiction"
    return "consistent"  # nothing the rules can see


def decide(task: str, items: list) -> list:
    """The rules' decision for each item, with no probabilities (confidence None)."""
    from decide import result  # the shared shape
    out = []  # decisions in order
    for it in items:  # one at a time
        t0 = time.time()  # the rules take microseconds; measured the same way as the others
        if task == "line_kind":
            label = line_kind(it["text"])
        elif task == "coverage":
            label = coverage(it["line"], it["evidence"])
        elif task == "claim":
            label = claim(it["claim"], it["evidence"])
        else:  # contradiction
            label = contradiction(it["a"], it["b"])
        out.append(result(task, label, None, "rules", (time.time() - t0) * 1000))
    return out
