"""Assistant tools over Studio components: a version's configuration and what changed between two versions."""

from __future__ import annotations

from typing import Any

from dishka import AsyncContainer
from pydantic import BaseModel, Field

from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.tools import Source, ToolCall, ToolResult, ToolSpec, clip
from agnostic_studio.application.access import READ_SCOPE, StudioAccess
from agnostic_studio.application.drafts import Drafts
from agnostic_studio.facade import StudioFacade

CONFIG_CHARS = 6000
MAX_CHANGES = 40


class ConfigArgs(BaseModel):
    component_id: str = Field(description="Agent, team or workflow id")
    version: int | None = Field(None, description="Version number; default: the live version, else the newest")


class DiffArgs(BaseModel):
    component_id: str
    from_version: int
    to_version: int


def component_source(call: ToolCall, kind: str, component_id: str, name: str) -> Source:
    return Source(kind, f"{kind.capitalize()} {name}", f"/i/{call.instance_slug}/studio/{kind}s/{component_id}")


async def get_component_config(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, ConfigArgs)
    instance = await (await container.get(StudioAccess)).instance(call.principal, call.instance_id)
    studio = await container.get(StudioFacade)
    state = await studio.component(call.principal, instance, args.component_id)
    if state is None:
        raise NotFoundError(f"There is no component {args.component_id!r} on {instance.display_name}.")
    version = args.version or state.current_version or state.latest_version
    if version is None:
        raise NotFoundError(f"{state.name} has no versions yet.")
    snapshot = await studio.snapshot(call.principal, instance, state.id, version)
    value: dict[str, Any] = {
        "component": {"id": state.id, "kind": state.kind, "name": state.name},
        "version": version,
        "stage": snapshot.stage,
        "live_version": state.current_version,
        "draft_version": state.draft_version,
        "author": snapshot.author_name,
        "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
        "config": clip(snapshot.config, CONFIG_CHARS),
    }
    return ToolResult(value, [component_source(call, state.kind, state.id, state.name)])


async def diff_versions(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, DiffArgs)
    diff = await (await container.get(Drafts)).diff(
        call.principal, call.instance_id, args.component_id, args.from_version, args.to_version
    )
    component = diff.component
    return ToolResult(
        {
            "component": {"id": component.id, "kind": component.kind, "name": component.name},
            "from_version": diff.from_version,
            "to_version": diff.to_version,
            "summary": diff.summary,
            "lines_added": diff.lines_added,
            "lines_removed": diff.lines_removed,
            "changes": [
                {
                    "path": change.path,
                    "op": change.op,
                    "before": clip(change.before, 300),
                    "after": clip(change.after, 300),
                }
                for change in diff.changes[:MAX_CHANGES]
            ],
            "changes_omitted": max(0, len(diff.changes) - MAX_CHANGES),
        },
        [component_source(call, component.kind, component.id, component.name)],
    )


TOOLS = (
    ToolSpec(
        "get_component_config",
        "The configuration of an agent, team or workflow version: model, instructions, tools, members, steps.",
        get_component_config,
        ConfigArgs,
        READ_SCOPE,
    ),
    ToolSpec(
        "diff_versions",
        "What changed between two versions of an agent, team or workflow, field by field.",
        diff_versions,
        DiffArgs,
        READ_SCOPE,
    ),
)
