"""Turn a job's interview markdown files into search items.

One item is one question and its script. A "### D7. title" heading (or "## S8b. title" in a stories file) names an
item; a "## A. title" heading names a category (a section). A category with no item headings under it is split into
one item per bold-labelled bullet when it has several, and kept whole otherwise. Labelled lines (**핵심**, **면접관**,
**나**, **해석**, **주의**, ...) become fields that the page shows as separate blocks and the index weighs separately.

Which files are read, their labels and their roles come from the job's kit.json (see job.py).
"""
import json  # alternate phrasings are stored as JSON
import re  # heading, field and token patterns

# "D12. title" or "S8b. title": an item heading with its own id.
ITEM_ID = re.compile(r"^(S\d+b?|[A-Z]\d+)\.\s+(.*)$")
# "A. title" or "0. title": a category heading.
CAT_ID = re.compile(r"^([A-Z0-9])\.\s+(.*)$")
# A labelled field line in either file style: "**나** text", "**KO(짧게)** text", "- **면접관**: text".
FIELD = re.compile(r"^(?:-\s+)?\*\*(핵심|KO|EN|국문|주의|꼬리 대비|면접관|나|해석)(?:\(([^)]*)\))?\*\*\s*[:：]?\s*(.*)$")
# A top-level bullet that starts with a bold label: "- **약점**: text".
LABEL_BULLET = re.compile(r"^-\s+\*\*(.+?)\*\*\s*[:：]?\s*(.*)$")
# Field names in the files mapped to item keys (the dialogue labels fill the same keys as the older KO and EN fields).
FIELD_KEY = {"핵심": "key", "KO": "ko", "국문": "ko", "EN": "en", "주의": "note", "꼬리 대비": "note", "면접관": "en", "나": "en", "해석": "ko"}


def plain(md):
    """Strip markdown marks so the text reads like speech for indexing and embedding."""
    t = re.sub(r"```.*?```", lambda m: m.group(0).strip("`"), md, flags=re.S)  # keep code text, drop fences
    t = re.sub(r"\*\*|__|`|==", "", t)  # bold, inline-code and highlight marks
    t = re.sub(r"(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", t)  # italic star marks
    t = re.sub(r"^\s*[-*]\s+", "", t, flags=re.M)  # bullet marks at line start
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)  # numbered-list marks
    t = re.sub(r"^\|?[\s:|-]+\|[\s:|-]*$", "", t, flags=re.M)  # table separator rows
    t = t.replace("|", " ")  # table cell bars
    t = re.sub(r"[ \t]+", " ", t)  # collapse runs of spaces
    t = re.sub(r"\n{2,}", "\n", t)  # collapse blank lines
    return t.strip()  # no leading or trailing whitespace


def split_title(title):
    """Split "한국어 제목 / English title" into its two halves; slashes inside a half (P/D) stay."""
    if " / " in title:  # the bilingual separator always has spaces around it
        ko, en = title.rsplit(" / ", 1)  # the English half is the last one
        letters = re.findall(r"[A-Za-z가-힣]", en)  # letters of the right half
        latin = sum(1 for c in letters if c.isascii())  # how many of them are Latin
        if letters and latin / len(letters) > 0.6:  # mostly Latin means it is the English title
            return ko.strip(), en.strip()
    return title.strip(), ""  # no English half


def fields(lines):
    """Collect labelled fields; lines after a label belong to it until the next label."""
    out = {"key": [], "ko": [], "en": [], "note": [], "pre": []}  # field texts in order
    cur = "pre"  # text before any label is preamble
    for ln in lines:  # walk the body once
        m = FIELD.match(ln.strip())  # a new labelled field starts here?
        if m:  # a label line
            cur = FIELD_KEY[m.group(1)]  # switch to that field
            out[cur].append(m.group(3))  # the rest of the label line is its first text
        elif ln.strip():  # a continuation line of the current field
            out[cur].append(ln.strip())
    return {k: plain("\n".join(v)) for k, v in out.items()}  # plain text per field


def label_bullets(body):
    """Split a body into (label, lines) per top-level bold-labelled bullet, or [] if it is not a label list."""
    groups = []  # (label, lines) for each bullet
    for ln in body:  # walk the body once
        m = LABEL_BULLET.match(ln)  # a new top-level labelled bullet?
        if m:  # a label bullet
            groups.append((m.group(1), [ln]))  # start its group
        elif groups and (ln.startswith("  ") or not ln.strip()):  # indented continuation or blank
            groups[-1][1].append(ln)  # it belongs to the open bullet
        elif ln.strip():  # any other text means this is not a plain label list
            return []  # the caller keeps the section whole
    return groups


def make_item(iid, title, body, src, cat, role, file, line):
    """Build one item from its heading and body lines."""
    md = "\n".join(body).strip()  # the markdown shown on the page
    md = re.sub(r"\n-{3,}\s*$", "", md).strip()  # drop a trailing horizontal rule
    tko, ten = split_title(title)  # bilingual title halves
    f = fields(body)  # labelled fields
    return {  # the fields the page, the index and the checker read
        "id": iid,  # stable id such as D7 or N4
        "src": src,  # which file it came from (its label)
        "role": role,  # how the page treats it: scenes, deep, terms or reference
        "cat": cat,  # its category heading
        "title": title,  # full heading text after the id
        "tko": tko,  # Korean title
        "ten": ten,  # English title (may be empty)
        "key": f["key"],  # the one-line core
        "ko": f["ko"],  # the Korean script (해석 lines)
        "en": f["en"],  # the English script (면접관 and 나 lines)
        "note": f["note"],  # cautions and follow-up notes
        "text": plain(md),  # every word of the body, for items without fields
        "md": md,  # markdown for rendering
        "file": file,  # the source file's name, for checker messages
        "line": line,  # the heading's line number in that file (1-based)
    }


def parse_text(text, src, prefix, role="scenes", file=""):
    """Parse one markdown text into items."""
    blocks = []  # [level, heading, body lines, line number] in file order
    cur = None  # block that body lines are added to
    for n, ln in enumerate(text.splitlines(), 1):  # one pass over the file
        if ln.startswith("### "):  # an item heading
            cur = [3, ln[4:].strip(), [], n]  # a level-3 block with its heading text
            blocks.append(cur)  # kept in file order
        elif ln.startswith("## "):  # a category or item heading
            cur = [2, ln[3:].strip(), [], n]  # a level-2 block with its heading text
            blocks.append(cur)  # kept in file order
        elif ln.startswith("# "):  # the document title: its preamble is not an item
            cur = None
        elif cur is not None:  # body text of the open block
            cur[2].append(ln)  # added to that block's body
    items, seq, i = [], 0, 0  # results, counter for prefix ids, block cursor

    def next_id():  # the next id from the file's prefix
        nonlocal seq  # shared counter across this file
        seq += 1  # ids start at 1
        return f"{prefix}{seq}"  # such as N4

    while i < len(blocks):  # walk level-2 blocks with their level-3 children
        level, head, body, line = blocks[i]  # the block at the cursor
        j = i + 1  # first child candidate
        kids = []  # level-3 blocks under this level-2 block
        while j < len(blocks) and blocks[j][0] == 3:  # the level-3 blocks right after it
            kids.append(blocks[j])  # one child
            j += 1  # and on to the next block
        mi, mc = ITEM_ID.match(head), CAT_ID.match(head)  # item id or category letter in the heading
        if level == 3:  # a stray item before any category
            kids, head = [blocks[i]], src  # treat it as its own child, filed under the file's label
        if kids:  # a category with item headings under it
            for _, khead, kbody, kline in kids:  # one item per child heading
                mk = ITEM_ID.match(khead)  # "D7. title"
                iid, title = (mk.group(1), mk.group(2)) if mk else (next_id(), khead)  # a heading without an id gets a prefix id
                items.append(make_item(iid, title, kbody, src, head, role, file, kline))  # filed under the parent heading
        elif mi:  # "## S8b. title": a whole item at level 2
            items.append(make_item(mi.group(1), mi.group(2), body, src, src, role, file, line))  # filed under the file's label
        else:  # a section without item headings
            letter = mc.group(1) if mc else None  # "C" for "## C. 기술: ..."
            title = mc.group(2) if mc else head  # heading text without the letter
            groups = label_bullets(body)  # one item per labelled bullet?
            if len(groups) >= 3:  # a real label list: split it
                for n, (lab, lines) in enumerate(groups, 1):  # numbered from 1
                    iid = f"{letter}{n}" if letter else next_id()  # C1, C2 or N4, N5
                    short = re.sub(r"\s*\(.*?\)\s*$", "", title)  # heading without its trailing note
                    name = lab if letter else f"{short}: {lab}"  # a lettered category already names the group
                    items.append(make_item(iid, name, lines, src, head, role, file, line))  # each bullet with its own lines
            elif "\n".join(body).strip():  # one item for the whole section
                items.append(make_item(letter or next_id(), title, body, src, src, role, file, line))  # the letter is its id when there is one
        i = j  # continue after the children
    return items


def chunks(text, limit=280):
    """Cut long text into sentence groups of about `limit` characters for embedding."""
    sents = [s for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]  # sentences and lines
    out, buf = [], ""  # finished chunks, chunk being built
    for s in sents:  # greedy packing in order
        if buf and len(buf) + len(s) + 1 > limit:  # this sentence would overflow
            out.append(buf)  # close the full chunk
            buf = s  # and start the next with this sentence
        else:
            buf = f"{buf} {s}".strip()  # keep adding to the chunk
    if buf:  # last partial chunk
        out.append(buf)
    return out


def views(item, alts):
    """Texts to embed for one item, as (label, weight, text); used only by the optional similarity model."""
    v = []  # all views of this item
    for t in (item["tko"], item["ten"]):  # the question in each language
        if t:  # an empty English title adds no view
            v.append(("question", 1.0, t))  # the title counts fully
    if item["key"]:  # the one-line core
        v.append(("key", 0.97, item["key"]))  # the core counts nearly as much as the question
    for a in alts.get(item["id"], []):  # other ways the question may be asked
        v.append(("phrasing", 1.0, a))  # as strong as the title
    body = [("answer", item["ko"]), ("answer", item["en"]), ("note", item["note"])]  # labelled scripts
    if not (item["ko"] or item["en"]):  # an item without labelled scripts: use its whole text
        body = [("text", item["text"])]  # the body as one text
    for label, text in body:  # long texts are cut into chunks
        for c in chunks(text):  # short pieces embed better than a whole script
            v.append((label, 0.95, c))  # body text counts a little less than the question
    return v


def load(job):
    """Read every source of a job and its alternate phrasings; return (items, alts)."""
    items = []  # all items in source order
    seen = set()  # ids already used, to keep ids unique across files
    drafts = {f for f, _, _, _ in job.draft_sources()}  # the agent's files, which the page and the checks treat as drafts
    for path, label, prefix, role in job.sources():  # in the kit's order
        for it in parse_text(path.read_text(encoding="utf-8"), label, prefix, role, path.name):  # this file's items, with its label and role
            it["draft"] = path in drafts  # written by the agent and not yet taken over by a person
            base, n = it["id"], 2  # on a clash, add a suffix
            while it["id"] in seen:  # count up until the id is free
                it["id"] = f"{base}-{n}"  # such as A1-2
                n += 1
            seen.add(it["id"])  # the id is now taken
            it["path"] = str(path)  # the full path, for the checker (the page does not get it)
            items.append(it)
    alt_path = job.alts_path()  # alts.json next to the scenes, unless the kit says otherwise
    alts = json.loads(alt_path.read_text(encoding="utf-8")) if alt_path and alt_path.is_file() else {}  # no alts file means no alternate phrasings
    alts = {k: v for k, v in alts.items() if not k.startswith("_")}  # comment keys are not items
    return items, alts


def stamp(job):
    """Sizes and change times of every file the items come from; a change means the index must be rebuilt."""
    paths = [p for p, _, _, _ in job.sources()]  # the markdown sources
    if job.alts_path():  # and the phrasings
        paths.append(job.alts_path())  # watched for changes too
    paths.append(job.kit_path or job.interview / "kit.json")  # and the kit itself (section names, roles, synonyms), watched even before it exists
    return [(str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths if p.is_file()]  # a missing file drops out of the stamp
