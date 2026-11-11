#!/usr/bin/env python3
"""Draw the pictures of Offerowl's docs from docs/assets/data, each in a light and a dark copy (CONTRIBUTING.md).

    python3 docs/assets/build.py                every SVG, light and dark, into docs/assets/ (the README's badges: .github/badges.sh)
    python3 docs/assets/build.py --check DIR    also render each SVG to DIR/<name>.png in Chrome and measure text that
                                                leaves its box or overlaps other text (needs Playwright with Chromium)

The numbers come from tools/measure.py, which writes docs/assets/data/*.json; nothing here is typed by hand. The house
style is made of the parts of the documents Offerowl makes, so the docs look like the resume and the deck they describe:

  a step of a diagram          the resume's project card: a title bar over the pale band
  a finished document          a page with a folded corner
  a chart's title              the resume's section title: a short blue bar, the title in navy, a thin rule

and a colour that means one thing everywhere, on a card's title bar, an arrow or a bar:

  navy    stays on your PC              orange  sent to the AI backend
  amber   the evidence (the highlighter) red    stopped by a check

Text widths are measured with the Pretendard files in fonts/, the first font the pictures ask for, so the layout is the
same on every machine. Every text keeps 8 percent of room to spare for the wider system fonts a viewer may fall back to.
"""
from __future__ import annotations  # `str | None` hints on Python 3.10

import argparse  # the command line
import json  # the data files
import math  # arrow geometry
import pathlib  # paths
import re  # the <img> tags of the docs
import sys  # exit codes
from html import escape  # text inside SVG

from PIL import ImageFont  # text widths from the font files

HERE = pathlib.Path(__file__).resolve().parent  # docs/assets
ROOT = HERE.parent.parent  # the repository
DATA = HERE / "data"  # tools/measure.py writes here
FONTS = ROOT / "fonts"  # Pretendard, which the documents use too

SANS = "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"  # labels
DISPLAY = SANS  # display numbers: Pretendard too, the brand's one typeface
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"  # file and module names
SPARE = 1.08  # room kept for fonts wider than Pretendard (Segoe UI, Noto Sans)

# The two themes: the colours of the resume Offerowl prints (owl navy, its pale blue band and blue-gray rule, the amber of
# its highlight), and the meaning colours. The red and the orange were checked apart for colour-blind readers in both
# themes; every use also has a word beside it.
THEMES = {
    "light": {"bg": "#ffffff", "ink": "#1b2e4b", "muted": "#566175", "box": "#eef3f9", "line": "#c9d4e3", "arrow": "#7f8ca1",
              "grid": "#eef3f9", "gray": "#8d98ab", "blue": "#2f6eba", "orange": "#d9622b", "red": "#c8102e",
              "redsoft": "#f0a7b3", "gold": "#b7860b", "hl": "#f6d35b", "hlsoft": "rgba(246,211,91,.45)",
              # the deck's cover: its name panel, the rule and the tile notes on it, and its highlighter, as measured on a printed cover
              "panel": "#14233a", "prule": "#394659", "ptext": "#ffffff", "pmuted": "#99a6bb", "hlpale": "#fff0a0",
              # a card's title bar per meaning, with white words (amber takes navy words), each at 4.5:1 or more
              "barpc": "#1b2e4b", "barai": "#b3400a", "barev": "#f2c744", "barstop": "#c8102e", "bartext": "#ffffff", "evtext": "#1b2e4b",
              # a finished document's page and its fold; a chart's passing bars; a table's head; a section title's bar
              "page": "#ffffff", "fold": "#dde5ef", "pass": "#1b2e4b", "head": "#1b2e4b", "headtext": "#ffffff", "secbar": "#2f6eba",
              # the path of a run: its line runs from the colour set's pale step to navy, as the deck's career path does
              "st0": "#94b5db", "st3": "#1b2e4b"},
    "dark": {"bg": "#111722", "ink": "#e8edf5", "muted": "#a3afc2", "box": "#18212f", "line": "#34435c", "arrow": "#6f7d95",
             "grid": "#1c2636", "gray": "#6f7c91", "blue": "#6fa3e8", "orange": "#e8834f", "red": "#ff8a8a",
             "redsoft": "#7d3b3f", "gold": "#d4a72c", "hl": "rgba(242,199,68,.8)", "hlsoft": "rgba(242,199,68,.34)",
             "panel": "#14233a", "prule": "#394659", "ptext": "#ffffff", "pmuted": "#99a6bb", "hlpale": "rgba(242,199,68,.3)",
             "barpc": "#2a4a78", "barai": "#b3400a", "barev": "#f2c744", "barstop": "#c8102e", "bartext": "#ffffff", "evtext": "#1b2e4b",
             "page": "#18212f", "fold": "#2a3547", "pass": "#7d9cc7", "head": "#2a4a78", "headtext": "#ffffff", "secbar": "#6fa3e8",
             "st0": "#3a5378", "st3": "#9cbbe6"},
}


def mix(a: str, b: str, t: float) -> str:
    """A colour between two hex colours: t 0 is a, 1 is b."""
    pa, pb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]  # their channels
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))  # the same step on each channel


for _t in THEMES.values():  # the two stations between the ends of the path
    _t["st1"], _t["st2"] = mix(_t["st0"], _t["st3"], 1 / 3), mix(_t["st0"], _t["st3"], 2 / 3)

BAR = {"blue": "barpc", "orange": "barai", "gold": "barev", "red": "barstop"}  # a meaning colour to its title bar


# measuring text

_FONT_CACHE = {}  # (weight, mono, size) -> PIL font


def font(size: float, weight: int = 400, mono: bool = False):
    """The Pretendard cut closest to a weight, at a size (the mono width is approximated by a fixed advance)."""
    name = "Pretendard-Bold.ttf" if weight >= 700 else "Pretendard-SemiBold.ttf" if weight >= 600 else "Pretendard-Regular.ttf"  # three cuts ship in fonts/
    key = (name, round(size * 4))  # quarter pixels are enough
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(str(FONTS / name), size=max(1, round(size * 4)))  # four times the size, for fine widths
    return _FONT_CACHE[key]


def width(text: str, size: float, weight: int = 400, mono: bool = False) -> float:
    """The width of a text in pixels, with room to spare for wider fallback fonts."""
    if mono:  # monospace: 0.6 of the size per character in the common mono fonts
        return len(text) * size * 0.61 * SPARE
    return font(size, weight).getlength(text) / 4 * SPARE  # measured at four times the size


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


# a figure

class Fig:
    """One picture as a list of shapes with colour names; render() writes it once per theme, so the light and the dark
    copy always have the same geometry."""

    def __init__(self, w: float, h: float, label: str, pad: float = 3, bg: bool = False):  # the drawing area and its alt text
        self.w, self.h, self.label, self.pad, self.bg = w, h, label, pad, bg  # size, accessible name, margin, a filled card
        self.items = []  # shapes in drawing order
        self.texts = []  # (x0, y0, x1, y1) of every text box, for the overlap check while building

    # basic shapes
    def rect(self, x, y, w, h, fill="box", stroke=None, sw=1, rx=10, dash=None, extra=""):
        """A rectangle: fill and stroke are colour names of the theme (or None)."""
        self.items.append(("rect", dict(x=x, y=y, w=w, h=h, fill=fill, stroke=stroke, sw=sw, rx=rx, dash=dash, extra=extra)))

    def path(self, d, stroke="arrow", sw=1.6, fill=None, dash=None, extra=""):
        """A path: a line, a connector or a filled shape."""
        self.items.append(("path", dict(d=d, stroke=stroke, sw=sw, fill=fill, dash=dash, extra=extra)))

    def text(self, x, y, s, size=12.5, weight=400, fill="muted", anchor="start", family=SANS, box=None, mono=False):
        """One line of text at a baseline. box = (x0, x1) is the room the text may use; it is checked here and kept in
        the SVG (data-box) for the check in the browser."""
        w = width(s, size, weight, mono)  # its measured width, with room to spare
        x0 = x if anchor == "start" else x - w / 2 if anchor == "middle" else x - w  # where it starts
        if box is not None and (x0 < box[0] - 0.5 or x0 + w > box[1] + 0.5):  # it leaves its room
            raise ValueError(f"text '{s}' ({x0:.0f} to {x0 + w:.0f}) leaves its box {box[0]:.0f} to {box[1]:.0f}")
        self.texts.append((x0, y - size * 0.8, x0 + w, y + size * 0.25, s))  # its box, for overlaps
        self.items.append(("text", dict(x=x, y=y, s=s, size=size, weight=weight, fill=fill, anchor=anchor,
                                        family=MONO if mono else family, box=box)))
        return w

    def hl(self, x, y, w, h=15, fill="hl"):
        """The highlight under a number or a word: a straight band, as the resume prints its result phrases."""
        self.items.append(("hl", dict(x=x, y=y, w=w, h=h, fill=fill)))

    def raw(self, svg: str):
        """SVG as written, with {name} for a colour of the theme (the logo, a gradient)."""
        self.items.append(("raw", dict(s=svg)))

    # composite parts
    def _stack(self, x, y, w, h, title, body, size, sub, mono_title, hl_title, inner):
        """A title and gray lines centred as a block in a room; stops when the block does not fit its height."""
        gap1, gap = size * 1.27, sub * 1.4  # title to first line; line to line
        block = size * 0.72 + (gap1 + (len(body) - 1) * gap + sub * 0.22 if body else 0)  # cap of the title to the last line's foot
        ty = y + (h - block) / 2 + size * 0.72  # the title's baseline
        if hl_title:  # the title sits on the highlighter: it is evidence
            self.hl(x + 10, ty - size * 0.22, width(title, size, 600, mono_title) / SPARE + 6, size * 0.42)
        self.text(inner[0], ty, title, size=size, weight=600, fill="ink", box=inner, mono=mono_title)
        for i, ln in enumerate(body):  # the gray lines under it
            self.text(inner[0], ty + gap1 + i * gap, ln, size=sub, fill="muted", box=inner)
        if ty - size * 0.8 < y + 4 or (ty + gap1 + (len(body) - 1) * gap if body else ty) + 4 > y + h:  # the block must fit the room's height
            raise ValueError(f"box '{title}' is too short for its {len(body)} lines")

    def box(self, x, y, w, h, title, lines=(), color=None, size=15, sub=12.5, mono_title=False, wrap_lines=True, hl_title=False):
        """A step, as the resume prints a selected project: its title on a bar that carries the meaning colour (navy: stays
        on your PC, orange: sent to the AI backend, amber: the evidence, red: stopped by a check) over the pale band with
        gray lines. Without a meaning colour it is the band alone with a navy title, as the resume's overview cards.
        Returns the box's edges as a dict."""
        inner = (x + 12, x + w - 12)  # the text's room inside the box
        body = []  # the gray lines, wrapped to the box
        for ln in lines:
            body += wrap(ln, sub, inner[1] - inner[0]) if wrap_lines else [ln]
        self.rect(x, y, w, h, fill="box", stroke=None, rx=2)  # the band, with the documents' nearly square corners
        if color:  # a card with a title bar
            bar = round(size * 1.75)  # the bar's height: the title with room above and below
            self.rect(x, y, w, bar, fill=BAR[color], stroke=None, rx=2)  # the bar, in the meaning colour
            tsize = size - 1  # the title a step smaller, so the bar stays slim
            self.text(inner[0], y + bar / 2 + tsize * 0.36, title, size=tsize, weight=600, fill="evtext" if color == "gold" else "bartext",
                      box=inner, mono=mono_title)  # white on the bar, navy on amber
            if body:  # the lines from the top of the band, as the resume's cards start under their head
                gap = sub * 1.4  # line to line
                by = y + bar + 12 + sub * 0.72  # the first line's baseline
                for i, ln in enumerate(body):
                    self.text(inner[0], by + i * gap, ln, size=sub, fill="muted", box=inner)
                if by - sub * 0.72 < y + bar + 4 or by + (len(body) - 1) * gap + sub * 0.25 > y + h - 3:  # the lines must fit under the bar
                    raise ValueError(f"box '{title}' is too short for its {len(body)} lines under the bar")
        else:  # the band alone, the title in navy
            self._stack(x, y, w, h, title, body, size, sub, mono_title, hl_title, inner)
        return {"x": x, "y": y, "w": w, "h": h, "l": x, "r": x + w, "t": y, "b": y + h, "cx": x + w / 2, "cy": y + h / 2}

    def doc(self, x, y, w, h, title, lines=(), size=14, sub=12, mono_title=False):
        """A finished document: a page with a thin rule and a folded corner, its name in navy and what it holds in gray."""
        fold = 12  # the folded corner's size
        self.path(f"M{x:.1f},{y:.1f} H{x + w - fold:.1f} L{x + w:.1f},{y + fold:.1f} V{y + h:.1f} H{x:.1f} Z", stroke="line", sw=1, fill="page")  # the page
        self.path(f"M{x + w - fold:.1f},{y:.1f} V{y + fold:.1f} H{x + w:.1f} Z", stroke="line", sw=1, fill="fold", extra='stroke-linejoin="round"')  # its fold
        inner = (x + 12, x + w - 14)  # the text's room on the page
        body = [ln2 for ln in lines for ln2 in wrap(ln, sub, inner[1] - inner[0])]  # what it holds, wrapped
        self._stack(x, y, w, h, title, body, size, sub, mono_title, False, inner)
        return {"x": x, "y": y, "w": w, "h": h, "l": x, "r": x + w, "t": y, "b": y + h, "cx": x + w / 2, "cy": y + h / 2}

    def section(self, x, y, title, right, size=19):
        """A chart's title as the resume sets its section titles: a short blue bar, the title in navy, a thin rule under it."""
        self.rect(x, y - size * 0.86, 4, size * 1.06, fill="secbar", stroke=None, rx=0)  # the bar beside the title
        self.text(x + 14, y, title, size=size, weight=700, fill="ink", box=(x + 14, right))  # the title
        self.path(f"M{x},{y + 12.5} H{right}", stroke="line", sw=1)  # the rule under it, the section's width

    def arrow(self, pts, color="arrow", label=None, label_xy=None, head=True, dash=None, label_anchor="middle", label_box=None):
        """A connector through points, with a head at the last point and a short label. The line stops where the head
        starts, so the tip is sharp."""
        color = "arrow" if color == "blue" else color  # staying on your PC is the default: only what leaves it, and a stop, are coloured
        (x1, y1), (x2, y2) = pts[-2], pts[-1]  # the last segment points the head
        ang = math.atan2(y2 - y1, x2 - x1)  # its direction
        L = 9 if head else 0  # head length
        end = (x2 - math.cos(ang) * (L - 1.5), y2 - math.sin(ang) * (L - 1.5)) if head else (x2, y2)  # the line ends under the head
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in list(pts[:-1]) + [end])  # the polyline
        self.path(d, stroke=color, sw=1.6, dash=dash, extra='stroke-linejoin="round"')
        if head:  # a filled triangle at the tip
            bx, by = x2 - math.cos(ang) * L, y2 - math.sin(ang) * L  # the middle of its base
            px, py = -math.sin(ang) * 4.5, math.cos(ang) * 4.5  # half its width, across the line
            self.path(f"M{x2:.1f},{y2:.1f} L{bx + px:.1f},{by + py:.1f} L{bx - px:.1f},{by - py:.1f} Z", stroke=None, fill=color)
        if label:  # a short label beside the line
            lines = label if isinstance(label, (list, tuple)) else [label]  # one or two lines
            lx, ly = label_xy  # the first line's baseline
            for i, ln in enumerate(lines):
                self.text(lx, ly + i * 13, ln, size=12, fill="muted", anchor=label_anchor, box=label_box)

    def legend(self, x, y, entries, right=None, end=None):
        """Swatches and words in one row: (colour name, words, kind). kind 'box' is a card's title bar, 'hl' a stroke of the
        highlighter, 'doc' a page, anything else a chart's dot, as the deck marks its series. With end, the row ends there.
        Returns the row's end."""
        sw = {"box": 30, "hl": 30, "doc": 22}  # a swatch and its gap, by kind; a dot takes 16
        if end is not None:  # right-aligned: start where the row's measured width ends at `end`
            x = end - sum(sw.get(k, 16) + width(words, 12) + 20 for _, words, k in entries) + 20
        for color, words, kind in entries:
            if kind == "box":  # a card's title bar
                self.rect(x, y, 22, 10, fill=BAR.get(color, color), stroke=None, rx=2)
            elif kind == "hl":  # a stroke of the highlighter
                self.hl(x, y + 1, 22, 9)
            elif kind == "doc":  # a small page
                self.path(f"M{x},{y - 2} H{x + 8} L{x + 12},{y + 2} V{y + 12} H{x} Z", stroke="line", sw=1, fill="page")
            else:  # a series of a chart
                self.path(f"M{x},{y + 4.5} a5,5 0 1,0 10,0 a5,5 0 1,0 -10,0", stroke=None, fill=color)
            gap = sw.get(kind, 16)  # where its words start
            w = self.text(x + gap, y + 9, words, size=12, fill="muted", box=(x + gap, right or end or self.w))
            x += gap + w + 20  # the next entry
        return x

    # writing the SVG
    def render(self, theme: str) -> str:
        """The SVG text in one theme."""
        T = THEMES[theme]  # colour names to colours
        col = lambda c: T.get(c, c) if c else "none"  # a colour name, a literal colour, or none
        p = self.pad  # the margin around the drawing, so strokes at the edge are not cut
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-p:g} {-p:g} {self.w + 2 * p:g} {self.h + 2 * p:g}" '
               f'width="{self.w + 2 * p:g}" height="{self.h + 2 * p:g}" font-family="{escape(SANS, quote=True)}" role="img" '
               f'aria-label="{escape(self.label, quote=True)}">']
        if self.bg:  # charts sit on a card of the page's own colour
            out.append(f'<rect x="{-p:g}" y="{-p:g}" width="{self.w + 2 * p:g}" height="{self.h + 2 * p:g}" rx="6" fill="{T["bg"]}"/>')
        for kind, a in self.items:
            if kind == "rect":
                dash = f' stroke-dasharray="{a["dash"]}"' if a["dash"] else ""
                stroke = f' stroke="{col(a["stroke"])}" stroke-width="{a["sw"]:g}"' if a["stroke"] else ""
                out.append(f'<rect x="{a["x"]:.1f}" y="{a["y"]:.1f}" width="{a["w"]:.1f}" height="{a["h"]:.1f}" rx="{a["rx"]:g}" '
                           f'fill="{col(a["fill"])}"{stroke}{dash}{(" " + a["extra"]) if a["extra"] else ""}/>')
            elif kind == "path":
                dash = f' stroke-dasharray="{a["dash"]}"' if a["dash"] else ""
                stroke = f' stroke="{col(a["stroke"])}" stroke-width="{a["sw"]:g}"' if a["stroke"] else ""
                out.append(f'<path d="{a["d"]}" fill="{col(a["fill"])}"{stroke}{dash}{(" " + a["extra"]) if a["extra"] else ""}/>')
            elif kind == "hl":  # the highlight: straight and nearly square, as on the printed resume
                out.append(f'<rect x="{a["x"]:.1f}" y="{a["y"]:.1f}" width="{a["w"]:.1f}" height="{a["h"]:.1f}" rx="1.5" fill="{col(a["fill"])}"/>')
            elif kind == "raw":  # SVG as written, its {colour} names filled in for this theme
                out.append(re.sub(r"\{(\w+)\}", lambda m: T.get(m.group(1), m.group(0)), a["s"]))
            elif kind == "text":
                fam = "" if a["family"] == SANS else f' font-family="{escape(a["family"], quote=True)}"'  # the root's family is the default
                weight = f' font-weight="{a["weight"]}"' if a["weight"] != 400 else ""
                anchor = f' text-anchor="{a["anchor"]}"' if a["anchor"] != "start" else ""
                box = f' data-box="{a["box"][0]:.1f},{a["box"][1]:.1f}"' if a["box"] else ""
                out.append(f'<text x="{a["x"]:.1f}" y="{a["y"]:.1f}" font-size="{a["size"]:g}"{weight}{fam} fill="{col(a["fill"])}"{anchor}{box}>'
                           f'{escape(a["s"])}</text>')
        out.append("</svg>")
        return "\n".join(out) + "\n"

    def overlaps(self) -> list:
        """Pairs of texts whose boxes cross, as measured while building."""
        bad = []
        for i, a in enumerate(self.texts):
            for b in self.texts[i + 1:]:
                if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1:  # a pixel of slack on each side
                    bad.append((a[4], b[4]))
        return bad


# the diagrams (no data)

LEGEND_PC = ("blue", "stays on your PC", "box")  # the legend entries the diagrams share: a title bar of each meaning
LEGEND_AI = ("orange", "sent to the AI backend", "box")
LEGEND_EV = ("gold", "the evidence", "box")
LEGEND_STOP = ("red", "stopped by a check", "box")


def diagram_pieces() -> Fig:
    """Your files and the panel; the Offerowl server; the one AI backend; the documents."""
    f = Fig(900, 392, "Your files and the panel in your browser go to the Offerowl server on your PC. The server reads the files, "
                      "keeps the facts their quotes back, plans each job, has the one AI backend you chose write from "
                      "that evidence, typesets and checks. It sends the AI backend the text of the files you add, the posting and the evidence of the part being written, and gives "
                      "back a resume, a portfolio deck, a cover letter and an interview kit, all on your PC")
    f.box(0, 18, 170, 92, "Your files", ["old resumes, portfolios, notes, reports"])
    f.box(0, 214, 170, 112, "Panel", ["in your browser: follow the run, change any sentence"])
    steps = ["reads your files", "keeps facts with quotes", "plans each job", "writes from evidence", "typesets", "checks every page"]
    f.box(250, 18, 200, 308, "Offerowl server", steps, color="blue", wrap_lines=False)  # the steps, one gray line each
    f.box(530, 120, 170, 112, "AI backend", ["the one you choose: Claude Code, Codex or a local model"], color="orange")
    outs = [("Resume", "Korean, English"), ("Portfolio deck", "16:9 slides"), ("Cover letter", "one page"), ("Interview kit", "questions, scripts")]
    for i, (t, s) in enumerate(outs):  # the four documents, stacked on the right
        f.doc(770, 18 + i * 78, 130, 66, t, [s], size=14, sub=12)  # a page each
    f.arrow([(170.5, 64), (249, 64)], color="blue", label="your files", label_xy=(210, 56), label_box=(173, 247))
    f.arrow([(170.5, 250), (249, 250)], color="blue", label="your edits", label_xy=(210, 242), label_box=(173, 247))
    f.arrow([(249.5, 292), (171.5, 292)], color="blue", label=["evidence of", "a sentence"], label_xy=(210, 309), label_box=(173, 247))
    f.arrow([(450.5, 152), (529, 152)], color="orange", label=["file text,", "evidence,", "the posting"], label_xy=(490, 113), label_box=(453, 527))
    f.arrow([(529.5, 200), (451.5, 200)], color="orange", label=["drafts", "citing it"], label_xy=(490, 217), label_box=(453, 527))
    f.path("M450.5,51 H745 V285", stroke="arrow", sw=1.6, extra='stroke-linejoin="round"')  # the trunk the four branches leave from
    for i in range(4):  # the trunk to each document
        y = 18 + i * 78 + 33
        f.arrow([(745, y), (769, y)], color="blue")
    f.text(598, 43, "checked documents", size=12, anchor="middle", box=(455, 740))
    f.legend(0, 368, [LEGEND_PC, LEGEND_AI], end=900)  # at the right, under the documents
    return f


def diagram_sentence() -> Fig:
    """How one sentence is made, from the evidence to the export, with the stopped branch."""
    f = Fig(900, 378, "How one sentence is made. A fact you confirmed carries the source's own words. The AI backend drafts "
                      "the sentence from that evidence and cites its ids. The fact check holds every number, name, tool and claim "
                      "against the evidence: a sentence that fails is stopped, rewritten once from the same evidence, and dropped "
                      "if it still fails. The style pack checks the wording. The page is typeset, the layout is checked, and then "
                      "it can be exported")
    f.box(0, 18, 180, 104, "Evidence", ["a fact you confirmed, with the source's own words"], color="gold", hl_title=True)
    f.box(240, 18, 180, 104, "Draft", ["the AI backend writes from the evidence and cites its ids"], color="orange")
    f.box(480, 18, 180, 104, "Fact check", ["numbers, names, tools and claim strength"])
    f.box(720, 18, 180, 104, "Style pack", ["banned words and patterns, lengths, highlights"])
    f.box(480, 162, 180, 64, "Stopped", ["one rewrite, else dropped"], color="red", size=14, sub=12)
    f.box(720, 270, 180, 92, "Render", ["DOCX and PDF from one layout"])
    f.box(480, 270, 180, 92, "Layout checks", ["page fill, line ends, overflow"])
    f.doc(240, 270, 180, 92, "Export", ["the PDF and DOCX you send"], size=15, sub=12.5)  # the document that goes out
    f.arrow([(180.5, 70), (239, 70)], color="orange", label="sent", label_xy=(210, 62), label_box=(183, 237))
    f.arrow([(420.5, 70), (479, 70)], color="arrow", label="draft", label_xy=(450, 62), label_box=(423, 477))
    f.arrow([(660.5, 70), (719, 70)], color="arrow", label="passes", label_xy=(690, 62), label_box=(663, 717))
    f.arrow([(810, 122.5), (810, 269)], color="arrow", label="passes", label_xy=(818, 200), label_anchor="start", label_box=(818, 900))
    f.arrow([(719.5, 316), (661, 316)], color="arrow")
    f.arrow([(479.5, 316), (421, 316)], color="arrow", label="passes", label_xy=(450, 308), label_box=(423, 477))
    f.arrow([(570, 122.5), (570, 161)], color="red", label="fails", label_xy=(578, 146), label_anchor="start", label_box=(578, 660))
    f.arrow([(479.5, 194), (330, 194), (330, 123)], color="red", label="rewrite", label_xy=(338, 186), label_anchor="start", label_box=(338, 476))
    f.legend(0, 282, [LEGEND_EV], right=200)  # the legend in the empty corner, one entry a line
    f.legend(0, 304, [LEGEND_AI], right=200)
    f.legend(0, 326, [LEGEND_STOP], right=200)
    return f


def diagram_interview() -> Fig:
    """From the posting, the resume and the portfolio to the question map, the scenes, the audits, the search view and
    practice."""
    f = Fig(900, 394, "The interview kit. The posting, the resume and the portfolio you sent, and your confirmed facts, give the "
                      "question map: questions for each posting line, resume line, portfolio page and term, plus behavioral, company "
                      "and opening questions. Each question gets a scene, a short dialogue in English with the Korean translation "
                      "under each line and speech marks, drafted by the AI backend from your evidence and checked. Audits rate how "
                      "well the scenes cover the posting and compare them with what you sent. The search view finds a scene by "
                      "keyword on your PC, practice mode asks the questions and gives feedback, and cue cards print the scenes")
    inputs = [("Posting", "each line a question"), ("Resume you sent", "each line a question"), ("Portfolio you sent", "each page a question"),
              ("Your facts", "the only evidence")]
    for i, (t, sub) in enumerate(inputs):  # four inputs down the left
        f.box(0, 8 + i * 88, 170, 72, t, [sub], size=14, sub=12, color="gold" if t == "Your facts" else None, hl_title=t == "Your facts")
    kinds = ["posting lines", "resume lines", "portfolio pages", "terms you used", "behavioral", "company", "opening logistics"]
    f.box(230, 8, 190, 336, "Question map", kinds, color="blue", wrap_lines=False)  # the kinds of question, one line each
    f.box(480, 8, 196, 160, "Scenes", ["English lines with the Korean translation under each, speech marks, one key phrase"], color="orange")
    f.box(480, 204, 196, 140, "Audits", ["posting coverage: strong, weak or none", "consistency with what you sent"])
    f.box(736, 8, 164, 100, "Search view", ["a scene by keyword, on your PC"], color="blue", size=14, sub=12)
    f.box(736, 126, 164, 100, "Practice", ["timer, your voice, feedback on your facts"], size=14, sub=12)
    f.doc(736, 244, 164, 100, "Cue cards", ["one scene per card, to print"], size=14, sub=12)  # printed pages
    for i in range(4):  # each input into the map
        y = 8 + i * 88 + 36
        f.arrow([(170.5, y), (229, y)], color="blue")
    f.arrow([(420.5, 88), (479, 88)], color="orange", label="draft", label_xy=(450, 80), label_box=(424, 476))
    f.arrow([(578, 168.5), (578, 203)], color="arrow", label="checked", label_xy=(586, 190), label_anchor="start", label_box=(586, 676))
    f.arrow([(420.5, 274), (479, 274)], color="arrow", label="gaps", label_xy=(450, 266), label_box=(424, 476))
    f.arrow([(676.5, 58), (735, 58)], color="blue")
    f.arrow([(676.5, 124), (706, 124), (706, 176), (735, 176)], color="arrow")
    f.arrow([(676.5, 150), (690, 150), (690, 294), (735, 294)], color="arrow")
    f.legend(0, 372, [LEGEND_PC, LEGEND_AI, LEGEND_EV], end=900)  # at the right
    return f


def diagram_ways() -> Fig:
    """The four ways to run Offerowl, with what runs where in each."""
    f = Fig(900, 452, "Four ways to run Offerowl. The app is one file that starts the panel and its server on your PC and typesets "
                      "with the browser you already have. The container runs the panel, the engine, the interview view and the typesetting tools "
                      "together, with a volume for your files. The Helm chart runs the same in one pod with a volume claim, reached by "
                      "a port-forward. The Python package gives the offerowl command and the panel, and typesets with Docker or with "
                      "the browser already on your PC")
    cols = [("The app", "apps/desktop", [("Panel and server", "the app's own Python"), ("Your browser", "opens the panel"),
                                                    ("AI backend", "Claude Code or Codex on this PC, or a local model"), ("Typesetting", "your own Chrome or Edge")]),
            ("Docker", "deploy/docker", [("One container", "panel, engine, interview view"), ("Typesetting", "LibreOffice and Chromium inside"),
                                        ("AI backend", "a local model server, or none"), ("Your files", "a volume")]),
            ("Kubernetes", "deploy/helm/offerowl", [("One pod", "the same image as Docker"), ("Port-forward", "the panel on this PC"),
                                                   ("AI backend", "a model server in the cluster, or none"), ("Your files", "a volume claim")]),
            ("Python package", "pyproject.toml", [("offerowl", "every command and the panel"), ("Typesetting", "Docker, or the PC's own browser"),
                                               ("AI backend", "Claude Code, Codex or a local model"), ("Your files", "the data folder")])]
    cw, gap = 210, 20  # column width and the space between columns
    for c, (title, code, parts) in enumerate(cols):
        x = c * (cw + gap)  # the column's left edge
        f.path(f"M{x},1 H{x + cw}", stroke="ink", sw=2)  # the column's rule, as the deck's focus columns
        f.text(x, 24, title, size=16, weight=700, fill="ink", box=(x, x + cw))
        f.text(x, 44, code, size=12.5, fill="muted", mono=True, box=(x, x + cw))
        for i, (t, s) in enumerate(parts):  # the parts of this way, top to bottom
            y = 62 + i * 92  # each part's top
            color = "orange" if t == "AI backend" else ("blue" if i == 0 else None)  # the AI backend is the one part that may leave the PC
            f.box(x + 26, y, cw - 26, 80, t, [s], size=14, sub=12.5, color=color, mono_title=(t == "offerowl"))
            f.arrow([(x + 6, y + 40), (x + 25, y + 40)], color="arrow")
        f.path(f"M{x + 6},54 V{62 + 3 * 92 + 40}", stroke="arrow", sw=1.6)  # the spine the parts hang from
    f.legend(0, 434, [("blue", "on your PC (or your server)", "box"), LEGEND_AI], end=900)  # at the right
    return f


def diagram_modules() -> Fig:
    """The code as it is laid out today, grouped by the part of the pipeline each file serves."""
    f = Fig(900, 608, "The modules. The desktop app starts the panel's server, which serves the page and Offerowl's one HTTP API; "
                      "the page only calls the API, and the agent's tools (apps/mcp) call it too. The API and the offerowl command call the engine in src: ingest reads files "
                      "into fact candidates; the writing modules call the one AI backend through llm.py; the renderers typeset the "
                      "resume, the deck and the cover letter; the checks hold every sentence and page to its evidence and layout; "
                      "the interview package builds the kit and the talk; decide answers typed questions. core/schema describes the files they share")
    top = [("apps/desktop", "the one-file app"), ("apps/panel", "the page, its server"), ("apps/api", "one HTTP API"), ("apps/mcp", "the agent's tools"), ("offerowl", "the command line")]
    for i, (t, sub) in enumerate(top):  # the programs, left to right as they call each other
        f.box(i * 182, 0, 172, 64, t, [sub], size=13.5, sub=12.5, mono_title=True)
    f.arrow([(172.5, 32), (181, 32)], color="arrow")  # the app starts the panel's server
    f.arrow([(354.5, 32), (363, 32)], color="arrow")  # the page calls the API
    f.arrow([(545.5, 32), (537, 32)], color="arrow")  # the agent's tools call the API too
    f.path("M450,64.5 V96 M814,64.5 V96 M108,96 H814", stroke="arrow", sw=1.6)  # the API and the command reach the engine on one line
    for x in (108, 336, 564, 792):  # into each group of the engine
        f.arrow([(x, 96), (x, 119)], color="arrow")
    f.text(632, 90, "call the engine in src/", size=12, anchor="middle", box=(470, 800))
    groups = [("Reading files", 0, ["ingest.py", "review.py", "probe_extract.py", "ocr_selfcheck.py"],
               ["files to fact candidates", "merge the facts you keep", "deck measurements", "scanned pages"]),
              ("Writing", 228, ["llm.py", "write_resume.py", "cover.py", "draft.py"],
               ["the one door to the AI", "resume parts", "cover letters", "fit, translation, figures"]),
              ("Typesetting", 456, ["layout.js", "resume_form.js", "deck_slides.js", "render_html/"],
               ["resume and letter DOCX", "the resume's parts", "the 16:9 deck", "typeset with your browser"]),
              ("Checking", 684, ["factcheck.py", "check_documents.py", "check_render.py", "style/"],
               ["numbers, names, claims", "resume and deck checks", "layout of the pages", "style packs"])]
    for name, x, files, notes in groups:  # four groups of the engine, side by side
        f.path(f"M{x},120 H{x + 216}", stroke="ink", sw=2)  # the group's rule, as the deck's focus columns
        f.text(x, 142, name, size=14, weight=700, fill="ink", box=(x, x + 216))  # its name, in words
        for i, (fn, note) in enumerate(zip(files, notes)):
            color = "orange" if fn == "llm.py" else "red" if fn == "factcheck.py" else None  # the door to the AI and the fact rules
            f.box(x, 154 + i * 72, 216, 62, fn, [note], size=13.5, sub=12.5, color=color, mono_title=True)
    f.path("M0,478 H544", stroke="ink", sw=2)  # the interview kit's rule
    f.text(0, 500, "Interview kit, src/interview/", size=14, weight=700, fill="ink", box=(0, 544))
    for i, (t, sub) in enumerate([("plan.py", "the map"), ("draft.py", "scenes"), ("audit.py", "audits"), ("server.py", "the pages"), ("talk.py", "the talk")]):
        f.box(i * 111, 512, 100, 62, t, [sub], size=12.5, sub=12, mono_title=True)
    f.path("M568,478 H900", stroke="ink", sw=2)  # the shared parts' rule, level with the kit's
    f.text(568, 500, "Decisions and shapes", size=14, weight=700, fill="ink", box=(568, 900))
    f.box(568, 512, 160, 62, "decide/", ["rules, the agent, small models"], size=13.5, sub=12.5, mono_title=True)
    f.box(740, 512, 160, 62, "core/schema", ["profile, job and documents"], size=13.5, sub=12.5, mono_title=True)
    f.legend(0, 596, [LEGEND_AI, LEGEND_STOP], end=900)  # llm.py sends to the AI backend; factcheck.py holds the rules that stop a text
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
WIDE = "text { font-family: 'DejaVu Sans', sans-serif !important; }"  # a wide fallback font, as a stress test


def check(paths: list, out_dir: pathlib.Path) -> int:
    """Render every SVG in Chrome to a PNG at twice the size, on its theme's page colour, and count the texts that leave
    their room, overlap another text or leave the picture: with the fonts this PC has, and again with a wide fallback
    font. The first count must be zero; the second is reported."""
    from playwright.sync_api import sync_playwright  # pip install playwright && python3 -m playwright install chromium
    out_dir.mkdir(parents=True, exist_ok=True)  # the previews go here
    problems, stress = 0, 0  # with this PC's fonts; with the wide font
    with sync_playwright() as pw:
        browser = pw.chromium.launch()  # headless
        page = browser.new_page(device_scale_factor=2)  # sharp previews
        for path in paths:
            theme = "dark" if path.stem.endswith("-dark") else "light"  # the page colour behind the picture
            svg = path.read_text(encoding="utf-8")
            page.set_content(f'<html><body style="margin:0;padding:16px;background:{THEMES[theme]["bg"]}">{svg}</body></html>')
            el = page.locator("svg")  # the picture
            el.screenshot(path=str(out_dir / f"{path.stem}.png"))  # the preview to look at
            got = page.evaluate(MEASURE, "")  # measured as rendered here
            n = len(got["overflow"]) + len(got["overlap"]) + len(got["outside"])
            problems += n
            page.set_content(f'<html><body style="margin:0;padding:16px;background:{THEMES[theme]["bg"]}">{svg}</body></html>')
            wide = page.evaluate(MEASURE, WIDE)  # measured again with the wide font
            m = len(wide["overflow"]) + len(wide["overlap"]) + len(wide["outside"])
            stress += m
            print(f"{path.name:32} texts {got['texts']:3}  overflow {len(got['overflow'])}  overlap {len(got['overlap'])}  "
                  f"outside {len(got['outside'])}   wide font: {m}")
            for k in ("overflow", "overlap", "outside"):  # the details of anything found
                for x in got[k][:4]:
                    print(f"    {k}: {x}")
        browser.close()
    print(f"check: {len(paths)} pictures, {problems} problems with this PC's fonts, {stress} with a wide fallback font; previews in {out_dir}")
    return problems


# the pictures with numbers

def load(name: str) -> dict:
    """One data file of tools/measure.py; a missing file stops with the command that makes it."""
    p = DATA / f"{name}.json"
    if not p.is_file():
        raise SystemExit(f"{p.relative_to(ROOT)} is missing: run `python3 tools/measure.py` first")
    return json.loads(p.read_text(encoding="utf-8"))


def bar(f: Fig, x, y, w, h, color, left_round=False):
    """A bar from a baseline at x, with a 4 px rounded data end on the right (square at the baseline)."""
    if w <= 0:
        return
    r = min(4, w / 2, h / 2)  # the rounding never exceeds the bar
    if left_round:  # a segmented bar's first part has no baseline
        f.path(f"M{x + r:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} "
               f"H{x + r:.1f} Q{x:.1f},{y + h:.1f} {x:.1f},{y + h - r:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} Z", stroke=None, fill=color)
        return
    f.path(f"M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z",
           stroke=None, fill=color)


def chart_factcheck() -> Fig:
    """Per task: texts drafted, passed as written, and stopped (rewritten or dropped); and why the stopped ones were stopped."""
    D = load("drafts")
    T = {t["task"]: t for t in D["tasks"]}  # the tasks by name
    f = Fig(860, 404, "", pad=0, bg=True)
    f.section(24, 40, "The fact check stops what the evidence does not hold", 836)  # the resume's section title
    dates = sorted({t.get('recorded') for t in D['tapes'].values() if t.get('recorded')})  # the tapes may have been recorded on different days
    when = dates[0] if len(dates) == 1 else ', '.join(dates[:-1]) + ' and ' + dates[-1]  # each day once
    sub = (f"Drafts for the fictional example, written by the AI backend on {when} and replayed by tools/measure.py. "
           f"A text is a sentence, a title or a card line; a scene counts once.")
    for i, ln in enumerate(wrap(sub, 13.5, 812)):
        f.text(24, 74 + i * 19, ln, size=13.5, fill="muted", box=(24, 836))
    rows = [("resume", "Resume"), ("cover", "Cover letter"), ("interview", "Interview")]
    x0, bw = 24, 400  # the bars' left edge and full width
    f.text(x0, 132, "What happened to each drafted text", size=13, weight=600, fill="ink", box=(x0, x0 + bw))
    for i, (key, name) in enumerate(rows):
        t = T[key]  # this task's counts
        y = 152 + i * 72  # the row's top
        unit = "scenes" if t["unit"] == "scenes" else "sentences" if key == "cover" else "texts"  # what was counted
        f.text(x0, y + 12, f"{name}, {t['drafted']} {unit}", size=12.5, weight=600, fill="ink", box=(x0, x0 + bw))
        gone = t.get("dropped", 0)  # still failing after the rewrite
        fixed = t["stopped"] - gone  # rewritten from the same evidence and passed
        if t["kept"] + t["stopped"] != t["drafted"]:  # a bar longer than its row is a wrong number, not a wrong drawing
            raise SystemExit(f"chart-factcheck: {key}: {t['kept']} kept + {t['stopped']} stopped is not {t['drafted']} drafted")
        parts = [p for p in [(t["kept"], "pass"), (fixed, "red"), (gone, "redsoft")] if p[0] > 0]  # parts at zero draw nothing
        x = x0
        for j, (n, color) in enumerate(parts):
            w = bw * n / max(1, t["drafted"]) - (2 if j < len(parts) - 1 else 0)  # a 2 px gap between parts
            bar(f, x, y + 21, w, 16, color, left_round=True)
            x += w + 2
        words = f"{t['kept']} passed as written, {fixed} stopped and rewritten, {gone} dropped" if t["stopped"] else f"{t['kept']} passed as written, none stopped"
        f.text(x0, y + 54, words, size=12, fill="muted", box=(x0, x0 + bw))
    X, XR = 488, 836  # the second panel's edges
    f.text(X, 132, f"Why the {D['stopped']} were stopped", size=13, weight=600, fill="ink", box=(X, XR))
    reasons = [("name", "a name the cited evidence lacks"), ("number", "a number the cited evidence lacks"),
               ("tool", "a tool the profile does not show"), ("claim", "a claim stronger than the evidence"), ("style", "wording the style pack bans")]
    counts = {k: sum(t["reasons"].get(k, 0) for t in D["tasks"]) for k, _ in reasons}  # over every task
    top = max(1, max(counts.values()))  # the longest bar
    for i, (k, words) in enumerate(reasons):
        y = 152 + i * 44
        f.text(X, y + 12, words, size=12.5, fill="ink", box=(X, XR - 40))
        f.text(XR, y + 12, str(counts[k]), size=12.5, weight=600, fill="ink", anchor="end", box=(XR - 40, XR))
        bar(f, X, y + 20, (XR - X) * counts[k] / top, 10, "red", left_round=True)  # nothing at zero
    f.legend(24, 378, [("pass", "passed as written", "dot"), ("red", "stopped, then rewritten from the same evidence", "dot"),
                       ("redsoft", "stopped and dropped", "dot")], right=836)
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
    written = []
    for name in names:
        fig = PICTURES[name]()  # the drawing, checked for text that leaves its box while it was built
        bad = fig.overlaps()  # texts on top of each other
        if bad:
            raise SystemExit(f"{name}: texts overlap: {bad[:3]}")
        for theme in THEMES:  # one copy per theme
            path = HERE / f"{name}-{theme}.svg"
            path.write_text(fig.render(theme), encoding="utf-8")
            written.append(path)
    sync_alts({name: PICTURES[name]().label for name in names})  # the docs say in words what the pictures now show
    if a.check:  # render and measure in a real browser
        problems = check(written, pathlib.Path(a.check))
        if problems:
            print(f"check: {problems} problems")
            return 1
    print(f"build: {len(written)} SVG files written to {HERE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
