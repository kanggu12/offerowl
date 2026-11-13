# -*- coding: utf-8 -*-
"""A Word-ready copy of a DOCX Offerowl typeset (the resume, the cover letter): the pages Word lays out are the PDF's.

The DOCX that src/layout.js writes is also what LibreOffice, or the browser through src/render_html, prints the PDF from.
Word reads two things in it otherwise, and the copy that goes to the Desktop fixes both:

- Line heights. The docx package writes a paragraph's w:line with no w:lineRule. LibreOffice 7.4 reads that as an exact
  height in twips at every font size (docs/ARCHITECTURE.md, "LibreOffice's rules, measured"; src/render_html/docx2html.py
  reads it the same way), and the layouts were tuned on that reading. Word reads the rule the standard gives when it is
  left out, auto: 240ths of its own single line. And the two single lines differ: a test document set in Pretendard at
  7 to 22 pt gave lines 1.19 times the size in LibreOffice (the font's typographic ascent and descent, (1949 + 494) / 2048)
  and 1.55 times in Word, so each single-spaced paragraph sat taller in Word and a page of the resume ended 37pt lower.
  Spacing between paragraphs (the larger of after and before) and exact heights came out the same in both. So the copy
  makes every text line exact at LibreOffice's height: a w:line with no rule keeps its value, an auto one becomes that
  share of LibreOffice's single line, and a paragraph with no w:line gets LibreOffice's single line, all for the
  paragraph's largest size (src/render_html/fonts.py reads the metrics LibreOffice uses from the font file). A paragraph
  that holds a picture keeps its own lines, so the picture is never cut, and so do exact and at-least lines.
- The font. The file names Pretendard and holds none of it, and a PC without Pretendard sets the text in another font:
  Word on Windows took Batang and Cambria, and lines broke elsewhere. The copy embeds Pretendard's regular and bold faces
  as ECMA-376 Part 1 (17.8.1) describes: each font file obfuscated with a key of its own, named in the font table, and
  settings.xml asks Word to keep them when the file is saved again. The whole fonts go in, so letters typed into the file
  later look the same. Pretendard is under the SIL Open Font License 1.1, which allows embedding a font in a document
  (fonts/Pretendard-LICENSE.txt), and its files allow installable embedding (OS/2 fsType 0).

The title and the author are set to the PDF's own (docProps/core.xml), so both files show the same in a title bar. The
same source gives the same bytes: the keys come from the source's hash, and new parts carry the date of the old ones.
The source is never changed.

    python3 src/docx_word.py in.docx out.docx "Title" "Author"
"""
import hashlib  # the fonts' keys, from the source's own bytes
import importlib.util  # the renderer's font reader, under its private name
import pathlib  # the files
import re  # the parts are rewritten as text, like the rest of Offerowl's DOCX code
import sys  # the command line
import zipfile  # a DOCX is a zip of XML parts

ROOT = pathlib.Path(__file__).resolve().parent.parent  # the repository (or the app's bundle)
FAMILY = "Pretendard"  # the one family the resume and the cover letter name (layout.js, cover_form.js)
FONTS = (("embedRegular", ROOT / "fonts" / "Pretendard-Regular.ttf"),  # plain text
         ("embedBold", ROOT / "fonts" / "Pretendard-Bold.ttf"))  # bold text, which every resume has: Word would thicken the regular face without it
REL_FONT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"  # a font part's relationship
ODTTF = "application/vnd.openxmlformats-officedocument.obfuscatedFont"  # an obfuscated font part's content type
NEEDED = ("word/document.xml", "word/fontTable.xml", "word/settings.xml", "docProps/core.xml", "[Content_Types].xml")  # the parts the copy rewrites
# settings.xml children that the schema puts before w:embedTrueTypeFonts (CT_Settings); the switch goes after the last one there
SETTINGS_BEFORE = ("writeProtection", "view", "zoom", "removePersonalInformation", "removeDateAndTime", "doNotDisplayPageBoundaries",
                   "displayBackgroundShape", "printPostScriptOverText", "printFractionalCharacterWidth", "printFormsData")
# w:pPr children that the schema puts after w:spacing (CT_PPrBase, then CT_PPr): a new w:spacing goes before the first of them
PPR_AFTER = ("ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment", "textboxTightWrap",
             "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")
BARE_LINE = re.compile(r'<w:spacing\b(?=[^>]*\sw:line=")(?![^>]*\sw:lineRule=)([^>]*?)(/?)>')  # a w:spacing with a w:line and no rule
PARAGRAPH = re.compile(r"<w:p\b[^>]*/>|<w:p\b[^>]*>.*?</w:p>", re.S)  # one paragraph (\b keeps w:pPr, w:pStyle and w:pict out)
PICTURE = re.compile(r"<w:drawing\b|<w:pict\b|<w:object\b|<w:txbxContent\b|<mc:AlternateContent\b")  # what a line must never cut, or a paragraph inside it
STORIES = re.compile(r"^word/(?:document|header\d*|footer\d*)\.xml$")  # the parts whose paragraphs are printed on the page


def _fonts():
    """src/render_html/fonts.py under the private name the renderer gives it, so both read a font file the same way."""
    key = "offerowl_fonts"  # the renderer's own name for it
    if key not in sys.modules:  # loaded once, shared with the renderer
        spec = importlib.util.spec_from_file_location(key, ROOT / "src" / "render_html" / "fonts.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[key]


def single_line() -> float:
    """LibreOffice's single line of Pretendard, as a share of its size: the ascent and descent it takes from the font
    file (the typographic ones, which the font asks for), 1.19 for the shipped files."""
    info = _fonts().read_font(FONTS[0][1])  # the regular face: the bold one has the same metrics
    return (info["asc"] + info["desc"]) / float(info["upm"])


def font_key(source: bytes, kind: str) -> str:
    """The GUID that obfuscates one font of one file, in the font table's form ({8-4-4-4-12}, upper case): from the
    source's bytes, so the same file always gets the same copy."""
    h = hashlib.sha256(source + kind.encode("ascii")).hexdigest().upper()[:32]  # 128 bits of the hash
    return "{%s-%s-%s-%s-%s}" % (h[:8], h[8:12], h[12:16], h[16:20], h[20:32])  # grouped as a GUID is written


def obfuscate(data: bytes, key: str) -> bytes:
    """ECMA-376's font obfuscation, which undoes itself: the GUID's 16 bytes, read from its last hex pair to its first,
    XORed over the font's first 32 bytes."""
    k = bytes.fromhex(key.strip("{}").replace("-", ""))[::-1]  # the key's bytes in reverse order
    return bytes(b ^ k[i % 16] for i, b in enumerate(data[:32])) + data[32:]  # the rest of the font stays as it is


def bare_exact(xml: str) -> str:
    """Every w:line that names no rule, which LibreOffice reads as an exact height, made exact for Word too."""
    return BARE_LINE.sub(lambda m: f'<w:spacing{m.group(1)} w:lineRule="exact"{m.group(2)}>', xml)  # the same value, now with its rule


def _set_line(spacing: str, twips: int) -> str:
    """A w:spacing element with this exact line height, its other values (before, after) kept."""
    kept = re.sub(r'\s+w:line(?:Rule)?="[^"]*"', "", spacing)  # the old line and rule go
    return re.sub(r"^<w:spacing\b", f'<w:spacing w:line="{twips}" w:lineRule="exact"', kept, count=1)  # the new ones first


def word_lines(xml: str, default_size: int = 18, single: float | None = None) -> str:
    """A story part (the body, a header, a footer) with every text line at LibreOffice's exact height: a w:line with no
    rule keeps its value, an auto w:line becomes its share of LibreOffice's single line, and a paragraph with no w:line gets
    that single line, for the paragraph's largest size in half-points (default_size where it names none). A paragraph
    with a picture keeps its own lines apart from the first rule; exact and at-least lines stay."""
    share = single_line() if single is None else single  # LibreOffice's single line, as a share of the size

    def one(m):  # one paragraph
        p = bare_exact(m.group(0))  # an unnamed rule is exact in LibreOffice, picture or not
        if PICTURE.search(p):  # a picture, a text box, an object: its own height stays
            return p
        if "</w:p>" not in p:  # an empty paragraph, <w:p/>: one line of the default size
            return p[:-2] + f'><w:pPr><w:spacing w:line="{round(share * default_size * 10)}" w:lineRule="exact"/></w:pPr></w:p>'
        head = re.match(r"<w:p\b[^>]*>", p).group(0)  # the paragraph's own tag
        ppr = re.match(r"<w:pPr>(.*?)</w:pPr>|<w:pPr/>", p[len(head):], re.S)  # its properties, which come first
        body = (ppr.group(1) or "") if ppr else ""  # their inside
        runs = p[len(head) + (ppr.end() if ppr else 0):]  # the runs, after the properties
        sizes = [int((re.search(r'<w:sz w:val="(\d+)"', r) or [None, default_size])[1])  # each run that prints letters, at its own size or the default
                 for r in re.findall(r"<w:r\b[^>]*>.*?</w:r>", runs, re.S) if re.search(r"<w:t\b|<w:tab\b|<w:sym\b", r)]
        mark = re.search(r'<w:sz w:val="(\d+)"', body)  # the paragraph mark's size, which an empty paragraph is as tall as
        size = max(sizes) if sizes else int(mark.group(1)) if mark else default_size  # the tallest letters decide a line in LibreOffice
        own = body.split("<w:rPr", 1)[0]  # before the paragraph mark's run properties: a run's w:spacing is letter spacing
        sp = re.search(r"<w:spacing\b[^>]*>", own)  # the paragraph's spacing, if it has one
        if sp and re.search(r'w:lineRule="(?:exact|atLeast)"', sp.group(0)):  # a fixed or a minimum height: kept
            return p
        line = re.search(r'\sw:line="(\d+)"', sp.group(0)) if sp else None  # an auto rule's 240ths of a line
        twips = round(share * size * 10 * (int(line.group(1)) / 240.0 if line else 1.0))  # half-points to twips: x 10
        if sp:  # the spacing there, with its new line
            new_body = own.replace(sp.group(0), _set_line(sp.group(0), twips), 1) + body[len(own):]
        else:  # a w:spacing of its own, where the schema puts it
            tag = f'<w:spacing w:line="{twips}" w:lineRule="exact"/>'
            at = min([re.search(r"<w:" + t + r"\b", body).start() for t in PPR_AFTER if re.search(r"<w:" + t + r"\b", body)] or [len(body)])  # before what follows it
            new_body = body[:at] + tag + body[at:]
        return head + "<w:pPr>" + new_body + "</w:pPr>" + runs
    return PARAGRAPH.sub(one, xml)


def default_size(styles: str) -> int:
    """The document's default size in half-points (styles.xml's w:docDefaults), 20 (10 pt) when it names none."""
    m = re.search(r"<w:rPrDefault>.*?<w:sz w:val=\"(\d+)\"", styles, re.S)  # the default run properties' size
    return int(m.group(1)) if m else 20  # Word's own default otherwise


def font_table(xml: str, embeds: list) -> str:
    """The font table with Pretendard's entry and its embedded faces. The docx package writes an empty table; an entry
    for Pretendard already there is replaced, so the faces are named once."""
    parts = "".join(f'<w:{kind} r:id="{rid}" w:fontKey="{key}"/>' for kind, rid, key in embeds)  # one per face, after pitch as the schema orders them
    entry = (f'<w:font w:name="{FAMILY}"><w:charset w:val="81"/><w:family w:val="swiss"/><w:pitch w:val="variable"/>'  # Hangul, sans serif, proportional
             + parts + "</w:font>")
    xml = re.sub(r'<w:font\b[^>]*\bw:name="' + FAMILY + r'"[^>]*?(?:/>|>.*?</w:font>)', "", xml, flags=re.S)  # an entry already there goes
    m = re.search(r"<w:fonts\b[^>]*?(/?)>", xml)  # the table itself
    if not m:  # not a font table
        raise ValueError("fontTable.xml has no w:fonts")
    if m.group(1):  # an empty table, <w:fonts .../>
        return xml[:m.start()] + m.group(0)[:-2] + ">" + entry + "</w:fonts>" + xml[m.end():]
    return xml.replace("</w:fonts>", entry + "</w:fonts>", 1)  # after the entries there


def settings(xml: str) -> str:
    """settings.xml with w:embedTrueTypeFonts, in its place in the schema's order, so Word keeps the fonts on saving."""
    if "<w:embedTrueTypeFonts" in xml:  # already asked
        return xml
    at = None  # where the switch goes: after the last element the schema puts before it
    for name in SETTINGS_BEFORE:  # in the schema's order
        m = None
        for m in re.finditer(r"<w:" + name + r"\b(?:[^>]*/>|[^>]*>.*?</w:" + name + ">)", xml, re.S):  # the element, empty or not
            pass  # the last one of that name
        if m:
            at = m.end()
    if at is None:  # none of them: right after the opening tag
        m = re.search(r"<w:settings\b[^>]*>", xml)
        if not m:  # not a settings part
            raise ValueError("settings.xml has no w:settings")
        at = m.end()
    return xml[:at] + "<w:embedTrueTypeFonts/>" + xml[at:]


def escape(text: str) -> str:
    """Text for an XML element."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def core(xml: str, title: str, author: str) -> str:
    """docProps/core.xml with the PDF's title and author (and the author as the last to change it)."""
    for tag, value in (("dc:title", title), ("dc:creator", author), ("cp:lastModifiedBy", author)):  # what a title bar and File > Info show
        new = f"<{tag}>{escape(value)}</{tag}>"  # the element with its value
        if re.search(rf"<{tag}\b[^>]*/>|<{tag}\b[^>]*>.*?</{tag}>", xml, re.S):  # there, empty or not: replaced
            xml = re.sub(rf"<{tag}\b[^>]*/>|<{tag}\b[^>]*>.*?</{tag}>", lambda _m: new, xml, count=1, flags=re.S)
        else:  # missing: added at the end
            xml = xml.replace("</cp:coreProperties>", new + "</cp:coreProperties>", 1)
    return xml


def ready(src, dst, title: str, author: str) -> None:
    """Write the Word-ready copy of src to dst (the line rules, the embedded fonts, the title and the author). src stays as
    it was. Raises ValueError for a file that is not a DOCX of this shape."""
    raw = pathlib.Path(src).read_bytes()  # the source, whole: its hash makes the keys
    try:
        zin = zipfile.ZipFile(pathlib.Path(src))  # its parts
    except zipfile.BadZipFile as exc:  # not a zip at all
        raise ValueError("not a DOCX") from exc
    with zin:
        names = zin.namelist()  # in the order they were written: [Content_Types].xml stays where it was
        missing = [n for n in NEEDED if n not in names]  # a part the copy must rewrite
        if missing:
            raise ValueError("not a DOCX of this shape: no " + ", ".join(missing))
        when = zin.getinfo("word/document.xml").date_time  # the new parts' date: the same copy for the same source
        embeds = [(kind, f"rIdOfferowlFont{i + 1}", font_key(raw, kind)) for i, (kind, _) in enumerate(FONTS)]  # (face, relationship, key)
        fonts = {f"word/fonts/offerowl{i + 1}.odttf": obfuscate(path.read_bytes(), embeds[i][2]) for i, (_, path) in enumerate(FONTS)}  # the obfuscated files
        rels_name = "word/_rels/fontTable.xml.rels"  # the font table's relationships
        rels = zin.read(rels_name).decode("utf-8") if rels_name in names else \
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'  # none yet
        rels = re.sub(r"<Relationships\b([^>]*?)/>", r"<Relationships\1></Relationships>", rels)  # an empty list opened up
        rels = rels.replace("</Relationships>", "".join(f'<Relationship Id="{rid}" Type="{REL_FONT}" Target="fonts/offerowl{i + 1}.odttf"/>'
                                                        for i, (_, rid, _) in enumerate(embeds)) + "</Relationships>", 1)  # one per face
        types = zin.read("[Content_Types].xml").decode("utf-8")  # what each part is
        if 'Extension="odttf"' not in types:  # the docx package names it already; another writer may not
            types = types.replace("</Types>", f'<Default ContentType="{ODTTF}" Extension="odttf"/></Types>', 1)
        out = {"word/fontTable.xml": font_table(zin.read("word/fontTable.xml").decode("utf-8"), embeds),  # the parts rewritten
               "word/settings.xml": settings(zin.read("word/settings.xml").decode("utf-8")),
               "docProps/core.xml": core(zin.read("docProps/core.xml").decode("utf-8"), title, author),
               "[Content_Types].xml": types, rels_name: rels}
        size = default_size(zin.read("word/styles.xml").decode("utf-8")) if "word/styles.xml" in names else 20  # what a run with no size of its own is
        share = single_line()  # LibreOffice's single line of the font, read once
        for n in names:  # the line heights: every printed paragraph of the body, the headers and the footers; an unnamed rule anywhere
            if not (n.startswith("word/") and n.endswith(".xml")) or n in out:  # not a part with paragraphs, or rewritten above
                continue
            xml = zin.read(n).decode("utf-8")  # the part
            if STORIES.match(n):  # printed: each line at LibreOffice's height
                out[n] = word_lines(xml, size, share)
            elif BARE_LINE.search(xml):  # a style or a list level: only its unnamed rule, which LibreOffice reads as exact
                out[n] = bare_exact(xml)
        dst = pathlib.Path(dst)  # where the copy goes
        tmp = dst.with_name(dst.name + ".part")  # written whole first
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:  # compressed: the fonts are most of the file
            def put(name, data):  # one part, dated like the source's
                info = zipfile.ZipInfo(name, date_time=zin.getinfo(name).date_time if name in names else when)
                info.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(info, data.encode("utf-8") if isinstance(data, str) else data)
            for n in names:  # the source's parts in their order (some readers want [Content_Types].xml first)
                if not n.endswith("/"):  # folders are not parts
                    put(n, out[n] if n in out else zin.read(n))
            if rels_name not in names:  # the font table had no relationships
                put(rels_name, out[rels_name])
            for n, data in fonts.items():  # the faces, last
                put(n, data)
    tmp.replace(dst)  # in place at once


def loose_lines(xml: str) -> int:
    """How many printed text paragraphs of a story part Word would still lay out at its own height: no exact or at-least
    line of their own (a paragraph with a picture keeps its lines, and is not counted)."""
    n = 0  # the paragraphs found
    for p in PARAGRAPH.findall(xml):  # each paragraph
        if PICTURE.search(p):  # its own height on purpose
            continue
        ppr = re.match(r"<w:p\b[^>]*>(<w:pPr>.*?</w:pPr>)", p, re.S)  # its properties
        own = ppr.group(1).split("<w:rPr", 1)[0] if ppr else ""  # the paragraph's, not its mark's run properties
        if not re.search(r'<w:spacing\b[^>]*w:lineRule="(?:exact|atLeast)"', own):  # no fixed height
            n += 1
    return n


def problems(path, title: str, author: str) -> list[str]:
    """The copy read back: every face named in the font table is there and turns back into Offerowl's own font file, every
    printed text line has a fixed height and no w:line is left without its rule, Word is asked to keep the fonts, and the
    title and the author are the ones given. The problems found ([] when there are none)."""
    try:
        z = zipfile.ZipFile(pathlib.Path(path))  # the copy
    except (OSError, zipfile.BadZipFile):  # not a zip
        return ["not a zip file"]
    with z:
        if z.testzip() is not None:  # a damaged part
            return ["a damaged part"]
        bad = []  # what is wrong
        table = z.read("word/fontTable.xml").decode("utf-8")  # the font table
        rels = z.read("word/_rels/fontTable.xml.rels").decode("utf-8") if "word/_rels/fontTable.xml.rels" in z.namelist() else ""
        for kind, font in FONTS:  # each face
            m = re.search(rf'<w:{kind} r:id="([^"]+)" w:fontKey="([^"]+)"/>', table)  # named in the table
            target = re.search(rf'Id="{re.escape(m.group(1))}"[^>]*Target="([^"]+)"', rels) if m else None  # and its part
            if not m or not target:
                bad.append(f"{kind} is not in the font table")
                continue
            part = "word/" + target.group(1)  # the obfuscated file
            if part not in z.namelist() or obfuscate(z.read(part), m.group(2)) != font.read_bytes():  # undone, it is the font
                bad.append(f"{kind} does not turn back into {font.name}")
        parts = [n for n in z.namelist() if n.startswith("word/") and n.endswith(".xml")]  # every XML part with paragraphs or styles
        left = sum(len(BARE_LINE.findall(z.read(n).decode("utf-8", "replace"))) for n in parts)  # a line Word would read as auto
        if left:
            bad.append(f"{left} line heights have no rule")
        loose = sum(loose_lines(z.read(n).decode("utf-8", "replace")) for n in parts if STORIES.match(n))  # a line at Word's own height
        if loose:
            bad.append(f"{loose} paragraphs have no fixed line height")
        if "<w:embedTrueTypeFonts/>" not in z.read("word/settings.xml").decode("utf-8"):  # Word would drop the fonts on saving
            bad.append("settings.xml does not keep the fonts")
        c = z.read("docProps/core.xml").decode("utf-8")  # the title and the author
        if f"<dc:title>{escape(title)}</dc:title>" not in c or f"<dc:creator>{escape(author)}</dc:creator>" not in c or not title.strip() or not author.strip():
            bad.append("the title or the author is not the PDF's")
        return bad


def main(argv=None) -> int:
    """The command line: python3 src/docx_word.py in.docx out.docx "Title" "Author" """
    a = list(sys.argv[1:] if argv is None else argv)  # the arguments
    if len(a) != 4:  # source, copy, title, author
        print('usage: docx_word.py in.docx out.docx "Title" "Author"')
        return 2
    ready(a[0], a[1], a[2], a[3])  # the copy
    bad = problems(a[1], a[2], a[3])  # read back
    print("\n".join(bad) if bad else f"Word-ready: {a[1]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
