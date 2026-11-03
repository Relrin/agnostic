"""Tamper-evidence hash chain over audit events.

Each chained event stores ``prev_hash`` (the hash of the event chained before it) and
``hash = sha256(prev_hash + canonical JSON of the event's stable fields)``. Changing, inserting or removing an event
inside a verified range breaks the link at that point.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agnostic_audit.domain.events import AuditEvent, event_document

GENESIS = ""
"""``prev_hash`` of the first event ever chained."""

_UNHASHED = frozenset({"prev_hash", "hash"})


def canonical_json(event: AuditEvent) -> str:
    """Sorted keys, no whitespace, UTF-8 text: the same event always gives the same string."""
    stable: dict[str, Any] = {key: value for key, value in event_document(event).items() if key not in _UNHASHED}
    return json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def chain_hash(prev_hash: str | None, event: AuditEvent) -> str:
    payload = (prev_hash or GENESIS) + canonical_json(event)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ChainResult:
    ok: bool
    checked: int
    first_broken_event_id: str | None = None


class ChainVerifier:
    """Feed events in chain order (``occurred_at``, then ``id``); unchained events (no hash) are skipped.

    The first chained event's ``prev_hash`` anchors the range unless ``anchor`` is given (the hash just before it).
    """

    def __init__(self, anchor: str | None = None) -> None:
        self._last: str | None = anchor
        self._started = anchor is not None
        self.checked = 0
        self.first_broken: str | None = None

    def feed(self, event: AuditEvent) -> bool:
        """``False`` once the chain is broken (stop feeding)."""
        if self.first_broken is not None:
            return False
        if event.hash is None:
            return True
        self.checked += 1
        linked = not self._started or (event.prev_hash or GENESIS) == (self._last or GENESIS)
        if not linked or chain_hash(event.prev_hash, event) != event.hash:
            self.first_broken = event.id
            return False
        self._started = True
        self._last = event.hash
        return True

    def result(self) -> ChainResult:
        return ChainResult(ok=self.first_broken is None, checked=self.checked, first_broken_event_id=self.first_broken)
