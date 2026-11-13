# -*- coding: utf-8 -*-
"""A PowerPoint copy of the portfolio deck's checked PDF: each slide is its page as one picture.

The deck is HTML that a browser printed. Turned into PowerPoint shapes, its font (Pretendard) and its figures would come
out otherwise on every PC that opens the file, so each slide holds its PDF page as one picture instead, 2560 x 1440 for
the deck's 960 x 540 pt page (192 dpi, twice its CSS pixels). It looks the same everywhere; its words cannot be edited.

- The slides are the size of the PDF's first page; a page of another shape is fitted inside its slide, centred.
- Every web and mail link of a page (the cover's email and profile, the last slide's) stays where it was: a rectangle
  over the picture that a click in the slide show follows. A shape with no fill cannot be clicked inside, so it is
  filled white at full transparency, with no line.
- Each picture's alternative text is its page's words, so a screen reader and a search read them.
- The title and the author are the PDF's own.

Only the standard library: the package is XML text in a zip, as ECMA-376 Part 1 lays out PresentationML. The page
pictures and words come from src/pdftools.py (poppler or PDFium), or from the callers' own readers.

    python3 src/deck_pptx.py deck.pdf deck.pptx "Title" "Author"
"""
import pathlib  # the files
import re  # the words and the read-back
import struct  # a PNG's size, from its header
import sys  # the command line
import tempfile  # the page pictures, made and gone
import zipfile  # a PPTX is a zip of XML parts

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # the sibling modules, however this file was started
import pdfmeta  # noqa: E402  the pages' sizes and links, and the PDF's title and author
import pdftools  # noqa: E402  the page pictures and words

DPI = 192  # the deck's 960 pt become 2560 pixels: twice the CSS pixels it was drawn at
EMU = 12700  # PowerPoint's units in a point
ALT_MAX = 4000  # characters of a page's words in its picture's alternative text: every page of a drawn deck fits (an English page ran to 1,444)
NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '  # DrawingML
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '  # relationships
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')  # PresentationML
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'  # every XML part's first line
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"  # the relationship types' common start
CT = "application/vnd.openxmlformats-officedocument.presentationml."  # the presentation parts' content types' common start
TREE = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/>'
        '<a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')  # a shape tree's own group, which every slide, layout and master starts with

# The theme every presentation needs: the standard colour, font and effect schemes, with Pretendard as the theme font
THEME = (HEAD + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Offerowl"><a:themeElements>'
         '<a:clrScheme name="Offerowl"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
         '<a:dk2><a:srgbClr val="1B2E4B"/></a:dk2><a:lt2><a:srgbClr val="E9EEF6"/></a:lt2><a:accent1><a:srgbClr val="1B2E4B"/></a:accent1>'
         '<a:accent2><a:srgbClr val="F2C744"/></a:accent2><a:accent3><a:srgbClr val="1D5C63"/></a:accent3><a:accent4><a:srgbClr val="5E2233"/></a:accent4>'
         '<a:accent5><a:srgbClr val="1F4D3A"/></a:accent5><a:accent6><a:srgbClr val="2F3B47"/></a:accent6><a:hlink><a:srgbClr val="1B2E4B"/></a:hlink>'
         '<a:folHlink><a:srgbClr val="5E2233"/></a:folHlink></a:clrScheme>'
         '<a:fontScheme name="Offerowl"><a:majorFont><a:latin typeface="Pretendard"/><a:ea typeface="Pretendard"/><a:cs typeface=""/></a:majorFont>'
         '<a:minorFont><a:latin typeface="Pretendard"/><a:ea typeface="Pretendard"/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
         '<a:fmtScheme name="Offerowl"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
         '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
         '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
         '<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
         '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
         '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
         '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
# The one master: a white background, the colour map, its one layout; text styles empty, since no slide holds text
MASTER = (HEAD + f'<p:sldMaster {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
          f'<p:spTree>{TREE}</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
          'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
          '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>')
LAYOUT = (HEAD + f'<p:sldLayout {NS} type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{TREE}</p:spTree></p:cSld>'
          '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')  # the blank layout each slide uses


def attr(text: str) -> str:
    """Text for an XML attribute: escaped, with the control characters XML forbids taken out."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)  # never allowed in XML 1.0
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def alt_text(words: str) -> str:
    """A page's words as one line for its picture's alternative text, cut at a word under ALT_MAX characters."""
    line = re.sub(r"\s+", " ", words).strip()  # one line
    if len(line) <= ALT_MAX:
        return line
    cut = line[:ALT_MAX]  # too long for one picture's description
    return cut[:cut.rfind(" ")] if " " in cut else cut  # at a word


def png_size(data: bytes) -> tuple[int, int]:
    """A PNG's width and height in pixels, from its header; (0, 0) for anything else."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":  # not a PNG
        return 0, 0
    return struct.unpack(">II", data[16:24])


def rels(items: list) -> str:
    """A relationships part from (id, type, target, external) entries."""
    out = "".join(f'<Relationship Id="{rid}" Type="{kind if "://" in kind else REL + kind}" Target="{attr(target)}"' + (' TargetMode="External"' if ext else "") + "/>"
                  for rid, kind, target, ext in items)
    return HEAD + f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{out}</Relationships>'


def place(page: dict, cx: int, cy: int) -> tuple[float, float, float]:
    """Where a page goes on its slide: (scale from points to EMU, left, top), fitted inside and centred."""
    s = min(cx / (page["width"] * EMU), cy / (page["height"] * EMU)) * EMU  # EMU per point of this page
    return s, (cx - page["width"] * s) / 2, (cy - page["height"] * s) / 2


def slide(n: int, page: dict, words: str, cx: int, cy: int) -> tuple[str, str]:
    """Slide n's XML and its relationships: the page's picture (rId2) and a clickable, invisible rectangle per link."""
    s, left, top = place(page, cx, cy)  # how the page sits on the slide
    shapes = (f'<p:pic><p:nvPicPr><p:cNvPr id="2" name="Page {n}" descr="{attr(alt_text(words))}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
              f'<p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
              f'<p:spPr><a:xfrm><a:off x="{round(left)}" y="{round(top)}"/><a:ext cx="{round(page["width"] * s)}" cy="{round(page["height"] * s)}"/></a:xfrm>'
              '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')  # the page, whole
    links = [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False), ("rId2", "image", f"../media/page{n}.png", False)]  # the layout and the picture
    for k, link in enumerate(page["links"], 3):  # each link of the page, over the picture
        links.append((f"rId{k}", "hyperlink", link["uri"], True))  # where a click goes
        x, y = left + link["x0"] * s, top + link["y0"] * s  # its corner on the slide
        w, h = max(1, (link["x1"] - link["x0"]) * s), max(1, (link["y1"] - link["y0"]) * s)  # its size, never empty
        shapes += (f'<p:sp><p:nvSpPr><p:cNvPr id="{k}" name="Link {attr(link["uri"])}"><a:hlinkClick r:id="rId{k}"/></p:cNvPr><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
                   f'<p:spPr><a:xfrm><a:off x="{round(x)}" y="{round(y)}"/><a:ext cx="{round(w)}" cy="{round(h)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
                   '<a:solidFill><a:srgbClr val="FFFFFF"><a:alpha val="0"/></a:srgbClr></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr></p:sp>')  # filled, so its inside takes a click; seen nowhere
    xml = HEAD + f'<p:sld {NS}><p:cSld><p:spTree>{TREE}{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
    return xml, rels(links)


def _pictures(pdf, folder: pathlib.Path) -> list:
    """The PDF's pages as PNG files with this PC's reader (src/pdftools.py)."""
    return pdftools.render_png(pdf, folder / "page", dpi=DPI)


def make(pdf, dst, title: str, author: str, pictures=None, text=None) -> int:
    """Write the PowerPoint copy of a deck's PDF to dst. pictures(pdf, folder) gives the page pictures in order (else this
    PC's reader draws them at DPI), text(pdf) the words with a form feed after each page (else this PC's reader). Returns
    the number of slides; raises ValueError when the pages cannot be read or drawn."""
    pages = pdfmeta.page_links(pdf)  # each page's size and links
    if not pages:  # no page tree this can read
        raise ValueError("no pages")
    words = ((text or pdftools.text)(pdf) or "").split("\f")  # each page's words
    cx, cy = round(pages[0]["width"] * EMU), round(pages[0]["height"] * EMU)  # the slides, as large as the first page
    if not (914400 <= cx <= 51206400 and 914400 <= cy <= 51206400):  # the slide sizes PowerPoint allows: 1 to 56 inches
        raise ValueError("a page size PowerPoint cannot take")
    with tempfile.TemporaryDirectory(prefix="offerowl-pptx-") as tmp:  # the pictures, gone afterwards
        files = [pathlib.Path(f) for f in (pictures or _pictures)(pdf, pathlib.Path(tmp))]  # one per page
        if len(files) != len(pages):  # a page that was not drawn
            raise ValueError(f"{len(files)} pictures for {len(pages)} pages")
        n = len(pages)  # the slides
        types = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
                 '<Default Extension="xml" ContentType="application/xml"/>', '<Default Extension="png" ContentType="image/png"/>',
                 f'<Override PartName="/ppt/presentation.xml" ContentType="{CT}presentation.main+xml"/>',
                 f'<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="{CT}slideMaster+xml"/>',
                 f'<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="{CT}slideLayout+xml"/>',
                 '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
                 f'<Override PartName="/ppt/presProps.xml" ContentType="{CT}presProps+xml"/>',
                 f'<Override PartName="/ppt/viewProps.xml" ContentType="{CT}viewProps+xml"/>',
                 f'<Override PartName="/ppt/tableStyles.xml" ContentType="{CT}tableStyles+xml"/>',
                 '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
                 '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>']
        types += [f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="{CT}slide+xml"/>' for i in range(1, n + 1)]  # each slide
        parts = {  # every part but the slides and their pictures
            "[Content_Types].xml": HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' + "".join(types) + "</Types>",
            "_rels/.rels": rels([("rId1", "officeDocument", "ppt/presentation.xml", False),
                                 ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml", False),
                                 ("rId3", "extended-properties", "docProps/app.xml", False)]),
            "docProps/core.xml": HEAD + ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                                         'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + attr(title) + "</dc:title><dc:creator>" + attr(author)
                                         + "</dc:creator><cp:lastModifiedBy>" + attr(author) + "</cp:lastModifiedBy></cp:coreProperties>"),  # what File > Info shows
            "docProps/app.xml": HEAD + ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                                        f"<Slides>{n}</Slides></Properties>"),
            "ppt/presentation.xml": HEAD + (f'<p:presentation {NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'
                                            + "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n + 1))  # slide ids start at 256
                                            + f'</p:sldIdLst><p:sldSz cx="{cx}" cy="{cy}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'),
            "ppt/_rels/presentation.xml.rels": rels([("rId1", "slideMaster", "slideMasters/slideMaster1.xml", False)]
                                                    + [(f"rId{i + 1}", "slide", f"slides/slide{i}.xml", False) for i in range(1, n + 1)]
                                                    + [(f"rId{n + 2}", "presProps", "presProps.xml", False), (f"rId{n + 3}", "viewProps", "viewProps.xml", False),
                                                       (f"rId{n + 4}", "theme", "theme/theme1.xml", False), (f"rId{n + 5}", "tableStyles", "tableStyles.xml", False)]),
            "ppt/presProps.xml": HEAD + f"<p:presentationPr {NS}/>",
            "ppt/viewProps.xml": HEAD + f"<p:viewPr {NS}/>",
            "ppt/tableStyles.xml": HEAD + '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>',
            "ppt/theme/theme1.xml": THEME,
            "ppt/slideMasters/slideMaster1.xml": MASTER,
            "ppt/slideMasters/_rels/slideMaster1.xml.rels": rels([("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False), ("rId2", "theme", "../theme/theme1.xml", False)]),
            "ppt/slideLayouts/slideLayout1.xml": LAYOUT,
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": rels([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml", False)]),
        }
        dst = pathlib.Path(dst)  # where the copy goes
        part = dst.with_name(dst.name + ".part")  # written whole first
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for name, xml in parts.items():  # [Content_Types].xml first, as some readers want
                z.writestr(name, xml.encode("utf-8"))
            for i, (page, png) in enumerate(zip(pages, files), 1):  # each slide, its relationships and its picture
                xml, rel = slide(i, page, words[i - 1] if i - 1 < len(words) else "", cx, cy)
                z.writestr(f"ppt/slides/slide{i}.xml", xml.encode("utf-8"))
                z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", rel.encode("utf-8"))
                z.writestr(zipfile.ZipInfo(f"ppt/media/page{i}.png", date_time=(2026, 1, 1, 0, 0, 0)), png.read_bytes(), compress_type=zipfile.ZIP_STORED)  # a PNG is compressed already
        part.replace(dst)  # in place at once
    return n


def problems(pptx, pdf, title: str, author: str, words: list | None = None) -> list[str]:
    """The copy read back against its PDF: one slide per page in order, each with one picture of its page at DPI inside the
    slide, the page's links at their places, and the PDF's title and author; with words (each page's, as make() read them),
    each picture's description is its page's words. The problems found ([] when there are none)."""
    pages = pdfmeta.page_links(pdf)  # what the slides must be
    try:
        z = zipfile.ZipFile(pathlib.Path(pptx))
    except (OSError, zipfile.BadZipFile):  # not a zip
        return ["not a zip file"]
    with z:
        if z.testzip() is not None:  # a damaged part
            return ["a damaged part"]
        names = set(z.namelist())  # the parts
        pres = z.read("ppt/presentation.xml").decode("utf-8") if "ppt/presentation.xml" in names else ""
        prels = z.read("ppt/_rels/presentation.xml.rels").decode("utf-8") if "ppt/_rels/presentation.xml.rels" in names else ""
        order = [re.search(rf'Id="{rid}"[^>]*Target="([^"]+)"', prels) for rid in re.findall(r'<p:sldId [^>]*r:id="([^"]+)"', pres)]  # the slides in order
        slides = ["ppt/" + m.group(1) for m in order if m]
        if len(slides) != len(pages):
            return [f"{len(slides)} slides for {len(pages)} pages"]
        size = re.search(r'<p:sldSz cx="(\d+)" cy="(\d+)"', pres)  # the slide's size
        cx, cy = (int(size.group(1)), int(size.group(2))) if size else (0, 0)
        bad = []  # what is wrong
        for i, (name, page) in enumerate(zip(slides, pages), 1):  # each slide against its page
            xml = z.read(name).decode("utf-8") if name in names else ""
            rel_name = name.replace("slides/", "slides/_rels/") + ".rels"  # its relationships
            rel = z.read(rel_name).decode("utf-8") if rel_name in names else ""
            pics = re.findall(r"<p:pic>.*?</p:pic>", xml, re.S)  # its pictures
            if len(pics) != 1:
                bad.append(f"slide {i} has {len(pics)} pictures")
                continue
            embed = re.search(r'<a:blip r:embed="([^"]+)"', pics[0])
            target = re.search(rf'Id="{embed.group(1)}"[^>]*Target="\.\./([^"]+)"', rel) if embed else None  # the picture's file
            data = z.read("ppt/" + target.group(1)) if target and "ppt/" + target.group(1) in names else b""
            w, h = png_size(data)  # its pixels
            if abs(w - page["width"] * DPI / 72) > 1.5 or abs(h - page["height"] * DPI / 72) > 1.5:  # not the page at DPI
                bad.append(f"slide {i}'s picture is {w} x {h}")
            off = [int(v) for v in re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/><a:ext cx="(\d+)" cy="(\d+)"', pics[0]).groups()]
            if off[0] < 0 or off[1] < 0 or off[0] + off[2] > cx + 1 or off[1] + off[3] > cy + 1:  # outside the slide
                bad.append(f"slide {i}'s picture is not on the slide")
            if words is not None:  # the description is the page's words
                descr = re.search(r'descr="([^"]*)"', pics[0])
                if (descr.group(1) if descr else "") != attr(alt_text(words[i - 1] if i - 1 < len(words) else "")):
                    bad.append(f"slide {i}'s description is not its page's words")
            got = []  # the links on the slide: (address, x, y, w, h)
            for sp in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S):
                hl = re.search(r'<a:hlinkClick r:id="([^"]+)"', sp)
                where = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/><a:ext cx="(\d+)" cy="(\d+)"', sp)
                to = re.search(rf'Id="{hl.group(1)}"[^>]*Target="([^"]+)"[^>]*TargetMode="External"', rel) if hl else None
                if to and where:
                    got.append((to.group(1).replace("&amp;", "&"), *[int(v) for v in where.groups()]))
            s, left, top = place(page, cx, cy)  # where the page sits
            want = [(link["uri"], round(left + link["x0"] * s), round(top + link["y0"] * s)) for link in page["links"]]
            if sorted(u for u, *_ in got) != sorted(u for u, *_ in want):  # not the page's links
                bad.append(f"slide {i}'s links are not the page's")
            elif any(min(abs(g[1] - w_[1]) + abs(g[2] - w_[2]) for g in got if g[0] == w_[0]) > EMU for w_ in want):  # a link more than a point from its place
                bad.append(f"slide {i}'s links are not where the page has them")
        core = z.read("docProps/core.xml").decode("utf-8") if "docProps/core.xml" in names else ""
        if f"<dc:title>{attr(title)}</dc:title>" not in core or f"<dc:creator>{attr(author)}</dc:creator>" not in core or not title.strip() or not author.strip():
            bad.append("the title or the author is not the PDF's")
        return bad


def described(pptx) -> list[str]:
    """Each slide's picture description, in order (the words a screen reader reads)."""
    with zipfile.ZipFile(pathlib.Path(pptx)) as z:
        n = len(re.findall(r"<p:sldId ", z.read("ppt/presentation.xml").decode("utf-8")))  # the slides
        out = []
        for i in range(1, n + 1):
            m = re.search(r'<p:cNvPr id="2" name="Page \d+" descr="([^"]*)"', z.read(f"ppt/slides/slide{i}.xml").decode("utf-8"))
            out.append(m.group(1).replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&") if m else "")
        return out


def main(argv=None) -> int:
    """The command line: python3 src/deck_pptx.py deck.pdf deck.pptx "Title" "Author" """
    a = list(sys.argv[1:] if argv is None else argv)  # the arguments
    if len(a) not in (2, 4):  # the PDF, the copy, and the title and author when the PDF's own are not wanted
        print('usage: deck_pptx.py deck.pdf deck.pptx ["Title" "Author"]')
        return 2
    meta = pdfmeta.read(a[0])  # the PDF's own title and author
    title, author = (a[2], a[3]) if len(a) == 4 else (meta.get("title") or "", meta.get("author") or "")
    n = make(a[0], a[1], title, author)  # the copy
    bad = problems(a[1], a[0], title, author, pdftools.text(a[0]).split("\f"))  # read back, its descriptions too
    print(f"{n} slides: {a[1]}" + ("".join("\n  - " + b for b in bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
