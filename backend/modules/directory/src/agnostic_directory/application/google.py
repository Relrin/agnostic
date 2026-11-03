"""Google Workspace directory sync (Google can't push SCIM to custom apps, so Agnostic pulls).

A service account with domain-wide delegation reads groups and users as a Workspace admin, with only the
``admin.directory.group.readonly`` and ``admin.directory.user.readonly`` scopes. Each run:

- every Google group the filter selects becomes (or updates) a ``google_directory`` group whose members are the
  org members with a matching email (primary or alias); people who aren't org members are counted as unmatched,
  never invited;
- a group that is no longer selected (or was deleted in Google) loses its members but is kept with its bindings,
  so a filter typo doesn't wipe role bindings; delete it here once it is gone for good;
- org members whose email is in a Workspace domain but whose Google user is suspended or gone are deprovisioned;
- mapping rules are applied.

The key is sealed with the installation's master key; responses only ever show the service account's email.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import orjson

from agnostic_audit.facade import AuditEntry, actor_of
from agnostic_directory.application.groups import READ, WRITE
from agnostic_directory.application.ports import GoogleDirectoryError, GoogleUser
from agnostic_directory.application.sync import Deprovisioner, RuleApplier, SyncContext
from agnostic_directory.domain.groups import GROUP_ID_PREFIX, Group, GroupMember, InvalidGroupError, clean_group_name
from agnostic_directory.domain.sync import (
    GOOGLE_ACTOR,
    GoogleCredentials,
    GoogleRecord,
    InvalidSyncConfigError,
    clean_group_filter,
    group_selected,
)
from agnostic_identity.facade import User, normalize_email
from agnostic_kernel.auth import Principal
from agnostic_kernel.crypto import SecretDecryptionError
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import bump_access_generation
from agnostic_kernel.errors import ConflictError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

VIA = "google"
GOOGLE_PRINCIPAL = Principal(kind="system", id="google_directory", display_name=GOOGLE_ACTOR, via=VIA)
SETTINGS_LINK = "/settings/directory?tab=google"


@dataclass(frozen=True, slots=True)
class GoogleView:
    configured: bool
    client_email: str | None
    admin_subject: str | None
    customer_id: str | None
    group_filter: tuple[str, ...]
    enabled: bool
    record: GoogleRecord


@dataclass(frozen=True, slots=True)
class GoogleTest:
    ok: bool
    detail: str


def parse_service_account(text: str) -> tuple[str, str, str | None]:
    """``(client_email, private_key, private_key_id)`` from the JSON key file Google hands out."""
    try:
        data = orjson.loads(text)
    except orjson.JSONDecodeError as exc:
        raise InvalidSyncConfigError("Paste the service account's JSON key file.") from exc
    if not isinstance(data, dict):
        raise InvalidSyncConfigError("Paste the service account's JSON key file.")
    fields = cast("dict[str, object]", data)
    if fields.get("type") != "service_account":
        raise InvalidSyncConfigError('The key file must be for a service account ("type": "service_account").')
    client_email, private_key = fields.get("client_email"), fields.get("private_key")
    if not isinstance(client_email, str) or not isinstance(private_key, str) or "PRIVATE KEY" not in private_key:
        raise InvalidSyncConfigError("The key file needs client_email and private_key.")
    key_id = fields.get("private_key_id")
    return client_email, private_key, key_id if isinstance(key_id, str) else None


class GoogleSettings:
    def __init__(self, context: SyncContext, runner: GoogleSyncRunner) -> None:
        self.c = context
        self._runner = runner

    async def get(self, principal: Principal) -> GoogleView:
        _ = await self.c.authorizer.require(principal, READ)
        return await self._view()

    async def update(
        self,
        principal: Principal,
        *,
        service_account_json: str | None = None,
        admin_subject: str | None = None,
        customer_id: str | None = None,
        group_filter: list[str] | None = None,
        enabled: bool | None = None,
    ) -> GoogleView:
        _ = await self.c.authorizer.require(principal, WRITE)
        current = await self._credentials()
        changes: list[str] = []
        try:
            credentials = merge_credentials(
                current,
                service_account_json=service_account_json,
                admin_subject=admin_subject,
                customer_id=customer_id,
                changes=changes,
            )
            filters = clean_group_filter(group_filter) if group_filter is not None else None
        except InvalidSyncConfigError as exc:
            raise ValidationFailedError(str(exc)) from exc
        if enabled and credentials is None:
            raise ValidationFailedError("Add the service account before turning the sync on.")
        if filters is not None:
            changes.append("group filter")
        if enabled is not None:
            changes.append("enabled" if enabled else "disabled")
        sealed = None
        if credentials is not None and credentials != current:
            sealed = self.c.box.seal(orjson.dumps(_credentials_json(credentials)))
        await self.c.config.save_google(config_enc=sealed, group_filter=filters, enabled=enabled)
        if changes:
            _ = await self.c.audit.record(
                AuditEntry(
                    action="directory.google.update",
                    actor=actor_of(principal),
                    resource_kind="directory_settings",
                    resource_id="google",
                    resource_display="Google Workspace sync",
                    fields={"change": ", ".join(changes)},
                    links={"settings": SETTINGS_LINK},
                )
            )
        await self.c.config.commit()
        return await self._view()

    async def test(self, principal: Principal) -> GoogleTest:
        _ = await self.c.authorizer.require(principal, WRITE)
        credentials = await self._credentials()
        if credentials is None:
            return GoogleTest(ok=False, detail="Add the service account and the admin first.")
        try:
            admin = await self.c.google.user(credentials, credentials.admin_subject)
            groups = await self.c.google.groups(credentials)
        except GoogleDirectoryError as exc:
            return GoogleTest(ok=False, detail=str(exc))
        record = await self.c.config.google()
        selected = [g for g in groups if group_selected(record.group_filter, email=g.email, name=g.name)]
        return GoogleTest(
            ok=True,
            detail=f"Connected as {admin.primary_email}; {len(selected)} of {len(groups)} groups match the filter.",
        )

    async def sync_now(self, principal: Principal) -> GoogleView:
        _ = await self.c.authorizer.require(principal, WRITE)
        if await self._credentials() is None:
            raise ValidationFailedError("Add the service account and the admin first.")
        counts = await self._runner.run(scheduled=False)
        _ = await self.c.audit.record(
            AuditEntry(
                action="directory.google.sync",
                actor=actor_of(principal),
                resource_kind="directory_settings",
                resource_id="google",
                resource_display="Google Workspace sync",
                fields={key: str(value) for key, value in (counts or {}).items()}
                | {"outcome": "failed" if counts is None else "done"},
                links={"settings": SETTINGS_LINK},
            )
        )
        await self.c.config.commit()
        return await self._view()

    async def _credentials(self) -> GoogleCredentials | None:
        return open_credentials(self.c, await self.c.config.google())

    async def _view(self) -> GoogleView:
        record = await self.c.config.google()
        credentials = open_credentials(self.c, record)
        return GoogleView(
            configured=credentials is not None,
            client_email=credentials.client_email if credentials else None,
            admin_subject=credentials.admin_subject if credentials else None,
            customer_id=credentials.customer_id if credentials else None,
            group_filter=record.group_filter,
            enabled=record.enabled,
            record=record,
        )


def merge_credentials(
    current: GoogleCredentials | None,
    *,
    service_account_json: str | None,
    admin_subject: str | None,
    customer_id: str | None,
    changes: list[str],
) -> GoogleCredentials | None:
    """The credentials after an update; omitted fields keep their value. Appends what changed to ``changes``."""
    if service_account_json is None and admin_subject is None and customer_id is None:
        return current
    if service_account_json is not None:
        client_email, private_key, key_id = parse_service_account(service_account_json)
        changes.append("service account")
    elif current is not None:
        client_email, private_key, key_id = current.client_email, current.private_key, current.private_key_id
    else:
        raise InvalidSyncConfigError("Add the service account's JSON key first.")
    if admin_subject is not None:
        changes.append("admin")
    if customer_id is not None:
        changes.append("customer")
    subject = admin_subject if admin_subject is not None else (current.admin_subject if current else "")
    try:
        subject = normalize_email(subject)
    except ValueError as exc:
        raise InvalidSyncConfigError("The admin must be a Workspace admin's email address.") from exc
    return GoogleCredentials(
        client_email=client_email,
        private_key=private_key,
        private_key_id=key_id,
        admin_subject=subject,
        customer_id=(customer_id or "").strip() or (current.customer_id if current else "my_customer"),
    )


def _credentials_json(credentials: GoogleCredentials) -> dict[str, str | None]:
    return {
        "client_email": credentials.client_email,
        "private_key": credentials.private_key,
        "private_key_id": credentials.private_key_id,
        "admin_subject": credentials.admin_subject,
        "customer_id": credentials.customer_id,
    }


def open_credentials(context: SyncContext, record: GoogleRecord) -> GoogleCredentials | None:
    if not record.config_enc:
        return None
    try:
        data: dict[str, str | None] = orjson.loads(context.box.open(record.config_enc))
    except (SecretDecryptionError, orjson.JSONDecodeError) as exc:
        log.warning("directory.google_config_unreadable", error=str(exc))
        return None
    return GoogleCredentials(
        client_email=data.get("client_email") or "",
        private_key=data.get("private_key") or "",
        private_key_id=data.get("private_key_id"),
        admin_subject=data.get("admin_subject") or "",
        customer_id=data.get("customer_id") or "my_customer",
    )


class GoogleSyncRunner:
    def __init__(self, context: SyncContext, deprovisioner: Deprovisioner, rules: RuleApplier) -> None:
        self.c = context
        self._deprovisioner = deprovisioner
        self._rules = rules

    async def run(self, *, scheduled: bool) -> dict[str, int] | None:
        """One sync; commits. ``None`` when it didn't run (not configured, turned off) or Google refused."""
        record = await self.c.config.google()
        credentials = open_credentials(self.c, record)
        if credentials is None or (scheduled and not record.enabled):
            return None
        try:
            counts = await self._sync(credentials, record.group_filter)
        except GoogleDirectoryError as exc:
            await self.c.config.rollback()
            log.warning("directory.google_sync_failed", error=str(exc))
            await self.c.config.record_google_run(error=str(exc), counts=None)
            await self.c.config.commit()
            return None
        await self.c.config.record_google_run(error=None, counts=counts)
        await self.c.config.commit()
        await bump_access_generation(self.c.store)
        return counts

    async def _sync(self, credentials: GoogleCredentials, group_filter: tuple[str, ...]) -> dict[str, int]:
        # Read everything first: nothing changes unless Google answered every page.
        google_groups = [
            group
            for group in await self.c.google.groups(credentials)
            if group_selected(group_filter, email=group.email, name=group.name)
        ]
        group_members = {group.id: await self.c.google.member_emails(credentials, group.id) for group in google_groups}
        google_users = await self.c.google.users(credentials)

        people = await self._people()
        addresses = _addresses(google_users)
        existing = {group.external_id: group for group in await self.c.groups.list_by_source("google_directory")}
        unmatched: set[str] = set()
        memberships = 0
        for google_group in google_groups:
            group = existing.pop(google_group.id, None)
            group = await self._upsert(group, google_group.id, google_group.name, google_group.email)
            wanted: set[str] = set()
            for email in group_members[google_group.id]:
                candidates = addresses.get(email.lower(), (email.lower(),))
                user = next((people[address] for address in candidates if address in people), None)
                if user is None:
                    unmatched.add(email.lower())
                else:
                    wanted.add(user.id)
            memberships += len(wanted)
            await self._set_members(group, wanted)
        for stale in existing.values():
            await self._set_members(stale, set())

        deprovisioned = 0
        for user in self._gone(people, google_users):
            try:
                outcome = await self._deprovisioner.deprovision(user, actor=GOOGLE_PRINCIPAL)
            except ConflictError as exc:
                log.warning("directory.google_deprovision_skipped", user_id=user.id, reason=str(exc))
                continue
            await self._deprovisioner.audit(GOOGLE_PRINCIPAL, "directory.users.deprovision", user, outcome, via=VIA)
            deprovisioned += 1
        _ = await self._rules.apply()
        return {
            "groups": len(google_groups),
            "memberships": memberships,
            "unmatched": len(unmatched),
            "deprovisioned": deprovisioned,
            "users": len(google_users),
        }

    async def _people(self) -> dict[str, User]:
        """Active org members by email."""
        member_ids = [member.user_id for member in await self.c.org.members()]
        return {user.email.lower(): user for user in await self.c.identity.get_users(member_ids) if user.active}

    @staticmethod
    def _gone(people: dict[str, User], google_users: list[GoogleUser]) -> list[User]:
        """Members in a Workspace domain whose Google user is suspended or no longer exists."""
        if not google_users:
            return []
        domains = {user.primary_email.lower().rpartition("@")[2] for user in google_users}
        active = {
            email.lower()
            for user in google_users
            if not user.suspended
            for email in (user.primary_email, *user.aliases)
        }
        return [user for email, user in people.items() if email.rpartition("@")[2] in domains and email not in active]

    async def _upsert(self, group: Group | None, external_id: str, name: str, email: str) -> Group:
        if group is not None:
            if group.external_name != email or group.name != name:
                renamed = await self._free_name(name, keep=group)
                group = await self.c.groups.update(group.id, name=renamed, external_name=email)
            return group
        now = utcnow()
        group = Group(
            id=new_id(GROUP_ID_PREFIX),
            name=await self._free_name(name),
            description="",
            source="google_directory",
            external_id=external_id,
            external_name=email,
            created_at=now,
            updated_at=now,
        )
        await self.c.groups.add(group)
        return group

    async def _free_name(self, name: str, keep: Group | None = None) -> str:
        try:
            for candidate in (clean_group_name(name), clean_group_name(f"{name} (Google)")):
                other = await self.c.groups.find_by_name(candidate)
                if other is None or (keep is not None and other.id == keep.id):
                    return candidate
            return clean_group_name(f"{name} ({new_id(GROUP_ID_PREFIX)[-6:]})")
        except InvalidGroupError as exc:
            raise GoogleDirectoryError(f"The Google group {name!r} can't be used: {exc}") from exc

    async def _set_members(self, group: Group, wanted: set[str]) -> None:
        current = {member.user_id for member in await self.c.groups.members(group.id)}
        now = utcnow()
        for user_id in wanted - current:
            _ = await self.c.groups.add_member(
                GroupMember(group_id=group.id, user_id=user_id, role="member", source="google_directory", added_at=now)
            )
        for user_id in current - wanted:
            _ = await self.c.groups.remove_member(group.id, user_id)


def _addresses(google_users: list[GoogleUser]) -> dict[str, tuple[str, ...]]:
    """Each address (primary or alias) → all of that person's addresses, so either one matches the account."""
    result: dict[str, tuple[str, ...]] = {}
    for user in google_users:
        emails = tuple(dict.fromkeys(e.lower() for e in (user.primary_email, *user.aliases)))
        for email in emails:
            result[email] = emails
    return result
