"""Resolving an approval and continuing its run, whoever does it.

A person deciding goes through delegated elevation (their ``approvals:write`` checked by the control plane); the
expiry watcher acts as the control plane itself. Both send the same AgentOS calls, so they share this code: resolve,
then ``continue`` with the per-kind payload, retrying while a durable ticket still owns the run (409).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from agnostic_agentos_client import AgentOSError
from agnostic_approvals.domain.decisions import Approval, ApprovalShapeError, Decision, continue_form
from agnostic_gateway.facade import GatewayFacade
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Principal
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

CONFLICT = 409
FORBIDDEN = 403

type ContinueState = Literal["continued", "pending_admin", "conflict", "failed", "skipped"]


class Reply(Protocol):
    @property
    def status(self) -> int: ...
    @property
    def body(self) -> Any: ...  # noqa: ANN401
    @property
    def ok(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class SystemReply:
    status: int
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300  # noqa: PLR2004


class Sender(Protocol):
    async def __call__(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Reply: ...


def elevated_sender(
    gateway: GatewayFacade, principal: Principal, instance: Instance, *, justification: str, action_label: str
) -> Sender:
    async def send(
        method: str,
        path: str,
        *,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Reply:
        return await gateway.elevated(
            principal,
            instance,
            method,
            path,
            justification=justification,
            action_label=action_label,
            json=json,
            form=form,
            params=params,
        )

    return send


def system_sender(instances: InstancesFacade, instance: Instance) -> Sender:
    """Calls as the control plane; AgentOS errors become replies so callers handle one shape."""

    async def send(
        method: str,
        path: str,
        *,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Reply:
        try:
            body = await instances.system_call(instance, method, path, params=params, json=json, form=form)
        except AgentOSError as exc:
            return SystemReply(exc.status or 502, {"detail": exc.body or str(exc)})
        return SystemReply(200, body)

    return send


def detail(response: Reply) -> str:
    body: object = response.body
    if isinstance(body, dict):
        value = cast("dict[str, object]", body).get("detail")
        return str(value) if value is not None else f"HTTP {response.status}"
    if body is None:
        return f"HTTP {response.status}"
    return str(cast("str", body))[:500]


class RunContinuer:
    def __init__(self, retry_delays: tuple[float, ...]) -> None:
        self._delays = retry_delays

    @staticmethod
    async def resolve(
        send: Sender, approval: Approval, *, approved: bool, resolved_by: str, resolution: Mapping[str, Any]
    ) -> Reply:
        return await send(
            "POST",
            f"/approvals/{approval.id}/resolve",
            json={
                "status": "approved" if approved else "rejected",
                "resolved_by": resolved_by,
                "resolution_data": dict(resolution),
            },
        )

    async def continue_run(
        self,
        send: Sender,
        approval: Approval,
        decision: Decision,
        edited: Mapping[str, Any] | None,
        *,
        bare: bool = False,
    ) -> tuple[ContinueState, str | None]:
        """``bare`` sends no decision (a workflow past its step timeout: AgentOS applies ``on_timeout``)."""
        if approval.run_id is None:
            return "skipped", "The approval isn't attached to a run."
        try:
            family, component_id, form = continue_form(approval, decision, edited)
        except ApprovalShapeError as exc:
            return "failed", str(exc)
        if bare:
            form = {
                key: value for key, value in form.items() if key not in {"tools", "requirements", "step_requirements"}
            }
        path = f"/{family}/{component_id}/runs/{approval.run_id}/continue"
        response: Reply | None = None
        for attempt, delay in enumerate((0.0, *self._delays)):
            if delay:
                await asyncio.sleep(delay)
            response = await send("POST", path, form=form)
            if response.status != CONFLICT:
                break
            log.info("approvals.continue_conflict", approval=approval.id, attempt=attempt + 1)
        assert response is not None
        if response.ok:
            return "continued", None
        if response.status == CONFLICT:
            return "conflict", "Another continuation owns the run; it resumes when that finishes."
        if response.status == FORBIDDEN:
            return "pending_admin", detail(response)
        return "failed", detail(response)
