"""Groups asserted at sign-in (OIDC ``groups`` claim, SAML attribute): Keycloak and any IdP without SCIM.

Each claimed group name becomes (or matches) an ``oidc_claim`` group keyed by provider and name; the person's
memberships among that provider's claim groups are replaced by what the IdP said this time. Mapping rules then
carry those memberships into the manual groups they name.
"""

from __future__ import annotations

from collections.abc import Sequence

from agnostic_directory.application.ports import GroupRepository
from agnostic_directory.application.sync import RuleApplier
from agnostic_directory.domain.groups import GROUP_ID_PREFIX, Group, GroupMember, clean_group_name
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.ids import new_id

MAX_CLAIMED_GROUPS = 200


def claim_external_id(provider_id: str, name: str) -> str:
    return f"{provider_id}:{name}"


class ClaimGroups:
    """Identity's ``ExternalGroupsSync``."""

    def __init__(self, groups: GroupRepository, store: EphemeralStore, rules: RuleApplier) -> None:
        self._groups = groups
        self._store = store
        self._rules = rules

    async def sync(self, user_id: str, *, provider_id: str, groups: Sequence[str]) -> None:
        names = list(dict.fromkeys(name.strip().lstrip("/") for name in groups if name.strip()))[:MAX_CLAIMED_GROUPS]
        wanted: set[str] = set()
        for name in names:
            group = await self._group_for(provider_id, name)
            wanted.add(group.id)
        current = {
            group.id: group
            for group in await self._groups.groups_of(user_id)
            if group.source == "oidc_claim" and (group.external_id or "").startswith(f"{provider_id}:")
        }
        changed = False
        for group_id in wanted - set(current):
            changed |= await self._groups.add_member(
                GroupMember(group_id=group_id, user_id=user_id, role="member", source="oidc_claim", added_at=utcnow())
            )
        for group_id in set(current) - wanted:
            changed |= await self._groups.remove_member(group_id, user_id)
        if changed:
            _ = await self._rules.apply()
            await bump_access_generation(self._store)

    async def _group_for(self, provider_id: str, name: str) -> Group:
        external_id = claim_external_id(provider_id, name)
        existing = await self._groups.find_external("oidc_claim", external_id)
        if existing is not None:
            return existing
        display = clean_group_name(name.rsplit("/", 1)[-1] or name)
        if await self._groups.find_by_name(display) is not None:
            display = clean_group_name(f"{display} ({provider_id})")
        now = utcnow()
        group = Group(
            id=new_id(GROUP_ID_PREFIX),
            name=display,
            description="",
            source="oidc_claim",
            external_id=external_id,
            external_name=name,
            created_at=now,
            updated_at=now,
        )
        await self._groups.add(group)
        return group
