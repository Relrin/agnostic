"""Approval decisions: argument diffs and the ``continue`` payload per component kind.

AgentOS keeps resolving an approval and resuming its run separately (``/approvals/{id}/resolve`` never resumes). The
continuation tells the paused run what happened: agents take ``tools`` (tool executions with ``confirmed`` and the
possibly edited ``tool_args``), teams take ``requirements``, workflows take ``step_requirements``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

type Decision = Literal["approve", "reject"]
type Family = Literal["agents", "teams", "workflows"]


class ApprovalShapeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Approval:
    """The parts of an AgentOS ``ApprovalResponse`` a decision needs."""

    id: str
    status: str
    run_id: str | None
    session_id: str | None
    user_id: str | None
    agent_id: str | None
    team_id: str | None
    workflow_id: str | None
    tool_name: str | None
    tool_args: Mapping[str, Any]
    requirements: list[dict[str, Any]]
    context: Mapping[str, Any]

    @classmethod
    def parse(cls, body: Mapping[str, Any]) -> Approval:
        try:
            approval_id = str(body["id"])
        except KeyError as exc:
            raise ApprovalShapeError("the approval has no id") from exc
        raw_requirements: Any = body.get("requirements") or []
        if isinstance(raw_requirements, dict):
            raw_requirements = [raw_requirements]
        return cls(
            id=approval_id,
            status=str(body.get("status") or "pending"),
            run_id=_str(body.get("run_id")),
            session_id=_str(body.get("session_id")),
            user_id=_str(body.get("user_id")),
            agent_id=_str(body.get("agent_id")),
            team_id=_str(body.get("team_id")),
            workflow_id=_str(body.get("workflow_id")),
            tool_name=_str(body.get("tool_name")),
            tool_args=cast("Mapping[str, Any]", body.get("tool_args") or {}),
            requirements=[
                cast("dict[str, Any]", item) for item in cast("list[Any]", raw_requirements) if isinstance(item, dict)
            ],
            context=cast("Mapping[str, Any]", body.get("context") or {}),
        )

    @property
    def component(self) -> tuple[Family, str]:
        """The paused run's owner: a workflow wins over a team, a team over an agent (members pause their parent)."""
        if self.workflow_id:
            return "workflows", self.workflow_id
        if self.team_id:
            return "teams", self.team_id
        if self.agent_id:
            return "agents", self.agent_id
        raise ApprovalShapeError(f"approval {self.id} names no agent, team or workflow")

    @property
    def pending(self) -> bool:
        return self.status == "pending"


def _str(value: object) -> str | None:
    return str(value) if value not in {None, ""} else None


def args_diff(before: Mapping[str, Any], after: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Per-argument ``{"before", "after"}`` for every argument the reviewer changed, added or removed."""
    if after is None:
        return {}
    changed: dict[str, dict[str, Any]] = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            changed[key] = {"before": old, "after": new}
    return changed


def _tool_execution(requirement: dict[str, Any]) -> dict[str, Any]:
    nested = requirement.get("tool_execution") or requirement.get("tool")
    return cast("dict[str, Any]", nested) if isinstance(nested, dict) else requirement


def _apply(execution: dict[str, Any], approval: Approval, decision: Decision, edited: Mapping[str, Any] | None) -> None:
    execution["confirmed"] = decision == "approve"
    if edited is not None and execution.get("tool_name", approval.tool_name) == approval.tool_name:
        execution["tool_args"] = dict(edited)


def _fallback_execution(approval: Approval) -> dict[str, Any]:
    call_id = approval.context.get("tool_call_id") or approval.context.get("call_id")
    return {
        "tool_call_id": call_id,
        "tool_name": approval.tool_name,
        "tool_args": dict(approval.tool_args),
        "requires_confirmation": True,
    }


def continue_form(
    approval: Approval, decision: Decision, edited_args: Mapping[str, Any] | None
) -> tuple[Family, str, dict[str, str]]:
    """``(family, component id, form fields)`` for ``POST /{family}/{id}/runs/{run_id}/continue``.

    The run continues in the background without streaming; whoever watches the run picks it up with ``/resume``.
    """
    family, component_id = approval.component
    requirements = copy.deepcopy(approval.requirements)
    form: dict[str, str] = {"stream": "false", "background": "true"}
    if approval.session_id:
        form["session_id"] = approval.session_id
    if approval.user_id:
        form["user_id"] = approval.user_id

    if family == "agents":
        executions = [_tool_execution(item) for item in requirements] or [_fallback_execution(approval)]
        for execution in executions:
            _apply(execution, approval, decision, edited_args)
        form["tools"] = json.dumps(executions)
    elif family == "teams":
        items = requirements or [{"tool_execution": _fallback_execution(approval)}]
        for item in items:
            _apply(_tool_execution(item), approval, decision, edited_args)
            item["confirmation"] = decision == "approve"
        form["requirements"] = json.dumps(items)
    else:
        items = requirements or [{"requires_confirmation": True}]
        for item in items:
            item["confirmed"] = decision == "approve"
            if decision == "reject":
                item["rejected"] = True
            if edited_args is not None and item.get("requires_user_input"):
                item["user_input"] = dict(edited_args)
        form["step_requirements"] = json.dumps(items)
    return family, component_id, form
