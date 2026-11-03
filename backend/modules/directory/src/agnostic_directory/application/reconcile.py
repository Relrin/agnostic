"""The periodic safety net behind the push-based syncs.

Takes deprovisioned (or deleted) accounts out of every group they are still in, re-applies the mapping rules and
refreshes the counts on the SCIM status pill. Normally there is nothing to do: SCIM and Google sync already do all
of this as they go; this catches whatever a failed request or a hand edit left behind.
"""

from __future__ import annotations

from dataclasses import dataclass

from agnostic_directory.application.sync import RuleApplier, SyncContext
from agnostic_identity.facade import UserStatus
from agnostic_kernel.ephemeral import bump_access_generation
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Reconciled:
    removed_memberships: int
    rules_changed: bool
    counts: dict[str, int]


class Reconcile:
    def __init__(self, context: SyncContext, rules: RuleApplier) -> None:
        self.c = context
        self._rules = rules

    async def __call__(self) -> Reconciled:
        members: dict[str, list[str]] = {}
        for group in await self.c.groups.list():
            for member in await self.c.groups.members(group.id):
                members.setdefault(member.user_id, []).append(group.id)
        users = {user.id: user for user in await self.c.identity.get_users(list(members))}
        removed = 0
        for user_id, group_ids in members.items():
            user = users.get(user_id)
            if user is not None and user.status is not UserStatus.DEPROVISIONED:
                continue
            for group_id in group_ids:
                removed += await self.c.groups.remove_member(group_id, user_id)
        changed = await self._rules.apply()
        counts = await self.c.scim.counts()
        await self.c.scim.save_counts(counts)
        await self.c.groups.commit()
        if removed or changed:
            await bump_access_generation(self.c.store)
        log.info("directory.reconciled", removed_memberships=removed, rules_changed=changed)
        return Reconciled(removed_memberships=removed, rules_changed=changed, counts=counts)
