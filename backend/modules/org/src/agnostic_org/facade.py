"""The only import surface other modules may use.

Org roles and membership, plus the bindings port that the access module implements.
"""

from __future__ import annotations

from typing import Protocol

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_kernel.auth import Principal
from agnostic_org.application.ports import GroupDirectory, InitialBindingsApplier, MemberRepository
from agnostic_org.domain.org import InitialBinding, Member, OrgRole

__all__ = [
    "GroupDirectory",
    "InitialBinding",
    "InitialBindingsApplier",
    "Member",
    "OrgFacade",
    "OrgFacadeImpl",
    "OrgRole",
]


class OrgFacade(Protocol):
    async def member(self, user_id: str) -> Member | None: ...
    async def members(self) -> list[Member]: ...
    async def leave(self, user_id: str, *, actor: Principal, reason: str) -> None:
        """Remove someone from the org (deprovisioning); audited, the caller commits and revokes sessions."""
        ...


class OrgFacadeImpl:
    def __init__(self, members: MemberRepository, audit: AuditLog) -> None:
        self._members = members
        self._audit = audit

    async def member(self, user_id: str) -> Member | None:
        member = await self._members.get(user_id)
        return member if member is not None and member.active else None

    async def members(self) -> list[Member]:
        return await self._members.list()

    async def leave(self, user_id: str, *, actor: Principal, reason: str) -> None:
        member = await self._members.get(user_id)
        if member is None or not member.active:
            return
        await self._members.remove(user_id)
        _ = await self._audit.record(
            AuditEntry(
                action="members.remove",
                actor=actor_of(actor),
                resource_kind="member",
                resource_id=user_id,
                resource_display=user_id,
                fields={"person": user_id, "reason": reason},
            )
        )
