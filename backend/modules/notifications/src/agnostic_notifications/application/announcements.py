"""Notifications for other modules' domain events (they publish, this module decides who hears about it)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import InstancesFacade
from agnostic_notifications.application.notify import NotificationRequest, Notify
from agnostic_org.facade import OrgFacade, OrgRole

ADMIN_ROLES = frozenset({OrgRole.OWNER, OrgRole.ADMINISTRATOR})


def _strings(value: object) -> list[str]:
    return [str(item) for item in cast("list[object]", value)] if isinstance(value, list) else []


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

    async def _admins(self, *, owners_only: bool = False) -> list[str]:
        roles = {OrgRole.OWNER} if owners_only else ADMIN_ROLES
        return [member.user_id for member in await self._org.members() if member.active and member.org_role in roles]

    async def access_request_created(self, payload: Mapping[str, Any]) -> None:
        who = payload.get("requester_name") or "Someone"
        hours = payload.get("duration_hours")
        _ = await self._notify(
            NotificationRequest(
                event_type="access.request_created",
                title=f"{who} asks for {payload.get('grant')} on {payload.get('where')}",
                body=f"For {hours} h. Reason: {payload.get('reason')}",
                link="/access/people?tab=requests",
                instance_id=payload.get("instance_id") or None,
                recipients=_strings(payload.get("approver_ids")),
                actions=(("Review request", "/access/people?tab=requests", "primary"),),
                data=dict(payload),
                dedupe_key=f"access-request:{payload.get('request_id')}",
            )
        )

    async def access_request_decided(self, payload: Mapping[str, Any]) -> None:
        status = str(payload.get("status") or "")
        decided_by = payload.get("decided_by_name") or "An approver"
        expires = payload.get("expires_at")
        body = f"Until {expires}." if status == "approved" and expires else ""
        if payload.get("note"):
            body = f"{body} {decided_by}: {payload.get('note')}".strip()
        _ = await self._notify(
            NotificationRequest(
                event_type="access.request_decided",
                title=f"{decided_by} {status} your request for {payload.get('grant')} on {payload.get('where')}",
                body=body,
                link="/access/people?tab=requests",
                instance_id=payload.get("instance_id") or None,
                recipients=[str(payload["requester_id"])] if payload.get("requester_id") else [],
                data=dict(payload),
                dedupe_key=f"access-decision:{payload.get('request_id')}",
            )
        )

    async def privileged_service_account(self, payload: Mapping[str, Any]) -> None:
        creator = payload.get("created_by_name") or "Someone"
        scopes = ", ".join(_strings(payload.get("privileged_scopes") or payload.get("scopes")))
        _ = await self._notify(
            NotificationRequest(
                event_type="service_accounts.privileged_created",
                title=f"{creator} created the privileged service account {payload.get('principal')}",
                body=f"Privileged scopes: {scopes}.",
                link=f"/access/service-accounts?account={payload.get('service_account_id')}",
                recipients=await self._admins(owners_only=True),
                data=dict(payload),
                dedupe_key=f"privileged-sa:{payload.get('service_account_id')}",
            )
        )

    async def break_glass_used(self, payload: Mapping[str, Any]) -> None:
        _ = await self._notify(
            NotificationRequest(
                event_type="identity.break_glass_used",
                title=f"{payload.get('user_name') or 'The break-glass account'} signed in with a password",
                body="SSO is enforced; this is the break-glass account. "
                f"From {payload.get('ip') or 'an unknown address'}.",
                link="/access/audit?action=auth.break_glass",
                recipients=await self._admins(owners_only=True),
                data=dict(payload),
            )
        )

    async def audit_archive_failed(self, payload: Mapping[str, Any]) -> None:
        month = payload.get("month")
        _ = await self._notify(
            NotificationRequest(
                event_type="audit.archive_failed",
                title=f"Archiving the audit log for {month} failed",
                body=f"The events stay in the database until the archive works. {payload.get('error') or ''}".strip(),
                link="/org/settings/audit-retention",
                recipients=await self._admins(),
                data=dict(payload),
                dedupe_key=f"archive-failed:{month}",
            )
        )

    async def audit_sink_failing(self, payload: Mapping[str, Any]) -> None:
        _ = await self._notify(
            NotificationRequest(
                event_type="audit.sink_failing",
                title=f"Audit events can't reach {payload.get('name') or 'a SIEM destination'}",
                body=str(payload.get("error") or ""),
                link="/org/settings/siem",
                recipients=await self._admins(),
                data=dict(payload),
            )
        )

    async def privileged_grant(self, payload: Mapping[str, Any]) -> None:
        person_id = str(payload.get("user_id") or "")
        person = await self._identity.get_user(person_id) if payload.get("principal_kind", "user") == "user" else None
        instance_id, where, _ = await self._instance(payload.get("instance_id"))
        grant = payload.get("role_name") or ", ".join(payload.get("scopes") or [])
        admins = [
            member.user_id for member in await self._org.members() if member.active and member.org_role in ADMIN_ROLES
        ]
        expires = payload.get("expires_at")
        granted_by = payload.get("granted_by_name") or "Someone"
        who = person.display_name if person else str(payload.get("principal_name") or person_id)
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
