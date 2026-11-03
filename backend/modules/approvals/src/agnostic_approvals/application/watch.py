"""The approvals watcher (a periodic job): route new approvals, warn before they expire, enforce expiry.

Every round lists each instance's pending approvals as the control plane and compares them with what it already
did (``apr_events``):

* a new approval is routed: its recipients are told through their channels and the route's org channels;
* an approval within ``expiring_lead_minutes`` of its effective expiry gets one reminder;
* past expiry, on instances that enforce it, the run is stopped the way AgentOS would: a workflow is continued
  without a decision (AgentOS applies the step's ``on_timeout``, cancel by default), an agent or team approval is
  rejected as expired and the run continued with the rejection. Instances that don't enforce expiry only show it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from agnostic_approvals.application.ports import ApprovalStore
from agnostic_approvals.application.reader import ApprovalsReader
from agnostic_approvals.application.resolution import RunContinuer, system_sender
from agnostic_approvals.application.routing import ApprovalRouting
from agnostic_approvals.domain.decisions import Approval
from agnostic_approvals.domain.inbox import ApprovalRecord, effective_expiry
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_instances.facade import Instance, InstancesFacade, InstanceStatus
from agnostic_kernel.auth import SYSTEM_PRINCIPAL
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError
from agnostic_kernel.events import EventBus, RealtimeEvent, instance_channel
from agnostic_kernel.logging import get_logger
from agnostic_notifications.facade import NotificationRequest, Notifier
from agnostic_settings.facade import OrgSettingsReader

log = get_logger(__name__)

DISABLED_BACKOFF = 300.0


@dataclass(frozen=True, slots=True)
class WatchSummary:
    instances: int = 0
    routed: int = 0
    reminded: int = 0
    expired: int = 0


def _ago(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return ""
    minutes = int((now - moment).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:  # noqa: PLR2004
        return f"{minutes}m ago"
    return f"{minutes // 60}h {minutes % 60:02d}m ago"


class WatchApprovals:
    def __init__(
        self,
        instances: InstancesFacade,
        reader: ApprovalsReader,
        store: ApprovalStore,
        routing: ApprovalRouting,
        notifier: Notifier,
        settings: OrgSettingsReader,
        audit: AuditLog,
        bus: EventBus,
        ephemeral: EphemeralStore,
        *,
        scan_limit: int,
        expiring_lead: timedelta,
        retry_delays: tuple[float, ...],
    ) -> None:
        self._instances = instances
        self._reader = reader
        self._store = store
        self._routing = routing
        self._notifier = notifier
        self._settings = settings
        self._audit = audit
        self._bus = bus
        self._ephemeral = ephemeral
        self._scan_limit = scan_limit
        self._lead = expiring_lead
        self._continuer = RunContinuer(retry_delays)

    async def __call__(self, now: datetime | None = None) -> WatchSummary:
        total = WatchSummary()
        for instance in await self._instances.list():
            if instance.status is InstanceStatus.DISABLED:
                continue
            if await self._ephemeral.get(f"apr:watch-disabled:{instance.id}") is not None:
                continue
            try:
                done = await self.instance(instance, now or utcnow())
            except AppError as exc:
                if exc.status == 503:  # noqa: PLR2004
                    await self._ephemeral.set(f"apr:watch-disabled:{instance.id}", b"1", ttl=DISABLED_BACKOFF)
                log.info("approvals.watch_skipped", instance=instance.id, reason=exc.detail or exc.title)
                continue
            total = WatchSummary(
                total.instances + 1,
                total.routed + done.routed,
                total.reminded + done.reminded,
                total.expired + done.expired,
            )
        return total

    async def instance(self, instance: Instance, now: datetime) -> WatchSummary:
        pending, _ = await self._reader.scan(instance, {"status": "pending"}, self._scan_limit)
        if not pending:
            return WatchSummary(instances=1)
        policy = await self._store.policy(instance.id)
        ttl = policy.ttl_hours if policy.ttl_hours is not None else (await self._settings.get()).approval_ttl_hours
        done = await self._store.event_kinds(instance.id, [record.id for record in pending])
        routed = reminded = expired = 0
        for record in sorted(pending, key=lambda r: r.created_at or now):
            kinds = done.get(record.id, set())
            expiry = effective_expiry(record, ttl)
            if "routed" not in kinds:
                await self._route(instance, record, expiry.at, now)
                routed += 1
            if expiry.at is None or "expired" in kinds:
                continue
            if expiry.at <= now:
                if policy.enforce_expiry and record.kind == "blocking":
                    await self._expire(instance, record, expiry.at)
                    expired += 1
            elif expiry.at - now <= self._lead and "expiring" not in kinds:
                await self._remind(instance, record, expiry.at, now)
                reminded += 1
        return WatchSummary(1, routed, reminded, expired)

    def _link(self, instance: Instance, record: ApprovalRecord) -> str:
        return f"/i/{instance.slug}/approvals?approval={record.id}"

    async def _route(
        self, instance: Instance, record: ApprovalRecord, expires_at: datetime | None, now: datetime
    ) -> None:
        recipients = await self._routing.recipients(instance.id, record)
        source = record.source
        where = f"{source[0]} {source[1]}" if source else instance.display_name
        link = self._link(instance, record)
        channels = ["control plane", *[c.title() for c in recipients.channels if c != "in_app"]]
        if recipients.channel_ids:
            channels.append(
                f"{len(recipients.channel_ids)} org channel{'s' if len(recipients.channel_ids) > 1 else ''}"
            )
        await self._store.add_event(
            instance.id,
            record.id,
            "routed",
            {
                "routed_to": recipients.routed_to,
                "recipients": recipients.user_ids,
                "channels": channels,
                "channel_ids": recipients.channel_ids,
            },
        )
        await self._store.commit()
        args = ", ".join(f"{key}={value}" for key, value in list(record.tool_args.items())[:4])
        result = await self._notifier.notify(
            NotificationRequest(
                event_type="approval.created",
                title=f"{record.tool_name or 'A step'} needs approval",
                body=(f"{where} · {args}" if args else where)
                + (f" · expires {expires_at.strftime('%a %d %b %H:%M UTC')}" if expires_at else ""),
                link=link,
                instance_id=instance.id,
                recipients=recipients.user_ids,
                channel_ids=recipients.channel_ids,
                forced_channels=recipients.channels,
                actions=(
                    ("Approve", f"{link}&intent=approve", "primary"),
                    ("Reject", f"{link}&intent=reject", "danger"),
                ),
                context=f"{instance.display_name} · requested {_ago(record.created_at, now)}"
                + (f" by {record.user_id}" if record.user_id else ""),
                data={"approval_id": record.id, "tool_name": record.tool_name, "run_id": record.run_id},
                dedupe_key=f"created:{instance.id}:{record.id}",
            )
        )
        if result.deliveries:
            await self._store.add_event(instance.id, record.id, "notified", {"deliveries": result.deliveries})
            await self._store.commit()
        await self._bus.publish(
            instance_channel(instance.id),
            RealtimeEvent(
                "approval.created",
                {"approval_id": record.id, "tool_name": record.tool_name, "routed_to": recipients.routed_to},
                instance_id=instance.id,
            ),
        )

    async def _remind(self, instance: Instance, record: ApprovalRecord, expires_at: datetime, now: datetime) -> None:
        recipients = await self._routing.recipients(instance.id, record)
        await self._store.add_event(instance.id, record.id, "expiring", {"expires_at": expires_at.isoformat()})
        await self._store.commit()
        minutes = max(int((expires_at - now).total_seconds() // 60), 1)
        _ = await self._notifier.notify(
            NotificationRequest(
                event_type="approval.expiring",
                title=f"{record.tool_name or 'An approval'} expires in {minutes} min",
                body="Decide before it expires, or the run may be stopped.",
                link=self._link(instance, record),
                instance_id=instance.id,
                recipients=recipients.user_ids,
                forced_channels=recipients.channels,
                context=instance.display_name,
                data={"approval_id": record.id, "expires_at": expires_at.isoformat()},
                dedupe_key=f"expiring:{instance.id}:{record.id}",
            )
        )

    async def _expire(self, instance: Instance, record: ApprovalRecord, expires_at: datetime) -> None:
        if not await self._ephemeral.set_if_absent(f"apr:expire:{instance.id}:{record.id}", b"1", ttl=300):
            return
        approval = Approval.parse(record.raw)
        send = system_sender(self._instances, instance)
        component = record.component
        if component is not None and component[0] == "workflow":
            state, detail = await self._continuer.continue_run(send, approval, "reject", None, bare=True)
            outcome = "The workflow continued past its step timeout; AgentOS applied the step's on_timeout."
        else:
            resolved = await self._continuer.resolve(
                send,
                approval,
                approved=False,
                resolved_by="agnostic (expired)",
                resolution={"expired": True, "decided_in": "agnostic", "note": "Expired without a decision."},
            )
            if not resolved.ok:
                log.warning("approvals.expire_failed", approval=record.id, status=resolved.status)
                return
            state, detail = await self._continuer.continue_run(send, approval, "reject", None)
            outcome = "Rejected as expired; the run continued with the rejection."
        await self._store.add_event(
            instance.id,
            record.id,
            "expired",
            {"expires_at": expires_at.isoformat(), "continue_state": state, "detail": detail, "outcome": outcome},
        )
        _ = await self._audit.record(
            AuditEntry(
                action="approvals.expired",
                actor=actor_of(SYSTEM_PRINCIPAL),
                resource_kind="approval",
                resource_id=record.id,
                resource_display=record.tool_name or record.id,
                instance_id=instance.id,
                decision="allowed",
                fields={"tool": record.tool_name or "a step", "instance": instance.display_name},
                links={"run_id": record.run_id, "session_id": record.session_id, "continue": state},
                via="job",
            )
        )
        await self._store.commit()
        await self._bus.publish(
            instance_channel(instance.id),
            RealtimeEvent(
                "approval.resolved",
                {"approval_id": record.id, "status": "expired", "run_id": record.run_id, "continue_state": state},
                instance_id=instance.id,
            ),
        )
