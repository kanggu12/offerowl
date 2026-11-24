"""The profile service's endpoints, as the gateway (apps/api/routes.py) gathers them: each path with its handler. A read
answers (status, answer, content type); a write answers the fields of its {"ok": true, ...}, or None; an upload keeps the
file it was sent (core/routing.py says how a table is read)."""
from __future__ import annotations

from ...core.routing import JSON, NotFound, Upload  # the answers' shapes, and an upload's route
from . import actions, masks, photo, sources, style  # the person's actions on the facts, the mask table, the photo, the sources, the style packs


# ------------------------------------------------------------------ reads


def get_photo(a, q, m):
    """GET /api/v1/photo: the resume's photo, for the details card; with ?w=240 the panel's small copy."""
    f = photo.photo_file(a)  # the file, if any
    if not f:  # none kept
        raise NotFound("/api/v1/photo")  # 404
    if q.get("w"):  # ?w=240: the panel's small copy, a fraction of the bytes the page would decode to draw it 120 px wide
        w = int(q["w"]) if str(q["w"]).isdigit() else 0  # a width in pixels
        small = photo.thumbnail(f, max(16, min(w, photo.THUMB_MAX))) if w else None  # None: no Pillow, or small already
        if small:
            return 200, small[0], small[1]  # JPEG, or PNG for one with see-through parts
    return 200, f.read_bytes(), "image/jpeg" if f.suffix == ".jpg" else "image/png"  # as it was sent


def get_blind(a, q, m):
    """GET /api/v1/blind: the blind edition's mask table, the person's own, else the shipped one."""
    return 200, masks.blind_read(a), JSON  # {table, own, counts, stamp}


def get_profile(a, q, m):
    """GET /api/v1/profile: the profile, its readiness and its schema check."""
    from core.schema import validate  # the data model
    prof = a.facts.profile()  # as built from the kept facts
    from .facts import problems  # readiness
    return 200, {"profile": prof, "problems": problems(prof), "schema": validate.check("profile", prof)}, JSON  # shape problems too


def get_facts(a, q, m):
    """GET /api/v1/facts: the facts with their states."""
    return 200, a.facts.view(), JSON  # rows and counts


def get_style(a, q, m):
    """GET /api/v1/style: the writing rules in use, their name and the pack as written, claims included (the harness's memory)."""
    return 200, style.style_read(a), JSON


# ------------------------------------------------------------------ writes


def post_read(a, req, path):
    """POST /api/v1/materials/read: read the listed materials."""
    return {"started": a.tasks.ingest([str(x) for x in req.get("ids") or []])}  # False when a reading already runs


def post_remove(a, req, path):
    """POST /api/v1/materials/remove: take a file and its facts out."""
    sources.remove_material(a, str(req.get("id") or ""))  # undoable
    return None  # the new state is the whole answer


def post_example(a, req, path):
    """POST /api/v1/example: the fictional example person, for a first look."""
    return {"material": sources.add_example(a, req.get("lang"))}  # read at once, in the page's language


def post_decide(a, req, path):
    """POST /api/v1/facts/decide: keep, drop, edit or put back one fact."""
    actions.fact(a, req)  # one undo step
    return None  # the new state is the whole answer


def post_keep_all(a, req, path):
    """POST /api/v1/facts/keep-all: keep every fact still to confirm."""
    return {"kept": actions.keep_all(a, str(req.get("material") or "") or None)}  # how many (one material's, when named)


def post_add_fact(a, req, path):
    """POST /api/v1/facts/add: a fact the person typed."""
    return {"cid": actions.add_fact(a, req)}  # its id


def post_details(a, req, path):
    """POST /api/v1/details: "Your details", autosaved while typing."""
    actions.details(a, req)  # one undo step per field and pause
    return None  # the new state is the whole answer


def post_translate(a, req, path):
    """POST /api/v1/translate: the English profile for English editions."""
    return {"started": a.tasks.translate(a.job_in(req))}  # False when one already runs; the job's draft decides how much is asked


def post_photo_remove(a, req, path):
    """POST /api/v1/photo/remove: the resume's photo removed; it waits in the Trash, which puts it back or deletes it for good."""
    return {"removed": photo.remove_photo(a, keep=True)}  # its id in the Trash, for the note's Undo (/api/v1/removed/restore)


def post_blind(a, req, path):
    """POST /api/v1/blind: the person's own mask table for the blind edition, replaced or taken away."""
    return {"blind": masks.set_blind(a, req)}  # the new summary


def post_style(a, req, path):
    """POST /api/v1/style: a person's own writing rules, added and chosen."""
    name = style.add_style(a, req)  # checked and kept
    a.set_settings({"style": name})  # in use from now on
    return {"style": name}  # the name it is kept under


def post_style_rule(a, req, path):
    """POST /api/v1/style/rule: one correction of the person's kept as a rule of the pack in use, so it never comes back."""
    return style.add_rule(a, req)  # {style, list, lang, rows}: checked like a whole pack, one undo step


def post_onboarding(a, req, path):
    """POST /api/v1/onboarding: where the first run stands."""
    actions.set_onboarding(a, req)  # kept with the workspace
    return None  # the new state is the whole answer


# ------------------------------------------------------------------ uploads


def upload_source(a, q, name, data):
    """POST /api/v1/materials: one file for the workspace's sources; a zip gives each file in it."""
    recs = a.ws.add_materials(name, data)  # kept in sources/; a program, or a file that is not the kind its name says, is refused
    if not recs:  # a zip with nothing a reader knows
        raise ValueError("empty")  # the page says so
    return {"material": recs[0], "materials": recs}  # the page then asks to read them


def upload_photo(a, q, name, data):
    """POST /api/v1/photo: the resume's photo (JPEG or PNG), in the workspace's profile folder."""
    return {"replaced": photo.set_photo(a, data)}  # checked and kept; the one before went to the Trash, for the page's Undo


GET = (  # the reads
    ("/api/v1/photo", get_photo),
    ("/api/v1/blind", get_blind),
    ("/api/v1/profile", get_profile),
    ("/api/v1/facts", get_facts),
    ("/api/v1/style", get_style),
)
POST = (  # the writes
    ("/api/v1/materials/read", post_read),
    ("/api/v1/materials/remove", post_remove),
    ("/api/v1/example", post_example),
    ("/api/v1/facts/decide", post_decide),
    ("/api/v1/facts/keep-all", post_keep_all),
    ("/api/v1/facts/add", post_add_fact),
    ("/api/v1/details", post_details),
    ("/api/v1/translate", post_translate),
    ("/api/v1/photo/remove", post_photo_remove),
    ("/api/v1/blind", post_blind),
    ("/api/v1/style", post_style),
    ("/api/v1/style/rule", post_style_rule),
    ("/api/v1/onboarding", post_onboarding),
)
UPLOADS = (  # the files sent as they are
    Upload("/api/v1/materials", upload_source),  # up to 60 MB
    Upload("/api/v1/photo", upload_photo, cap="photo"),  # up to 10 MB: a phone's full-size picture fits
)
