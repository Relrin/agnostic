"""SQLAlchemy repositories of the org module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.db import aware, aware_or_none, utcnow
from agnostic_kernel.errors import NotFoundError
from agnostic_org.domain.org import (
    InitialBinding,
    Invitation,
    InvitationStatus,
    Member,
    MemberStatus,
    OrgProfile,
    OrgRole,
)
from agnostic_org.infrastructure.tables import PROFILE_ID, InvitationRow, MemberRow, OrgProfileRow


class SqlOrgRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _row(self) -> OrgProfileRow | None:
        return await self._session.get(OrgProfileRow, PROFILE_ID)

    async def get(self) -> OrgProfile | None:
        row = await self._row()
        if row is None:
            return None
        return OrgProfile(
            name=row.name,
            slug=row.slug,
            logo_url=row.logo_url,
            plan_label=row.plan_label,
            seat_limit=row.seat_limit,
            updated_at=aware(row.updated_at),
        )

    async def save(self, profile: OrgProfile) -> None:
        row = await self._row()
        if row is None:
            row = OrgProfileRow(id=PROFILE_ID, created_at=utcnow())
            self._session.add(row)
        row.name = profile.name
        row.slug = profile.slug
        row.logo_url = profile.logo_url
        row.plan_label = profile.plan_label
        row.seat_limit = profile.seat_limit
        row.updated_at = profile.updated_at
        await self._session.flush()

    async def set_bootstrap_token(self, token_hash: str | None, expires_at: datetime | None) -> None:
        row = await self._row()
        if row is not None:
            row.bootstrap_token_hash = token_hash
            row.bootstrap_expires_at = expires_at
            await self._session.flush()

    async def bootstrap_token(self) -> tuple[str, datetime] | None:
        row = await self._row()
        if row is None or row.bootstrap_token_hash is None or row.bootstrap_expires_at is None:
            return None
        return row.bootstrap_token_hash, aware(row.bootstrap_expires_at)

    async def commit(self) -> None:
        await self._session.commit()


def _member(row: MemberRow) -> Member:
    return Member(
        user_id=row.user_id,
        org_role=OrgRole(row.org_role),
        status=MemberStatus(row.status),
        joined_at=aware(row.joined_at),
        joined_via=row.joined_via,
    )


class SqlMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: str) -> Member | None:
        row = await self._session.get(MemberRow, user_id)
        return _member(row) if row else None

    async def list(self, *, include_removed: bool = False) -> list[Member]:
        statement = select(MemberRow)
        if not include_removed:
            statement = statement.where(MemberRow.status == MemberStatus.ACTIVE.value)
        return [_member(row) for row in await self._session.scalars(statement)]

    async def upsert(self, user_id: str, org_role: OrgRole, *, joined_via: str) -> Member:
        now = utcnow()
        row = await self._session.get(MemberRow, user_id)
        if row is None:
            row = MemberRow(user_id=user_id, joined_at=now)
            self._session.add(row)
        elif row.status != MemberStatus.ACTIVE.value:
            row.joined_at = now
        row.org_role = org_role.value
        row.status = MemberStatus.ACTIVE.value
        row.joined_via = joined_via
        row.updated_at = now
        await self._session.flush()
        return _member(row)

    async def set_role(self, user_id: str, org_role: OrgRole) -> Member:
        row = await self._session.get(MemberRow, user_id)
        if row is None:
            raise NotFoundError(f"{user_id} isn't a member.")
        row.org_role = org_role.value
        row.updated_at = utcnow()
        await self._session.flush()
        return _member(row)

    async def remove(self, user_id: str) -> None:
        row = await self._session.get(MemberRow, user_id)
        if row is not None:
            row.status = MemberStatus.REMOVED.value
            row.updated_at = utcnow()
            await self._session.flush()

    async def count_active(self, role: OrgRole | None = None) -> int:
        statement = select(func.count()).select_from(MemberRow).where(MemberRow.status == MemberStatus.ACTIVE.value)
        if role is not None:
            statement = statement.where(MemberRow.org_role == role.value)
        return int(await self._session.scalar(statement) or 0)


def _invitation(row: InvitationRow) -> Invitation:
    return Invitation(
        id=row.id,
        email=row.email,
        org_role=OrgRole(row.org_role),
        bindings=tuple(
            InitialBinding(role_id=str(item["role_id"]), instance_id=item.get("instance_id")) for item in row.bindings
        ),
        access_ends_at=aware_or_none(row.access_ends_at),
        invited_by=row.invited_by,
        expires_at=aware(row.expires_at),
        status=InvitationStatus(row.status),
        created_at=aware(row.created_at),
    )


class SqlInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, invitation: Invitation, token_hash: str) -> None:
        self._session.add(
            InvitationRow(
                id=invitation.id,
                email=invitation.email,
                org_role=invitation.org_role.value,
                bindings=[{"role_id": b.role_id, "instance_id": b.instance_id} for b in invitation.bindings],
                access_ends_at=invitation.access_ends_at,
                invited_by=invitation.invited_by,
                token_hash=token_hash,
                expires_at=invitation.expires_at,
                status=invitation.status.value,
                created_at=invitation.created_at,
                updated_at=invitation.created_at,
            )
        )
        await self._session.flush()

    async def get(self, invitation_id: str) -> Invitation | None:
        row = await self._session.get(InvitationRow, invitation_id)
        return _invitation(row) if row else None

    async def by_token(self, token_hash: str) -> Invitation | None:
        row = await self._session.scalar(select(InvitationRow).where(InvitationRow.token_hash == token_hash))
        return _invitation(row) if row else None

    async def pending_for(self, email: str) -> Invitation | None:
        row = await self._session.scalar(
            select(InvitationRow)
            .where(InvitationRow.email == email, InvitationRow.status == InvitationStatus.PENDING.value)
            .order_by(InvitationRow.created_at.desc())
        )
        return _invitation(row) if row else None

    async def list_pending(self) -> list[Invitation]:
        rows = await self._session.scalars(
            select(InvitationRow)
            .where(InvitationRow.status == InvitationStatus.PENDING.value)
            .order_by(InvitationRow.created_at.desc())
        )
        return [_invitation(row) for row in rows]

    async def set_status(self, invitation_id: str, status: InvitationStatus) -> None:
        row = await self._session.get(InvitationRow, invitation_id)
        if row is not None:
            row.status = status.value
            row.updated_at = utcnow()
            await self._session.flush()

    async def renew(self, invitation_id: str, token_hash: str, expires_at: datetime) -> Invitation:
        row = await self._session.get(InvitationRow, invitation_id)
        if row is None:
            raise NotFoundError(f"Invitation {invitation_id} doesn't exist.")
        row.token_hash = token_hash
        row.expires_at = expires_at
        row.updated_at = utcnow()
        await self._session.flush()
        return _invitation(row)

    async def count_pending(self, now: datetime) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(InvitationRow)
                .where(InvitationRow.status == InvitationStatus.PENDING.value, InvitationRow.expires_at > now)
            )
            or 0
        )
