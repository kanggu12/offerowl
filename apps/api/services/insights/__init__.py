"""The Insights service: the numbers of the Insights view (GET /api/v1/insights), counted from the applications, their
fits, the facts and the interview kits as they are now. Read only: nothing here writes.

Owns: no file. It reads through the services that keep the data: applications (the jobs, their fits and the days of
their stages), interview (how far each kit answers its likely questions) and the profile's facts and details (the
composition root's Facts).

    routes.py    its endpoint (the gateway gathers it)
    insights.py  every number the view draws

Offers: its endpoint only; no other part calls it in this process.
"""
from .routes import GET as GET_ROUTES, POST as POST_ROUTES, UPLOADS as UPLOAD_ROUTES  # noqa: F401  its endpoints, which the gateway gathers
