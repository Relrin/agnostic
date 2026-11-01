"""Code-defined workflows (path mapping: app/workflows/*.py)."""

from app.workflows.daily_brief import daily_brief
from app.workflows.refund_review import refund_review
from app.workflows.ticket_router import ticket_router

WORKFLOWS = [ticket_router, daily_brief, refund_review]
