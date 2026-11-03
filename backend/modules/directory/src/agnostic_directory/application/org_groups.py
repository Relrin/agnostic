"""Org's ``GroupDirectory``: groups on the members table, groups an invitation adds people to, bulk "add to group"."""

from __future__ import annotations

from collections.abc import Sequence

from agnostic_directory.application.ports import GroupRepository
from agnostic_directory.domain.groups import GroupMember
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ValidationFailedError


class OrgGroups:
    def __init__(self, groups: GroupRepository) -> None:
        self._groups = groups

    async def validate(self, group_ids: Sequence[str]) -> None:
        for group_id in dict.fromkeys(group_ids):
            group = await self._groups.get(group_id)
            if group is None:
                raise ValidationFailedError(f"There is no group {group_id!r}.")
            if group.synced:
                raise ValidationFailedError(f"{group.name} is synced from the IdP; people are added there.")

    async def add(self, user_id: str, group_ids: Sequence[str]) -> list[str]:
        added: list[str] = []
        for group_id in dict.fromkeys(group_ids):
            group = await self._groups.get(group_id)
            if group is None or group.synced:
                continue
            member = GroupMember(group_id=group_id, user_id=user_id, role="member", source="manual", added_at=utcnow())
            if await self._groups.add_member(member):
                added.append(group_id)
        return added

    async def memberships(self, user_ids: Sequence[str]) -> dict[str, list[tuple[str, str]]]:
        names = {group.id: group.name for group in await self._groups.list()}
        return {
            user_id: [(group_id, names[group_id]) for group_id in group_ids if group_id in names]
            for user_id, group_ids in (await self._groups.memberships_of(user_ids)).items()
        }
