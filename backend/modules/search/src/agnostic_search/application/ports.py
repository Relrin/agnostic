"""Ports of the search module."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from agnostic_kernel.modules import SearchDocument


@dataclass(frozen=True, slots=True)
class Hit:
    kind: str
    ref: str
    instance_id: str | None
    title: str
    body: str
    url_path: str
    required_scope: str | None
    score: float


class SearchIndex(Protocol):
    async def replace(self, provider: str, documents: Sequence[SearchDocument]) -> None:
        """Swap every document of ``provider`` for ``documents`` (the caller commits)."""
        ...

    async def count(self) -> int: ...
    async def query(self, text: str, *, instance_id: str | None, limit: int) -> list[Hit]: ...
