"""SQLAlchemy repositories of the access module."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_access.domain.roles import AccessRole, Binding, RunScope
from agnostic_access.domain.scopes import ScopeSpec
from agnostic_access.infrastructure.tables import BindingRow, RoleRow, ScopeCatalogRow
from agnostic_kernel.db import aware, aware_or_none, utcnow


def _role(row: RoleRow) -> AccessRole:
    run_scope: dict[str, RunScope] = {
        resource: "all" if value == "all" else tuple(cast("list[str]", value))
        for resource, value in row.run_scope.items()
    }
    return AccessRole(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        color=row.color,
        kind=cast("Literal['built_in', 'custom']", row.kind),
        permissions={resource: tuple(actions) for resource, actions in row.permissions.items()},
        run_scope=run_scope,
        bindable_instance_ids=tuple(row.bindable_instance_ids) if row.bindable_instance_ids is not None else None,
        version=row.version,
    )


class SqlRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def custom(self) -> list[AccessRole]:
        rows = await self._session.scalars(select(RoleRow).where(RoleRow.kind == "custom").order_by(RoleRow.name))
        return [_role(row) for row in rows]

    async def sync_built_ins(self, roles: Sequence[AccessRole]) -> None:
        for role in roles:
            row = await self._session.get(RoleRow, role.id)
            if row is None:
                row = RoleRow(id=role.id, kind="built_in", created_at=utcnow(), version=1)
                self._session.add(row)
            row.slug = role.slug
            row.name = role.name
            row.description = role.description
            row.color = role.color
            row.permissions = {resource: list(actions) for resource, actions in role.permissions.items()}
            row.run_scope = {
                resource: value if value == "all" else list(value) for resource, value in role.run_scope.items()
            }
            row.bindable_instance_ids = list(role.bindable_instance_ids) if role.bindable_instance_ids else None
            row.updated_at = utcnow()
        await self._session.commit()


def _binding(row: BindingRow) -> Binding:
    return Binding(
        id=row.id,
        principal_kind=cast("Literal['user', 'group', 'service_account']", row.principal_kind),
        principal_id=row.principal_id,
        instance_id=row.instance_id,
        role_id=row.role_id,
        scopes=tuple(row.scopes),
        expires_at=aware_or_none(row.expires_at),
        reason=row.reason,
        created_by=row.created_by,
        created_at=aware(row.created_at),
    )


class SqlBindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_user(self, user_id: str) -> list[Binding]:
        rows = await self._session.scalars(
            select(BindingRow).where(BindingRow.principal_kind == "user", BindingRow.principal_id == user_id)
        )
        return [_binding(row) for row in rows]

    async def list(self, *, principal_id: str | None = None, instance_id: str | None = None) -> list[Binding]:
        statement = select(BindingRow).order_by(BindingRow.created_at)
        if principal_id is not None:
            statement = statement.where(BindingRow.principal_id == principal_id)
        if instance_id is not None:
            statement = statement.where((BindingRow.instance_id == instance_id) | BindingRow.instance_id.is_(None))
        return [_binding(row) for row in await self._session.scalars(statement)]

    async def get(self, binding_id: str) -> Binding | None:
        row = await self._session.get(BindingRow, binding_id)
        return _binding(row) if row else None

    async def add(self, binding: Binding) -> None:
        self._session.add(
            BindingRow(
                id=binding.id,
                principal_kind=binding.principal_kind,
                principal_id=binding.principal_id,
                instance_id=binding.instance_id,
                role_id=binding.role_id,
                scopes=list(binding.scopes),
                expires_at=binding.expires_at,
                reason=binding.reason,
                created_by=binding.created_by,
                created_at=binding.created_at,
            )
        )
        await self._session.flush()

    async def delete(self, binding_id: str) -> None:
        _ = await self._session.execute(delete(BindingRow).where(BindingRow.id == binding_id))

    async def commit(self) -> None:
        await self._session.commit()


class SqlCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sync(self, specs: Sequence[ScopeSpec]) -> None:
        existing = {row.scope: row for row in await self._session.scalars(select(ScopeCatalogRow))}
        for spec in specs:
            row = existing.pop(spec.scope, None)
            if row is None:
                row = ScopeCatalogRow(scope=spec.scope)
                self._session.add(row)
            row.family = spec.family
            row.action = spec.action
            row.resource_kind = spec.resource_kind
            row.source = spec.source
            row.agentos_min_version = spec.agentos_min_version
            row.description = spec.description
            row.privileged = spec.privileged
            row.hidden = spec.hidden
        for stale in existing.values():
            await self._session.delete(stale)
        await self._session.commit()
