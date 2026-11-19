#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A PDF made smaller with no change a reader can see, for an upload limit (a job site that takes a portfolio of 2 MB at
most). The safe steps come first, and each later one is taken only while the file is still over the size asked for:

  1. A page's shapes are drawn with more digits than any screen or printer shows (Chrome writes 39.999996 and
     15882.2998). Each path coordinate (m l c v y re) is rounded to the fewest decimals that keep it within 0.04 pt of its
     place, under the scale in force there (cm, q and Q followed). An image of 256 colours or fewer (a logo, a figure) is
     written as a palette of exactly its colours over its own colour space, its transparency mask kept: the same pixels in
     fewer bytes. The file is saved with its objects packed into object streams and every Flate stream compressed again.
     The text layer is untouched: an extractor reads it as before.
  2. The text positions too (Td, and the place a Tm sets), each within 0.004 pt. A Td moves from the one before it, so what
     one rounding gives up is carried into the next: no glyph drifts along its line. Every character stays, in its order,
     though an extractor that sits on its threshold for a word set with wide letter spacing may break it otherwise.
  3. The 8-bit RGB images get a palette of at most 256 colours, then 224, 192, 160 and 128, chosen by median cut and never
     dithered, so a flat area stays flat. Never fewer than 128 colours, never JPEG. When even 128 colours do not fit, the
     smallest file is the result, and it says so.

With no size asked for, steps 1 and 2 are taken. The words, the links, the outline, the title and the author stay; a PDF
under the size already is copied as it is. The result writes its cross-references as a stream (PDF 1.5), which every PDF
reader reads, though src/pdfmeta.py, which reads only the classic form, does not. pikepdf (with Pillow) does the work:
the render container and the app image carry it, and a Python without it (the desktop app) has no shrinking and says so
(Unavailable).

    python3 src/pdf_shrink.py <in.pdf> <out.pdf> [--max-mb 1.99] [--json out.json]

A megabyte here is 1,000,000 bytes, the stricter of the two ways a site may count one: 1.99 stays under a limit of 2 MB
either way. Exit 0 when done (and under the size asked for), 1 when even the fewest colours do not fit, 2 for a wrong
command line, 3 when this Python has no pikepdf.
"""
import inspect  # what this pikepdf's save takes
import io  # the PDF in memory between the steps
import json  # the result for a reader that words it itself
import math  # the scale of a matrix
import os  # an atomic replace of the result
import pathlib  # paths
import sys  # the command line
import zlib  # the size an image's palette would take, before it is chosen
from decimal import ROUND_HALF_EVEN, Decimal  # exact rounding of the numbers as written

ROOT = pathlib.Path(__file__).resolve().parent.parent  # the repository root, one level above src/
sys.path.insert(0, str(ROOT / "src"))  # llm.py beside this file, however it was started
import llm  # noqa: E402  the message helper and the language setting

MB = 1_000_000  # bytes in a megabyte as an upload limit counts them (the stricter way)
PATH_PT = 0.04  # how far a path coordinate may move, in points: less than one dot of a 1200 dpi printer (0.06 pt)
TEXT_PT = 0.004  # how far a text position may move, in points: ten times finer, as a word's glyphs sit side by side
PATH_OPS = {"m": 2, "l": 2, "c": 6, "v": 4, "y": 4, "re": 4}  # path construction and its operand count: every operand a coordinate
PALETTES = (256, 224, 192, 160, 128)  # the most colours an image keeps, tried in turn while the file is over its size
MOST_DIGITS = 6  # decimals a rounded number may keep: more would be written as an exponent, which a PDF does not read
MSG = {  # what this tool says, in both languages with the same keys
    "en": {
        "done": "{file}: {before} MB -> {after} MB",
        "colors": "{file}: {before} MB -> {after} MB, its images at {colors} colours at most",
        "as_is": "{file}: {before} MB, under {limit} MB already: copied as it is",
        "over": "{file}: {after} MB at its smallest, over the {limit} MB asked for: the smallest file was written",
        "unavailable": "shrinking a PDF needs pikepdf, which this Python does not have",
        "unreadable": "{file} could not be read as a PDF",
        "unwritable": "{file} could not be written",
        "usage": "usage: python3 src/pdf_shrink.py <in.pdf> <out.pdf> [--max-mb 1.99] [--json out.json]",
    },
    "ko": {
        "done": "{file}: {before}MB에서 {after}MB로 줄였다",
        "colors": "{file}: {before}MB에서 {after}MB로 줄였다. 그림은 많아야 {colors}색",
        "as_is": "{file}: {before}MB로 이미 {limit}MB 아래라 그대로 복사했다",
        "over": "{file}: 가장 작게 줄여도 {after}MB라 요청한 {limit}MB를 넘는다. 가장 작은 파일을 썼다",
        "unavailable": "PDF를 줄이려면 pikepdf가 있어야 하는데 이 Python에는 없다",
        "unreadable": "{file} 파일을 PDF로 읽지 못했다",
        "unwritable": "{file} 파일을 쓰지 못했다",
        "usage": "쓰는 법: python3 src/pdf_shrink.py <입력.pdf> <출력.pdf> [--max-mb 1.99] [--json out.json]",
    },
}


class Unavailable(RuntimeError):
    """This Python has no pikepdf: nothing can be made smaller here (the desktop app carries none)."""


def t(key: str, **kw) -> str:
    """A message of this tool in the person's language."""
    return llm.message(MSG, key, **kw)


def available() -> bool:
    """Can this Python make a PDF smaller? (Asked without importing pikepdf, which loads a large library.)"""
    import importlib.util  # find_spec looks without importing
    return importlib.util.find_spec("pikepdf") is not None  # Pillow comes with it


def _pikepdf():
    """pikepdf, or Unavailable."""
    try:
        import pikepdf  # qpdf underneath
    except ImportError as exc:  # the desktop app, or a Python it was never installed for
        raise Unavailable("pikepdf") from exc
    return pikepdf


# ---------------------------------------------------------------- the numbers a page is drawn with


def mul(m: tuple, n: tuple) -> tuple:
    """The matrix m then n, as PDF writes matrices ([a b c d e f], a point as a row on the left)."""
    a, b, c, d, e, f = m
    p, q, r, s, u, v = n
    return (a * p + b * r, a * q + b * s, c * p + d * r, c * q + d * s, e * p + f * r + u, e * q + f * s + v)


def stretch(m: tuple) -> float:
    """The most a matrix lengthens a distance: its largest singular value (0.75 for Chrome's px to pt)."""
    a, b, c, d = (float(x) for x in m[:4])  # the linear part; the translation moves, it does not stretch
    s, det = a * a + b * b + c * c + d * d, a * d - b * c  # the sum of the squares, and the area it scales by
    return math.sqrt(max(0.0, (s + math.sqrt(max(0.0, s * s - 4 * det * det))) / 2))  # the larger root, never a negative from rounding


def digits_for(scale: float, tol_pt: float):
    """The fewest decimals that keep a number within tol_pt points once the scale is applied, or None to leave it as
    written (a scale of nothing, or one so large that six decimals are not enough)."""
    if not (scale > 0 and math.isfinite(scale)):  # a matrix that draws nothing, or a broken one
        return None
    for d in range(MOST_DIGITS + 1):  # the fewest first
        if 0.5 * 10 ** -d * scale <= tol_pt:  # the most a rounding to d decimals moves it, in points
            return d
    return None  # finer than six decimals: kept as it is


def number(x: Decimal):
    """A rounded number as a page writes it: an integer as one, else its decimals without trailing zeros."""
    return int(x) if x == x.to_integral_value() else x.normalize()  # 39.0 is 39; 9.250 is 9.25


def rounded(x, d: int):
    """x with at most d decimals, half to even so that no direction is favoured."""
    return number(Decimal(str(x)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_EVEN))


def numeric(operands) -> bool:
    """Are all the operands numbers (an operator written by hand may carry something else)?"""
    return all(isinstance(x, (int, float, Decimal)) and not isinstance(x, bool) for x in operands)


def round_content(instructions: list, text_too: bool = True) -> list:
    """A page's instructions with its positions rounded (path coordinates within PATH_PT, and with text_too the text
    positions within TEXT_PT), each under the scale in force there. An instruction left as it was stays the same object,
    so an inline image and a marked-content property list go back as they came."""
    out = []  # the instructions, some of them rounded
    ctm, saved = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), []  # the current matrix from the page's own space, and those q saved
    text = (1.0, 0.0, 0.0, 1.0)  # the linear part of the text matrix, which scales a Td
    carry = [Decimal(0), Decimal(0)]  # what the last Td's rounding gave up, owed to the next one
    for inst in instructions:
        operands, op = inst  # an instruction is (its operands, its operator)
        name, new = str(op), None  # the operator's name, and its rounded operands when they change
        if name == "q":  # the graphics state saved
            saved.append(ctm)
        elif name == "Q":  # and restored (a Q too many keeps the matrix it has)
            ctm = saved.pop() if saved else ctm
        elif name == "cm" and len(operands) == 6 and numeric(operands):  # a new matrix in front of the current one
            ctm = mul(tuple(float(x) for x in operands), ctm)
        elif name == "BT":  # a text object starts at the identity, with nothing owed
            text, carry = (1.0, 0.0, 0.0, 1.0), [Decimal(0), Decimal(0)]
        elif name == "Tm" and len(operands) == 6 and numeric(operands):  # a text matrix set outright: nothing owed from before
            text, carry = tuple(float(x) for x in operands[:4]), [Decimal(0), Decimal(0)]
            d = digits_for(stretch(ctm), TEXT_PT) if text_too else None  # its place is in the page's space, under the current matrix
            if d is not None:  # only the place: its scale and turn stay exact
                new = [*operands[:4], *(rounded(x, d) for x in operands[4:])]
        elif name == "Td" and text_too and len(operands) == 2 and numeric(operands):  # a move from the start of the line before
            d = digits_for(stretch(mul(text + (0.0, 0.0), ctm)), TEXT_PT)  # in text space: the text matrix, then the page's
            if d is not None:
                new = []  # the move as written, with what the last one gave up added
                for k in (0, 1):
                    exact = Decimal(str(operands[k])) + carry[k]  # where this glyph should be, from the last one written
                    near = exact.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_EVEN)  # as written now
                    carry[k] = exact - near  # owed to the next move: the error never adds up along a line
                    new.append(number(near))
        elif name in PATH_OPS and len(operands) == PATH_OPS[name] and numeric(operands):  # a path's coordinates
            d = digits_for(stretch(ctm), PATH_PT)  # where they land on the page decides how many decimals they keep
            if d is not None:
                new = [rounded(x, d) for x in operands]
        out.append(inst if new is None else (new, op))  # the instruction itself, or its rounded twin
    return out


def page_contents(pk, pdf, text_too: bool) -> list:
    """Each page's content with its positions rounded (the text's too, with text_too), as bytes (None for a page whose
    content cannot be read: it stays as it is). Made once for each kind, and set on every attempt."""
    out = []  # one per page
    for page in pdf.pages:
        try:
            out.append(pk.unparse_content_stream(round_content(pk.parse_content_stream(page), text_too)))  # its instructions, written again
        except Exception:  # noqa: BLE001  a content this cannot read or write again stays as it is
            out.append(None)
    return out


# ---------------------------------------------------------------- images


def inherited(obj, key: str):
    """A page's entry, from the page or from the page tree above it (a page's resources may be its parent's)."""
    seen = 0  # a guard against a tree that loops
    while obj is not None and seen < 64:
        if key in obj:  # here
            return obj.get(key)
        obj, seen = obj.get("/Parent"), seen + 1  # one level up
    return None


def images(pk, pdf) -> list:
    """Every image the pages draw, those inside forms too, once each."""
    seen, out = set(), []  # the streams met, and the images in the order met

    def walk(resources):  # a resource dictionary's images, and its forms' own
        xobjects = resources.get("/XObject") if isinstance(resources, pk.Dictionary) else None
        if not isinstance(xobjects, pk.Dictionary):  # nothing drawn from outside the content
            return
        for _, x in xobjects.items():
            if not isinstance(x, pk.Stream) or x.objgen in seen:  # met already (a form may draw itself)
                continue
            seen.add(x.objgen)
            if x.get("/Subtype") == "/Image":  # a picture
                out.append(x)
            elif x.get("/Subtype") == "/Form":  # a form: what it draws
                walk(x.get("/Resources"))
    for page in pdf.pages:
        walk(inherited(page.obj, "/Resources"))
    return out


def rgb_pixels(pk, raw):
    """The pixels of an image a palette can stand for, as an RGB Pillow image, or None: 8 bits a component, red green and
    blue (DeviceRGB, or an ICC profile of three components), Flate or no filter, no colour-key mask, no Decode array. Its
    transparency mask (SMask) is a picture of its own and stays as it is."""
    if raw.get("/BitsPerComponent") != 8 or raw.get("/ImageMask") or "/Mask" in raw or "/Decode" in raw:  # another kind of image
        return None
    filters = raw.get("/Filter")  # how its bytes are packed
    filters = list(filters) if isinstance(filters, pk.Array) else [] if filters is None else [filters]
    if any(str(f) != "/FlateDecode" for f in filters):  # a JPEG, JPEG 2000 or the like stays as it is: no second loss
        return None
    cs = raw.get("/ColorSpace")  # its colours
    if not (cs == pk.Name.DeviceRGB or (isinstance(cs, pk.Array) and len(cs) == 2 and cs[0] == pk.Name.ICCBased and cs[1].get("/N") == 3)):
        return None  # grey, CMYK, a palette already, or a space this does not know
    try:
        pil = pk.PdfImage(raw).as_pil_image()  # the pixels as written, no colour management
    except Exception:  # noqa: BLE001  an image this cannot decode stays as it is
        return None
    if pil.mode == "RGBA":  # pikepdf put the SMask in: only the colours are wanted
        pil = pil.convert("RGB")
    return pil if pil.mode == "RGB" else None


def palette(pil, colours):
    """A palette (Pillow 'P') image for these pixels: exactly their colours when there are no more than `colours` (256 when
    none are given up), else that many colours, chosen by median cut and never dithered, so a flat area stays flat. None
    when the pixels have more than 256 colours and none are given up."""
    from PIL import Image  # Pillow, which pikepdf brings
    found = pil.getcolors(colours or 256)  # every colour, or None when there are more than that
    if found is not None:  # few enough colours: the palette is exactly them
        exact = Image.new("P", (1, 1))  # a palette holder
        flat = [v for _, c in found for v in c]  # their red, green and blue
        exact.putpalette(flat + [0] * (768 - len(flat)))  # padded to 256 entries
        q = pil.quantize(palette=exact, dither=getattr(getattr(Image, "Dither", Image), "NONE", 0))  # each pixel its own colour
        return q if q.convert("RGB").tobytes() == pil.tobytes() else None  # the same pixels, or nothing
    if not colours:  # more than 256 colours, and none given up
        return None
    method = getattr(getattr(Image, "Quantize", Image), "MEDIANCUT", 0)  # Pillow 9.1 named its enums; earlier ones are plain numbers
    return pil.quantize(colors=colours, method=method, dither=getattr(getattr(Image, "Dither", Image), "NONE", 0))


def set_palette(pk, raw, q) -> bool:
    """The image written as indexes into its palette, over the colour space it had, when that is smaller than it was;
    True when it was."""
    data = q.tobytes()  # one byte a pixel
    if len(zlib.compress(data, 6)) >= len(raw.read_raw_bytes()):  # no smaller packed (the file's compression is about this)
        return False
    lookup = bytes(q.getpalette()[:768])  # the palette's colours, red green blue
    lookup += bytes(768 - len(lookup))  # 256 entries, each index a colour of it
    base = raw.get("/ColorSpace")  # the image's own colours (its ICC profile) under the palette
    raw.write(data)  # unpacked here: the save packs it
    for key in ("/Filter", "/DecodeParms"):  # the old packing no longer applies (an older pikepdf keeps the keys)
        if key in raw:
            del raw[key]
    raw.ColorSpace = pk.Array([pk.Name.Indexed, base, 255, pk.String(lookup)])
    raw.BitsPerComponent = 8
    return True


# ---------------------------------------------------------------- the file


def attempt(pk, data: bytes, contents: dict, text_too: bool, colours) -> bytes:
    """The PDF made smaller once: the pages' rounded contents (the text's positions too, with text_too), every image of
    256 colours or fewer as its exact palette and, with `colours`, every other one at that many colours, saved packed.
    `contents` keeps the rounded pages of each kind for the next attempt."""
    with pk.open(io.BytesIO(data)) as pdf:
        if text_too not in contents:  # the first attempt of each kind rounds the pages; the later ones reuse it
            contents[text_too] = page_contents(pk, pdf, text_too)
        for page, content in zip(pdf.pages, contents[text_too]):
            if content is not None:  # a page this could read
                page.obj.Contents = pdf.make_stream(content)  # one stream for the page, packed when saved
        for raw in images(pk, pdf):  # each picture once
            pil = rgb_pixels(pk, raw)
            q = palette(pil, colours) if pil is not None else None
            if q is not None:
                set_palette(pk, raw, q)
        out = io.BytesIO()  # the file, in memory until the result is chosen
        same = {"deterministic_id": True} if "deterministic_id" in inspect.signature(pdf.save).parameters else {}  # the same bytes for the same input, where it can (not in pikepdf 6, the images' Debian one)
        pdf.save(out, compress_streams=True, recompress_flate=True, object_stream_mode=pk.ObjectStreamMode.generate,
                 stream_decode_level=pk.StreamDecodeLevel.generalized, **same)
    return out.getvalue()


def write(dst: pathlib.Path, data: bytes) -> None:
    """The result in place at once, written whole beside it first (the source may be the same file)."""
    part = dst.with_name(f"{dst.name}.{os.getpid()}.shrink")  # a name of this writer's own, on the same disk
    part.write_bytes(data)
    os.replace(part, dst)


def shrink(src, dst, max_bytes: int | None = None) -> dict:
    """src made smaller into dst (the module's steps): the safe ones, then the text's positions and fewer colours, each
    only while the file is over max_bytes. {"before", "after", "text" (its positions rounded), "colors" (the palette the
    images got, or None), "fits" (under max_bytes, or None when none was asked), "changed" (False when dst is src's
    bytes)}. Raises Unavailable without pikepdf, and ValueError("unreadable") for a file it cannot read as a PDF."""
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    data = src.read_bytes()  # the PDF as it is
    before = len(data)
    if max_bytes and before <= max_bytes:  # under the size already: nothing to give up
        write(dst, data)
        return {"before": before, "after": before, "text": False, "colors": None, "fits": True, "changed": False}
    pk = _pikepdf()  # or Unavailable
    steps = [(False, None), (True, None), *((True, c) for c in (PALETTES if max_bytes else ()))]  # (text positions too, colours), the safest first
    best, contents = (before, data, False, None), {}  # the smallest so far (size, bytes, text, colours), and the rounded pages of each kind
    for text_too, colours in steps:
        try:
            made = attempt(pk, data, contents, text_too, colours)
        except pk.PdfError as exc:  # not a PDF, or one qpdf cannot read (a password)
            raise ValueError("unreadable") from exc
        if len(made) < best[0]:  # smaller than anything before
            best = (len(made), made, text_too, colours)
        if max_bytes and best[0] <= max_bytes:  # it fits: nothing more is given up
            break
    size, out, text_too, colours = best
    write(dst, out)
    return {"before": before, "after": size, "text": text_too, "colors": colours,
            "fits": None if not max_bytes else size <= max_bytes, "changed": out is not data}


# ---------------------------------------------------------------- the command line


def mb(n: int) -> str:
    """Bytes as megabytes, two decimals (1,990,000 is 1.99)."""
    return f"{n / MB:.2f}"


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)  # the arguments
    opt = lambda name: args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None  # noqa: E731  an option's value
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--max-mb", "--json"))]  # the two files
    if args[:1] in (["-h"], ["--help"], ["help"]):  # the tool in plain words
        print(__doc__.strip())
        return 0
    try:
        limit = round(float(opt("--max-mb")) * MB) if opt("--max-mb") is not None else None  # the size to fit, in bytes
    except (ValueError, OverflowError):  # not a number, or not a finite one
        limit = -1
    if len(pos) != 2 or (limit is not None and limit <= 0):  # anything else
        print(t("usage"), file=sys.stderr)
        return 2
    name = pathlib.Path(pos[0]).name  # the file, as the lines below name it
    if not pathlib.Path(pos[0]).is_file():  # nothing to read
        print(t("unreadable", file=name), file=sys.stderr)
        return 1
    try:
        got = shrink(pos[0], pos[1], limit)
    except Unavailable:  # the desktop app, or a Python without pikepdf
        print(t("unavailable"), file=sys.stderr)
        return 3
    except ValueError:  # not a PDF, or one with a password
        print(t("unreadable", file=name), file=sys.stderr)
        return 1
    except OSError:  # a folder that is not there, or one that cannot be written
        print(t("unwritable", file=pathlib.Path(pos[1]).name), file=sys.stderr)
        return 1
    if opt("--json"):  # for a reader that words it itself
        pathlib.Path(opt("--json")).write_text(json.dumps(got), encoding="utf-8")
    words = {"file": name, "before": mb(got["before"]), "after": mb(got["after"]), "colors": got["colors"], "limit": mb(limit or 0)}  # the line's values
    if got["fits"] is False:  # the fewest colours were not enough
        print(t("over", **words))
        return 1
    same, fewer = bool(limit) and not got["changed"], bool(got["colors"])  # copied as it was, or its images at fewer colours
    print(t("as_is" if same else "colors" if fewer else "done", **words))
    return 0


def utf8_stdio() -> None:
    """Print UTF-8 whatever the console's code page (the Korean lines through a Windows pipe in cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # a text stream of this Python, not a test's replacement
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    utf8_stdio()  # before anything is printed
    sys.exit(main())
