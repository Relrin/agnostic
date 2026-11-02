"""Ports of the observe module: price tables and the trace-comparison cache."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from agnostic_observe.domain.costs import Price

type PriceScope = Literal["org", "instance"]


@dataclass(frozen=True, slots=True)
class PriceEntry:
    price: Price
    scope: PriceScope
    updated_at: datetime | None
    updated_by: str | None


class PriceRepository(Protocol):
    async def rows(self, instance_id: str | None) -> list[PriceEntry]:
        """The org defaults (``instance_id=None``) or one instance's overrides."""
        ...

    async def replace(self, instance_id: str | None, prices: Sequence[Price], updated_by: str) -> None:
        """Replace the whole table of that scope (joins the request's unit of work)."""
        ...

    async def commit(self) -> None: ...


class ComparisonStore(Protocol):
    async def get(
        self, instance_id: str, trace_id: str, baseline_trace_id: str, *, newer_than: datetime
    ) -> dict[str, Any] | None: ...

    async def put(self, instance_id: str, trace_id: str, baseline_trace_id: str, result: dict[str, Any]) -> None:
        """Stores and commits."""
        ...
