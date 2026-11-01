"""The only import surface other modules may use.

Org roles and membership, plus the bindings port that the access module implements.
"""

from __future__ import annotations

from typing import Protocol

from agnostic_org.application.ports import InitialBindingsApplier, MemberRepository
from agnostic_org.domain.org import InitialBinding, Member, OrgRole

__all__ = ["InitialBinding", "InitialBindingsApplier", "Member", "OrgFacade", "OrgFacadeImpl", "OrgRole"]


class OrgFacade(Protocol):
    async def member(self, user_id: str) -> Member | None: ...
    async def members(self) -> list[Member]: ...


class OrgFacadeImpl:
    def __init__(self, members: MemberRepository) -> None:
        self._members = members

    async def member(self, user_id: str) -> Member | None:
        member = await self._members.get(user_id)
        return member if member is not None and member.active else None

    async def members(self) -> list[Member]:
        return await self._members.list()
