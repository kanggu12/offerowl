#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON Resume interop: move a resume in and out of Offerowl (docs/WRITING.md).

JSON Resume (https://jsonresume.org/schema, v1.0.0) is the open format many resume tools read and write. `import` turns
one into an Offerowl profile (resume-profile/0.1, the fields of docs/DOCUMENTS.md); `export` turns a profile
into one, in Korean or English. What has no place on the other side is kept, not dropped: JSON Resume parts that Offerowl
does not use (volunteer work, interests, references, meta and any unknown keys) travel in the profile under
"_jsonresume" and come back on export, so a round trip loses nothing.

  python3 src/write_jsonresume.py import <resume.json> [-o profile.json]
  python3 src/write_jsonresume.py export <profile.json> [--lang en|ko] [-o resume.json]

How the parts map:
  basics            person (name, tagline from label, email, phone, links from url and profiles, location), summary.intro
  work              roles: org, title, place, start and end; summary becomes the role's desc, highlights become one project per role
                    whose title is the position and whose points are the highlights (the drafting step reads them as evidence)
  projects          a project of the work entry it names (entity) or whose dates hold it; the rest go to a "Projects" section
  education         education: school, major (area), degree (studyType), note (score), start and end
  skills            skills: category (name), items (keywords; the name alone when there are none)
  awards, certificates, publications, languages   sections with dated lines or items
On export, a role's projects on the resume become its highlights ("Title (period): summary"), highlight marks removed.
"""
from __future__ import annotations  # `str | None` hints on older Python versions

import argparse  # command line
import copy  # the remainder is copied, never shared
import datetime  # lastModified on export
import json  # both formats are JSON
import pathlib  # paths
import re  # dates and marks
import sys  # exit codes

SCHEMA = "resume-profile/0.1"  # the Offerowl profile schema
JR_VERSION = "v1.0.0"  # the JSON Resume schema version written on export
KNOWN = {"basics", "work", "projects", "education", "skills", "awards", "certificates", "publications", "languages"}  # parts this module maps
SECTION_TITLES = {  # the section a JSON Resume part becomes, per language, and the words that find it again on export
    "awards": {"en": "Awards", "ko": "수상", "find": r"award|수상|prize"},
    "certificates": {"en": "Certificates", "ko": "자격", "find": r"certif|licen|자격|면허"},
    "publications": {"en": "Publications", "ko": "논문", "find": r"publication|paper|논문|저술"},
    "languages": {"en": "Languages", "ko": "외국어", "find": r"language|외국어|어학"},
    "projects": {"en": "Projects", "ko": "프로젝트", "find": r"^projects?$|^프로젝트$"},
}


# small helpers

def plain(v) -> str:
    """Text without highlight and bold marks, one space between words."""
    return re.sub(r"\s+", " ", re.sub(r"==|\*\*", "", str(v or ""))).strip()


def pick(v, lang: str):
    """The language side of a {ko, en} pair (the other side when it is missing), else the value itself."""
    if isinstance(v, dict) and v and set(v) <= {"ko", "en"}:  # a language pair
        return v.get(lang) if v.get(lang) not in (None, "") else (v.get("en") if lang == "ko" else v.get("ko"))
    return v


def is_korean(text: str) -> bool:
    """Is a text mostly Hangul? It decides the section titles of an import."""
    letters = re.findall(r"[A-Za-z가-힣]", text or "")  # letters of both scripts
    return bool(letters) and sum(1 for c in letters if "가" <= c <= "힣") / len(letters) > 0.2


def ym_out(s) -> str:
    """An Offerowl date ('2024.05', '24.05', '2024', '2024-05-17') as an ISO date for JSON Resume ('2024-05'); '' when unreadable."""
    m = re.search(r"((?:19|20)\d{2}|\d{2})(?:[.\-/](\d{1,2}))?(?:[.\-/](\d{1,2}))?", str(s or ""))  # year, month, day
    if not m:  # no date at all
        return ""
    y = m.group(1) if len(m.group(1)) == 4 else "20" + m.group(1)  # a two-digit year is 20YY
    if not m.group(2):  # a bare year
        return y
    out = f"{y}-{int(m.group(2)):02d}"  # year and month
    return out + (f"-{int(m.group(3)):02d}" if m.group(3) else "")  # and the day when there is one


def ym_in(s) -> str:
    """A JSON Resume ISO date ('2024-05-17', '2024-05', '2024') as an Offerowl date ('2024.05', '2024'); '' when empty."""
    m = re.match(r"^\s*((?:19|20)\d{2})(?:-(\d{1,2}))?", str(s or ""))  # year and month; the day is dropped, as the resume prints months
    if not m:  # no date at all
        return ""
    return m.group(1) + (f".{int(m.group(2)):02d}" if m.group(2) else "")


def period_parts(p) -> tuple[str, str]:
    """A project period ('2023.01 ~ 2023.09', '23.01 - 23.09', '2023.05') as (start, end) Offerowl dates."""
    sides = re.split(r"\s*[~–—]\s*|\s+-\s+", str(p or ""))  # the range marks of both languages
    start = ym_in(ym_out(sides[0])) if sides and sides[0] else ""  # normalized through the ISO form
    end = ym_in(ym_out(sides[1])) if len(sides) > 1 and sides[1] else ""  # the end side, when there is one
    return start, end


def key_of(name: str, taken: set) -> str:
    """A role key from an organisation name: lowercase Latin letters and digits, or 'role' for other scripts; unique."""
    base = re.sub(r"[^a-z0-9]+", "-", plain(name).lower()).strip("-") or "role"  # a slug of the Latin part
    k, n = base, 2  # the first try, and the counter for repeats
    while k in taken:  # two employers with one name get two keys
        k, n = f"{base}-{n}", n + 1  # the next free key
    taken.add(k)  # taken from now on
    return k


# import: JSON Resume to profile

def import_resume(jr: dict) -> dict:
    """An Offerowl profile from a JSON Resume document."""
    if not isinstance(jr, dict) or not (jr.get("basics") or jr.get("work")):  # nothing a resume is made of
        raise ValueError("not a JSON Resume document: it has neither basics nor work")  # a document without either cannot be a resume
    b = jr.get("basics") or {}  # name, contacts, summary
    ko = is_korean(json.dumps(jr, ensure_ascii=False))  # the language of the section titles
    title = lambda part: SECTION_TITLES[part]["ko" if ko else "en"]  # a section's title in that language
    person = {"name": plain(b.get("name")), "email": plain(b.get("email"))}  # the two fields the profile needs
    for k_from, k_to in (("phone", "phone"), ("label", "tagline")):  # simple fields
        if b.get(k_from):  # only fields that are there
            person[k_to] = plain(b[k_from])  # as plain text
    links = []  # [label, shown text, address]
    if b.get("url"):  # the person's own page
        links.append(["Web", re.sub(r"^https?://(www\.)?", "", b["url"]), b["url"]])  # shown without its scheme
    for pr in b.get("profiles") or []:  # LinkedIn, GitHub and the like
        if isinstance(pr, dict) and (pr.get("url") or pr.get("username")):  # a profile needs an address or a user name
            shown = re.sub(r"^https?://(www\.)?", "", pr.get("url") or "") or pr.get("username")  # the address without its scheme
            links.append([plain(pr.get("network") or "Profile"), shown, pr.get("url") or ""])  # label, shown text, address
    if links:  # at least one link
        person["links"] = links  # the profile's link rows
    loc = b.get("location") or {}  # an address object
    place = ", ".join(plain(loc.get(k)) for k in ("city", "region", "countryCode") if isinstance(loc, dict) and loc.get(k))  # city, region and country in one line
    if place:  # something to show
        person["location"] = place  # the person's place
    if b.get("image"):  # a photo address is kept for the job file
        person["image"] = b["image"]  # the address of the photo
    prof = {"schema": SCHEMA, "person": person, "summary": {}, "roles": [], "education": [], "skills": [], "sections": []}  # the profile's skeleton; empty parts go at the end
    if b.get("summary"):  # the introduction
        prof["summary"]["intro"] = plain(b["summary"])  # the introduction of the resume
    taken = set()  # role keys in use
    for w in jr.get("work") or []:  # one role per work entry
        if not isinstance(w, dict) or not (w.get("name") or w.get("position")):  # an entry needs a name or a position
            continue  # skip it
        k = key_of(w.get("name") or w.get("position"), taken)  # the role's key
        role = {"key": k, "org": plain(w.get("name")) or plain(w.get("position")), "title": plain(w.get("position")),  # organisation, position and dates
                "start": ym_in(w.get("startDate")), "end": ym_in(w.get("endDate")) or None}  # no end date means the role is ongoing
        if w.get("location"):  # where the role was
            role["place"] = plain(w["location"])  # as the role's place
        if w.get("summary"):  # the line under the company band
            role["desc"] = plain(w["summary"])  # the company line under the band
        if w.get("url"):  # a link to the employer
            role["url"] = w["url"]  # kept for the way back
        hl = [plain(h) for h in w.get("highlights") or [] if plain(h)]  # the achievements
        if hl:  # one project holds them as evidence; the drafting step writes its sentences
            period = " ~ ".join(x for x in (role["start"], ym_in(w.get("endDate"))) if x)  # the role's own period
            role["projects"] = [{"id": f"{k}-1", "title": role["title"] or role["org"], "period": period, "points": hl}]  # the highlights become the points of one project
        prof["roles"].append(role)  # in the document's order
    loose = []  # projects that belong to no work entry
    for pj in jr.get("projects") or []:  # projects join the role they name or whose dates hold them
        if not isinstance(pj, dict) or not pj.get("name"):  # a project needs a name
            continue  # skip it
        start, end = ym_in(pj.get("startDate")), ym_in(pj.get("endDate"))  # the project's dates
        home = next((r for r in prof["roles"] if pj.get("entity") and plain(pj["entity"]).lower() == r["org"].lower()), None)  # the role it names
        if not home and start:  # else the role whose dates hold its start
            home = next((r for r in prof["roles"] if r["start"] and r["start"] <= start and (r["end"] is None or start <= r["end"])), None)  # the role whose dates hold the project's start
        proj = {"title": plain(pj["name"]), "period": " ~ ".join(x for x in (start, end) if x)}  # the project's name and period
        if pj.get("description"):  # what it was
            proj["summary"] = plain(pj["description"])  # its summary
        if pj.get("highlights"):  # its achievements
            proj["points"] = [plain(h) for h in pj["highlights"] if plain(h)]  # its points
        if pj.get("url"):  # a link
            proj["url"] = pj["url"]  # kept
        if home:  # numbered after the role's own projects
            home.setdefault("projects", [])  # the role may have no projects yet
            proj["id"] = f"{home['key']}-{len(home['projects']) + 1}"  # numbered after the role's own
            home["projects"].append(proj)  # the role holds it now
        else:
            loose.append(proj)  # kept for the section
    if loose:  # a section keeps them, dated
        prof["sections"].append({"title": title("projects"), "title_en": "Projects", "_jr": "projects",  # one dated line per project
                                 "lines": [[p["title"] + (": " + p["summary"] if p.get("summary") else ""), "", p["period"]] for p in loose]})
    for e in jr.get("education") or []:  # schools
        if not isinstance(e, dict) or not e.get("institution"):  # a school needs a name
            continue  # skip it
        ed = {"school": plain(e["institution"]), "major": plain(e.get("area")), "degree": plain(e.get("studyType")),  # school, field, degree and dates
              "start": ym_in(e.get("startDate")), "end": ym_in(e.get("endDate")) or None}
        if e.get("score"):  # a grade is a note under the degree
            ed["note"] = plain(e["score"])  # a grade
        if e.get("courses"):  # a course list
            ed["courses"] = [plain(c) for c in e["courses"]]  # kept as it is
        prof["education"].append(ed)  # in the document's order
    for s in jr.get("skills") or []:  # skill groups
        if isinstance(s, dict) and s.get("name"):  # a group needs a name
            items = [plain(x) for x in s.get("keywords") or [] if plain(x)] or [plain(s["name"])]  # a group without keywords names itself
            row = {"category": plain(s["name"]), "items": items}  # the category and its items
            if s.get("level"):  # a level
                row["level"] = plain(s["level"])  # kept for the way back
            prof["skills"].append(row)  # in order
    lines_of = {  # the dated parts: (main text, organisation, date)
        "awards": lambda a: [plain(a.get("title")), plain(a.get("awarder")), ym_in(a.get("date"))],
        "certificates": lambda c: [plain(c.get("name")), plain(c.get("issuer")), ym_in(c.get("date"))],
        "publications": lambda p: [plain(p.get("name")), plain(p.get("publisher")), ym_in(p.get("releaseDate"))],
    }
    for part, fn in lines_of.items():  # each becomes a section of dated lines
        rows = [fn(x) for x in jr.get(part) or [] if isinstance(x, dict) and fn(x)[0]]  # entries with a main text
        if rows:  # the part has entries
            prof["sections"].append({"title": title(part), "title_en": SECTION_TITLES[part]["en"], "_jr": part, "lines": rows})  # a section of dated lines
    langs = [f"{plain(l.get('language'))}: {plain(l.get('fluency'))}".rstrip(": ") for l in jr.get("languages") or [] if isinstance(l, dict) and l.get("language")]  # 'Language: fluency' items
    if langs:  # languages are items
        prof["sections"].append({"title": title("languages"), "title_en": "Languages", "_jr": "languages", "items": langs})  # a section of items
    rest = {k: copy.deepcopy(v) for k, v in jr.items() if k not in KNOWN and k != "$schema"}  # volunteer, interests, references, meta and anything new
    if rest:  # kept for the way back
        prof["_jsonresume"] = rest  # kept for the way back
    for k in ("summary", "sections", "education", "skills"):  # empty parts are left out
        if not prof[k]:  # an empty part
            prof.pop(k)  # is left out
    return prof


# export: profile to JSON Resume

def role_fields(r: dict, lang: str) -> dict:
    """A role's organisation, position, place and dates from the plain or the ledger form."""
    c = r.get("career") or {}  # a ledger's career block
    cl = c.get(lang) or c.get("en" if lang == "ko" else "ko") or {}  # its language half
    org = plain(pick(r.get("org"), lang)) or plain(cl.get("name")) or plain(r.get("heading")) or plain(r.get("key"))  # the plain field first, then the exporter's names
    return {"org": org, "title": plain(pick(r.get("title"), lang)) or plain(cl.get("role")) or plain(c.get("title")),
            "place": plain(pick(r.get("place"), lang)) or plain(cl.get("place")),
            "start": r.get("start") or c.get("start") or "", "end": r.get("end", c.get("end", ""))}


def item_text(p: dict, lang: str) -> str:
    """One resume item as a highlight: 'Title (period): summary', marks removed."""
    title, summary = plain(pick(p.get("title"), lang)), plain(pick(p.get("summary"), lang))  # the item's name and its sentences
    period = plain(pick(p.get("period"), lang))  # the item's period
    head = title + (f" ({period})" if period else "")  # title and period
    return f"{head}: {summary}" if summary else head


def export_profile(prof: dict, lang: str = "en") -> dict:
    """A JSON Resume document from an Offerowl profile, in one language."""
    P = prof.get("person") or {}  # who
    S = prof.get("summary") or {}  # the top of the resume
    name = plain(P.get("name_en") if lang == "en" and P.get("name_en") else P.get("name"))  # the English name for an English document
    if lang == "en" and "," in name:  # 'Hong, Gildong' reads 'Gildong Hong' in English
        name = " ".join(reversed([x.strip() for x in name.split(",", 1)]))  # first name first
    m = re.match(r"^(.*?)\s*\(([A-Za-z][A-Za-z .,'-]+)\)$", name)  # a ledger name '홍 길 동 (Gil-Dong Hong)'
    if m:  # a ledger name with a Latin name
        name = m.group(2).strip() if lang == "en" else re.sub(r"(?<=[가-힣])\s(?=[가-힣])", "", m.group(1).strip())  # the Latin name in English, the Korean one joined in Korean
    basics = {"name": name, "email": plain(P.get("email"))}  # the two fields every resume has
    if P.get("tagline"):  # a tagline
        basics["label"] = plain(pick(P["tagline"], lang))  # as the label
    if P.get("image"):  # a photo
        basics["image"] = P["image"]  # its address
    if P.get("phone"):  # a phone number
        basics["phone"] = plain(P["phone"])  # as written
    intro = plain(pick(S.get("intro"), lang)) or plain(pick(S.get("headline"), lang))  # the introduction, else the headline
    if intro:  # an introduction
        basics["summary"] = intro  # the summary
    if P.get("location"):  # a place
        basics["location"] = {"city": plain(pick(P["location"], lang))}  # as a city line
    links = [l for l in P.get("links") or [] if isinstance(l, list) and len(l) >= 3]  # [label, shown, address]
    for k, label in (("linkedin", "LinkedIn"), ("github", "GitHub"), ("scholar", "Scholar"), ("homepage", "Web")):  # the exporter's separate keys
        if P.get(k) and not any(l[0] == label for l in links):  # a separate key not yet among the links
            links.append([label, P[k], P[k] if str(P[k]).startswith("http") else "https://" + str(P[k])])  # with a full address
    web = next((l for l in links if l[0].lower() in ("web", "homepage", "website")), None)  # the person's own page
    if web:  # the person's own page
        basics["url"] = web[2]  # goes into url
    basics["profiles"] = [{"network": l[0], "url": l[2], "username": l[1].rstrip("/").split("/")[-1]} for l in links if l is not web]  # the other links are profiles
    if not basics["profiles"]:  # no profile at all
        basics.pop("profiles")  # no empty list
    out = {"$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/" + JR_VERSION + "/schema.json", "basics": basics}  # the schema the document follows
    work = []  # one entry per role
    for r in prof.get("roles") or []:  # one work entry per role
        if not isinstance(r, dict) or not (r.get("org") or r.get("career") or r.get("heading")):  # a role needs a name
            continue  # skip it
        f = role_fields(r, lang)  # the role's names and dates
        w = {"name": f["org"], "position": f["title"]}  # the entry
        if f["place"]:  # a place
            w["location"] = f["place"]  # as location
        if ym_out(f["start"]):  # a start
            w["startDate"] = ym_out(f["start"])  # as an ISO date
        if f["end"] and ym_out(f["end"]):  # no end date: the role is ongoing
            w["endDate"] = ym_out(f["end"])  # as an ISO date
        desc = plain(pick(r.get("desc"), lang))  # the company line
        if desc:  # there is one
            w["summary"] = desc  # as summary
        if r.get("url"):  # a link
            w["url"] = r["url"]  # kept
        on = [p for p in r.get("projects") or [] if isinstance(p, dict) and p.get("resume") is not False]  # the items the resume prints
        hl = [item_text(p, lang) for p in on if pick(p.get("summary"), lang)]  # drafted or written items
        if not hl:  # a role that only has a project built from imported highlights gives them back as they were
            hl = [plain(x) for p in on if p.get("points") and not p.get("summary") for x in p["points"]]  # the points of a project without a summary
        if not hl:  # a ledger without sentences yet: the item titles
            hl = [plain(pick(p.get("title"), lang)) for p in on if pick(p.get("title"), lang)]  # the titles alone
        if hl:  # something to list
            w["highlights"] = hl  # the role's highlights
        work.append(w)  # in order
    if work:  # at least one role
        out["work"] = work  # the work part
    edu = []  # one entry per school
    for e in prof.get("education") or []:  # the plain shape, or the ledger form's {ko: {title, sub}}
        if not isinstance(e, dict):  # a school needs fields
            continue  # skip it
        el = e.get(lang) or {}  # the ledger's language half
        parts = [plain(x) for x in re.split(r"\s{2,}", str(el.get("title")).strip())] if el.get("title") else []  # 'Degree  School': split before the spaces collapse
        school = plain(pick(e.get("school"), lang)) or (parts[-1] if parts else "")  # the plain field, else a ledger's title
        if not school:  # no school name
            continue  # skip it
        x = {"institution": school}  # the entry
        area = plain(pick(e.get("major"), lang)) or plain(el.get("sub"))  # the field of study
        study = plain(pick(e.get("degree"), lang)) or (parts[0] if len(parts) > 1 else "")  # the degree
        if area:  # a field
            x["area"] = area  # as area
        if study:  # a degree
            x["studyType"] = study  # as studyType
        if ym_out(e.get("start")):  # a start
            x["startDate"] = ym_out(e.get("start"))  # as an ISO date
        if e.get("end") and ym_out(e.get("end")):  # an end
            x["endDate"] = ym_out(e.get("end"))  # as an ISO date
        if e.get("note"):  # a note
            x["score"] = plain(pick(e["note"], lang))  # as score
        if e.get("courses"):  # courses
            x["courses"] = list(e["courses"])  # as they are
        edu.append(x)  # in order
    if edu:  # at least one school
        out["education"] = edu  # the education part
    skills = [{"name": plain(s.get("category")), "keywords": [plain(i) for i in s.get("items") or []], **({"level": s["level"]} if s.get("level") else {})}  # category, items and level
              for s in pick(prof.get("skills"), lang) or [] if isinstance(s, dict) and s.get("category")]  # every skills row with a category
    if skills:  # at least one
        out["skills"] = skills  # the skills part
    for s in prof.get("sections") or []:  # sections back to their parts
        if not isinstance(s, dict):  # a section needs fields
            continue  # skip it
        part = s.get("_jr") or next((k for k, v in SECTION_TITLES.items() if re.search(v["find"], plain(pick(s.get("title"), lang)) + " " + plain(s.get("title_en")), re.I)), None)  # its JSON Resume part: marked on import, else found by its title
        if not part:  # a section JSON Resume has no part for
            continue  # skip it
        lines = [l for l in s.get("lines") or [] if isinstance(l, list) and l]  # [main, organisation, date]
        items = [plain(pick(i, lang)) for i in s.get("items") or []]  # plain items
        if part == "languages":  # 'Language: fluency' items
            out["languages"] = [{"language": x.split(":")[0].strip(), **({"fluency": x.split(":", 1)[1].strip()} if ":" in x else {})} for x in items]  # language and fluency
        elif part == "projects":  # projects without a role
            out.setdefault("projects", []).extend({"name": plain(l[0]).split(": ")[0], **({"description": plain(l[0]).split(": ", 1)[1]} if ": " in plain(l[0]) else {}),  # name and description from 'name: description'
                                                   **({"startDate": ym_out(period_parts(l[2])[0])} if len(l) > 2 and l[2] else {})} for l in lines)  # the start of its period
        else:
            key = {"awards": ("title", "awarder", "date"), "certificates": ("name", "issuer", "date"), "publications": ("name", "publisher", "releaseDate")}[part]  # the field names of each dated part
            rows = [{key[0]: plain(l[0]), **({key[1]: plain(l[1])} if len(l) > 1 and l[1] else {}), **({key[2]: ym_out(l[2])} if len(l) > 2 and ym_out(l[2]) else {})} for l in lines]  # main text, organisation, date
            rows += [{key[0]: x} for x in items if x]  # plain items too
            if rows:  # something to write
                out[part] = rows  # the part
    for k, v in (prof.get("_jsonresume") or {}).items():  # the parts that came in and had no place here
        out.setdefault(k, copy.deepcopy(v))  # the input's own value wins
    meta = out.setdefault("meta", {})  # where the document came from
    if isinstance(meta, dict):  # a meta object
        meta.update({"version": JR_VERSION, "lastModified": datetime.date.today().isoformat(), "offerowl": {"schema": SCHEMA, "lang": lang}})  # the version, the date and where it came from
    return out


# command line

def read_json(path) -> dict:
    """A JSON file, or a clear stop."""
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # missing or not JSON
        raise SystemExit(f"not a readable JSON file: {path}")  # say which file


def write_json(path, data) -> None:
    """UTF-8, indented, a newline at the end."""
    p = pathlib.Path(path)  # the target
    p.parent.mkdir(parents=True, exist_ok=True)  # the folder may not exist yet
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # readable diffs


def main(argv=None) -> int:
    """import and export; exit 0 when done, 1 when the input is not what it should be."""
    ap = argparse.ArgumentParser(prog="offerowl", description="JSON Resume import and export for Offerowl profiles.")  # "offerowl import" and "offerowl export", as the launcher calls them
    sub = ap.add_subparsers(dest="cmd", required=True)  # a bare call prints usage
    i = sub.add_parser("import", help="JSON Resume -> Offerowl profile")  # JSON Resume in
    i.add_argument("resume"), i.add_argument("-o", "--out")  # the input and an optional output
    e = sub.add_parser("export", help="Offerowl profile -> JSON Resume")  # JSON Resume out
    e.add_argument("profile"), e.add_argument("--lang", choices=("en", "ko"), default="en"), e.add_argument("-o", "--out")  # the profile, the language and an optional output
    a = ap.parse_args(argv)  # None reads sys.argv; tests pass a list
    if a.cmd == "import":  # JSON Resume to profile
        src = pathlib.Path(a.resume)  # the input
        try:
            prof = import_resume(read_json(src))  # the mapping
        except ValueError as err:  # not a JSON Resume document
            print(err)  # say what is wrong
            return 1
        out = pathlib.Path(a.out) if a.out else src.with_name(src.stem + ".profile.json")  # beside the input, never over it
        write_json(out, prof)  # the new profile
        print(f"import: {len(prof.get('roles', []))} roles, {len(prof.get('education', []))} schools, {len(prof.get('skills', []))} skill groups, "  # what came in
              f"{len(prof.get('sections', []))} sections -> {out}")  # and where it went
        return 0
    src = pathlib.Path(a.profile)  # profile to JSON Resume
    prof = read_json(src)  # the input
    if prof.get("schema") != SCHEMA:  # only Offerowl profiles
        print(f"not an Offerowl profile ({SCHEMA}): {src}")  # say what is wrong
        return 1
    jr = export_profile(prof, a.lang)  # the mapping
    out = pathlib.Path(a.out) if a.out else src.with_name(f"{src.stem}.resume.{a.lang}.json")  # beside the input, never over it
    write_json(out, jr)  # the document
    print(f"export: {len(jr.get('work', []))} work entries, {len(jr.get('education', []))} schools, {len(jr.get('skills', []))} skill groups ({a.lang}) -> {out}")  # what went out
    return 0


if __name__ == "__main__":
    sys.exit(main())  # the exit code reaches the shell
