"""The Library service's endpoints, as the gateway (apps/api/routes.py) gathers them: each path or pattern with its
handler. A read answers (status, answer, content type); a write answers the fields of its {"ok": true, ...}, or None; an
upload keeps the file it was sent (core/routing.py says how a table is read). The files it opens are the other services':
each names its own."""
from __future__ import annotations

import re  # paths
import time  # the day a backup's name carries
import urllib.parse  # job ids in paths

from .. import applications, documents, interview, profile  # a job's posting, a copy that went out, a kit's files, a source
from ...core.routing import JSON, FileAnswer, FileStream, HeadAnswer, NotFound, Upload, cheap_head, text_field  # the answers' shapes, a cheap HEAD, an upload's route, a request's text
from . import backup, library, removed  # the backup, the Library's file rules, the Trash

JOBFILE = re.compile(r"^/api/v1/jobs/([0-9A-Za-z가-힣%-]+)/(posting|sent/[A-Za-z0-9_.-]{1,80}|kit/(?:out/)?[A-Za-z0-9_.%()-]{1,240})$")  # a job's posting, a copy that went out, a file of its interview kit
SOURCE = re.compile(r"^/api/v1/materials/(m\d{1,6})$")  # a file brought in for the profile, as it came


# ------------------------------------------------------------------ reads


def get_job_file(a, q, m):
    """GET /api/v1/jobs/<job>/posting, /sent/<name>, /kit/<name> and /kit/out/<name>: the Library's files of one job."""
    jid, part = a.need_job({"job": urllib.parse.unquote(m.group(1))}), m.group(2)  # it exists
    if part == "posting":  # the posting as it was read
        f, name = applications.posting_file(a.ws, jid), "posting.md"
    elif part.startswith("sent/"):  # only a copy the lock recorded
        f, name = documents.sent_file(a.ws, jid, part[5:]), part[5:]
    else:  # kit/<name> or kit/out/<name>
        rest = urllib.parse.unquote(part[4:])  # after "kit/": a Hangul name comes percent-encoded
        f = interview.kit_file(a.ws, jid, rest[4:], out=True) if rest.startswith("out/") else interview.kit_file(a.ws, jid, rest)
        name = rest.rsplit("/", 1)[-1]
    if not f or not f.is_file():  # not there, or not one of its files
        raise NotFound(m.group(0))  # 404
    data, ctype, headers = library.answer(f, name)  # with its type and its name
    return 200, FileAnswer(data, headers), ctype


def get_source(a, q, m):
    """GET /api/v1/materials/<id>: a file brought in for the profile, byte for byte under the name it came with."""
    found = profile.source_file(a.ws, m.group(1))  # listed, not taken off
    if not found:
        raise NotFound(m.group(0))  # 404
    data, ctype, headers = library.answer(*found)  # byte for byte, under the name it came with
    return 200, FileAnswer(data, headers), ctype


def head_json(a, q, m):
    """HEAD of a listing: its headers, with nothing listed (D4-04: the Library's took 3 s under load)."""
    return 200, HeadAnswer(), JSON


@cheap_head(head_json)
def get_library(a, q, m):
    """GET /api/v1/library: every file brought in or made, with what can be done to each."""
    return 200, library.listing(a), JSON  # listed on demand


@cheap_head(head_json)
def get_removed(a, q, m):
    """GET /api/v1/removed: what was taken off, to put back or delete for good, and the folders restores kept aside."""
    return 200, removed.listing(a), JSON  # listed on demand


def backup_name() -> str:
    """The backup's file name as a browser saves it: underscores and the day, as every file Offerowl hands out is named
    (offerowl_backup_20261126.zip; it was offerowl-backup-2026-11-26.zip, and the answer did not even carry it, B4-04)."""
    return f"offerowl_backup_{time.strftime('%Y%m%d')}.zip"  # the day on this PC


def backup_headers() -> dict:
    """What a backup's answer says of its file: saved under its name, never shown."""
    return {"Content-Disposition": f'attachment; filename="{backup_name()}"'}  # ASCII only, so one spelling serves every browser


def head_backup(a, q, m):
    """HEAD /api/v1/workspace/backup: the headers a download gets, with no backup made (D4-04: it made the whole zip, 762 MB
    in 7 s, and held a request slot meanwhile, only to send these)."""
    return 200, HeadAnswer(backup_headers()), "application/zip"


@cheap_head(head_backup)
def get_backup(a, q, m):
    """GET /api/v1/workspace/backup: the whole workspace as one file. With ?check=1, only whether the disk has room for it
    now ({room, need}, or disk_full): the page asks first, since a download that fails shows nothing it can word."""
    if q.get("check") == "1":  # the page's question before the download
        return 200, backup.check_room(a.ws), JSON
    return 200, FileStream(backup.write_file(a.ws), headers=backup_headers()), "application/zip"  # a file to save, sent in pieces (hundreds of MB), under its name


# ------------------------------------------------------------------ writes


def post_put_back(a, req, path):
    """POST /api/v1/removed/restore: one thing taken off, put back."""
    return removed.restore(a, text_field(req, "id"))  # what came back, and whether a source is to be read again


def post_delete(a, req, path):
    """POST /api/v1/removed/delete: deleted for good: one thing taken off, or every one ({"all": true})."""
    return removed.delete(a, text_field(req, "id"), every=req.get("all") is True)  # the ids that went


def post_export(a, req, path):
    """POST /api/v1/library/export: one Library row's file on the Desktop, exactly that file."""
    return {"exported": [library.export(a, text_field(req, "id"))]}  # the name written


# ------------------------------------------------------------------ uploads


def upload_backup(a, q, name, f):
    """POST /api/v1/workspace/restore: a backup in the workspace's place, from the file its body was written to. The
    workspace as it was stays beside it, and its folder is named in the answer."""
    return backup.restore_workspace(a, f)  # the workspace, from the file; the page reloads


GET = (  # the reads
    (JOBFILE.match, get_job_file),
    (SOURCE.match, get_source),
    ("/api/v1/library", get_library),
    ("/api/v1/removed", get_removed),
    ("/api/v1/workspace/backup", get_backup),
)
POST = (  # the writes
    ("/api/v1/removed/restore", post_put_back),
    ("/api/v1/removed/delete", post_delete),
    ("/api/v1/library/export", post_export),
)
UPLOADS = (  # the files sent as they are
    Upload("/api/v1/workspace/restore", upload_backup, cap="backup", spool=True),  # into the data folder beside the workspace, never whole in memory
)
