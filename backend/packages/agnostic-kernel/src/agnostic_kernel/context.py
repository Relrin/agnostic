"""Per-request context shared by logging, errors and outgoing calls."""

from __future__ import annotations

from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("agnostic_request_id", default=None)


def current_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> None:
    _ = _request_id.set(value)
