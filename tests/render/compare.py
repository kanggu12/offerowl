#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare two PDFs of one document page by page: the container's (LibreOffice or its Chromium) and the browser
renderer's. This is the parity gate of docs/ARCHITECTURE.md.

Per page it measures:
  - pixels: the share of pixels whose grey value differs by more than 40 (of 255) at 60 dpi, the metric the parts test
    uses;
  - the text layer: the words in reading order, and the lines (where each line breaks);
  - word positions: how far each matched word moved (points), for finding what differs.

  python3 tests/render/compare.py <old.pdf> <new.pdf> [--dpi 60] [--images DIR] [--words N] [--json FILE]

The last line reads `compare: P/Q pages, worst page X.XX% pixels, lines L/M, words W/V`. The exit code is 0 when the
page counts match and every page is under the --max share (default 1%) with the same lines; else 1.
Needs pdftoppm and pdftotext (poppler) and Pillow.
"""
import argparse  # command line
import html  # pdftotext escapes the words
import json  # the machine-readable result
import pathlib  # paths
import re  # the bbox listing
import subprocess  # poppler
import sys  # exit code
import tempfile  # page images

INVISIBLE = dict.fromkeys(map(ord, "⁠​﻿­"), None)  # joiners and soft hyphens: not part of a word


def font_box(pdf: str) -> tuple[float, float]:
    """(ascent, descent) that poppler gives the words of this PDF, as fractions of the font size. It reads them from
    the first font descriptor; LibreOffice writes 0 there, and poppler then uses 0.95 and 0.35. The word boxes of the
    two producers therefore differ by a size-dependent amount, and the baseline is what can be compared"""
    raw = pathlib.Path(pdf).read_bytes()
    m = re.search(rb"/Ascent\s+(-?[\d.]+)\s*/Descent\s+(-?[\d.]+)", raw)
    a, d = (float(m.group(1)) / 1000.0, abs(float(m.group(2))) / 1000.0) if m else (0.0, 0.0)
    return (a if 0 < a < 3 else 0.95), (d if 0 < d < 3 else 0.35)


def text_pages(pdf: str) -> list[list[dict]]:
    """Per page, the lines of the text layer: [{"y", "words": [{"t", "x0", "y0", "x1", "y1", "base"}]}] in reading order.
    "base" is the word's baseline, worked out from its box and the producer's ascent and descent"""
    asc, desc = font_box(pdf)
    xml = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout  # its XML is UTF-8 on every system
    pages = []
    for pg in re.findall(r"<page [^>]*>(.*?)</page>", xml, re.S):  # one page at a time
        lines = []
        for ln in re.findall(r"<line [^>]*>(.*?)</line>", pg, re.S):  # one line of words
            words = []
            for x0, y0, x1, y1, t in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', ln):
                t = html.unescape(t).translate(INVISIBLE)  # the word as typed
                if t:
                    h = float(y1) - float(y0)  # (ascent + descent) times the font size
                    words.append({"t": t, "x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1),
                                  "base": float(y1) - h * desc / (asc + desc)})
            if words:
                lines.append({"y": min(w["y0"] for w in words), "words": words})
        pages.append(lines)
    return pages


def page_images(pdf: str, tmp: str, tag: str, dpi: int) -> list[pathlib.Path]:
    """The pages as grey PNG files, in page order"""
    subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-png", pdf, f"{tmp}/{tag}"], check=True)
    return sorted(pathlib.Path(tmp).glob(f"{tag}-*.png"), key=lambda p: int(p.stem.split("-")[-1]))


def _beyond(x, y, threshold: int):
    """Pixels of x that are more than `threshold` grey levels outside the range of y's 3x3 neighbourhood"""
    from PIL import ImageChops, ImageFilter
    over = ImageChops.subtract(x, y.filter(ImageFilter.MaxFilter(3)))  # brighter than every neighbour
    under = ImageChops.subtract(y.filter(ImageFilter.MinFilter(3)), x)  # darker than every neighbour
    return ImageChops.lighter(over, under).point(lambda v: 255 if v > threshold else 0)


def pixel_share(a: pathlib.Path, b: pathlib.Path, threshold: int = 40, side: pathlib.Path | None = None) -> tuple[float, float]:
    """(strict, tolerant) shares of differing pixels. Strict: the grey values differ by more than `threshold` (the
    metric of the parts test). Tolerant: a pixel counts only when no pixel within one pixel of it in the other image
    is that close, in either direction, so a letter that moved by a fraction of a pixel does not count and a missing,
    extra or recoloured part still does. Writes old | new | strict difference when asked"""
    from PIL import Image, ImageChops  # only this part needs Pillow
    x, y = Image.open(a).convert("L"), Image.open(b).convert("L")
    if x.size != y.size:  # page sizes a fraction of a point apart give images a pixel apart
        # Both rasters start at the page's top-left corner, where both producers start their content; cropping to the
        # common area keeps them aligned. Stretching one onto the other instead shifts the right edge of
        # the page by a whole pixel: the browser prints A4 as 594.96pt wide, LibreOffice as 595.30pt.
        w, h = min(x.size[0], y.size[0]), min(x.size[1], y.size[1])
        x, y = x.crop((0, 0, w, h)), y.crop((0, 0, w, h))
    d = ImageChops.difference(x, y).point(lambda v: 255 if v > threshold else 0)
    n = d.histogram()[255]  # the differing pixels
    tol = ImageChops.lighter(_beyond(x, y, threshold), _beyond(y, x, threshold))  # differing in either direction
    nt = tol.histogram()[255]
    if side:
        im = Image.new("RGB", (x.size[0] * 3 + 20, x.size[1]), "red")
        im.paste(x.convert("RGB"), (0, 0))
        im.paste(y.convert("RGB"), (x.size[0] + 10, 0))
        im.paste(Image.merge("RGB", (d, Image.new("L", d.size, 0), Image.new("L", d.size, 0))), (2 * x.size[0] + 20, 0))
        im.save(side)
        tol.save(side.with_name(side.stem + "_tolerant.png"))
    return n / float(x.size[0] * x.size[1]), nt / float(x.size[0] * x.size[1])


def compare(old: str, new: str, dpi: int = 60, images: str | None = None, threshold: int = 40) -> dict:
    """The page-by-page comparison of two PDFs"""
    ta, tb = text_pages(old), text_pages(new)
    out = {"pages_old": len(ta), "pages_new": len(tb), "pages": []}
    with tempfile.TemporaryDirectory() as tmp:
        ia, ib = page_images(old, tmp, "a", dpi), page_images(new, tmp, "b", dpi)
        for i in range(max(len(ta), len(tb))):
            if i >= len(ta) or i >= len(tb):
                out["pages"].append({"page": i + 1, "only": "old" if i >= len(tb) else "new"})
                continue
            side = pathlib.Path(images) / f"p{i + 1}.png" if images else None
            if side:
                side.parent.mkdir(parents=True, exist_ok=True)
            share, tolerant = pixel_share(ia[i], ib[i], threshold, side)
            # The lines as text without spaces: pdftotext splits letter-spaced text into words differently per
            # producer ('PRO F ESSIONAL' from LibreOffice, 'PROFESSIONAL' from the browser), so the characters of a line
            # and their order are what is compared. Lines are matched as a set, each to the nearest line with the same
            # text: pdftotext's reading order across table columns depends on tiny position differences, so the order
            # of whole lines is not part of the check. A changed line break or word order changes a line's text.
            la = [("".join(w["t"] for w in ln["words"]), ln) for ln in ta[i]]
            lb = [("".join(w["t"] for w in ln["words"]), ln) for ln in tb[i]]
            pool = {}  # text -> lines of the new PDF not matched yet
            for t, ln in lb:
                pool.setdefault(t, []).append(ln)
            pairs, gone = [], []  # matched (old, new) lines, and old lines with no partner
            for t, ln in la:
                cands = pool.get(t) or []
                if not cands:
                    gone.append(t)
                    continue
                base = ln["words"][0]["base"]
                k = min(range(len(cands)), key=lambda j: abs(cands[j]["words"][0]["base"] - base) + abs(cands[j]["words"][0]["x0"] - ln["words"][0]["x0"]))
                pairs.append((ln, cands.pop(k)))
            extra = [t for t, ln_list in pool.items() for _ in ln_list]  # new lines with no partner
            moves = []  # (distance, dx, dy, first word) of each matched line
            for u, v in pairs:
                dx = v["words"][0]["x0"] - u["words"][0]["x0"]
                dy = v["words"][0]["base"] - u["words"][0]["base"]
                moves.append((max(abs(dx), abs(dy)), round(dx, 2), round(dy, 2), u["words"][0]["t"]))
            moves.sort(reverse=True)
            chars_old = sum(len(t) for t, _ in la)
            chars_new = sum(len(t) for t, _ in lb)
            chars_same = sum(len("".join(w["t"] for w in u["words"])) for u, _ in pairs)
            out["pages"].append({
                "page": i + 1, "pixels": share, "pixels_tolerant": tolerant,
                "lines_old": len(la), "lines_new": len(lb), "lines_same": len(pairs),
                "chars_old": chars_old, "chars_new": chars_new, "chars_same": chars_same,
                "move_max": moves[0][0] if moves else 0.0,
                "move_median": sorted(m[0] for m in moves)[len(moves) // 2] if moves else 0.0,
                "worst": moves[:12],
                "lines_diff": ["- " + t for t in gone][:20] + ["+ " + t for t in extra][:20],
            })
    return out


def summary(r: dict, limit: float, tolerant: bool = False) -> tuple[str, bool]:
    """One line per page and a verdict. The verdict reads the strict share, or the share within one pixel with tolerant"""
    lines, ok = [], r["pages_old"] == r["pages_new"]
    worst, worst_t, lsum, lall, wsum, wall = 0.0, 0.0, 0, 0, 0, 0
    for p in r["pages"]:
        if "only" in p:
            lines.append("p%d: only in the %s PDF" % (p["page"], p["only"]))
            ok = False
            continue
        worst, worst_t = max(worst, p["pixels"]), max(worst_t, p["pixels_tolerant"])
        lsum, lall = lsum + p["lines_same"], lall + max(p["lines_old"], p["lines_new"])
        wsum, wall = wsum + p["chars_same"], wall + max(p["chars_old"], p["chars_new"])
        share = p["pixels_tolerant"] if tolerant else p["pixels"]  # the share the verdict uses
        page_ok = share < limit and p["lines_same"] == p["lines_old"] == p["lines_new"] and p["chars_same"] == p["chars_old"] == p["chars_new"]
        ok = ok and page_ok
        lines.append("p%d: pixels %.2f%% strict, %.2f%% within 1px, lines %d/%d same, text %d/%d characters, moved max %.1fpt median %.2fpt%s"
                     % (p["page"], p["pixels"] * 100, p["pixels_tolerant"] * 100, p["lines_same"], max(p["lines_old"], p["lines_new"]),
                        p["chars_same"], max(p["chars_old"], p["chars_new"]), p["move_max"], p["move_median"], "" if page_ok else "  <-"))
    lines.append("compare: %d/%d pages, worst page %.2f%% strict, %.2f%% within 1px, lines %d/%d, characters %d/%d"
                 % (r["pages_new"], r["pages_old"], worst * 100, worst_t * 100, lsum, lall, wsum, wall))
    return "\n".join(lines), ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--dpi", type=int, default=60)
    ap.add_argument("--threshold", type=int, default=40)
    ap.add_argument("--max", type=float, default=0.01, help="largest share of differing pixels a page may have")
    ap.add_argument("--tolerant", action="store_true", help="judge pages by the share within one pixel instead of the strict share")
    ap.add_argument("--images", help="write old | new | difference images per page into this folder")
    ap.add_argument("--words", type=int, default=0, help="list the N words that moved most, per page")
    ap.add_argument("--diff", action="store_true", help="list the lines that differ")
    ap.add_argument("--json", help="write the full result here")
    a = ap.parse_args()
    r = compare(a.old, a.new, a.dpi, a.images, a.threshold)
    text, ok = summary(r, a.max, a.tolerant)
    if a.words or a.diff:
        for p in r["pages"]:
            if "only" in p:
                continue
            if a.words:
                print("p%d worst words: %s" % (p["page"], p["worst"][:a.words]))
            if a.diff and p["lines_diff"]:
                print("p%d lines:\n  %s" % (p["page"], "\n  ".join(p["lines_diff"])))
    print(text)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
