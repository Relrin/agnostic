"""What every kind of directory sync shares: deprovisioning people the IdP deactivated, and mapping rules.

Deprovisioning (see :class:`~agnostic_directory.domain.sync.SyncSettings` for the two behaviours) ends the
person's sessions, deletes their role bindings, takes them out of every group and bumps the access generation, so
whatever they still hold stops working on their next request.

Mapping rules copy the members of an IdP group (SCIM, claim or Google group) into an existing manual group, so a
team keeps its hand-made group and bindings while the IdP decides who is in it.
"""

from __future__ import annotations

from dataclasses import dataclass

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_directory.application.ports import (
    AccessRevoker,
    DirectoryConfigRepository,
    GoogleDirectory,
    GroupRepository,
    MappingRuleRepository,
    ScimRepository,
)
from agnostic_directory.domain.groups import GroupMember, GroupSource
from agnostic_directory.domain.sync import MappingRule
from agnostic_identity.facade import IdentityFacade, MembershipDirectory, User, UserStatus
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import ConflictError
from agnostic_kernel.logging import get_logger
from agnostic_org.facade import OrgFacade, OrgRole

log = get_logger(__name__)

RULE_SOURCES: tuple[GroupSource, ...] = ("scim", "oidc_claim", "google_directory")


@dataclass(frozen=True, slots=True)
class DirectoryPolicy:
    scim_base_url: str
    """``{public_url}/scim/v2``: what the IdP is configured with."""


@dataclass(frozen=True, slots=True)
class SyncContext:
    groups: GroupRepository
    scim: ScimRepository
    rules: MappingRuleRepository
    config: DirectoryConfigRepository
    identity: IdentityFacade
    org: OrgFacade
    membership: MembershipDirectory
    authorizer: Authorizer
    audit: AuditLog
    store: EphemeralStore
    revoker: AccessRevoker
    policy: DirectoryPolicy
    box: SecretBox
    google: GoogleDirectory


class SeatsFullError(ConflictError):
    code = "seats_full"
    title = "The org has no seats left"


@dataclass(frozen=True, slots=True)
class Deprovisioned:
    bindings: int
    groups: int
    left_org: bool


class Deprovisioner:
    def __init__(self, context: SyncContext) -> None:
        self.c = context

    async def deprovision(self, user: User, *, actor: Principal, leave: bool | None = None) -> Deprovisioned:
        """Joins the caller's transaction. ``leave`` overrides the configured behaviour (a deleted SCIM user)."""
        await self._keep_an_owner(user)
        if leave is None:
            leave = (await self.c.config.settings()).deprovision == "remove"
        if user.status is not UserStatus.DEPROVISIONED:
            _ = await self.c.identity.set_status(user.id, UserStatus.DEPROVISIONED)
        await self.c.identity.revoke_sessions(user.id)
        bindings = await self.c.revoker.revoke_principal("user", user.id, actor=actor, reason="deprovisioned")
        left = await self.c.groups.remove_user(user.id)
        if leave:
            await self.c.org.leave(user.id, actor=actor, reason="deprovisioned")
        await bump_access_generation(self.c.store)
        log.info("directory.deprovisioned", user_id=user.id, bindings=bindings, groups=len(left), left_org=leave)
        return Deprovisioned(bindings=bindings, groups=len(left), left_org=leave)

    async def reactivate(self, user: User, *, via: str) -> None:
        """Make the account active again and (re)admit it to the org; the seat limit still applies."""
        membership = await self.c.membership.membership(user.id)
        if membership is None or not membership.active:
            admission = await self.c.membership.admit(user.email, jit_allowed=True)
            if not admission.allowed:
                raise SeatsFullError("The org has no seats left; free one or raise the seat limit.")
        if user.status is not UserStatus.ACTIVE:
            user = await self.c.identity.set_status(user.id, UserStatus.ACTIVE)
        if membership is None or not membership.active:
            await self.c.membership.join(user, via=via)
        await bump_access_generation(self.c.store)

    async def _keep_an_owner(self, user: User) -> None:
        member = await self.c.org.member(user.id)
        if member is None or member.org_role is not OrgRole.OWNER:
            return
        owners = [m.user_id for m in await self.c.org.members() if m.org_role is OrgRole.OWNER]
        active = [u for u in await self.c.identity.get_users(owners) if u.active and u.id != user.id]
        if not active:
            raise ConflictError(f"{user.display_name} is the only Owner; make someone else Owner first.")

    async def audit(
        self, actor: Principal, action: str, user: User, outcome: Deprovisioned | None, *, via: str
    ) -> None:
        fields = {"person": user.display_name, "email": user.email}
        diff: dict[str, object] | None = None
        if outcome is not None:
            fields |= {"bindings": str(outcome.bindings), "groups": str(outcome.groups)}
            lines = [
                {"op": "remove", "text": "Sessions ended"},
                {"op": "remove", "text": f"{outcome.bindings} role binding{'s' if outcome.bindings != 1 else ''}"},
                {"op": "remove", "text": f"{outcome.groups} group membership{'s' if outcome.groups != 1 else ''}"},
            ]
            if outcome.left_org:
                lines.append({"op": "remove", "text": "Org membership"})
            diff = {"title": "Deprovisioned", "lines": lines, "note": None}
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(actor),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.display_name,
                fields=fields,
                diff=diff,
                links={"person": f"/access/people?person={user.id}"},
                via=via,
            )
        )


class RuleApplier:
    """Make the rule-made memberships of every target group match the members of the IdP groups the rules name."""

    def __init__(self, groups: GroupRepository, rules: MappingRuleRepository) -> None:
        self._groups = groups
        self._rules = rules

    async def apply(self) -> bool:  # noqa: C901
        """Joins the caller's transaction; ``True`` when a membership changed (the caller bumps the generation)."""
        rules = await self._rules.list()
        wanted_sources: set[GroupSource] = {rule.source for rule in rules}
        sources = {source: await self._groups.list_by_source(source) for source in wanted_sources}
        desired: dict[str, dict[str, MappingRule]] = {}
        for rule in rules:
            target = await self._groups.get(rule.group_id)
            if target is None or target.synced:
                continue
            wanted = desired.setdefault(target.id, {})
            for group in sources.get(rule.source, []):
                if not rule.matches(group.source, group.external_id, group.external_name):
                    continue
                for member in await self._groups.members(group.id):
                    _ = wanted.setdefault(member.user_id, rule)
        current: dict[str, set[str]] = {}
        for member in await self._groups.rule_members():
            current.setdefault(member.group_id, set()).add(member.user_id)
        changed = False
        for group_id, user_ids in current.items():
            for user_id in user_ids - set(desired.get(group_id, {})):
                changed |= await self._groups.remove_rule_member(group_id, user_id)
        now = utcnow()
        for group_id, people in desired.items():
            for user_id, rule in people.items():
                if user_id in current.get(group_id, set()):
                    continue
                changed |= await self._groups.add_rule_member(
                    GroupMember(
                        group_id=group_id,
                        user_id=user_id,
                        role="member",
                        source=rule.source,
                        added_at=now,
                        rule_id=rule.id,
                    )
                )
        return changed
