"""SQLAlchemy repositories of the directory module."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_directory.domain.groups import Group, GroupMember, GroupSource, MemberRole, group_key
from agnostic_directory.infrastructure.tables import GroupMemberRow, GroupRow
from agnostic_kernel.db import aware, utcnow


def _group(row: GroupRow, member_count: int = 0) -> Group:
    return Group(
        id=row.id,
        name=row.name,
        description=row.description,
        source=cast("GroupSource", row.source),
        external_id=row.external_id,
        external_name=row.external_name,
        created_at=aware(row.created_at),
        updated_at=aware(row.updated_at),
        member_count=member_count,
    )


def _member(row: GroupMemberRow) -> GroupMember:
    return GroupMember(
        group_id=row.group_id,
        user_id=row.user_id,
        role=cast("MemberRole", row.role),
        source=cast("GroupSource", row.source),
        added_at=aware(row.added_at),
        rule_id=row.rule_id,
    )


class SqlGroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _counts(self) -> dict[str, int]:
        rows = await self._session.execute(
            select(GroupMemberRow.group_id, func.count()).group_by(GroupMemberRow.group_id)
        )
        return {str(group_id): int(count) for group_id, count in rows.all()}

    async def list(self) -> list[Group]:
        counts = await self._counts()
        rows = await self._session.scalars(select(GroupRow).order_by(GroupRow.name))
        return [_group(row, counts.get(row.id, 0)) for row in rows]

    async def get(self, group_id: str) -> Group | None:
        row = await self._session.get(GroupRow, group_id)
        if row is None:
            return None
        count = await self._session.scalar(
            select(func.count()).select_from(GroupMemberRow).where(GroupMemberRow.group_id == group_id)
        )
        return _group(row, count or 0)

    async def find_external(self, source: GroupSource, external_id: str) -> Group | None:
        row = await self._session.scalar(
            select(GroupRow).where(GroupRow.source == source, GroupRow.external_id == external_id)
        )
        return await self.get(row.id) if row else None

    async def find_by_name(self, name: str) -> Group | None:
        row = await self._session.scalar(select(GroupRow).where(GroupRow.name_key == group_key(name)))
        return await self.get(row.id) if row else None

    async def add(self, group: Group) -> None:
        self._session.add(
            GroupRow(
                id=group.id,
                name=group.name,
                name_key=group_key(group.name),
                description=group.description,
                source=group.source,
                external_id=group.external_id,
                external_name=group.external_name,
                created_at=group.created_at,
                updated_at=group.updated_at,
            )
        )
        await self._session.flush()

    async def update(
        self,
        group_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        external_name: str | None = None,
    ) -> Group:
        row = await self._session.get(GroupRow, group_id)
        if row is None:
            raise LookupError(group_id)
        if name is not None:
            row.name = name
            row.name_key = group_key(name)
        if description is not None:
            row.description = description
        if external_name is not None:
            row.external_name = external_name
        row.updated_at = utcnow()
        await self._session.flush()
        group = await self.get(group_id)
        assert group is not None
        return group

    async def delete(self, group_id: str) -> None:
        _ = await self._session.execute(delete(GroupMemberRow).where(GroupMemberRow.group_id == group_id))
        _ = await self._session.execute(delete(GroupRow).where(GroupRow.id == group_id))

    async def members(self, group_id: str) -> list[GroupMember]:
        rows = await self._session.scalars(
            select(GroupMemberRow).where(GroupMemberRow.group_id == group_id).order_by(GroupMemberRow.added_at)
        )
        return [_member(row) for row in rows]

    async def groups_of(self, user_id: str) -> list[Group]:
        rows = await self._session.scalars(
            select(GroupRow)
            .join(GroupMemberRow, GroupMemberRow.group_id == GroupRow.id)
            .where(GroupMemberRow.user_id == user_id)
            .order_by(GroupRow.name)
        )
        return [_group(row) for row in rows]

    async def memberships_of(self, user_ids: Sequence[str]) -> dict[str, list[str]]:
        if not user_ids:
            return {}
        rows = await self._session.execute(
            select(GroupMemberRow.user_id, GroupMemberRow.group_id).where(GroupMemberRow.user_id.in_(user_ids))
        )
        result: dict[str, list[str]] = {user_id: [] for user_id in user_ids}
        for user_id, group_id in rows.all():
            result[user_id].append(group_id)
        return result

    async def add_member(self, member: GroupMember) -> bool:
        row = await self._session.get(GroupMemberRow, (member.group_id, member.user_id))
        if row is not None:
            row.role = member.role
            await self._session.flush()
            return False
        self._session.add(
            GroupMemberRow(
                group_id=member.group_id,
                user_id=member.user_id,
                role=member.role,
                source=member.source,
                rule_id=member.rule_id,
                added_at=member.added_at,
            )
        )
        await self._session.flush()
        return True

    async def list_by_source(self, source: GroupSource) -> list[Group]:
        counts = await self._counts()
        rows = await self._session.scalars(select(GroupRow).where(GroupRow.source == source).order_by(GroupRow.name))
        return [_group(row, counts.get(row.id, 0)) for row in rows]

    async def rule_members(self) -> list[GroupMember]:
        rows = await self._session.scalars(select(GroupMemberRow).where(GroupMemberRow.rule_id.is_not(None)))
        return [_member(row) for row in rows]

    async def add_rule_member(self, member: GroupMember) -> bool:
        if await self._session.get(GroupMemberRow, (member.group_id, member.user_id)) is not None:
            return False
        return await self.add_member(member)

    async def remove_rule_member(self, group_id: str, user_id: str) -> bool:
        result = await self._session.execute(
            delete(GroupMemberRow).where(
                GroupMemberRow.group_id == group_id,
                GroupMemberRow.user_id == user_id,
                GroupMemberRow.rule_id.is_not(None),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def rollback(self) -> None:
        await self._session.rollback()

    async def remove_member(self, group_id: str, user_id: str) -> bool:
        result = await self._session.execute(
            delete(GroupMemberRow).where(GroupMemberRow.group_id == group_id, GroupMemberRow.user_id == user_id)
        )
        return bool(getattr(result, "rowcount", 0))

    async def remove_user(self, user_id: str) -> list[str]:
        left = list(
            await self._session.scalars(select(GroupMemberRow.group_id).where(GroupMemberRow.user_id == user_id))
        )
        _ = await self._session.execute(delete(GroupMemberRow).where(GroupMemberRow.user_id == user_id))
        return left

    async def set_role(self, group_id: str, user_id: str, role: MemberRole) -> None:
        row = await self._session.get(GroupMemberRow, (group_id, user_id))
        if row is not None:
            row.role = role
            await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()
