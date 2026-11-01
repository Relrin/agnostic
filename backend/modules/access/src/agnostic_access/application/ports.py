"""Ports of the access module."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from agnostic_access.domain.roles import AccessRole, Binding
from agnostic_access.domain.scopes import ScopeSpec


class RoleRepository(Protocol):
    async def custom(self) -> list[AccessRole]:
        """Custom roles (Phase 6); built-in roles come from code."""
        ...

    async def sync_built_ins(self, roles: Sequence[AccessRole]) -> None: ...


class BindingRepository(Protocol):
    async def for_user(self, user_id: str) -> list[Binding]: ...
    async def list(self, *, principal_id: str | None = None, instance_id: str | None = None) -> list[Binding]: ...
    async def get(self, binding_id: str) -> Binding | None: ...
    async def add(self, binding: Binding) -> None: ...
    async def delete(self, binding_id: str) -> None: ...
    async def commit(self) -> None: ...


class CatalogRepository(Protocol):
    async def sync(self, specs: Sequence[ScopeSpec]) -> None: ...
