# -*- coding: utf-8 -*-
"""Reading a finished PDF: its text, the boxes of its lines and words, its size, and pictures of its pages.

The checks, the panel's page previews and the reading of old resumes all go through this module. It uses poppler
(pdftotext, pdfinfo, pdftoppm) where poppler is installed, as it is in the render container, and otherwise PDFium through
pypdfium2, which the desktop app carries. So a PC with neither Docker nor poppler can still read and check a PDF.

    text(pdf, layout=False, first=None, last=None)   the text, each page ended by a form feed, as pdftotext writes it
    bbox_layout(pdf)                                 the lines and words with their boxes, in the XML of pdftotext -bbox-layout
    info(pdf)                                        {"pages": 2, "width": 595.0, "height": 842.0} in points, of the first page
    render_png(pdf, prefix, dpi=..., gray=False, first=None, last=None)   one PNG per page: <prefix>-1.png ...

Boxes come from the font's own height, as poppler's do, so a measure on them means the same with both readers.
"""
import html  # the words inside the XML
import os  # the reader setting
import pathlib  # the output files
import re  # the size line of pdfinfo
import shutil  # is poppler there
import subprocess  # poppler's programs

LINE_GAP = 1.0  # a space wider than this many line heights starts a new line box, as pdftotext splits a line at a wide gap
ROW_SHARE = 0.5  # two boxes are on one printed row when they overlap by this share of the lower one's height


class PdfToolsMissing(RuntimeError):
    """Neither poppler nor pypdfium2 is on this PC."""


def have_poppler() -> bool:
    """Is poppler installed here, and not switched off by OFFEROWL_PDF_READER=pdfium?"""
    if os.environ.get("OFFEROWL_PDF_READER", "").strip().lower() == "pdfium":  # the tests measure the other reader on a PC that has both
        return False
    return bool(shutil.which("pdftotext") and shutil.which("pdftoppm") and shutil.which("pdfinfo"))  # the three programs this module starts


def have_pdfium() -> bool:
    """Is pypdfium2 installed here? (Asked without importing it, since it loads a large library.)"""
    import importlib.util  # find_spec looks without importing
    return importlib.util.find_spec("pypdfium2") is not None  # the one Python package this module can use


def reader() -> str:
    """The reader in use: poppler, pdfium, or an empty string when there is neither."""
    return "poppler" if have_poppler() else "pdfium" if have_pdfium() else ""  # poppler first: the container's results stay what they were


def _document(pdf):
    """The PDF opened with PDFium."""
    try:  # the import fails on a PC that has neither reader
        import pypdfium2  # loaded on first use
    except ImportError as e:  # nothing can read a PDF here
        raise PdfToolsMissing("reading a PDF needs poppler or pypdfium2") from e
    return pypdfium2.PdfDocument(str(pdf))  # the file stays open until the object goes


def _pages(doc, first, last) -> range:
    """Page indexes for a 1-based first and last page, as poppler's -f and -l count them."""
    return range((first or 1) - 1, min(last or len(doc), len(doc)))  # past the end is cut off, as poppler does


def _rows(page) -> list:
    """The text of one page as rows of boxes: [{x0, y0, x1, y1, words: [{x0, y0, x1, y1, text}]}], y counted from the top.
    A row ends at a line end PDFium reports, or at a space much wider than the text is tall."""
    height = page.get_height()  # PDF coordinates count from the bottom
    tp = page.get_textpage()  # the characters of this page
    rows, cur, word = [], None, None  # finished rows, the row being filled, the word being filled

    def end_word():
        nonlocal word
        if word and word["text"].strip():  # a word that holds something
            cur["words"].append(word)  # it joins its row
            cur["x1"] = max(cur["x1"], word["x1"])  # and the row's box grows
            cur["y0"], cur["y1"] = min(cur["y0"], word["y0"]), max(cur["y1"], word["y1"])
        word = None

    def end_row():
        nonlocal cur
        end_word()  # the last word first
        if cur and cur["words"]:  # a row with words
            rows.append(cur)
        cur = None

    for i in range(tp.count_chars()):  # character by character
        ch = tp.get_text_range(i, 1)  # the character
        if ch in ("\r", "\n"):  # a line end PDFium worked out
            end_row()
            continue
        if not ch.strip():  # a space ends a word
            end_word()
            continue
        left, bottom, right, top = tp.get_charbox(i, loose=True)  # the font's own box, as poppler measures
        y0, y1 = height - top, height - bottom  # from the top of the page
        if cur is not None and (word or cur["words"]):  # is this character still on the row?
            before = word["x1"] if word else cur["words"][-1]["x1"]  # where the text so far ends
            gap = left - before  # the space before this character
            if gap > LINE_GAP * max(y1 - y0, 1.0) or y0 >= cur["y1"] - 0.5:  # a wide gap, or a new line PDFium did not mark
                end_row()
        if cur is None:  # the first character of a row
            cur = {"x0": left, "y0": y0, "x1": right, "y1": y1, "words": []}
        if word is None:  # the first character of a word
            word = {"x0": left, "y0": y0, "x1": right, "y1": y1, "text": ""}
        word["text"] += ch  # the word grows
        word["x1"] = max(word["x1"], right)  # to the right
        word["y0"], word["y1"] = min(word["y0"], y0), max(word["y1"], y1)  # and to the tallest font in it
    end_row()  # the page's last row
    return rows


def text(pdf, layout: bool = False, first: int | None = None, last: int | None = None) -> str:
    """The text of a PDF. Each page ends with a form feed. layout=True keeps columns side by side."""
    if have_poppler():  # the reader the checks were written against
        cmd = ["pdftotext"] + (["-layout"] if layout else [])  # the program and its one mode switch
        cmd += (["-f", str(first)] if first else []) + (["-l", str(last)] if last else [])  # the page range
        return subprocess.run(cmd + [str(pdf), "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout  # the dash sends it to standard output
    doc = _document(pdf)  # with PDFium
    out = []  # one string per page
    for n in _pages(doc, first, last):  # each page asked for
        page = doc[n]  # the page
        if layout:  # rows top to bottom, the parts of a row left to right, with a wide space between them
            rows = _rows(page)  # the boxes
            groups = []  # [rows that share a printed line]
            for r in sorted(rows, key=lambda x: (x["y0"], x["x0"])):  # top to bottom
                g = groups[-1] if groups else None  # the printed line so far
                if g and min(r["y1"], g[0]["y1"]) - max(r["y0"], g[0]["y0"]) > ROW_SHARE * (r["y1"] - r["y0"]):  # the same printed line
                    g.append(r)
                else:  # a new printed line
                    groups.append([r])
            lines = ["     ".join(" ".join(w["text"] for w in r["words"]) for r in sorted(g, key=lambda x: x["x0"])) for g in groups]  # one string per printed line
            out.append("\n".join(lines) + "\n")
        else:  # in reading order, as PDFium worked it out
            out.append(page.get_textpage().get_text_range().replace("\r\n", "\n").replace("\r", "\n") + "\n")
    return "".join(p + "\f" for p in out)  # pages end with a form feed, as pdftotext writes them


def bbox_layout(pdf) -> str:
    """The lines and words of a PDF with their boxes, in the XML pdftotext -bbox-layout writes: y counts from the top of
    the page, and a <line> holds <word> elements."""
    if have_poppler():  # the reader the checks were written against
        return subprocess.run(["pdftotext", "-bbox-layout", str(pdf), "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    doc = _document(pdf)  # with PDFium
    out = ["<doc>"]  # the document

    def box(b):  # the four attributes, in the order the checks' patterns read them
        return f'xMin="{b["x0"]:.6f}" yMin="{b["y0"]:.6f}" xMax="{b["x1"]:.6f}" yMax="{b["y1"]:.6f}"'

    for n in range(len(doc)):  # every page
        page = doc[n]  # the page
        out.append(f'<page width="{page.get_width():.6f}" height="{page.get_height():.6f}"><flow>')
        for r in _rows(page):  # each row is one block with one line
            out.append(f"<block {box(r)}><line {box(r)}>" + "".join(f'<word {box(w)}>{html.escape(w["text"], quote=False)}</word>' for w in r["words"]) + "</line></block>")
        out.append("</flow></page>")
    return "\n".join(out + ["</doc>"]) + "\n"


def info(pdf) -> dict:
    """{"pages", "width", "height"} of a PDF, the size in points of its first page. Pages is 0 for an unreadable file."""
    if have_poppler():  # pdfinfo prints both
        got = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        pages = re.search(r"Pages:\s+(\d+)", got)  # the page count
        size = re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", got)  # the first page's size
        return {"pages": int(pages.group(1)) if pages else 0, "width": float(size.group(1)) if size else 0.0, "height": float(size.group(2)) if size else 0.0}
    try:  # an unreadable file counts as no pages, as above
        doc = _document(pdf)  # with PDFium
    except PdfToolsMissing:  # nothing to read it with: the caller has to know
        raise
    except Exception:  # noqa: BLE001  the library has its own error for a damaged file
        return {"pages": 0, "width": 0.0, "height": 0.0}
    width, height = doc[0].get_size() if len(doc) else (0.0, 0.0)  # the first page
    return {"pages": len(doc), "width": float(width), "height": float(height)}


def render_png(pdf, prefix, dpi: int = 100, gray: bool = False, first: int | None = None, last: int | None = None) -> list:
    """One PNG per page, named <prefix>-1.png, <prefix>-2.png ... in page order. Returns the files."""
    prefix = pathlib.Path(prefix)  # the folder and the start of the name
    if have_poppler():  # pdftoppm pads the number by the page count (p-01.png), so the files are renamed below
        cmd = ["pdftoppm", "-r", str(dpi), "-png"] + (["-gray"] if gray else [])  # size and colour
        cmd += (["-f", str(first)] if first else []) + (["-l", str(last)] if last else [])  # the page range
        subprocess.run(cmd + [str(pdf), str(prefix)], capture_output=True)
        made = sorted(prefix.parent.glob(prefix.name + "-*.png"), key=lambda p: int(re.search(r"-(\d+)\.png$", p.name).group(1)))  # in page order, not name order
        out = []  # the files under their plain names
        for p in made:  # p-01.png to p-1.png
            number = int(re.search(r"-(\d+)\.png$", p.name).group(1))  # the page, without its padding
            q = p.with_name(f"{prefix.name}-{number}.png")  # the plain name
            if q != p:  # nothing to do when it had no padding
                p.replace(q)
            out.append(q)
        return out
    doc = _document(pdf)  # with PDFium
    out = []  # the files
    for n in _pages(doc, first, last):  # each page asked for
        image = doc[n].render(scale=dpi / 72, grayscale=gray).to_pil()  # 72 points to the inch
        f = prefix.with_name(f"{prefix.name}-{n + 1}.png")  # numbered like the page
        image.save(str(f))  # written
        out.append(f)
    return out
