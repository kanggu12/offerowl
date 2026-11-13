#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Font files and metrics for the browser renderer.

The page never relies on fonts installed on the PC: every family a document asks for becomes an @font-face rule that
points at a font file. Two PCs then typeset the same letters with the same widths, and so break lines in the same places.
The files come from, in order:
  1. the repository's fonts/ folder (Pretendard ships with Offerowl);
  2. the folders named by OFFEROWL_FONT_DIRS (separated like PATH);
  3. the system font folders of Windows, macOS and Linux.

The vertical metrics are those LibreOffice uses (the OS/2 typographic values when the font asks for them, else hhea),
written into the rule as ascent-override and descent-override. So the browser's line box and baseline match the PDF that
LibreOffice made from the same DOCX, on every system.
"""
import os  # environment and system folders
import pathlib  # paths
import struct  # the sfnt tables
import sys  # the platform

HERE = pathlib.Path(__file__).resolve().parent  # src/render_html
ROOT = HERE.parent.parent  # the repository root

# Names a document may ask for, and the families that stand in for them. The container's fontconfig maps the same way
# (TeX Gyre Pagella is metric compatible with Palatino), so a stand-in here breaks lines as the container's PDF does.
ALIASES = {
    "palatino linotype": ["Palatino Linotype", "TeX Gyre Pagella", "P052", "URW Palladio L"],
    "palatino": ["Palatino", "TeX Gyre Pagella", "P052", "URW Palladio L"],
    "calibri": ["Calibri", "Carlito"],
}

_CACHE = {}  # family (lower case) -> {(weight, italic): font info}, filled as folders are read


def font_dirs(system: bool = True) -> list[pathlib.Path]:
    """Folders to search, the repository's own first; `system` adds the system font folders"""
    dirs = [ROOT / "fonts", HERE / "fonts"]  # the repository's fonts
    extra = os.environ.get("OFFEROWL_FONT_DIRS", "")  # the person's own folders
    dirs += [pathlib.Path(d) for d in extra.split(os.pathsep) if d]
    if system and sys.platform.startswith("win"):  # Windows keeps fonts in two places
        dirs += [pathlib.Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                 pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    elif system and sys.platform == "darwin":  # macOS
        dirs += [pathlib.Path("/System/Library/Fonts"), pathlib.Path("/Library/Fonts"), pathlib.Path.home() / "Library" / "Fonts"]
    elif system:  # Linux and the rest
        dirs += [pathlib.Path("/usr/share/fonts"), pathlib.Path("/usr/local/share/fonts"),
                 pathlib.Path("/usr/share/texmf/fonts/opentype"), pathlib.Path.home() / ".fonts",
                 pathlib.Path.home() / ".local" / "share" / "fonts"]
    return [d for d in dirs if d.is_dir()]  # only folders that exist


def _names(data: bytes) -> dict:
    """Name id -> string, from the bytes of a 'name' table (Windows English records first, then Unicode, then Mac Roman)"""
    if len(data) < 6:
        return {}
    _, count, strings = struct.unpack(">HHH", data[:6])  # format, record count, string offset
    out = {}
    for i in range(count):
        pid, eid, lid, nid, ln, so = struct.unpack(">HHHHHH", data[6 + 12 * i:18 + 12 * i])  # one name record
        raw = data[strings + so:strings + so + ln]  # the string bytes
        if pid == 3 or pid == 0:  # Windows or Unicode records are UTF-16
            s = raw.decode("utf-16-be", "ignore")
            if nid not in out or (pid == 3 and lid == 0x409):  # US English wins over other languages
                out[nid] = s
        elif pid == 1 and nid not in out:  # Mac Roman as a last resort
            out[nid] = raw.decode("latin-1", "ignore")
    return out


def read_font(path: pathlib.Path) -> dict | None:
    """Family, weight, italic and LibreOffice's vertical metrics of one font file, or None if it is not one.
    Only the table directory and four small tables are read, so scanning a folder of large CJK fonts stays quick"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)  # sfnt version and table count
            if len(head) < 12 or head[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):  # collections are skipped
                return None
            n = struct.unpack(">H", head[4:6])[0]  # number of tables
            rec = fh.read(16 * n)  # the table records
            t = {}
            for i in range(n):
                tag, _, off, ln = struct.unpack(">4sIII", rec[16 * i:16 * i + 16])
                t[tag.decode("latin-1")] = (off, ln)
            if "head" not in t or "hhea" not in t:
                return None

            def table(tag):  # the bytes of one table
                fh.seek(t[tag][0])
                return fh.read(t[tag][1])
            hd, hh = table("head"), table("hhea")
            os2 = table("OS/2") if "OS/2" in t else b""
            nm = table("name") if "name" in t else b""
    except OSError:
        return None
    upm = struct.unpack(">H", hd[18:20])[0]  # units per em
    asc, desc, gap = struct.unpack(">hhh", hh[4:10])  # hhea ascender, descender, line gap
    weight, italic = 400, False
    if len(os2) >= 78:
        weight = struct.unpack(">H", os2[4:6])[0]  # usWeightClass
        fs = struct.unpack(">H", os2[62:64])[0]  # fsSelection
        italic = bool(fs & 1)  # the italic bit
        ta, td, tg, wa, wd = struct.unpack(">hhhHH", os2[68:78])  # typographic and Windows metrics
        if asc == 0 and desc == 0:  # LibreOffice falls back to the Windows metrics without hhea values
            asc, desc, gap = wa, -wd, 0
        if fs & 0x80 and ta >= 0 and td <= 0:  # USE_TYPO_METRICS: LibreOffice then takes the typographic values
            asc, desc, gap = ta, td, tg
    names = _names(nm)
    fam = names.get(16) or names.get(1) or path.stem  # typographic family, else the legacy family
    sub = (names.get(17) or names.get(2) or "").lower()  # its style name
    if "bold" in sub and weight < 600:  # a legacy 'Bold' style with a plain weight class
        weight = 700
    if "italic" in sub or "oblique" in sub:
        italic = True
    return {"family": fam, "weight": weight, "italic": italic, "path": str(path),
            "upm": upm, "asc": asc, "desc": -desc, "gap": gap}


_SCANNED = set()  # folders already read into _CACHE


def _scan(dirs) -> None:
    """Add every font file of these folders to the cache (each folder once per process)"""
    for d in dirs:
        if str(d) in _SCANNED:
            continue
        _SCANNED.add(str(d))
        for f in sorted(d.rglob("*")):
            if f.suffix.lower() not in (".ttf", ".otf"):
                continue
            info = read_font(f)
            if not info:
                continue
            fam = _CACHE.setdefault(info["family"].lower(), {})  # families are matched without case
            fam.setdefault((info["weight"], info["italic"]), info)  # the first folder wins, so the repository's copy is used


def faces(family: str) -> dict:
    """(weight, italic) -> font info for one family, through the aliases; empty when no file is found.
    The repository's folders are read first; the system folders only when a family is not there"""
    for system in (False, True):
        _scan(font_dirs(system))
        for name in ALIASES.get(family.lower(), [family]):  # the family itself first, then its stand-ins
            hit = _CACHE.get(name.lower())
            if hit:
                return hit
    return {}


def css_name(family: str) -> str:
    """The private family name used in the page, so an installed font of the same name is never picked instead"""
    return "owl-" + "".join(c if c.isalnum() else "-" for c in family.lower())


def css_family(latin: str, east: str) -> str:
    """font-family of a run: the Latin face, then the East Asian face for the letters the first one lacks"""
    names = [css_name(latin)] + ([css_name(east)] if east and east != latin else [])
    fallback = ["'%s'" % latin] + (["'%s'" % east] if east and east != latin else [])  # installed fonts when no file was found
    return ",".join(["'%s'" % n for n in names] + fallback + ["sans-serif"])


def font_face_css(families) -> str:
    """@font-face rules for every family a document uses, with LibreOffice's vertical metrics"""
    rules = []
    for fam in sorted(f for f in families if f):
        found = faces(fam)
        for (weight, italic), info in sorted(found.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            upm = float(info["upm"])
            rules.append(
                "@font-face { font-family: '%s'; font-weight: %d; font-style: %s; src: url('%s');"
                " ascent-override: %.4f%%; descent-override: %.4f%%; line-gap-override: 0%%; }"
                % (css_name(fam), weight, "italic" if italic else "normal", pathlib.Path(info["path"]).resolve().as_uri(),
                   info["asc"] / upm * 100, info["desc"] / upm * 100))
    return "\n".join(rules)


def metrics_for(families) -> dict:
    """family -> {asc, desc} as fractions of the em, from the regular face, for page.js's line heights"""
    out = {}
    for fam in families:
        if not fam:
            continue
        found = faces(fam)
        if not found:  # no file: an installed font, with metrics the page measures itself
            continue
        info = found.get((400, False)) or sorted(found.values(), key=lambda i: abs(i["weight"] - 400))[0]
        upm = float(info["upm"])
        out[css_name(fam)] = {"asc": info["asc"] / upm, "desc": info["desc"] / upm}
    return out


def missing(families) -> list[str]:
    """The families of a document for which no font file was found"""
    return sorted(f for f in families if f and not faces(f))


if __name__ == "__main__":
    for fam in sys.argv[1:] or ["Pretendard"]:  # print what a family resolves to
        for k, v in sorted(faces(fam).items()):
            print(fam, k, v["path"], "asc %.4f desc %.4f" % (v["asc"] / v["upm"], v["desc"] / v["upm"]))
