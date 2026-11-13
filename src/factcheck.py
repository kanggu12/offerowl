# -*- coding: utf-8 -*-
"""The fact rules in one place. Extraction (src/ingest.py), the drafts (src/draft.py, src/write_resume.py) and the cover
letter (src/cover.py) use the same rules, so a fact that the evidence does not hold is dropped the same way everywhere.

Two kinds of rule live here:

- Facts: numbers (with their units and counted words), Latin words (tools and product names) and Korean organisation
  names must occur in the evidence. The rules cover numbers with commas or units ('1,200', '30%', '3x'), counted words
  ('three times', 'half', 'millions'), Latin words, which are matched as whole words so that one does not pass by being
  part of a longer evidence word ('Java' inside 'JavaScript'), and Korean organisation names.
- Claim strength: a sentence that says the person led, designed, built or owned something is flagged when the evidence
  it cites says the person helped, proposed, took part, or did it with the team or a colleague. The sentence passes when
  it carries the same qualifier itself ("designed and proposed").

  unsupported(text, evidence)  gives the problems (an empty list passes)
  claim_issues(text, evidence)  gives the problems of claim strength (an empty list passes)
"""
import os  # the language of the messages
import re  # every rule here is a pattern

# Numbers: comma groups and decimals, and the unit after them. Units fall into three kinds: percent, multiples, and scale
# words (만, 천, 억, k, M ...). Other units (대, 장, 명, 건, 분 ...) only keep the value.
NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(%|퍼센트|배|x|X|×|만|천|백|억|조|[kK](?![a-zA-Z])|[mM](?![a-zA-Z])|[bB](?![a-zA-Z]))?")
SCALE = {"만": 1e4, "천": 1e3, "백": 1e2, "억": 1e8, "조": 1e12, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "b": 1e9, "B": 1e9}  # scale words to factors
# Counted words: accepted only when the evidence uses the same word
NUM_WORDS = re.compile(r"절반|반으로|두\s*배|세\s*배|네\s*배|다섯\s*배|여섯\s*배|일곱\s*배|여덟\s*배|아홉\s*배|열\s*배|몇\s*배|여러\s*배|"
                       r"수십|수백|수천|수만|수억|배\s*이상|"
                       r"\bhalf\b|\btwice\b|\bdouble[ds]?\b|\btriple[ds]?\b|\bquadruple[ds]?\b|\w+fold\b|\bdozens?\b|\bhundreds\b|"
                       r"\bthousands\b|\bmillions\b|\bbillions\b", re.I)
# Endings of Korean company and institution names. A Korean word with one of these (a bank, a card issuer, an institute)
# must occur in the evidence
ORG_TAIL = ("은행", "카드", "증권", "페이", "공사", "재단", "연구원", "연구소", "대학교", "대학원", "대학", "병원", "그룹", "전자", "통신",
            "텔레콤", "생명", "보험", "화재", "캐피탈", "금융", "감독원", "위원회", "청", "부처", "협회", "공단", "랩스", "테크", "소프트",
            "시스템즈", "솔루션즈", "코리아", "커머스", "모빌리티", "엔터테인먼트", "뱅크", "투자", "자산운용")
# Korean particles at the end of a word, removed before the organisation test
JOSA = re.compile(r"(으로부터|에서부터|으로서|으로써|에게서|이라는|이라고|에서|에게|께서|으로|로서|로써|부터|까지|처럼|보다|이나|이며|이고|"
                  r"과|와|은|는|이|가|을|를|에|의|로|도|만|께|나)$")
# Common English words that join a sentence; they need no evidence
COMMON_EN = set("a an the and or of to in on for with by at from as is are was were be been this that it its into over via per vs "
                "api apis app apps ci cd ui ux id ids os db sql http https url json yaml "
                "cpu cpus vm vms ram ssd hdd io tcp udp ip ips dns ssh cli gui fqdn nic nics lan wan vpn uri urls csv pdf".split())  # general computing words: they name no product

# Messages of unsupported(), in Korean and English. The callers log them and show them in the review screens.
MSG = {  # the messages of unsupported() and highlight_ok()
    "en": {"number": "number not in the evidence: {x}", "number_word": "counted word not in the evidence: {x}",
           "latin": "Latin word not in the evidence: {x}", "org": "organisation not in the evidence: {x}",
           "hl_count": "{n} highlights (allowed {lo} to {hi})", "hl_size": "highlight length {n} (allowed {lo} to {hi})",
           "hl_cover": "the highlight covers almost the whole sentence"},
    "ko": {"number": "근거에 없는 숫자: {x}", "number_word": "근거에 없는 숫자 낱말: {x}",
           "latin": "근거에 없는 영문 낱말: {x}", "org": "근거에 없는 회사·기관 이름: {x}",
           "hl_count": "노란 강조 {n}개(허용 {lo}~{hi})", "hl_size": "강조 길이 {n}(허용 {lo}~{hi})",
           "hl_cover": "강조가 문장 거의 전부를 덮는다"},
}


def ui_lang() -> str:
    """The language of messages: OFFEROWL_LANG, else the locale, else English (the same rule as llm.lang())."""
    value = (os.environ.get("OFFEROWL_LANG") or os.environ.get("LC_ALL") or os.environ.get("LANG") or "en").lower()  # the setting, then the locale
    return "ko" if value.startswith("ko") else "en"  # only two languages exist


def msg(key: str, **kw) -> str:
    """One message of this module in the user's language."""
    return MSG[ui_lang()][key].format(**kw)  # both tables hold every key


def number_tokens(text: str, date_parts: bool = True) -> set:
    """The numbers of a text as (value, kind). The kind is '%', 'x' (a multiple) or '' (anything else). Scale words multiply
    the value. The parts of a date (2024 and 5 of 2024.05) are added as plain numbers too, unless date_parts is off: a sentence
    may say "May 2024" for it, but the 5 of a date is no measurement a chart can draw."""
    out = set()  # (value, kind) pairs
    for m in NUM.finditer(text or ""):  # every number with its unit
        raw, unit = m.group(1), (m.group(2) or "")  # the digits and the unit after them
        v = float(raw.replace(",", ""))  # 1,200 becomes 1200
        if unit in ("%", "퍼센트"):  # a percentage
            out.add((v, "%"))  # a percentage
        elif unit in ("배", "x", "X", "×"):  # a multiple
            out.add((v, "x"))  # a multiple
        else:  # a plain number, scaled when it has a scale word
            out.add((v * SCALE.get(unit, 1), ""))  # a plain number, scaled
        if date_parts and "." in raw and "," not in raw:  # a date such as 2024.05 also counts as its parts
            out |= {(float(p), "") for p in raw.split(".") if p}  # 2024 and 5 of 2024.05
    return out


def number_words(text: str) -> set:
    """Counted words of a text, lowercase and without spaces."""
    return {re.sub(r"\s+", "", m.group(0)).lower() for m in NUM_WORDS.finditer(text or "")}  # 세 배 and 세배 are one word


def latin_tokens(text: str) -> set:
    """Latin words of a text, lowercase. Split at '.', '-' and '/' too (Node.js gives node and js). One-letter capitals (R, C) count."""
    words = set()  # the words and their parts
    for w in re.findall(r"[A-Za-z][A-Za-z0-9+#]*(?:[.\-/][A-Za-z0-9+#]+)*", text or ""):  # a word, kept whole when dotted or hyphenated
        parts = {p.lower() for p in re.split(r"[.\-/]", w) if p}  # its parts
        if not parts <= COMMON_EN:  # a compound of common parts (CI/CD) is as common as its parts
            words.add(w.lower())  # the whole word
        words |= parts  # and its parts
    words |= {w.lower() for w in re.findall(r"(?<![A-Za-z0-9])[A-Z](?![A-Za-z0-9])", text or "")}  # a single capital letter (the R language)
    return words - COMMON_EN  # joining words need no evidence


def plural_ok(w: str, pool: set) -> bool:
    """A word that differs only by a plural s counts as the same word."""
    return w in pool or (w.endswith("s") and w[:-1] in pool) or (w + "s") in pool  # both directions


def korean_orgs(text: str) -> set:
    """Korean words with a company or institution ending, particles removed."""
    out = set()  # the organisation names
    for w in re.findall(r"[가-힣]{2,}", text or ""):  # every Korean word
        if len(w) >= 3 and w.endswith(ORG_TAIL) and w not in ORG_TAIL:  # the whole word is already a name with an ending
            out.add(w)  # kept whole: a name ending in a particle-like syllable must not lose it
            continue  # the particle rule below would cut it
        stem = JOSA.sub("", w)  # without the particle at its end
        if len(stem) >= 3 and stem.endswith(ORG_TAIL) and stem not in ORG_TAIL:  # a name with an ending, not the ending alone
            out.add(stem)  # a name with an ending
    return out


def unsupported(text: str, evidence: str, *, check_latin: bool = True, names: str = "") -> list:
    """Does text hold facts outside the evidence? A list of problems (empty passes). names is other text whose names and
    organisations may appear without being facts about the person (a question, a posting); its numbers count for nothing."""
    bad = []  # problems in the order a person reads them
    ev_nums = number_tokens(evidence)  # what the evidence states
    extra = sorted({(v, k) for v, k in number_tokens(text) if (v, k) not in ev_nums}, key=lambda x: x[0])  # value and kind must both match
    if extra:  # a number the evidence does not state
        bad.append(msg("number", x=", ".join(f"{v:g}{k}" for v, k in extra[:5])))  # the first five, sorted
    words = number_words(text) - number_words(evidence)  # counted words the evidence does not use
    if words:  # counted words the evidence lacks
        bad.append(msg("number_word", x=", ".join(sorted(words)[:5])))  # the first five
    if check_latin:  # a Korean text: every Latin word must come from the evidence
        pool = latin_tokens(evidence) | latin_tokens(names)  # the Latin words of the evidence, and the names a question or a posting gives
        new = sorted(w for w in latin_tokens(text) if not plural_ok(w, pool))  # plural tolerant
        if new:  # Latin words the evidence lacks
            bad.append(msg("latin", x=", ".join(new[:5])))  # the first five
    ev_flat = re.sub(r"\s+", "", (evidence or "") + "\n" + (names or ""))  # organisations compare without spaces; a posting may name its own
    orgs = sorted(o for o in korean_orgs(text) if o not in ev_flat)  # names the evidence does not hold
    if orgs:  # organisations the evidence lacks
        bad.append(msg("org", x=", ".join(orgs[:5])))  # the first five
    return bad


def highlight_ok(text: str, lang: str = "ko", count: tuple = (0, 1), size: tuple | None = None) -> list:
    """The yellow highlight (==phrase==): how many, how long one phrase is (Korean 4 to 30 characters, English 2 to 8 words,
    or `size`), and some text must stay outside it (it may not cover the whole sentence)."""
    bad = []  # problems
    marks = re.findall(r"==(.+?)==", text or "")  # the highlighted phrases
    if not count[0] <= len(marks) <= count[1] or (text or "").count("==") % 2:  # too many, too few, or an unclosed mark
        bad.append(msg("hl_count", n=len(marks), lo=count[0], hi=count[1]))  # count and allowed range
    for m in marks:  # each phrase on its own
        n = len(m.split()) if lang == "en" else len(m.replace(" ", ""))  # words in English, characters in Korean
        lo, hi = size or ((2, 8) if lang == "en" else (4, 30))  # the allowed range
        if not lo <= n <= hi:  # outside the range
            bad.append(msg("hl_size", n=n, lo=lo, hi=hi))  # the size and the range
    if marks:  # the text outside the marks must be a real part of the sentence
        outside = re.sub(r"==(.+?)==", "", text)  # the sentence without its highlighted phrases
        if len(re.sub(r"[\s.,]", "", outside)) < max(8, 0.3 * len(re.sub(r"\s", "", text.replace("==", "")))):  # too little text outside the marks
            bad.append(msg("hl_cover"))  # the whole sentence is highlighted
    return bad


# ---------------------------------------------------------------- claim strength
# What a sentence claims about the person's part, and the qualifiers in the evidence that make such a claim too strong.
# Every pattern is applied to every text: a Korean sentence holds no English verbs and an English one no Hangul, so one
# set of patterns serves both languages and a sentence in one language can be held against evidence in the other.

CLAIMS = {  # claim class to pattern; the classes are compared by name across languages
    "lead": (r"\b(?:led|leading|headed|spearheaded|directed|drove|championed)\b|\bI lead\b|\b(?:team|tech|technical|project) lead\b"
             r"|주도|이끌|이끈|이끔|총괄|지휘|진두|리드(?:했|하였|한|하며|해|로|를 맡)|팀장|파트장|그룹장|(?<![A-Za-z])(?:PL|TPO|PM)(?![A-Za-z])"),
    "design": (r"\b(?:re)?(?:designed|architected|devised)\b|\bre-?architected\b"
               r"|설계(?:했|하였|한 |해 |해서|하고|하여|하며|함|를 맡|를 주도|를 총괄|를 담당|안을 만)|아키텍처를 (?:잡|세웠|짰)|설계(?=\s*(?:$|[.,;·]))"),
    "build": (r"\b(?:re)?(?:built|implemented|developed|created|constructed|founded|co-founded)\b|\bstood up\b|\bset up\b|\bestablished\b"
              r"|구축(?:했|하였|한|해|하고|하여|하며|함)|구현(?:했|하였|한|해|하고|하여|하며|함)|개발(?:했|하였|한|해|하고|하여|하며|함)"
              r"|만들(?:었|어|고)|만든|세웠|세운|세워|신설|창업|(?:구축|구현|개발)(?=\s*(?:$|[.,;·]))"),
    "own": (r"\b(?:owned|owning|owns)\b|\bin charge of\b|\bresponsible for\b|\btook (?:charge|ownership)\b"
            r"|담당(?:했|하였|한|해|하고|하여|하며|함)|책임(?:졌|지고|진|을 맡)|전담|맡(?:았|아|은|고|음)|오너|담당(?=\s*(?:$|[.,;·]))"),
}
HEDGES = {  # qualifier kind to pattern; the kinds are the ones a sentence must keep when its evidence has them
    "helped": (r"\b(?:help(?:ed|ing|s)?|assist(?:ed|ing|s)?|contribut(?:ed|ing|es)\s+to)\b"
               r"|(?<![가-힣])(?:도왔|도와|도움을|돕는|돕고|거들)|(?<![가-힣])보조(?:했|하였|하고|하여|로)|(?:을|를) 지원(?:했|하였)"),  # a word of its own: 산점도와 is 'scatter plot and'
    "proposed": (r"\b(?:propos(?:ed|al|als|ing)|suggest(?:ed|ion|ions)|recommend(?:ed|ation|ations)|draft(?:ed|s)?)\b"
                 r"|제안(?:했|하였|한|해|하고|하여|하며|함|을|서)|건의|권고|초안|안을 (?:냈|내|올렸|올려|만들어 (?:냈|올렸))"),
    "team": r"\b(?:the|our|my) team\b|\bas a team\b|\bteam-wide\b|팀(?:과|이랑|하고|원들과|원과) ?(?:함께|같이)|(?<![가-힣])팀(?:이|은) |팀 단위로",  # 분석팀은 names another team
    "colleague": r"\b(?:colleagues?|co-?workers?|teammates?)\b|동료|선배|후배",
    "participated": r"\b(?:participat(?:ed|ing|es)|took part|was part of|as part of|member of|joined)\b|참여(?:했|하였|한|해|하고|하여|하며|함)|(?<![가-힣])참가|일원(?:으로|이)|구성원으로",
    "jointly": (r"\b(?:jointly|together with|alongside)\b|\bco-(?:designed|built|led|developed|wrote|authored|founded)\b"
                r"|공동(?:으로|작업|개발|설계|구축|창업)|협업(?:했|하여|해|하며|으로)|(?:와|과) 함께|함께 (?:만들|구축|개발|설계|진행|작업|고도화|재구성|적용|수행|운영)"),
}
HEDGE_ORDER = ("helped", "proposed", "participated", "colleague", "team", "jointly")  # the most specific qualifier first, for the message
# A proposal that was adopted is the person's own result: these words cancel the "proposed" qualifier of their sentence
ADOPTED = re.compile(r"관철|채택|합의를 (?:받|얻)|승인을 (?:받|얻)|반영(?:됐|되었|했|하였)|\b(?:adopted|accepted|approved|rolled out)\b", re.I)
# "the team" is not a qualifier when the person led, built or hired it ("led the team", "founded the SRE team")
TEAM_OBJECT = re.compile(r"\b(?:led|built|founded|formed|managed|grew|hired|started|ran|headed|joined)\s+(?:the|a|an|our|my)\s+(?:[\w-]+\s+){0,3}?team\b", re.I)
# "A와 B를 함께 개발했다" means both A and B, not "with someone": a conjunction before 를/을 함께 is not a qualifier
BOTH_TOGETHER = re.compile(r"[가-힣A-Za-z0-9)]+(?:와|과) [^,.\n]{1,40}?(?:를|을) 함께")
CLAIM_RE = {k: re.compile(v, re.I) for k, v in CLAIMS.items()}  # compiled once
HEDGE_RE = {k: re.compile(v, re.I) for k, v in HEDGES.items()}  # compiled once
SENT_END = re.compile(r"(?<=[.!?。])\s+|\n+")  # sentence ends in both languages; a ledger bullet is one block already


def claims_of(text: str) -> dict:
    """The claim classes of a text, each with the first word that claims it."""
    out = {}  # class to the word as written
    for k, rx in CLAIM_RE.items():  # every class once
        m = rx.search(text or "")  # the first occurrence is enough
        if m:  # first occurrence only
            out[k] = m.group(0).strip()  # the word, for the message
    return out


def hedges_of(text: str) -> dict:
    """The qualifiers of a text, each kind with its first word. Adopted proposals, teams the person led and Korean
    'A and B together' phrases are left out."""
    t = TEAM_OBJECT.sub(" ", text or "")  # "led the team" says nothing about who did the work
    t = BOTH_TOGETHER.sub(" ", t)  # "A와 B를 함께" lists two objects
    out = {}  # kind to the word as written
    for k, rx in HEDGE_RE.items():  # every kind once
        m = rx.search(t)  # the first occurrence is enough
        if m:  # first occurrence only
            out[k] = m.group(0).strip()  # the word, for the message
    if "proposed" in out and ADOPTED.search(t):  # the proposal went through, so it is the person's result
        out.pop("proposed")  # an adopted proposal is the person's result
    return out


def sentences_of(evidence) -> list:
    """Evidence as sentences: a string is split at sentence ends, a list is taken block by block and split the same way."""
    blocks = evidence if isinstance(evidence, (list, tuple)) else [evidence or ""]  # one string or many blocks
    out = []  # the sentences, in order
    for b in blocks:  # each block
        out += [s.strip() for s in SENT_END.split(str(b or "")) if s and len(s.strip()) >= 4]  # tiny pieces say nothing
    return out


def _overlap(a: str, b: str) -> int:
    """Shared Latin words and Korean syllable pairs of two texts: which evidence sentence a claim is about."""
    la, lb = latin_tokens(a), latin_tokens(b)  # tool names and other Latin words
    ka = {w[i:i + 2] for w in re.findall(r"[가-힣]{2,}", a or "") for i in range(len(w) - 1)}  # Korean syllable pairs
    kb = {w[i:i + 2] for w in re.findall(r"[가-힣]{2,}", b or "") for i in range(len(w) - 1)}  # Korean syllable pairs of the other text
    return len(la & lb) * 2 + len(ka & kb)  # a shared tool name says more than a shared syllable pair


def claim_issues(text: str, evidence) -> list:
    """Claims that are stronger than the evidence. For each claim class of the sentence (lead, design, build, own):

    - it passes when some evidence sentence makes the same claim and every qualifier of that sentence is in the sentence
      under check too;
    - it is flagged when the evidence makes the claim only with qualifiers the sentence dropped, or never makes it and
      carries a qualifier (helped, proposed, the team, a colleague, participated, jointly) that the sentence dropped.

    `evidence` is the cited text: a string, or a list of blocks (the caller narrows a whole project to the blocks that
    speak to the sentence). Returns [{code: "claim", claim, word, hedge, said, quote}]."""
    mine = claims_of(text)  # what the sentence claims
    if not mine:  # no claim of strength: nothing to compare
        return []
    keep = hedges_of(text)  # the qualifiers the sentence carries itself
    ev = [(s, claims_of(s), hedges_of(s)) for s in sentences_of(evidence)]  # each evidence sentence with its claims and qualifiers
    out = []  # one problem per claim class
    for cls, word in mine.items():  # each claim of the sentence
        same = [(s, h) for s, c, h in ev if cls in c]  # evidence sentences that make the same claim
        if any(not (set(h) - set(keep)) for _, h in same):  # one of them without a qualifier the sentence dropped
            continue  # supported
        hedged = [(s, h) for s, h in same if set(h) - set(keep)]  # the same claim, but qualified
        if not hedged:  # the evidence never makes this claim: look for a qualifier in it
            hedged = [(s, h) for s, c, h in ev if set(h) - set(keep)]  # every qualified sentence of the cited evidence
            if hedged and any(_overlap(text, s) for s, _, _ in ev):  # the evidence speaks to the sentence somewhere
                hedged = [(s, h) for s, h in hedged if _overlap(text, s)]  # then only a qualifier in that part counts
        if hedged:  # the evidence qualifies the work and the sentence does not
            s, h = max(hedged, key=lambda x: _overlap(text, x[0]))  # the qualified sentence closest to the claim is quoted
            kind = next(k for k in HEDGE_ORDER if k in set(h) - set(keep))  # the most specific qualifier is quoted
            out.append({"code": "claim", "claim": cls, "word": word, "hedge": kind, "said": h[kind], "quote": s[:160]})  # the claim, its word, the qualifier and the quoted sentence
    return out


def claim_text(issue: dict, lang: str | None = None) -> str:
    """One claim problem as a sentence a person can act on."""
    lang = lang or ui_lang()  # the caller may fix the language
    if lang == "ko":  # Korean message
        return f"'{issue['word']}'라고 썼지만 근거는 '{issue['said']}'라고 한다: {issue['quote'][:80]}"
    return f"says '{issue['word']}' but the evidence says '{issue['said']}': {issue['quote'][:80]}"  # English message


# ---------------------------------------------------------------- names across languages
# A Korean profile names a client 알파페이 and an English letter writes Alpha Pay. A glossary pair lets the checker accept the
# English spelling when the Korean one stands in the cited evidence (and the reverse), without the writer declaring it.

# Countries and cities in Korean and English: general knowledge, not about any person
GEO = {"한국": ["Korea", "South Korea"], "대한민국": ["Korea", "South Korea"], "국내": ["Korea"], "중국": ["China"], "베트남": ["Vietnam"],
       "인도": ["India"], "일본": ["Japan"], "미국": ["United States", "U.S.", "US", "America"], "대만": ["Taiwan"],
       "독일": ["Germany"], "영국": ["United Kingdom", "UK"], "프랑스": ["France"], "캐나다": ["Canada"], "호주": ["Australia"],
       "하노이": ["Hanoi"], "상하이": ["Shanghai"], "상해": ["Shanghai"], "베이징": ["Beijing"], "북경": ["Beijing"], "서울": ["Seoul"],
       "대전": ["Daejeon"], "부산": ["Busan"], "성남": ["Seongnam"], "판교": ["Pangyo"], "도쿄": ["Tokyo"], "실리콘밸리": ["Silicon Valley"],
       "아시아": ["Asia"], "유럽": ["Europe"], "동남아": ["Southeast Asia"]}


def _plain(v) -> str:
    """Profile text as one plain line (no highlight or bold marks)."""
    return re.sub(r"\s+", " ", re.sub(r"==|\*\*", "", str(v or ""))).strip()


def _items(s) -> list:
    """A comma list as its items."""
    return [x.strip() for x in re.split(r"[,，、]", str(s or "")) if x.strip()]  # commas of both scripts


def glossary_of(profile: dict) -> list:
    """Pairs (Korean spelling, English spelling) for names of one profile: its own "glossary" field, the two spellings of each
    role's name, short name and places (a ledger's career block), a heading such as "가나전자 (Gana Electronics)", the
    cell-by-cell pairs of bilingual summary rows (layers, highlights, cards), and the places above."""
    pairs = []  # (ko, en), in the order found

    def add(ko, en):  # one pair: both sides present, different, and short enough to be a name
        ko, en = _plain(ko), _plain(en)  # plain text without marks
        if ko and en and ko != en and len(en) <= 60:  # a long phrase is a sentence, not a name
            pairs.append((ko, en))  # kept in order

    for ko, ens in GEO.items():  # general places
        for en in ens:  # some places have several English names
            add(ko, en)  # every English name of the place
    g = (profile or {}).get("glossary") or {}  # the person's own glossary: {"알파페이": "Alpha Pay"}
    for ko, en in (g.items() if isinstance(g, dict) else []):  # the person's own pairs
        for e in (en if isinstance(en, list) else [en]):  # one spelling or several
            add(ko, e)  # one pair per spelling
    for r in (profile or {}).get("roles") or []:  # each role's names in both languages
        if not isinstance(r, dict):  # a stray value in the list
            continue  # skip it
        c = r.get("career") or {}  # the ledger form keeps them here
        ko, en = c.get("ko") or {}, c.get("en") or {}  # the two halves
        for k in ("name", "short"):  # the full and the short company name
            add(ko.get(k), en.get(k))  # full and short names
        kp, ep = _items(ko.get("place")), _items(en.get("place"))  # "서울, 하노이" and "Seoul, Hanoi"
        if len(kp) == len(ep):  # lists pair item by item only when they have the same length
            for a, b in zip(kp, ep):  # item by item
                add(a, b)  # one pair per place
        m = re.match(r"^(.*?)\s*\(([^)]+)\)$", _plain(r.get("heading")))  # "가나전자 (Gana Electronics)"
        if m:  # a heading with a Latin name in parentheses
            add(m.group(1), m.group(2))  # the Korean and the Latin name
    S = (profile or {}).get("summary") or {}  # bilingual summary rows, cell by cell
    for key in ("layers", "highlights", "cards"):  # the rows a person writes in both languages
        v = S.get(key) if isinstance(S, dict) else None  # {ko: [...], en: [...]} or a one-language list
        if not (isinstance(v, dict) and isinstance(v.get("ko"), list) and isinstance(v.get("en"), list)):  # only pairs align
            continue  # only {ko, en} lists align
        for a, b in zip(v["ko"], v["en"]):  # row by row
            if isinstance(a, dict) and isinstance(b, dict):  # a selected-project card: its title, then the text of its rows
                add(a.get("title"), b.get("title"))  # the card's two titles
                a = [x for r in (a.get("rows") or []) if isinstance(r, list) for x in r[1:]]  # the Korean rows' texts
                b = [x for r in (b.get("rows") or []) if isinstance(r, list) for x in r[1:]]  # the English rows' texts
            for x, y in zip(a if isinstance(a, list) else [a], b if isinstance(b, list) else [b]):  # cell by cell
                xs, ys = _items(x), _items(y)  # a comma list pairs item by item
                if len(xs) == len(ys) and len(xs) > 1:  # only lists of the same length align
                    for p, q in zip(xs, ys):  # item by item
                        add(p, q)  # one pair per item
    return list(dict.fromkeys(pairs))  # once each, in order


def glossary_accept(text: str, evidence: str, glossary: list) -> list:
    """Spellings in a text whose other-language twin stands in the evidence. Latin spellings match as whole words, Korean
    ones as text; the evidence is compared without spaces and case."""
    ev = re.sub(r"\s+", "", evidence or "").lower()  # the evidence without spaces
    out = []  # accepted spellings
    for ko, en in glossary or []:  # both directions
        for mine, other in ((en, ko), (ko, en)):  # both directions
            if re.search(r"[가-힣]", mine):  # Korean: plain text
                hit = mine in (text or "")  # Korean text has no word boundaries
            else:  # Latin: a whole word or phrase in any case, so US does not match inside 'focus'
                hit = re.search(r"(?<![A-Za-z0-9])" + re.escape(mine) + r"(?![A-Za-z0-9])", text or "", re.I) is not None  # whole words only
            if hit and re.sub(r"\s+", "", other).lower() in ev:  # the twin stands in the evidence
                out.append(mine)  # accepted
    return list(dict.fromkeys(out))  # once each, in order
