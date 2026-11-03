"""Notifications for other modules' domain events (they publish, this module decides who hears about it)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import InstancesFacade
from agnostic_notifications.application.notify import NotificationRequest, Notify
from agnostic_org.facade import OrgFacade, OrgRole

ADMIN_ROLES = frozenset({OrgRole.OWNER, OrgRole.ADMINISTRATOR})


class Announcements:
    def __init__(self, notify: Notify, org: OrgFacade, identity: IdentityFacade, instances: InstancesFacade) -> None:
        self._notify = notify
        self._org = org
        self._identity = identity
        self._instances = instances

    async def _instance(self, instance_id: object) -> tuple[str | None, str, str | None]:
        """``(id, display name, slug)``; "all instances" when the event isn't about one."""
        if not isinstance(instance_id, str) or not instance_id:
            return None, "all instances", None
        instance = await self._instances.get(instance_id)
        if instance is None:
            return instance_id, instance_id, None
        return instance.id, instance.display_name, instance.slug

    async def privileged_grant(self, payload: Mapping[str, Any]) -> None:
        person_id = str(payload.get("user_id") or "")
        person = await self._identity.get_user(person_id)
        instance_id, where, _ = await self._instance(payload.get("instance_id"))
        grant = payload.get("role_name") or ", ".join(payload.get("scopes") or [])
        admins = [
            member.user_id for member in await self._org.members() if member.active and member.org_role in ADMIN_ROLES
        ]
        expires = payload.get("expires_at")
        granted_by = payload.get("granted_by_name") or "Someone"
        who = person.display_name if person else person_id
        _ = await self._notify(
            NotificationRequest(
                event_type="access.privileged_grant",
                title=f"{granted_by} gave {who} {grant} on {where}",
                body=f"Privileged scopes: {', '.join(payload.get('scopes') or [])}."
                + (f" Expires {expires}." if expires else " No expiry."),
                link="/access/people",
                instance_id=instance_id,
                recipients=admins,
                data=dict(payload),
                dedupe_key=f"grant:{payload.get('binding_id')}",
            )
        )

    async def eval_regression(self, payload: Mapping[str, Any]) -> None:
        instance_id, where, slug = await self._instance(payload.get("instance_id"))
        regressions = int(payload.get("regressions") or 0)
        component = str(payload.get("component_id") or "")
        batch_id = str(payload.get("batch_id") or "")
        link = f"/i/{slug}/evals?evaluation={batch_id}" if slug else None
        _ = await self._notify(
            NotificationRequest(
                event_type="evals.regression",
                title=f"{component} regressed on {regressions} case{'s' if regressions != 1 else ''}",
                body=f"{payload.get('batch_name') or 'The evaluation'} on {payload.get('dataset_name')} scored worse "
                f"than the previous run ({payload.get('fixes') or 0} fixed).",
                link=link,
                instance_id=instance_id,
                recipients=[str(payload["started_by"])] if payload.get("started_by") else [],
                actions=(("Compare runs", link, "primary"),) if link else (),
                context=where,
                data=dict(payload),
                dedupe_key=f"regression:{batch_id}",
            )
        )
