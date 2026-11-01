"""Tables owned by the search module (``search_*``)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import make_metadata


class SearchBase(DeclarativeBase):
    metadata = make_metadata()


class SearchDocumentRow(SearchBase):
    """One palette entry. On PostgreSQL the migration adds a generated ``tsv`` column (GIN) and a trigram index."""

    __tablename__ = "search_documents"
    __table_args__ = (Index("ix_search_documents_provider", "provider"),)

    id: Mapped[str] = mapped_column(String(400), primary_key=True)
    provider: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(40))
    ref: Mapped[str] = mapped_column(String(200))
    instance_id: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    url_path: Mapped[str] = mapped_column(String(500), default="")
    required_scope: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
