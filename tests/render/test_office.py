# -*- coding: utf-8 -*-
"""The Word and PowerPoint files the export writes, on small fictional files made here: the Word-ready copy of a DOCX
(src/docx_word.py), the PowerPoint copy of a deck's PDF (src/deck_pptx.py), the page links it keeps (src/pdfmeta.py
page_links), and the questions to Word and PowerPoint (src/office_check.py) with PowerShell stood in, so no Office runs.

Run: python3 -m unittest tests/render/test_office.py -v
"""
import os  # the switch that turns Office off
import pathlib  # paths
import re  # the parts' XML
import struct  # a PNG's header
import subprocess  # the stand-in for PowerShell raises its errors
import sys  # the import path
import tempfile  # a folder per test
import unittest  # the runner
import xml.etree.ElementTree as ET  # every part must be well-formed XML
import zipfile  # DOCX and PPTX are zips
import zlib  # a PNG's pixels, an object stream's objects
from unittest import mock  # PowerShell stood in for

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
sys.path.insert(0, str(ROOT / "src"))  # the modules under test
import deck_pptx  # noqa: E402  the PowerPoint copy
import docx_word  # noqa: E402  the Word-ready copy
import office_check  # noqa: E402  Word and PowerPoint on this PC
import pdfmeta  # noqa: E402  the pages and their links
import pdftools  # noqa: E402  is there a reader on this PC

W14 = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
SHARE = (1949 + 494) / 2048  # Pretendard's ascent and descent: LibreOffice's single line, as a share of the size


def run(text: str, size: int | None = None) -> str:
    """One run of text, at its own size in half-points or the document's default."""
    sz = f'<w:rPr><w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr>' if size else ""
    return f"<w:r>{sz}<w:t xml:space=\"preserve\">{text}</w:t></w:r>"


# The paragraphs of the fictional resume, one of each kind the typesetting writes (layout.js through the docx package)
BODY = [
    '<w:p><w:pPr><w:spacing w:after="20" w:line="230"/></w:pPr>' + run("결제 승인 서비스를 나눴다", 17) + "</w:p>",  # 0: a line with no rule
    '<w:p><w:pPr><w:spacing w:line="264" w:lineRule="auto"/></w:pPr>' + run("정산과 알림을 이벤트로 옮겼다", 18) + "</w:p>",  # 1: an auto line, 1.1 lines
    '<w:p><w:pPr><w:spacing w:before="160"/><w:jc w:val="left"/></w:pPr>' + run("홍길동", 24) + run(" 백엔드", 14) + "</w:p>",  # 2: single, two sizes
    "<w:p>" + run("기본 크기의 글") + "</w:p>",  # 3: no properties, the default size
    '<w:p><w:pPr><w:spacing w:line="20" w:lineRule="exact"/></w:pPr></w:p>',  # 4: exact already
    '<w:p><w:pPr><w:spacing/></w:pPr><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"/></w:drawing></w:r></w:p>',  # 5: a picture
    "<w:p/>",  # 6: empty
    '<w:p><w:pPr><w:jc w:val="both"/><w:rPr><w:spacing w:val="-4"/><w:sz w:val="16"/></w:rPr></w:pPr><w:r><w:rPr><w:spacing w:val="-4"/><w:sz w:val="16"/></w:rPr><w:t>자간</w:t></w:r></w:p>',  # 7: letter spacing in the mark
]


def make_docx(path: pathlib.Path, body=None, title: str = "홍길동 이력서", author: str = "홍길동") -> pathlib.Path:
    """A DOCX of the shape the docx package writes (read from a real one): an empty font table, settings that start with
    displayBackgroundShape, odttf already named in the content types, a footer, and stored (uncompressed) parts."""
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W14}><w:body>' + "".join(BODY if body is None else body)
           + '<w:sectPr><w:footerReference w:type="default" r:id="rId7"/><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>')
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                               '<Default ContentType="image/png" Extension="png"/><Default ContentType="application/vnd.openxmlformats-package.relationships+xml" Extension="rels"/>'
                               '<Default ContentType="application/xml" Extension="xml"/><Default ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont" Extension="odttf"/>'
                               '<Override ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" PartName="/word/document.xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": doc,
        "word/styles.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {W14}><w:docDefaults><w:rPrDefault><w:rPr>'
                           '<w:rFonts w:ascii="Pretendard" w:eastAsia="Pretendard" w:hAnsi="Pretendard" w:cs="Pretendard"/><w:sz w:val="18"/></w:rPr></w:rPrDefault><w:pPrDefault/></w:docDefaults>'
                           '<w:style w:type="paragraph" w:styleId="Title"><w:pPr><w:spacing w:line="300"/></w:pPr></w:style>'  # a style's unnamed rule
                           '<w:style w:type="paragraph" w:styleId="FootnoteText"><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:style></w:styles>',
        "word/settings.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings {W14}><w:displayBackgroundShape/><w:evenAndOddHeaders w:val="false"/>'
                             '<w:compat><w:compatSetting w:val="15" w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word"/></w:compat></w:settings>',
        "word/fontTable.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:fonts {W14}/>',
        "word/_rels/fontTable.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        "word/footer1.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {W14}><w:p>' + run("홍길동 1/1", 15) + "</w:p></w:ftr>",
        "docProps/core.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                             'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Un-named</dc:title><dc:creator>Un-named</dc:creator><cp:revision>1</cp:revision></cp:coreProperties>',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:  # stored, as the docx package writes
        for name, xml in parts.items():
            z.writestr(name, xml)
    return path


def png(path: pathlib.Path, w: int, h: int) -> pathlib.Path:
    """A white PNG of w x h pixels, written with the standard library."""
    def chunk(kind: bytes, body: bytes) -> bytes:  # one chunk with its checksum
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\xff" * (w * 3) for _ in range(h))  # each row: no filter, white
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return path


def write_file(path: pathlib.Path, objects: list, trailer: str) -> None:
    """A PDF of these objects (numbered from 1) with a cross-reference table and this trailer dictionary."""
    out, offsets = "%PDF-1.5\n", []  # the file, and where each object starts
    for i, body in enumerate(objects, 1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out.encode("latin-1"))  # the table of offsets
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n{trailer}\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(out.encode("latin-1"))


def deck_pdf(path: pathlib.Path, pages: list, indirect: bool = False) -> pathlib.Path:
    """A deck PDF: pages are (width, height, [(x0, y0, x1, y1 from the top, address)], text), with each link an annotation
    as Chromium writes it (the action inside the annotation, or its own object with indirect)."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]  # 1 catalog, 2 tree, 3 font
    kids = []  # the page objects
    for w, h, links, text in pages:
        stream = f"BT /F1 10 Tf 1 0 0 1 10 {h - 20} Tm ({text}) Tj ET" if text else ""  # its words
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content = len(objects)  # the stream's number
        annots = []  # its annotations' numbers
        for x0, y0, x1, y1, uri in links:
            action = f"<< /Type /Action /S /URI /URI ({uri}) >>"
            if indirect:  # the action as an object of its own
                objects.append(action)
                action = f"{len(objects)} 0 R"
            objects.append(f"<< /Type /Annot /Subtype /Link /F 4 /Border [0 0 0] /Rect [{x0} {h - y1} {x1} {h - y0}] /A {action} >>")
            annots.append(len(objects))
        annot = f" /Annots [{' '.join(f'{a} 0 R' for a in annots)}]" if annots else ""
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Contents {content} 0 R /Resources << /Font << /F1 3 0 R >> >>{annot} >>")
        kids.append(len(objects))
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    write_file(path, objects, f"<< /Size {len(objects) + 1} /Root 1 0 R >>")
    return path


# The fictional deck: a cover with two links, an empty page, and a square page that a 16:9 slide fits
DECK = [(192, 108, [(100, 60, 180, 70, "mailto:gildong@example.com"), (100, 75, 180, 85, "https://github.com/example-gildong")], "PORTFOLIO Gildong Hong"),
        (192, 108, [], "OVERVIEW"),
        (108, 108, [(10, 10, 50, 20, "https://example.com/a?b=1&c=2")], "")]
WORDS = "PORTFOLIO   Gildong\nHong\fOVERVIEW\f\f"  # each page's words as a reader gives them, a form feed after each


class WordReady(unittest.TestCase):
    """The Word-ready copy: Word's line heights at LibreOffice's, Pretendard inside, the PDF's title and author."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-word-"))  # this test's files
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))
        self.src = make_docx(self.dir / "resume.docx")  # the fictional resume
        self.out = self.dir / "ready.docx"
        docx_word.ready(self.src, self.out, "홍길동 이력서 & 포트폴리오", "홍길동")  # an ampersand the XML must escape

    def part(self, name: str) -> str:
        with zipfile.ZipFile(self.out) as z:
            return z.read(name).decode("utf-8")

    def lines(self) -> list:
        """Each paragraph's own line height and rule in the copy's body: (line, rule) or None."""
        out = []
        for p in docx_word.PARAGRAPH.findall(self.part("word/document.xml")):
            m = re.match(r"<w:p\b[^>]*>(<w:pPr>.*?</w:pPr>)", p, re.S)
            sp = re.search(r"<w:spacing\b[^>]*>", m.group(1).split("<w:rPr", 1)[0]) if m else None
            out.append((re.search(r'w:line="(\d+)"', sp.group(0)).group(1), re.search(r'w:lineRule="(\w+)"', sp.group(0)).group(1))
                       if sp and "w:line=" in sp.group(0) else None)
        return out

    def test_every_text_line_is_exact_at_libreoffices_height(self):
        self.assertAlmostEqual(SHARE, docx_word.single_line(), places=6)  # read from the shipped font file, as the renderer reads it
        got = self.lines()
        self.assertEqual(("230", "exact"), got[0])  # an unnamed rule keeps its value: LibreOffice read it as exact
        self.assertEqual((str(round(SHARE * 180 * 264 / 240)), "exact"), got[1])  # 1.1 of LibreOffice's 9 pt line
        self.assertEqual((str(round(SHARE * 240)), "exact"), got[2])  # single: the largest size on it, 12 pt
        self.assertEqual((str(round(SHARE * 180)), "exact"), got[3])  # no size of its own: the default, 9 pt
        self.assertEqual(("20", "exact"), got[4])  # exact already: kept
        self.assertIsNone(got[5])  # a picture keeps its own height: an exact line would cut it
        self.assertEqual((str(round(SHARE * 180)), "exact"), got[6])  # an empty paragraph: one line of the default size
        self.assertEqual((str(round(SHARE * 160)), "exact"), got[7])  # the paragraph's own spacing, not the mark's letter spacing
        body = self.part("word/document.xml")
        self.assertIn('<w:spacing w:line="191" w:lineRule="exact"/><w:jc w:val="both"/>', body)  # before w:jc, where the schema puts it
        self.assertEqual(2, body.count('<w:spacing w:val="-4"/>'))  # the letter spacing stays, in the mark and in the run
        self.assertIn(f'w:line="{round(SHARE * 150)}" w:lineRule="exact"', self.part("word/footer1.xml"))  # a footer's line too
        styles = self.part("word/styles.xml")
        self.assertIn('<w:spacing w:line="300" w:lineRule="exact"/>', styles)  # a style's unnamed rule
        self.assertIn('w:line="240" w:lineRule="auto"', styles)  # and a style's own auto rule stays: paragraphs carry their own heights

    def test_pretendard_is_embedded_and_turns_back_into_the_shipped_files(self):
        table = self.part("word/fontTable.xml")
        self.assertRegex(table, r'<w:font w:name="Pretendard"><w:charset w:val="81"/><w:family w:val="swiss"/><w:pitch w:val="variable"/>'
                                r'<w:embedRegular r:id="[^"]+" w:fontKey="\{[0-9A-F-]{36}\}"/><w:embedBold r:id="[^"]+" w:fontKey="\{[0-9A-F-]{36}\}"/></w:font></w:fonts>')
        rels = self.part("word/_rels/fontTable.xml.rels")
        with zipfile.ZipFile(self.out) as z:
            for kind, font in docx_word.FONTS:  # each face, through its relationship
                rid, key = re.search(rf'<w:{kind} r:id="([^"]+)" w:fontKey="([^"]+)"/>', table).groups()
                target = re.search(rf'Id="{rid}"[^>]*Target="([^"]+)"', rels).group(1)
                data = z.read("word/" + target)
                self.assertNotEqual(font.read_bytes()[:32], data[:32])  # obfuscated, as the standard asks
                self.assertEqual(font.read_bytes(), docx_word.obfuscate(data, key))  # and undone, the font itself
        self.assertIn('<w:displayBackgroundShape/><w:embedTrueTypeFonts/><w:evenAndOddHeaders', self.part("word/settings.xml"))  # in the schema's order
        self.assertIn('Extension="odttf"', self.part("[Content_Types].xml"))

    def test_the_title_and_author_are_the_pdfs(self):
        core = self.part("docProps/core.xml")
        self.assertIn("<dc:title>홍길동 이력서 &amp; 포트폴리오</dc:title>", core)  # escaped
        self.assertIn("<dc:creator>홍길동</dc:creator>", core)
        self.assertIn("<cp:lastModifiedBy>홍길동</cp:lastModifiedBy>", core)  # added where it was missing
        self.assertNotIn("Un-named", core)

    def test_every_part_is_well_formed_and_the_read_back_passes(self):
        with zipfile.ZipFile(self.out) as z:
            for name in z.namelist():
                if name.endswith((".xml", ".rels")):
                    ET.fromstring(z.read(name))  # raises on broken XML
            self.assertEqual("[Content_Types].xml", z.namelist()[0])  # still first
        self.assertEqual([], docx_word.problems(self.out, "홍길동 이력서 & 포트폴리오", "홍길동"))

    def test_the_same_source_gives_the_same_bytes_and_stays_as_it_was(self):
        before = self.src.read_bytes()
        again = self.dir / "again.docx"
        docx_word.ready(self.src, again, "홍길동 이력서 & 포트폴리오", "홍길동")
        self.assertEqual(self.out.read_bytes(), again.read_bytes())  # the keys come from the source, the dates from its parts
        self.assertEqual(before, self.src.read_bytes())  # the source untouched

    def test_the_read_back_finds_planted_defects(self):
        self.assertTrue(docx_word.problems(self.out, "Another title", "홍길동"))  # not the PDF's title
        broken = self.dir / "broken.docx"
        with zipfile.ZipFile(self.out) as zin, zipfile.ZipFile(broken, "w") as zout:  # a line put back to Word's own height
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == "word/document.xml":
                    data = data.replace(b'w:line="230" w:lineRule="exact"', b'w:line="230"', 1)
                if info.filename == "word/fonts/offerowl1.odttf":  # the regular face damaged
                    data = data[:100] + bytes([data[100] ^ 0xFF]) + data[101:]
                zout.writestr(info, data)
        bad = docx_word.problems(broken, "홍길동 이력서 & 포트폴리오", "홍길동")
        self.assertTrue(any("no rule" in b for b in bad), bad)  # the line Word would read as auto
        self.assertTrue(any("embedRegular does not turn back" in b for b in bad), bad)  # the damaged face
        self.assertTrue(docx_word.problems(self.src, "홍길동 이력서", "홍길동"))  # the source itself is not Word-ready

    def test_a_file_that_is_not_a_docx_is_refused(self):
        bad = self.dir / "bad.docx"
        bad.write_bytes(b"PK not really")
        with self.assertRaises(ValueError):
            docx_word.ready(bad, self.dir / "out.docx", "t", "a")


class PageLinks(unittest.TestCase):
    """Each page's size and links, read with the standard library, as a reader shows the page."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-links-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))

    def test_links_from_the_top_left_of_each_page(self):
        for indirect in (False, True):  # the action inside the annotation, or an object of its own
            pages = pdfmeta.page_links(deck_pdf(self.dir / "d.pdf", DECK, indirect))
            self.assertEqual([(192, 108), (192, 108), (108, 108)], [(p["width"], p["height"]) for p in pages])
            self.assertEqual({"uri": "mailto:gildong@example.com", "x0": 100, "y0": 60, "x1": 180, "y1": 70}, pages[0]["links"][0])
            self.assertEqual(["https://github.com/example-gildong"], [link["uri"] for link in pages[0]["links"][1:]])
            self.assertEqual([], pages[1]["links"])
            self.assertEqual("https://example.com/a?b=1&c=2", pages[2]["links"][0]["uri"])

    def test_a_tree_of_nodes_inherited_boxes_a_crop_box_and_a_turned_page(self):
        objects = ["<< /Type /Catalog /Pages 2 0 R >>",
                   "<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 3 /MediaBox [0 0 300 200] >>",  # the box, given to every page under it
                   "<< /Type /Pages /Parent 2 0 R /Kids [4 0 R 5 0 R] /Count 2 >>",
                   "<< /Type /Page /Parent 3 0 R /Annots 7 0 R >>",  # its annotations as an array object of their own
                   "<< /Type /Page /Parent 3 0 R /CropBox [50 20 250 180] /Annots [8 0 R] >>",  # a reader shows the crop box
                   "<< /Type /Page /Parent 2 0 R /Rotate 90 /Annots [8 0 R] >>",  # turned: its links are left out
                   "[8 0 R]",
                   "<< /Type /Annot /Subtype /Link /Rect [60 150 160 170] /A << /S /URI /URI <68747470733a2f2f6578616d706c652e636f6d> >> >>"]  # a hex address
        write_file(self.dir / "t.pdf", objects, "<< /Size 9 /Root 1 0 R >>")
        pages = pdfmeta.page_links(self.dir / "t.pdf")
        self.assertEqual([(300, 200), (200, 160), (300, 200)], [(p["width"], p["height"]) for p in pages])  # in the tree's order
        self.assertEqual({"uri": "https://example.com", "x0": 60, "y0": 30, "x1": 160, "y1": 50}, pages[0]["links"][0])
        self.assertEqual({"uri": "https://example.com", "x0": 10, "y0": 10, "x1": 110, "y1": 30}, pages[1]["links"][0])  # from the crop box's corner
        self.assertEqual([], pages[2]["links"])

    def test_objects_packed_in_a_compressed_stream_and_a_cross_reference_stream(self):
        packed = [b"<< /Type /Annot /Subtype /Link /Rect [10 10 90 30] /A 6 0 R >>", b"<< /S /URI /URI (mailto:gildong@example.com) >>"]  # objects 5 and 6
        head, body = b"", b""
        for num, obj in zip((5, 6), packed):  # the stream's table: number and offset, then the objects
            head += b"%d %d " % (num, len(body))
            body += obj + b" "
        data = zlib.compress(head + body)
        stream_head = ("4 0 obj\n<< /Type /ObjStm /N 2 /First %d /Filter /FlateDecode /Length %d >>\nstream\n" % (len(head), len(data))).encode()  # the packed objects' stream
        raw = (b"%PDF-1.5\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
               b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Annots [5 0 R] >>\nendobj\n"
               + stream_head + data + b"\nendstream\nendobj\n"
               b"7 0 obj\n<< /Type /XRef /Root 1 0 R /Size 8 /W [1 2 1] /Length 0 >>\nstream\n\nendstream\nendobj\nstartxref\n0\n%%EOF\n")  # no classic trailer
        (self.dir / "s.pdf").write_bytes(raw)
        self.assertEqual([{"width": 200, "height": 100, "links": [{"uri": "mailto:gildong@example.com", "x0": 10, "y0": 70, "x1": 90, "y1": 90}]}],
                         pdfmeta.page_links(self.dir / "s.pdf"))

    def test_a_file_with_no_page_tree_gives_nothing(self):
        (self.dir / "x.pdf").write_bytes(b"%PDF-1.4\nnothing here\n%%EOF\n")
        self.assertEqual([], pdfmeta.page_links(self.dir / "x.pdf"))


class PowerPointCopy(unittest.TestCase):
    """The deck as PowerPoint: a slide per page with its picture, its links where they were, its words as the description."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-pptx-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))
        self.pdf = deck_pdf(self.dir / "deck.pdf", DECK)
        self.pptx = self.dir / "deck.pptx"
        self.n = deck_pptx.make(self.pdf, self.pptx, "홍길동 포트폴리오", "홍길동", pictures=self.pictures, text=lambda _p: WORDS)

    def pictures(self, pdf, folder):  # the pages drawn at 192 dpi, as a reader would
        return [png(folder / f"page-{i}.png", round(w * deck_pptx.DPI / 72), round(h * deck_pptx.DPI / 72)) for i, (w, h, _, _) in enumerate(DECK, 1)]

    def part(self, name: str) -> str:
        with zipfile.ZipFile(self.pptx) as z:
            return z.read(name).decode("utf-8")

    def test_one_slide_per_page_the_size_of_the_first(self):
        self.assertEqual(3, self.n)
        self.assertEqual(3, len(re.findall(r"<p:sldId ", self.part("ppt/presentation.xml"))))
        self.assertIn(f'<p:sldSz cx="{192 * 12700}" cy="{108 * 12700}"/>', self.part("ppt/presentation.xml"))  # 192 x 108 pt
        first = self.part("ppt/slides/slide1.xml")
        self.assertIn(f'<a:off x="0" y="0"/><a:ext cx="{192 * 12700}" cy="{108 * 12700}"/>', first)  # the picture fills the slide
        square = self.part("ppt/slides/slide3.xml")
        self.assertIn(f'<a:off x="{(192 - 108) * 12700 // 2}" y="0"/><a:ext cx="{108 * 12700}" cy="{108 * 12700}"/>', square)  # fitted and centred

    def test_the_links_are_clickable_where_the_page_has_them(self):
        slide, rels = self.part("ppt/slides/slide1.xml"), self.part("ppt/slides/_rels/slide1.xml.rels")
        shapes = re.findall(r"<p:sp>.*?</p:sp>", slide, re.S)
        self.assertEqual(2, len(shapes))  # one per link
        rid = re.search(r'<a:hlinkClick r:id="([^"]+)"/>', shapes[0]).group(1)
        self.assertRegex(rels, rf'Id="{rid}" Type="[^"]+/hyperlink" Target="mailto:gildong@example.com" TargetMode="External"')
        self.assertIn(f'<a:off x="{100 * 12700}" y="{60 * 12700}"/><a:ext cx="{80 * 12700}" cy="{10 * 12700}"/>', shapes[0])  # from the page's corner
        self.assertIn('<a:solidFill><a:srgbClr val="FFFFFF"><a:alpha val="0"/></a:srgbClr></a:solidFill><a:ln><a:noFill/></a:ln>', shapes[0])  # clickable, unseen
        self.assertIn('Target="https://example.com/a?b=1&amp;c=2"', self.part("ppt/slides/_rels/slide3.xml.rels"))  # escaped in the part
        self.assertNotIn("<p:sp>", self.part("ppt/slides/slide2.xml"))  # a page with no link has none

    def test_each_picture_says_its_pages_words_and_the_file_its_title(self):
        self.assertEqual(["PORTFOLIO Gildong Hong", "OVERVIEW", ""], deck_pptx.described(self.pptx))  # one line each
        core = self.part("docProps/core.xml")
        self.assertIn("<dc:title>홍길동 포트폴리오</dc:title>", core)
        self.assertIn("<dc:creator>홍길동</dc:creator>", core)
        self.assertEqual("x " * 1999 + "x", deck_pptx.alt_text("x " * 2500)[:3999])  # a long page is cut at a word
        self.assertLessEqual(len(deck_pptx.alt_text("x " * 2500)), deck_pptx.ALT_MAX)

    def test_every_part_is_well_formed_and_the_read_back_passes(self):
        with zipfile.ZipFile(self.pptx) as z:
            self.assertEqual("[Content_Types].xml", z.namelist()[0])  # first, as some readers want
            for name in z.namelist():
                if name.endswith((".xml", ".rels")):
                    ET.fromstring(z.read(name))  # raises on broken XML
            self.assertEqual(3, len([n for n in z.namelist() if n.startswith("ppt/media/") and z.getinfo(n).compress_type == zipfile.ZIP_STORED]))  # pictures stored
        self.assertEqual([], deck_pptx.problems(self.pptx, self.pdf, "홍길동 포트폴리오", "홍길동", WORDS.split("\f")))

    def test_the_read_back_finds_a_moved_link_a_wrong_picture_and_another_title(self):
        broken = self.dir / "broken.pptx"
        with zipfile.ZipFile(self.pptx) as zin, zipfile.ZipFile(broken, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == "ppt/slides/_rels/slide1.xml.rels":  # a link that goes elsewhere
                    data = data.replace(b"mailto:gildong@example.com", b"mailto:someone@example.com")
                if info.filename == "ppt/media/page2.png":  # a picture of the wrong size
                    data = png(self.dir / "small.png", 10, 10).read_bytes()
                zout.writestr(info, data)
        bad = deck_pptx.problems(broken, self.pdf, "Another", "홍길동", WORDS.split("\f"))
        self.assertTrue(any("slide 1's links" in b for b in bad), bad)
        self.assertTrue(any("slide 2's picture is 10 x 10" in b for b in bad), bad)
        self.assertTrue(any("title" in b for b in bad), bad)
        self.assertTrue(deck_pptx.problems(self.pptx, deck_pdf(self.dir / "two.pdf", DECK[:2]), "홍길동 포트폴리오", "홍길동"))  # three slides for two pages

    def test_a_page_that_was_not_drawn_stops_it(self):
        with self.assertRaises(ValueError):
            deck_pptx.make(self.pdf, self.dir / "x.pptx", "t", "a", pictures=lambda p, f: self.pictures(p, f)[:2], text=lambda _p: WORDS)

    @unittest.skipUnless(pdftools.reader(), "no PDF reader on this PC (poppler or pypdfium2)")
    def test_with_this_pcs_reader(self):
        out = self.dir / "real.pptx"
        self.assertEqual(3, deck_pptx.make(self.pdf, out, "홍길동 포트폴리오", "홍길동"))  # the pages drawn and read here
        self.assertEqual([], deck_pptx.problems(out, self.pdf, "홍길동 포트폴리오", "홍길동", pdftools.text(self.pdf).split("\f")))
        self.assertEqual("PORTFOLIO Gildong Hong", deck_pptx.described(out)[0])


class OfficeQuestions(unittest.TestCase):
    """Word and PowerPoint asked through PowerShell, which is stood in for: no Office program runs."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-office-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))
        self.doc = make_docx(self.dir / "r.docx")  # a file to ask about
        self.calls, self.ended = [], []  # what PowerShell was handed; which processes were ended
        for p in (mock.patch.object(office_check, "powershell", return_value="powershell.exe"),  # a Windows PC, as far as these tests know
                  mock.patch.object(office_check, "_temp", return_value=("C:\\T", self.dir)),  # Windows' temporary folder: this test's
                  mock.patch.object(office_check, "_end", side_effect=lambda pids, exe, wait=15: self.ended.append((pids, exe))),
                  mock.patch.dict(os.environ, {"OFFEROWL_OFFICE": ""}), mock.patch.dict(office_check._AVAILABLE, {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def answer(self, out: str = "", err: str = "", rc: int = 0, hang: bool = False):
        """A stand-in for subprocess.run that records the script and answers as PowerShell would."""
        def fake(argv, **kw):
            if "-File" in argv:  # a question about a file: its script and the copy, as Windows would read them
                folder = self.dir / pathlib.PureWindowsPath(argv[argv.index("-File") + 1]).parent.name  # the question's folder, here
                self.calls.append({"argv": argv, "script": (folder / "ask.ps1").read_text(encoding="utf-8-sig"), "copy": (folder / pathlib.PureWindowsPath(argv[-1]).name).read_bytes()})
            else:  # a one-line command: is Office registered
                self.calls.append({"argv": argv})
            if hang:  # it ran over, after naming the process it started
                raise subprocess.TimeoutExpired(argv, kw.get("timeout"), output=out.encode())
            return subprocess.CompletedProcess(argv, rc, out.encode(), err.encode())
        return mock.patch.object(office_check.subprocess, "run", side_effect=fake)

    def test_word_is_asked_about_a_copy_read_only_and_its_pages_read(self):
        with self.answer("started=4242\r\npages=3\r\nquit=1\r\n"):
            self.assertEqual(3, office_check.count("word", self.doc))
        call = self.calls[0]
        self.assertEqual(self.doc.read_bytes(), call["copy"])  # the file itself, under a plain name
        self.assertTrue(call["argv"][-1].startswith("C:\\T\\offerowl_word_") and call["argv"][-1].endswith("\\in.docx"))  # an ASCII folder of its own
        self.assertIn("New-Object -ComObject Word.Application", call["script"])
        self.assertIn("$app.Visible = $false", call["script"])  # never shown
        self.assertIn("Documents.Open($In, $false, $true, $false)", call["script"])  # read-only, not in the recent files
        self.assertIn("ComputeStatistics(2)", call["script"])  # pages
        self.assertIn("-match 'Embedding'", call["script"])  # only a program started for automation is named
        self.assertEqual([([4242], "WINWORD.EXE")], self.ended)  # what it started is never left behind
        self.assertEqual([], [p for p in self.dir.iterdir() if p.name.startswith("offerowl_")])  # its folder is gone

    def test_a_program_the_person_has_open_is_kept(self):
        with self.answer("started=\r\nslides=13\r\nkept=1\r\n"):  # PowerPoint, already open with the person's own file
            self.assertEqual(13, office_check.count("powerpoint", self.doc))
        self.assertIn("Presentations.Open($In, -1, 0, 0)", self.calls[0]["script"])  # read-only, no window
        self.assertIn('else { "kept=1" }', self.calls[0]["script"])  # it quits only when nothing else is open
        self.assertEqual([], self.ended)  # nothing of the person's is ended

    def test_a_question_that_hangs_or_fails_ends_what_it_started_and_says_so(self):
        with self.answer("started=777\r\n", hang=True):
            with self.assertRaises(office_check.OfficeFailed):
                office_check.count("word", self.doc)
        self.assertEqual([([777], "WINWORD.EXE")], self.ended)  # the invisible program it started
        with self.answer("started=778\r\n", "Exception calling Open: the file is damaged\r\n", rc=1):
            with self.assertRaises(office_check.OfficeFailed) as cm:
                office_check.count("powerpoint", self.doc)
        self.assertIn("the file is damaged", str(cm.exception))  # the reason, for the log
        self.assertEqual(([778], "POWERPNT.EXE"), self.ended[-1])

    def test_whether_office_is_there_is_asked_once_and_can_be_turned_off(self):
        with self.answer("True\r\n"):
            self.assertTrue(office_check.available("word"))
            self.assertTrue(office_check.available("word"))  # asked once
        self.assertEqual(1, len([c for c in self.calls]))
        self.assertIn("Word.Application", self.calls[0]["argv"][-1])  # its COM registration
        with mock.patch.dict(os.environ, {"OFFEROWL_OFFICE": "0"}):  # turned off: nothing is asked
            self.assertFalse(office_check.available("powerpoint"))
        self.assertEqual(1, len(self.calls))

    def test_a_pc_with_no_windows_reaches_no_office(self):
        with mock.patch.object(office_check, "powershell", return_value=None), self.answer("True"):
            self.assertFalse(office_check.available("word"))
            with self.assertRaises(office_check.OfficeFailed):
                office_check.count("word", self.doc)
        self.assertEqual([], self.calls)  # nothing started


if __name__ == "__main__":
    unittest.main()
