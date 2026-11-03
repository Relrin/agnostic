"""SQL repositories of the notifications module. Channel configs are sealed at rest."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, time
from typing import Any, cast

import orjson
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.db import aware, aware_or_none, utcnow
from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.ids import new_id
from agnostic_notifications.application.ports import (
    Delivery,
    DeliveryStatus,
    InboxItem,
    NewChannel,
)
from agnostic_notifications.domain.catalog import ChannelKind, QuietHours
from agnostic_notifications.domain.channels import Channel
from agnostic_notifications.infrastructure.tables import (
    ChannelRow,
    DefaultRow,
    DeliveryRow,
    InboxRow,
    PreferenceRow,
    QuietHoursRow,
)


class SqlChannelRepository:
    def __init__(self, session: AsyncSession, secrets: SecretBox) -> None:
        self._session = session
        self._secrets = secrets

    def _channel(self, row: ChannelRow) -> Channel:
        return Channel(
            id=row.id,
            kind=cast("ChannelKind", row.kind),
            name=row.name,
            config=cast("dict[str, Any]", orjson.loads(self._secrets.open(row.config_enc))),
            events=tuple(row.events or ()),
            instance_ids=tuple(row.instance_ids or ()),
            enabled=row.enabled,
            created_by=row.created_by,
            created_at=aware(row.created_at),
            updated_at=aware(row.updated_at),
        )

    async def list(self) -> list[Channel]:
        rows = (await self._session.scalars(select(ChannelRow).order_by(ChannelRow.name))).all()
        return [self._channel(row) for row in rows]

    async def get(self, channel_id: str) -> Channel | None:
        row = await self._session.get(ChannelRow, channel_id)
        return self._channel(row) if row is not None else None

    async def add(self, channel: NewChannel, *, created_by: str) -> Channel:
        now = utcnow()
        row = ChannelRow(
            id=new_id("nch"),
            kind=channel.kind,
            name=channel.name,
            config_enc=self._secrets.seal(orjson.dumps(dict(channel.config))),
            events=list(channel.events),
            instance_ids=list(channel.instance_ids),
            enabled=channel.enabled,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return self._channel(row)

    async def update(self, channel_id: str, changes: Mapping[str, Any]) -> Channel:
        row = await self._session.get(ChannelRow, channel_id)
        if row is None:
            raise NotFoundError(f"There is no notification channel {channel_id!r}.")
        for key, value in changes.items():
            if key == "config":
                row.config_enc = self._secrets.seal(orjson.dumps(dict(value)))
            elif key in {"events", "instance_ids"}:
                setattr(row, key, list(value))
            else:
                setattr(row, key, value)
        row.updated_at = utcnow()
        await self._session.flush()
        return self._channel(row)

    async def delete(self, channel_id: str) -> None:
        _ = await self._session.execute(delete(ChannelRow).where(ChannelRow.id == channel_id))


class SqlPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_user(self, user_id: str) -> dict[str, tuple[str, ...]]:
        rows = (await self._session.scalars(select(PreferenceRow).where(PreferenceRow.user_id == user_id))).all()
        return {row.event_type: tuple(row.channels or ()) for row in rows}

    async def set_for_user(self, user_id: str, preferences: Mapping[str, Sequence[str] | None]) -> None:
        for event, channels in preferences.items():
            row = await self._session.get(PreferenceRow, (user_id, event))
            if channels is None:
                if row is not None:
                    await self._session.delete(row)
            elif row is None:
                self._session.add(
                    PreferenceRow(user_id=user_id, event_type=event, channels=list(channels), updated_at=utcnow())
                )
            else:
                row.channels = list(channels)
                row.updated_at = utcnow()
        await self._session.flush()

    async def defaults(self) -> dict[str, tuple[str, ...]]:
        rows = (await self._session.scalars(select(DefaultRow))).all()
        return {row.event_type: tuple(row.channels or ()) for row in rows}

    async def set_defaults(self, defaults: Mapping[str, Sequence[str] | None]) -> None:
        for event, channels in defaults.items():
            row = await self._session.get(DefaultRow, event)
            if channels is None:
                if row is not None:
                    await self._session.delete(row)
            elif row is None:
                self._session.add(DefaultRow(event_type=event, channels=list(channels), updated_at=utcnow()))
            else:
                row.channels = list(channels)
                row.updated_at = utcnow()
        await self._session.flush()

    async def quiet_hours(self, user_id: str) -> QuietHours | None:
        row = await self._session.get(QuietHoursRow, user_id)
        if row is None:
            return None
        return QuietHours(
            start=time.fromisoformat(row.start_time), end=time.fromisoformat(row.end_time), timezone=row.timezone
        )

    async def set_quiet_hours(self, user_id: str, quiet: QuietHours | None) -> None:
        row = await self._session.get(QuietHoursRow, user_id)
        if quiet is None:
            if row is not None:
                await self._session.delete(row)
        elif row is None:
            self._session.add(
                QuietHoursRow(
                    user_id=user_id,
                    start_time=quiet.start.strftime("%H:%M"),
                    end_time=quiet.end.strftime("%H:%M"),
                    timezone=quiet.timezone,
                )
            )
        else:
            row.start_time = quiet.start.strftime("%H:%M")
            row.end_time = quiet.end.strftime("%H:%M")
            row.timezone = quiet.timezone
        await self._session.flush()


def _item(row: InboxRow) -> InboxItem:
    return InboxItem(
        id=row.id,
        user_id=row.user_id,
        kind=row.kind,
        title=row.title,
        body=row.body,
        link=row.link,
        instance_id=row.instance_id,
        payload=dict(row.payload or {}),
        created_at=aware(row.created_at),
        read_at=aware_or_none(row.read_at),
    )


class SqlInboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        user_id: str,
        kind: str,
        title: str,
        body: str,
        link: str | None,
        instance_id: str | None,
        payload: Mapping[str, Any],
    ) -> InboxItem:
        row = InboxRow(
            id=new_id("ntf"),
            user_id=user_id,
            kind=kind,
            title=title[:300],
            body=body,
            link=link,
            instance_id=instance_id,
            payload=dict(payload),
            created_at=utcnow(),
        )
        self._session.add(row)
        await self._session.flush()
        return _item(row)

    async def page(
        self, user_id: str, *, limit: int, before: tuple[datetime, str] | None, unread_only: bool
    ) -> list[InboxItem]:
        query = select(InboxRow).where(InboxRow.user_id == user_id)
        if unread_only:
            query = query.where(InboxRow.read_at.is_(None))
        if before is not None:
            at, item_id = before
            query = query.where(or_(InboxRow.created_at < at, and_(InboxRow.created_at == at, InboxRow.id < item_id)))
        query = query.order_by(InboxRow.created_at.desc(), InboxRow.id.desc()).limit(limit)
        return [_item(row) for row in (await self._session.scalars(query)).all()]

    async def unread(self, user_id: str) -> int:
        query = select(func.count()).where(InboxRow.user_id == user_id, InboxRow.read_at.is_(None))
        return int((await self._session.execute(query)).scalar_one())

    async def mark_read(self, user_id: str, item_ids: Sequence[str] | None) -> int:
        statement = update(InboxRow).where(InboxRow.user_id == user_id, InboxRow.read_at.is_(None))
        if item_ids is not None:
            statement = statement.where(InboxRow.id.in_(list(item_ids)))
        result = await self._session.execute(
            statement.values(read_at=utcnow()).execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)


def _delivery(row: DeliveryRow) -> Delivery:
    return Delivery(
        id=row.id,
        event_type=row.event_type,
        channel=cast("Any", row.channel),
        channel_id=row.channel_id,
        user_id=row.user_id,
        target=row.target,
        message=dict(row.message or {}),
        status=cast("DeliveryStatus", row.status),
        attempts=row.attempts,
        error=row.error,
        message_ref=row.message_ref,
        created_at=aware(row.created_at),
        sent_at=aware_or_none(row.sent_at),
    )


class SqlDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        event_type: str,
        channel: str,
        channel_id: str | None,
        user_id: str | None,
        target: str,
        message: Mapping[str, Any],
    ) -> Delivery:
        row = DeliveryRow(
            id=new_id("ndl"),
            event_type=event_type,
            channel=channel,
            channel_id=channel_id,
            user_id=user_id,
            target=target[:500],
            message=dict(message),
            status="pending",
            attempts=0,
            created_at=utcnow(),
        )
        self._session.add(row)
        await self._session.flush()
        return _delivery(row)

    async def get(self, delivery_id: str) -> Delivery | None:
        row = await self._session.get(DeliveryRow, delivery_id)
        return _delivery(row) if row is not None else None

    async def finish(
        self, delivery_id: str, *, status: DeliveryStatus, error: str | None = None, message_ref: str | None = None
    ) -> None:
        row = await self._session.get(DeliveryRow, delivery_id)
        if row is None:
            return
        row.status = status
        row.error = error
        row.attempts += 0 if status == "skipped" else 1
        if message_ref is not None:
            row.message_ref = message_ref
        if status == "sent":
            row.sent_at = utcnow()
        await self._session.flush()

    async def recent(self, *, channel_id: str | None = None, limit: int = 20) -> list[Delivery]:
        query = select(DeliveryRow)
        if channel_id is not None:
            query = query.where(DeliveryRow.channel_id == channel_id)
        query = query.order_by(DeliveryRow.created_at.desc(), DeliveryRow.id.desc()).limit(limit)
        return [_delivery(row) for row in (await self._session.scalars(query)).all()]


class SqlRepositories:
    """The four repositories on one session, committed together."""

    def __init__(self, session: AsyncSession, secrets: SecretBox) -> None:
        self._session = session
        self.channels = SqlChannelRepository(session, secrets)
        self.preferences = SqlPreferenceRepository(session)
        self.inbox = SqlInboxRepository(session)
        self.deliveries = SqlDeliveryRepository(session)

    async def commit(self) -> None:
        await self._session.commit()
