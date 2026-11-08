"""Tables owned by the artefacts module (``art_*``). The token of a share link is stored only as its SHA-256."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import make_metadata


class ArtifactsBase(DeclarativeBase):
    metadata = make_metadata()


class ShareRow(ArtifactsBase):
    __tablename__ = "art_shares"
    __table_args__ = (Index("ix_art_shares_instance_session", "instance_id", "session_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    instance_id: Mapped[str] = mapped_column(String(40))
    session_id: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(1024))
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    audience: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[str] = mapped_column(String(40))
    created_by_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_count: Mapped[int] = mapped_column(Integer, default=0)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
