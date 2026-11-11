#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Figures and logo tiles for the resume and deck.

It draws the overview figures at a fixed size, in fixed fonts, colors and bar shapes; every value comes from the profile:
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


def hex_rgb(h):
    """'#1F3A5F' or '1F3A5F' to an RGB tuple, None when it is not a color"""
    h = str(h or "").lstrip("#")  # the leading mark is optional
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if re.fullmatch(r"[0-9A-Fa-f]{6}", h) else None


def theme_navy():
    """The bar color: the theme's name-cell color, or a darker theme color when that one is light (light bars got light text)"""
    name = os.environ.get("OFFEROWL_THEME") or os.environ.get("OFFEROWL_FIG_THEME") or "navy"  # the theme the build uses
    themes = json.loads((ROOT / "src" / "themes.json").read_text(encoding="utf-8"))  # built-in themes
    if os.environ.get("OFFEROWL_THEME_FILE"):  # a user's theme file adds to or overrides the built-in ones
        themes.update(json.loads(pathlib.Path(os.environ["OFFEROWL_THEME_FILE"]).read_text(encoding="utf-8")))
    elif name == "navy":  # the built-in navy keeps the colors above exactly
        return NAVY
    t = themes.get(name)
    if not t:
        raise SystemExit(f"unknown theme '{name}'")
    for key in ("nameFill", "sec", "acc"):  # darkest usable first
        c = hex_rgb(t.get(key))
        if c and (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) < 140:  # dark enough for white text
            return c
    return INK  # no dark color in the theme: near black


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
                    color = navy if it.get("key") == active else mix(GREY, .78)
                    label, sub = career_label(it)
                elif key == "career":  # newest darkest, older lighter (the reference shades run 0 to .70)
                    color = mix(navy, min(.70, recency[id(it)] * .16))
                    label, sub = career_label(it)
                elif key == "edu" and active_edu is not None and it.get("key") == active_edu:  # the study this chapter belongs to, dark
                    color = navy
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
                else:
                    d.rounded_rectangle([x0, yy * S, x1, (yy + h) * S], radius=3 * S, fill=color)
                tx = x0 + 4 * S
                if tb is not None and x0 < XB < x1:  # a bar through the squeezed span is cut by the wave, its text starts after it
                    wave((yy - 2) * S, (yy + h + 2) * S)
                    tx = XB + 1.75 * S + 1.5 * S + 4 * S
                dark = sum(color) < 450
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


def stack(prof, lang, path, navy):
    """Hierarchy figure (the reference stack figure): layer name on the left, skills and where on the right, darker toward the bottom"""
    layers = (prof.get("summary") or {}).get("layers") or []
    layers = [r for r in layers if isinstance(r, (list, tuple)) and r]
    if not layers:
        return None
    n = len(layers)
    row, gap = 38, 4
    H = (row * n + gap * (n - 1)) * S
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    lw = int(W * 0.27)  # left column wide enough for English layer names on one line
    for i, item in enumerate(layers):
        name, tech, where = [str(v) for v in (list(item) + ["", "", ""])[:3]]
        y0 = i * (row + gap) * S
        y1 = y0 + row * S
        c = mix(navy, max(0, .30 - i * .075))  # darker toward the bottom, never past the base color
        d.rounded_rectangle([0, y0, lw, y1], radius=3 * S, fill=c)
        pad = 12  # left inset of both columns
        f, ft, fw = font(12.5, True), font(11.5, True), font(10.5)
        b = d.textbbox((0, 0), name, font=f)  # center the name by its ink height (fonts differ in top room)
        draw_text(d, (pad * S, y0 + (row * S - (b[3] - b[1])) / 2 - b[1]), name, "white", f)
        d.rounded_rectangle([lw + 10 * S, y0, W, y1], radius=3 * S, fill=TINT)
        # The two right lines (skills, where) sit as one block centered in the row, 6 apart
        b1, b2 = d.textbbox((0, 0), tech or " ", font=ft), d.textbbox((0, 0), where or " ", font=fw)
        h1, h2, lead = b1[3] - b1[1], b2[3] - b2[1], 6 * S
        top = y0 + (row * S - (h1 + lead + h2)) / 2
        draw_text(d, (lw + (10 + pad) * S, top - b1[1]), tech, navy, ft)
        draw_text(d, (lw + (10 + pad) * S, top + h1 + lead - b2[1]), where, GREY, fw)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, dpi=(96 * S, 96 * S))
    return path


def logo_tile(spec, path, navy):
    """One square logo tile. An image is trimmed of near-white edges and fitted in 70% of a white rounded tile with a light
    outline (the reference tile style); a monogram draws its initials on a filled rounded tile"""
    t = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    d = ImageDraw.Draw(t)
    if spec.get("monogram"):
        fill = hex_rgb(spec.get("color")) or navy  # the given color or the theme color
        d.rounded_rectangle([1, 1, TILE - 2, TILE - 2], radius=88, fill=fill + (255,))
        text = spec["monogram"][:3]
        f = ImageFont.truetype(FD + "Pretendard-Bold.ttf", int(TILE * (0.42 if len(text) < 3 else 0.32)))
        bb = d.textbbox((0, 0), text, font=f)
        d.text(((TILE - (bb[2] - bb[0])) / 2 - bb[0], (TILE - (bb[3] - bb[1])) / 2 - bb[1]), text, fill="white", font=f)
    else:
        im = Image.open(spec["file"], formats=LOGO_FORMATS).convert("RGBA")   # a logo's usual kinds; no other decoder of Pillow's is reached
        if im.width == im.height and all(im.getpixel(c)[3] == 0 for c in ((0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1))):
            # A square image with transparent corners is a finished rounded tile already: keep it, only scale it to the tile size
            im.resize((TILE, TILE), Image.LANCZOS).save(path)
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
        d.rounded_rectangle([1, 1, TILE - 2, TILE - 2], radius=88, fill=(255, 255, 255, 255), outline=TILE_BORDER, width=6)
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
    suffix = "_en" if lang == "en" else ""
    for kind, fn in (("timeline", timeline), ("stack", stack)):
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
                logo_tile(spec, OUT / f"{out}_logo_ch_{key}.png", navy)
            except Exception as e:  # an unreadable logo leaves the chapter without one
                WARN.append(f"logo for chapter '{key}' failed: {type(e).__name__}: {e}")
    tiles = 0
    for x in (prof.get("roles") or []) + (prof.get("education") or []):
        if x.get("logo") and x.get("logoId"):
            try:
                logo_tile(x["logo"], OUT / f"{out}_logo_{x['logoId']}.png", navy)
                tiles += 1
            except Exception as e:  # an unreadable logo file leaves that row without a logo
                WARN.append(f"logo for '{x.get('org') or x.get('school')}' failed: {type(e).__name__}: {e}")
    print("logos", tiles)
    for w in WARN:
        print("  note: " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
