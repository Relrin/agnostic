"""Assistant tools over sessions, read through the passthrough pipeline as the asking person."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from dishka import AsyncContainer
from pydantic import BaseModel, Field

from agnostic_gateway.facade import GatewayFacade
from agnostic_kernel.errors import AppError, ForbiddenError, NotFoundError
from agnostic_kernel.tools import Source, ToolCall, ToolResult, ToolSpec, clip

FORBIDDEN = 403
NOT_FOUND = 404
MAX_RUNS = 20


class SessionsArgs(BaseModel):
    component_id: str | None = Field(None, description="Only sessions of this agent, team or workflow id")
    user_id: str | None = Field(None, description="Only sessions of this end user")
    limit: int = Field(10, ge=1, le=25)


class SessionArgs(BaseModel):
    session_id: str


async def _json(container: AsyncContainer, call: ToolCall, path: str, params: Mapping[str, str | int]) -> Any:  # noqa: ANN401
    gateway = await container.get(GatewayFacade)
    instance = await gateway.instance(call.instance_id)
    response = await gateway.call(call.principal, instance, "GET", path, params=params)
    body: object = response.body
    message = (
        str(cast("dict[str, object]", body).get("detail")) if isinstance(body, dict) else f"HTTP {response.status}"
    )
    if response.status == FORBIDDEN:
        raise ForbiddenError(message)
    if response.status == NOT_FOUND:
        raise NotFoundError(message)
    if not response.ok:
        raise AppError(message)
    return cast("Any", body)


def _items(payload: object) -> list[dict[str, Any]]:
    data = cast("dict[str, Any]", payload).get("data") if isinstance(payload, dict) else payload
    return [cast("dict[str, Any]", item) for item in cast("list[Any]", data or []) if isinstance(item, dict)]


def _component(item: Mapping[str, Any]) -> str | None:
    for key, kind in (("workflow_id", "workflow"), ("team_id", "team"), ("agent_id", "agent")):
        if item.get(key):
            return f"{kind}:{item[key]}"
    return None


def session_source(call: ToolCall, session_id: str, name: object = None) -> Source:
    label = f"Session {name}" if name else f"Session {session_id[:12]}"
    return Source("session", label, f"/i/{call.instance_slug}/sessions/{session_id}")


async def list_sessions(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, SessionsArgs)
    params: dict[str, str | int] = {"page": 1, "limit": args.limit, "sort_by": "updated_at", "sort_order": "desc"}
    if args.component_id:
        params["component_id"] = args.component_id
    if args.user_id:
        params["user_id"] = args.user_id
    items = _items(await _json(container, call, "/sessions", params))
    rows = [
        {
            "session_id": item.get("session_id"),
            "name": item.get("session_name"),
            "component": _component(item),
            "user_id": item.get("user_id"),
            "total_tokens": item.get("total_tokens"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        for item in items
    ]
    sources = [session_source(call, str(row["session_id"]), row["name"]) for row in rows[:5] if row["session_id"]]
    return ToolResult({"sessions": rows}, sources)


def _run(run: Mapping[str, Any]) -> dict[str, Any]:
    tools = cast("list[Any]", run.get("tools") or [])
    return {
        "run_id": run.get("run_id"),
        "component": _component(run),
        "status": run.get("status"),
        "created_at": run.get("created_at"),
        "user_message": clip(run.get("run_input")),
        "answer": clip(run.get("content")),
        "tools": [
            {
                "name": tool.get("tool_name"),
                "tool_args": clip(tool.get("tool_args"), 300),
                "error": bool(tool.get("tool_call_error")),
            }
            for tool in (cast("dict[str, Any]", t) for t in tools if isinstance(t, dict))
        ],
    }


async def get_session(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, SessionArgs)
    runs = _items(await _json(container, call, f"/sessions/{args.session_id}/runs", {}))
    return ToolResult(
        {
            "session_id": args.session_id,
            "runs": [_run(run) for run in runs[-MAX_RUNS:]],
            "runs_omitted": max(0, len(runs) - MAX_RUNS),
        },
        [session_source(call, args.session_id)],
    )


TOOLS = (
    ToolSpec(
        "list_sessions",
        "Recent chat sessions, most recently active first, optionally for one component or end user.",
        list_sessions,
        SessionsArgs,
        "sessions:read",
    ),
    ToolSpec(
        "get_session",
        "The runs of one session: what the user asked, the answer, the tools called and each run's status.",
        get_session,
        SessionArgs,
        "sessions:read",
    ),
)
