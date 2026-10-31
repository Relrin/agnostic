"""Tables owned by the hello module (``hello_*`` in schema ``agnostic``)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import make_metadata


class HelloBase(DeclarativeBase):
    metadata = make_metadata()


class GreetingRow(HelloBase):
    __tablename__ = "hello_greetings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    reply: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
