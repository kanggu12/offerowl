"""The title and the author of a PDF, and the links on its pages, read and written with the standard library alone.

A browser prints a PDF whose title is the page's file name (owl_40352724_ko) and whose author is empty, and that title
is what a recruiter sees in the window's bar. stamp() writes the document's own title and the person's name as one
incremental update: a new information dictionary appended after the file, with a cross-reference section and a trailer
that point back to the old ones, so nothing printed is rewritten. read() gives the title and the author a reader shows.
page_links() gives each page's size and the web and mail links on it, where they are: the PowerPoint copy of a deck
puts a link at the same place (src/deck_pptx.py). add_links() puts links on page 1 as stamp() writes the title, one more
update after the file: a resume header's contacts, which LibreOffice drops from a table cell (src/resume.py).

    python3 src/pdfmeta.py read file.pdf
    python3 src/pdfmeta.py stamp file.pdf "Title" "Author"
    python3 src/pdfmeta.py links file.pdf
"""
import pathlib  # the files
import re  # the trailer's keys
import sys  # the command line
import zlib  # an object stream's compressed objects

STARTXREF = re.compile(rb"startxref\s+(\d+)\s+%%EOF\s*$")  # the last cross-reference's place, at the file's end
TRAILER = re.compile(rb"trailer\s*<<(.*?)>>\s*startxref", re.S)  # a classic trailer and its dictionary


def pdf_string(text: str) -> bytes:
    """A PDF text string: plain ASCII as a literal string, anything else (Korean) as UTF-16BE with its byte-order mark."""
    if all(32 <= ord(c) < 127 for c in text):  # plain: readable in the file
        return b"(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("ascii") + b")"
    return b"<FEFF" + text.encode("utf-16-be").hex().upper().encode("ascii") + b">"  # hex, so no byte needs escaping


def _literal(raw: bytes, i: int) -> tuple[bytes, int]:
    """The bytes of a literal string starting at raw[i] == '(', with its escapes resolved, and the index after it."""
    out, depth, i = bytearray(), 1, i + 1  # inside the first parenthesis
    esc = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b", ord("f"): b"\f", ord("("): b"(", ord(")"): b")", ord("\\"): b"\\"}
    while i < len(raw) and depth:
        c = raw[i]
        if c == ord("\\"):  # an escape
            n = raw[i + 1] if i + 1 < len(raw) else 0
            if n in esc:
                out += esc[n]; i += 2
            elif 48 <= n <= 55:  # an octal code of up to three digits
                m = re.match(rb"[0-7]{1,3}", raw[i + 1:i + 4])
                out.append(int(m.group(0), 8) & 255); i += 1 + len(m.group(0))
            else:  # a line continuation, or an unknown escape: dropped
                i += 2
            continue
        depth += c == ord("("); depth -= c == ord(")")  # nested parentheses are part of the string
        if depth:
            out.append(c)
        i += 1
    return bytes(out), i


def _text(raw: bytes) -> str:
    """A PDF string's bytes as text: UTF-16BE after its mark, else PDFDocEncoding read as Latin-1 (close enough here)."""
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    return raw.decode("latin-1")


def _value(dct: bytes, key: bytes) -> str | None:
    """The text of a string entry (/Title, /Author) in a dictionary's bytes, or None."""
    m = re.search(rb"/" + key + rb"\s*([(<])", dct)
    if not m:
        return None
    i = m.start(1)
    if dct[i:i + 1] == b"(":  # a literal string
        return _text(_literal(dct, i)[0])
    end = dct.index(b">", i)  # a hex string
    hexs = re.sub(rb"\s", b"", dct[i + 1:end])
    return _text(bytes.fromhex((hexs + b"0" * (len(hexs) % 2)).decode("ascii")))


def _last_trailer(raw: bytes) -> bytes | None:
    """The dictionary of the file's last classic trailer, or None (a file with only cross-reference streams)."""
    found = list(TRAILER.finditer(raw))
    return found[-1].group(1) if found else None


def _object(raw: bytes, num: int, gen: int) -> bytes | None:
    """The body of an object as last defined in the file (an update redefines it further down)."""
    found = list(re.finditer(rb"(?<!\d)" + str(num).encode() + rb"\s+" + str(gen).encode() + rb"\s+obj\b(.*?)endobj", raw, re.S))
    return found[-1].group(1) if found else None


STRINGS = re.compile(rb"/(?:Title|Author|Subject|Keywords|URI)\s*([(<])(?!<)")  # a text string under one of these keys (not a dictionary)


def strings(pdf) -> list:
    """Every text string under /Title, /Author, /Subject, /Keywords and /URI in the file's bytes: the information dictionary
    of every revision (an update leaves the older one in the file), the outline's entries and the links' addresses. What a
    blind edition's check reads besides the text layer. Strings inside compressed object streams are not read; Offerowl's
    printers write none."""
    raw = pathlib.Path(pdf).read_bytes()  # the file
    out = []  # the strings found
    for m in STRINGS.finditer(raw):  # each keyed string, in the file's order
        i = m.start(1)  # where it starts
        if raw[i:i + 1] == b"(":  # a literal string
            out.append(_text(_literal(raw, i)[0]))
            continue
        end = raw.find(b">", i)  # a hex string ends at the first >
        hexs = re.sub(rb"\s", b"", raw[i + 1:end]) if end > i else b""  # its digits
        try:
            out.append(_text(bytes.fromhex((hexs + b"0" * (len(hexs) % 2)).decode("ascii"))))
        except ValueError:  # not a hex string after all
            continue
    return out


def pages(pdf) -> int:
    """The page count from the page tree (the largest /Count of a /Pages node), 0 when there is none."""
    raw = pathlib.Path(pdf).read_bytes()  # the file
    counts = [int(m.group(1)) for m in re.finditer(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", raw)]  # /Type before /Count
    counts += [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", raw)]  # and after it
    return max(counts) if counts else 0


def read(pdf) -> dict:
    """{"title", "author"} as a reader shows them (None when the file does not say)."""
    raw = pathlib.Path(pdf).read_bytes()
    tr = _last_trailer(raw)
    m = re.search(rb"/Info\s+(\d+)\s+(\d+)\s+R", tr or b"")
    info = _object(raw, int(m.group(1)), int(m.group(2))) if m else None
    return {"title": _value(info, b"Title") if info else None, "author": _value(info, b"Author") if info else None}


def stamp(pdf, title: str, author: str, creator: str = "Offerowl") -> bool:
    """Write the title and the author as an incremental update. False when the file is not one this can update (no
    classic trailer at its end: a file with cross-reference streams); then it is left exactly as it was."""
    path = pathlib.Path(pdf)
    raw = path.read_bytes()
    end = STARTXREF.search(raw[-64:])  # the file must end with startxref and %%EOF
    tr = _last_trailer(raw)
    if not end or tr is None or raw[int(end.group(1)):int(end.group(1)) + 4] != b"xref":  # the last section must be a classic table
        return False
    size_m, root_m = re.search(rb"/Size\s+(\d+)", tr), re.search(rb"/Root\s+(\d+\s+\d+\s+R)", tr)  # the next free number, the catalogue
    if b"/Encrypt" in tr or not size_m or not root_m:  # an encrypted file (a new trailer would drop its key) or a trailer this cannot read
        return False  # left exactly as it was
    size = int(size_m.group(1))  # the next free object number
    root = root_m.group(1)  # the catalogue, kept
    ident = re.search(rb"/ID\s*(\[[^\]]*\])", tr)  # the file's identifier, kept
    old = re.search(rb"/Info\s+(\d+)\s+(\d+)\s+R", tr)
    info = _object(raw, int(old.group(1)), int(old.group(2))) if old else b""
    kept = re.search(rb"/CreationDate\s*(\([^)]*\))", info or b"")  # when it was printed, kept
    body = (b"<< /Title " + pdf_string(title) + b" /Author " + pdf_string(author) + b" /Creator " + pdf_string(creator)
            + (b" /CreationDate " + kept.group(1) if kept else b"") + b" >>")
    head = raw if raw.endswith(b"\n") else raw + b"\n"  # the update starts on a line of its own
    at = len(head)  # where the new object starts
    obj = str(size).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_at = at + len(obj)  # where the new cross-reference section starts
    xref = b"xref\n" + str(size).encode() + b" 1\n" + f"{at:010d} 00000 n \n".encode()  # one entry: the new object
    trailer = (b"trailer\n<< /Size " + str(size + 1).encode() + b" /Root " + root + b" /Info " + str(size).encode() + b" 0 R /Prev "
               + end.group(1) + (b" /ID " + ident.group(1) if ident else b"") + b" >>\nstartxref\n" + str(xref_at).encode() + b"\n%%EOF\n")
    tmp = path.with_name(path.name + ".meta")  # written whole, then put in place
    tmp.write_bytes(head + obj + xref + trailer)
    tmp.replace(path)
    return True


# ------------------------------------------------------------------ objects, pages and links

SPACE = b" \t\r\n\x0c\x00"  # PDF white space
NAME = re.compile(rb"/([^\s()<>\[\]{}/%]*)")  # a name runs to the next space or delimiter
NUMBER = re.compile(rb"[+-]?(?:\d+\.\d*|\.\d+|\d+)")  # an integer or a real
REF_TAIL = re.compile(rb"\s+(\d+)\s+R(?![^\s()<>\[\]{}/%])")  # after an integer: its generation and R make a reference
OBJ = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")  # where an object starts


class Name(str):
    """A PDF name (/Link), without its slash, apart from a string."""


class Ref(tuple):
    """A reference to an object: (number, generation)."""


class Stream:
    """A stream object: its dictionary and where its bytes are in the file."""

    def __init__(self, info: dict, start: int, end: int):
        self.info, self.start, self.end = info, start, end  # the dictionary, the bytes' place


def _skip(raw: bytes, i: int) -> int:
    """The index of the next token: past white space and comments."""
    while i < len(raw):
        if raw[i] in SPACE:  # white space
            i += 1
        elif raw[i] == 0x25:  # a comment runs to the end of its line
            while i < len(raw) and raw[i] not in b"\r\n":
                i += 1
        else:
            break
    return i


def _parse(raw: bytes, i: int, depth: int = 0):
    """One PDF value at raw[i]: (value, the index after it). A dictionary is a dict of names, an array a list, a string
    bytes, a name a Name, a reference a Ref. Raises ValueError where there is no value."""
    if depth > 64:  # a nesting no real file has
        raise ValueError("nested too deep")
    i = _skip(raw, i)
    if raw.startswith(b"<<", i):  # a dictionary
        out, i = {}, i + 2
        while True:
            i = _skip(raw, i)
            if raw.startswith(b">>", i):  # its end
                return out, i + 2
            key, i = _parse(raw, i, depth + 1)  # a name, then its value
            if not isinstance(key, Name):
                raise ValueError("a key that is not a name")
            out[str(key)], i = _parse(raw, i, depth + 1)
    c = raw[i:i + 1]  # the first byte decides the kind
    if c == b"[":  # an array
        out, i = [], i + 1
        while True:
            i = _skip(raw, i)
            if raw[i:i + 1] == b"]":  # its end
                return out, i + 1
            if i >= len(raw):  # cut off
                raise ValueError("an array with no end")
            value, i = _parse(raw, i, depth + 1)
            out.append(value)
    if c == b"(":  # a literal string
        return _literal(raw, i)
    if c == b"<":  # a hex string
        end = raw.index(b">", i)
        digits = re.sub(rb"\s", b"", raw[i + 1:end])
        return bytes.fromhex((digits + b"0" * (len(digits) % 2)).decode("ascii")), end + 1
    if c == b"/":  # a name, with its #xx escapes
        m = NAME.match(raw, i)
        return Name(re.sub(rb"#([0-9A-Fa-f]{2})", lambda h: bytes([int(h.group(1), 16)]), m.group(1)).decode("latin-1")), m.end()
    m = NUMBER.match(raw, i)
    if m:  # a number, or the start of a reference
        if b"." not in m.group(0):  # an integer may be an object's number
            r = REF_TAIL.match(raw, m.end())
            if r:  # 15 0 R
                return Ref((int(m.group(0)), int(r.group(1)))), r.end()
            return int(m.group(0)), m.end()
        return float(m.group(0)), m.end()
    for word, value in ((b"true", True), (b"false", False), (b"null", None)):  # the three keywords that are values
        if raw.startswith(word, i):
            return value, i + len(word)
    raise ValueError("no value at %d" % i)


def _objects(raw: bytes) -> dict:
    """Every object of the file by its number, as last defined: each object in order (a stream's bytes are stepped over,
    so nothing inside an image is read as an object), then those packed in compressed object streams."""
    out, pos = {}, 0  # the objects, where to look next
    while True:
        m = OBJ.search(raw, pos)  # the next object
        if not m:
            break
        try:
            value, i = _parse(raw, m.end())  # its value
        except (ValueError, IndexError):  # not an object after all
            pos = m.end()
            continue
        j = _skip(raw, i)  # a stream's bytes follow the keyword
        if isinstance(value, dict) and raw.startswith(b"stream", j):
            start = j + 6 + (2 if raw.startswith(b"\r\n", j + 6) else 1 if raw[j + 6:j + 7] in (b"\n", b"\r") else 0)  # the end of line after it
            n = value.get("Length")  # its length, when the dictionary says it plainly
            end = start + n if isinstance(n, int) and raw.startswith(b"endstream", _skip(raw, start + n)) else raw.find(b"endstream", start)
            if end < 0:  # cut off
                break
            out[int(m.group(1))] = Stream(value, start, end)
            pos = end + 9  # after endstream
        else:
            out[int(m.group(1))] = value
            pos = i
    for s in [o for o in out.values() if isinstance(o, Stream) and o.info.get("Type") == "ObjStm"]:  # objects packed in a stream
        filt = s.info.get("Filter")
        filt = filt[0] if isinstance(filt, list) and len(filt) == 1 else filt  # one filter, maybe in an array
        try:
            data = zlib.decompress(raw[s.start:s.end]) if filt == "FlateDecode" else raw[s.start:s.end] if filt is None else None
            if data is None:  # a filter this reader does not undo
                continue
            first, count = int(s.info["First"]), int(s.info["N"])  # where the objects start, and how many
            head = [int(x) for x in data[:first].split()]  # pairs of object number and offset
            for k in range(min(count, len(head) // 2)):
                num, off = head[2 * k], head[2 * k + 1]
                if num not in out:  # an object written plainly wins
                    out[num] = _parse(data, first + off)[0]
        except (zlib.error, ValueError, KeyError, IndexError, TypeError):  # a damaged stream: its objects stay unread
            continue
    return out


def _get(objs: dict, value, hops: int = 32):
    """A value with its references followed (a stream gives its dictionary); None for a missing object."""
    while isinstance(value, Ref) and hops:  # a chain of references
        value, hops = objs.get(value[0]), hops - 1
    return value.info if isinstance(value, Stream) else value


def _numbers(objs: dict, value) -> list | None:
    """An array of numbers (a box, a rectangle), each followed if it is a reference; None when it is not one."""
    value = _get(objs, value)
    if not isinstance(value, list):
        return None
    out = [_get(objs, v) for v in value]
    return [float(v) for v in out] if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in out) else None


def page_links(pdf) -> list:
    """Each page in order: {"width", "height", "links": [{"uri", "x0", "y0", "x1", "y1"}]}, in points, y counted from the
    top of the page as it is shown (its crop box, else its media box). Only web and mail links (a URI action) are given;
    a page turned by /Rotate gives its size and no links. [] for a file whose page tree cannot be read."""
    raw = pathlib.Path(pdf).read_bytes()  # the file
    objs = _objects(raw)  # every object
    tr = _last_trailer(raw)  # a classic trailer, else a cross-reference stream's dictionary
    try:
        trailer = _parse(b"<<" + tr + b">>", 0)[0] if tr is not None else \
            next((o.info for o in reversed(list(objs.values())) if isinstance(o, Stream) and o.info.get("Type") == "XRef"), {})
    except (ValueError, IndexError):  # a trailer this cannot read
        return []
    root = _get(objs, trailer.get("Root"))  # the catalogue
    top = _get(objs, root.get("Pages")) if isinstance(root, dict) else None  # the page tree
    secret = "Encrypt" in trailer  # an encrypted file's strings cannot be read
    pages = []  # the result

    def walk(node, inherited: dict, depth: int) -> None:  # one node of the tree, with what its parents give it
        node = _get(objs, node)
        if not isinstance(node, dict) or depth > 64:  # a broken or looping tree
            return
        here = dict(inherited)  # the boxes and the turn a page may take from its parents
        for key in ("MediaBox", "CropBox", "Rotate"):
            if key in node:
                here[key] = node[key]
        kids = _get(objs, node.get("Kids"))
        if node.get("Type") != "Page" and isinstance(kids, list):  # a node of the tree: its pages in order
            for kid in kids:
                walk(kid, here, depth + 1)
            return
        box = _numbers(objs, here.get("CropBox")) or _numbers(objs, here.get("MediaBox"))  # what a reader shows
        if not box or len(box) != 4:  # a page with no size
            return
        x0, y0, x1, y1 = min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3])
        links = []  # its web and mail links
        turned = (_get(objs, here.get("Rotate")) or 0) % 360  # a turned page is shown otherwise
        annots = _get(objs, node.get("Annots"))
        for a in (annots if isinstance(annots, list) and not turned and not secret else []):
            a = _get(objs, a)  # the annotation
            act = _get(objs, a.get("A")) if isinstance(a, dict) and a.get("Subtype") == "Link" else None  # its action
            uri = _get(objs, act.get("URI")) if isinstance(act, dict) and act.get("S") == "URI" else None  # its address
            rect = _numbers(objs, a.get("Rect")) if isinstance(uri, bytes) else None  # where it is
            if rect and len(rect) == 4:
                links.append({"uri": _text(uri), "x0": min(rect[0], rect[2]) - x0, "y0": y1 - max(rect[1], rect[3]),  # from the top left
                              "x1": max(rect[0], rect[2]) - x0, "y1": y1 - min(rect[1], rect[3])})
        pages.append({"width": x1 - x0, "height": y1 - y0, "links": links})

    if isinstance(top, dict):
        walk(top, {}, 0)
    return pages


# ------------------------------------------------------------------ links written

def _name(key: str) -> bytes:
    """A name as a file writes it: a byte outside visible ASCII, a delimiter or # goes as #xx."""
    return b"/" + re.sub(rb"[^!-~]|[#()<>\[\]{}/%]", lambda m: b"#%02X" % m.group(0)[0], str(key).encode("latin-1"))


def _dump(value) -> bytes:
    """A value as _parse reads it, written back; a string goes as hex, so no byte of it needs escaping."""
    if isinstance(value, dict):  # a dictionary: its names and values in order
        return b"<<" + b"".join(_name(k) + b" " + _dump(v) for k, v in value.items()) + b">>"
    if isinstance(value, list):  # an array
        return b"[" + b" ".join(_dump(v) for v in value) + b"]"
    if isinstance(value, Name):  # before str: a name is one
        return _name(value)
    if isinstance(value, Ref):  # 15 0 R
        return b"%d %d R" % (value[0], value[1])
    if isinstance(value, bool):  # before int: True is one
        return b"true" if value else b"false"
    if value is None:
        return b"null"
    if isinstance(value, int):
        return b"%d" % value
    if isinstance(value, float):  # no exponent, no trailing zeros
        return (("%.4f" % value).rstrip("0").rstrip(".") or "0").encode()
    if isinstance(value, bytes):  # a string
        return b"<" + value.hex().encode() + b">"
    raise ValueError("a value this cannot write")


def _first_page(objs: dict, trailer: dict) -> tuple:
    """Page 1: its reference and the boxes and turn it has or takes from its parents; (None, {}) for a tree this cannot read."""
    root = _get(objs, trailer.get("Root"))  # the catalogue
    ref = root.get("Pages") if isinstance(root, dict) else None  # the tree's top
    here = {}  # what the page inherits
    for _ in range(64):  # down the first branch
        node = _get(objs, ref)
        if not isinstance(node, dict) or not isinstance(ref, Ref):  # a broken tree, or a page written inside its parent
            return None, {}
        for key in ("MediaBox", "CropBox", "Rotate"):
            if key in node:
                here[key] = node[key]
        if node.get("Type") == "Page":  # the first page
            return ref, here
        kids = _get(objs, node.get("Kids"))
        if not isinstance(kids, list) or not kids:
            return None, {}
        ref = kids[0]  # its first child
    return None, {}


def add_links(pdf, links: list) -> int:
    """Put web and mail links on page 1 as one incremental update, the way stamp() writes the title: each link is (x0, y0,
    x1, y1, address) in points, y counted from the top of the page as pdftotext's boxes are. An address the page already
    links is skipped. Returns how many were added; 0, with the file left exactly as it was, when none is new or the file is
    not one this can update (no classic trailer at its end, encrypted, a turned page, a page tree this cannot read)."""
    path = pathlib.Path(pdf)
    raw = path.read_bytes()  # the file
    end = STARTXREF.search(raw[-64:])  # the file must end with startxref and %%EOF
    tr = _last_trailer(raw)
    if not end or tr is None or raw[int(end.group(1)):int(end.group(1)) + 4] != b"xref":  # the last section must be a classic table
        return 0
    try:
        trailer = _parse(b"<<" + tr + b">>", 0)[0]  # its dictionary
    except (ValueError, IndexError):  # one this cannot read
        return 0
    size = trailer.get("Size")  # the next free object number
    if "Encrypt" in trailer or not isinstance(size, int) or isinstance(size, bool) or not isinstance(trailer.get("Root"), Ref):
        return 0  # an encrypted file's strings would need its key; a trailer with no catalogue cannot be followed
    objs = _objects(raw)  # every object
    ref, inherited = _first_page(objs, trailer)
    page = objs.get(ref[0]) if ref else None  # page 1's dictionary
    if not isinstance(page, dict) or (_get(objs, inherited.get("Rotate")) or 0) % 360:  # a turned page places its boxes otherwise
        return 0
    box = _numbers(objs, inherited.get("CropBox")) or _numbers(objs, inherited.get("MediaBox"))  # what a reader shows
    if not box or len(box) != 4:
        return 0
    left, top = min(box[0], box[2]), max(box[1], box[3])  # where the page's top left corner is
    first = page_links(path)[:1]  # the links page 1 has
    have = {link["uri"] for link in first[0]["links"]} if first else set()
    new = []  # (rectangle in the page's own units, address)
    for x0, y0, x1, y1, uri in links:
        if uri and uri not in have:  # one link per address
            have.add(uri)
            new.append(([round(left + x0, 3), round(top - y1, 3), round(left + x1, 3), round(top - y0, 3)], uri))
    annots = page.get("Annots")  # the page's annotations: none, an array, or an array kept as an object of its own
    held = _get(objs, annots) if isinstance(annots, Ref) else annots
    if not new or (annots is not None and not isinstance(held, list)):  # nothing to add, or an /Annots this does not know
        return 0
    out = bytearray(raw if raw.endswith(b"\n") else raw + b"\n")  # the update starts on a line of its own
    at = {}  # object number -> (where it starts, its generation)
    refs = []  # the new annotations
    for k, (rect, uri) in enumerate(new):
        num = size + k
        at[num], refs = (len(out), 0), refs + [Ref((num, 0))]
        link = {"Type": Name("Annot"), "Subtype": Name("Link"), "Rect": rect, "Border": [0, 0, 0],  # no frame drawn around it
                "A": {"S": Name("URI"), "URI": uri.encode("utf-8")}}
        out += b"%d 0 obj\n" % num + _dump(link) + b"\nendobj\n"
    if isinstance(annots, Ref):  # the array is an object of its own: a new version of it, the page unchanged
        at[annots[0]] = (len(out), annots[1])
        out += b"%d %d obj\n" % (annots[0], annots[1]) + _dump(list(held) + refs) + b"\nendobj\n"
    else:  # the page holds its array or has none: a new version of the page
        at[ref[0]] = (len(out), ref[1])
        out += b"%d %d obj\n" % (ref[0], ref[1]) + _dump(dict(page, Annots=list(held or []) + refs)) + b"\nendobj\n"
    xref_at = len(out)  # the new cross-reference section: a run of entries for each run of numbers
    out += b"xref\n"
    run = []
    for n in sorted(at) + [None]:
        if run and (n is None or n != run[-1] + 1):  # a run ends
            out += b"%d %d\n" % (run[0], len(run)) + b"".join(b"%010d %05d n \n" % at[r] for r in run)
            run = []
        if n is not None:
            run.append(n)
    tail = {"Size": size + len(new), "Root": trailer["Root"]}  # the new trailer: the catalogue, the information and the identifier kept
    for key in ("Info", "ID"):
        if key in trailer:
            tail[key] = trailer[key]
    tail["Prev"] = int(end.group(1))  # the section before it
    out += b"trailer\n" + _dump(tail) + b"\nstartxref\n%d\n%%%%EOF\n" % xref_at
    tmp = path.with_name(path.name + ".links")  # written whole, then put in place
    tmp.write_bytes(bytes(out))
    tmp.replace(path)
    return len(new)


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) == 2 and a[0] == "read":
        print(read(a[1]))
        return 0
    if len(a) == 2 and a[0] == "links":  # each page's size and links
        for n, page in enumerate(page_links(a[1]), 1):
            print(n, "%gx%g" % (page["width"], page["height"]), " ".join(link["uri"] for link in page["links"]))
        return 0
    if len(a) == 4 and a[0] == "stamp":
        ok = stamp(a[1], a[2], a[3])
        print("stamped" if ok else "not a file this can update")
        return 0 if ok else 1
    print(__doc__.strip().splitlines()[-2:])
    return 2


if __name__ == "__main__":
    sys.exit(main())
