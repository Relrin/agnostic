"""Request and response bodies of ``/api/v1/instances/{instance}/approvals``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_approvals.application.decide import DecideResult


class DecideIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000)
    edited_args: dict[str, Any] | None = Field(
        default=None, description="Replacement tool arguments (approve only); the change is audited as a diff"
    )


class DecideOut(BaseModel):
    approval_id: str
    instance_id: str
    decision: Literal["approve", "reject"]
    status: str = Field(description="approved, rejected, or what someone else decided first")
    run_id: str | None
    session_id: str | None
    continue_state: Literal["continued", "pending_admin", "conflict", "failed", "skipped"]
    continue_detail: str | None
    already_resolved: bool
    args_changed: list[str]

    @classmethod
    def from_result(cls, result: DecideResult) -> DecideOut:
        return cls(
            approval_id=result.approval_id,
            instance_id=result.instance_id,
            decision=result.decision,
            status=result.status,
            run_id=result.run_id,
            session_id=result.session_id,
            continue_state=result.continue_state,
            continue_detail=result.continue_detail,
            already_resolved=result.already_resolved,
            args_changed=list(result.args_changed),
        )


class CountOut(BaseModel):
    instance_id: str
    count: int | None = Field(description="None when the instance has approvals disabled or didn't answer")
    available: bool
