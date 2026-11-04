"""Tables owned by the settings module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata


class SettingsBase(DeclarativeBase):
    metadata = make_metadata()


class OrgSettingRow(SettingsBase):
    __tablename__ = "settings_org"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonDocument, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FlagRow(SettingsBase):
    """Feature flags for staged rollouts of modules."""

    __tablename__ = "settings_flags"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonDocument, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
