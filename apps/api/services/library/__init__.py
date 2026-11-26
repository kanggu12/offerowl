"""The Library service: every file the person brought in and every file Offerowl made, in one list with what can be done
to each (the Library, GET /api/v1/library); what the person took off, to put back or delete for good (the Trash, GET
/api/v1/removed); and the whole workspace as one file, saved and restored (the backup).

Owns: no file of the workspace. The folders a restore keeps aside beside it are its own. It lists, puts back, deletes and
backs up through the services that keep each file: profile (the sources and the photo), applications (the jobs'
postings and materials), documents (the editions' printed files and the copies that went out), interview (the kits'
files) and agent (the finished runs). A job's card and folder, and the Trash's marks on them, are the core's workspace.

    routes.py    its endpoints: each path or pattern with its handler (the gateway gathers them)
    library.py   the Library's rows, a row's file opened or copied to the Desktop
    removed.py   the Trash: its rows and counts, putting back, deleting for good with the undo steps rewritten once
    backup.py    the workspace zipped, and a backup put in its place with the old one kept aside

Offers: removed_counts (how many things the Trash holds, for the state). Everything else it does is its endpoints.
"""
from . import backup  # noqa: F401  the backup, whose leftovers the start sweeps
from .removed import counts as removed_counts  # noqa: F401  the Trash's counts, for the state
from .routes import GET as GET_ROUTES, POST as POST_ROUTES, UPLOADS as UPLOAD_ROUTES  # noqa: F401  its endpoints, which the gateway gathers
