"""The Insights service's endpoint, as the gateway (apps/api/routes.py) gathers it (core/routing.py says how a table is
read)."""
from __future__ import annotations

from ...core.routing import JSON, HeadAnswer, cheap_head  # the answer's type, and a HEAD that counts nothing
from . import insights  # the numbers


def head_insights(a, q, m):
    """HEAD /api/v1/insights: the headers, with nothing counted (counting takes up to a second, D4-04)."""
    return 200, HeadAnswer(), JSON


@cheap_head(head_insights)
def get_insights(a, q, m):
    """GET /api/v1/insights: the Insights view's numbers: progress, evidence, fit by area, readiness."""
    return 200, insights.summary(a), JSON  # counted on demand


GET = (  # the reads
    ("/api/v1/insights", get_insights),
)
POST = ()  # the Insights write nothing
UPLOADS = ()  # and take no file
