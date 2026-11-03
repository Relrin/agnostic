"""Tables owned by the scheduler module (``sch_*``). Schedules themselves stay in AgentOS (``agno_schedules``)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import make_metadata


class SchedulerBase(DeclarativeBase):
    metadata = make_metadata()


class NoteRow(SchedulerBase):
    """Why a person disabled a schedule (the AgentOS ``disabled_reason`` is set by the system)."""

    __tablename__ = "sch_notes"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    schedule_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    reason: Mapped[str] = mapped_column(String(500))
    disabled_by: Mapped[str] = mapped_column(String(40))
    disabled_by_name: Mapped[str] = mapped_column(String(200))
    disabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
