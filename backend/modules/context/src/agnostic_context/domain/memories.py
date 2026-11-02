"""Likely-duplicate memories (word trigrams, as PostgreSQL ``pg_trgm``) and the run a memory most likely came from.

AgentOS memory responses carry neither the source input nor the session, so the source run is matched: the newest
run of the memory's user and agent that started before the memory was last written.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

_WORD = re.compile(r"[0-9a-z]+")
SOURCE_SLACK = timedelta(minutes=2)
"""Memories are written while or right after a run; clocks of the run and memory tables can drift a little."""


def trigrams(text: str) -> frozenset[str]:
    """``pg_trgm``'s trigrams: lowercase alphanumeric words, each padded with two spaces before and one after."""
    grams: set[str] = set()
    for word in _WORD.findall(text.lower()):
        padded = f"  {word} "
        grams.update(padded[index : index + 3] for index in range(len(padded) - 2))
    return frozenset(grams)


def similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Shared trigrams over all trigrams (0 to 1)."""
    union = len(left | right)
    return len(left & right) / union if union else 0.0


@dataclass(frozen=True, slots=True)
class MemoryText:
    memory_id: str
    text: str
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class Duplicate:
    memory_id: str
    """The memory flagged "likely duplicate": the shorter of the pair (it adds less), else the older one."""
    duplicate_of: str
    similarity: float


def _keeps(left: MemoryText, right: MemoryText) -> bool:
    """Whether ``left`` is the one to keep when it and ``right`` say the same thing."""
    if len(left.text.strip()) != len(right.text.strip()):
        return len(left.text.strip()) > len(right.text.strip())
    left_at, right_at = left.updated_at, right.updated_at
    if left_at is not None and right_at is not None and left_at != right_at:
        return left_at > right_at
    return left.memory_id < right.memory_id


def find_duplicates(memories: Sequence[MemoryText], threshold: float) -> list[Duplicate]:
    """Each memory is flagged at most once, against its most similar match; strongest pairs first."""
    grams = [trigrams(memory.text) for memory in memories]
    best: dict[str, Duplicate] = {}
    for i, left in enumerate(memories):
        for j in range(i + 1, len(memories)):
            right = memories[j]
            score = similarity(grams[i], grams[j])
            if score < threshold:
                continue
            kept, flagged = (left, right) if _keeps(left, right) else (right, left)
            current = best.get(flagged.memory_id)
            if current is None or score > current.similarity:
                best[flagged.memory_id] = Duplicate(flagged.memory_id, kept.memory_id, round(score, 3))
    return sorted(best.values(), key=lambda item: (-item.similarity, item.memory_id))


@dataclass(frozen=True, slots=True)
class RunRef:
    session_id: str
    run_id: str
    created_at: datetime
    input: str | None
    status: str | None


def source_run(runs: Sequence[RunRef], written_at: datetime) -> RunRef | None:
    """The newest run that started before the memory was written (within :data:`SOURCE_SLACK`)."""
    candidates = [run for run in runs if run.created_at <= written_at + SOURCE_SLACK]
    return max(candidates, key=lambda run: run.created_at, default=None)
