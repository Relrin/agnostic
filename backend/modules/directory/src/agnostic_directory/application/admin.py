"""Org settings > Directory sync: SCIM tokens and status, mapping rules, deprovisioning behaviour.

There is at most one active SCIM token. Rotating it issues a new one and keeps the old one working for 24 hours
(or until it is revoked), so the IdP can be switched over without failed pushes; rotating again during that window
revokes the oldest one at once. Tokens are stored hashed and shown only when created.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from agnostic_audit.facade import AuditEntry, actor_of
from agnostic_directory.application.groups import READ, WRITE
from agnostic_directory.application.sync import RULE_SOURCES, RuleApplier, SyncContext
from agnostic_directory.domain.sync import (
    ROTATION_GRACE,
    RULE_ID_PREFIX,
    SCIM_TOKEN_DISPLAY_PREFIX,
    SCIM_TOKEN_ID_PREFIX,
    SCIM_TOKEN_PREFIX,
    DeprovisionBehaviour,
    InvalidSyncConfigError,
    MappingRule,
    RuleSource,
    ScimToken,
    SyncSettings,
    SyncState,
    clean_label,
)
from agnostic_kernel.auth import Principal
from agnostic_kernel.crypto import hash_token, new_token
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import bump_access_generation
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id

SCIM_LINK = "/settings/directory"


@dataclass(frozen=True, slots=True)
class ScimStatus:
    endpoint_url: str
    state: SyncState
    tokens: list[ScimToken]
    """Tokens that still work (the active one and one in rotation), newest first."""


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: ScimToken
    secret: str


class ScimAdmin:
    def __init__(self, context: SyncContext) -> None:
        self.c = context

    async def status(self, principal: Principal) -> ScimStatus:
        _ = await self.c.authorizer.require(principal, READ)
        now = utcnow()
        tokens = [token for token in await self.c.scim.tokens() if token.usable(now)]
        return ScimStatus(endpoint_url=self.c.policy.scim_base_url, state=await self.c.scim.state(), tokens=tokens)

    async def create_token(self, principal: Principal, label: str) -> IssuedToken:
        _ = await self.c.authorizer.require(principal, WRITE)
        now = utcnow()
        if any(token.state(now) == "active" for token in await self.c.scim.tokens()):
            raise ConflictError("There already is a SCIM token; rotate it to get a new one.")
        issued = await self._issue(principal, self._label(label), rotated_from=None)
        await self._audit(principal, "directory.scim.token.create", issued.token)
        await self.c.scim.commit()
        return issued

    async def rotate(self, principal: Principal, token_id: str) -> IssuedToken:
        _ = await self.c.authorizer.require(principal, WRITE)
        now = utcnow()
        tokens = await self.c.scim.tokens()
        old = next((token for token in tokens if token.id == token_id), None)
        if old is None or not old.usable(now):
            raise NotFoundError(f"There is no working SCIM token {token_id}.")
        if old.state(now) != "active":
            raise ConflictError("This token is already being rotated; rotate the new one or revoke this one.")
        for token in tokens:
            if token.state(now) == "rotating":
                await self.c.scim.update_token(token.id, revoked_at=now)
        await self.c.scim.update_token(old.id, expires_at=now + ROTATION_GRACE)
        issued = await self._issue(principal, old.label, rotated_from=old.id)
        await self._audit(principal, "directory.scim.token.rotate", issued.token)
        await self.c.scim.commit()
        return issued

    async def revoke(self, principal: Principal, token_id: str) -> None:
        _ = await self.c.authorizer.require(principal, WRITE)
        token = await self.c.scim.token(token_id)
        if token is None or token.revoked_at is not None:
            raise NotFoundError(f"There is no SCIM token {token_id}.")
        await self.c.scim.update_token(token.id, revoked_at=utcnow())
        await self._audit(principal, "directory.scim.token.revoke", token)
        await self.c.scim.commit()

    async def _issue(self, principal: Principal, label: str, *, rotated_from: str | None) -> IssuedToken:
        secret = f"{SCIM_TOKEN_PREFIX}{new_token(32)}"
        token = ScimToken(
            id=new_id(SCIM_TOKEN_ID_PREFIX),
            label=label,
            prefix=secret[:SCIM_TOKEN_DISPLAY_PREFIX],
            token_hash=hash_token(secret),
            created_by=principal.id,
            created_at=utcnow(),
            last_used_at=None,
            expires_at=None,
            revoked_at=None,
            rotated_from=rotated_from,
        )
        await self.c.scim.add_token(token)
        return IssuedToken(token=token, secret=secret)

    @staticmethod
    def _label(label: str) -> str:
        try:
            return clean_label(label)
        except InvalidSyncConfigError as exc:
            raise ValidationFailedError(str(exc)) from exc

    async def _audit(self, principal: Principal, action: str, token: ScimToken) -> None:
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="scim_token",
                resource_id=token.id,
                resource_display=token.label,
                fields={"label": token.label, "prefix": token.prefix},
                links={"settings": SCIM_LINK},
            )
        )


@dataclass(frozen=True, slots=True)
class RuleView:
    rule: MappingRule
    group_name: str


class MappingRules:
    def __init__(self, context: SyncContext, applier: RuleApplier) -> None:
        self.c = context
        self._applier = applier

    async def list(self, principal: Principal) -> list[RuleView]:
        _ = await self.c.authorizer.require(principal, READ)
        names = {group.id: group.name for group in await self.c.groups.list()}
        return [RuleView(rule, names.get(rule.group_id, rule.group_id)) for rule in await self.c.rules.list()]

    async def create(
        self, principal: Principal, *, source: RuleSource, idp_group: str, group_id: str, provider_id: str | None
    ) -> RuleView:
        _ = await self.c.authorizer.require(principal, WRITE)
        if source not in RULE_SOURCES:
            raise ValidationFailedError(f"Unknown source {source!r}.")
        idp_group = idp_group.strip()
        if not idp_group:
            raise ValidationFailedError("Name the IdP group (its name or id).")
        if provider_id is not None and source != "oidc_claim":
            raise ValidationFailedError("Only claim rules name a sign-in provider.")
        group = await self.c.groups.get(group_id)
        if group is None:
            raise ValidationFailedError(f"There is no group {group_id}.")
        if group.synced:
            raise ValidationFailedError(f"{group.name} is synced from the IdP; map into a manual group.")
        for rule in await self.c.rules.list():
            if (rule.source, rule.provider_id, rule.idp_group.lower(), rule.group_id) == (
                source,
                provider_id,
                idp_group.lower(),
                group_id,
            ):
                raise ConflictError(f"{idp_group} is already mapped to {group.name}.")
        rule = MappingRule(
            id=new_id(RULE_ID_PREFIX),
            source=source,
            provider_id=provider_id,
            idp_group=idp_group,
            group_id=group.id,
            created_by=principal.id,
            created_at=utcnow(),
        )
        await self.c.rules.add(rule)
        await self._audit(principal, "directory.mapping.create", rule, group.name)
        await self._apply()
        return RuleView(rule, group.name)

    async def delete(self, principal: Principal, rule_id: str) -> None:
        _ = await self.c.authorizer.require(principal, WRITE)
        rule = await self.c.rules.get(rule_id)
        if rule is None:
            raise NotFoundError(f"There is no mapping rule {rule_id}.")
        group = await self.c.groups.get(rule.group_id)
        await self.c.rules.delete(rule.id)
        await self._audit(principal, "directory.mapping.delete", rule, group.name if group else rule.group_id)
        await self._apply()

    async def _apply(self) -> None:
        changed = await self._applier.apply()
        await self.c.groups.commit()
        if changed:
            await bump_access_generation(self.c.store)

    async def _audit(self, principal: Principal, action: str, rule: MappingRule, group_name: str) -> None:
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="mapping_rule",
                resource_id=rule.id,
                resource_display=f"{rule.idp_group} → {group_name}",
                fields={"idp_group": rule.idp_group, "group": group_name, "source": rule.source},
                links={"group": f"/access/people?tab=groups&group={rule.group_id}", "settings": SCIM_LINK},
            )
        )


class DirectorySettingsAdmin:
    def __init__(self, context: SyncContext) -> None:
        self.c = context

    async def get(self, principal: Principal) -> SyncSettings:
        _ = await self.c.authorizer.require(principal, READ)
        return await self.c.config.settings()

    async def update(self, principal: Principal, *, deprovision: DeprovisionBehaviour) -> SyncSettings:
        _ = await self.c.authorizer.require(principal, WRITE)
        current = await self.c.config.settings()
        if current.deprovision == deprovision:
            return current
        updated = replace(current, deprovision=deprovision)
        await self.c.config.save_settings(updated)
        _ = await self.c.audit.record(
            AuditEntry(
                action="directory.settings.update",
                actor=actor_of(principal),
                resource_kind="directory_settings",
                resource_id="directory",
                resource_display="Directory sync",
                fields={"change": f"deprovisioning: {deprovision}"},
                diff={
                    "title": "Deprovisioning",
                    "lines": [
                        {"op": "remove", "text": current.deprovision},
                        {"op": "add", "text": deprovision},
                    ],
                    "note": None,
                },
                links={"settings": SCIM_LINK},
            )
        )
        await self.c.config.commit()
        return updated
