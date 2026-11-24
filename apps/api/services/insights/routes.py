"""The Insights service's endpoint, as the gateway (apps/api/routes.py) gathers it (core/routing.py says how a table is
read)."""
from __future__ import annotations

from ...core.routing import JSON  # the answer's type
from . import insights  # the numbers


def get_insights(a, q, m):
    """GET /api/v1/insights: the Insights view's numbers: progress, evidence, fit by area, readiness."""
    return 200, insights.summary(a), JSON  # counted on demand


GET = (  # the reads
    ("/api/v1/insights", get_insights),
)
POST = ()  # the Insights write nothing
UPLOADS = ()  # and take no file
