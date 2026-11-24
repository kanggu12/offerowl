"""What every service's table and the gateway share, with no HTTP in it (apps/api/routes.py gathers the tables, web.py puts
them behind HTTP): the answer types, the request's language, and how a table names its routes.

A table is three tuples in a service's routes.py:

    GET     (matcher, handler(api, query, match) -> (status, answer, content type))
    POST    (matcher, handler(api, body, path) -> the answer's fields, or None)
    UPLOADS (Upload(path, handler(api, query, name, data) -> the answer's fields, ...))

A matcher is a path ("/api/v1/jobs"), a tuple of paths, or a pattern's match or fullmatch method, called with the path (the
match it returns reaches the handler). The gateway tries the tables one after the other and the first route that matches
answers; no two routes of any tables match one path (tests/app/test_architecture.py checks it), so their order never
decides an answer.
"""
from __future__ import annotations

import json  # an answer as bytes

JSON = "application/json; charset=utf-8"  # most answers
LANGS = ("ko", "en")  # the languages an edition is made in (the documents' LANGS says the same)


class NotFound(Exception):
    """A path the API does not have (a KeyError from a bug must stay a 500)."""


class FileStream:
    """A file on disk sent in pieces (web.py), then deleted when it was made for this answer: a workspace's backup."""

    def __init__(self, path, delete: bool = True, headers: dict | None = None):
        self.path, self.delete, self.headers = path, delete, dict(headers or {})


class FileAnswer(bytes):
    """A file's bytes with headers of its own (web.py sends them): its name for a browser's Save as, and for a web page a
    sandbox, so it runs nothing at the panel's address."""

    def __new__(cls, data: bytes, headers: dict):
        obj = super().__new__(cls, data)  # the bytes themselves, unchanged
        obj.headers = dict(headers)  # what the answer adds
        return obj


class Upload:
    """A file upload route: the raw body (application/octet-stream) with its name in X-File-Name, which web.py reads under
    the route's cap before the handler keeps it. cap: "file" (60 MB), "photo" (10 MB) or "backup" (the edge's own caps,
    web.py), or a function that says the cap at each upload (a job's material: its own). spool: the body goes to a file of
    its own in the data folder, never whole in memory (a backup), and the handler gets that file. whole_name: the name is
    kept whole (the handler shortens it itself), else cut at 200 characters."""

    def __init__(self, path: str, handler, cap="file", spool: bool = False, whole_name: bool = False):
        self.path, self.handler, self.cap, self.spool, self.whole_name = path, handler, cap, spool, whole_name


def matches(matcher, path: str):
    """A route's matcher against a path: the match object of a pattern, True for an exact path, or None."""
    if isinstance(matcher, str):  # one exact path
        return True if path == matcher else None
    if isinstance(matcher, tuple):  # several exact paths, one handler
        return True if path in matcher else None
    return matcher(path)  # a pattern's match or fullmatch


def lang_of(v) -> str:
    """A document language from a request: ko or en, Korean when unknown."""
    return v if v in LANGS else "ko"  # only the editions there are


def dumps(obj) -> bytes:
    """An answer as UTF-8 JSON bytes."""
    return obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")  # Korean stays readable
