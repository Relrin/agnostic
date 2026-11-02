"""Tables owned by the observe module (``obs_*``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata


class ObserveBase(DeclarativeBase):
    metadata = make_metadata()


class PriceRow(ObserveBase):
    """One model's rates in USD per million tokens. ``instance_id`` null = the org default table."""

    __tablename__ = "obs_price_tables"
    __table_args__ = (Index("ix_obs_price_tables_instance_id", "instance_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[str | None] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str | None] = mapped_column(String(100))
    input_per_1m: Mapped[float] = mapped_column(Float)
    output_per_1m: Mapped[float] = mapped_column(Float)
    cache_read_per_1m: Mapped[float | None] = mapped_column(Float)
    reasoning_per_1m: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    updated_by: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TraceComparisonRow(ObserveBase):
    """Cached comparison of a trace with one baseline trace."""

    __tablename__ = "obs_trace_comparisons"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    baseline_trace_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    result: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
