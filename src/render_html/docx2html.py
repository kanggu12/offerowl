#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DOCX to HTML for the browser renderer.

src/layout.js writes every resume and cover letter as DOCX, and the DOCX stays the export format. In the container
LibreOffice turns that DOCX into the PDF. This module turns the same DOCX into one HTML page instead, and
src/render_html/page.js lays it out in the browser the way LibreOffice does: lines, tab stops, borders, tables, page
breaks and the footer. So the design has one source (layout.js) and two outputs that cannot drift apart.

It reads only the part of OOXML that layout.js writes: paragraphs, runs, tab stops, borders, shading, tables, inline and
floating pictures, hyperlinks, the page size and margins, and one footer with page fields.

  python3 src/render_html/docx2html.py <in.docx> <out.html>
"""
import base64  # pictures go into the page as data URIs, so the page needs no files beside it
import html  # escape text and attribute values
import importlib.util  # fonts.py under a private name
import json  # the page settings that page.js reads
import pathlib  # paths
import re  # small text rules (autospace, field names)
import sys  # command line
import zipfile  # a DOCX is a zip file
import xml.etree.ElementTree as ET  # the XML parts

HERE = pathlib.Path(__file__).resolve().parent  # src/render_html
ROOT = HERE.parent.parent  # the repository root


def _fonts():
    """fonts.py of this folder under a private name, so a fonts module elsewhere on the path cannot stand in"""
    key = "offerowl_fonts"
    if key not in sys.modules:  # load it once, shared with render.py
        spec = importlib.util.spec_from_file_location(key, HERE / "fonts.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[key]


FONTS = _fonts()  # font files and their metrics

# XML namespaces of the parts layout.js writes.
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
W = "{%s}" % NS["w"]  # prefix of WordprocessingML names in ElementTree form
R = "{%s}" % NS["r"]  # prefix of relationship attributes


def q(tag: str) -> str:
    """'w:p' -> the ElementTree name of that element"""
    pre, name = tag.split(":")  # namespace prefix and local name
    return "{%s}%s" % (NS[pre], name)  # Clark notation


def val(el, attr: str = "val", default=None):
    """The w:<attr> attribute of an element, or the default when the element or the attribute is missing"""
    if el is None:  # no element: the property is not set
        return default
    return el.get(W + attr, default)  # attributes are in the w namespace


def on(el) -> bool | None:
    """A toggle property (w:b, w:i, w:keepNext...): None when absent, else its value ('false' and '0' mean off)"""
    if el is None:  # absent: the caller keeps the inherited value
        return None
    return val(el) not in ("false", "0", "off")  # no w:val means on


UNITS = {"pt": 1.0, "in": 72.0, "cm": 72 / 2.54, "mm": 72 / 25.4, "pc": 12.0, "pi": 12.0}  # OOXML universal measures


def measure(v, per_point: float) -> float:
    """A length in points: '1pt', '0.5in' and the like, or a plain number in the attribute's own unit
    (per_point of them make one point: 20 for twips, 2 for half points)"""
    s = str(v).strip()
    for unit, k in UNITS.items():  # a universal measure names its unit
        if s.endswith(unit):
            return float(s[:-len(unit)]) * k
    return float(s) / per_point  # a plain number


def pt(twips) -> float:
    """Twips (1/20 pt), or a universal measure, to points"""
    return measure(twips, 20.0)


# The page is laid out at SCALE times its size and drawn back at 1/SCALE when printed (page.js). The browser snaps
# baselines and line boxes to whole CSS pixels, keeps glyph advances in 1/64 pixels and floors border widths to whole
# pixels. At 24 times the size a pixel is 1/32pt, and every OOXML border width (a multiple of 1/8pt) is a whole number
# of pixels. Measured on the fictional examples (strict pixel share, worst page): 1x gave baselines in 0.75pt steps;
# 6x 3.5%, 12x 1.6%, 24x 1.2% on the full Korean example, with the page-size crop of tests/render/compare.py.
SCALE = 24


def fmt(x: float) -> str:
    """A CSS length: points times SCALE, with at most three decimals"""
    return ("%.3f" % (x * SCALE)).rstrip("0").rstrip(".") + "pt"


def num(x: float) -> str:
    """A length for page.js (a data attribute), in the same scaled points as fmt()"""
    return "%g" % round(x * SCALE, 4)


def color(c: str | None, fallback: str = "#000") -> str:
    """An OOXML colour (RRGGBB or auto) as CSS"""
    if not c or c == "auto":  # auto means the default text colour
        return fallback
    return "#" + c  # six hex digits


# ---------------------------------------------------------------- run properties

# The advance of the square glyph (U+25A0) in Pretendard, in em, regular and bold (src/blind_metrics.json "box"): the blind
# edition's bars are that glyph, widened by a horizontal scale (w:w, src/save.js), the only runs Offerowl writes with one
BAR_EM = {k: v["box"] for k, v in json.loads((ROOT / "src" / "blind_metrics.json").read_text(encoding="utf-8")).items() if "box" in v}


class RunProps:
    """The character properties that layout.js uses, resolved from the document defaults and the run's own w:rPr"""
    __slots__ = ("font", "size", "bold", "italic", "color", "underline", "fill", "spacing", "raise_", "east", "scale")

    def __init__(self):
        self.font = "Pretendard"  # w:rFonts ascii (and hAnsi)
        self.east = "Pretendard"  # w:rFonts eastAsia: the font for Hangul and other East Asian characters
        self.size = 10.0  # w:sz in points (OOXML default 10pt)
        self.bold = False  # w:b
        self.italic = False  # w:i
        self.color = None  # w:color, None = auto
        self.underline = False  # w:u
        self.fill = None  # w:shd fill behind the characters
        self.spacing = 0.0  # w:spacing (character spacing) in points
        self.raise_ = 0.0  # w:position in points (positive raises)
        self.scale = 100.0  # w:w, the horizontal scale in percent

    def copy(self) -> "RunProps":
        """A copy for one run, so the run's own properties never change the defaults"""
        c = RunProps()  # a new object
        for k in self.__slots__:  # copy every field
            setattr(c, k, getattr(self, k))
        return c

    def apply(self, rpr) -> "RunProps":
        """Apply one w:rPr element on top of these properties (the element may be None)"""
        if rpr is None:  # nothing to apply
            return self
        f = rpr.find(q("w:rFonts"))  # fonts by script
        if f is not None:
            self.font = f.get(W + "ascii") or f.get(W + "hAnsi") or self.font  # Latin text
            self.east = f.get(W + "eastAsia") or self.east  # Hangul and other East Asian text
        s = rpr.find(q("w:sz"))  # size in half points
        if s is not None:
            self.size = measure(val(s), 2.0)
        b = on(rpr.find(q("w:b")))  # bold
        if b is not None:
            self.bold = b
        i = on(rpr.find(q("w:i")))  # italics
        if i is not None:
            self.italic = i
        c = rpr.find(q("w:color"))  # colour
        if c is not None:
            self.color = val(c)
        u = rpr.find(q("w:u"))  # underline: present without w:val, or with a value other than none
        if u is not None:
            self.underline = val(u, default="single") != "none"
        sh = rpr.find(q("w:shd"))  # character shading
        if sh is not None:
            fill = sh.get(W + "fill")  # the background colour
            self.fill = fill if fill and fill != "auto" else None
        sp = rpr.find(q("w:spacing"))  # character spacing in twips
        if sp is not None:
            self.spacing = pt(val(sp, default="0"))
        pos = rpr.find(q("w:position"))  # raise in half points
        if pos is not None:
            self.raise_ = measure(val(pos, default="0"), 2.0)
        w = rpr.find(q("w:w"))  # horizontal scale in percent
        if w is not None:
            try:
                self.scale = float(val(w, default="100"))
            except ValueError:  # an unreadable value keeps the glyphs as drawn
                self.scale = 100.0
        return self


# ---------------------------------------------------------------- the converter

# Hangul (syllables, jamo, compatibility jamo) and CJK: LibreOffice's Asian script for spacing purposes.
ASIAN = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣぀-ヿ一-鿿]")
# Latin letters and digits: LibreOffice's Latin script for spacing purposes.
LATIN = re.compile(r"[A-Za-z0-9]")


class Converter:
    """One DOCX to one HTML page"""

    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path)  # the DOCX
        self.zip = zipfile.ZipFile(self.path)  # its parts
        self.doc = ET.fromstring(self.zip.read("word/document.xml"))  # the body
        self.rels = self._rels("word/_rels/document.xml.rels")  # pictures and links of the body
        self.defaults = self._defaults()  # document default run properties
        self.families = set()  # every font family the runs ask for, for the @font-face rules
        self.ids = 0  # running number of blocks, so page.js and the tests can name them
        self.links = {}  # id() of a run inside a hyperlink -> the link target (ElementTree elements take no new attributes)

    # ---------- package parts

    def _rels(self, name: str) -> dict:
        """Relationship id -> (type, target) of one part"""
        try:
            root = ET.fromstring(self.zip.read(name))  # the .rels part
        except KeyError:  # a part without relationships
            return {}
        return {r.get("Id"): (r.get("Type", ""), r.get("Target", ""), r.get("TargetMode", "")) for r in root}

    def _defaults(self) -> RunProps:
        """The document default run properties from styles.xml (docDefaults/rPrDefault)"""
        rp = RunProps()  # OOXML's own defaults
        try:
            st = ET.fromstring(self.zip.read("word/styles.xml"))  # the styles part
        except KeyError:  # no styles: the OOXML defaults hold
            return rp
        d = st.find("w:docDefaults/w:rPrDefault/w:rPr", NS)  # the default character properties
        return rp.apply(d)

    def media(self, rid: str, rels: dict | None = None) -> str:
        """A picture of the package as a data URI"""
        typ, target, _ = (rels or self.rels)[rid]  # the relationship names the media file
        name = "word/" + target if not target.startswith("/") else target[1:]  # targets are relative to word/
        data = self.zip.read(name)  # the picture bytes
        mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg" if data[:2] == b"\xff\xd8" else "image/gif"
        return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode())  # inline, so the page is one file

    # ---------- section (page size and margins)

    def section(self) -> dict:
        """Page size, margins and the footer distance of the (only) section, in points"""
        s = self.doc.find("w:body/w:sectPr", NS)  # the last section's properties
        sz, mar = s.find("w:pgSz", NS), s.find("w:pgMar", NS)  # size and margins
        return {
            "w": pt(val(sz, "w", "11906")), "h": pt(val(sz, "h", "16838")),  # A4 when missing
            "top": pt(val(mar, "top", "1440")), "bottom": pt(val(mar, "bottom", "1440")),
            "left": pt(val(mar, "left", "1440")), "right": pt(val(mar, "right", "1440")),
            "footer": pt(val(mar, "footer", "708")), "header": pt(val(mar, "header", "708")),
        }

    def footer_xml(self):
        """The default footer part of the section, or None"""
        s = self.doc.find("w:body/w:sectPr", NS)  # section properties
        ref = s.find("w:footerReference", NS) if s is not None else None  # the footer it uses
        if ref is None:  # no footer
            return None, {}
        _, target, _ = self.rels[ref.get(R + "id")]  # footerN.xml
        part = "word/" + target  # its place in the package
        rels = self._rels("word/_rels/" + target + ".rels")  # its own pictures and links
        return ET.fromstring(self.zip.read(part)), rels

    # ---------- blocks

    def blocks(self, parent, rels=None, in_cell=False) -> list[str]:
        """HTML of the paragraphs and tables under one parent (the body, a table cell or the footer)"""
        kids = [k for k in parent if k.tag in (q("w:p"), q("w:tbl"))]  # block-level children in order
        # Word needs a paragraph after a table at the end of a cell; LibreOffice drops that empty paragraph when it reads
        # the DOCX (measured: the career table's logo rows were as high as if the 1pt paragraph were not there).
        if in_cell and len(kids) >= 2 and kids[-2].tag == q("w:tbl") and kids[-1].tag == q("w:p") and not self._has_content(kids[-1]):
            kids = kids[:-1]
        out = []  # HTML pieces
        groups = self._border_groups(kids)  # consecutive paragraphs with the same borders share one border box
        for i, k in enumerate(kids):  # each block in order
            if k.tag == q("w:p"):
                nxt = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].tag == q("w:p") else None  # the paragraph after it
                out.append(self.paragraph(k, rels, groups[i], in_cell, self._before(nxt)))
            else:
                out.append(self.table(k, rels))
        return out

    @staticmethod
    def _has_content(p) -> bool:
        """True when a paragraph holds text, a tab, a break or a picture"""
        return any(el.tag in (q("w:t"), q("w:tab"), q("w:br"), q("w:drawing")) and (el.tag != q("w:t") or el.text) for el in p.iter())

    @staticmethod
    def _before(p) -> float:
        """The spacing before a paragraph in points (0 for none)"""
        if p is None:
            return 0.0
        sp = p.find("w:pPr/w:spacing", NS)
        return pt(val(sp, "before", "0"))

    def _border_groups(self, kids) -> list:
        """For each block, ('first'|'mid'|'last'|None): its place in a run of paragraphs with identical borders.
        Word and LibreOffice draw one border around such a run (the bars of the about-me steps and the quote box stay
        unbroken across the paragraph spacing), and only the first gets the top border, only the last the bottom one"""
        keys = []  # the border key of each block (None for tables and paragraphs without borders)
        for k in kids:
            b = k.find("w:pPr/w:pBdr", NS) if k.tag == q("w:p") else None  # the paragraph's borders
            keys.append(ET.tostring(b) if b is not None and len(b) else None)  # identical XML means identical borders
        out = []  # one place per block
        for i, key in enumerate(keys):
            if key is None:  # not bordered
                out.append(None)
                continue
            prev_same = i > 0 and keys[i - 1] == key  # the block before has the same borders
            next_same = i + 1 < len(keys) and keys[i + 1] == key  # the block after has the same borders
            out.append(None if not (prev_same or next_same) else "mid" if prev_same and next_same else "last" if prev_same else "first")
        return out

    # ---------- paragraphs

    def paragraph(self, p, rels=None, group=None, in_cell=False, next_before=0.0) -> str:
        """One w:p as a block"""
        self.ids += 1  # a running number for debugging and tests
        ppr = p.find("w:pPr", NS)  # paragraph properties
        mark = self.defaults.copy().apply(ppr.find("w:rPr", NS) if ppr is not None else None)  # the paragraph mark's font
        style, data = [], {"id": str(self.ids)}  # CSS declarations and data attributes for page.js
        sp = ppr.find("w:spacing", NS) if ppr is not None else None  # spacing before, after and between lines
        before, after = pt(val(sp, "before", "0")), pt(val(sp, "after", "0"))  # paragraph spacing
        line, rule = val(sp, "line"), val(sp, "lineRule")  # line spacing and its rule (None when the DOCX leaves it out)
        jc = val(ppr.find("w:jc", NS) if ppr is not None else None, default="left")  # alignment
        ind = ppr.find("w:ind", NS) if ppr is not None else None  # indents in twips
        left = pt(val(ind, "left", val(ind, "start", "0")))  # left indent
        right = pt(val(ind, "right", val(ind, "end", "0")))  # right indent
        hanging, first = pt(val(ind, "hanging", "0")), pt(val(ind, "firstLine", "0"))  # first line offset
        shd = ppr.find("w:shd", NS) if ppr is not None else None  # paragraph shading
        fill = shd.get(W + "fill") if shd is not None else None  # its colour
        for flag, name in (("keepNext", "kn"), ("keepLines", "kl"), ("pageBreakBefore", "pb"), ("widowControl", "wc")):
            if ppr is not None and on(ppr.find("w:" + flag, NS)):  # LibreOffice reads these when it breaks pages
                data[name] = "1"
        outline = ppr.find("w:outlineLvl", NS) if ppr is not None else None  # a heading for the PDF bookmarks
        # Tab stops: page.js places the text after each tab. Positions are from the column's left edge, as in Word
        # (LibreOffice imports DOCX with tabs relative to the margin, not to the indent).
        tabs = []  # [kind, position in points]
        for t in (ppr.findall("w:tabs/w:tab", NS) if ppr is not None else []):
            kind = val(t, default="left")  # left, right, center, clear...
            if kind != "clear":  # a cleared stop is not a stop
                tabs.append([{"start": "left", "end": "right"}.get(kind, kind), round(pt(val(t, "pos", "0")) * SCALE, 4)])
        if tabs:
            data["tabs"] = json.dumps(sorted(tabs, key=lambda x: x[1]))  # in order of position
        data["ind"] = num(left)  # the left indent: a hanging indent is also an implicit tab stop
        # Borders. Word places a left or right border outside the indent: the text stays at the indent and the border sits
        # `space` points before it. Measured in LibreOffice's PDF: the bar of a section title ends 6pt left of its text.
        bdr = ppr.find("w:pBdr", NS) if ppr is not None else None
        sides = {}
        for side in ("top", "left", "bottom", "right"):
            e = bdr.find("w:" + side, NS) if bdr is not None else None  # one border
            if e is not None and val(e) not in (None, "none", "nil"):
                sides[side] = (float(val(e, "sz", "4")) / 8.0, float(val(e, "space", "0")), color(val(e, "color"), "#000"))
        if group in ("mid", "last"):  # inside a run of paragraphs with the same borders: no top border here
            sides.pop("top", None)
        if group in ("first", "mid"):  # ... and no bottom border before the next one
            sides.pop("bottom", None)
        ml, mr = left, right  # the box edges before borders
        pl = pr = pt_ = pb = 0.0  # padding between border and text
        for side, (w_, space, c) in sides.items():
            style.append("border-%s:%s solid %s" % (side, fmt(w_), c))  # the line itself
            if side == "left":
                ml, pl = left - space - w_, space  # the border goes out into the indent, the text stays put
            elif side == "right":
                mr, pr = right - space - w_, space
            elif side == "top":
                pt_ = space  # distance from the border to the text below it
            else:
                pb = space  # distance from the text to the border below it
        # In a run of bordered paragraphs, the spacing between them sits inside the shared border box, so the bar is not
        # broken by the gap. Spacing is then padding, not margin. LibreOffice keeps the larger of the two spacings at a
        # joint (as it does between any two paragraphs), so the joint gets that and the next paragraph none.
        if group in ("first", "mid"):
            pb, after_in = pb + max(after, next_before), True  # the joint's spacing goes inside the box, below this one
        else:
            after_in = False
        if group in ("mid", "last"):
            before_in = True  # the paragraph above already holds the joint's spacing
        else:
            before_in = False
        style.append("margin:%s %s %s %s" % (fmt(0 if before_in else before), fmt(mr), fmt(0 if after_in else after), fmt(ml)))
        style.append("padding:%s %s %s %s" % (fmt(pt_), fmt(pr), fmt(pb), fmt(pl)))
        data["sb"], data["sa"] = num(0 if before_in else before), num(0 if after_in else after)  # page.js drops or keeps these at page edges
        if fill and fill != "auto":
            style.append("background:#" + fill)  # the band colour
        # First line: a hanging indent pulls the first line out by `hanging`, a first-line indent pushes it in.
        if hanging or first:
            style.append("text-indent:" + fmt(first - hanging))
        style.append("text-align:" + {"both": "justify", "distribute": "justify", "center": "center", "right": "right", "end": "right"}.get(jc, "left"))
        # Lines. page.js needs the rule and the value; the CSS below gives the first guess that it then corrects.
        runs, maxsize, _ = self.runs(p, rels, mark)  # the inline HTML and the largest font size
        # LibreOffice 7.4 reads a w:line without a w:lineRule as an exact height in twips, not as 240ths of a line: in a
        # test document line="264" gave lines 13.2pt apart at 8, 9 and 12pt, with the baseline at 80% of the line. The
        # docx package never writes the rule, so every w:line of layout.js is an exact height, and the layouts
        # were tuned on that reading. It is kept here so the two renderers agree.
        if line and rule in (None, "exact"):  # a fixed line height
            data["lh"], data["lr"] = num(pt(line)), "exact"
        elif line and rule == "atLeast":  # a minimum line height
            data["lh"], data["lr"] = num(pt(line)), "atLeast"
        elif line and rule == "auto":  # an explicit proportional rule, in 240ths of the font's line
            data["lh"], data["lr"] = "%g" % (float(line) / 240.0), "auto"
        else:  # single spacing: each line as high as its tallest letters
            data["lh"], data["lr"] = "1", "auto"
        data["mx"] = num(maxsize or mark.size)  # largest font size of the paragraph
        if not runs.strip() and data["lr"] != "exact":  # an empty paragraph is one line of its paragraph mark's font
            runs = self.span("\u200b", mark)  # a zero-width character carries that font (an exact line needs none)
        tag = "div"
        attrs = " ".join('data-%s="%s"' % (k, html.escape(v, quote=True)) for k, v in data.items())  # data attributes
        if outline is not None and val(outline) == "0" and not in_cell:  # a level-1 heading: an <h1> becomes a PDF bookmark
            tag = "h1"
        return '<%s class="p" %s style="%s">%s</%s>' % (tag, attrs, ";".join(style), runs, tag)

    # ---------- runs

    def runs(self, p, rels, mark) -> tuple:
        """The inline HTML of a paragraph, its largest font size and its families"""
        out, maxsize, fams = [], 0.0, set()  # pieces, size, families
        self._prev = ""  # the last character written, for the Asian and Latin spacing at run edges
        fld = None  # inside a field: its instruction, until the field ends
        skip = False  # between 'separate' and 'end' of a field: the cached result, which page.js replaces
        for el in p.iter():  # every run and hyperlink in document order
            if el.tag == q("w:r"):
                rp = self.defaults.copy().apply(el.find("w:rPr", NS))  # the run's properties
                link = self.links.get(id(el))  # set below for runs inside a hyperlink
                for c in el:  # the run's content in order
                    if c.tag == q("w:fldChar"):  # a field boundary
                        kind = val(c, "fldCharType")
                        if kind == "begin":
                            fld, skip = "", False  # collect the instruction
                        elif kind == "separate":
                            skip = True  # what follows is the cached result
                            out.append(self.field(fld or "", rp))  # page.js fills in the live value
                            fld = None
                        elif kind == "end":
                            if fld is not None:  # a field without a separate part
                                out.append(self.field(fld, rp))
                            fld, skip = None, False
                        continue
                    if c.tag == q("w:instrText"):  # the field instruction (PAGE, NUMPAGES)
                        if fld is not None:
                            fld += c.text or ""
                        continue
                    if skip:  # the cached field result is not shown
                        continue
                    if c.tag == q("w:t"):  # text
                        out.append(self.text(c.text or "", rp, link))
                        maxsize = max(maxsize, rp.size)
                        fams.add(rp.font)
                    elif c.tag == q("w:tab"):  # a tab: page.js gives it its width
                        out.append('<span class="tab" style="font-size:%s"></span>' % fmt(rp.size))
                        self._prev = " "
                    elif c.tag == q("w:br"):  # a line break or a page break
                        if val(c, "type") == "page":
                            out.append('<span class="pgbr"></span>')
                        else:
                            out.append("<br>")
                        self._prev = " "
                    elif c.tag == q("w:drawing"):  # a picture
                        out.append(self.drawing(c, rels))
                        h = self._drawing_inline_h(c)  # an inline picture's height counts like a big letter
                        if h:
                            maxsize = max(maxsize, h / 1.19)
            elif el.tag == q("w:hyperlink"):  # mark the runs of a link so their text becomes an <a>
                rid = el.get(R + "id")  # the link target's relationship
                target = (rels or self.rels).get(rid, ("", "", ""))[1] if rid else ""
                for r in el.iter(q("w:r")):
                    self.links[id(r)] = target  # the runs come after the hyperlink element in document order
        return "".join(out), maxsize, fams

    def _drawing_inline_h(self, d) -> float:
        """The height in points of an inline picture, 0 for a floating one"""
        inl = d.find("wp:inline", NS)
        if inl is None:
            return 0.0
        return float(inl.find("wp:extent", NS).get("cy")) / 12700.0  # EMU to points

    def span_style(self, rp: RunProps) -> str:
        """CSS of one run"""
        self.families.add(rp.font)  # needed in @font-face
        self.families.add(rp.east)
        fam = FONTS.css_family(rp.font, rp.east)  # Latin face first, the East Asian face for Hangul
        s = ["font-family:" + fam, "font-size:" + fmt(rp.size)]
        if rp.bold:
            s.append("font-weight:700")
        if rp.italic:
            s.append("font-style:italic")
        s.append("color:" + color(rp.color, "#000"))  # auto is black, as in Word
        if rp.underline:
            s.append("text-decoration:underline")
        if rp.fill:
            s.append("background:#" + rp.fill)  # highlighter or badge colour
        # LibreOffice adds the spacing after every character, as CSS does. A horizontal scale widens each glyph; it is written only
        # on the blind edition's bars, whose glyph is the square, so the extra advance of the square at that scale is added the
        # same way: the bar's background then runs the width LibreOffice gives it
        extra = (rp.scale / 100 - 1) * BAR_EM["bold" if rp.bold else "regular"] * rp.size if rp.scale != 100 else 0.0
        if rp.spacing or extra:
            s.append("letter-spacing:" + fmt(rp.spacing + extra))
        if rp.raise_:
            s.append("vertical-align:" + fmt(rp.raise_))  # raised or lowered text
        return ";".join(s)

    def span(self, text: str, rp: RunProps) -> str:
        """One run of text as a span"""
        return '<span style="%s">%s</span>' % (self.span_style(rp), html.escape(text, quote=False))

    def text(self, t: str, rp: RunProps, link: str | None) -> str:
        """Text of one run. A tab character in the text is a tab, as LibreOffice reads it (the docx package writes tabs
        that way). LibreOffice puts a gap of a fifth of the font size between Hangul and a Latin letter or a digit that
        touch (save.js measured 1.8pt at 9pt); a WORD JOINER in between stops it, as save.js relies on. The gap is drawn
        as a right margin on the character before it, so the text layer stays as it is"""
        out = []  # pieces of this run: styled text and tabs
        for k, part in enumerate(t.split("\t")):  # the text between tabs
            if k:  # a tab before this part
                out.append('<span class="tab" style="font-size:%s"></span>' % fmt(rp.size))
                self._prev = " "  # a tab separates like a space
            for piece in re.split(r"(\S*\u2011\S*)", part):  # the words with a non-breaking hyphen, between the other text
                if "\u2011" in piece:  # drawn as a plain hyphen, as LibreOffice draws it (its PDF holds '-'), in a span the line cannot break
                    out.append('<span class="nb">%s</span>' % self._styled(piece.replace("\u2011", "-"), rp))
                elif piece:  # everything else
                    out.append(self._styled(piece, rp))
        inner = "".join(out)
        if link:  # a hyperlink keeps its target in the PDF
            return '<a href="%s">%s</a>' % (html.escape(link, quote=True), inner)
        return inner

    def _styled(self, t: str, rp: RunProps) -> str:
        """One piece of text in the run's style. When the run names different Latin and East Asian fonts (the label
        form: Palatino with NanumGothic), the text is split into script runs the way LibreOffice splits it: Hangul and
        CJK take the East Asian font, Latin letters the Latin one, and spaces, digits and punctuation the script of the
        letter before them (of the one after them at the start). The browser would otherwise take a space between two
        Hangul words from the first font that has one, and the line would break elsewhere"""
        if rp.east and rp.east != rp.font and ASIAN.search(t):
            out, seg, kind = [], "", None  # finished spans, the current segment and its script
            for ch in t:
                k = "a" if ASIAN.match(ch) else "l" if re.match(r"[A-Za-z\u00C0-\u024F]", ch) else None  # strong or weak
                if kind is None and k is None:  # weak characters at the start wait for the first strong one
                    seg += ch
                    continue
                if kind is None:
                    kind = k
                if k is not None and k != kind:  # a new script starts
                    out.append(self._styled_one(seg, rp, kind))
                    seg, kind = "", k
                seg += ch
            out.append(self._styled_one(seg, rp, kind or "l"))
            return "".join(out)
        return self._styled_one(t, rp, None)

    def _styled_one(self, t: str, rp: RunProps, script) -> str:
        """One piece of text in one script, with the Asian and Latin gaps"""
        pieces, buf = [], ""  # finished pieces and the current plain text
        prev = self._prev  # the character before this piece
        for ch in t:
            if ch == "\u2060":  # a word joiner stops the gap and is not written: the PDF's text must stay searchable, as LibreOffice's is
                prev = ch  # the next character sees no Hangul or Latin before it; keep-all already stops a line break here
                continue
            if prev and ((ASIAN.match(prev) and LATIN.match(ch)) or (LATIN.match(prev) and ASIAN.match(ch))):
                if buf:  # the character before the gap gets the margin
                    pieces.append(html.escape(buf[:-1], quote=False))
                    pieces.append('<span class="as">%s</span>' % html.escape(buf[-1], quote=False))
                    buf = ""
                else:  # the gap falls on a run edge: put it before this character instead
                    pieces.append('<span class="asl"></span>')
            buf += ch
            prev = ch
        pieces.append(html.escape(buf, quote=False))
        self._prev = prev  # the next run continues from here
        style = self.span_style(rp)
        if script == "a":  # an East Asian script run: its own font first
            style = style.replace("font-family:" + FONTS.css_family(rp.font, rp.east), "font-family:" + FONTS.css_family(rp.east, rp.font))
        return '<span style="%s">%s</span>' % (style, "".join(pieces))

    def field(self, instr: str, rp: RunProps) -> str:
        """A field: PAGE and NUMPAGES become placeholders that page.js fills per page"""
        name = instr.strip().split(" ")[0].upper() if instr.strip() else ""  # the field's name
        kind = {"PAGE": "page", "NUMPAGES": "pages", "SECTIONPAGES": "pages"}.get(name)
        if not kind:  # another field: nothing to show (layout.js writes no other kind)
            return ""
        return '<span class="fld" data-f="%s" style="%s">1</span>' % (kind, self.span_style(rp))

    def drawing(self, d, rels) -> str:
        """An inline or floating picture"""
        rels = rels or self.rels
        inl, anc = d.find("wp:inline", NS), d.find("wp:anchor", NS)  # one of the two
        el = inl if inl is not None else anc
        ext = el.find("wp:extent", NS)  # size in EMU
        w_, h_ = float(ext.get("cx")) / 12700.0, float(ext.get("cy")) / 12700.0  # points
        blip = el.find(".//a:blip", NS)  # the picture's relationship
        src = self.media(blip.get(R + "embed"), rels)
        if inl is not None:  # sits on the baseline like a letter
            return '<img class="inl" src="%s" style="width:%s;height:%s" alt="">' % (src, fmt(w_), fmt(h_))
        ph, pv = anc.find("wp:positionH", NS), anc.find("wp:positionV", NS)  # offsets from the column and the paragraph
        x = float(ph.find("wp:posOffset", NS).text) / 12700.0 if ph is not None and ph.find("wp:posOffset", NS) is not None else 0.0
        y = float(pv.find("wp:posOffset", NS).text) / 12700.0 if pv is not None and pv.find("wp:posOffset", NS) is not None else 0.0
        rel_h = ph.get("relativeFrom") if ph is not None else "column"  # what x is measured from
        rel_v = pv.get("relativeFrom") if pv is not None else "paragraph"  # what y is measured from
        return ('<img class="flt" src="%s" data-rh="%s" data-rv="%s" data-x="%s" data-y="%s" style="width:%s;height:%s" alt="">'
                % (src, rel_h, rel_v, num(x), num(y), fmt(w_), fmt(h_)))

    # ---------- tables

    def table(self, tbl, rels=None) -> str:
        """One w:tbl as an HTML table with fixed column widths"""
        self.ids += 1
        tpr = tbl.find("w:tblPr", NS)  # table properties
        grid = [pt(g.get(W + "w")) for g in tbl.findall("w:tblGrid/w:gridCol", NS)]  # column widths
        tb = {}  # table borders by side
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = tpr.find("w:tblBorders/w:" + side, NS) if tpr is not None else None
            tb[side] = self._border(e)
        # Default cell margins: the table's own, else Word's (0 top and bottom, 0.075in left and right).
        dm = {"top": 0.0, "bottom": 0.0, "left": 5.4, "right": 5.4}
        for side in dm:
            e = tpr.find("w:tblCellMar/w:" + side, NS) if tpr is not None else None
            if e is not None:
                dm[side] = pt(val(e, "w", "0"))
        ind = pt(val(tpr.find("w:tblInd", NS) if tpr is not None else None, "w", "0"))  # table indent
        rows = tbl.findall("w:tr", NS)  # the rows
        # Vertical merges: a cell with vMerge=restart spans down over the cells with vMerge (continue) below it.
        layout = []  # per row: [(cell, first column, span)]
        for tr in rows:
            col, cells = 0, []
            for tc in tr.findall("w:tc", NS):
                span = int(val(tc.find("w:tcPr/w:gridSpan", NS), default="1"))  # columns this cell covers
                vm = tc.find("w:tcPr/w:vMerge", NS)  # vertical merge
                cells.append((tc, col, span, None if vm is None else val(vm, default="continue")))
                col += span
            layout.append(cells)
        rowspan = {}  # (row, column) of a restart cell -> rows it covers
        for ri, cells in enumerate(layout):
            for tc, col, span, vm in cells:
                if vm == "restart":
                    n = 1
                    for below in layout[ri + 1:]:  # count the continue cells under it
                        hit = [c for c in below if c[1] == col and c[3] == "continue"]
                        if not hit:
                            break
                        n += 1
                    rowspan[(ri, col)] = n
        ncols = len(grid)
        # The table has no spacing of its own: the paragraph above it keeps its spacing after. Its outer borders lie
        # inside its height in both renderers (measured: the cards' first line 7.6pt below the 4.5pt top rule and 3pt margin).
        out = ['<table class="t" data-id="%d" style="width:%s;margin:0 0 0 %s">' % (self.ids, fmt(sum(grid)), fmt(ind))]
        out.append("<colgroup>%s</colgroup>" % "".join('<col style="width:%s">' % fmt(g) for g in grid))
        for ri, (tr, cells) in enumerate(zip(rows, layout)):
            trpr = tr.find("w:trPr", NS)  # row properties
            attrs = []
            if trpr is not None and on(trpr.find("w:cantSplit", NS)):
                attrs.append('data-cant="1"')  # the row never breaks across pages
            if trpr is not None and on(trpr.find("w:tblHeader", NS)):
                attrs.append('data-head="1"')  # the row repeats at the top of each page
            hgt = trpr.find("w:trHeight", NS) if trpr is not None else None  # a row height
            rstyle = ""
            if hgt is not None:
                hv = pt(val(hgt, default="0"))
                rule = val(hgt, "hRule", "atLeast")
                rstyle = ' style="height:%s"' % fmt(hv)  # CSS row heights are minimums, which is atLeast
                if rule == "exact":
                    attrs.append('data-exact="%g"' % hv)
            out.append("<tr %s%s>" % (" ".join(attrs), rstyle))
            # LibreOffice gives every cell of a row the largest top and the largest bottom margin of that row (layout.js
            # notes it for the header: the name cell's 8pt reached the photo cell). Measured: the contacts of the header
            # sit 3pt lower than their own 5pt margin would put them.
            row_mar = [self._margins(tc, dm) for tc, _, _, vm in cells if vm != "continue"]
            vmax = {"top": max([m["top"] for m in row_mar] or [0.0]), "bottom": max([m["bottom"] for m in row_mar] or [0.0])}
            for tc, col, span, vm in cells:
                if vm == "continue":  # covered by the cell above
                    continue
                out.append(self.cell(tc, rels, ri, col, span, rowspan.get((ri, col), 1), len(rows), ncols, tb, dm, vmax))
            out.append("</tr>")
        out.append("</table>")
        return "".join(out)

    def _border(self, e):
        """(width in points, CSS colour) of one border element, or None for no border"""
        if e is None or val(e) in (None, "none", "nil"):
            return None
        return (float(val(e, "sz", "4")) / 8.0, color(val(e, "color"), "#000"))

    def _margins(self, tc, dm) -> dict:
        """A cell's margins in points: its own, else the table's default"""
        tcp = tc.find("w:tcPr", NS)
        mar = dict(dm)
        for side in mar:
            e = tcp.find("w:tcMar/w:" + side, NS) if tcp is not None else None
            if e is not None:
                mar[side] = pt(val(e, "w", "0"))
        return mar

    def cell(self, tc, rels, ri, col, span, rspan, nrows, ncols, tb, dm, vmax=None) -> str:
        """One table cell"""
        tcp = tc.find("w:tcPr", NS)  # cell properties
        st = []
        mar = self._margins(tc, dm)  # cell margins: the table default unless the cell has its own
        if vmax:  # the row's largest top and bottom margins
            mar["top"], mar["bottom"] = vmax["top"], vmax["bottom"]
        # Borders: the cell's own, else the table's outer border on the table's edge and the inside border elsewhere.
        own = {}
        for side in ("top", "left", "bottom", "right"):
            e = tcp.find("w:tcBorders/w:" + side, NS) if tcp is not None else None
            if e is not None:
                own[side] = self._border(e)
        edge = {"top": ri == 0, "bottom": ri + rspan >= nrows, "left": col == 0, "right": col + span >= ncols}
        inside = {"top": "insideH", "bottom": "insideH", "left": "insideV", "right": "insideV"}
        half = {}  # half of each border's width: the part of a shared border that lies inside this cell
        for side in ("top", "left", "bottom", "right"):
            b = own[side] if side in own else tb[side if edge[side] else inside[side]]
            st.append("border-%s:%s" % (side, "%s solid %s" % (fmt(b[0]), b[1]) if b else "none"))
            half[side] = b[0] / 2.0 if b else 0.0
        # Left and right, LibreOffice measures cell margins from the grid line, and a border straddles that line. In CSS's
        # collapsed borders half the border lies inside the cell before the padding starts, so the padding is the margin
        # less that half (measured: with the cards' 4.5pt white gaps the text sat 2.1pt right of LibreOffice's without
        # this). Top and bottom, the margin starts inside the border (measured: two card rows 4.5pt further apart).
        pad = {"left": max(0.0, mar["left"] - half["left"]), "right": max(0.0, mar["right"] - half["right"]),
               "top": mar["top"], "bottom": mar["bottom"]}
        st.append("padding:%s %s %s %s" % (fmt(pad["top"]), fmt(pad["right"]), fmt(pad["bottom"]), fmt(pad["left"])))
        shd = tcp.find("w:shd", NS) if tcp is not None else None  # cell background
        if shd is not None and shd.get(W + "fill") not in (None, "auto"):
            st.append("background:#" + shd.get(W + "fill"))
        va = val(tcp.find("w:vAlign", NS) if tcp is not None else None, default="top")  # vertical alignment
        st.append("vertical-align:" + {"center": "middle", "bottom": "bottom"}.get(va, "top"))
        attrs = ""
        if span > 1:
            attrs += ' colspan="%d"' % span
        if rspan > 1:
            attrs += ' rowspan="%d"' % rspan
        inner = "".join(self.blocks(tc, rels, in_cell=True))  # the cell's paragraphs and nested tables
        return '<td%s style="%s"><div class="cc">%s</div></td>' % (attrs, ";".join(st), inner)

    # ---------- the page

    def convert(self, title: str = "") -> str:
        """The whole HTML page"""
        sec = self.section()  # page geometry
        body = "".join(self.blocks(self.doc.find("w:body", NS)))  # the document body
        fx, frels = self.footer_xml()  # the footer
        footer = "".join(self.blocks(fx, frels)) if fx is not None else ""
        css = (HERE / "page.css").read_text(encoding="utf-8")  # the base rules
        js = (HERE / "page.js").read_text(encoding="utf-8")  # the layout engine
        faces = FONTS.font_face_css(self.families)  # @font-face rules for the families the runs use
        lang = "ko" if self._has_hangul(body) else "en"  # the page language, for line breaking and hyphenation
        cfg = json.dumps({"page": {k: v * SCALE for k, v in sec.items()}, "scale": SCALE,  # what page.js needs, in scaled points
                          "metrics": FONTS.metrics_for(self.families)})
        real = lambda x: ("%.3f" % x).rstrip("0").rstrip(".") + "pt"  # the printed size, not scaled
        return ("<!DOCTYPE html>\n<html lang=\"%s\"><head><meta charset=\"utf-8\"><title>%s</title>\n<style>\n%s\n"
                "@page { size: %s %s; margin: 0; }\n%s\n</style></head><body>\n"
                '<div id="galley" class="body" style="width:%s">%s</div>\n'
                '<template id="footer">%s</template>\n'
                "<script>window.OWL_PAGE = %s;</script>\n<script>\n%s\n</script>\n</body></html>\n"
                % (lang, html.escape(title), faces, real(sec["w"]), real(sec["h"]), css,
                   fmt(sec["w"] - sec["left"] - sec["right"]), body, footer, cfg, js))

    @staticmethod
    def _has_hangul(s: str) -> bool:
        """True when the text holds Hangul"""
        return bool(re.search(r"[가-힣]", s))


def convert(docx: str | pathlib.Path, out: str | pathlib.Path | None = None, title: str = "") -> str:
    """Convert one DOCX; write the HTML when `out` is given and return it"""
    page = Converter(docx).convert(title or pathlib.Path(docx).stem)  # the HTML text
    if out:
        pathlib.Path(out).write_text(page, encoding="utf-8")
    return page


if __name__ == "__main__":
    if len(sys.argv) != 3:  # exactly an input and an output
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        sys.exit(2)
    convert(sys.argv[1], sys.argv[2])
