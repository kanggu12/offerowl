"""A resume photo without what the camera wrote into it.

A phone's JPEG carries its EXIF block: where it was taken (GPS), the phone, its serial number, the time, a thumbnail. A
PNG may carry text chunks and its own EXIF. None of it belongs in a file sent to a company, and the PDF and the Word file
would carry the photo as it was given. This takes those blocks out, byte by byte, with no image library, and keeps
the picture itself untouched (no new encoding, so no loss). The one thing kept is the orientation: a portrait photo a
phone stored on its side would print on its side without it, so it stays, alone, in a minimal EXIF block of its own.

The panel shows the photo small; thumbnail() makes that small copy with Pillow when it is installed. Only the panel's
own display asks for it: every document is made from the kept file.

A photo the person removed waits in the profile's folder under a name of its own (removed-photo-<day>-<time>.*); the Trash
lists it, puts it back and deletes it for good through the functions at the end (kept_photos, photo_back, purge_photo).
"""
from __future__ import annotations

import io  # the small copy's bytes (thumbnail)
import os  # a removed photo moved back into its place
import re  # the names removed photos wait under
import struct  # the fields of the blocks
import threading  # the small copies, asked for by request threads at once
import time  # the moment a photo was removed, in its name in the Trash
import zlib  # a PNG chunk's checksum
from pathlib import Path  # paths

from ...core.workspace import gone, retried  # a file deleted or refused, and moves waited for on Windows

JPEG_KEEP = {0xE0, 0xE2, 0xEE}  # APP0 (JFIF), APP2 (the colour profile), APP14 (Adobe's colour transform): what the picture needs
JPEG_DROP = set(range(0xE1, 0xF0)) - JPEG_KEEP | {0xFE}  # every other APPn (EXIF, XMP, IPTC, makers' blocks) and comments
PNG_DROP = {b"tEXt", b"iTXt", b"zTXt", b"tIME"}  # text (author, software, places) and the time it was saved
PHOTO = re.compile(r"removed-photo-(\d{8}-\d{6}(?:-\d{1,3})?)\.(jpg|png)")  # a removed photo's file, as remove_photo names it


def orientation(tiff: bytes) -> int:
    """The Orientation tag (1 to 8) of an EXIF block's TIFF data; 1 when it has none or cannot be read."""
    order = {b"II": "<", b"MM": ">"}.get(tiff[:2])  # little or big endian
    if not order or len(tiff) < 8:  # not TIFF data
        return 1
    off = struct.unpack(order + "I", tiff[4:8])[0]  # where the first directory starts
    if off + 2 > len(tiff):  # past the end
        return 1
    count = struct.unpack(order + "H", tiff[off:off + 2])[0]  # its entries
    for k in range(count):  # each twelve bytes long
        e = off + 2 + 12 * k  # this entry
        if e + 12 > len(tiff):  # cut short
            break
        tag, kind = struct.unpack(order + "HH", tiff[e:e + 4])  # what it is and its type
        if tag == 0x0112 and kind == 3:  # Orientation, a SHORT
            value = struct.unpack(order + "H", tiff[e + 8:e + 10])[0]  # held in the entry itself
            return value if 1 <= value <= 8 else 1  # only the values the standard has
    return 1  # no orientation: upright


def tiff_with(value: int) -> bytes:
    """TIFF data with one directory holding the Orientation tag alone."""
    return (b"II*\x00" + struct.pack("<I", 8)  # little endian, the directory right after the header
            + struct.pack("<H", 1) + struct.pack("<HHIHH", 0x0112, 3, 1, value, 0)  # one entry: Orientation, SHORT, one value
            + struct.pack("<I", 0))  # no next directory


def clean_jpeg(data: bytes) -> bytes:
    """A JPEG without its metadata blocks; the frame, the tables and the scan as they were. ValueError when it is broken."""
    if data[:2] != b"\xff\xd8":  # no start of image
        raise ValueError("photo")
    out, i, turned = [b"\xff\xd8"], 2, False  # what is kept, where we are, and whether the orientation went back in
    while True:
        if i + 2 > len(data) or data[i] != 0xFF:  # every segment starts with FF; anything else is a broken file
            raise ValueError("photo")
        while i + 1 < len(data) and data[i + 1] == 0xFF:  # fill bytes before a marker
            i += 1
        if i + 2 > len(data):  # ended inside the fill
            raise ValueError("photo")
        marker = data[i + 1]  # what the segment is
        if marker == 0xDA or marker == 0xD9:  # the scan (the picture, then the end), or an early end: the rest as it was
            out.append(data[i:])
            return b"".join(out)
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # a marker with no length
            out.append(data[i:i + 2])
            i += 2
            continue
        if i + 4 > len(data):  # no room for its length
            raise ValueError("photo")
        n = struct.unpack(">H", data[i + 2:i + 4])[0]  # its length, the two length bytes included
        if n < 2 or i + 2 + n > len(data):  # a length that cannot be
            raise ValueError("photo")
        seg = data[i:i + 2 + n]  # the whole segment
        if marker == 0xE1 and seg[4:10] == b"Exif\x00\x00":  # the camera's block: only its orientation stays
            value = orientation(seg[10:])  # how the picture is turned
            if value != 1 and not turned:  # turned: kept, alone
                body = b"Exif\x00\x00" + tiff_with(value)  # a minimal EXIF block
                out.append(b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body)
                turned = True  # once
        elif marker not in JPEG_DROP:  # the frame, the tables, JFIF, the colour profile
            out.append(seg)
        i += 2 + n  # the next segment


def chunk(kind: bytes, body: bytes) -> bytes:
    """One PNG chunk: its length, its type, its data and their checksum."""
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def clean_png(data: bytes) -> bytes:
    """A PNG without its text chunks, its time and its EXIF (but the orientation); the picture's chunks as they were."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":  # not a PNG
        raise ValueError("photo")
    out, i = [data[:8]], 8  # what is kept, where we are
    while i < len(data):  # chunk by chunk
        if i + 12 > len(data):  # no room for a chunk
            raise ValueError("photo")
        n = struct.unpack(">I", data[i:i + 4])[0]  # its data's length
        kind = data[i + 4:i + 8]  # its type
        end = i + 12 + n  # where the next one starts
        if end > len(data):  # cut short
            raise ValueError("photo")
        if kind == b"eXIf":  # a camera's block: only its orientation stays
            value = orientation(data[i + 8:i + 8 + n])  # how the picture is turned
            if value != 1:
                out.append(chunk(b"eXIf", tiff_with(value)))
        elif kind not in PNG_DROP:  # the header, the palette, the picture, the colour information
            out.append(data[i:end])
        i = end  # the next chunk
        if kind == b"IEND":  # the end: nothing after it is kept
            return b"".join(out)
    raise ValueError("photo")  # no end chunk


def clean(data: bytes, kind: str) -> bytes:
    """The photo's bytes without its metadata, by its kind ("jpg" or "png")."""
    return clean_jpeg(data) if kind == "jpg" else clean_png(data)


# ---------------------------------------------------------------- the panel's small copy

THUMB_MAX = 480  # the widest small copy a request may ask for: the panel shows the photo about 120 px wide, twice that on a sharp screen
_thumbs: dict = {}  # (path, inode, mtime, size, width) -> (bytes, type): one photo at a time, so it never grows past a few entries
_thumbs_lock = threading.Lock()  # request threads ask at the same time


def thumbnail(path, width: int):
    """A small copy of the photo file at path for the panel's own display, at most width pixels wide: (bytes, type), or None
    when the original should be sent instead (Pillow is not installed, the photo is that small already, or it cannot be read).
    The resume, the PDF and the Word file read the original file itself and never this copy. Remembered while the file is
    unchanged, so the page's every draw does not decode the picture again."""
    try:
        st = path.stat()  # which version of the file
    except OSError:  # gone meanwhile
        return None
    key = (str(path), st.st_ino, st.st_mtime_ns, st.st_size, width)  # a new photo is a new file (set_photo removes the old one first)
    with _thumbs_lock:
        if key in _thumbs:  # made before from this very file
            return _thumbs[key]
    made = _make_thumbnail(path.read_bytes(), width)  # outside the lock: decoding takes a moment
    with _thumbs_lock:
        _thumbs.clear()  # older photos' copies go: only the one kept now is asked for
        _thumbs[key] = made  # None is remembered too: the original is sent without trying again
    return made


def _make_thumbnail(data: bytes, width: int):
    """The small copy itself: upright (the orientation the clean file kept is applied, as the copy carries no EXIF), JPEG for
    a picture without transparency, PNG for one with it."""
    try:
        from PIL import Image, ImageOps  # optional (the pdf and tray extras install it); without it the original is sent
    except ImportError:
        return None
    try:
        # Only the two kinds a photo is taken in (clean() keeps no other): a file that is something else inside reaches none of
        # Pillow's other decoders, whose flaws fill its advisories, whatever Pillow this Python can install.
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(data), formats=("JPEG", "PNG")))  # decoded, and turned upright as the browser would turn the original
        if im.width <= width:  # small already: the original is no larger than a copy would be
            return None
        im.thumbnail((width, width * 4), Image.LANCZOS)  # the width it may have, the height following its shape
        out = io.BytesIO()  # the copy's bytes
        if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):  # see-through parts stay see-through
            im.save(out, "PNG", optimize=True)
            return out.getvalue(), "image/png"
        im.convert("RGB").save(out, "JPEG", quality=85, optimize=True)  # a photograph: a JPEG is a tenth of a PNG's size
        return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001  a file Pillow cannot read: the original goes as it is, and the browser shows what it can
        return None


# ---------------------------------------------------------------- the resume's photo, kept and taken away

PHOTO_KINDS = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png"}  # the start of each file a resume photo may be


def photo_file(api):
    """The resume's photo in the workspace (profile/photo.jpg or .png), or None."""
    return next((f for f in (api.ws.path("profile", "photo.jpg"), api.ws.path("profile", "photo.png")) if f.is_file()), None)


def set_photo(api, data: bytes) -> str | None:
    """A JPEG or a PNG as the resume's photo, by what the file is, not by its name, kept without what the camera
    wrote into it (clean, above). It replaces the one before, which waits in the Trash (put back from there or by the
    change's Undo), and goes on the resume (the setting can take it off again). Returns the old photo's Trash id, or None."""
    kind = next((k for magic, k in PHOTO_KINDS.items() if data.startswith(magic)), None)  # what the bytes are
    if not kind:  # anything else is refused
        raise ValueError("photo")  # the page says to use a JPEG or a PNG
    kept_clean = clean(data, kind)  # no place, phone or time; a broken file is refused here like any other
    kept = remove_photo(api, keep=True)  # one photo at a time: the one before goes to the Trash, never lost
    f = api.ws.path("profile", f"photo.{kind}")  # where it is kept
    f.parent.mkdir(parents=True, exist_ok=True)  # a new workspace has no profile folder yet
    f.write_bytes(kept_clean)  # the picture alone
    api.set_settings({"photo": True})  # on the resume
    return kept  # the old photo's id in the Trash, for the page's Undo


def remove_photo(api, keep: bool = False) -> str | None:
    """The resume's photo taken away. With keep (the person removed it) it waits in the Trash under a name of its own,
    profile/removed-photo-<day>-<time>.<kind>, until it is put back or deleted for good (the Library's removed.py): a second photo
    removed later never takes its place. A new photo that replaces it keeps nothing. Returns the Trash's id of the photo
    kept aside ("photo:<day>-<time>"), or None. A new photo that replaces it keeps it too (set_photo)."""
    with api.ws.lock:  # one writer: a put-back or a deletion never meets this half way
        f, kept = photo_file(api), None  # the photo, if any; its id in the Trash
        if f and keep:  # removed by the person: aside, whole
            base = f"removed-photo-{time.strftime('%Y%m%d-%H%M%S')}"  # the moment it went
            name, n = base, 2  # two removals in one second each keep their own
            while any(api.ws.path("profile", name + ext).exists() for ext in (".jpg", ".png")):
                name, n = f"{base}-{n}", n + 1
            aside = api.ws.path("profile", name + f.suffix)  # removed-photo-20261110-153000.jpg
            retried(os.replace, f, aside)  # moved, not copied: the picture as it was
            os.utime(aside)  # its date says when it was removed
            kept = "photo:" + name[len("removed-photo-"):]  # how the Trash names it
        for f in (api.ws.path("profile", "photo.jpg"), api.ws.path("profile", "photo.png")):  # either kind
            f.unlink(missing_ok=True)  # gone
        return kept


def photo_state(api) -> dict | None:
    """What the page shows of the photo: when it changed (for a fresh picture) and whether it goes on the resume."""
    f = photo_file(api)  # the file, if any
    return {"at": int(f.stat().st_mtime), "on": api.settings().get("photo", True) is not False} if f else None


# ---------------------------------------------------------------- the photos in the Trash (the Library's removed.py asks here)


def kept_photos(ws) -> list[tuple[str, Path]]:
    """The photos the person removed, kept aside by remove_photo, newest first: (id in the Trash, file)."""
    found = []  # (stamp, file)
    folder = ws.path("profile")  # where they wait
    for f in folder.iterdir() if folder.is_dir() else []:
        m = PHOTO.fullmatch(f.name)  # only the names remove_photo gives
        if m and f.is_file() and not f.is_symlink():
            found.append((m.group(1), f))
    return [("photo:" + stamp, f) for stamp, f in sorted(found, reverse=True)]  # the stamps sort as the moments they name


def kept_photo(ws, pid: str) -> Path | None:
    """One removed photo by its id in the Trash, or None."""
    return next((f for i, f in kept_photos(ws) if i == pid), None)


def photo_back(api, pid: str) -> dict:
    """A removed photo, back on the resume's details. A photo added since is not lost: it goes to the Trash under a name of
    its own. Each move leaves every file under a name the Trash lists, so a move that fails hides nothing."""
    ws = api.ws
    with ws.lock:  # one writer
        kept = kept_photo(ws, pid)
        if not kept:  # back already, deleted, or never there
            raise ValueError("removed")
        remove_photo(api, keep=True)  # the photo there now, if any, goes to the Trash first
        dest = ws.path("profile", "photo" + kept.suffix)  # photo.jpg or photo.png
        retried(os.replace, kept, dest)  # then this one takes its place
        os.utime(dest)  # a new date: the page draws it afresh
    return {"photo": pid}


def purge_photo(ws, pid: str):
    """Delete a removed photo for good (the caller, the Trash, holds the locks). Returns what is done outside the locks: the
    panel's small copy of it in memory goes."""
    kept = kept_photo(ws, pid)
    if not kept:
        raise ValueError("removed")
    gone(kept)  # held open elsewhere: said, and kept

    def later() -> None:
        with _thumbs_lock:
            _thumbs.clear()  # the next look makes one of the photo there is
    return later
