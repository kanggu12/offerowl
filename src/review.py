# -*- coding: utf-8 -*-
"""Rules for merging fact candidates into the profile draft and taking them out again. The review screen
(src/ui/server.py) and the tests (tests/) call it.

When a person accepts a candidate (the kept ones from src/ingest.py), it moves to the profile field that fits its kind
(the fields of docs/DOCUMENTS.md). Every moved item carries the candidate id (cid, a hash made from
the content), so undoing a candidate removes only what it added. Fields and items a person edited are kept.
The candidate id comes from the content, not from the position in the candidate list. When the extraction runs again
and the order changes, the added marks and the removals still point at the right candidates (ids tied to list
numbers let a removal after a re-extraction delete a different item).
"""
import hashlib  # candidate id
import re  # reading periods, grouping company names

import llm  # the message helper and the language setting

SCHEMA = "resume-profile/0.1"  # profile schema
# kinds that go to a list section, with the section names (Korean, English)
SECTION = {"paper": ("논문", "Publications"), "patent": ("특허", "Patents"), "award": ("수상", "Awards"),
           "certificate": ("자격증", "Certificates"), "other": ("기타", "Other")}
ROLE_FIELDS = ("title", "start", "end")  # fields a role candidate fills


MSG = {  # what this step says, in both languages with the same keys
    "en": {"bad_profile": "this is not a profile in the expected form", "bad_field": "{field} is not in the expected form",
           "no_org": "Company not set", "role_kept": "This role already has a title and dates, so they were left as they are. If they differ, change them in the draft",
           "need_name": "Please fill in your name", "need_email": "Please fill in your email", "need_role": "Please add at least one role"},
    "ko": {"bad_profile": "프로필 꼴이 다르다", "bad_field": "{field} 꼴이 다르다",
           "no_org": "소속 미정", "role_kept": "이미 직무와 기간이 있어 바꾸지 않았다. 다르면 초안에서 고친다",
           "need_name": "이름을 채워 주세요", "need_email": "이메일을 채워 주세요", "need_role": "경력을 하나 넣어 주세요"},
}


def t(key: str, **kw) -> str:
    """A message of this step in the person's language."""
    return llm.message(MSG, key, **kw)


def empty() -> dict:
    """An empty draft"""
    return {"schema": SCHEMA, "person": {"name": "", "email": ""}, "summary": {"headline": "", "intro": {"ko": "", "en": ""}},
            "roles": [], "education": [], "skills": [], "sections": []}


def normalize(draft) -> dict:
    """Bring a draft that a person edited and sent back into shape: fill the missing fields and reject wrong types
    (ValueError). Saving a malformed draft would block every later accept and reject, so it is refused here"""
    if not isinstance(draft, dict) or draft.get("schema") != SCHEMA:
        raise ValueError(t("bad_profile"))
    base = empty()
    for k, v in base.items():  # top-level fields that are missing
        draft.setdefault(k, v)
    for k in ("person", "summary"):
        if not isinstance(draft[k], dict):
            raise ValueError(t("bad_field", field=k))
    draft["summary"].setdefault("intro", {"ko": "", "en": ""})
    for k in ("roles", "education", "skills", "sections"):
        if not isinstance(draft[k], list) or not all(isinstance(x, dict) for x in draft[k]):
            raise ValueError(t("bad_field", field=k))
    for r in draft["roles"]:
        r.setdefault("projects", [])
        if not isinstance(r["projects"], list) or not all(isinstance(p, dict) for p in r["projects"]):
            raise ValueError(t("bad_field", field="projects"))
        for f in ("org", "title", "dept", "place", "start"):
            r.setdefault(f, "")
        r.setdefault("end", "")
    for s in draft["skills"]:
        s.setdefault("category", "")
        if not isinstance(s.setdefault("items", []), list):
            raise ValueError(t("bad_field", field="skills"))
    for s in draft["sections"]:
        s.setdefault("title", "")
        if not isinstance(s.setdefault("items", []), list):
            raise ValueError(t("bad_field", field="sections"))
    return draft


def cid(cand: dict) -> str:
    """Candidate id: a short hash of kind, company, title and quote (independent of the list order)"""
    raw = "\x1f".join(str(cand.get(k) or "") for k in ("kind", "org", "title", "quote"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def period(text: str) -> tuple:
    """A period such as '2022.03 ~ 2024.06', '2022.3 - present' (Korean year and month characters work too) or '2019-2021'
    as (start, end). The end is None when it says present (the Korean words for present or employed count) or is empty
    as in '2022.03 ~'. With a single date it is (that date, that date), and when nothing can be read it is ("", "")"""
    t = text or ""
    # year and month. The month is 1 to 12 and must not be followed by another digit (so the '20' of '2019-2021' is not read
    # as a month)
    ym = [f"{y}.{int(m):02d}" for y, m in re.findall(r"((?:19|20)\d{2})\s*[.\-/년]\s*(0?[1-9]|1[0-2])(?!\d)", t)]
    if not ym:  # only a year is given
        ym = re.findall(r"(?:19|20)\d{2}", t)
    if not ym:
        return "", ""
    if re.search(r"현재|재직|present|now", t, re.I) or (len(ym) == 1 and re.search(r"[~\-–]\s*$", t.strip())):
        return ym[0], None  # until now
    return ym[0], (ym[1] if len(ym) > 1 else ym[0])


def org_key(org: str) -> str:
    """Key for grouping company names: drops the Korean company-form markers (parenthesized or spelled out, both meaning
    'Co., Ltd.'), parenthesized text (usually the English name) and whitespace. Same rule as ingest.org_key"""
    s = re.sub(r"\(주\)|주식회사|\([^)]*\)", "", org or "")
    return re.sub(r"\s+", "", s).lower()


def _role(draft: dict, cand: dict, c: str) -> dict:
    """The career entry for the candidate's company, created when missing. The same company is found by its name key, also
    for older drafts whose entries carry no stored key"""
    key = org_key(cand.get("org")) or "unknown"
    for r in draft["roles"]:
        if (r.get("key") or org_key(r.get("org"))) == key:
            return r
    # end: an empty string means unknown, null means still employed. A candidate alone cannot tell, so it stays an empty string
    r = {"key": key, "org": cand.get("org") or t("no_org"), "title": "", "dept": "", "place": "", "start": "", "end": "",
         "projects": [], "cand": c}
    draft["roles"].append(r)
    return r


def accept(draft: dict, cand: dict, c: str = None) -> str:
    """Put one candidate into the draft. The same candidate is never added twice. Returns one result line (the reason, when
    some field could not be filled)"""
    c = cid(cand) if c is None else str(c)  # the id is always a string (so a numeric 0 is not read as missing)
    reject(draft, c)  # remove first, then add again (pressing twice still gives one)
    kind = cand.get("kind")
    start, end = period(cand.get("period", ""))
    if kind == "role":  # company and role: only the empty fields of the career entry are filled
        r = _role(draft, cand, c)
        filled = {}
        for f, v in (("title", cand.get("title", "")), ("start", start), ("end", end)):
            if v not in ("", None) or (f == "end" and v is None and start):  # only values that are present (null for still employed counts)
                if r.get(f) in ("", None) and not (f == "end" and r.get("end") is None and r.get("start")):
                    r[f] = v
                    filled[f] = v
        r.setdefault("filled", {})[c] = filled  # fields this candidate filled and their values (on removal only the fields nobody changed are reset)
        if not filled:
            return t("role_kept")
    elif kind == "project":  # project: a bullet under that company
        r = _role(draft, cand, c)
        r["projects"].append({"id": "c" + c, "title": cand.get("title", ""), "period": cand.get("period", ""),
                              "summary": cand.get("statement", ""), "cand": c})
    elif kind == "education":  # education: one row of the table
        draft["education"].append({"school": cand.get("org", ""), "major": cand.get("title", ""), "degree": "",
                                   "start": start, "end": end or "", "cand": c})
    elif kind == "skill":  # skills: split the candidate title at commas and add to the 'Skills' category (a person fixes the category)
        row = next((s for s in draft["skills"] if s.get("category") == "Skills"), None)
        if row is None:
            row = {"category": "Skills", "items": []}
            draft["skills"].append(row)
        for it in [x.strip() for x in (cand.get("title") or "").split(",") if x.strip()]:
            if it not in row["items"]:
                row["items"].append(it)
            owners = row.setdefault("cand_items", {}).setdefault(it, [])  # every candidate that added the same skill
            if c not in owners:
                owners.append(c)
    else:  # papers, patents, awards, certificates, other: list sections
        ko, en = SECTION.get(kind, SECTION["other"])
        sec = next((s for s in draft["sections"] if s.get("title") == ko), None)
        if sec is None:
            sec = {"title": ko, "title_en": en, "items": []}
            draft["sections"].append(sec)
        text = cand.get("statement") or cand.get("title", "")
        sec["items"].append(text)
        sec.setdefault("cand_text", {})[c] = text  # the text this candidate added (on removal only that one text is deleted)
    return ""


def reject(draft: dict, c: str) -> None:
    """Take what came from one candidate out of the draft. Fields a person edited and items a person added stay"""
    c = str(c)
    keep_roles = []
    for r in draft["roles"]:
        r["projects"] = [p for p in r.get("projects", []) if p.get("cand") != c]
        filled = r.get("filled", {}).pop(c, None)
        if filled:  # of the fields this candidate filled, reset only those a person did not change
            for f, v in filled.items():
                if r.get(f) == v:
                    r[f] = ""
        # a company entry made for this candidate is deleted when it has no projects, no other candidates and no field filled by a person
        human = any(r.get(f) for f in ("title", "dept", "place", "start")) or r.get("end") is None
        if r.get("cand") == c and not r["projects"] and not r.get("filled") and not human:
            continue
        keep_roles.append(r)
    draft["roles"] = keep_roles
    draft["education"] = [e for e in draft["education"] if e.get("cand") != c]
    for s in draft["skills"]:
        before = len(s.get("items", []))
        for it, owners in list(s.get("cand_items", {}).items()):
            if c in owners:
                owners.remove(c)
                if not owners:  # nobody else added that skill, so remove it
                    s["items"] = [x for x in s["items"] if x != it]
                    del s["cand_items"][it]
        s["_emptied"] = before > 0 and not s["items"]  # only categories emptied right now are deleted (empty categories a person created stay)
    draft["skills"] = [s for s in draft["skills"] if not s.pop("_emptied")]
    for s in draft["sections"]:
        text = s.get("cand_text", {}).pop(c, None)
        if text is not None and text in s["items"]:
            s["items"].remove(text)  # only that text
            s["_emptied"] = not s["items"]
    draft["sections"] = [s for s in draft["sections"] if not s.pop("_emptied", False)]


def merge_roles(draft: dict) -> None:
    """When a person edits a company name to match another entry, merge the two entries (the way to move a project that was
    created under a customer name back to its real company). The later entry's projects are appended to the earlier one, and
    only the earlier entry's empty fields are filled from the later one"""
    out, seen = [], {}
    for r in draft["roles"]:
        k = org_key(r.get("org", ""))
        if k and k in seen:  # the same company is already there
            a = seen[k]
            a["projects"] += r.get("projects", [])
            for f in ("title", "dept", "place", "start"):
                a[f] = a.get(f) or r.get(f, "")
            if a.get("end") == "" and r.get("end", "") != "":  # if the end is unknown, take the known one (including null for still employed)
                a["end"] = r["end"]
            a.setdefault("filled", {}).update(r.get("filled", {}))
            continue
        r["key"] = k or r.get("key")
        seen[k] = r
        out.append(r)
    draft["roles"] = out


def problems(draft: dict) -> list:
    """Blanks that block building the resume (the wording is shown to the person as it is)"""
    out = []
    if draft.get("schema") != SCHEMA:
        out.append(t("bad_profile"))
    p = draft.get("person") or {}
    if not p.get("name"):
        out.append(t("need_name"))
    if not p.get("email"):
        out.append(t("need_email"))
    if not draft.get("roles"):
        out.append(t("need_role"))
    return out
