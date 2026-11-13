#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What a typeset resume's pages show and no text check sees (the style pack's "pages" object, docs/WRITING.md), measured
on the page pictures and the PDF's word boxes:

  fill_last      an application's last page leaves at most this share (percent) empty at its foot: the room is filled
                 with facts, never by cutting the margins (a general edition is left out)
  mid_gap        no page in the middle leaves more than this share empty at its foot: a block that moved whole to the next
                 page is a typesetting accident, not the end of the document (a first page of few lines is a cover)
  summary_first  these sections (the career summary) end on page 1 (an application only)
  bands          the words, the logo and the badge of each company band, and the title of each about-me band, sit within
                 this many points of their band's middle
  volume         the lines of each company's experience follow its tenure: a company held clearly shorter (two thirds or
                 less) never gets more lines than a longer one, and none gets more lines per month than this many times
                 the median of all

A page's foot is measured above the footer (the bottom 50 pt of a portrait page); the bands are found by the colour the
typesetting painted them in, which the sidecar (<name>.highlights.json, its "parts") names with the companies it set.
"""
import datetime  # an ongoing role's tenure runs to today
import math  # how many lines would fill a page
import pathlib  # page pictures
import re  # the layout text
import statistics  # the median density
import tempfile  # page pictures

import check_lines as CL  # the Issue every check gives, and the PDF's word boxes
import llm  # the message helper and the language setting

MSG = {  # what these checks say, in both languages with the same keys
    "en": {
        "last_page_room": "the last page leaves {gap}% empty at its foot, more than {limit}%: about {lines} more line(s) fit. Fill it with facts or tighten what is there, never the margins",
        "page_gap": "page {page} leaves {gap}% empty at its foot, more than {limit}%: a block moved whole to the next page",
        "summary_spills": "'{title}' runs past page 1",
        "band_off": "page {page}, the band of {name}: its {part} sits {off} pt off the band's middle (at most {limit})",
        "band_logo": "page {page}, the band of {name}: its logo sticks {over} pt out of the band, {off} pt off its middle",
        "band_count": "{found} company band(s) were found on the pages for {want} set",
        "volume_order": "{short} ({m_short} months) has {n_short} lines, more than {long} ({m_long} months) with {n_long}",
        "volume_density": "{org} has {density} lines a month, {times} times the median {median} (at most {limit})",
        "volume_section": "the section '{title}' was not found, so the lines per company were not measured",
        "volume_band": "the band of {name} was found {n} times, so the lines per company were not measured",
        "part_name": "name", "part_place": "place", "part_period": "period", "part_badge": "badge", "part_title": "title",
    },
    "ko": {
        "last_page_room": "마지막 쪽 아래가 {gap}% 비었다(상한 {limit}%). 약 {lines}줄 더 들어간다. 여백을 깎지 말고 사실로 채우거나 군더더기를 걷는다",
        "page_gap": "{page}쪽 아래가 {gap}% 비었다(상한 {limit}%). 덩어리가 통째로 다음 쪽으로 넘어갔다",
        "summary_spills": "'{title}' 절이 1쪽을 넘어간다",
        "band_off": "{page}쪽 {name} 띠의 {part}: 띠 가운데에서 {off}pt 어긋난다(상한 {limit})",
        "band_logo": "{page}쪽 {name} 띠: 로고가 띠 밖으로 {over}pt, 가운데에서 {off}pt 어긋난다",
        "band_count": "회사 띠를 {want}개 그렸는데 쪽에서 {found}개를 찾았다",
        "volume_order": "기간이 짧은 {short}({m_short}개월)의 줄이 {n_short}줄로 {long}({m_long}개월)의 {n_long}줄보다 많다",
        "volume_density": "{org}의 한 달 줄 수가 {density}줄로 가운데값 {median}의 {times}배다(상한 {limit}배)",
        "volume_section": "'{title}' 절을 찾지 못해 회사별 줄 수를 재지 못했다",
        "volume_band": "{name} 띠를 {n}번 찾아 회사별 줄 수를 재지 못했다",
        "part_name": "회사명", "part_place": "소재지", "part_period": "기간", "part_badge": "배지", "part_title": "제목",
    },
}
DPI = 100  # page pictures for the page rules
COVER_MAX_LINES = 12  # a first page with fewer lines is a cover: its foot is meant to be empty
FOOT_PT = 50  # the footer's zone at a portrait page's bottom, never the body's end
BAND_DPI = 200  # page pictures for the band measurement
BAND_H = 24  # a company band with a logo is 24 pt high (layout.js fbandLogo)
LEFT_TW = 750  # the body's left edge in twips (layout.js margin)
SHORTER = 2 / 3  # a tenure this share of another's or less is clearly shorter
PERIOD = re.compile(r"((?:19|20)\d{2})\.(\d{2})\s*[~\-–]\s*(?:((?:19|20)\d{2})\.(\d{2})|\S)")  # a band's period: closed, or open to today
DATE_WORD = re.compile(r"^(\d{4}\.\d{2}|~|-|\(.*|.*\)|mos?\)?|yrs?|개월\)?|년\)?|재직|재학|중|Present)$")  # the words of a band's period and tenure


def t(key: str, **kw) -> str:
    """A message of these checks in the person's language."""
    return llm.message(MSG, key, **kw)


def issue(key: str, polish: bool = False, **kw) -> CL.Issue:
    """A problem worded in the person's language, with its code and values kept for the report."""
    out = CL.Issue(t(key, **kw))  # the words, a str to every caller
    out.code, out.values, out.polish = key, kw, polish  # and what they say
    return out


def page_stats(path) -> dict:
    """One page picture: where its ink starts and ends, how much of its foot is empty (percent of the height), how many
    lines it has and the usual pitch between them (percent of the height). The footer's zone is never the body's end."""
    from PIL import Image  # in the container and on the host
    im = Image.open(path).convert("L")  # one grey value per pixel
    w, h = im.size  # the page's size in pixels
    data = im.tobytes()  # the pixels, row after row
    dark = bytes(1 if v < 170 else 0 for v in range(256))  # ink is darker than 170
    rows = [data[y * w:(y + 1) * w:2].translate(dark).count(1) for y in range(h)]  # ink on every second column of each row
    floor = int(h * (1 - FOOT_PT / 841.9)) if h > w else h  # a portrait page's footer zone is left out
    body = [y for y, v in enumerate(rows) if v > 10 and y < floor]  # rows of the body with ink
    starts = [y for i, y in enumerate(body) if i == 0 or y - body[i - 1] > 3]  # where each line starts
    gaps = sorted(b - a for a, b in zip(starts, starts[1:]))  # the pitch between lines
    return {"top": body[0] if body else 0, "bottom": body[-1] if body else 0, "lines": len(starts),  # where the ink is, and its lines
            "tail_gap": round(100 * (h - (body[-1] if body else h)) / h, 1),  # the empty foot, in percent of the page
            "pitch": round(100 * gaps[len(gaps) // 2] / h, 2) if gaps else 0}  # the usual line pitch (the median), in percent


def stats_of(pdf: str) -> list:
    """The page_stats of every page of a PDF."""
    import pdftools as P  # page pictures, with poppler or PDFium
    with tempfile.TemporaryDirectory() as tmp:  # the pictures go when measured
        return [page_stats(f) for f in P.render_png(pdf, pathlib.Path(tmp) / "p", dpi=DPI, gray=True)]  # small and grey: only the ink matters


def page_issues(stats: list, rules: dict, application: bool) -> list:
    """The page rules on measured pages: a middle page's empty foot, and an application's last page."""
    out, n = [], len(stats)  # the findings, and how many pages there are
    mid, last = rules.get("mid_gap"), rules.get("fill_last")  # the two thresholds, in percent of the page
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731  a threshold the pack set
    for i, s in enumerate(stats, 1):
        if i == 1 and s["lines"] <= COVER_MAX_LINES:  # a cover is empty by design
            continue
        if i == n:  # the last page ends where the document ends
            if application and num(last) and s["tail_gap"] > last:  # an application's last page left too empty
                need = math.ceil((s["tail_gap"] - last) / s["pitch"]) if s.get("pitch") else 1  # the lines that would fill it
                out.append(issue("last_page_room", gap=s["tail_gap"], limit=last, lines=need))
            continue
        if num(mid) and s["tail_gap"] > mid:  # a hole in the middle
            out.append(issue("page_gap", page=i, gap=s["tail_gap"], limit=mid))
    return out


def summary_issues(pdf: str, titles: list, sections: list) -> list:
    """Each section of `titles` that the form printed ends on page 1: its title is on page 1, and page 2 holds none of its
    rows (a period) before the next section's title."""
    import pdftools as P  # the text of one page
    out = []  # the findings
    names = [x for x in titles or [] if isinstance(x, str)]  # the titles the pack names
    for k, title in enumerate(sections):  # the sections in print order
        if title not in names:  # not one the pack keeps on page 1
            continue
        nxt = sections[k + 1] if k + 1 < len(sections) else None  # the section after it
        p1 = P.text(pdf, first=1, last=1)  # page 1's words
        if not re.search(rf"^\s*{re.escape(title)}", p1, re.M):  # not on page 1 at all
            out.append(issue("summary_spills", title=title))
            continue
        p2 = P.text(pdf, first=2, last=2) if P.info(pdf)["pages"] > 1 else ""  # page 2's words, when there is a page 2
        m = re.search(rf"^\s*{re.escape(nxt)}", p2, re.M) if nxt else None  # the next section on page 2
        head = p2[:m.start()] if m else ""  # what page 2 holds before it
        if re.search(r"\d{4}\.\d{2}\s*[-~]\s*(?:\d{4}\.\d{2}|재직|Present)", head):  # a row of it
            out.append(issue("summary_spills", title=title))
    return out


def _lum(p) -> float:
    """The brightness of a pixel."""
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


def _rgb(hexcolor: str) -> tuple:
    """A colour written as hex (EEF3F9) as an RGB triple."""
    s = str(hexcolor or "").lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) if re.fullmatch(r"[0-9A-Fa-f]{6}", s) else (0, 0, 0)


def _near(p, c, tol: int = 3) -> bool:
    """A pixel of this colour, within the rounding a renderer adds."""
    return all(abs(p[i] - c[i]) <= tol for i in range(3))


def text_center(px, x0: int, x1: int, y0: int, y1: int, band: tuple):
    """The middle of the ink between x0 and x1 inside a band: (the ink's top + its baseline) / 2, the baseline being the last
    row with at least a quarter of the fullest row's ink (descenders aside). None when there is no ink."""
    bl = _lum(band)  # the band's own brightness
    prof = [sum(1 for x in range(x0, x1) if _lum(px[x, y]) < bl - 60) for y in range(y0, y1 + 1)]  # ink per row, clearly darker than the band
    mx = max(prof) if prof else 0  # the fullest row
    if mx == 0:  # no ink: nothing to place
        return None
    top = next(i for i, v in enumerate(prof) if v > 0)  # the ink's top
    base = max(i for i, v in enumerate(prof) if v >= 0.25 * mx)  # its baseline, descenders aside
    return y0 + (top + base) / 2  # the middle the eye reads


def _runs(ys: list) -> list:
    """Consecutive rows as (first, last) pairs."""
    out, s, p = [], None, None  # the runs, the current run's first and last row
    for y in ys:
        if s is None:  # the first row
            s = p = y
        elif y == p + 1:  # the run goes on
            p = y
        else:  # a gap: the run ends, another starts
            out.append((s, p))
            s = p = y
    if s is not None:  # the last run
        out.append((s, p))
    return out


def band_issues(pdf: str, parts: dict, limit: float) -> list:
    """Every company band's logo, name, place, period and badge, and every about-me band's title, at its band's middle."""
    import pdftools as P  # page pictures and word boxes
    from PIL import Image  # pixels
    band, rail, badge = _rgb(parts.get("band")), _rgb(parts.get("rail")), _rgb(parts.get("badgeFill"))
    pt = BAND_DPI / 72  # pixels per point
    words = CL.words_of(pdf)  # (page, line, text, x0, y0, x1, y1) in points
    out, found = [], 0  # the findings, and how many company bands the pages showed
    with tempfile.TemporaryDirectory() as tmp:  # the pictures go when measured
        pics = P.render_png(pdf, pathlib.Path(tmp) / "b", dpi=BAND_DPI)  # in colour: the bands are found by theirs
        for pi, f in enumerate(pics):  # each page
            im = Image.open(f).convert("RGB")
            w, h = im.size  # its size in pixels
            px = im.load()  # its pixels
            cl = int(LEFT_TW / 1440 * BAND_DPI)  # the body's left edge
            full = lambda y: _near(px[cl + int(1 * pt), y], band) and _near(px[cl + int(2 * pt), y], band)  # noqa: E731  band colour at the edge
            bands, y = [], 0
            while y < h:  # the company bands: runs of the band's colour at the body's edge
                if full(y):  # a band starts
                    y0 = y
                    while y < h and full(y):  # down to its foot
                        y += 1
                    if 12 <= (y - y0) / pt <= BAND_H + 2.5:  # a band's height, with a logo or without
                        bands.append((y0, y - 1))
                y += 1
            ws = [x for x in words if x[0] == pi]  # this page's words
            for b0, b1 in bands:  # each company band
                found += 1  # one more seen
                bc = (b0 + b1) / 2  # the band's middle
                inb = [x for x in ws if b0 / pt - 1 < (x[4] + x[6]) / 2 < b1 / pt + 1]  # its words
                name = [x for x in inb if x[3] < w / pt / 2]  # the left half: the company
                right = [x for x in inb if x[3] >= w / pt / 2]  # the right half: place and period
                period = [x for x in right if DATE_WORD.match(x[2])]  # the period and the tenure
                place = [x for x in right if x not in period]  # the place before them
                label = " ".join(x[2] for x in name)[:24]  # the company, for the finding
                if abs((b1 - b0) / pt - BAND_H) < 2.5:  # a logo band: its logo sits in the middle too
                    x0, x1 = int(cl + 6 * pt), int(cl + 20 * pt)  # the logo's column (layout.js floats it 4 pt in, 18 pt wide)
                    ink = lambda yy: any(not _near(px[x, yy], band) and not _near(px[x, yy], (255, 255, 255)) for x in range(x0, x1))  # noqa: E731  a row of the logo
                    c = (b0 + b1) // 2  # the band's middle row
                    if ink(c):  # a logo there
                        a, z = c, c  # its run of rows through the middle
                        while a > 0 and ink(a - 1):  # up to its top
                            a -= 1
                        while z < h - 1 and ink(z + 1):  # down to its foot
                            z += 1
                        over, off = max(b0 - a, z - b1, 0) / pt, ((a + z) - (b0 + b1)) / 2 / pt  # out of the band, and off its middle, in points
                        if over > 0.5 or abs(off) > 1.0:  # how far a logo may stick out or sit off the band's middle
                            out.append(issue("band_logo", page=pi + 1, name=label, over=round(over, 1), off=round(off, 1)))
                for which, part, grp in (("name", t("part_name"), name), ("place", t("part_place"), place), ("period", t("part_period"), period)):
                    if not grp:  # a band without a place has two parts
                        continue
                    g0, g1 = int(min(x[3] for x in grp) * pt), int(max(x[5] for x in grp) * pt)  # the part's words, in pixels
                    tc = text_center(px, g0, g1, b0, b1, band)  # where its ink's middle is
                    if tc is not None and abs(tc - bc) / pt > limit:  # off the middle
                        out.append(issue("band_off", page=pi + 1, name=label, part=part, which=which, off=round((tc - bc) / pt, 1), limit=limit))
                if name and any(b.get("badge") for b in parts.get("bands") or []):  # a badge: its box and its letters
                    nx = int(max(x[5] for x in name) * pt)  # where the company's name ends
                    pts = [(x, yy) for yy in range(b0, b1 + 1) for x in range(nx, min(w, nx + int(80 * pt)), 2) if _near(px[x, yy], badge, 30)]  # the badge's box, within 80 pt
                    if len(pts) > 20:  # a box is there
                        bx0, bx1 = min(p[0] for p in pts), max(p[0] for p in pts)  # its left and right
                        by0, by1 = min(p[1] for p in pts), max(p[1] for p in pts)  # its top and foot
                        white = [yy for yy in range(by0, by1 + 1) if any(min(px[x, yy]) > 225 for x in range(bx0, bx1))]  # the rows of its white letters
                        boff = ((by0 + by1) / 2 - bc) / pt  # the box off the band's middle
                        inner = ((white[0] - by0) - (by1 - white[-1])) / pt if white else 99  # the letters off the box's middle
                        if abs(boff) > limit or abs(inner) > 1.0:  # either one
                            out.append(issue("band_off", page=pi + 1, name=label, part=t("part_badge"), which="badge", off=round(boff, 1), limit=limit))
            # about-me bands: the rail's colour at the edge, the band's a little further in
            rows = [yy for yy in range(h) if _near(px[cl + int(1 * pt), yy], rail, 40) and _near(px[cl + int(8 * pt), yy], band)]
            for r0, r1 in _runs(rows):  # each such band
                if not 10 < (r1 - r0) / pt < 20:  # a stage band's height (an accent bar elsewhere is not one)
                    continue
                inb = [x for x in ws if r0 / pt - 1 < (x[4] + x[6]) / 2 < r1 / pt + 1]  # its title's words
                if not inb:  # no title: nothing to place
                    continue
                g0, g1 = int(min(x[3] for x in inb) * pt), int(max(x[5] for x in inb) * pt)  # the title, in pixels
                tc = text_center(px, g0, g1, r0, r1, band)  # its ink's middle
                if tc is not None and abs(tc - (r0 + r1) / 2) / pt > limit:  # off the band's middle
                    out.append(issue("band_off", page=pi + 1, name=" ".join(x[2] for x in inb)[:24], part=t("part_title"), which="title",
                                     off=round((tc - (r0 + r1) / 2) / pt, 1), limit=limit))
    want = len(parts.get("bands") or [])  # the bands the typesetting set
    if want and found != want:  # a band the measurement missed is said, never passed over
        out.append(issue("band_count", found=found, want=want))
    return out


def months_of(right: str, today: datetime.date | None = None) -> int | None:
    """A band's tenure in months, both ends counted, from its period (an open end runs to today)."""
    m = PERIOD.search(right or "")  # its period
    if not m:  # none written: no tenure to weigh
        return None
    y1, m1 = int(m.group(1)), int(m.group(2))  # the start
    if m.group(3):  # a closed period
        y2, m2 = int(m.group(3)), int(m.group(4))
    else:  # still there: up to this month
        today = today or datetime.date.today()
        y2, m2 = today.year, today.month
    return max(1, (y2 - y1) * 12 + (m2 - m1) + 1)  # both ends counted


class Unmeasured(ValueError):
    """The lines per company could not be measured: the finding that says why (an Issue)."""


def line_counts(layout_text: str, parts: dict) -> dict:
    """The lines of the experience section from each company's band to the next, footer lines and empty lines aside:
    {band index: lines}. Unmeasured, carrying the finding, when the section or a band cannot be found once."""
    bands = parts.get("bands") or []  # the company bands, in print order
    sections = parts.get("sections") or []  # the section titles, in print order
    k = bands[0].get("section", -1) if bands else -1  # the section the companies stand in
    title = sections[k] if 0 <= k < len(sections) else None  # its title
    nxt = sections[k + 1] if 0 <= k + 1 < len(sections) else None  # the title it ends at
    lines = [ln for ln in layout_text.split("\n") if ln.strip() and not re.match(r"^\s*(\S.*?)?\s*\d+\s*/\s*\d+\s*$", ln)]  # the footer is "<name>  N / M"
    a = next((i for i, ln in enumerate(lines) if title and ln.strip().startswith(title)), None)  # where the section starts
    if a is None:  # its title is not on the pages
        raise Unmeasured(issue("volume_section", title=title or ""))
    b = next((i for i, ln in enumerate(lines) if i > a and nxt and ln.strip().startswith(nxt)), len(lines))  # and where it ends
    body = lines[a + 1:b]  # its lines
    heads = []  # (the band's line, the band)
    for j, bd in enumerate(bands):  # each company
        m = PERIOD.search(bd.get("right") or "")  # the band's period: its line holds the name and the start
        start = f"{m.group(1)}.{m.group(2)}" if m else None  # its first month, as printed
        hit = [i for i, ln in enumerate(body) if bd.get("name") and bd["name"] in ln and (not start or start in ln)]  # the lines that are its band
        if len(hit) != 1:  # not found, or found twice: the count would be a guess
            raise Unmeasured(issue("volume_band", name=bd.get("name") or "", n=len(hit)))
        heads.append((hit[0], j))
    heads.sort()  # in the order they print
    return {j: (heads[n + 1][0] if n + 1 < len(heads) else len(body)) - i for n, (i, j) in enumerate(heads)}  # band to band


def volume_issues(counts: dict, months: dict, names: dict, limit: float) -> list:
    """The volume rules on measured lines: {band: lines}, {band: months}, {band: name}."""
    keys = [k for k in counts if months.get(k)]  # the companies with a tenure to weigh
    if len(keys) < 2:  # one company is its own median
        return []
    dens = {k: counts[k] / months[k] for k in keys}  # lines per month
    med = statistics.median(dens.values())  # the usual density
    out = []  # the findings
    for a in keys:  # every pair
        for b in keys:
            if months[a] <= months[b] * SHORTER and counts[a] > counts[b]:  # clearly shorter, and more lines
                out.append(issue("volume_order", short=names[a], m_short=months[a], n_short=counts[a], long=names[b], m_long=months[b], n_long=counts[b]))
    for k in keys:  # each company's density
        if med and dens[k] > med * limit:  # more than the pack allows over the median
            out.append(issue("volume_density", org=names[k], density=round(dens[k], 2), times=round(dens[k] / med, 2), median=round(med, 2), limit=limit))
    return out


def check(pdf: str, parts: dict, pack: dict, application: bool) -> list:
    """The page rules the pack sets, on one typeset resume. parts: the sidecar's (an empty one when the typesetting left none:
    the rules that need it are not read); application: an edition for one posting (fill_last and summary_first are for those)."""
    rules = pack.get("pages") if isinstance(pack.get("pages"), dict) else {}  # the pack's page rules
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731  a threshold the pack set
    out = []  # the findings
    if num(rules.get("mid_gap")) or (application and num(rules.get("fill_last"))):  # the pages' feet, measured only when a rule asks
        out += page_issues(stats_of(pdf), rules, application)
    if application and rules.get("summary_first") and parts.get("sections"):  # the sections that end on page 1
        titles = rules["summary_first"] if isinstance(rules["summary_first"], list) else []
        out += summary_issues(pdf, titles, parts["sections"])
    if num(rules.get("bands")) and parts.get("bands"):  # the bands' middles
        out += band_issues(pdf, parts, float(rules["bands"]))
    if num(rules.get("volume")) and parts.get("bands"):  # the lines per company
        import pdftools as P  # the layout text
        try:
            counts = line_counts(P.text(pdf, layout=True), parts)
        except Unmeasured as exc:  # not measured: said, never passed over
            return out + [exc.args[0]]
        bands = parts["bands"]  # the companies, in print order
        months = {j: months_of(b.get("right") or "") for j, b in enumerate(bands)}  # each one's tenure, from its period
        out += volume_issues(counts, months, {j: b.get("name") or "" for j, b in enumerate(bands)}, float(rules["volume"]))
    return out


def problems(pack: dict) -> list:
    """What makes the pages object unusable (the style pack's validator refuses the pack on any)."""
    rules = pack.get("pages", {})  # none: nothing to refuse
    if not isinstance(rules, dict):  # the object itself in another shape
        return ["pages"]
    bad = []  # what is wrong, as short lines
    for k in ("fill_last", "mid_gap", "bands", "volume"):  # the thresholds: positive numbers
        v = rules.get(k)
        if v is not None and not (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0):
            bad.append(f"pages.{k}")
    sf = rules.get("summary_first")  # a list of section titles
    if sf is not None and not (isinstance(sf, list) and all(isinstance(x, str) for x in sf)):
        bad.append("pages.summary_first")
    return bad
