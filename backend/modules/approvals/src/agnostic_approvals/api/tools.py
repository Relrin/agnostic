"""Assistant tools over the approvals inbox, read as the asking person."""

from __future__ import annotations

from typing import Literal

from dishka import AsyncContainer
from pydantic import BaseModel, Field

from agnostic_approvals.application.inbox import READ, ApprovalsInbox, Filters, Row
from agnostic_kernel.tools import Source, ToolCall, ToolResult, ToolSpec, clip


class ApprovalsArgs(BaseModel):
    status: Literal["pending", "approved", "rejected", "expired", "cancelled"] = "pending"
    tool: str | None = Field(None, description="Only approvals for this tool, e.g. refund_customer")
    schedule_id: str | None = Field(None, description="Only approvals of runs started by this schedule")
    limit: int = Field(10, ge=1, le=25)


def _row(row: Row) -> dict[str, object]:
    record = row.record
    return {
        "id": record.id,
        "status": row.status,
        "tool": record.tool_name,
        "tool_args": clip(dict(record.tool_args), 300),
        "source": record.source_name or record.agent_id or record.team_id or record.workflow_id,
        "schedule_id": record.schedule_id,
        "user": row.user_name or record.user_id,
        "run_id": record.run_id,
        "session_id": record.session_id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "resolved_by": row.resolver_name or record.resolved_by,
        "resolved_at": record.resolved_at.isoformat() if record.resolved_at else None,
    }


async def list_approvals(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, ApprovalsArgs)
    inbox = await container.get(ApprovalsInbox)
    filters = Filters(status=args.status, tool=args.tool, schedule_id=args.schedule_id)
    found = await inbox.list(call.principal, call.instance_id, filters, page=1, limit=args.limit)
    path = f"/i/{call.instance_slug}/approvals"
    sources = [
        Source("approval", f"Approval · {row.record.tool_name or row.record.id}", f"{path}?approval={row.record.id}")
        for row in found.rows[:5]
    ]
    return ToolResult(
        {
            "status": args.status,
            "total": found.total,
            "truncated": found.truncated,
            "oldest_pending_at": found.oldest_pending_at.isoformat() if found.oldest_pending_at else None,
            "approvals": [_row(row) for row in found.rows],
        },
        sources or [Source("approvals", "Approvals", f"{path}?status={args.status}")],
    )


TOOLS = (
    ToolSpec(
        "list_approvals",
        "Runs paused for a person's approval, by status: which tool, its arguments, who asked and who resolved it.",
        list_approvals,
        ApprovalsArgs,
        READ,
    ),
)
