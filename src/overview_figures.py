#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Figures and logo tiles for the resume and deck.

It draws the overview figures at a fixed size, in fixed fonts and bar shapes, in the colours of the edition's set (the bars in its
dark colour, the hierarchy's boxes in its band, the tiles' outline in its rule; the built-in navy keeps its own); every value
comes from the profile:
  timeline   career, education and service on one time axis. Labels go inside a bar when they fit (bold name, regular note after
             two spaces, a sub line under it), above the bar for short career bars, else beside it. A long education-only lead-in
             before the first role is squeezed behind a double wave (summary.timeline.break, or found by itself).
             An unfinished degree with fadeTo fades out instead of ending.
  stack      the hierarchy figure: layer name on the left, skills and where they were used on the right (summary.layers).
  logo tiles one square tile per company and school logo: an image is trimmed and padded on a white rounded tile, a monogram
             { text, color } is drawn as initials. The resume tables, the company bands and the deck chapters use the same tile.

The profile is read through src/profile_loader.js (one loader for the resume, the deck and the figures).

A blind edition (OFFEROWL_BLIND=1) draws what its table covers (src/blind.py) as bars of the text's own width in the table's
mask_fill, in the timeline and the hierarchy figure alike, so a figure keeps its layout and shows no covered word. A figure
is a picture: the words are never drawn under the bar. The logo tiles are drawn as they are.

Square corners (OFFEROWL_CORNERS=square, src/corners.py, the person's setting `corners` in the panel) draw the bars, the boxes
and the tiles with square corners: an image's tile is a white square with the same light outline, and a finished rounded
tile brought in as a logo gets its plate squared around the logo, which stays as it is. Unset, every picture is the same as before.

  python3 src/overview_figures.py <profile.json> <out name> [ko|en]
    -> output/_figures/<out>_timeline[_en].png, <out>_stack[_en].png, <out>_logo_<id>.png
"""
import datetime  # the end of ongoing bars
import json  # the normalized profile and themes
import math  # the wave of a squeezed axis
import os  # environment
import pathlib  # paths
import re  # year-month parsing and label parts
import subprocess  # the profile loader runs in node
import sys  # arguments

from PIL import Image, ImageDraw, ImageFont  # drawing

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
sys.path.insert(0, str(ROOT / "src"))  # blind.py beside this file, however it was started
import blind  # noqa: E402  the blind edition's table and its bars
import corners  # noqa: E402  the corners setting: rounded boxes, or square ones
BT = blind.load() if blind.on() else None  # the table this run covers with, when it makes a blind edition
OUT = ROOT / "output" / "_figures"  # the overview figures
FD = str(ROOT / "fonts") + "/"  # Pretendard, the resume font
S = 4  # drawing scale; the document places the image at 1/S
W = 694 * S  # body width 10406 twips = 694 px at 96 dpi
NAVY, INK, GREY, FAINT, TINT = (31, 58, 95), (31, 31, 31), (107, 107, 107), (200, 205, 212), (232, 238, 245)  # the figure colors
LABELS = {"ko": ("경력", "학력", "병역"), "en": ("Career", "Study", "Service")}  # row names
WARN = []  # notes raised while drawing (dropped bars, shortened labels)
TILE = 512  # logo tile side in pixels (about 6 mm in the document)
LOGO_FORMATS = ("PNG", "JPEG", "WEBP", "GIF", "BMP", "ICO")  # the kinds a logo comes in, as Pillow names them: no other decoder is reached
TILE_BORDER = (211, 220, 232)  # the tile's light outline
INSET = 40  # a finished tile's inside (its logo) starts this far in on every side of TILE, past its rounded corner and its outline


def hex_rgb(h):
    """'#1F3A5F' or '1F3A5F' to an RGB tuple, None when it is not a color"""
    h = str(h or "").lstrip("#")  # the leading mark is optional
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if re.fullmatch(r"[0-9A-Fa-f]{6}", h) else None


def theme_set():
    """The colour set the figures are drawn in: OFFEROWL_THEME, else OFFEROWL_FIG_THEME (the edition's, which the build names),
    else navy, from src/themes.json with the sets of OFFEROWL_THEME_FILE over it. None for the built-in navy, whose figures keep
    the colours above exactly."""
    name = os.environ.get("OFFEROWL_THEME") or os.environ.get("OFFEROWL_FIG_THEME") or "navy"  # the theme the build uses
    themes = json.loads((ROOT / "src" / "themes.json").read_text(encoding="utf-8"))  # built-in themes
    if os.environ.get("OFFEROWL_THEME_FILE"):  # a user's theme file adds to or overrides the built-in ones
        themes.update(json.loads(pathlib.Path(os.environ["OFFEROWL_THEME_FILE"]).read_text(encoding="utf-8")))
    elif name == "navy":  # the built-in navy keeps the colors above exactly
        return None
    t = themes.get(name)
    if not t:
        raise SystemExit(f"unknown theme '{name}'")
    return t


def theme_navy():
    """The bar color: the theme's name-cell color, or a darker theme color when that one is light (light bars got light text)"""
    t = theme_set()  # the set, None for the built-in navy
    if t is None:  # its own navy, exactly
        return NAVY
    for key in ("nameFill", "sec", "acc"):  # darkest usable first
        c = hex_rgb(t.get(key))
        if c and (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) < 140:  # dark enough for white text
            return c
    return INK  # no dark color in the theme: near black


def theme_ramp():
    """The set's own sequential tones, light to dark (its optional keys ramp1, ramp2, ... in order), or None when it names none:
    the career bars and the hierarchy's plates are drawn in them, so a set whose dark colour is black still draws its figures in
    its own hue instead of greys (a black-based set otherwise draws both figures as shades of black). The built-in navy
    names none and keeps its colours exactly."""
    t = theme_set()  # the set, None for the built-in navy
    if t is None:
        return None
    steps = []
    while hex_rgb(t.get(f"ramp{len(steps) + 1}")):  # ramp1, ramp2, ... until the first one missing
        steps.append(hex_rgb(t[f"ramp{len(steps) + 1}"]))
    return steps if len(steps) >= 3 else None  # fewer than three steps make no ramp


def contrast_white(c):
    """WCAG contrast of white words on c"""
    lum = [(v / 255) / 12.92 if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in c]
    return 1.05 / (0.2126 * lum[0] + 0.7152 * lum[1] + 0.0722 * lum[2] + 0.05)


def ramp_pick(ramp, n):
    """n colours from the ramp's steps that carry white words at 4.5:1 (light to dark), spread evenly, blended between two steps
    when n is more than the ramp has"""
    dark = [c for c in ramp if contrast_white(c) >= 4.5] or ramp[-1:]
    if n <= 1:
        return [dark[-1]]
    out = []
    for i in range(n):
        p = i * (len(dark) - 1) / (n - 1)  # where along the dark steps
        a, b, t = dark[int(p)], dark[min(len(dark) - 1, int(p) + 1)], p - int(p)
        out.append(tuple(round(x + (y - x) * t) for x, y in zip(a, b)))
    return out


def theme_tones():
    """(the hierarchy figure's pale boxes, the tiles' outline): TINT and TILE_BORDER for the built-in navy, the set's band and its
    rule for any other, so a figure in another colour keeps no pale blue"""
    t = theme_set()  # the set, None for the built-in navy
    if t is None:  # its own tones, exactly
        return TINT, TILE_BORDER
    return hex_rgb(t.get("band")) or TINT, hex_rgb(t.get("rule")) or TILE_BORDER  # a set without one keeps the figure's own


def font(px, bold=False):
    """Pretendard at a size in document pixels"""
    return ImageFont.truetype(FD + ("Pretendard-Bold.ttf" if bold else "Pretendard-Regular.ttf"), round(px * S))


def mix(c, t):
    """Blend c toward white by t (0 keeps c, 1 is white)"""
    return tuple(round(a + (255 - a) * t) for a in c)


def ym(s):
    """Year-month to a fractional year: '2022.03', '2022-03', '2022/3', '2022년 3월', '2022'. None when unreadable"""
    m = re.search(r"((?:19|20)\d{2})(?:\s*[.\-/년]\s*(\d{1,2}))?", str(s or ""))
    if not m:
        return None
    mon = int(m.group(2)) if m.group(2) and 1 <= int(m.group(2)) <= 12 else 1  # January when the month is missing
    return int(m.group(1)) + (mon - 1) / 12


def now_y():
    """This month as a fractional year (the end of ongoing bars)"""
    t = datetime.date.today()
    return t.year + (t.month - 1) / 12


def span(x):
    """(start, end) of an item in years. end null is today, empty or missing ends early in the start year. None when unreadable.
    A bar runs to the end of its last month"""
    a = ym(x.get("start"))
    if a is None:
        return None
    if x.get("fadeTo"):  # an unfinished degree fades out at fadeTo
        b = ym(x["fadeTo"])
    else:
        e = x.get("end", "")
        b = now_y() if e is None else (ym(e) if e else min(now_y(), a + 0.5))
    if b is None or b < a:
        return None
    return a, b + 1 / 12  # through the last month


def load_profile(path, lang, job=None):
    """The normalized profile from src/profile_loader.js (the one loader every document uses), read with the edition's
    choices (job.json: a role's long title on the timeline, titleView) when one is given"""
    r = subprocess.run(["node", str(ROOT / "src" / "profile_loader.js"), str(path), lang, *([str(job)] if job else [])],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:  # a profile the loader rejects stops the figures with its reason
        raise SystemExit("profile: " + (r.stderr.strip().splitlines() or ["unreadable"])[-1])
    return json.loads(r.stdout)


def lanes(items):
    """Split items whose periods overlap into lanes (an item joins the first lane that ended before it starts).
    A shared boundary month (one role ends the month the next begins) is not an overlap: such roles stay
    on one row and the later bar covers the shared month"""
    ends, out = [], []
    for it, (a, b) in sorted(items, key=lambda x: x[1][0]):
        for i, e in enumerate(ends):
            if a >= e - 1 / 12 - 1e-6:  # starting in the month the lane's last bar ends still fits the lane
                ends[i] = b
                out.append((i, it, (a, b)))
                break
        else:
            ends.append(b)
            out.append((len(ends) - 1, it, (a, b)))
    return out, max(1, len(ends))


def parts(t):
    """'Name  note' (two spaces) splits into a bold head and regular rest"""
    return [p for p in re.split(r" {2,}", str(t or "")) if p]


def label_w(d, t, z):
    """Width of a label line: bold head, regular rest, half a character between parts"""
    ps = parts(t)
    if not ps:
        return 0
    return d.textlength(ps[0], font=font(z, True)) + sum(d.textlength(q, font=font(z)) for q in ps[1:]) + (len(ps) - 1) * z * 0.5 * S


def draw_text(d, xy, s, fill, f, fl=None):
    """Draw one text. In a blind edition what the table covers is drawn as bars of its own width (src/blind.py), never as the
    words; fl carries the flags when they come from a longer text (a shortened label keeps its full label's)"""
    if BT is None:  # an ordinary edition: the words
        d.text(xy, s, fill=fill, font=f)
    else:  # the words, with bars where the table covers them
        blind.draw(d, xy, s, f, fill, BT, fl)


def covered(t, full=None):
    """The blind edition's flags of a label (one per character, True under a bar), read on the full label when t is a shortened
    one ending in '…', so a cut never splits a covered name into words a pattern no longer finds. None when not blind"""
    if BT is None:  # nothing is covered
        return None
    if full and t.endswith("…"):  # shortened: the flags of what it kept, and none for the ellipsis
        return blind.flags(full, BT)[:len(t) - 1] + [False]
    return blind.flags(t, BT)  # as it is


def put_label(d, x, y_top, t, sub, ink, sub_ink, z=12, zs=9.5, anchor="left", gap=None, full=None):
    """Draw a label line and its optional sub line from y_top (document px); anchor 'right' ends both lines at x. gap is
    how far below the label's top the sub line starts (default z + 1.5). full is the label before it was shortened"""
    lw = label_w(d, t, z)
    lx = x - lw if anchor == "right" else x
    fl, at = covered(t, full), 0  # the blind edition's flags over the whole label; where the next part is looked for
    for k, q in enumerate(parts(t)):  # bold head, regular rest
        f = font(z, k == 0)
        i = t.index(q, at)  # where this part sits in the label, so a pattern that spans two parts covers both
        draw_text(d, (lx, y_top * S), q, ink, f, fl[i:i + len(q)] if fl else None)
        at = i + len(q)  # the next part comes after it
        lx += d.textlength(q, font=f) + z * 0.5 * S
    if sub:
        fs = font(zs)
        sx = x - d.textlength(sub, font=fs) if anchor == "right" else x
        draw_text(d, (sx, (y_top + (z + 1.5 if gap is None else gap)) * S), sub, sub_ink, fs)


def timeline(prof, lang, path, navy, active=None, width=694, active_edu=None):
    """Career, education and service on one axis. Values come from the profile.
    active (a role key) draws a chapter variant for the deck: that role's bar dark, the other roles light, no service row.
    active_edu (an education key) draws the variant for a chapter that is not a company (research done during a degree): that study
    bar dark and every role light.
    width is the figure width in document pixels: 694 for the resume body, wider for the 16:9 deck (a flatter figure)"""
    ramp = theme_ramp()  # the set's own tones for the career bars, None for a set that names none (navy keeps its own)
    accent = None
    if ramp:  # a chapter's own bar: the set's accent when white words read on it, else a middle dark step of the ramp
        acc2 = hex_rgb((theme_set() or {}).get("acc2"))
        accent = acc2 if acc2 and contrast_white(acc2) >= 4.5 else ramp_pick(ramp, 5)[1]
    if active_edu is not None and active is None:
        active = "\0none"  # a chapter variant with no role dark
    W = width * S  # the canvas width (shadows the module's resume width)

    def collect(xs, what, name):
        got = []
        for x in xs or []:
            if not isinstance(x, dict) or not x.get("start"):
                continue
            sp = span(x)
            if sp is None:
                WARN.append(f"{what} '{name(x)}': unreadable period, left out of the timeline ({x.get('start')} ~ {x.get('end')})")
                continue
            got.append((x, sp))
        return got

    roles = collect(prof.get("roles"), "role", lambda x: x.get("org"))
    edus = collect([e for e in prof.get("education") or [] if e.get("timeline", True)], "education", lambda x: x.get("school"))
    svc = collect([prof["service"]] if isinstance(prof.get("service"), dict) and prof["service"].get("start") and active is None else [], "service", lambda x: x.get("label"))
    if not roles and not edus:
        return None
    allsp = [sp for _, sp in roles + edus + svc]
    last = max(b for _, b in allsp)  # the latest end on the axis
    # whole first year; the axis runs to late in the last year (its tick label and a label above the last bar fit), or a
    # little past the latest end when that is later in the year
    t0, t1 = math.floor(min(a for a, _ in allsp)), (math.floor(last) + 0.9 if last <= math.floor(last) + 0.8 else last + 0.1)

    # Axis break: squeeze an education-only lead-in before the first role behind a double wave (the study
    # years are squeezed so they do not dwarf the career). summary.timeline.break sets the year; otherwise it is found when the
    # lead-in is longer than three years
    tl = (prof.get("summary") or {}).get("timeline") or {}
    first_role = min((a for _, (a, _) in roles), default=None)
    tb = None
    if tl.get("break"):
        tb = float(ym(str(tl["break"])) or 0) or None
    elif first_role is not None and first_role - t0 > 2:  # a lead-in of more than two study years
        tb = float(math.floor(first_role))
    if tb is not None and not (t0 < tb < t1):
        tb = None  # a break outside the axis means nothing
    L, R = 54 * S, 8 * S
    BRK = 36 * S  # the squeezed span's width (the wave sits 4 px clear of both year labels)
    XB = L + BRK / 2  # the wave's x

    def X(t):
        if tb is None:
            return L + (t - t0) / (t1 - t0) * (W - R - L)
        if t < tb:
            return L + (t - t0) / (tb - t0) * BRK
        return L + BRK + (t - tb) / (t1 - tb) * (W - R - L - BRK)

    role_l, nr = lanes(roles)
    edu_l, ne = lanes(edus) if edus else ([], 0)
    svc_l, ns = lanes(svc) if svc else ([], 0)
    edu_two = any(e.get("chartSub") or (not e.get("chartTitle") and e.get("major")) for e, _ in edus)  # education bars carry a sub line when any entry has one
    LH_C, LH_E, LH_S, GAP = 32, (32 if edu_two else 20), 20, 4  # row heights: career, education, service; gap between lanes

    im0 = Image.new("RGB", (W, 10))
    d0 = ImageDraw.Draw(im0)  # a scratch canvas to measure labels before sizing the image

    def career_label(it):
        return it.get("short") or it.get("org") or "", it.get("chart") or ""

    # Career labels that do not fit inside their bar go above it; reserve that room above the career row
    def fits(x0, x1, t, sub, z=12, zs=9.5):
        return max(label_w(d0, t, z), d0.textlength(sub, font=font(zs)) if sub else 0) + 8 * S <= x1 - x0

    above = set()
    for lane, it, (a, b) in role_l:
        name, sub = career_label(it)
        if not fits(X(a), X(b), name, sub):
            above.add(id(it))
    # Row geometry: the career row at 32 when labels sit above it (14 otherwise), 8 between row blocks,
    # the axis 12 below the last row and 18 for the year labels (career 32, study 72, service 112, height 162 with all three)
    top = 32 if above else 14
    blocks, y = [], top
    for key, lay, n, h in (("career", role_l, nr, LH_C), ("edu", edu_l, ne, LH_E), ("svc", svc_l, ns, LH_S)):
        if n:
            blocks.append((key, y, h, n, lay))
            y += n * h + (n - 1) * GAP + 8
    H = (y - 8 + 12 + 18) * S
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    axis_y = H - 18 * S

    def wave(ya, yb):
        """A double wave at XB from ya to yb, blank between the lines (marks the squeezed span on the axis and bars)"""
        WA, WP, WG = 1.5 * S, 7 * S, 3.5 * S  # amplitude, period, gap between the two lines
        n = int((yb - ya) / S * 2) + 1
        ys = [ya + (yb - ya) * i / max(1, n - 1) for i in range(n)]
        off = [WA * math.sin(2 * math.pi * (yy - ya) / WP) for yy in ys]
        left = [(XB - WG / 2 + o, yy) for o, yy in zip(off, ys)]
        right = [(XB + WG / 2 + o, yy) for o, yy in zip(off, ys)]
        d.polygon(left + right[::-1], fill="white")
        for line in (left, right):
            d.line(line, fill=mix(GREY, .40), width=S, joint="curve")

    # Year ticks and faint vertical lines; years inside the squeezed span are not labeled
    years = [y0 for y0 in range(int(t0), int(t1) + 1) if tb is None or y0 >= tb or y0 == int(t0)]
    step = 1 if len(years) <= 15 else 2  # long careers label every other year
    for i, yr in enumerate(years):
        if step == 2 and i % 2 and yr != years[-1]:
            continue
        x = X(yr)
        tw = d.textlength(str(yr), font=font(10))
        if x + tw / 2 > W or x - tw / 2 < 0:  # a year the axis only just reaches (it runs a little past the latest end): its label would be cut by the edge
            continue  # neither its line nor a half label
        d.line([(x, 8 * S), (x, axis_y)], fill=(238, 238, 238), width=S)
        draw_text(d, (x - tw / 2, axis_y + 4 * S), str(yr), GREY, font(10))
    d.line([(L, axis_y), (W - R, axis_y)], fill=FAINT, width=S)
    if tb is not None:
        wave(axis_y - 5 * S, axis_y + 4 * S)

    names = dict(zip(("career", "edu", "svc"), LABELS[lang]))
    by_recent = sorted(roles, key=lambda x: x[1][0], reverse=True)
    recency = {id(it): i for i, (it, _) in enumerate(by_recent)}
    edu_rank = {id(e): i for i, (e, _) in enumerate(sorted(edus, key=lambda x: x[1][0], reverse=True))}  # 0 is the newest study

    for key, by, h, n, lay in blocks:
        draw_text(d, (4 * S, (by + (n * (h + GAP) - GAP) / 2 - 7) * S), names[key], navy, font(12, True))
        per_lane = {}
        for lane, it, sp in lay:
            per_lane.setdefault(lane, []).append((it, sp))
        for lane, bars in per_lane.items():
            bars.sort(key=lambda x: x[1][0])
            yy = by + lane * (h + GAP)
            for k, (it, (a, b)) in enumerate(bars):
                x0, x1 = X(a), max(X(a) + 2 * S, X(b) - 1.5 * S)  # end of the last month, a small gap to the neighbor
                if k + 1 < len(bars):  # a shared boundary month: stop short of the next bar in the lane
                    x1 = max(x0 + 2 * S, min(x1, X(bars[k + 1][1][0]) - 1.5 * S))
                fade = key == "edu" and bool(it.get("fadeTo"))
                if key == "career" and active is not None:  # chapter variant: this chapter dark, the others light grey
                    color = (accent if it.get("key") == active else mix(GREY, .78)) if ramp else (navy if it.get("key") == active else mix(GREY, .78))
                    label, sub = career_label(it)
                elif key == "career" and ramp:  # the set's own ramp: newest the darkest step, each older one a step lighter
                    color = ramp[max(0, len(ramp) - 1 - recency[id(it)])]
                    label, sub = career_label(it)
                elif key == "career":  # newest darkest, older lighter (the reference shades run 0 to .70)
                    color = mix(navy, min(.70, recency[id(it)] * .16))
                    label, sub = career_label(it)
                elif key == "edu" and active_edu is not None and it.get("key") == active_edu:  # the study this chapter belongs to, dark
                    color = accent if ramp else navy
                    label = it.get("chartTitle") or "  ".join(v for v in (it.get("degree"), it.get("school")) if v)
                    sub = it.get("chartSub") if it.get("chartTitle") else (it.get("major") or "")
                elif key == "edu":  # newest study darkest; the oldest of three or more lighter
                    color = mix(GREY, .75 if edu_rank[id(it)] >= 2 else .62)
                    # The figure's own short labels when the profile has them ('Degree  School' and the major), else the table's words
                    label = it.get("chartTitle") or "  ".join(v for v in (it.get("degree"), it.get("school")) if v)
                    sub = it.get("chartSub") if it.get("chartTitle") else (it.get("major") or "")
                else:
                    color, label, sub = mix(GREY, .70), it.get("label", ""), ""
                if fade:  # the bar fades toward white instead of ending
                    for i in range(int(x1 - x0)):
                        d.line([(x0 + i, yy * S), (x0 + i, (yy + h) * S)], fill=mix(color, i / max(1, x1 - x0)))
                else:  # the bar, its corners as the run asks (src/corners.py)
                    corners.box(d, [x0, yy * S, x1, (yy + h) * S], 3 * S, fill=color)
                tx = x0 + 4 * S
                if tb is not None and x0 < XB < x1:  # a bar through the squeezed span is cut by the wave, its text starts after it
                    wave((yy - 2) * S, (yy + h + 2) * S)
                    tx = XB + 1.75 * S + 1.5 * S + 4 * S
                dark = contrast_white(color) >= 4.5 if ramp else sum(color) < 450  # a ramp's bar: white words only where they read
                ink = "white" if dark and not fade else navy
                sub_ink = ink  # the sub line takes the label's color
                z, zs = 12, 9.5  # one size for every row's label, the service bar's too
                if key == "svc":
                    sub = ""
                room = (W - R - tx) if fade else (x1 - tx)  # a fading bar may carry its label past its end
                two = bool(sub) and h >= 30
                need = max(label_w(d, label, z), d.textlength(sub, font=font(zs)) if two else 0) + 4 * S
                block_h = (z + 1.5 + zs + 2) if two else z + 1
                if need <= room:  # inside the bar
                    put_label(d, tx, yy + (h - block_h) / 2, label, sub if two else "", ink, sub_ink, z, zs)
                    continue
                if key == "career" and id(it) in above:  # above the bar, aligned to its start, or to its end near the right edge
                    tw = max(label_w(d, label, z), d.textlength(sub, font=font(zs)) if sub else 0)
                    ytop = yy - 26 if sub else yy - z - 3  # two lines sit a little tighter above a bar than inside one
                    # both lines start at one x: the bar's start, or as far left as keeps the wider line inside the right edge
                    put_label(d, min(x0, W - R - tw), ytop, label, sub, navy, GREY, z, zs, gap=11.5 if sub else None)
                    continue
                # Beside the bar: right free space, then left free space (labels above would hit the row above)
                short = it.get("chartShort") if key == "edu" else ""
                if short and label_w(d, short, z) + 4 * S <= room:  # the education's short label fits inside
                    put_label(d, tx, yy + (h - (z + 1)) / 2, short, "", ink, sub_ink, z, zs)
                    continue
                left_free = X(bars[k - 1][1][1]) + 6 * S if k else L
                right_free = X(bars[k + 1][1][0]) - 6 * S if k + 1 < len(bars) else W - R
                one = label_w(d, label, z)
                cy = yy + (h - (z + 1)) / 2
                if right_free - (x1 + 4 * S) >= one:
                    put_label(d, x1 + 4 * S, cy, label, "", INK, GREY, z, zs)
                elif (x0 - 4 * S) - left_free >= one:
                    put_label(d, x0 - 4 * S, cy, label, "", INK, GREY, z, zs, anchor="right")
                else:  # no room anywhere: shorten into the larger space and say so
                    room2 = max(x1 - x0 - 8 * S, right_free - (x1 + 4 * S))
                    t = label
                    while t and label_w(d, t + "…", z) > room2:
                        t = t[:-1]
                    inside = x1 - x0 - 8 * S >= right_free - (x1 + 4 * S)
                    put_label(d, tx if inside else x1 + 4 * S, cy, (t + "…") if t else "", "", ink if inside else INK, GREY, z, zs, full=label)  # a blind edition reads its bars on the whole label
                    WARN.append(f"timeline label '{label}' was shortened (no room beside the bar)")
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, dpi=(96 * S, 96 * S))
    return path


def stack(prof, lang, path, navy, tint=TINT):
    """Hierarchy figure (the reference stack figure): each layer's name on an arrow plate, the plates stepping out toward the
    bottom like a staircase of layers and darker as they go down, the skills and where they were used in a pale box on the
    right. The plates of equal width drawn from 2026-11-03 read as a plain list; the stepped arrows are the figure the
    author's submitted resumes carried (2026-10-16) and asked for again (2026-11-13). tint: the pale boxes' colour (theme_tones)."""
    layers = (prof.get("summary") or {}).get("layers") or []
    layers = [r for r in layers if isinstance(r, (list, tuple)) and r]
    if not layers:
        return None
    n = len(layers)
    row, gap = 38, 4  # a layer's height and the room between two
    step, tip, pad = 6 * S, 8 * S, 10  # how much shorter each plate above is, the arrow tip's depth, the name's left inset
    H = (row * n + gap * (n - 1)) * S
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    f, ft, fw = font(12.5, True), font(11.5, True), font(10.5)
    rows = [[str(v) for v in (list(item) + ["", "", ""])[:3]] for item in layers]  # name, skills, where
    # the bottom plate's width: a quarter of the figure (English names a little more), and wide enough that every name
    # fits its own plate, the top one being the shortest
    lw = int(W * (0.27 if lang == "en" else 0.25))
    lw = max([lw] + [int(d.textlength(name, font=f) + 2 * pad * S + (n - 1 - i) * step) for i, (name, _, _) in enumerate(rows)])
    right = lw + tip + 7 * S  # the pale boxes start a clear gap past the longest plate's tip (a hair's gap read as a slip: 2026-10-26)
    ramp = theme_ramp()  # the set's own tones, light to dark (None: the plates are shades of its dark colour, as navy's always were)
    plates = ramp_pick(ramp, n) if ramp else None  # the steps that carry white words, lightest at the top
    for i, (name, tech, where) in enumerate(rows):
        y0 = i * (row + gap) * S
        y1 = y0 + row * S
        c = plates[i] if plates else mix(navy, .30 - i * (.30 / max(1, n - 1)))  # lighter at the top, darkest at the bottom; white words keep 4.5:1 on the lightest
        end = lw - (n - 1 - i) * step  # where this plate's body ends: each plate above is shorter
        d.polygon([(0, y0), (end, y0), (end + tip, (y0 + y1) / 2), (end, y1), (0, y1)], fill=c)  # the arrow plate
        b = d.textbbox((0, 0), name, font=f)  # center the name by its ink height (fonts differ in top room)
        draw_text(d, (pad * S, y0 + (row * S - (b[3] - b[1])) / 2 - b[1]), name, "white", f)
        corners.box(d, [right, y0, W, y1], 3 * S, fill=tint)  # the pale box of the skills, its corners as the run asks
        # The two right lines (skills, where) sit as one block centered in the row, 6 apart
        b1, b2 = d.textbbox((0, 0), tech or " ", font=ft), d.textbbox((0, 0), where or " ", font=fw)
        h1, h2, lead = b1[3] - b1[1], b2[3] - b2[1], 6 * S
        top = y0 + (row * S - (h1 + lead + h2)) / 2
        draw_text(d, (right + 12 * S, top - b1[1]), tech, navy, ft)
        draw_text(d, (right + 12 * S, top + h1 + lead - b2[1]), where, GREY, fw)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, dpi=(96 * S, 96 * S))
    return path


def plate(d, **kw) -> None:
    """A tile's plate: a rounded square 1 px inside the picture, as the tiles always were, or under square corners a square
    that fills the picture (no curve to keep clear of its edge). kw (fill, outline, width) goes to Pillow as given."""
    if corners.square():  # square corners: edge to edge
        d.rectangle([0, 0, TILE - 1, TILE - 1], **kw)
    else:  # rounded, asked for exactly as before, so the tile is the same bytes
        d.rounded_rectangle([1, 1, TILE - 2, TILE - 2], radius=88, **kw)


def off_line(p, a, b) -> float:
    """How far colour p lies from the colours between a and b (RGB, the largest channel's distance): 0 for a, for b and for any
    blend of the two. b None: how far p lies from a alone."""
    if b is None:  # one colour only
        return max(abs(p[i] - a[i]) for i in range(3))
    step = [b[i] - a[i] for i in range(3)]  # from a to b
    span = sum(v * v for v in step)  # its length, squared
    t = 0.0 if not span else max(0.0, min(1.0, sum((p[i] - a[i]) * step[i] for i in range(3)) / span))  # the nearest blend, a to b
    return max(abs(p[i] - (a[i] + t * step[i])) for i in range(3))  # its distance from p


def squared(im):
    """A finished rounded tile, scaled to TILE, made square: its plate's colour fills the whole picture, the inside of the old
    plate (INSET in from every side, where the logo is) goes back where it was, pixel for pixel, and the outline the plate had
    is drawn square, as wide and in its colour. None when the picture is not a plate with a logo inside it (a round emblem, a
    logo on a clear ground, a logo that reaches into the plate's edge, a plate rounder than INSET clears): such a picture keeps
    its own shape, and no logo loses a pixel."""
    mid = TILE // 2  # the middle of the top edge, where the outline is read
    colour = im.getpixel((mid, 30))  # the plate's colour, inside the outline

    def same(p, c):
        return p[3] > 200 and max(abs(p[i] - c[i]) for i in range(3)) <= 12  # opaque and one colour, give or take its smoothing

    if colour[3] != 255:  # no opaque plate there: an emblem or a bare logo
        return None
    edge = [im.getpixel((mid, y)) for y in range(30)]  # down from the middle of the top edge: the clear ground, the outline, the plate
    k = next((y for y, p in enumerate(edge) if p[3] > 200), len(edge))  # past the ground and the smoothing of the plate's edge
    ring = []  # the outline's pixels, outside in
    while k < len(edge) and edge[k][3] > 200 and not same(edge[k], colour):  # opaque, and not the plate
        ring.append(edge[k])
        k += 1
    if not all(same(p, colour) for p in edge[k:]):  # past the outline there is the plate alone, or this is no tile
        return None
    inside = im.crop((INSET, INSET, TILE - INSET, TILE - INSET))  # the old plate's inside, with the logo
    last = TILE - 2 * INSET - 1  # the inside's last pixel
    if not all(same(inside.getpixel(c), colour) for c in ((0, 0), (last, 0), (0, last), (last, last))):  # its corners are on the plate
        return None  # a plate rounder than INSET clears: its curve would show inside the square
    ring_colour = ring[len(ring) // 2] if ring else None  # the outline's colour, from its middle
    flat = Image.new("RGBA", im.size, colour[:3] + (255,))  # the picture over its own plate: the clear corners read as plate
    flat.alpha_composite(im)
    band = ((0, 0, TILE, INSET), (0, TILE - INSET, TILE, TILE), (0, INSET, INSET, TILE - INSET), (TILE - INSET, INSET, TILE, TILE - INSET))  # top, bottom, left, right
    for strip in band:  # the edge band, between the picture's edge and the inside, holds the plate, its outline and their blends
        found = flat.crop(strip).getcolors(4096)  # its colours, each once (None: more than a plate's smoothed edge ever has)
        if found is None or any(off_line(c, colour, ring_colour) > 16 for _, c in found):  # anything else is the logo, which would lose its edge
            return None
    out = Image.new("RGBA", im.size, colour[:3] + (255,))  # the plate's colour over the whole tile
    out.alpha_composite(inside, (INSET, INSET))  # the inside where it was
    draw = ImageDraw.Draw(out)  # the outline over it
    for w in range(len(ring)):  # square, as wide as the old one, edge inwards
        draw.rectangle((w, w, TILE - 1 - w, TILE - 1 - w), outline=ring_colour[:3] + (255,))
    return out


def logo_tile(spec, path, navy, outline=TILE_BORDER):
    """One square logo tile. An image is trimmed of near-white edges and fitted in 70% of a white rounded tile with a light
    outline (the reference tile style); a monogram draws its initials on a filled rounded tile. Under square corners
    (src/corners.py) both tiles are square, and a finished rounded tile brought in as the logo has its plate squared. outline: the
    white tile's outline colour (theme_tones)."""
    t = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    d = ImageDraw.Draw(t)
    if spec.get("monogram"):
        fill = hex_rgb(spec.get("color")) or navy  # the given color or the theme color
        plate(d, fill=fill + (255,))  # the filled tile, its corners as the run asks
        text = spec["monogram"][:3]
        f = ImageFont.truetype(FD + "Pretendard-Bold.ttf", int(TILE * (0.42 if len(text) < 3 else 0.32)))
        bb = d.textbbox((0, 0), text, font=f)
        d.text(((TILE - (bb[2] - bb[0])) / 2 - bb[0], (TILE - (bb[3] - bb[1])) / 2 - bb[1]), text, fill="white", font=f)
    else:
        im = Image.open(spec["file"], formats=LOGO_FORMATS).convert("RGBA")   # a logo's usual kinds; no other decoder of Pillow's is reached
        if im.width == im.height and all(im.getpixel(c)[3] == 0 for c in ((0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1))):
            # A square image with transparent corners is a finished rounded tile already: keep it, only scale it to the tile size
            t = im.resize((TILE, TILE), Image.LANCZOS)  # as it came, at the tile's size
            if corners.square():  # square corners asked: its plate squared around the logo
                sq = squared(t)  # None when it is no plate with a logo inside
                if sq is None:  # said, since a command line run can read it: the picture keeps its own shape
                    WARN.append(f"logo {pathlib.Path(spec['file']).name}: kept as it is, no plate around its logo to square")
                t = sq or t  # the squared tile, or the picture as it came
            t.save(path)
            return path
        px = im.load()
        if im.getchannel("A").getextrema()[0] == 255:  # an opaque image: turn its near-white background transparent
            for yy in range(im.height):
                for xx in range(im.width):
                    r, g, b, a = px[xx, yy]
                    if r > 238 and g > 238 and b > 238:
                        px[xx, yy] = (r, g, b, 0)
        bb = im.getchannel("A").getbbox()
        if bb:
            im = im.crop(bb)
        plate(d, fill=(255, 255, 255, 255), outline=outline, width=6)  # the white tile with its light outline, its corners as the run asks
        box = int(TILE * 0.70)
        k = min(box / im.width, box / im.height)
        m = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        t.alpha_composite(m, ((TILE - m.width) // 2, (TILE - m.height) // 2))
    path.parent.mkdir(parents=True, exist_ok=True)
    t.save(path)
    return path


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    out, lang = sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "ko")
    job = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None  # the edition's job.json, when the build passes it
    prof = load_profile(sys.argv[1], lang, job)
    navy = theme_navy()
    tint, outline = theme_tones()  # the hierarchy's boxes and the tiles' outline, in the set's own tones
    suffix = "_en" if lang == "en" else ""
    for kind, fn in (("timeline", timeline), ("stack", lambda *a: stack(*a, tint=tint))):  # the hierarchy's boxes in the set's tone
        p = OUT / f"{out}_{kind}{suffix}.png"
        p.unlink(missing_ok=True)  # a field removed from the profile removes its figure too
        try:
            made = fn(prof, lang, p, navy)
        except Exception as e:  # one figure failing leaves the resume buildable without it
            WARN.append(f"{kind} figure failed: {type(e).__name__}: {e}")
            made = None
        print(kind, made.name if made else "none")
    for old in OUT.glob(f"{out}_timeline_ch_*{suffix}.png"):  # stale chapter variants
        if suffix or not old.stem.endswith("_en"):
            old.unlink()
    try:  # the deck's career slide reads a flatter figure as wide as its body (1184 px)
        timeline(prof, lang, OUT / f"{out}_timeline_deck{suffix}.png", navy, width=1184)
    except Exception as e:
        WARN.append(f"deck timeline failed: {type(e).__name__}: {e}")
    for r in prof.get("roles") or []:  # one chapter variant per role for the deck's chapter dividers (the divider's panel is 736 px)
        if r.get("start") and r.get("logoId"):
            try:
                timeline(prof, lang, OUT / f"{out}_timeline_ch_{r['logoId']}{suffix}.png", navy, active=r.get("key"), width=736)
            except Exception as e:  # the deck falls back to no timeline on that divider
                WARN.append(f"chapter timeline for '{r.get('org')}' failed: {type(e).__name__}: {e}")
    # Chapters that are not companies (profile chapters[], read raw: the shared loader does not carry them): a timeline variant with
    # the study or role they belong to dark (chapters[].timeline names its key), and a logo tile
    raw = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    extra = [c for c in (raw.get("chapters") or []) if isinstance(c, dict)]
    edu_keys = {e.get("key") for e in prof.get("education") or []}
    role_keys = {r.get("key") for r in prof.get("roles") or []}
    for i, c in enumerate(extra):
        key = re.sub(r"[^\w-]", "_", str(c.get("key") or f"ch{i + 1}"))  # the same key rule as deck_slides.js
        tk = c.get("timeline")
        if tk:
            try:
                timeline(prof, lang, OUT / f"{out}_timeline_ch_ch_{key}{suffix}.png", navy, width=736,
                         active=tk if tk in role_keys else None, active_edu=tk if tk in edu_keys else None)
            except Exception as e:  # the divider goes without a timeline
                WARN.append(f"chapter timeline for '{key}' failed: {type(e).__name__}: {e}")
    for old in OUT.glob(f"{out}_logo_*.png"):  # stale tiles from an earlier profile
        old.unlink()
    for i, c in enumerate(extra):  # the chapters' own tiles: an image next to the profile, or a monogram { text, color }
        key = re.sub(r"[^\w-]", "_", str(c.get("key") or f"ch{i + 1}"))
        lg = c.get("logo")
        spec = {"monogram": lg["text"], "color": lg.get("color")} if isinstance(lg, dict) and lg.get("text") else None
        if isinstance(lg, str):
            f = next((x for x in (pathlib.Path(lg), pathlib.Path(sys.argv[1]).resolve().parent / lg, ROOT / lg) if x.is_absolute() and x.exists()), None)
            spec = {"file": str(f)} if f else None
        if spec:
            try:
                logo_tile(spec, OUT / f"{out}_logo_ch_{key}.png", navy, outline=outline)
            except Exception as e:  # an unreadable logo leaves the chapter without one
                WARN.append(f"logo for chapter '{key}' failed: {type(e).__name__}: {e}")
    tiles = 0
    for x in (prof.get("roles") or []) + (prof.get("education") or []):
        if x.get("logo") and x.get("logoId"):
            try:
                logo_tile(x["logo"], OUT / f"{out}_logo_{x['logoId']}.png", navy, outline=outline)
                tiles += 1
            except Exception as e:  # an unreadable logo file leaves that row without a logo
                WARN.append(f"logo for '{x.get('org') or x.get('school')}' failed: {type(e).__name__}: {e}")
    print("logos", tiles)
    for w in WARN:
        print("  note: " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
