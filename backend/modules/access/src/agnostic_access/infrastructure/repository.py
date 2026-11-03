"""SQLAlchemy repositories of the access module."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_access.domain.requests import AccessRequest, RequestStatus
from agnostic_access.domain.roles import AccessRole, Binding, PrincipalKind, RoleVersion, RunScope
from agnostic_access.domain.scopes import ScopeSpec
from agnostic_access.infrastructure.tables import (
    BindingRow,
    RoleRow,
    RoleVersionRow,
    ScopeCatalogRow,
    TempGrantRequestRow,
)
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


def _fill(row: RoleRow, role: AccessRole) -> None:
    row.kind = role.kind
    row.slug = role.slug
    row.name = role.name
    row.description = role.description
    row.color = role.color
    row.permissions = {resource: list(actions) for resource, actions in role.permissions.items()}
    row.run_scope = {resource: value if value == "all" else list(value) for resource, value in role.run_scope.items()}
    row.bindable_instance_ids = list(role.bindable_instance_ids) if role.bindable_instance_ids is not None else None
    row.version = role.version
    row.updated_at = utcnow()


class SqlRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self) -> list[AccessRole]:
        rows = await self._session.scalars(select(RoleRow).order_by(RoleRow.kind, RoleRow.created_at, RoleRow.name))
        return [_role(row) for row in rows]

    async def get(self, role_id: str) -> AccessRole | None:
        row = await self._session.get(RoleRow, role_id)
        return _role(row) if row else None

    async def slug_taken(self, slug: str, *, except_id: str | None = None) -> bool:
        statement = select(RoleRow.id).where(RoleRow.slug == slug)
        if except_id is not None:
            statement = statement.where(RoleRow.id != except_id)
        return (await self._session.scalar(statement)) is not None

    async def add(self, role: AccessRole) -> None:
        row = RoleRow(id=role.id, created_at=utcnow())
        _fill(row, role)
        self._session.add(row)
        await self._session.flush()

    async def save(self, role: AccessRole) -> None:
        row = await self._session.get(RoleRow, role.id)
        if row is None:
            raise LookupError(role.id)
        _fill(row, role)
        await self._session.flush()

    async def delete(self, role_id: str) -> None:
        _ = await self._session.execute(delete(RoleRow).where(RoleRow.id == role_id))

    async def seed_built_ins(self, roles: Sequence[AccessRole]) -> None:
        for role in roles:
            if await self._session.get(RoleRow, role.id) is None:
                row = RoleRow(id=role.id, created_at=utcnow())
                _fill(row, role)
                self._session.add(row)
        await self._session.commit()

    async def add_version(
        self, role_id: str, version: int, snapshot: Mapping[str, Any], *, changed_by: str, changed_by_name: str
    ) -> None:
        self._session.add(
            RoleVersionRow(
                role_id=role_id,
                version=version,
                snapshot=dict(snapshot),
                changed_by=changed_by,
                changed_by_name=changed_by_name,
                changed_at=utcnow(),
            )
        )
        await self._session.flush()

    async def versions(self, role_id: str) -> list[RoleVersion]:
        rows = await self._session.scalars(
            select(RoleVersionRow).where(RoleVersionRow.role_id == role_id).order_by(RoleVersionRow.version.desc())
        )
        return [
            RoleVersion(
                role_id=row.role_id,
                version=row.version,
                snapshot=row.snapshot,
                changed_by=row.changed_by,
                changed_by_name=row.changed_by_name,
                changed_at=aware(row.changed_at),
            )
            for row in rows
        ]

    async def commit(self) -> None:
        await self._session.commit()


def _binding(row: BindingRow) -> Binding:
    return Binding(
        id=row.id,
        principal_kind=cast("PrincipalKind", row.principal_kind),
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
        return await self.for_principals([("user", user_id)])

    async def for_principals(self, principals: Iterable[tuple[PrincipalKind, str]]) -> list[Binding]:
        conditions = [
            and_(BindingRow.principal_kind == kind, BindingRow.principal_id == principal_id)
            for kind, principal_id in principals
        ]
        if not conditions:
            return []
        rows = await self._session.scalars(select(BindingRow).where(or_(*conditions)).order_by(BindingRow.created_at))
        return [_binding(row) for row in rows]

    async def list(
        self,
        *,
        principal_id: str | None = None,
        instance_id: str | None = None,
        principal_kind: PrincipalKind | None = None,
        role_id: str | None = None,
    ) -> list[Binding]:
        statement = select(BindingRow).order_by(BindingRow.created_at)
        if principal_id is not None:
            statement = statement.where(BindingRow.principal_id == principal_id)
        if principal_kind is not None:
            statement = statement.where(BindingRow.principal_kind == principal_kind)
        if role_id is not None:
            statement = statement.where(BindingRow.role_id == role_id)
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

    async def expired(self, now: datetime) -> list[Binding]:
        rows = await self._session.scalars(
            select(BindingRow).where(BindingRow.expires_at.is_not(None), BindingRow.expires_at <= now)
        )
        return [_binding(row) for row in rows]

    async def commit(self) -> None:
        await self._session.commit()


def _request(row: TempGrantRequestRow) -> AccessRequest:
    return AccessRequest(
        id=row.id,
        requester_id=row.requester_id,
        instance_id=row.instance_id,
        role_id=row.role_id,
        scopes=tuple(row.scopes),
        reason=row.reason,
        duration_hours=row.duration_hours,
        status=cast("RequestStatus", row.status),
        created_at=aware(row.created_at),
        decided_by=row.decided_by,
        decided_at=aware_or_none(row.decided_at),
        note=row.note,
        binding_id=row.binding_id,
        expires_at=aware_or_none(row.expires_at),
    )


class SqlRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: AccessRequest) -> None:
        row = TempGrantRequestRow(id=request.id, created_at=request.created_at)
        self._fill(row, request)
        self._session.add(row)
        await self._session.flush()

    async def get(self, request_id: str) -> AccessRequest | None:
        row = await self._session.get(TempGrantRequestRow, request_id)
        return _request(row) if row else None

    async def list(
        self, *, status: RequestStatus | None = None, requester_id: str | None = None, limit: int = 200
    ) -> list[AccessRequest]:
        statement = select(TempGrantRequestRow).order_by(TempGrantRequestRow.created_at.desc()).limit(limit)
        if status is not None:
            statement = statement.where(TempGrantRequestRow.status == status)
        if requester_id is not None:
            statement = statement.where(TempGrantRequestRow.requester_id == requester_id)
        return [_request(row) for row in await self._session.scalars(statement)]

    async def save(self, request: AccessRequest) -> None:
        row = await self._session.get(TempGrantRequestRow, request.id)
        if row is None:
            raise LookupError(request.id)
        self._fill(row, request)
        await self._session.flush()

    async def by_binding(self, binding_ids: Sequence[str]) -> list[AccessRequest]:
        if not binding_ids:
            return []
        rows = await self._session.scalars(
            select(TempGrantRequestRow).where(TempGrantRequestRow.binding_id.in_(binding_ids))
        )
        return [_request(row) for row in rows]

    @staticmethod
    def _fill(row: TempGrantRequestRow, request: AccessRequest) -> None:
        row.requester_id = request.requester_id
        row.instance_id = request.instance_id
        row.role_id = request.role_id
        row.scopes = list(request.scopes)
        row.reason = request.reason
        row.duration_hours = request.duration_hours
        row.status = request.status
        row.decided_by = request.decided_by
        row.decided_at = request.decided_at
        row.note = request.note
        row.binding_id = request.binding_id
        row.expires_at = request.expires_at


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
