"""Code-defined workflows (path mapping: app/workflows/*.py)."""

from app.workflows.daily_brief import daily_brief
from app.workflows.ticket_router import ticket_router

WORKFLOWS = [ticket_router, daily_brief]
