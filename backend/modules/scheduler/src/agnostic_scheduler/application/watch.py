"""The schedule-failure watcher (a periodic job): tell people when a scheduled run fails.

With agnostic-bridge the instance answers ``GET /agnostic/v1/events?since=`` with failed schedule runs since the last
round (one call); without it the watcher lists schedules and their latest runs. Either way the last failure it
announced per schedule is remembered, so each failure is announced once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from agnostic_access.facade import AccessFacade
from agnostic_agentos_client import AgentOSError
from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import Instance, InstancesFacade, InstanceStatus
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.events import EventBus, RealtimeEvent, instance_channel
from agnostic_kernel.logging import get_logger
from agnostic_notifications.facade import NotificationRequest, Notifier
from agnostic_scheduler.application.calls import page_items
from agnostic_scheduler.domain.schedules import ScheduleRun, consecutive_failures

log = get_logger(__name__)

SEEN_TTL = 30 * 24 * 3600
BRIDGE_EVENTS = "/agnostic/v1/events"


@dataclass(frozen=True, slots=True)
class Failure:
    schedule: Mapping[str, Any]
    run: ScheduleRun
    streak: int


class WatchScheduleFailures:
    def __init__(
        self,
        instances: InstancesFacade,
        store: EphemeralStore,
        notifier: Notifier,
        access: AccessFacade,
        identity: IdentityFacade,
        bus: EventBus,
    ) -> None:
        self._instances = instances
        self._store = store
        self._notifier = notifier
        self._access = access
        self._identity = identity
        self._bus = bus

    async def __call__(self) -> int:
        announced = 0
        for instance in await self._instances.list():
            if instance.status is InstanceStatus.DISABLED:
                continue
            try:
                failures = await self._from_bridge(instance)
                if failures is None:
                    failures = await self._from_listing(instance)
            except AgentOSError as exc:
                log.debug("scheduler.watch_skipped", instance=instance.id, error=str(exc))
                continue
            for failure in failures:
                if await self._announce(instance, failure):
                    announced += 1
        return announced

    async def _get(self, instance: Instance, path: str, params: Mapping[str, str | int] | None = None) -> Any:  # noqa: ANN401
        return await self._instances.system_call(instance, "GET", path, params=params)

    async def _from_bridge(self, instance: Instance) -> list[Failure] | None:
        key = f"sch:events-since:{instance.id}"
        stored = await self._store.get(key)
        # The first round starts from now instead of announcing old failures.
        since = int(stored) if stored else int(utcnow().timestamp())
        try:
            body = await self._get(instance, BRIDGE_EVENTS, {"since": since, "limit": 200})
        except AgentOSError as exc:
            if exc.status in {404, 405}:
                return None
            raise
        if not isinstance(body, dict):
            return None
        payload = cast("dict[str, Any]", body)
        failures: list[Failure] = []
        for event in cast("list[dict[str, Any]]", payload.get("events") or []):
            if event.get("type") != "schedule_run.failed":
                continue
            run = ScheduleRun.parse(cast("dict[str, Any]", event.get("data") or {}))
            try:
                schedule = cast("dict[str, Any]", await self._get(instance, f"/schedules/{run.schedule_id}"))
                runs, _ = page_items(await self._get(instance, f"/schedules/{run.schedule_id}/runs", {"limit": 5}))
            except AgentOSError:
                continue
            failures.append(Failure(schedule, run, consecutive_failures([ScheduleRun.parse(r) for r in runs]) or 1))
        await self._store.set(key, str(int(payload.get("next_since") or since)).encode(), ttl=SEEN_TTL)
        return failures

    async def _from_listing(self, instance: Instance) -> list[Failure]:
        items, _ = page_items(await self._get(instance, "/schedules", {"limit": 100, "enabled": "true"}))
        failures: list[Failure] = []
        for schedule in items:
            runs_body = await self._get(instance, f"/schedules/{schedule.get('id')}/runs", {"limit": 5})
            runs = [ScheduleRun.parse(item) for item in page_items(runs_body)[0]]
            if runs and runs[0].failed:
                failures.append(Failure(schedule, runs[0], consecutive_failures(runs)))
        return failures

    async def _announce(self, instance: Instance, failure: Failure) -> bool:
        schedule_id = str(failure.schedule.get("id") or failure.run.schedule_id)
        key = f"sch:failed:{instance.id}:{schedule_id}"
        if await self._store.get(key) == failure.run.id.encode():
            return False
        await self._store.set(key, failure.run.id.encode(), ttl=SEEN_TTL)
        name = str(failure.schedule.get("name") or schedule_id)
        owner = cast("str | None", failure.schedule.get("user_id"))
        recipients = [user.id for user in await self._identity.get_users([owner])] if owner else []
        if not recipients:
            recipients = await self._access.holders(instance.id, scope="schedules:write")
        times = {1: "", 2: " twice"}.get(failure.streak, f" {failure.streak} times in a row")
        link = f"/i/{instance.slug}/scheduler?schedule={schedule_id}"
        actions: list[tuple[str, str, str]] = [("Open schedule", link, "primary")]
        if failure.run.run_id:
            actions.append(("Open trace", f"/i/{instance.slug}/traces?run_id={failure.run.run_id}", "default"))
        _ = await self._notifier.notify(
            NotificationRequest(
                event_type="schedule.failed",
                title=f"{name} failed{times}",
                body=failure.run.error or f"The scheduled run ended {failure.run.status.upper()}.",
                link=link,
                instance_id=instance.id,
                recipients=recipients,
                actions=actions,
                context=instance.display_name,
                data={"schedule_id": schedule_id, "run_id": failure.run.run_id, "streak": failure.streak},
                dedupe_key=f"schedule-failed:{instance.id}:{failure.run.id}",
            )
        )
        await self._bus.publish(
            instance_channel(instance.id),
            RealtimeEvent(
                "schedule.failed",
                {"schedule_id": schedule_id, "name": name, "run_id": failure.run.run_id, "streak": failure.streak},
                instance_id=instance.id,
            ),
        )
        return True
