"""The only import surface other modules may use: who is in which group, and the port access implements."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from agnostic_directory.application.ports import AccessRevoker, GroupRepository
from agnostic_directory.domain.groups import GroupMember, GroupSource
from agnostic_kernel.db import utcnow

__all__ = ["AccessRevoker", "DirectoryFacade", "DirectoryFacadeImpl", "GroupRef"]


@dataclass(frozen=True, slots=True)
class GroupRef:
    id: str
    name: str
    source: GroupSource


class DirectoryFacade(Protocol):
    async def groups_of(self, user_id: str) -> list[GroupRef]: ...
    async def memberships(self, user_ids: Sequence[str]) -> dict[str, list[GroupRef]]:
        """User id → the groups they are in, for many people at once."""
        ...

    async def group(self, group_id: str) -> GroupRef | None: ...
    async def groups(self) -> list[GroupRef]: ...
    async def members_of(self, group_id: str) -> list[str]: ...
    async def owners_of(self, group_id: str) -> list[str]: ...
    async def add_to_groups(self, user_id: str, group_ids: Sequence[str]) -> list[str]:
        """Add someone to manual groups (invitations, bulk actions); the caller commits. Returns the ids added."""
        ...


class DirectoryFacadeImpl:
    def __init__(self, groups: GroupRepository) -> None:
        self._groups = groups

    async def groups_of(self, user_id: str) -> list[GroupRef]:
        return [GroupRef(group.id, group.name, group.source) for group in await self._groups.groups_of(user_id)]

    async def memberships(self, user_ids: Sequence[str]) -> dict[str, list[GroupRef]]:
        refs = {group.id: GroupRef(group.id, group.name, group.source) for group in await self._groups.list()}
        return {
            user_id: [refs[group_id] for group_id in group_ids if group_id in refs]
            for user_id, group_ids in (await self._groups.memberships_of(user_ids)).items()
        }

    async def group(self, group_id: str) -> GroupRef | None:
        group = await self._groups.get(group_id)
        return GroupRef(group.id, group.name, group.source) if group else None

    async def groups(self) -> list[GroupRef]:
        return [GroupRef(group.id, group.name, group.source) for group in await self._groups.list()]

    async def members_of(self, group_id: str) -> list[str]:
        return [member.user_id for member in await self._groups.members(group_id)]

    async def owners_of(self, group_id: str) -> list[str]:
        return [member.user_id for member in await self._groups.members(group_id) if member.role == "owner"]

    async def add_to_groups(self, user_id: str, group_ids: Sequence[str]) -> list[str]:
        added: list[str] = []
        for group_id in dict.fromkeys(group_ids):
            group = await self._groups.get(group_id)
            if group is None or group.synced:
                continue
            if await self._groups.add_member(
                GroupMember(group_id=group_id, user_id=user_id, role="member", source="manual", added_at=utcnow())
            ):
                added.append(group_id)
        return added
