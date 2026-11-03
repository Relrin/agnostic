"""Deciding an approval inline: check ``approvals:write``, resolve, continue the run, audit the args diff.

Both AgentOS calls go through delegated elevation: under user isolation AgentOS hides other people's
approvals and runs from non-admins, while the control plane has already checked that this person may decide.

The endpoint is idempotent per approval: a second decide returns the first outcome, and an approval that was already
resolved elsewhere is reported as such instead of failing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, cast

import orjson

from agnostic_approvals.application.ports import ApprovalStore
from agnostic_approvals.application.resolution import (
    ContinueState,
    RunContinuer,
    detail,
    elevated_sender,
)
from agnostic_approvals.domain.decisions import Approval, ApprovalShapeError, Decision, args_diff
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_gateway.facade import GatewayFacade
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.events import EventBus, RealtimeEvent, instance_channel
from agnostic_kernel.logging import get_logger
from agnostic_notifications.facade import NotificationRequest, Notifier

log = get_logger(__name__)

JUSTIFICATION = "approvals:write"
RESULT_TTL = 24 * 3600
LOCK_TTL = 120


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


class DecideApproval:
    def __init__(
        self,
        gateway: GatewayFacade,
        audit: AuditLog,
        store: EphemeralStore,
        bus: EventBus,
        retry_delays: Sequence[float],
        approvals: ApprovalStore,
        notifier: Notifier,
    ) -> None:
        self._gateway = gateway
        self._audit = audit
        self._store = store
        self._bus = bus
        self._continuer = RunContinuer(tuple(retry_delays))
        self._approvals = approvals
        self._notifier = notifier

    async def __call__(
        self, principal: Principal, instance_ref: str, approval_id: str, request: DecideRequest
    ) -> DecideResult:
        instance = await self._gateway.instance(instance_ref)
        key = f"apr:decide:{instance.id}:{approval_id}"
        stored = await self._store.get(key)
        if stored is not None and stored != b"pending":
            return DecideResult.from_json(stored)
        if request.decision == "reject" and not (request.note or "").strip():
            raise ValidationFailedError("Rejecting needs a note: the requester sees it, and so does the audit log.")
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
        send = elevated_sender(
            self._gateway, principal, instance, justification=JUSTIFICATION, action_label="decide approvals"
        )
        fetched = await send("GET", f"/approvals/{approval_id}")
        if fetched.status == 404:  # noqa: PLR2004
            raise NotFoundError(f"Approval {approval_id} doesn't exist on {instance.display_name}.")
        if not fetched.ok or not isinstance(fetched.body, dict):
            raise UpstreamApprovalError(f"{instance.display_name}: {detail(fetched)}")
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
        resolved = await self._continuer.resolve(
            send,
            approval,
            approved=request.decision == "approve",
            resolved_by=resolved_by(principal),
            resolution=resolution,
        )
        if not resolved.ok:
            raise UpstreamApprovalError(f"{instance.display_name} didn't resolve {approval.id}: {detail(resolved)}")

        state, continue_detail = await self._continuer.continue_run(send, approval, request.decision, edited)
        status = "approved" if request.decision == "approve" else "rejected"
        await self._record(principal, instance, approval, request, status, diff, state)
        await self._approvals.add_event(
            instance.id,
            approval.id,
            "continued",
            {"continue_state": state, "detail": continue_detail, "decision": status},
            actor=principal.id,
        )
        await self._approvals.commit()
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
        await self._tell_requester(principal, instance, approval, status, request.note)
        return DecideResult(
            approval_id=approval.id,
            instance_id=instance.id,
            decision=request.decision,
            status=status,
            run_id=approval.run_id,
            session_id=approval.session_id,
            continue_state=state,
            continue_detail=continue_detail,
            already_resolved=False,
            args_changed=tuple(diff),
        )

    async def _tell_requester(
        self, principal: Principal, instance: Instance, approval: Approval, status: str, note: str | None
    ) -> None:
        """The person whose run paused hears the outcome (when they are someone else in this org)."""
        if not approval.user_id or approval.user_id == principal.id:
            return
        _ = await self._notifier.notify(
            NotificationRequest(
                event_type="approval.resolved",
                title=f"{principal.display_name} {status} {approval.tool_name or 'a step'}",
                body=note or "",
                link=f"/i/{instance.slug}/approvals?status={status}&approval={approval.id}",
                instance_id=instance.id,
                recipients=[approval.user_id],
                context=instance.display_name,
                data={"approval_id": approval.id, "status": status, "run_id": approval.run_id},
                dedupe_key=f"resolved:{instance.id}:{approval.id}",
            )
        )

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
