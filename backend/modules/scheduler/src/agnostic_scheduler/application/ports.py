"""What the scheduler use cases need from storage: the reasons people gave for disabling schedules."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DisableNote:
    """AgentOS keeps ``disabled_reason`` for itself (an archived target); the person's reason lives here."""

    instance_id: str
    schedule_id: str
    reason: str
    disabled_by: str
    disabled_by_name: str
    disabled_at: datetime


class NoteStore(Protocol):
    async def notes(self, instance_id: str, schedule_ids: Sequence[str]) -> dict[str, DisableNote]: ...
    async def set(self, note: DisableNote) -> None: ...
    async def clear(self, instance_id: str, schedule_id: str) -> None: ...
    async def commit(self) -> None: ...
