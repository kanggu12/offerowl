"""Text helpers shared by plan and audit: lines of a document, content words, abbreviations.

The word rules follow the search page's tokenizer (Korean particles and endings stripped, English plurals and -ing,
-ed stemmed, question filler dropped, synonym groups), so a posting line and a scene are compared the way a typed
question and a scene are.
"""
import json  # synonym groups
import pathlib  # the package folder
import re  # patterns

HERE = pathlib.Path(__file__).resolve().parent  # src/interview
# Korean particles and endings stripped from the end of a word, longest first (the page's list).
JOSA = ["에서부터", "으로부터", "이라고", "에게서", "으로서", "으로써", "에서는", "에서도", "으로는", "이라는", "까지는",
        "습니까", "습니다", "했나요", "하나요", "인가요", "였나요", "했는지", "하는지", "입니다", "합니다", "했어요", "해요",
        "에서", "에게", "한테", "께서", "까지", "부터", "보다", "처럼", "마다", "이나", "이랑", "하고", "으로", "라고", "라는", "이란",
        "했다", "하다", "한다", "했던", "하는", "인데", "는데", "은데", "나요", "가요", "죠",
        "로", "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "와", "과", "랑", "요", "란"]
# Korean question words and posting filler: they say nothing about a topic, so they never count as key terms
STOP_KO = {"어떻게", "무엇", "무엇을", "뭐", "뭘", "어떤", "있나", "있나요", "있습니까", "있었나", "해주세요", "해주시겠어요",
           "말씀", "주세요", "설명", "대해", "대해서", "그리고", "그럼", "혹시", "본인", "지원자", "하셨나", "했나", "건가", "인가", "좀", "한번",
           "그런", "이런", "저런", "어느", "얼마나", "정도", "가장", "제일", "때", "것", "수", "등",
           "및", "통해", "위한", "위해", "있는", "있습니다", "경험", "능력", "이상", "관련", "분야", "업무"}  # posting filler too
# English function words, question filler and posting boilerplate, dropped for the same reason
STOP_EN = set(("a an the of to in on for and or is are was were be been being i you we it its this that these those with as at by "
               "from my your our me do does did how what why when which who whom can could would should will about into than then there "
               "their they them he she his her tell describe explain please us so if any some have has had time times example give "
               "talk walk through ever kind much many more most really just like also still even well way thing things something "
               "work working experience experienced ability able strong good excellent knowledge skills skill understanding years year "
               "plus preferred required requirements responsibilities qualifications including include includes etc using use used "
               "within across other new related relevant least one two three across team teams role you'll we're our").split())
WORD = re.compile(r"[a-z0-9]+(?:[./+\-][a-z0-9]+)*|[가-힣]+")  # Latin words (with p/d, ci/cd) or Hangul runs
BULLET = re.compile(r"^\s*(?:[-*•·▪◦‣]|\d+[.)])\s+")  # a list mark at the start of a line
KEYED = re.compile(r"^[\w ./-]{1,24}:\s")  # "Location: ..." or "Languages: ..." lines
# An abbreviation: two or more capitals, maybe with digits or a lowercase letter in between (K8s, gRPC, mTLS, P/D).
ABBR = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9]*(?:[/&+][A-Z0-9]+)?[A-Z0-9]|[a-z][A-Z][A-Za-z0-9]*|[A-Z][a-z]?[0-9][a-z0-9]*)(?![A-Za-z0-9])")
# short capitals that are ordinary words, places or file types, not abbreviations worth listing
ABBR_STOP = {"I", "A", "OK", "AM", "PM", "US", "UK", "EU", "KR", "TV", "ID", "IDS", "ETC", "AND", "THE", "FOR", "WITH", "FAQ", "CV", "PDF"}


def stem_ko(w):  # Korean words are compared without their particles
    """Strip one particle or ending, keeping at least two syllables."""
    for j in JOSA:  # longest endings first, so the first match is the whole ending
        if len(w) >= len(j) + 2 and w.endswith(j):  # a stem of at least two syllables must remain
            return w[:-len(j)]  # the word without that ending
    return w  # no ending to strip


def stem_en(w):  # English words are compared without their inflection
    """A light English stemmer: plurals and -ing, -ed (the page's)."""
    if len(w) > 4 and w.endswith("ies"):  # policies and policy meet
        return w[:-3] + "y"  # the word without -ies, plus y
    if len(w) > 5 and w.endswith("ing"):  # long enough that a stem remains
        return w[:-3]  # deploying and deploy meet
    if len(w) > 4 and w.endswith("ed"):  # deployed and deploy meet
        return w[:-2]  # the word without -ed
    # plurals; not words in -ss, and not tokens with digits
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not re.search(r"\d", w):
        return w[:-1]  # the singular
    return w  # nothing to strip


def words(s):  # the one tokenizer for postings, scenes and questions
    """Content words of a text, stemmed and lowercased, in order (stop words and single letters dropped)."""
    out = []  # in order, repeats kept
    for m in WORD.finditer((s or "").lower()):  # lowercased first, so case never splits a word
        tok = m.group(0)  # the raw word
        if re.match(r"[가-힣]", tok):  # Hangul
            st = stem_ko(tok)  # the word without its particle
            if tok in STOP_KO or st in STOP_KO or tok in JOSA:  # filler before or after stripping, and bare particles
                continue
            out.append(st)  # the stem is what gets compared
        else:  # Latin and digits
            if tok in STOP_EN or (len(tok) < 2 and not tok.isdigit()):  # function words and stray letters; digits stay
                continue
            out.append(stem_en(tok))  # the whole token, stemmed
            if re.search(r"[./+\-]", tok):  # ci/cd -> ci, cd as well
                # each part of two letters or more, unless it is a stop word
                out += [stem_en(p) for p in re.split(r"[./+\-]", tok) if len(p) >= 2 and p not in STOP_EN]
    return out


def synonyms(kit_groups=()):  # built once per run by the coverage rater
    """{stem: set of other stems in its groups} from synonyms.json and the job's own groups."""
    # the shared groups first, then the job's own groups from kit.json
    groups = json.loads((HERE / "synonyms.json").read_text(encoding="utf-8"))["groups"] + list(kit_groups or [])
    out = {}  # stem -> others
    for g in groups:  # each group lists words that mean the same
        stems = [stem_ko(w) if re.match(r"[가-힣]", w) else stem_en(w.lower()) for w in g]  # normalised like words()
        for i, s in enumerate(stems):  # every member points at all the others
            out.setdefault(s, set()).update(x for j, x in enumerate(stems) if j != i)  # groups sharing a word merge
    return out


def abbreviations(text):  # the plan lists the abbreviations its documents use
    """Abbreviations in a text, in order of first use, with how often each appears. A capitalised word that the same
    text also writes in ordinary case (BACKEND and Backend) is a title set in capitals, not an abbreviation."""
    plain = {w.lower() for w in re.findall(r"\b[A-Za-z][a-z]+\b", text or "")}  # words written in ordinary case
    seen = {}  # abbreviation -> count, in first-use order
    for m in ABBR.finditer(text or ""):  # every candidate in reading order
        a = m.group(0)  # the candidate as written
        if a in ABBR_STOP or len(a) > 8 or re.fullmatch(r"\d+", a):  # function words, long capitalised titles, plain numbers
            continue
        if a.isalpha() and a.isupper() and len(a) >= 5 and a.lower() in plain:  # a title word in capitals
            continue
        seen[a] = seen.get(a, 0) + 1  # dict order keeps the first use first
    return seen


def doc_lines(text):  # postings and resumes come as markdown or pasted plain text
    """(line number, text, is a list item, is a heading) of a document's logical lines, marks stripped. A list item
    takes in its wrapped continuation lines, and consecutive plain lines form one paragraph (wrapped text joins up)."""
    out = []  # in order
    for n, raw in enumerate((text or "").splitlines(), 1):  # line numbers from 1, as editors show them
        ln = raw.rstrip()  # trailing spaces carry no meaning
        if ln.strip().startswith("```"):  # a fence line itself is not content; the pasted text inside it is
            if out:  # only when there is a line to close
                out[-1][4] = True  # it ends the paragraph before it
            continue
        if not ln.strip():  # a blank line ends a paragraph or a list item
            if out:  # a blank line at the top closes nothing
                out[-1][4] = True  # the fifth field marks a closed line
            continue
        head = ln.lstrip().startswith("#")  # a markdown heading
        bullet = bool(BULLET.match(ln))  # a list item
        s = re.sub(r"^#+\s*", "", ln.strip())  # heading marks
        s = BULLET.sub("", s)  # list marks
        s = re.sub(r"\*\*|__|`|==", "", s).strip()  # inline marks
        if not s:  # a line of marks only, such as a bare bullet
            continue
        prev = out[-1] if out else None  # the logical line this one may continue
        keyed = bool(KEYED.match(s))  # "Languages: Go, Java" stands alone
        # a short capitalised line without end punctuation, right after a break, reads as a heading
        if not head and not bullet and (prev is None or prev[4]) and len(s.split()) <= 3 and s[:1].isupper() and not re.search(r"[.,;:!?]$", s):
            head = True  # a short line after a break is a heading of a plain-text document ("Summary", "Education")
        cont = s[:1].islower() or s[:1] in "(,;&"  # wrapped text goes on in lowercase; a new item or sentence starts in capitals
        # join only onto an open plain line, and only when this line is not a heading, an item or a keyed line
        joins = prev and not prev[4] and not head and not bullet and not keyed and not prev[1].endswith(":") and cont
        if joins:  # wrapped text: a list item's or a paragraph's next physical line
            prev[1] = prev[1] + " " + s  # one space where the line broke
            continue
        out.append([n, s, bullet, head, head or keyed])  # a heading or a keyed line closes itself
    return [(n, s, b, h) for n, s, b, h, _ in out]  # the closed flag is internal; callers get four fields
