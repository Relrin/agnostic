"""Publish a draft (validation and eval gates first, with an audited override) and roll back by setting current."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_evals.facade import EvalGates, GateCheck
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.errors import ConflictError, ValidationFailedError, VersionConflictError
from agnostic_studio.application.access import (
    CONFLICT,
    OVERRIDE_SCOPE,
    READ_SCOPE,
    WRITE_SCOPE,
    StudioAccess,
    detail,
    raise_for,
)
from agnostic_studio.application.components import Reader, VersionView, version_of
from agnostic_studio.application.ports import PublishHold, StudioStore
from agnostic_studio.application.validation import ValidationReport, Validator
from agnostic_studio.domain.diff import FieldChange, diff
from agnostic_studio.domain.model import Component, ComponentMeta, HoldCheck, Version, VersionMeta
from agnostic_studio.domain.summaries import audit_lines, change_summary, publish_outcome, rollback_outcome

MAX_REASON = 1000
PUBLISHED_EVENT = "studio.published"


class GateBlockedError(ConflictError):
    code = "gate_blocked"
    title = "An eval gate blocks this publish"


class PublishHeldError(ConflictError):
    code = "publish_held"
    title = "Publishing waits for something else first"


@dataclass(frozen=True, slots=True)
class PublishCheck:
    instance: Instance
    component: Component
    version: Version
    validation: ValidationReport
    gates: list[GateCheck]
    can_publish: bool
    can_override: bool
    outcome: str
    changes: list[FieldChange]
    summary: str
    hold: HoldCheck = field(default_factory=HoldCheck)

    @property
    def blocked_by_gates(self) -> bool:
        return any(gate.blocks for gate in self.gates)


@dataclass(frozen=True, slots=True)
class PublishResult:
    version: VersionView
    outcome: str
    overridden: bool
    gates: list[GateCheck]


class Publisher:
    def __init__(
        self,
        access: StudioAccess,
        store: StudioStore,
        audit: AuditLog,
        gates: EvalGates,
        validator: Validator,
        hold: PublishHold,
        events: DomainEvents,
    ) -> None:
        self._access = access
        self._store = store
        self._audit = audit
        self._gates = gates
        self._validator = validator
        self._hold = hold
        self._events = events
        self._reader = Reader(access, store)

    async def check(self, principal: Principal, ref: str, component_id: str, number: int) -> PublishCheck:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        return await self._check(principal, instance, component_id, number)

    async def _check(self, principal: Principal, instance: Instance, component_id: str, number: int) -> PublishCheck:
        component = await self._reader.component(principal, instance, component_id)
        version = await self._reader.version(principal, instance, component_id, number)
        validation = await self._validator.validate(principal, instance, component.kind, version.config or {})
        gates = await self._gates.check(instance.id, component_id, number, f"v{number} draft")
        current = await self._reader.current(principal, instance, component_id)
        changes = diff(current.config or {} if current else {}, version.config or {})
        hold = await self._hold.check(instance.id, component_id, number)
        return PublishCheck(
            instance=instance,
            component=component,
            version=version,
            validation=validation,
            gates=gates,
            can_publish=not hold.held and await self._access.allowed(principal, WRITE_SCOPE, instance),
            can_override=await self._access.allowed(principal, OVERRIDE_SCOPE, instance),
            outcome=publish_outcome(number, instance.display_name, component.current_version),
            changes=changes,
            summary=change_summary(changes) if current else "First published version",
            hold=hold,
        )

    async def publish(
        self,
        principal: Principal,
        ref: str,
        component_id: str,
        number: int,
        *,
        notes: str | None = None,
        override_reason: str | None = None,
    ) -> PublishResult:
        instance = await self._access.instance(principal, ref, WRITE_SCOPE)
        check = await self._check(principal, instance, component_id, number)
        if check.version.stage != "draft":
            raise ConflictError(f"v{number} is already published.")
        if not check.validation.ok:
            raise ValidationFailedError(
                f"v{number} can't be published: {check.validation.summary}",
                extra={"diagnostics": [item.as_dict() for item in check.validation.diagnostics]},
            )
        if check.hold.held:
            raise PublishHeldError(check.hold.reason, extra={"link": check.hold.link})
        reason = (override_reason or "").strip()[:MAX_REASON]
        overridden = False
        if check.blocked_by_gates:
            if not reason:
                raise GateBlockedError(
                    "; ".join(gate.consequence for gate in check.gates if gate.blocks),
                    extra={"gates": [_gate_dict(gate) for gate in check.gates]},
                )
            await self._access.require(principal, OVERRIDE_SCOPE, instance)
            overridden = True
        component = check.component
        response = await self._access.call(
            principal,
            instance,
            "PATCH",
            f"/components/{component_id}/configs/{number}",
            body={
                "stage": "published",
                "notes": notes,
                "guard": {"current_version": component.current_version or 0},
            },
        )
        if response.status == CONFLICT:
            raise VersionConflictError(
                f"Someone published another version of {component.name} meanwhile: {detail(response)}"
            )
        raise_for(instance, response)
        published = version_of(cast("dict[str, Any]", response.body))
        now = utcnow()
        meta = await self._store.version_meta(instance.id, component_id, number) or VersionMeta(
            instance.id, component_id, number
        )
        meta = replace(
            meta,
            notes=notes if notes is not None else meta.notes,
            change_summary=check.summary,
            eval_status="overridden" if overridden else ("passed" if check.gates else "no_gates"),
            published_by=principal.id,
            published_by_name=principal.display_name,
            published_at=now,
        )
        await self._store.save_version_meta(meta)
        component_meta = await self._store.component_meta(instance.id, component_id) or ComponentMeta(
            instance.id, component_id, component.kind
        )
        await self._store.save_component_meta(replace(component_meta, last_known_current_version=number))
        if overridden:
            _ = await self._audit.record(
                AuditEntry(
                    action="evals.gate.override",
                    actor=actor_of(principal),
                    resource_kind=component.kind,
                    resource_id=component_id,
                    resource_display=f"{component.name} v{number}",
                    instance_id=instance.id,
                    decision="allowed",
                    scope_checked=OVERRIDE_SCOPE,
                    fields={
                        "component": component.name,
                        "version": f"v{number}",
                        "gates": "; ".join(gate.consequence for gate in check.gates if gate.blocks),
                        "reason": reason,
                    },
                )
            )
        _ = await self._audit.record(
            AuditEntry(
                action="studio.publish",
                actor=actor_of(principal),
                resource_kind=component.kind,
                resource_id=component_id,
                resource_display=f"{component.name} v{number}",
                instance_id=instance.id,
                fields={
                    "component": component.name,
                    "version": f"v{number}",
                    "instance": instance.display_name,
                    "summary": check.summary,
                    "override": "with a gate override" if overridden else "",
                },
                diff={
                    "title": f"v{component.current_version} → v{number}" if component.current_version else f"v{number}",
                    "lines": audit_lines(check.changes),
                    "note": f"Gate override: {reason}" if overridden else check.summary,
                },
            )
        )
        await self._store.commit()
        await self._access.forget(f"studio:indexed:{instance.id}")
        await self._events.publish(
            PUBLISHED_EVENT,
            {
                "instance_id": instance.id,
                "component_id": component_id,
                "kind": component.kind,
                "name": component.name,
                "version": number,
                "published_by": principal.id,
                "published_by_name": principal.display_name,
                "published_by_email": principal.email,
                "summary": check.summary,
            },
        )
        return PublishResult(VersionView(published, meta, current=True), check.outcome, overridden, check.gates)

    async def set_current(
        self, principal: Principal, ref: str, component_id: str, number: int, *, reason: str | None = None
    ) -> tuple[VersionView, str]:
        instance = await self._access.instance(principal, ref, WRITE_SCOPE)
        component = await self._reader.component(principal, instance, component_id)
        target = await self._reader.version(principal, instance, component_id, number)
        if target.stage != "published":
            raise ConflictError(f"v{number} is a draft; only published versions can be current.")
        if component.current_version == number:
            raise ConflictError(f"v{number} is already current.")
        response = await self._access.call(
            principal,
            instance,
            "POST",
            f"/components/{component_id}/configs/{number}/set-current",
            body={"guard": {"current_version": component.current_version or 0}},
        )
        if response.status == CONFLICT:
            raise VersionConflictError(f"The current version of {component.name} changed meanwhile: {detail(response)}")
        raise_for(instance, response)
        component_meta = await self._store.component_meta(instance.id, component_id) or ComponentMeta(
            instance.id, component_id, component.kind
        )
        await self._store.save_component_meta(replace(component_meta, last_known_current_version=number))
        outcome = rollback_outcome(number, instance.display_name, component.current_version)
        _ = await self._audit.record(
            AuditEntry(
                action="components.set_current",
                actor=actor_of(principal),
                resource_kind=component.kind,
                resource_id=component_id,
                resource_display=component.name,
                instance_id=instance.id,
                fields={
                    "component": component.name,
                    "from": f"v{component.current_version}" if component.current_version else "none",
                    "to": f"v{number}",
                    "reason": (reason or "").strip()[:MAX_REASON],
                },
            )
        )
        await self._store.commit()
        await self._access.forget(f"studio:indexed:{instance.id}")
        meta = await self._store.version_meta(instance.id, component_id, number)
        return VersionView(target, meta, current=True), outcome


def _gate_dict(gate: GateCheck) -> dict[str, Any]:
    return {
        "gate_id": gate.gate_id,
        "dataset_id": gate.dataset_id,
        "dataset_name": gate.dataset_name,
        "eval_type": gate.eval_type,
        "min_average": gate.min_average,
        "value": gate.value,
        "state": gate.state,
        "consequence": gate.consequence,
    }
