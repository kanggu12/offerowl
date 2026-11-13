#!/usr/bin/env python3
"""Draw the pictures of Offerowl's docs from docs/assets/data, each in a light and a dark copy (CONTRIBUTING.md).

    python3 docs/assets/build.py                every SVG, light and dark, into docs/assets/ (the README's badges: .github/badges.sh)
    python3 docs/assets/build.py --check DIR    also render each SVG to DIR/<name>.png in Chrome and measure text that
                                                leaves its box or overlaps other text, with this PC's fonts, a wide
                                                fallback font and a narrow one (needs Playwright with Chromium)

The numbers come from tools/measure.py, which writes docs/assets/data/*.json; nothing here is typed by hand. The house
style is the panel's own (apps/panel/static/skin.css, 'owl glass'), so a picture in the docs looks like a piece of the
screen it describes:

  the ground               the desk: a cool pale grey, the lamp's warmth from the top left, the night's blue at the bottom right
  a step or a part         a pane of the panel's frosted glass, its kind in an icon of the panel on a tinted tile, its title, a quiet line
  a run of steps           the chevrons of Make's chain ("the evidence's way"), each pointing at the next
  a group                  one pane, its head inside and its parts on rows divided by hairlines (never a box in a box)
  a finished document      a sheet of paper with a folded corner; a posting is an application's note
  a chart                  an Insights tile: rows of bars on their tracks, the counts beside them

and each colour means what it means in the panel:

  blue    your sources            amber   the facts, the evidence (the owl's eyes; its highlighter, once per picture)
  orange  what the AI writes, and the arrows that carry text to it      green   finished documents
  red     stopped by a check      the rainbow rim   the AI backend, where text is handed to it
  grey    everything that stays on your PC (an arrow without colour)

Icons are read from the panel's own set (apps/panel/static/core.js ICONS), so the pictures and the screen never drift.
Text widths are measured with the Pretendard files in fonts/, the first font the pictures ask for, with room to spare for
the widest fallback a viewer may have (DejaVu Sans: a seventh wider, a quarter wider in bold).
"""
from __future__ import annotations  # `str | None` hints on Python 3.10

import argparse  # the command line
import json  # the data files
import math  # arrow geometry
import pathlib  # paths
import re  # the <img> tags of the docs, the panel's icons
import sys  # exit codes
from html import escape  # text inside SVG

from PIL import ImageFont  # text widths from the font files

HERE = pathlib.Path(__file__).resolve().parent  # docs/assets
ROOT = HERE.parent.parent  # the repository
DATA = HERE / "data"  # tools/measure.py writes here
FONTS = ROOT / "fonts"  # Pretendard, which the documents and the panel use too

SANS = "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"  # labels
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"  # file and module names
SPARE = 1.15  # room for the widest regular fallback (DejaVu Sans is 11 to 14 percent wider than Pretendard)
SPARE_BOLD = 1.26  # and for its bold, which a 600 weight falls back to (18 to 24 percent wider than Pretendard SemiBold)
SPARE_MONO = 1.04  # mono fonts differ little (0.55 to 0.61 of the size per character)

# The two themes: the panel's tokens (skin.css 'owl glass (11-12)', 'the palette in tune (11-11)'). A colour is a hex
# string, or (hex, opacity) for the glass and the hairlines, which let what lies under them show.
THEMES = {
    "light": {
        "page": "#ffffff",                                                    # GitHub's page round the picture (the check's previews)
        "desk_top": "#f2f4f7", "desk": "#e8ebf0", "desk_low": "#e1e5eb",     # the desk: cool, pale, lighter at the top
        "lamp": ("#ffc88a", .32), "shade": ("#425c94", .2),                   # the lamp's warmth (top left), the night's blue (bottom right)
        "frame": ("#1e2434", .1),                                             # the desk's edge against the page
        "pane": ("#ffffff", .5), "rim": ("#ffffff", .85), "edge": ("#1e2434", .08),   # frosted white, its lit rim, a hairline out
        "sheen": (.5, .08), "lampbox": ("#ffbe6e", .075),                     # brighter at the lit corner; the lamp in every box
        "shadow": ("#1e2434", .3), "blur": 13, "spread": 16, "drop": 12,      # one soft shadow under a pane
        "paper": "#ffffff", "paper_back": "#e3e7ee", "paper_edge": ("#1e2434", .14), "paper_shadow": ("#281e0f", .16),
        "note": "#f3eac8", "note_back": "#faf5e1", "note_ink3": "#5f5a48",   # a note of the preparing stage, its lighter back, its quiet words
        "ink": "#171717", "ink2": "#4d4d4d", "ink3": "#616161",              # words: main, secondary, quiet (the panel's #666 a touch darker: 4.5:1 where the night's blue falls)
        "rule": ("#1e2434", .1),                                              # a hairline between rows
        "arrow": "#7b8494", "orange_line": "#d4531f", "red_line": "#d63b3b",  # arrows: 3:1 or more on the desk
        "blue": "#2663ae", "amber": "#865901", "orange": "#a0421c", "green": "#087736", "red": "#a23d3a", "violet": "#5b55ac",   # words and icons
        "violet_bar": "#6250d6", "red_bar": "#e34948", "red_deep": "#8f2433",   # bars: passed, stopped, dropped (validate_palette.js passes, both themes)
        "tile": .12,                                                          # an icon's tile: its colour at this share
        "hl": ("#f2c744", .58),                                               # the highlighter: the owl's eyes, as the panel marks a selection
        "track": ("#1e2434", .07),                                            # a bar's track (the panel's well)
        "mark": "#1b2e4b",                                                    # the logo's body
    },
    "dark": {
        "page": "#0d1117",
        "desk_top": "#13151a", "desk": "#0e0f13", "desk_low": "#0b0c0f",
        "lamp": ("#ffa854", .17), "shade": ("#4e6cbc", .22),
        "frame": ("#ffffff", .08),
        "pane": ("#1e2028", .5), "rim": ("#ffffff", .11), "edge": ("#000000", .35),
        "sheen": (.09, .03), "lampbox": ("#ffb056", .055),
        "shadow": ("#000000", .9), "blur": 16, "spread": 20, "drop": 16,
        "paper": "#1c1d20", "paper_back": "#2e3036", "paper_edge": ("#ffffff", .1), "paper_shadow": ("#000000", .5),
        "note": "#45402c", "note_back": "#5b553f", "note_ink3": "#c6c1b0",
        "ink": "#ededed", "ink2": "#c7c7c7", "ink3": "#a8a8a8",                # the panel's quiet grey a touch lighter: 4.5:1 under the lamp's warmth too
        "rule": ("#ffffff", .08),
        "arrow": "#6f7787", "orange_line": "#d95926", "red_line": "#e66767",
        "blue": "#87bafe", "amber": "#e4ac59", "orange": "#f89c7b", "green": "#7ccd8e", "red": "#fb9890", "violet": "#aeaefe",
        "violet_bar": "#9085e9", "red_bar": "#e66767", "red_deep": "#a83a48",   # the dropped red under 3:1 here: its count is written under every bar
        "tile": .18,
        "hl": ("#f2c744", .36),
        "track": ("#ffffff", .07),
        "mark": "#2a4a78",
    },
}
RAINBOW = ["#ff4d6d", "#ffb347", "#f2e14c", "#4cd97b", "#4cc9f0", "#7b61ff", "#e84cf0", "#ff4d6d"]   # the panel's AI rim (skin.css --rainbow)


def panel_icons() -> dict:
    """The panel's icons (apps/panel/static/core.js ICONS): a 24-unit grid, drawn as lines."""
    src = (ROOT / "apps" / "panel" / "static" / "core.js").read_text(encoding="utf-8")  # the panel's own file
    start = src.index("const ICONS = {")  # the table
    return dict(re.findall(r"^\s+(\w+): '(<[^']*)',", src[start:src.index("};", start)], re.M))  # name -> its SVG shapes


ICONS = panel_icons()  # read once


# measuring text

_FONT_CACHE = {}  # (cut, size) -> PIL font


def font(size: float, weight: int = 400):
    """The Pretendard cut closest to a weight, at a size."""
    name = "Pretendard-Bold.ttf" if weight >= 700 else "Pretendard-SemiBold.ttf" if weight >= 600 else "Pretendard-Regular.ttf"  # three cuts ship in fonts/
    key = (name, round(size * 4))  # quarter pixels are enough
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(str(FONTS / name), size=max(1, round(size * 4)))  # four times the size, for fine widths
    return _FONT_CACHE[key]


def natural(text: str, size: float, weight: int = 400, mono: bool = False) -> float:
    """The width of a text in Pretendard (or a common mono font), with no room to spare: where a highlight ends."""
    if mono:  # monospace: 0.61 of the size per character in the common mono fonts
        return len(text) * size * 0.61
    return font(size, weight).getlength(text) / 4  # measured at four times the size


def width(text: str, size: float, weight: int = 400, mono: bool = False) -> float:
    """The room a text needs: its Pretendard width with room for the widest fallback font of its kind."""
    return natural(text, size, weight, mono) * (SPARE_MONO if mono else SPARE_BOLD if weight >= 600 else SPARE)


def wrap(text: str, size: float, maxw: float, weight: int = 400) -> list[str]:
    """Greedy line breaks so that every line fits maxw; a single word that cannot fit is an error."""
    lines, cur = [], ""  # finished lines; the line being filled
    for word in text.split():
        trial = f"{cur} {word}".strip()  # the line with one more word
        if width(trial, size, weight) <= maxw:  # it still fits
            cur = trial
            continue
        if not cur:  # one word wider than the space: the picture must change
            raise ValueError(f"'{word}' does not fit in {maxw:.0f} px at {size}px")
        lines.append(cur)  # the line is full
        cur = word  # the word starts the next one
    if cur:
        lines.append(cur)
    return lines


def num(n: float) -> str:
    """A number as the pictures print it: thousands with commas, no needless decimals."""
    if isinstance(n, float) and not n.is_integer():  # a measured time
        return f"{n:,.1f}"
    return f"{int(n):,}"


def chevron(x: float, y: float, w: float, h: float, tip: float, notch: bool = True, point: bool = True, left: bool = False) -> str:
    """The outline of one step of Make's chain: a pane cut to an arrow, notched behind and pointing on (or, left, back)."""
    m = y + h / 2  # the middle, where the point and the notch are
    if left:  # pointing left: the mirror of the right-pointing step
        start = x + tip if point else x  # where the top edge starts
        return f"M{start:.1f},{y:.1f} H{x + w:.1f} " + (f"L{x + w - tip:.1f},{m:.1f} L{x + w:.1f},{y + h:.1f}" if notch else f"V{y + h:.1f}") + \
            f" H{start:.1f} " + (f"L{x:.1f},{m:.1f} Z" if point else f"V{y:.1f} Z")
    end = x + w - tip if point else x + w  # where the top edge ends
    nose = f"L{x + w:.1f},{m:.1f} L{end:.1f},{y + h:.1f}" if point else f"V{y + h:.1f}"  # the point, or a straight edge
    back = f"L{x + tip:.1f},{m:.1f} Z" if notch else "Z"  # the notch, or a straight edge
    return f"M{x:.1f},{y:.1f} H{end:.1f} {nose} H{x:.1f} {back}"


def box_path(x: float, y: float, w: float, h: float) -> str:
    """A rectangle as a path, so a pane and a chevron are drawn the same way."""
    return f"M{x:.1f},{y:.1f} H{x + w:.1f} V{y + h:.1f} H{x:.1f} Z"


# a figure

class Fig:
    """One picture on a slice of the panel's desk, as a list of shapes with colour names; render() writes it once per
    theme, so the light and the dark copy always have the same geometry."""

    def __init__(self, w: float, h: float, label: str):  # the drawing area and its alt text
        self.w, self.h, self.label = w, h, label  # size and accessible name
        self.items = []  # shapes in drawing order
        self.texts = []  # (x0, y0, x1, y1, words) of every text, for the overlap check while building
        self.highlights = 0  # the highlighter is used once per picture at most

    # basic shapes
    def rect(self, x, y, w, h, fill=None, stroke=None, sw=1, rx=2, extra=""):
        """A rectangle: fill and stroke are colour names of the theme, (name, opacity name) pairs, or None."""
        self.items.append(("rect", dict(x=x, y=y, w=w, h=h, fill=fill, stroke=stroke, sw=sw, rx=rx, extra=extra)))

    def path(self, d, stroke=None, sw=1.4, fill=None, extra=""):
        """A path: a line, a connector or a filled shape."""
        self.items.append(("path", dict(d=d, stroke=stroke, sw=sw, fill=fill, extra=extra)))

    def text(self, x, y, s, size=12.5, weight=400, fill="ink3", anchor="start", box=None, mono=False, italic=False, fit=None):
        """One line of text at a baseline. box = (x0, x1) is the room the text may use; it is checked here and kept in
        the SVG (data-box) for the check in the browser. fit: the exact width the words are set to in any font (the
        highlighted line, so the highlighter covers it whatever font the viewer has)."""
        w = fit if fit else width(s, size, weight, mono)  # its width: exact when fitted, else the widest fallback's
        x0 = x if anchor == "start" else x - w / 2 if anchor == "middle" else x - w  # where it starts
        if box is not None and (x0 < box[0] - 0.5 or x0 + w > box[1] + 0.5):  # it leaves its room
            raise ValueError(f"text '{s}' ({x0:.0f} to {x0 + w:.0f}) leaves its box {box[0]:.0f} to {box[1]:.0f}")
        self.texts.append((x0, y - size * 0.8, x0 + w, y + size * 0.25, s))  # its box, for overlaps
        self.items.append(("text", dict(x=x, y=y, s=s, size=size, weight=weight, fill=fill, anchor=anchor, box=box, mono=mono, italic=italic, fit=fit)))
        return w

    def raw(self, svg: str):
        """SVG as written, with {name} for a colour of the theme (an icon, the logo)."""
        self.items.append(("raw", dict(s=svg)))

    def icon(self, name: str, x: float, y: float, size: float, color: str):
        """One of the panel's icons at a size, drawn in a colour of the theme."""
        k = size / 24  # the icons are drawn on a 24-unit grid
        self.raw(f'<g transform="translate({x:.1f},{y:.1f}) scale({k:.4f})" fill="none" stroke="{{{color}}}" stroke-width="1.8" '
                 f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')

    def tile(self, x: float, y: float, name: str, color: str = "ink3", size: float = 22):
        """An icon on a tile tinted with its colour, as Make's chain marks each step's kind."""
        self.rect(x, y, size, size, fill=(color, "tile"), rx=2)  # the tint
        self.icon(name, x + (size - 13) / 2, y + (size - 13) / 2, 13, color)  # the icon, 13 px as the panel's

    def mark(self, x: float, y: float, size: float):
        """Offerowl's mark (docs/assets/icon.svg), as it stands beside the wordmark in the panel's bar."""
        k = size / 64  # the mark is drawn on a 64-unit grid
        self.raw(f'<g transform="translate({x:.1f},{y:.1f}) scale({k:.4f})"><path d="M9.5 17.5 L13.2 4.8 L23.5 13 Z M54.5 17.5 L50.8 4.8 L40.5 13 Z" fill="{{mark}}"/>'
                 '<rect x="7" y="11" width="50" height="46" rx="10.5" fill="{mark}"/><path d="M13.5 19 L29.4 29.6 Q32 31.4 34.6 29.6 L50.5 19" fill="none" '
                 'stroke="#ffffff" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="20.6" cy="38.6" r="7.6" fill="#f2c744"/>'
                 '<circle cx="43.4" cy="38.6" r="7.6" fill="#f2c744"/><circle cx="21.8" cy="37.6" r="3" fill="#1b2e4b"/><circle cx="42.2" cy="37.6" r="3" fill="#1b2e4b"/></g>')

    def hl(self, x: float, baseline: float, s: str, size: float, weight: int = 400):
        """The highlighter under a line of words, as the panel marks a selection: the lower part of the line, a little past
        its ends. Once per picture: it says "this is the evidence"."""
        self.highlights += 1  # counted, so a second one stops the build
        if self.highlights > 1:
            raise ValueError("the highlighter is used once per picture")
        w = natural(s, size, weight) + 5  # a touch past the words, which are set to their Pretendard width (text fit=)
        self.items.append(("hl", dict(x=x - 2.5, y=baseline - size * 0.72, w=w, h=size * 0.98)))

    def dot(self, cx: float, cy: float, color: str, r: float = 3.5):
        """A lamp: the panel's dot that carries a state's colour beside its words."""
        self.path(f"M{cx - r:.1f},{cy:.1f} a{r},{r} 0 1,0 {2 * r},0 a{r},{r} 0 1,0 {-2 * r},0", fill=color)

    # the panel's parts
    def pane(self, d: str, bbox: tuple, rim: str = "rim"):
        """A pane of the panel's frosted glass in an outline (a box or a chevron): a milky fill the desk shows through, the
        lamp's warmth at its top left corner, a lit rim, a hairline out and one soft shadow under it. rim "rainbow" is the
        AI's rim, as the panel draws it round what hands text to the AI."""
        self.items.append(("pane", dict(d=d, bbox=bbox, rim=rim)))

    def paper(self, x: float, y: float, w: float, h: float, fold: float = 12, note: bool = False):
        """A sheet of paper, opaque, with a folded corner showing its back: a document's at the top right, as the panel's
        file icon; a note's at the bottom right, as the panel's applications on their board."""
        f = fold  # the fold's size
        if note:  # a note: its bottom right corner turned up
            body = f"M{x:.1f},{y:.1f} H{x + w:.1f} V{y + h - f:.1f} L{x + w - f:.1f},{y + h:.1f} H{x:.1f} Z"
            flap = f"M{x + w - f:.1f},{y + h - f:.1f} H{x + w:.1f} L{x + w - f:.1f},{y + h:.1f} Z"
        else:  # a document: its top right corner turned down
            body = f"M{x:.1f},{y:.1f} H{x + w - f:.1f} L{x + w:.1f},{y + f:.1f} V{y + h:.1f} H{x:.1f} Z"
            flap = f"M{x + w - f:.1f},{y:.1f} V{y + f:.1f} H{x + w:.1f} Z"
        self.items.append(("paper", dict(body=body, flap=flap, note=note)))

    def card(self, x, y, w, h, title, lines=(), icon=None, color="ink3", rim="rim", size=14.5, sub=12.5, mono_title=False,
             hl_line=None, lamp=None, d=None, pad_l=12, pad_r=12, wrap_lines=True, quiet=None):
        """A step or a part: a pane with its head (an icon on its tile, or a lamp, and the title) and quiet lines under it.
        d: another outline (a chevron); pad_l, pad_r: the room its point and notch take. hl_line: the line the
        highlighter marks. quiet: a word after the title, as the panel says where a step's data goes. Returns its edges."""
        self.pane(d or box_path(x, y, w, h), (x, y, w, h), rim)  # the glass
        inner = (x + pad_l, x + w - pad_r)  # the words' room
        tx = inner[0]  # where the title starts
        if icon:  # the kind, on its tile
            self.tile(inner[0], y + 13, icon, color)
            tx = inner[0] + 22 + 9
        elif lamp:  # a state, on its dot
            self.dot(inner[0] + 4, y + 24, lamp)
            tx = inner[0] + 15
        tw = self.text(tx, y + 29, title, size=size, weight=600, fill="ink", box=(tx, inner[1]), mono=mono_title)  # the title
        if quiet:  # a quiet word after it
            self.text(tx + tw + 6, y + 29, quiet, size=12, fill="ink3", box=(tx + tw + 6, inner[1]))
        body = []  # the quiet lines, wrapped to the room: (line, the item it starts)
        for k, ln in enumerate(lines):
            for j, part in enumerate(wrap(ln, sub, inner[1] - inner[0]) if wrap_lines else [ln]):
                body.append((part, k > 0 and j == 0))
        by = y + 53 - sub * 1.42  # the baseline before the first line
        for ln, new_item in body:  # under the head
            by += sub * 1.42 + (5 if new_item else 0)  # each line's baseline; a new item a little further down
            if hl_line is not None and ln == hl_line:  # the evidence, marked
                self.hl(inner[0], by, ln, sub)
            marked = hl_line is not None and ln == hl_line  # the evidence's line: darker words, set to the highlighter's width
            self.text(inner[0], by, ln, size=sub, fill="ink" if marked else "ink3", box=inner, fit=natural(ln, sub) if marked else None)
        last = by if body else y + 29  # the last baseline
        if last + 10 > y + h:  # the words must fit the pane
            raise ValueError(f"card '{title}' is too short for its {len(body)} lines ({last + 10:.0f} > {y + h:.0f})")
        return {"x": x, "y": y, "w": w, "h": h, "l": x, "r": x + w, "t": y, "b": y + h, "cx": x + w / 2, "cy": y + h / 2}

    def doc(self, x, y, w, h, title, lines=(), size=14, sub=12):
        """A finished document: a sheet with a folded corner (its outline says what it is, in either theme), its name and
        what it holds. The words start under the fold, so they may run to the sheet's right margin."""
        self.paper(x, y, w, h)  # the sheet
        inner = (x + 12, x + w - 12)  # the words' room
        self.text(inner[0], y + 27, title, size=size, weight=600, fill="ink", box=inner)
        body = [ln2 for ln in lines for ln2 in wrap(ln, sub, inner[1] - inner[0])]  # what it holds
        for i, ln in enumerate(body):
            self.text(inner[0], y + 47 + i * sub * 1.42, ln, size=sub, fill="ink3", box=inner)
        if body and y + 47 + (len(body) - 1) * sub * 1.42 + 9 > y + h:  # the words must fit the sheet
            raise ValueError(f"document '{title}' is too short for its lines")
        return {"x": x, "y": y, "w": w, "h": h, "l": x, "r": x + w, "t": y, "b": y + h, "cx": x + w / 2, "cy": y + h / 2}

    def note(self, x, y, w, h, title, lines=(), size=14, sub=12):
        """A posting: the note an application is on the panel's board, in the preparing stage's paper."""
        self.paper(x, y, w, h, fold=14, note=True)  # the note
        inner = (x + 12, x + w - 12)  # the words' room
        self.text(inner[0], y + 27, title, size=size, weight=600, fill="ink", box=inner)
        for i, ln in enumerate([ln2 for ln in lines for ln2 in wrap(ln, sub, inner[1] - inner[0])]):
            self.text(inner[0], y + 47 + i * sub * 1.42, ln, size=sub, fill="note_ink3", box=inner)
        return {"x": x, "y": y, "w": w, "h": h, "l": x, "r": x + w, "t": y, "b": y + h, "cx": x + w / 2, "cy": y + h / 2}

    def rule(self, x0: float, x1: float, y: float):
        """A hairline between two rows of a pane."""
        self.path(f"M{x0:.1f},{y:.1f} H{x1:.1f}", stroke="rule", sw=1)

    def arrow(self, pts, color="arrow", label=None, label_xy=None, head=True, label_anchor="middle", label_box=None):
        """A connector through points, thin as the panel's hairlines, with a small head at the last point and a short
        label. The line stops where the head starts, so the tip is sharp."""
        (x1, y1), (x2, y2) = pts[-2], pts[-1]  # the last segment points the head
        ang = math.atan2(y2 - y1, x2 - x1)  # its direction
        L = 7.5 if head else 0  # head length
        end = (x2 - math.cos(ang) * (L - 1.5), y2 - math.sin(ang) * (L - 1.5)) if head else (x2, y2)  # the line ends under the head
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in list(pts[:-1]) + [end])  # the polyline
        self.path(d, stroke=color, sw=1.4, extra='stroke-linejoin="round"')
        if head:  # a filled triangle at the tip
            bx, by = x2 - math.cos(ang) * L, y2 - math.sin(ang) * L  # the middle of its base
            px, py = -math.sin(ang) * 3.6, math.cos(ang) * 3.6  # half its width, across the line
            self.path(f"M{x2:.1f},{y2:.1f} L{bx + px:.1f},{by + py:.1f} L{bx - px:.1f},{by - py:.1f} Z", fill=color)
        if label:  # a short label beside the line
            lines = label if isinstance(label, (list, tuple)) else [label]  # one line or a few
            lx, ly = label_xy  # the first line's baseline
            for i, ln in enumerate(lines):
                self.text(lx, ly + i * 14, ln, size=12, fill="ink3", anchor=label_anchor, box=label_box)

    def legend(self, x, y, entries, end=None, right=None):
        """Swatches and words in one row, as the panel's legends: (kind, colour, words). kind 'line' is an arrow of that
        colour, 'hl' the highlighter, 'dot' a lamp, 'rim' the AI's rainbow rim. With end, the row ends there. Returns the
        row's end."""
        sw = {"line": 26, "hl": 30, "dot": 14, "rim": 30, "tile": 24}  # a swatch and the gap after it
        if end is not None:  # right-aligned: start where the row's measured width ends at `end`
            x = end - sum(sw[k] + width(words, 12) + 18 for k, _, words in entries) + 18
        for kind, color, words in entries:
            if kind == "line":  # an arrow
                self.arrow([(x, y + 5), (x + 19, y + 5)], color=color)
            elif kind == "hl":  # a stroke of the highlighter
                self.items.append(("hl", dict(x=x, y=y + 1, w=22, h=8)))
            elif kind == "dot":  # a lamp
                self.dot(x + 4, y + 5, color, 4)
            elif kind == "tile":  # an icon on its tile: (icon, colour)
                self.rect(x, y - 3, 17, 17, fill=(color[1], "tile"), rx=2)
                self.icon(color[0], x + 2.5, y - 0.5, 12, color[1])
            else:  # the AI's rim, on a small pane
                self.items.append(("rimswatch", dict(x=x, y=y - 1, w=22, h=12)))
            w = self.text(x + sw[kind], y + 9.5, words, size=12, fill="ink2", box=(x + sw[kind], right or end or self.w))  # a step darker: the legend sits where the night's blue falls
            x += sw[kind] + w + 18  # the next entry
        return x

    # writing the SVG
    def render(self, theme: str) -> str:
        """The SVG text in one theme."""
        T = THEMES[theme]  # colour names to colours

        def paint(attr: str, c) -> str:
            """A fill or a stroke: a colour name, a (name, opacity name) pair, a (hex, opacity) colour, or none."""
            if c is None:
                return f' {attr}="none"'
            if isinstance(c, tuple) and isinstance(c[1], str):  # a colour at the theme's share (a tile)
                return f' {attr}="{hexof(T[c[0]])}" {attr}-opacity="{T[c[1]]:g}"'
            v = T.get(c, c) if isinstance(c, str) else c  # a name of the theme, or a literal
            if isinstance(v, tuple):  # glass: a colour and how much of it
                return f' {attr}="{v[0]}" {attr}-opacity="{v[1]:g}"'
            return f' {attr}="{v}"'

        def hexof(v) -> str:
            """The colour of a theme value without its opacity."""
            return v[0] if isinstance(v, tuple) else v

        W, H = self.w, self.h  # the desk
        defs, body = [], []  # gradients and clips; the drawing
        lamp, shade, sheen, lampbox = T["lamp"], T["shade"], T["sheen"], T["lampbox"]
        defs.append(f'<linearGradient id="desk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{T["desk_top"]}"/>'
                    f'<stop offset=".46" stop-color="{T["desk"]}"/><stop offset="1" stop-color="{T["desk_low"]}"/></linearGradient>')
        defs.append(f'<radialGradient id="lamp" cx=".03" cy="-.12" r=".74"><stop offset="0" stop-color="{lamp[0]}" stop-opacity="{lamp[1]:g}"/>'
                    f'<stop offset=".64" stop-color="{lamp[0]}" stop-opacity="0"/></radialGradient>')
        defs.append(f'<radialGradient id="shade" cx="1.06" cy="1.14" r=".88"><stop offset="0" stop-color="{shade[0]}" stop-opacity="{shade[1]:g}"/>'
                    f'<stop offset=".62" stop-color="{shade[0]}" stop-opacity="0"/></radialGradient>')
        defs.append(f'<linearGradient id="sheen" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity="{sheen[0]:g}"/>'
                    f'<stop offset=".55" stop-color="#ffffff" stop-opacity="{sheen[1]:g}"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/></linearGradient>')
        defs.append(f'<radialGradient id="lampbox" cx="0" cy="0" r="1.3"><stop offset="0" stop-color="{lampbox[0]}" stop-opacity="{lampbox[1]:g}"/>'
                    f'<stop offset=".55" stop-color="{lampbox[0]}" stop-opacity="0"/></radialGradient>')
        defs.append('<linearGradient id="rainbow" x1="0" y1="0" x2="1" y2=".18">' +
                    "".join(f'<stop offset="{i / (len(RAINBOW) - 1):.3f}" stop-color="{c}"/>' for i, c in enumerate(RAINBOW)) + "</linearGradient>")
        defs.append(f'<filter id="soft" filterUnits="userSpaceOnUse" x="0" y="0" width="{W:g}" height="{H:g}"><feGaussianBlur stdDeviation="{T["blur"]:g}"/></filter>')
        ps = T["paper_shadow"]  # an opaque sheet's own shadow, along its outline (the panel's notes: drop-shadow)
        defs.append(f'<filter id="sheet" x="-20%" y="-20%" width="150%" height="170%"><feGaussianBlur in="SourceAlpha" stdDeviation="4"/>'
                    f'<feOffset dx="3" dy="5" result="b"/><feFlood flood-color="{ps[0]}" flood-opacity="{ps[1]:g}"/><feComposite in2="b" operator="in"/>'
                    '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
        body.append(f'<rect width="{W:g}" height="{H:g}" rx="8" fill="url(#desk)"/>')  # the desk
        body.append(f'<rect width="{W:g}" height="{H:g}" rx="8" fill="url(#lamp)"/>')  # the lamp's warmth
        body.append(f'<rect width="{W:g}" height="{H:g}" rx="8" fill="url(#shade)"/>')  # the night's blue
        n = 0  # clips made so far
        for kind, a in self.items:
            if kind == "rect":
                rx = f' rx="{a["rx"]:g}"' if a["rx"] else ""
                stroke = paint("stroke", a["stroke"]) + f' stroke-width="{a["sw"]:g}"' if a["stroke"] else ""
                body.append(f'<rect x="{a["x"]:.1f}" y="{a["y"]:.1f}" width="{a["w"]:.1f}" height="{a["h"]:.1f}"{rx}{paint("fill", a["fill"])}{stroke}'
                            f'{(" " + a["extra"]) if a["extra"] else ""}/>')
            elif kind == "path":
                stroke = paint("stroke", a["stroke"]) + f' stroke-width="{a["sw"]:g}"' if a["stroke"] else ""
                body.append(f'<path d="{a["d"]}"{paint("fill", a["fill"])}{stroke}{(" " + a["extra"]) if a["extra"] else ""}/>')
            elif kind == "pane":  # the glass: a shadow outside it, its fill, its warmth and sheen, its rim inside
                n += 1
                x, y, w, h = a["bbox"]  # its box
                s, dy = T["spread"], T["drop"]  # the shadow drawn smaller than the pane and moved down, so only its foot shows
                defs.append(f'<clipPath id="o{n}"><path clip-rule="evenodd" d="M-40,-40 H{W + 40:g} V{H + 40:g} H-40 Z {a["d"]}"/></clipPath>')  # outside the pane
                defs.append(f'<clipPath id="i{n}"><path d="{a["d"]}"/></clipPath>')  # inside it
                sh = T["shadow"]
                body.append(f'<g clip-path="url(#o{n})"><rect x="{x + s:.1f}" y="{y + s + dy:.1f}" width="{max(4, w - 2 * s):.1f}" height="{max(4, h - 2 * s):.1f}" '
                            f'fill="{sh[0]}" fill-opacity="{sh[1]:g}" filter="url(#soft)"/>'
                            f'<path d="{a["d"]}"{paint("fill", None)}{paint("stroke", "edge")} stroke-width="2"/></g>')  # the hairline out
                body.append(f'<path d="{a["d"]}"{paint("fill", "pane")}/>')  # the milky glass
                body.append(f'<path d="{a["d"]}" fill="url(#lampbox)"/><path d="{a["d"]}" fill="url(#sheen)"/>')  # warmth and sheen
                if a["rim"] == "rainbow":  # the AI's rim, as the panel draws round what hands text to the AI
                    body.append(f'<path d="{a["d"]}" fill="none" stroke="url(#rainbow)" stroke-width="3.2" clip-path="url(#i{n})"/>')
                else:  # the lit rim
                    body.append(f'<path d="{a["d"]}" fill="none"{paint("stroke", a["rim"])} stroke-width="2" clip-path="url(#i{n})"/>')
            elif kind == "paper":  # an opaque sheet, its shadow along its outline, its fold showing its back
                face, back = ("note", "note_back") if a["note"] else ("paper", "paper_back")
                body.append(f'<g filter="url(#sheet)"><path d="{a["body"]}"{paint("fill", face)}/></g>')
                body.append(f'<path d="{a["body"]}" fill="none"{paint("stroke", "paper_edge")} stroke-width="1"/>')  # its edge
                body.append(f'<path d="{a["flap"]}"{paint("fill", back)}{paint("stroke", "paper_edge")} stroke-width="1" stroke-linejoin="round"/>')
            elif kind == "hl":  # the highlighter: straight, nearly square, the owl's eyes' yellow
                body.append(f'<rect x="{a["x"]:.1f}" y="{a["y"]:.1f}" width="{a["w"]:.1f}" height="{a["h"]:.1f}" rx="1.5"{paint("fill", "hl")}/>')
            elif kind == "rimswatch":  # the legend's sample of the AI's rim
                body.append(f'<rect x="{a["x"] + .8:.1f}" y="{a["y"] + .8:.1f}" width="{a["w"] - 1.6:.1f}" height="{a["h"] - 1.6:.1f}" rx="2"'
                            f'{paint("fill", "pane")} stroke="url(#rainbow)" stroke-width="1.6"/>')
            elif kind == "raw":  # SVG as written, its {colour} names filled in for this theme
                body.append(re.sub(r"\{(\w+)\}", lambda m: hexof(T.get(m.group(1), m.group(0))), a["s"]))
            elif kind == "text":
                fam = f' font-family="{escape(MONO, quote=True)}" class="m"' if a["mono"] else ""  # the root's family is the default
                weight = f' font-weight="{a["weight"]}"' if a["weight"] != 400 else ""
                style = ' font-style="italic"' if a["italic"] else ""
                style += f' textLength="{a["fit"]:.1f}" lengthAdjust="spacingAndGlyphs"' if a["fit"] else ""  # the same width in any font
                anchor = f' text-anchor="{a["anchor"]}"' if a["anchor"] != "start" else ""
                box = f' data-box="{a["box"][0]:.1f},{a["box"][1]:.1f}"' if a["box"] else ""
                body.append(f'<text x="{a["x"]:.1f}" y="{a["y"]:.1f}" font-size="{a["size"]:g}"{weight}{style}{fam}{paint("fill", a["fill"])}{anchor}{box}>'
                            f'{escape(a["s"])}</text>')
        body.append(f'<rect x=".5" y=".5" width="{W - 1:g}" height="{H - 1:g}" rx="7.5" fill="none"{paint("stroke", "frame")} stroke-width="1"/>')  # the desk's edge
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:g} {H:g}" width="{W:g}" height="{H:g}" '
                f'font-family="{escape(SANS, quote=True)}" role="img" aria-label="{escape(self.label, quote=True)}">')
        return "\n".join([head, "<defs>", *defs, "</defs>", *body, "</svg>"]) + "\n"

    def overlaps(self) -> list:
        """Pairs of texts whose boxes cross, as measured while building."""
        bad = []
        for i, a in enumerate(self.texts):
            for b in self.texts[i + 1:]:
                if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1:  # a pixel of slack on each side
                    bad.append((a[4], b[4]))
        return bad


# the diagrams (no data)

LEGEND_PC = ("line", "arrow", "stays on your PC")  # the legend entries the diagrams share
LEGEND_AI = ("line", "orange_line", "sent to the AI backend")
LEGEND_EV = ("hl", "hl", "the evidence")
LEGEND_STOP = ("line", "red_line", "stopped by a check")


def diagram_pieces() -> Fig:
    """Your files and the panel; the Offerowl server; the one AI backend; the documents."""
    f = Fig(900, 420, "Your files and the panel in your browser go to the Offerowl server on your PC. The server reads the files, "
                      "keeps the facts their quotes back, plans each job, has the one AI backend you chose write from "
                      "that evidence, typesets and checks. It sends the AI backend the text of the files you add, the posting and the evidence of the part being written, and gives "
                      "back a resume, a portfolio deck, a cover letter and an interview kit, all on your PC")
    f.card(20, 28, 160, 112, "Your files", ["old resumes, portfolios, notes, reports"], icon="folder", color="blue")
    f.card(20, 236, 160, 124, "Panel", ["in your browser: follow the run, change any sentence"], icon="panel")
    sx, sy, sw, sh = 256, 28, 212, 332  # the server
    f.pane(box_path(sx, sy, sw, sh), (sx, sy, sw, sh))
    f.mark(sx + 12, sy + 12, 24)  # the product's own mark, as on the panel's bar
    f.text(sx + 44, sy + 29, "Offerowl server", size=14.5, weight=600, fill="ink", box=(sx + 44, sx + sw - 12))
    f.text(sx + 12, sy + 54, "on your PC", size=12.5, fill="ink3", box=(sx + 12, sx + sw - 12))
    steps = [("folder", "blue", "reads your files"), ("check", "amber", "keeps facts with quotes"), ("map", "ink3", "plans each job"),
             ("edit", "orange", "writes from evidence"), ("file", "green", "typesets"), ("search", "ink3", "checks every page")]
    for i, (ic, col, words) in enumerate(steps):  # its work, a row each, as the panel lists a run's steps
        ry = sy + 68 + i * 43  # the row's top
        f.rule(sx + 12, sx + sw - 12, ry)
        f.icon(ic, sx + 12, ry + 14, 15, col)
        if col == "amber":  # the facts and their quotes: the evidence, marked
            f.hl(sx + 36, ry + 26, words, 13)
        f.text(sx + 36, ry + 26, words, size=13, fill="ink2" if col != "amber" else "ink", box=(sx + 36, sx + sw - 12),
               fit=natural(words, 13) if col == "amber" else None)
    f.card(546, 136, 156, 124, "AI backend", ["the one you choose: Claude Code, Codex or a local model"], icon="agent", color="orange", rim="rainbow")
    outs = [("Resume", "Korean, English"), ("Portfolio deck", "16:9 slides"), ("Cover letter", "one page"), ("Interview kit", "questions, scripts")]
    for i, (t, s) in enumerate(outs):  # the four documents, stacked on the right
        f.doc(744, 28 + i * 86, 136, 72, t, [s], size=13.5, sub=12)
    f.arrow([(180.5, 84), (255, 84)], label="your files", label_xy=(218, 76), label_box=(182, 254))
    f.arrow([(180.5, 280), (255, 280)], label="your edits", label_xy=(218, 272), label_box=(182, 254))
    f.arrow([(255.5, 322), (181.5, 322)], label=["evidence of", "a sentence"], label_xy=(218, 340), label_box=(182, 254))
    f.arrow([(468.5, 174), (545, 174)], color="orange_line", label=["file text,", "evidence,", "the posting"], label_xy=(507, 128), label_box=(470, 544))
    f.arrow([(545.5, 222), (469.5, 222)], color="orange_line", label=["drafts", "citing it"], label_xy=(507, 240), label_box=(470, 544))
    f.path("M468.5,52 H722 V286", stroke="arrow", sw=1.4, extra='stroke-linejoin="round"')  # the trunk the four branches leave from
    for i in range(4):  # the trunk to each document
        f.arrow([(722, 28 + i * 86 + 36), (743, 28 + i * 86 + 36)])
    f.text(595, 44, "checked documents", size=12, anchor="middle", box=(472, 718))
    f.legend(0, 392, [LEGEND_PC, LEGEND_AI, LEGEND_EV], end=880)  # at the right, under the documents
    return f


def diagram_sentence() -> Fig:
    """How one sentence is made, from the evidence to the export, with the stopped branch: Make's chain of steps."""
    f = Fig(900, 412, "How one sentence is made. A fact you confirmed carries the source's own words. The AI backend drafts "
                      "the sentence from that evidence and cites its ids. The fact check holds every number, name, tool and claim "
                      "against the evidence: a sentence that fails is stopped, rewritten once from the same evidence, and dropped "
                      "if it still fails. The style pack checks the wording. The page is typeset, the layout is checked, and then "
                      "it can be exported")
    tip, gap = 16, 4  # a step's point, and the light between a point and the next notch
    y1, h1 = 24, 112  # the first row
    sw = (860 + 3 * (tip - gap)) / 4  # four steps across the desk, each overlapping the next by its point
    xs = [20 + i * (sw - tip + gap) for i in range(4)]  # their left edges
    first = [("Evidence", "check", "amber", ["a fact you confirmed,", "the source's own words"], "the source's own words", "rim"),
             ("Draft", "agent", "orange", ["the AI backend writes from the evidence and cites its ids"], None, "rainbow"),
             ("Fact check", "search", "ink3", ["numbers, names, tools and claim strength"], None, "rim"),
             ("Style pack", "sliders", "ink3", ["banned words and patterns, lengths, highlights"], None, "rim")]
    cards = []
    for i, (t, ic, col, lines, hl, rim) in enumerate(first):  # the chain, left to right
        notch, point = i > 0, i < 3  # the first has no notch; the last turns down instead of pointing on
        d = chevron(xs[i], y1, sw, h1, tip, notch=notch, point=point)
        cards.append(f.card(xs[i], y1, sw, h1, t, lines, icon=ic, color=col, rim=rim, d=d, pad_l=12 + (tip if notch else 0),
                            pad_r=12 + (tip if point else 0), hl_line=hl, wrap_lines=hl is None))
    y2, h2 = 286, 100  # the second row, back from right to left
    rw = sw  # the same width
    rx = [880 - rw, 880 - rw - (rw - tip + gap)]  # Render, then Layout checks
    second = [("Render", "file", "green", ["DOCX and PDF from one layout"]), ("Layout checks", "search", "ink3", ["page fill, line ends, overflow"])]
    for i, (t, ic, col, lines) in enumerate(second):
        notch = i > 0  # Render takes the turn with a straight edge; Layout checks is notched behind
        d = chevron(rx[i], y2, rw, h2, tip, notch=notch, point=True, left=True)
        f.card(rx[i], y2, rw, h2, t, lines, icon=ic, color=col, d=d, pad_l=12 + tip, pad_r=12 + (tip if notch else 0))
    ex = f.doc(rx[1] - 60 - 178, y2 + 4, 178, 92, "Export", ["the PDF and DOCX you send"], size=14, sub=12.5)  # the document that goes out
    f.arrow([(rx[1] - 0.5, y2 + h2 / 2), (ex["r"] + 1, y2 + h2 / 2)], label="passes", label_xy=((rx[1] + ex["r"]) / 2, y2 + h2 / 2 - 8),
            label_box=(ex["r"] + 2, rx[1] - 2))
    down = xs[3] + sw / 2  # Style pack's middle, down to Render
    f.arrow([(down, y1 + h1 + 0.5), (down, y2 - 1)], label="passes", label_xy=(down + 8, (y1 + h1 + y2) / 2 + 4), label_anchor="start",
            label_box=(down + 8, 880))
    stop = f.card(cards[2]["cx"] - 92, 168, 184, 64, "Stopped", ["one rewrite, else dropped"], lamp="red_line", size=14, sub=12)  # the branch
    stop_t = stop["t"]
    f.arrow([(cards[2]["cx"], y1 + h1 + 0.5), (cards[2]["cx"], stop_t - 1)], color="red_line", label="fails", label_xy=(cards[2]["cx"] + 8, y1 + h1 + 22),
            label_anchor="start", label_box=(cards[2]["cx"] + 8, stop["r"] + 40))
    back = cards[1]["cx"]  # back up into Draft
    f.arrow([(stop["l"] - 0.5, stop["cy"]), (back, stop["cy"]), (back, y1 + h1 + 1)], color="red_line", label="rewrite", label_xy=(back + 8, stop["cy"] - 8),
            label_anchor="start", label_box=(back + 8, stop["l"] - 2))
    f.legend(20, 316, [LEGEND_EV], right=ex["l"] - 10)  # the legend in the empty corner, one entry a line
    f.legend(20, 340, [("rim", "rainbow", "the AI backend writes")], right=ex["l"] - 10)
    f.legend(20, 364, [LEGEND_STOP], right=ex["l"] - 10)
    return f


def diagram_interview() -> Fig:
    """From the posting, the resume and the portfolio to the question map, the scenes, the audits, the search view and
    practice."""
    f = Fig(900, 424, "The interview kit. The posting, the resume and the portfolio you sent, and your confirmed facts, give the "
                      "question map: questions for each posting line, resume line, portfolio page and term, plus behavioral, company "
                      "and opening questions. Each question gets a scene, a short dialogue in English with the Korean translation "
                      "under each line and speech marks, drafted by the AI backend from your evidence and checked. Audits rate how "
                      "well the scenes cover the posting and compare them with what you sent. The search view finds a scene by "
                      "keyword on your PC, practice mode asks the questions and gives feedback, and cue cards print the scenes")
    ins = [f.note(20, 24, 166, 74, "Posting", ["each line a question"]),
           f.doc(20, 112, 166, 74, "Resume you sent", ["each line a question"], size=13.5),
           f.doc(20, 200, 166, 74, "Portfolio you sent", ["each page a question"], size=13.5),
           f.card(20, 288, 166, 74, "Your facts", ["the only evidence"], icon="check", color="amber", size=14, sub=12.5, hl_line="the only evidence")]
    mx, mw = 240, 186  # the question map
    f.pane(box_path(mx, 24, mw, 338), (mx, 24, mw, 338))
    f.tile(mx + 12, 37, "map")
    f.text(mx + 43, 53, "Question map", size=14.5, weight=600, fill="ink", box=(mx + 43, mx + mw - 12))
    kinds = ["posting lines", "resume lines", "portfolio pages", "terms you used", "behavioral", "company", "opening logistics"]
    for i, k in enumerate(kinds):  # the kinds of question, a row each
        ry = 70 + i * 41
        f.rule(mx + 12, mx + mw - 12, ry)
        f.text(mx + 12, ry + 26, k, size=13, fill="ink2", box=(mx + 12, mx + mw - 12))
    sc = f.card(482, 24, 182, 162, "Scenes", ["English lines with the Korean translation under each, speech marks, one key phrase"], icon="agent",
                color="orange", rim="rainbow")
    au = f.card(482, 222, 182, 140, "Audits", ["posting coverage: strong, weak or none", "consistency with what you sent"], icon="search")
    sv = f.card(722, 24, 158, 104, "Search view", ["a scene by keyword, on your PC"], icon="search", size=14, sub=12)
    pr = f.card(722, 142, 158, 104, "Practice", ["timer, your voice, feedback on your facts"], icon="mic", size=14, sub=12)
    cc = f.doc(722, 260, 158, 102, "Cue cards", ["one scene per card, to print"], size=14, sub=12)  # printed pages
    for b in ins:  # each input into the map
        f.arrow([(b["r"] + 0.5, b["cy"]), (mx - 1, b["cy"])])
    f.arrow([(mx + mw + 0.5, 104), (sc["l"] - 1, 104)], color="orange_line", label="draft", label_xy=((mx + mw + sc["l"]) / 2, 96), label_box=(mx + mw + 2, sc["l"] - 2))
    f.arrow([(sc["cx"], sc["b"] + 0.5), (sc["cx"], au["t"] - 1)], label="checked", label_xy=(sc["cx"] + 8, (sc["b"] + au["t"]) / 2 + 4), label_anchor="start",
            label_box=(sc["cx"] + 8, sc["r"]))
    f.arrow([(mx + mw + 0.5, 292), (au["l"] - 1, 292)], label="gaps", label_xy=((mx + mw + au["l"]) / 2, 284), label_box=(mx + mw + 2, au["l"] - 2))
    f.arrow([(sc["r"] + 0.5, sv["cy"]), (sv["l"] - 1, sv["cy"])])
    f.arrow([(sc["r"] + 0.5, 130), (700, 130), (700, pr["cy"]), (pr["l"] - 1, pr["cy"])])
    f.arrow([(sc["r"] + 0.5, 158), (686, 158), (686, cc["cy"]), (cc["l"] - 1, cc["cy"])])
    f.legend(0, 396, [LEGEND_PC, LEGEND_AI, LEGEND_EV], end=880)  # at the right
    return f


def diagram_ways() -> Fig:
    """The four ways to run Offerowl, with what runs where in each."""
    f = Fig(900, 444, "Four ways to run Offerowl. The app is one file that starts the panel and its server on your PC and typesets "
                      "with the browser you already have. The container runs the panel, the engine, the interview view and the typesetting tools "
                      "together, with a volume for your files. The Helm chart runs the same in one pod with a volume claim, reached by "
                      "a port-forward. The Python package gives the offerowl command and the panel, and typesets with Docker or with "
                      "the browser already on your PC")
    cols = [("The app", "apps/desktop", [("layers", "ink3", "Panel and server", "the app's own Python"), ("globe", "ink3", "Your browser", "opens the panel"),
                                          ("agent", "orange", "AI backend", "Claude Code or Codex on this PC, or a local model"), ("file", "green", "Typesetting", "your own Chrome or Edge")]),
            ("Docker", "deploy/docker", [("layers", "ink3", "One container", "panel, engine, interview view"), ("file", "green", "Typesetting", "LibreOffice and Chromium inside"),
                                         ("agent", "orange", "AI backend", "a local model server, or none"), ("folder", "blue", "Your files", "a volume")]),
            ("Kubernetes", "deploy/helm/offerowl", [("layers", "ink3", "One pod", "the same image as Docker"), ("link", "ink3", "Port-forward", "the panel on this PC"),
                                                    ("agent", "orange", "AI backend", "a model server in the cluster, or none"), ("folder", "blue", "Your files", "a volume claim")]),
            ("Python package", "pyproject.toml", [("layers", "ink3", "offerowl", "every command and the panel"), ("file", "green", "Typesetting", "Docker, or the PC's own browser"),
                                                  ("agent", "orange", "AI backend", "Claude Code, Codex or a local model"), ("folder", "blue", "Your files", "the data folder")])]
    cw, gap = 206, 12  # column width and the space between columns
    for c, (title, code, parts) in enumerate(cols):
        x = 20 + c * (cw + gap)  # the column's left edge
        f.pane(box_path(x, 24, cw, 376), (x, 24, cw, 376))  # one pane: its head, then its parts on rows
        f.text(x + 14, 50, title, size=16, weight=600, fill="ink", box=(x + 14, x + cw - 12))
        f.text(x + 14, 70, code, size=12, fill="ink3", mono=True, box=(x + 14, x + cw - 12))
        for i, (ic, col, t, s) in enumerate(parts):  # the parts of this way, top to bottom
            y = 86 + i * 78  # each row's top
            f.rule(x + 12, x + cw - 12, y)
            f.tile(x + 12, y + 12, ic, col)
            f.text(x + 43, y + 28, t, size=13.5, weight=600, fill="ink", mono=(t == "offerowl"), box=(x + 43, x + cw - 12))
            for j, ln in enumerate(wrap(s, 12, cw - 24)):
                f.text(x + 12, y + 49 + j * 16, ln, size=12, fill="ink3", box=(x + 12, x + cw - 12))
    f.legend(0, 418, [("tile", ("agent", "orange"), "the AI backend: the one part that may send text off your PC")], end=880)  # at the right
    return f


def diagram_modules() -> Fig:
    """The code as it is laid out today, grouped by the part of the pipeline each file serves."""
    f = Fig(900, 640, "The modules. The desktop app starts the panel's server, which serves the page and Offerowl's one HTTP API; "
                      "the page only calls the API, and the agent's tools (apps/mcp) call it too. The API and the offerowl command call the engine in src: ingest reads files "
                      "into fact candidates; the writing modules call the one AI backend through llm.py; the renderers typeset the "
                      "resume, the deck and the cover letter; the checks hold every sentence and page to its evidence and layout; "
                      "the interview package builds the kit and the talk; decide answers typed questions. core/schema describes the files they share")
    top = [("apps/desktop", "the one-file app"), ("apps/panel", "the page, its server"), ("apps/api", "one HTTP API"), ("apps/mcp", "the agent's tools"), ("offerowl", "the command line")]
    tw, tg = 160, 15  # a program's width and the space between
    tops = []
    for i, (t, sub) in enumerate(top):  # the programs, left to right as they call each other
        x = 20 + i * (tw + tg)
        f.pane(box_path(x, 24, tw, 66), (x, 24, tw, 66))
        f.text(x + 12, 50, t, size=13, weight=600, fill="ink", mono=True, box=(x + 12, x + tw - 12))
        f.text(x + 12, 72, sub, size=12, fill="ink3", box=(x + 12, x + tw - 12))
        tops.append(x)
    f.arrow([(tops[0] + tw + 0.5, 57), (tops[1] - 1, 57)])  # the app starts the panel's server
    f.arrow([(tops[1] + tw + 0.5, 57), (tops[2] - 1, 57)])  # the page calls the API
    f.arrow([(tops[3] - 0.5, 57), (tops[2] + tw + 1, 57)])  # the agent's tools call the API too
    gw, gg = 206, 12  # a group's width and the space between
    gx = [20 + i * (gw + gg) for i in range(4)]
    bus = 120  # the line the API and the command reach the engine on
    api_x, cli_x = tops[2] + tw / 2, tops[4] + tw / 2
    f.path(f"M{api_x:.1f},90.5 V{bus} M{cli_x:.1f},90.5 V{bus} M{gx[0] + gw / 2:.1f},{bus} H{cli_x:.1f}", stroke="arrow", sw=1.4)
    for x in gx:  # into each group of the engine
        f.arrow([(x + gw / 2, bus), (x + gw / 2, 147)])
    f.text((api_x + cli_x) / 2, bus - 8, "call the engine in src/", size=12, anchor="middle", box=(api_x + 8, cli_x - 8))
    groups = [("Reading files", "folder", "blue", [("ingest.py", "files to fact candidates", None), ("review.py", "merge the facts you keep", None),
                                                    ("probe_extract.py", "deck measurements", None), ("ocr_selfcheck.py", "scanned pages", None)]),
              ("Writing", "edit", "orange", [("llm.py", "the one door to the AI", "orange_line"), ("write_resume.py", "resume parts", None),
                                             ("cover.py", "cover letters", None), ("draft.py", "fit, translation, figures", None)]),
              ("Typesetting", "file", "green", [("layout.js", "resume and letter DOCX", None), ("resume_form.js", "the resume's parts", None),
                                                ("deck_slides.js", "the 16:9 deck", None), ("render_html/", "typeset with your browser", None)]),
              ("Checking", "search", "ink3", [("factcheck.py", "numbers, names, claims", "red_line"), ("check_documents.py", "resume and deck checks", None),
                                              ("check_render.py", "layout of the pages", None), ("style/", "style packs", None)])]
    for (name, ic, col, files), x in zip(groups, gx):  # four groups of the engine, side by side
        f.pane(box_path(x, 148, gw, 300), (x, 148, gw, 300))
        f.tile(x + 12, 161, ic, col)
        f.text(x + 43, 177, name, size=14.5, weight=600, fill="ink", box=(x + 43, x + gw - 12))
        for i, (fn, note, lamp) in enumerate(files):  # its files, a row each
            ry = 194 + i * 63
            f.rule(x + 12, x + gw - 12, ry)
            fw = f.text(x + 12, ry + 26, fn, size=13, weight=600, fill="ink", mono=True, box=(x + 12, x + gw - 30))
            if lamp:  # the door to the AI, the rules that stop a text: a lamp of their meaning
                f.dot(x + 12 + fw + 10, ry + 21.5, lamp)
            f.text(x + 12, ry + 46, note, size=12, fill="ink3", box=(x + 12, x + gw - 12))
    kx, kw = 20, 532  # the interview kit
    f.pane(box_path(kx, 466, kw, 126), (kx, 466, kw, 126))
    f.tile(kx + 12, 479, "chat")
    tw2 = f.text(kx + 43, 495, "Interview kit", size=14.5, weight=600, fill="ink", box=(kx + 43, kx + kw - 12))
    f.text(kx + 43 + tw2 + 8, 495, "src/interview/", size=12, fill="ink3", mono=True, box=(kx + 43 + tw2 + 8, kx + kw - 12))
    mods = [("plan.py", "the map"), ("draft.py", "scenes"), ("audit.py", "audits"), ("server.py", "the pages"), ("talk.py", "the talk")]
    mw = (kw - 24) / len(mods)  # a module's column
    f.rule(kx + 12, kx + kw - 12, 512)
    for i, (t, sub) in enumerate(mods):
        x = kx + 12 + i * mw
        if i:  # a hairline between two modules
            f.path(f"M{x - 6:.1f},524 V580", stroke="rule", sw=1)
        f.text(x, 542, t, size=12.5, weight=600, fill="ink", mono=True, box=(x, x + mw - 12))
        f.text(x, 562, sub, size=12, fill="ink3", box=(x, x + mw - 12))
    dx, dw = 564, 316  # decisions and shapes
    f.pane(box_path(dx, 466, dw, 126), (dx, 466, dw, 126))
    f.tile(dx + 12, 479, "sliders")
    f.text(dx + 43, 495, "Decisions and shapes", size=14.5, weight=600, fill="ink", box=(dx + 43, dx + dw - 12))
    f.rule(dx + 12, dx + dw - 12, 512)
    for i, (t, sub) in enumerate([("decide/", "rules, the agent, small models"), ("core/schema", "profile, job and documents")]):
        x = dx + 12 + i * (dw - 24) / 2
        if i:
            f.path(f"M{x - 6:.1f},524 V580", stroke="rule", sw=1)
        f.text(x, 542, t, size=12.5, weight=600, fill="ink", mono=True, box=(x, x + (dw - 24) / 2 - 12))
        for j, ln in enumerate(wrap(sub, 12, (dw - 24) / 2 - 12)):
            f.text(x, 562 + j * 16, ln, size=12, fill="ink3", box=(x, x + (dw - 24) / 2 - 12))
    f.legend(0, 612, [("dot", "orange_line", "sends to the AI backend"), ("dot", "red_line", "holds the rules that stop a text")], end=880)
    return f


# the check in a browser

MEASURE = """(force) => {
  // every text of the SVG: its rendered box against the room it was given (data-box), and against every other text
  const svg = document.querySelector('svg');
  if (force) { const st = document.createElementNS('http://www.w3.org/2000/svg', 'style'); st.textContent = force; svg.prepend(st); }
  const vb = svg.viewBox.baseVal;
  const texts = [...svg.querySelectorAll('text')].map((t) => { const b = t.getBBox(); return { s: t.textContent, x0: b.x, x1: b.x + b.width, y0: b.y, y1: b.y + b.height, box: t.getAttribute('data-box') }; });
  const out = { texts: texts.length, overflow: [], overlap: [], outside: [] };
  for (const t of texts) {
    if (t.box) { const [l, r] = t.box.split(',').map(Number); if (t.x0 < l - 2 || t.x1 > r + 2) out.overflow.push(`${t.s} [${t.x0.toFixed(1)}..${t.x1.toFixed(1)} in ${l}..${r}]`); }
    if (t.x0 < vb.x || t.x1 > vb.x + vb.width || t.y0 < vb.y || t.y1 > vb.y + vb.height) out.outside.push(t.s);
  }
  for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
    const a = texts[i], b = texts[j];
    if (a.x0 < b.x1 - 1 && b.x0 < a.x1 - 1 && a.y0 < b.y1 - 2 && b.y0 < a.y1 - 2) out.overlap.push(`${a.s} | ${b.s}`);
  }
  return out;
}"""
FORCED = {  # the fonts a viewer may fall back to, forced on every text: the widest and a narrow one
    "wide font": "text { font-family: 'DejaVu Sans', sans-serif !important; } text.m { font-family: 'DejaVu Sans Mono', monospace !important; }",
    "narrow font": "text { font-family: 'Liberation Sans', sans-serif !important; } text.m { font-family: 'Liberation Mono', monospace !important; }",
}


def check(paths: list, out_dir: pathlib.Path) -> int:
    """Render every SVG in Chrome to a PNG at twice the size, on GitHub's page colour of its theme, and count the texts
    that leave their room, overlap another text or leave the picture: with the fonts this PC has, then with a wide and a
    narrow fallback font forced on every text. Every count must be zero."""
    from playwright.sync_api import sync_playwright  # pip install playwright && python3 -m playwright install chromium
    out_dir.mkdir(parents=True, exist_ok=True)  # the previews go here
    problems = 0  # over every picture and every font
    with sync_playwright() as pw:
        browser = pw.chromium.launch()  # headless
        page = browser.new_page(device_scale_factor=2)  # sharp previews
        for path in paths:
            theme = "dark" if path.stem.endswith("-dark") else "light"  # the page colour behind the picture
            svg = path.read_text(encoding="utf-8")
            html = f'<html><body style="margin:0;padding:16px;background:{THEMES[theme]["page"]}">{svg}</body></html>'
            page.set_content(html)
            page.locator("svg").screenshot(path=str(out_dir / f"{path.stem}.png"))  # the preview to look at
            counts = []  # this PC's fonts, then each forced one
            for name, force in [("this PC", ""), *FORCED.items()]:
                page.set_content(html)  # a fresh copy: the forced style goes into the SVG
                got = page.evaluate(MEASURE, force)
                n = len(got["overflow"]) + len(got["overlap"]) + len(got["outside"])
                counts.append(n)
                for k in ("overflow", "overlap", "outside"):  # the details of anything found
                    for x in got[k][:4]:
                        print(f"    {name}: {k}: {x}")
            problems += sum(counts)
            print(f"{path.name:32} texts {got['texts']:3}  this PC {counts[0]}  wide font {counts[1]}  narrow font {counts[2]}")
        browser.close()
    print(f"check: {len(paths)} pictures, {problems} problems over this PC's fonts and the wide and narrow fallbacks; previews in {out_dir}")
    return problems


# the pictures with numbers

def load(name: str) -> dict:
    """One data file of tools/measure.py; a missing file stops with the command that makes it."""
    p = DATA / f"{name}.json"
    if not p.is_file():
        raise SystemExit(f"{p.relative_to(ROOT)} is missing: run `python3 tools/measure.py` first")
    return json.loads(p.read_text(encoding="utf-8"))


def bar(f: Fig, x, y, w, h, color):
    """A bar on its track, square as the panel's (2 px corners)."""
    if w <= 0:
        return
    f.rect(x, y, w, h, fill=color, rx=min(2, w / 2))


def chart_factcheck() -> Fig:
    """Per task: texts drafted, passed as written, and stopped (rewritten or dropped); and why the stopped ones were
    stopped. An Insights tile on the desk."""
    D = load("drafts")
    T = {t["task"]: t for t in D["tasks"]}  # the tasks by name
    f = Fig(900, 444, "")
    px, py, pw, ph = 20, 20, 860, 404  # the tile
    f.pane(box_path(px, py, pw, ph), (px, py, pw, ph))
    f.tile(px + 16, py + 16, "check", "amber")  # the evidence's mark: what the check holds a text to
    f.text(px + 48, py + 32, "The fact check stops what the evidence does not hold", size=15.5, weight=600, fill="ink", box=(px + 48, px + pw - 16))
    dates = sorted({t.get('recorded') for t in D['tapes'].values() if t.get('recorded')})  # the tapes may have been recorded on different days
    when = dates[0] if len(dates) == 1 else ', '.join(dates[:-1]) + ' and ' + dates[-1]  # each day once
    sub = (f"Drafts for the fictional example, written by the AI backend on {when} and replayed by tools/measure.py. "
           f"A text is a sentence, a title or a card line; a scene counts once.")
    for i, ln in enumerate(wrap(sub, 12.5, pw - 64)):
        f.text(px + 48, py + 54 + i * 18, ln, size=12.5, fill="ink3", box=(px + 48, px + pw - 16))
    f.rule(px + 16, px + pw - 16, py + 98)
    rows = [("resume", "Resume"), ("cover", "Cover letter"), ("interview", "Interview")]
    x0, bw = px + 20, 392  # the bars' left edge and full width
    f.text(x0, py + 128, "What happened to each drafted text", size=13, weight=600, fill="ink2", box=(x0, x0 + bw))
    for i, (key, name) in enumerate(rows):
        t = T[key]  # this task's counts
        y = py + 146 + i * 72  # the row's top
        unit = "scenes" if t["unit"] == "scenes" else "sentences" if key == "cover" else "texts"  # what was counted
        f.text(x0, y + 12, f"{name}, {t['drafted']} {unit}", size=12.5, weight=600, fill="ink", box=(x0, x0 + bw))
        gone = t.get("dropped", 0)  # still failing after the rewrite
        fixed = t["stopped"] - gone  # rewritten from the same evidence and passed
        if t["kept"] + t["stopped"] != t["drafted"]:  # a bar longer than its row is a wrong number, not a wrong drawing
            raise SystemExit(f"chart-factcheck: {key}: {t['kept']} kept + {t['stopped']} stopped is not {t['drafted']} drafted")
        f.rect(x0, y + 21, bw, 12, fill="track", rx=2)  # the track
        parts = [p for p in [(t["kept"], "violet_bar"), (fixed, "red_bar"), (gone, "red_deep")] if p[0] > 0]  # parts at zero draw nothing
        x = x0
        for j, (n, color) in enumerate(parts):
            w = bw * n / max(1, t["drafted"]) - (2 if j < len(parts) - 1 else 0)  # a 2 px gap between parts
            bar(f, x, y + 21, w, 12, color)
            x += w + 2
        words = f"{t['kept']} passed as written, {fixed} stopped and rewritten, {gone} dropped" if t["stopped"] else f"{t['kept']} passed as written, none stopped"
        f.text(x0, y + 51, words, size=12, fill="ink3", box=(x0, x0 + bw))
    X, XR = px + 464, px + pw - 20  # the second figure's edges
    f.text(X, py + 128, f"Why the {D['stopped']} were stopped", size=13, weight=600, fill="ink2", box=(X, XR))
    reasons = [("name", "a name the cited evidence lacks"), ("number", "a number the cited evidence lacks"),
               ("tool", "a tool the profile does not show"), ("claim", "a claim stronger than the evidence"), ("style", "wording the style pack bans")]
    counts = {k: sum(t["reasons"].get(k, 0) for t in D["tasks"]) for k, _ in reasons}  # over every task
    top = max(1, max(counts.values()))  # the longest bar
    for i, (k, words) in enumerate(reasons):
        y = py + 146 + i * 42
        f.text(X, y + 12, words, size=12.5, fill="ink", box=(X, XR - 40))
        f.text(XR, y + 12, str(counts[k]), size=12.5, weight=600, fill="ink", anchor="end", box=(XR - 40, XR))
        f.rect(X, y + 20, XR - X, 8, fill="track", rx=2)  # the track
        bar(f, X, y + 20, (XR - X) * counts[k] / top, 8, "red_bar")  # nothing at zero
    f.rule(px + 16, px + pw - 16, py + ph - 42)
    f.legend(px + 20, py + ph - 28, [("dot", "violet_bar", "passed as written"), ("dot", "red_bar", "stopped, then rewritten from the same evidence"),
                                     ("dot", "red_deep", "stopped and dropped")], right=px + pw - 16)
    f.label = (f"Texts drafted for the fictional example, by task. Resume: {T['resume']['drafted']} texts, {T['resume']['kept']} passed as written, "
               f"{T['resume']['stopped'] - T['resume'].get('dropped', 0)} stopped and rewritten from the same evidence, {T['resume'].get('dropped', 0)} dropped. Cover letter: "
               f"{T['cover']['drafted']} sentences, {T['cover']['stopped']} stopped. Interview scenes: {T['interview']['drafted']}, "
               f"{T['interview']['stopped']} stopped. Why: " + ", ".join(f"{counts[k]} for {w}" for k, w in reasons))
    return f


PICTURES = {  # every picture this script draws, in the order of the README
    "chart-factcheck": chart_factcheck,
    "diagram-pieces": diagram_pieces, "diagram-sentence": diagram_sentence, "diagram-interview": diagram_interview,
    "diagram-ways": diagram_ways, "diagram-modules": diagram_modules,
}


def sync_alts(labels: dict) -> None:
    """Write each picture's text into the alt of its <img> in the docs, so the words change with the numbers."""
    pages = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").glob("*.md"))]  # every page that shows a picture
    for page in pages:
        if not page.is_file():  # a page that was removed
            continue
        text = page.read_text(encoding="utf-8")  # as it is now
        new = re.sub(r'<img alt="[^"]*" src="((?:\.\./)?(?:docs/)?assets/([a-z-]+)-light\.svg)"',
                     lambda m: f'<img alt="{escape(labels[m.group(2)], quote=True)}" src="{m.group(1)}"' if m.group(2) in labels else m.group(0), text)
        if new != text:  # only a page that changed is written
            page.write_text(new, encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="build.py", description="Draw the docs' pictures from docs/assets/data, light and dark.")
    ap.add_argument("--check", metavar="DIR", help="render each SVG to DIR/<name>.png in Chrome and measure overflow and overlaps")
    ap.add_argument("--only", default="", help="pictures to draw, comma separated")
    a = ap.parse_args(argv)
    names = [x for x in a.only.split(",") if x] or list(PICTURES)
    written, labels = [], {}
    for name in names:
        fig = PICTURES[name]()  # the drawing, checked for text that leaves its box while it was built
        bad = fig.overlaps()  # texts on top of each other
        if bad:
            raise SystemExit(f"{name}: texts overlap: {bad[:3]}")
        labels[name] = fig.label  # what the alt text says
        for theme in THEMES:  # one copy per theme
            path = HERE / f"{name}-{theme}.svg"
            path.write_text(fig.render(theme), encoding="utf-8")
            written.append(path)
    sync_alts(labels)  # the docs say in words what the pictures now show
    if a.check:  # render and measure in a real browser
        problems = check(written, pathlib.Path(a.check))
        if problems:
            print(f"check: {problems} problems")
            return 1
    print(f"build: {len(written)} SVG files written to {HERE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
