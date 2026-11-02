"""Tables owned by the evals module (``eval_*``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, TimestampMixin, make_metadata


class EvalsBase(DeclarativeBase):
    metadata = make_metadata()


class DatasetRow(TimestampMixin, EvalsBase):
    """Org-wide: every instance evaluates against the same datasets."""

    __tablename__ = "eval_datasets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    eval_type: Mapped[str] = mapped_column(String(30))
    tags: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(40))


class CaseRow(EvalsBase):
    __tablename__ = "eval_cases"
    __table_args__ = (Index("ix_eval_cases_dataset_id", "dataset_id", "position"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("eval_datasets.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    input: Mapped[str] = mapped_column(Text)
    expected_output: Mapped[str | None] = mapped_column(Text)
    criteria: Mapped[str | None] = mapped_column(Text)
    expected_tool_calls: Mapped[list[str] | None] = mapped_column(JsonDocument)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDocument, default=dict)


class BatchRow(EvalsBase):
    __tablename__ = "eval_batches"
    __table_args__ = (Index("ix_eval_batches_instance_id", "instance_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(40))
    dataset_id: Mapped[str] = mapped_column(String(40))
    dataset_name: Mapped[str] = mapped_column(String(200))
    case_count: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    component_kind: Mapped[str] = mapped_column(String(20))
    component_id: Mapped[str] = mapped_column(String(200))
    component_version: Mapped[int | None] = mapped_column(Integer)
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    eval_type: Mapped[str] = mapped_column(String(30))
    judge_model_id: Mapped[str | None] = mapped_column(String(200))
    judge_provider: Mapped[str | None] = mapped_column(String(100))
    via_bridge: Mapped[bool] = mapped_column(Boolean, default=False)
    params: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    status: Mapped[str] = mapped_column(String(20))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    started_by: Mapped[str] = mapped_column(String(40))
    started_by_name: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    error: Mapped[str | None] = mapped_column(Text)


class BatchItemRow(EvalsBase):
    __tablename__ = "eval_batch_items"
    __table_args__ = (Index("ix_eval_batch_items_batch_id", "batch_id", "position"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("eval_batches.id", ondelete="CASCADE"))
    case_id: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)
    input: Mapped[str] = mapped_column(Text)
    expected: Mapped[str | None] = mapped_column(Text)
    case: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    """The full case as it was when the batch started (what the job sends)."""
    status: Mapped[str] = mapped_column(String(20))
    eval_run_id: Mapped[str | None] = mapped_column(String(200))
    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    actual: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    trace_id: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)


class GateRow(EvalsBase):
    __tablename__ = "eval_publish_gates"
    __table_args__ = (
        UniqueConstraint("instance_id", "component_id", "dataset_id", "eval_type", name="uq_eval_publish_gates_target"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(40))
    component_kind: Mapped[str] = mapped_column(String(20))
    component_id: Mapped[str] = mapped_column(String(200))
    dataset_id: Mapped[str] = mapped_column(String(40))
    eval_type: Mapped[str] = mapped_column(String(30))
    min_average: Mapped[float] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
