"""Schedules over AgentOS ``/schedules``: the person's own scopes through the gateway, plus what AgentOS lacks.

AgentOS checks ``schedules:*`` (and, for a run endpoint, ``<family>:run`` on the target). The control plane adds:

* run history and failure streaks next to each schedule, and a human sentence for its cron;
* the reason a person gave when disabling (AgentOS's ``disabled_reason`` is set by the system only);
* custom endpoints (anything but ``POST /{agents|teams|workflows}/{id}/runs``) only for Instance admins, checked
  before anything is sent and audited with ``target=custom``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ValidationFailedError
from agnostic_scheduler.application.calls import SchedulerCalls, page_items
from agnostic_scheduler.application.ports import DisableNote, NoteStore
from agnostic_scheduler.domain.cron import CronError, Preview, describe, preview, validate, zone
from agnostic_scheduler.domain.schedules import ScheduleRun, Target, consecutive_failures, target_of

READ = "schedules:read"
ADMIN = "agent_os:admin"
HISTORY = 5
FIELDS = (
    "name",
    "description",
    "cron_expr",
    "timezone",
    "method",
    "endpoint",
    "payload",
    "timeout_seconds",
    "max_retries",
    "retry_delay_seconds",
)


@dataclass(frozen=True, slots=True)
class ScheduleView:
    raw: Mapping[str, Any]
    target: Target
    description: str | None
    runs: list[ScheduleRun]
    consecutive_failures: int
    note: DisableNote | None

    @property
    def id(self) -> str:
        return str(self.raw.get("id") or "")

    @property
    def name(self) -> str:
        return str(self.raw.get("name") or self.id)


@dataclass(frozen=True, slots=True)
class SchedulerStatus:
    instance: Instance
    enabled: bool | None
    """``None``: unknown (the instance has no bridge to ask)."""
    poll_interval_seconds: float | None
    can_write: bool
    can_delete: bool
    can_custom: bool


@dataclass(frozen=True, slots=True)
class EndpointCheck:
    target: Target
    documented: bool | None
    """Whether the path is in the instance's OpenAPI document (``None``: it publishes none)."""
    needs_admin: bool


@dataclass(frozen=True, slots=True)
class RunsPage:
    runs: list[ScheduleRun]
    total: int | None


def _describe(cron: object) -> str | None:
    if not isinstance(cron, str) or not cron.strip():
        return None
    try:
        return describe(cron)
    except CronError:
        return None


def _path_matches(template: str, path: str) -> bool:
    parts, wanted = template.strip("/").split("/"), path.split("?", maxsplit=1)[0].strip("/").split("/")
    return len(parts) == len(wanted) and all(
        a == b or (a.startswith("{") and a.endswith("}")) for a, b in zip(parts, wanted, strict=True)
    )


class Schedules:
    def __init__(self, calls: SchedulerCalls, authorizer: Authorizer, notes: NoteStore, audit: AuditLog) -> None:
        self._calls = calls
        self._authorizer = authorizer
        self._notes = notes
        self._audit = audit

    async def _history(
        self, principal: Principal, instance: Instance, schedule_id: str, limit: int
    ) -> list[ScheduleRun]:
        body = await self._calls.json(principal, instance, f"/schedules/{schedule_id}/runs", params={"limit": limit})
        items, _ = page_items(body)
        runs = [ScheduleRun.parse(item) for item in items]
        return sorted(runs, key=lambda run: run.triggered_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    async def _view(
        self,
        principal: Principal,
        instance: Instance,
        raw: Mapping[str, Any],
        note: DisableNote | None,
        *,
        history: int,
    ) -> ScheduleView:
        runs = await self._history(principal, instance, str(raw.get("id")), history)
        return ScheduleView(
            raw=raw,
            target=target_of(str(raw.get("method") or "POST"), str(raw.get("endpoint") or "")),
            description=_describe(raw.get("cron_expr")),
            runs=runs,
            consecutive_failures=consecutive_failures(runs),
            note=note,
        )

    async def list(
        self, principal: Principal, ref: str, *, enabled: bool | None, page: int, limit: int
    ) -> tuple[list[ScheduleView], int | None]:
        instance = await self._calls.instance(ref)
        params: dict[str, str | int | None] = {"page": page, "limit": limit}
        if enabled is not None:
            params["enabled"] = "true" if enabled else "false"
        items, total = page_items(await self._calls.json(principal, instance, "/schedules", params=params))
        notes = await self._notes.notes(instance.id, [str(item.get("id")) for item in items])
        views = [
            await self._view(principal, instance, item, notes.get(str(item.get("id"))), history=HISTORY)
            for item in items
        ]
        return views, total

    async def get(self, principal: Principal, ref: str, schedule_id: str) -> ScheduleView:
        instance = await self._calls.instance(ref)
        raw = cast("dict[str, Any]", await self._calls.json(principal, instance, f"/schedules/{schedule_id}"))
        notes = await self._notes.notes(instance.id, [schedule_id])
        return await self._view(principal, instance, raw, notes.get(schedule_id), history=10)

    async def runs(self, principal: Principal, ref: str, schedule_id: str, *, page: int, limit: int) -> RunsPage:
        instance = await self._calls.instance(ref)
        body = await self._calls.json(
            principal, instance, f"/schedules/{schedule_id}/runs", params={"page": page, "limit": limit}
        )
        items, total = page_items(body)
        return RunsPage([ScheduleRun.parse(item) for item in items], total)

    async def _guard(self, principal: Principal, instance: Instance, values: Mapping[str, Any]) -> Target:
        """Validates cron and timezone locally; custom endpoints need Instance admin before anything is sent."""
        cron = values.get("cron_expr")
        if isinstance(cron, str) and cron.strip():
            try:
                validate(cron)
            except CronError as exc:
                raise ValidationFailedError(str(exc), extra={"fields": list(exc.fields)}) from exc
        timezone = values.get("timezone")
        if isinstance(timezone, str):
            try:
                _ = zone(timezone)
            except CronError as exc:
                raise ValidationFailedError(str(exc), extra={"fields": ["timezone"]}) from exc
        target = target_of(str(values.get("method") or "POST"), str(values.get("endpoint") or ""))
        if target.kind == "custom":
            _ = await self._authorizer.require(principal, ADMIN, instance_id=instance.id)
        return target

    async def create(self, principal: Principal, ref: str, values: Mapping[str, Any]) -> ScheduleView:
        instance = await self._calls.instance(ref)
        body = {key: value for key, value in values.items() if key in FIELDS and value is not None}
        target = await self._guard(principal, instance, body)
        raw = cast(
            "dict[str, Any]", await self._calls.json(principal, instance, "/schedules", method="POST", body=body)
        )
        await self._record(principal, instance, "schedules.create", raw, target, changed=sorted(body))
        return await self._view(principal, instance, raw, None, history=1)

    async def update(self, principal: Principal, ref: str, schedule_id: str, values: Mapping[str, Any]) -> ScheduleView:
        instance = await self._calls.instance(ref)
        body = {key: value for key, value in values.items() if key in FIELDS and value is not None}
        if not body:
            raise ValidationFailedError("Nothing to change.")
        current = cast("dict[str, Any]", await self._calls.json(principal, instance, f"/schedules/{schedule_id}"))
        target = await self._guard(principal, instance, {**current, **body})
        raw = cast(
            "dict[str, Any]",
            await self._calls.json(principal, instance, f"/schedules/{schedule_id}", method="PATCH", body=body),
        )
        await self._record(principal, instance, "schedules.update", raw, target, changed=sorted(body))
        notes = await self._notes.notes(instance.id, [schedule_id])
        return await self._view(principal, instance, raw, notes.get(schedule_id), history=HISTORY)

    async def delete(self, principal: Principal, ref: str, schedule_id: str) -> None:
        instance = await self._calls.instance(ref)
        current = cast("dict[str, Any]", await self._calls.json(principal, instance, f"/schedules/{schedule_id}"))
        _ = await self._calls.json(principal, instance, f"/schedules/{schedule_id}", method="DELETE")
        await self._notes.clear(instance.id, schedule_id)
        await self._notes.commit()
        target = target_of(str(current.get("method") or "POST"), str(current.get("endpoint") or ""))
        await self._record(principal, instance, "schedules.delete", current, target)

    async def enable(self, principal: Principal, ref: str, schedule_id: str) -> ScheduleView:
        instance = await self._calls.instance(ref)
        _ = await self._calls.json(principal, instance, f"/schedules/{schedule_id}/enable", method="POST")
        await self._notes.clear(instance.id, schedule_id)
        await self._notes.commit()
        view = await self.get(principal, ref, schedule_id)
        await self._record(principal, instance, "schedules.enable", view.raw, view.target)
        return view

    async def disable(self, principal: Principal, ref: str, schedule_id: str, reason: str | None) -> ScheduleView:
        instance = await self._calls.instance(ref)
        _ = await self._calls.json(principal, instance, f"/schedules/{schedule_id}/disable", method="POST")
        if reason and reason.strip():
            await self._notes.set(
                DisableNote(
                    instance_id=instance.id,
                    schedule_id=schedule_id,
                    reason=reason.strip()[:500],
                    disabled_by=principal.id,
                    disabled_by_name=principal.display_name,
                    disabled_at=utcnow(),
                )
            )
        else:
            await self._notes.clear(instance.id, schedule_id)
        await self._notes.commit()
        view = await self.get(principal, ref, schedule_id)
        await self._record(principal, instance, "schedules.disable", view.raw, view.target, reason=reason)
        return view

    async def trigger(self, principal: Principal, ref: str, schedule_id: str) -> ScheduleRun:
        instance = await self._calls.instance(ref)
        current = cast("dict[str, Any]", await self._calls.json(principal, instance, f"/schedules/{schedule_id}"))
        target = target_of(str(current.get("method") or "POST"), str(current.get("endpoint") or ""))
        if target.kind == "custom":
            _ = await self._authorizer.require(principal, ADMIN, instance_id=instance.id)
        body = await self._calls.json(principal, instance, f"/schedules/{schedule_id}/trigger", method="POST")
        await self._record(principal, instance, "schedules.trigger", current, target)
        return ScheduleRun.parse(cast("dict[str, Any]", body) if isinstance(body, dict) else {})

    async def preview(
        self, principal: Principal, ref: str, cron: str, timezone: str, *, count: int, start: datetime | None
    ) -> Preview:
        instance = await self._calls.instance(ref)
        _ = await self._authorizer.require(principal, READ, instance_id=instance.id)
        try:
            return preview(cron, timezone, start=start or utcnow(), count=count)
        except CronError as exc:
            raise ValidationFailedError(str(exc), extra={"fields": list(exc.fields)}) from exc

    async def status(self, principal: Principal, ref: str) -> SchedulerStatus:
        instance = await self._calls.instance(ref)
        _ = await self._authorizer.require(principal, READ, instance_id=instance.id)
        workers = await self._calls.bridge_workers(instance)
        scheduler = cast("dict[str, Any]", (workers or {}).get("scheduler") or {})

        async def allowed(scope: str) -> bool:
            return (await self._authorizer.check(principal, scope, instance_id=instance.id)).allowed

        return SchedulerStatus(
            instance=instance,
            enabled=bool(scheduler.get("enabled")) if workers else None,
            poll_interval_seconds=cast("float | None", scheduler.get("poll_interval_seconds")),
            can_write=await allowed("schedules:write"),
            can_delete=await allowed("schedules:delete"),
            can_custom=await allowed(ADMIN),
        )

    async def endpoint_check(self, principal: Principal, ref: str, method: str, path: str) -> EndpointCheck:
        instance = await self._calls.instance(ref)
        _ = await self._authorizer.require(principal, READ, instance_id=instance.id)
        target = target_of(method, path)
        paths = await self._calls.openapi_paths(instance)
        documented = None if paths is None else any(_path_matches(template, path) for template in paths)
        return EndpointCheck(target=target, documented=documented, needs_admin=target.kind == "custom")

    async def _record(
        self,
        principal: Principal,
        instance: Instance,
        action: str,
        raw: Mapping[str, Any],
        target: Target,
        *,
        changed: list[str] | None = None,
        reason: str | None = None,
    ) -> None:
        name = str(raw.get("name") or raw.get("id") or "")
        _ = await self._audit.record_now(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="schedule",
                resource_id=str(raw.get("id") or ""),
                resource_display=name,
                instance_id=instance.id,
                decision="allowed",
                scope_checked=ADMIN if target.kind == "custom" and action != "schedules.delete" else None,
                response_status=200,
                fields={
                    "schedule": name,
                    "instance": instance.display_name,
                    "target": "custom" if target.kind == "custom" else f"{target.kind} {target.id}",
                },
                links={
                    "target": "custom" if target.kind == "custom" else target.kind,
                    "endpoint": raw.get("endpoint"),
                    "changed": changed,
                    "reason": reason,
                },
                via="web",
            )
        )
