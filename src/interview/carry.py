"""Carry one application's interview kit into another's, so a new interview starts from everything prepared before.

What goes: every file the earlier kit names in its kit.json (scenes, deep dives, terms, notes; never the workspace's stories,
which every kit reads already), the other ways each question is asked (alts.json) and the names file. What stays behind:
  - a scene that names the earlier application's company (its kit's company, its record's company, the companies its own kit
    was carried from, and any name the caller adds): that scene is about that interview;
  - nothing of the target is replaced: a file name already there gets "-carried", and an id the target already uses moves to
    the hundreds of its letter (K3 -> K103, then K203), with the ids its alts name;
  - a category written as a list of bold-labelled bullets, whose items would be numbered from its letter (C1, C2 ...), becomes
    headed items with ids of their own, so they never take an id of the target's.
korean: the interview is held in Korean. An English-spoken scene is turned round: its 해석, the Korean that was checked against
the facts, becomes the spoken line, and its English goes under it as plain text (no breath, stress or key-phrase marks). A scene
spoken in Korean already stays as it is.
The target's kit.json names every carried file with its role and label (after its own files, so its own ids come first) and
records where they came from. Returns a report: the files written with their scene counts, the scenes left behind, the ids moved.
"""
import datetime  # the day a kit was carried
import json  # kit.json and alts.json
import re  # scenes, ids and names
from pathlib import Path  # paths

from interview import corpus  # the reader that turns a file into items, as the kit reads it

DLG = re.compile(r"^(\s*(?:-\s+)?)\*\*(면접관|나)\*\*\s*[:：]?\s*(.*)$")  # a spoken line
TR = re.compile(r"^\s*(?:-\s+)?\*\*해석\*\*\s*[:：]?\s*(.*)$")  # the line under it
HEAD = re.compile(r"^### ([A-Z])(\d+)(b?)\.(.*)$")  # a scene's heading: its letter, number and title
CAT = re.compile(r"^## ([A-Z])\.\s+(.*)$")  # a category's heading
BULLET = re.compile(r"^-\s+\*\*(.+?)\*\*\s*[:：]?\s*(.*)$")  # a bold-labelled bullet
HANGUL = re.compile(r"[가-힣]")  # a Korean letter
CITES = re.compile(r"(?<![\w-])(?:company(?:_facts)?|research[\w-]*)\.md\b")  # a scene that cites the earlier kit's research on its company
STAGE = re.compile(r"\([^()]*[가-힣][^()]*\)")  # a Korean stage note, "(웃으며)": how a line is said, never words of it
FIELD = re.compile(r"^\s*(?:[-*]\s*)?\*\*([^*]{1,16})\*\*")  # a scene's field: "**나** ...", "**주의** ..."
NOTE_FIELDS = {"핵심", "주의", "꼬리 대비", "꼬리대비", "근거", "메모", "출처", "참고", "물으면", "읽는 법", "note", "notes", "tip", "source", "key"}  # the person's own notes, never said aloud
SCENE_ROLES = (("deep", "deep"), ("terms", "terms"), ("english", "reference"), ("notes", "reference"), ("research", "reference"))  # a file's role by its name, as the panel's upload reads it


def plain_en(s):
    """An English line as the note under a Korean one: without breath, stress or key-phrase marks, and without Korean stage
    notes, which the spoken Korean line carries."""
    s = STAGE.sub(" ", s)  # "(웃으며)": said, not read
    s = s.replace("**", "").replace("==", "")  # stress and key-phrase marks
    s = re.sub(r"\s+//\s+|\s+/\s+", " ", s)  # breath marks
    return re.sub(r"\s{2,}", " ", s).strip()


def turn_round(lines):
    """Each English line with the Korean 해석 under it, the other way round; every other line as it is. A line whose 해석 holds
    no Korean (a scene spoken in Korean already) is not touched."""
    out, k = [], 0
    while k < len(lines):
        m = DLG.match(lines[k])  # a spoken line
        t = TR.match(lines[k + 1]) if m and k + 1 < len(lines) else None  # and the line under it
        if m and t and HANGUL.search(t.group(1)) and not HANGUL.search(STAGE.sub(" ", m.group(3))):  # English above (its stage notes aside), Korean under
            said = t.group(1).strip()  # the Korean, spoken
            notes = [n for n in STAGE.findall(m.group(3)) if n not in said]  # a stage note the Korean does not have yet goes with it
            out.append(f"{m.group(1)}**{m.group(2)}** {' '.join(notes + [said])}")
            out.append(f"{m.group(1)}**해석** {plain_en(m.group(3))}")  # the English, under it
            k += 2
            continue
        out.append(lines[k])
        k += 1
    return out


def name_pattern(names):
    """One pattern for the names a carried scene may not hold: each name as written, and each Latin word of four letters or
    more in it ("Mistral AI" also catches "Mistral"), never inside a longer word."""
    words = set()
    for n in names:
        n = (n or "").strip()
        if not n:
            continue
        words.add(n)
        words.update(w for w in re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", n))  # its Latin words
    if not words:
        return None
    alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))  # the longest first
    return re.compile(rf"(?<![A-Za-z0-9가-힣])(?:{alts})(?![A-Za-z0-9])", re.I)


def kit_sources(iv: Path) -> list:
    """A kit's files with their roles and labels: as its kit.json names them, else every markdown file by its name's role."""
    kit = read_json(iv / "kit.json")
    if kit.get("sources") is not None:
        return [dict(s) for s in kit["sources"] if isinstance(s, dict) and s.get("file")]
    return [{"file": f.name, "role": next((r for start, r in SCENE_ROLES if f.stem.lower().startswith(start)), "scenes")} for f in sorted(iv.glob("*.md"))]


def read_json(path: Path, default=None):
    """A JSON file's data, or the default ({}) when it is missing or broken."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def ids_of(iv: Path) -> set:
    """Every item id the kit in this folder reads now (headed scenes, numbered bullets, whole categories)."""
    out = set()
    for s in kit_sources(iv):
        f = iv / s["file"]
        if s["file"].startswith("@") or not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        out.update(it["id"] for it in corpus.parse_text(text, f.stem, f.stem[:1].upper(), s.get("role", "scenes"), f.name))
    return out


def free_id(letter, num, suffix, taken):
    """The scene's own id when the target does not use it, else the same number in the next free hundred of its letter."""
    k = 0
    while True:
        cand = f"{letter}{int(num) + 100 * k}{suffix}"
        if cand not in taken:
            return cand
        k += 1


def headed(cat_letter, cat_title, body_lines, taken):
    """A category written as bold-labelled bullets, as headed items with ids the target does not use."""
    out, n = [], 0
    cur = None
    for ln in body_lines:
        m = BULLET.match(ln)
        if m:
            n += 1
            new = free_id(cat_letter, n, "", taken)
            taken.add(new)
            cur = [f"### {new}. {m.group(1)}", "", m.group(2)]  # the label as its title, the text as its body
            out.append(cur)
        elif cur is not None and (ln.startswith("  ") or not ln.strip()):  # the bullet's own continuation
            cur.append(ln.strip())
        elif ln.strip() and cur is None:  # text before the first bullet stays with the category
            out.append([ln])
    return [ln for block in out for ln in block]


def title_key(title):
    """A scene's title as two kits can share it: letters and digits only, lower case."""
    return re.sub(r"[\W_]+", "", str(title or "").lower())


def note_lines(block):
    """The indices of a scene's note lines (its fields of notes, with the lines that run on under them)."""
    out, note = set(), False
    for i, ln in enumerate(block[1:], 1):
        f = FIELD.match(ln)
        if f:  # a field starts: a note, or something said
            note = f.group(1).strip().lower() in NOTE_FIELDS
        if note:
            out.add(i)
    return out


def carry_file(text, deny, taken, korean, moved, have=None, before=None):
    """One file carried: scenes naming the earlier company left out (in their title or what is said; a note that names it
    is dropped and the scene kept), scenes the target already holds under the same title skipped, ids the target uses moved,
    bullet categories headed, and, for a Korean interview, English scenes turned round. have: the target's titles (title_key),
    grown as scenes come in. before: the titles the target held before the carry and not yet counted, the only ones said to
    be there already, each once (a title the carried kit holds twice comes once, and is no scene the target had: C4-15); it
    shrinks as they are counted. Returns (text, scenes kept, titles left out, scenes the target had)."""
    lines = text.splitlines()
    out, kept, left, same = [], 0, [], 0
    have = have if have is not None else set()
    before = set(have) if before is None else before  # called alone: what the target holds as it starts
    k = 0
    while k < len(lines):
        ln = lines[k]
        c = CAT.match(ln)
        if c and deny is not None and deny.search(c.group(2)):  # a section about the earlier company ("C. 감마시스 이해와 지원 동기"): left behind whole
            j = k + 1
            while j < len(lines) and not lines[j].startswith("## "):
                h = HEAD.match(lines[j])
                if h:
                    left.append(h.group(4).strip()[:60])
                j += 1
            k = j
            continue
        if c:  # a category: its bullets may need ids of their own
            j = k + 1
            while j < len(lines) and not lines[j].startswith("## ") and not lines[j].startswith("### "):
                j += 1
            body = lines[k + 1:j]
            groups = [b for b in body if BULLET.match(b)]
            if len(groups) >= 3 and (j >= len(lines) or not lines[j].startswith("### ")):  # a list the reader would number from the letter
                out.append(ln)
                out.extend(headed(c.group(1), c.group(2), body, taken))
            else:
                out.extend(lines[k:j])
            k = j
            continue
        m = HEAD.match(ln)
        if m:  # a scene: up to the next scene or category
            j = k + 1
            while j < len(lines) and not lines[j].startswith("### ") and not lines[j].startswith("## "):
                j += 1
            block = lines[k:j]
            notes = note_lines(block)  # the person's notes under it
            said = "\n".join(b for i, b in enumerate(block) if i not in notes)  # its title and what is said
            if (deny is not None and deny.search(said)) or CITES.search("\n".join(block)):  # about the earlier interview (its title or what is said), or resting on that company's research (a note citing it: the answer was built on it)
                left.append(m.group(4).strip()[:60])
                k = j
                continue
            block = [b for i, b in enumerate(block) if not (i in notes and deny is not None and deny.search(b))]   # a note that only names that company goes, the answer stays
            key = title_key(m.group(4))
            if key and key in have:  # the target holds this scene already (its own, or carried a moment ago from another file of this kit)
                same += key in before  # said as "here already" only when the target had it before the carry,
                before.discard(key)  # and once: the same title again is a double of the carried kit's own
                k = j
                continue
            have.add(key)
            old = f"{m.group(1)}{m.group(2)}{m.group(3)}"
            new = free_id(m.group(1), m.group(2), m.group(3), taken)
            taken.add(new)
            if new != old:
                moved[old] = new
                block[0] = f"### {new}.{m.group(4)}"
            out.extend(turn_round(block) if korean else block)
            kept += 1
            k = j
            continue
        out.append(ln)
        k += 1
    return "\n".join(out).rstrip("\n") + "\n", kept, left, same


def carry(src_iv: Path, dst_iv: Path, korean: bool = False, names=(), job_from: str = "") -> dict:
    """Carry the kit in src_iv (an application's interview folder) into dst_iv. names: more names a carried scene may not hold.
    Returns {"files": [{file, role, label, scenes, left_out}], "moved": {old id: new id}, "alts": n, "left": [titles]}."""
    src_iv, dst_iv = Path(src_iv), Path(dst_iv)
    dst_iv.mkdir(parents=True, exist_ok=True)
    src_kit, dst_kit = read_json(src_iv / "kit.json"), read_json(dst_iv / "kit.json")
    company = src_kit.get("company")
    deny_names = list(names) + ([company.get("ko", ""), company.get("en", "")] if isinstance(company, dict) else [str(company or "")])
    st = read_json(src_iv.parent / "status.json")
    deny_names += [st.get("company", "")] + [n for c in src_kit.get("carried") or [] for n in c.get("names") or []]  # its own, and what it was carried from
    deny = name_pattern(deny_names)
    source = job_from or src_iv.parent.name
    if any(c.get("from") == source for c in dst_kit.get("carried") or []):  # carried from there already: a second run would only double it
        raise ValueError("already_carried")
    taken = ids_of(dst_iv)  # the target's own ids are never taken
    own_letters = {m.group(1) for f in dst_iv.glob("*.md") for m in re.finditer(r"^## ([A-Z])\.", f.read_text(encoding="utf-8"), re.M)}   # the sections the target names itself
    have = {title_key(x) for f in dst_iv.glob("*.md") for x in re.findall(r"^### [A-Z]\d+b?\.(.*)$", f.read_text(encoding="utf-8"), re.M)}   # the target's scene titles: one it holds is never carried again
    before = set(have)  # the titles it held before this carry: the report's "here already" counts each of these once
    if dst_kit.get("sources") is None:  # a kit that reads every file as scenes: its files named once, with their roles
        dst_kit["sources"] = [{"file": f.name, "role": next((r for s, r in SCENE_ROLES if f.stem.lower().startswith(s)), "scenes")}
                              for f in sorted(dst_iv.glob("*.md"))] + [{"file": "@stories", "role": "reference"}]
    report = {"files": [], "moved": {}, "alts": 0, "left": [], "same": 0, "kept_aside": []}
    for s in kit_sources(src_iv):
        if s["file"].startswith("@"):  # the workspace's stories: every kit reads them already
            continue
        f = src_iv / s["file"]
        if not f.is_file():
            continue
        if re.match(r"(?:research|company)", f.stem, re.I) or source.lower() in f.stem.lower():  # that company's research, or a file named after it: about that interview whole
            report["kept_aside"].append(f.name)
            continue
        text, kept, left, same = carry_file(f.read_text(encoding="utf-8"), deny, taken, korean, report["moved"], have, before)
        report["left"].extend(left)
        report["same"] += same
        if not kept and not left:  # a file with no scene of its own (a note page): carried as it is
            kept = len(corpus.parse_text(text, f.stem, f.stem[:1].upper(), s.get("role", "scenes"), f.name))
        if not kept:
            continue
        name = f.name if not (dst_iv / f.name).exists() else f"{f.stem}-carried.md"  # never over the target's own file
        n = 2
        while (dst_iv / name).exists():
            name, n = f"{f.stem}-carried-{n}.md", n + 1
        (dst_iv / name).write_text(text, encoding="utf-8")
        entry = {"file": name, "role": s.get("role", "scenes")}
        if s.get("label") and not (deny is not None and deny.search(s["label"])):  # its label, unless it names the earlier company ("감마시스 문답")
            entry["label"] = s["label"]
        dst_kit["sources"].append(entry)  # after the target's own files: its own ids come first
        report["files"].append({**entry, "scenes": kept, "left_out": len(left)})
    alts_src, alts_dst = read_json(src_iv / "alts.json"), read_json(dst_iv / "alts.json")
    for key, vals in (alts_src.items() if isinstance(alts_src, dict) else []):
        key = report["moved"].get(key, key)  # the scene's id in the target
        if key in taken and key not in alts_dst and isinstance(vals, list):  # a carried scene's, never the target's own
            alts_dst[key] = vals
            report["alts"] += 1
    if report["alts"]:
        (dst_iv / "alts.json").write_text(json.dumps(alts_dst, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    names_src = (src_iv / "names.txt").read_text(encoding="utf-8").splitlines() if (src_iv / "names.txt").is_file() else []
    names_dst = (dst_iv / "names.txt").read_text(encoding="utf-8").splitlines() if (dst_iv / "names.txt").is_file() else []
    more = [ln for ln in names_src if ln.strip() and ln not in names_dst]
    if more:  # the Korean and English names of the person's own companies, for the search
        (dst_iv / "names.txt").write_text("\n".join(names_dst + more) + "\n", encoding="utf-8")
    src_sections = src_kit.get("sections") if isinstance(src_kit.get("sections"), dict) else {}
    letters = {m.group(1) for f in report["files"] for m in re.finditer(r"^## ([A-Z])\.", (dst_iv / f["file"]).read_text(encoding="utf-8"), re.M)} if src_sections else set()
    more_sections = {k: v for k, v in src_sections.items() if k in letters and k not in (dst_kit.get("sections") or {}) and k not in own_letters}   # never over a section the target names itself
    if more_sections:  # a carried section's tab name, unless the target names that letter itself
        dst_kit["sections"] = {**(dst_kit.get("sections") or {}), **more_sections}
    dst_kit.setdefault("carried", []).append({"from": source, "names": [n for n in deny_names if n],
                                              "korean": bool(korean), "at": datetime.date.today().isoformat()})
    (dst_iv / "kit.json").write_text(json.dumps(dst_kit, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report
