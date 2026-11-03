"""SCIM 2.0 provisioning: the IdP (Okta, Entra ID, OneLogin…) pushes people and groups.

Users are the org's people: ``GET /Users`` lists every member (so the IdP can match existing accounts by
``userName``) plus everyone it provisioned, deactivated or not. The IdP's own data (``externalId``, ``userName``,
the resource as sent) is kept beside the account; the account's email never changes through SCIM. Creating a user
provisions a password-less account (it signs in through SSO) and admits it to the org; ``active: false`` deprovisions
it, ``active: true`` brings it back, and ``DELETE`` deprovisions it and removes it from the org.

Groups are ``scim`` groups: their membership is what the IdP says, and mapping rules carry it into manual groups.

The caller is the SCIM token, audited as a system actor named after the token's label ("Okta SCIM").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import cast

from agnostic_audit.facade import AuditEntry, actor_of
from agnostic_directory.application.sync import Deprovisioned, Deprovisioner, RuleApplier, SeatsFullError, SyncContext
from agnostic_directory.domain.groups import (
    GROUP_ID_PREFIX,
    Group,
    GroupMember,
    InvalidGroupError,
    affects,
    clean_group_name,
)
from agnostic_directory.domain.scim import (
    GROUP_SCHEMA,
    USER_SCHEMA,
    Json,
    Page,
    ScimError,
    display_name_of,
    get_attr,
    get_str,
    member_ids,
    primary_email,
    put_attr,
)
from agnostic_directory.domain.scim_filter import Filter, ScimFilterError, coerce_bool, equality, matches, parse_filter
from agnostic_directory.domain.scim_patch import ScimPatchError, apply_patch, parse_operations
from agnostic_directory.domain.sync import ScimUser
from agnostic_identity.facade import CreatedVia, User, UserStatus, normalize_email
from agnostic_kernel.auth import Principal
from agnostic_kernel.crypto import hash_token, tokens_equal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import bump_access_generation
from agnostic_kernel.errors import ConflictError
from agnostic_kernel.ids import new_id

VIA = "scim"
SERVER_ATTRIBUTES = ("id", "meta", "groups", "password")
TOUCH_EVERY = timedelta(minutes=1)


def scim_principal(token_id: str, label: str) -> Principal:
    return Principal(kind="system", id=token_id, display_name=label, via=VIA)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _filter(text: str | None) -> Filter | None:
    if not text or not text.strip():
        return None
    try:
        return parse_filter(text)
    except ScimFilterError as exc:
        raise ScimError(400, str(exc), "invalidFilter") from exc


def _patched(resource: Json, body: Mapping[str, object]) -> Json:
    try:
        return apply_patch(resource, parse_operations(body))
    except ScimPatchError as exc:
        raise ScimError(400, str(exc), exc.scim_type) from exc
    except ScimFilterError as exc:
        raise ScimError(400, str(exc), "invalidPath") from exc


def _client_data(body: Mapping[str, object]) -> Json:
    """The resource as the IdP sent it, minus what the server owns (and any password)."""
    return {key: value for key, value in body.items() if key.lower() not in SERVER_ATTRIBUTES}


class ScimAuth:
    def __init__(self, context: SyncContext) -> None:
        self.c = context

    async def authenticate(self, authorization: str | None) -> Principal:
        scheme, _, credentials = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not credentials.strip():
            raise ScimError(401, "Send the SCIM token as 'Authorization: Bearer <token>'.")
        digest = hash_token(credentials.strip())
        token = await self.c.scim.token_by_hash(digest)
        now = utcnow()
        if token is None or not tokens_equal(token.token_hash, digest) or not token.usable(now):
            raise ScimError(401, "The SCIM token isn't valid: it is unknown, revoked or past its rotation window.")
        if token.last_used_at is None or now - token.last_used_at > TOUCH_EVERY:
            await self.c.scim.update_token(token.id, last_used_at=now)
            await self.c.scim.commit()
        return scim_principal(token.id, token.label)


class ScimRecorder:
    """Keeps ``dir_scim_sync_state`` current: the status pill shows the last request and the last error."""

    def __init__(self, context: SyncContext) -> None:
        self.c = context

    async def succeeded(self) -> None:
        await self.c.scim.record_request(counts=await self.c.scim.counts())
        await self.c.scim.commit()

    async def failed(self, error: ScimError) -> None:
        await self.c.scim.rollback()
        await self.c.scim.record_request(error=f"{error.status}: {error.detail}")
        await self.c.scim.commit()


class ScimUsers:
    def __init__(self, context: SyncContext, deprovisioner: Deprovisioner) -> None:
        self.c = context
        self._deprovisioner = deprovisioner

    async def list(self, *, filter_text: str | None, page: Page) -> tuple[list[Json], int]:
        query = _filter(filter_text)
        user_ids = await self._candidates(query)
        resources = await self._resources(user_ids)
        if query is not None:
            resources = [resource for resource in resources if matches(query, resource)]
        return page.slice(resources), len(resources)

    async def get(self, user_id: str) -> Json:
        resources = await self._resources([user_id])
        if not resources:
            raise ScimError(404, f"There is no user {user_id}.")
        return resources[0]

    async def create(self, actor: Principal, body: Mapping[str, object]) -> Json:
        user_name = get_str(body, "userName")
        if user_name is None:
            raise ScimError(400, "userName is required.", "invalidValue")
        external_id = get_str(body, "externalId")
        if await self.c.scim.user_by_name(user_name) is not None:
            raise ScimError(409, f"A user with userName {user_name} already exists.", "uniqueness")
        if external_id and await self.c.scim.user_by_external_id(external_id) is not None:
            raise ScimError(409, f"A user with externalId {external_id} already exists.", "uniqueness")
        email = self._email(body, user_name)
        active = coerce_bool(get_attr(body, "active"))
        active = True if active is None else active
        existing = await self.c.identity.find_user_by_email(email)
        if existing is not None and await self.c.scim.user(existing.id) is not None:
            raise ScimError(409, f"{email} is already provisioned.", "uniqueness")
        if existing is None:
            user = await self.c.identity.provision_user(email, display_name_of(body), via=CreatedVia.SCIM)
            if not active:
                user = await self.c.identity.set_status(user.id, UserStatus.DEPROVISIONED)
        else:
            user = await self._rename(existing, display_name_of(body))
        now = utcnow()
        await self.c.scim.save_user(
            ScimUser(
                user_id=user.id,
                external_id=external_id,
                user_name=user_name,
                active=active,
                raw=_client_data(body),
                created_at=now,
                updated_at=now,
            )
        )
        if active:
            await self._reactivate(user)
        elif existing is not None and existing.active:
            _ = await self._deprovision(actor, existing, leave=None)
        await self._audit(actor, "scim.users.create", user, fields={"user_name": user_name})
        await self.c.scim.commit()
        return await self.get(user.id)

    async def replace(self, actor: Principal, user_id: str, body: Mapping[str, object]) -> Json:
        user, scim_user = await self._known(user_id)
        return await self._update(actor, user, scim_user, _client_data(body))

    async def patch(self, actor: Principal, user_id: str, body: Mapping[str, object]) -> Json:
        user, scim_user = await self._known(user_id)
        current = await self.get(user_id)
        return await self._update(actor, user, scim_user, _client_data(_patched(current, body)))

    async def delete(self, actor: Principal, user_id: str) -> None:
        user, _ = await self._known(user_id)
        outcome = await self._deprovision(actor, user, leave=True)
        await self.c.scim.delete_user(user.id)
        await self._deprovisioner.audit(actor, "scim.users.delete", user, outcome, via=VIA)
        await self.c.scim.commit()

    async def _update(self, actor: Principal, user: User, scim_user: ScimUser | None, data: Json) -> Json:
        user_name = get_str(data, "userName") or (scim_user.user_name if scim_user else user.email)
        other = await self.c.scim.user_by_name(user_name)
        if other is not None and other.user_id != user.id:
            raise ScimError(409, f"A user with userName {user_name} already exists.", "uniqueness")
        external_id = get_str(data, "externalId")
        if external_id:
            other = await self.c.scim.user_by_external_id(external_id)
            if other is not None and other.user_id != user.id:
                raise ScimError(409, f"A user with externalId {external_id} already exists.", "uniqueness")
        active = coerce_bool(get_attr(data, "active"))
        if active is None:
            active = user.active
        put_attr(data, "active", active)
        before = {k.lower(): v for k, v in (scim_user.raw if scim_user else {}).items() if k.lower() != "active"}
        after = {k.lower(): v for k, v in data.items() if k.lower() != "active"}
        changes = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
        renamed = await self._rename(user, display_name_of(data))
        await self.c.scim.save_user(
            ScimUser(
                user_id=user.id,
                external_id=external_id,
                user_name=user_name,
                active=active,
                raw=data,
                created_at=scim_user.created_at if scim_user else utcnow(),
                updated_at=utcnow(),
            )
        )
        if changes or renamed.display_name != user.display_name:
            await self._audit(
                actor, "scim.users.update", renamed, fields={"change": ", ".join(changes) or "displayName"}
            )
        if active and not user.active:
            await self._reactivate(renamed)
            await self._audit(actor, "scim.users.reactivate", renamed)
        elif not active and user.active:
            outcome = await self._deprovision(actor, renamed, leave=None)
            await self._deprovisioner.audit(actor, "scim.users.deactivate", renamed, outcome, via=VIA)
        await self.c.scim.commit()
        return await self.get(user.id)

    async def _deprovision(self, actor: Principal, user: User, *, leave: bool | None) -> Deprovisioned:
        try:
            return await self._deprovisioner.deprovision(user, actor=actor, leave=leave)
        except ConflictError as exc:
            raise ScimError(409, exc.detail or exc.title, "mutability") from exc

    async def _reactivate(self, user: User) -> None:
        try:
            await self._deprovisioner.reactivate(user, via=VIA)
        except SeatsFullError as exc:
            raise ScimError(403, exc.detail or exc.title) from exc

    async def _rename(self, user: User, display_name: str | None) -> User:
        if display_name and display_name != user.display_name:
            return await self.c.identity.update_user(user.id, display_name=display_name)
        return user

    @staticmethod
    def _email(body: Mapping[str, object], user_name: str) -> str:
        candidate = primary_email(body) or user_name
        try:
            return normalize_email(candidate)
        except ValueError as exc:
            raise ScimError(400, f"{candidate!r} is not an email address; send one in emails.", "invalidValue") from exc

    async def _known(self, user_id: str) -> tuple[User, ScimUser | None]:
        user = await self.c.identity.get_user(user_id)
        scim_user = await self.c.scim.user(user_id)
        if user is None or (scim_user is None and await self.c.org.member(user_id) is None):
            raise ScimError(404, f"There is no user {user_id}.")
        return user, scim_user

    async def _candidates(self, query: Filter | None) -> list[str] | None:
        """User ids worth looking at for an indexed ``eq`` filter; ``None`` means everyone."""
        lookup = equality(query) if query is not None else None
        if lookup is None:
            return None
        attribute, value = lookup
        if attribute == "id":
            return [value]
        if attribute == "externalid":
            found = await self.c.scim.user_by_external_id(value)
            return [found.user_id] if found else []
        if attribute in {"username", "emails.value"}:
            ids: list[str] = []
            if attribute == "username" and (found := await self.c.scim.user_by_name(value)) is not None:
                ids.append(found.user_id)
            try:
                if (user := await self.c.identity.find_user_by_email(value)) is not None:
                    ids.append(user.id)
            except ValueError:
                pass
            return list(dict.fromkeys(ids))
        return None

    async def _resources(self, user_ids: Sequence[str] | None) -> list[Json]:
        scim_users = {row.user_id: row for row in await self.c.scim.users()}
        members = {member.user_id for member in await self.c.org.members()}
        if user_ids is None:
            user_ids = [*members, *(uid for uid in scim_users if uid not in members)]
        known = [uid for uid in dict.fromkeys(user_ids) if uid in members or uid in scim_users]
        users = sorted(await self.c.identity.get_users(known), key=lambda u: (u.created_at, u.id))
        names = {group.id: group.name for group in await self.c.groups.list()}
        memberships = await self.c.groups.memberships_of([user.id for user in users])
        return [
            self._resource(user, scim_users.get(user.id), [(gid, names.get(gid, gid)) for gid in memberships[user.id]])
            for user in users
        ]

    def _resource(self, user: User, scim_user: ScimUser | None, groups: list[tuple[str, str]]) -> Json:
        base = self.c.policy.scim_base_url
        resource: Json = dict(scim_user.raw) if scim_user else {}
        schemas = get_attr(resource, "schemas")
        put_attr(
            resource,
            "schemas",
            cast("list[object]", schemas) if isinstance(schemas, list) and schemas else [USER_SCHEMA],
        )
        put_attr(resource, "id", user.id)
        put_attr(resource, "externalId", scim_user.external_id if scim_user else None)
        put_attr(resource, "userName", scim_user.user_name if scim_user else user.email)
        put_attr(resource, "displayName", user.display_name)
        if not isinstance(get_attr(resource, "name"), Mapping):
            put_attr(resource, "name", {"formatted": user.display_name})
        if not isinstance(get_attr(resource, "emails"), list) or primary_email(resource) is None:
            put_attr(resource, "emails", [{"value": user.email, "type": "work", "primary": True}])
        put_attr(resource, "active", user.status is UserStatus.ACTIVE)
        put_attr(
            resource,
            "groups",
            [{"value": gid, "display": name, "$ref": f"{base}/Groups/{gid}"} for gid, name in groups] or None,
        )
        put_attr(
            resource,
            "meta",
            {
                "resourceType": "User",
                "created": _iso(user.created_at),
                "lastModified": _iso(scim_user.updated_at if scim_user else user.created_at),
                "location": f"{base}/Users/{user.id}",
            },
        )
        return resource

    async def _audit(self, actor: Principal, action: str, user: User, *, fields: dict[str, str] | None = None) -> None:
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(actor),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.display_name,
                fields={"person": user.display_name, "email": user.email, **(fields or {})},
                links={"person": f"/access/people?person={user.id}"},
                via=VIA,
            )
        )


class ScimGroups:
    def __init__(self, context: SyncContext, rules: RuleApplier) -> None:
        self.c = context
        self._rules = rules

    async def list(self, *, filter_text: str | None, page: Page) -> tuple[list[Json], int]:
        query = _filter(filter_text)
        resources = [await self._resource(group) for group in await self.c.groups.list_by_source("scim")]
        if query is not None:
            resources = [resource for resource in resources if matches(query, resource)]
        return page.slice(resources), len(resources)

    async def get(self, group_id: str) -> Json:
        return await self._resource(await self._group(group_id))

    async def create(self, actor: Principal, body: Mapping[str, object]) -> Json:
        display = get_str(body, "displayName")
        if display is None:
            raise ScimError(400, "displayName is required.", "invalidValue")
        external_id = get_str(body, "externalId")
        for group in await self.c.groups.list_by_source("scim"):
            if (group.external_name or "").lower() == display.lower() or (
                external_id and group.external_id == external_id
            ):
                raise ScimError(409, f"The group {display} already exists.", "uniqueness")
        now = utcnow()
        group_id = new_id(GROUP_ID_PREFIX)
        group = Group(
            id=group_id,
            name=await self._free_name(display),
            description="",
            source="scim",
            external_id=external_id or group_id,
            external_name=display,
            created_at=now,
            updated_at=now,
        )
        await self.c.groups.add(group)
        added, _ = await self._set_members(group, member_ids(body))
        await self._audit(actor, "scim.groups.create", group, added=added, removed=[])
        await self._finish()
        return await self.get(group.id)

    async def replace(self, actor: Principal, group_id: str, body: Mapping[str, object]) -> Json:
        return await self._update(actor, await self._group(group_id), body)

    async def patch(self, actor: Principal, group_id: str, body: Mapping[str, object]) -> Json:
        group = await self._group(group_id)
        return await self._update(actor, group, _patched(await self._resource(group), body))

    async def delete(self, actor: Principal, group_id: str) -> None:
        group = await self._group(group_id)
        members = await self.c.groups.members(group.id)
        removed = await self.c.revoker.revoke_principal("group", group.id, actor=actor, reason="group deleted")
        await self.c.groups.delete(group.id)
        _ = await self.c.audit.record(
            AuditEntry(
                action="scim.groups.delete",
                actor=actor_of(actor),
                resource_kind="group",
                resource_id=group.id,
                resource_display=group.name,
                fields={"group": group.name, "count": str(len(members)), "bindings": str(removed)},
                diff={
                    "title": "Group deleted",
                    "lines": [{"op": "remove", "text": f"{removed} role binding{'s' if removed != 1 else ''}"}],
                    "note": affects(len(members)) + f" of {group.name}.",
                },
                via=VIA,
            )
        )
        await self._finish()

    async def _update(self, actor: Principal, group: Group, body: Mapping[str, object]) -> Json:
        display = get_str(body, "displayName") or group.external_name or group.name
        if display != group.external_name:
            for other in await self.c.groups.list_by_source("scim"):
                if other.id != group.id and (other.external_name or "").lower() == display.lower():
                    raise ScimError(409, f"The group {display} already exists.", "uniqueness")
            group = await self.c.groups.update(
                group.id, name=await self._free_name(display, keep=group), external_name=display
            )
        added, removed = await self._set_members(group, member_ids(body))
        await self._audit(actor, "scim.groups.update", group, added=added, removed=removed)
        await self._finish()
        return await self.get(group.id)

    async def _finish(self) -> None:
        _ = await self._rules.apply()
        await self.c.groups.commit()
        await bump_access_generation(self.c.store)

    async def _set_members(self, group: Group, wanted_ids: Sequence[str]) -> tuple[list[User], list[User]]:
        """Membership becomes exactly the active org members among ``wanted_ids`` (unknown ids are ignored)."""
        members = {member.user_id for member in await self.c.org.members()}
        wanted = {user.id: user for user in await self.c.identity.get_users(wanted_ids) if user.active}
        wanted = {uid: user for uid, user in wanted.items() if uid in members}
        current = {member.user_id for member in await self.c.groups.members(group.id)}
        now = utcnow()
        added = [user for uid, user in wanted.items() if uid not in current]
        for user in added:
            _ = await self.c.groups.add_member(
                GroupMember(group_id=group.id, user_id=user.id, role="member", source="scim", added_at=now)
            )
        gone = [uid for uid in current if uid not in wanted]
        for user_id in gone:
            _ = await self.c.groups.remove_member(group.id, user_id)
        return added, await self.c.identity.get_users(gone)

    async def _free_name(self, display: str, keep: Group | None = None) -> str:
        """The IdP's name, or "<name> (SCIM)" when a group made here already has it."""
        try:
            for candidate in (clean_group_name(display), clean_group_name(f"{display} (SCIM)")):
                other = await self.c.groups.find_by_name(candidate)
                if other is None or (keep is not None and other.id == keep.id):
                    return candidate
        except InvalidGroupError as exc:
            raise ScimError(400, str(exc), "invalidValue") from exc
        raise ScimError(409, f"A group called {display} already exists.", "uniqueness")

    async def _group(self, group_id: str) -> Group:
        group = await self.c.groups.get(group_id)
        if group is None or group.source != "scim":
            raise ScimError(404, f"There is no group {group_id}.")
        return group

    async def _resource(self, group: Group) -> Json:
        base = self.c.policy.scim_base_url
        members = await self.c.groups.members(group.id)
        users = {user.id: user for user in await self.c.identity.get_users([m.user_id for m in members])}
        resource: Json = {
            "schemas": [GROUP_SCHEMA],
            "id": group.id,
            "displayName": group.external_name or group.name,
            "members": [
                {
                    "value": member.user_id,
                    "display": users[member.user_id].display_name if member.user_id in users else member.user_id,
                    "type": "User",
                    "$ref": f"{base}/Users/{member.user_id}",
                }
                for member in members
            ],
            "meta": {
                "resourceType": "Group",
                "created": _iso(group.created_at),
                "lastModified": _iso(group.updated_at),
                "location": f"{base}/Groups/{group.id}",
            },
        }
        if group.external_id and group.external_id != group.id:
            resource["externalId"] = group.external_id
        return resource

    async def _audit(
        self, actor: Principal, action: str, group: Group, *, added: list[User], removed: list[User]
    ) -> None:
        lines = [{"op": "add", "text": user.display_name} for user in added]
        lines += [{"op": "remove", "text": user.display_name} for user in removed]
        count = len(await self.c.groups.members(group.id))
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(actor),
                resource_kind="group",
                resource_id=group.id,
                resource_display=group.name,
                fields={
                    "group": group.name,
                    "count": str(count),
                    "added": str(len(added)),
                    "removed": str(len(removed)),
                },
                diff={"title": "Members", "lines": lines, "note": affects(count) + "."} if lines else None,
                links={"group": f"/access/people?tab=groups&group={group.id}"},
                via=VIA,
            )
        )
