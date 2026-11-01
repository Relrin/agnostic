"""Deciding an approval inline: check ``approvals:write``, resolve, continue the run, audit the args diff.

Both AgentOS calls go through delegated elevation: under user isolation AgentOS hides other people's
approvals and runs from non-admins, while the control plane has already checked that this person may decide.

The endpoint is idempotent per approval: a second decide returns the first outcome, and an approval that was already
resolved elsewhere is reported as such instead of failing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, cast

import orjson

from agnostic_approvals.domain.decisions import Approval, ApprovalShapeError, Decision, args_diff, continue_form
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_gateway.facade import ElevatedResponse, GatewayFacade
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ConflictError, NotFoundError
from agnostic_kernel.events import EventBus, RealtimeEvent, instance_channel
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

JUSTIFICATION = "approvals:write"
RESULT_TTL = 24 * 3600
LOCK_TTL = 120
CONFLICT = 409
FORBIDDEN = 403

type ContinueState = Literal["continued", "pending_admin", "conflict", "failed", "skipped"]


class UpstreamApprovalError(AppError):
    status = 502
    code = "approval_upstream_failed"
    title = "The instance refused the approval decision"


@dataclass(frozen=True, slots=True)
class DecideRequest:
    decision: Decision
    note: str | None = None
    edited_args: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DecideResult:
    approval_id: str
    instance_id: str
    decision: Decision
    status: str
    """The approval's status afterwards: ``approved``, ``rejected``, or what someone else already decided."""
    run_id: str | None
    session_id: str | None
    continue_state: ContinueState
    continue_detail: str | None
    already_resolved: bool
    args_changed: Sequence[str]

    def to_json(self) -> bytes:
        return orjson.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: bytes) -> DecideResult:
        value = orjson.loads(raw)
        value["args_changed"] = tuple(value.get("args_changed") or ())
        return cls(**value)


def resolved_by(principal: Principal) -> str:
    return f"{principal.display_name} ({principal.id})"[:255]


def _detail(response: ElevatedResponse) -> str:
    body: object = response.body
    if isinstance(body, dict):
        detail = cast("dict[str, object]", body).get("detail")
        return str(detail) if detail is not None else f"HTTP {response.status}"
    if body is None:
        return f"HTTP {response.status}"
    return str(cast("str", body))[:500]


class DecideApproval:
    def __init__(
        self,
        gateway: GatewayFacade,
        audit: AuditLog,
        store: EphemeralStore,
        bus: EventBus,
        retry_delays: Sequence[float],
    ) -> None:
        self._gateway = gateway
        self._audit = audit
        self._store = store
        self._bus = bus
        self._delays = tuple(retry_delays)

    async def __call__(
        self, principal: Principal, instance_ref: str, approval_id: str, request: DecideRequest
    ) -> DecideResult:
        instance = await self._gateway.instance(instance_ref)
        key = f"apr:decide:{instance.id}:{approval_id}"
        stored = await self._store.get(key)
        if stored is not None and stored != b"pending":
            return DecideResult.from_json(stored)
        if not await self._store.set_if_absent(key, b"pending", ttl=LOCK_TTL):
            raise ConflictError("Someone is deciding this approval right now. Refresh in a moment.")
        try:
            result = await self._decide(principal, instance, approval_id, request)
        except BaseException:
            await self._store.delete(key)
            raise
        await self._store.set(key, result.to_json(), ttl=RESULT_TTL)
        return result

    async def _decide(
        self, principal: Principal, instance: Instance, approval_id: str, request: DecideRequest
    ) -> DecideResult:
        action = "decide approvals"
        fetched = await self._gateway.elevated(
            principal,
            instance,
            "GET",
            f"/approvals/{approval_id}",
            justification=JUSTIFICATION,
            action_label=action,
        )
        if fetched.status == 404:  # noqa: PLR2004
            raise NotFoundError(f"Approval {approval_id} doesn't exist on {instance.display_name}.")
        if not fetched.ok or not isinstance(fetched.body, dict):
            raise UpstreamApprovalError(f"{instance.display_name}: {_detail(fetched)}")
        try:
            approval = Approval.parse(cast("dict[str, Any]", fetched.body))
        except ApprovalShapeError as exc:
            raise UpstreamApprovalError(f"{instance.display_name} returned an unexpected approval: {exc}") from exc

        if not approval.pending:
            return DecideResult(
                approval_id=approval.id,
                instance_id=instance.id,
                decision=request.decision,
                status=approval.status,
                run_id=approval.run_id,
                session_id=approval.session_id,
                continue_state="skipped",
                continue_detail=f"Already {approval.status}.",
                already_resolved=True,
                args_changed=(),
            )

        edited = request.edited_args if request.decision == "approve" else None
        diff = args_diff(approval.tool_args, edited)
        resolution: dict[str, Any] = {"decided_in": "agnostic"}
        if request.note:
            resolution["note"] = request.note
        if diff:
            resolution["edited_args"] = dict(edited or {})
            resolution["diff"] = diff
        resolved = await self._gateway.elevated(
            principal,
            instance,
            "POST",
            f"/approvals/{approval.id}/resolve",
            justification=JUSTIFICATION,
            action_label=action,
            json={
                "status": "approved" if request.decision == "approve" else "rejected",
                "resolved_by": resolved_by(principal),
                "resolution_data": resolution,
            },
        )
        if not resolved.ok:
            raise UpstreamApprovalError(f"{instance.display_name} didn't resolve {approval.id}: {_detail(resolved)}")

        state, detail = await self._continue(principal, instance, approval, request.decision, edited)
        status = "approved" if request.decision == "approve" else "rejected"
        await self._record(principal, instance, approval, request, status, diff, state)
        await self._bus.publish(
            instance_channel(instance.id),
            RealtimeEvent(
                "approval.resolved",
                {
                    "approval_id": approval.id,
                    "status": status,
                    "run_id": approval.run_id,
                    "session_id": approval.session_id,
                    "continue_state": state,
                },
                instance_id=instance.id,
            ),
        )
        return DecideResult(
            approval_id=approval.id,
            instance_id=instance.id,
            decision=request.decision,
            status=status,
            run_id=approval.run_id,
            session_id=approval.session_id,
            continue_state=state,
            continue_detail=detail,
            already_resolved=False,
            args_changed=tuple(diff),
        )

    async def _continue(
        self,
        principal: Principal,
        instance: Instance,
        approval: Approval,
        decision: Decision,
        edited: Mapping[str, Any] | None,
    ) -> tuple[ContinueState, str | None]:
        if approval.run_id is None:
            return "skipped", "The approval isn't attached to a run."
        try:
            family, component_id, form = continue_form(approval, decision, edited)
        except ApprovalShapeError as exc:
            return "failed", str(exc)
        path = f"/{family}/{component_id}/runs/{approval.run_id}/continue"
        response: ElevatedResponse | None = None
        for attempt, delay in enumerate((0.0, *self._delays)):
            if delay:
                await asyncio.sleep(delay)
            response = await self._gateway.elevated(
                principal,
                instance,
                "POST",
                path,
                justification=JUSTIFICATION,
                action_label="continue approved runs",
                form=form,
            )
            if response.status != CONFLICT:
                break
            log.info("approvals.continue_conflict", approval=approval.id, attempt=attempt + 1)
        assert response is not None
        if response.ok:
            return "continued", None
        if response.status == CONFLICT:
            return "conflict", "Another continuation owns the run; it resumes when that finishes."
        if response.status == FORBIDDEN:
            return "pending_admin", _detail(response)
        return "failed", _detail(response)

    async def _record(
        self,
        principal: Principal,
        instance: Instance,
        approval: Approval,
        request: DecideRequest,
        status: str,
        diff: Mapping[str, Any],
        state: ContinueState,
    ) -> None:
        family, component_id = approval.component
        fields = {
            "verb": status,
            "tool": approval.tool_name or "a step",
            "component": component_id,
            "instance": instance.display_name,
        }
        _ = await self._audit.record_now(
            AuditEntry(
                action="approvals.decided",
                actor=actor_of(principal),
                resource_kind="approval",
                resource_id=approval.id,
                resource_display=approval.tool_name or approval.id,
                instance_id=instance.id,
                decision="allowed",
                scope_checked=JUSTIFICATION,
                response_status=200,
                fields=fields,
                diff={"tool_args": diff} if diff else None,
                links={
                    "run_id": approval.run_id,
                    "session_id": approval.session_id,
                    "component": f"{family}/{component_id}",
                    "note": request.note,
                    "continue": state,
                },
                via="web",
            )
        )
