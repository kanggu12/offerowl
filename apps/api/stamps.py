"""A file's version without reading it, and the short hashes of files that the panel's every poll asks for: worked out
once while the file is unchanged (apps/api/tasks.py and the modules beside it name them)."""
from __future__ import annotations

import hashlib  # hashes
import json  # files
import threading  # threads and locks
import time  # clocks
from pathlib import Path  # paths


RACY_NS = 2_000_000_000  # a file changed less than this long ago is read again: a second write in the same clock tick (or a FAT disk's two seconds) keeps the stamp
HASH_CACHE_MAX = 4096  # remembered hashes before the memory starts over: a workspace's decks and builds stay far below it
_hash_cache: dict = {}  # (kind, path, stamp) -> hash, so the panel's poll reads each unchanged file once, not every few seconds
_hash_lock = threading.Lock()  # request threads and tasks hash at the same time


def file_stamp(path: Path):
    """What tells a file's version without reading it: (inode, mtime in ns, size). None when it is missing, or when it changed
    so recently that a second write in the same clock tick could keep the same stamp (that file is read every time, as git
    does with its own racy entries). Every write in the workspace goes through a rename (write_json), which gives a new inode."""
    try:
        st = path.stat()  # one system call
    except OSError:  # missing, or no access
        return None
    if time.time_ns() - st.st_mtime_ns < RACY_NS:  # written just now: the stamp alone cannot be trusted yet
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)  # a rewrite changes at least one of these


def _cached(kind: str, path: Path, make):
    """make(path) remembered under the file's stamp: worked out again only when the file changed."""
    stamp = file_stamp(path)  # None: read it now, remember nothing
    if stamp is None:
        return make(path)
    key = (kind, str(path), stamp)  # the kind of hash, which file, which version of it
    with _hash_lock:  # read under the lock: another thread may be clearing the memory
        if key in _hash_cache:
            return _hash_cache[key]
    value = make(path)  # outside the lock: hashing a large file never holds the other threads
    with _hash_lock:
        if len(_hash_cache) >= HASH_CACHE_MAX:  # files come and go (builds, decks): start over rather than grow without end
            _hash_cache.clear()
        _hash_cache[key] = value
    return value


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else ""  # a missing file hashes as empty, never raises


def file_hash(path: Path) -> str:
    """A short hash of a file's bytes ("" when it is missing): tells a stale translation or build from a fresh one. Remembered
    while the file is unchanged (file_stamp)."""
    return _cached("bytes", path, _file_hash)


def _content_hash(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))  # its content
    except (OSError, ValueError):  # missing or broken
        return ""
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]  # one spelling of it


def content_hash(path: Path) -> str:
    """A short hash of a JSON file's content, whatever its spacing or key order ("" when it is missing or unreadable): a
    profile written again with the same content (a rebuild, a tool's own formatting) is the same profile. Remembered while the
    file is unchanged (file_stamp)."""
    return _cached("content", path, _content_hash)
