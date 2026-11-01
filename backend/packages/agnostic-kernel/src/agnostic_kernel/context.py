"""Per-request context shared by logging, errors, audit records and outgoing calls."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None


_request_id: ContextVar[str | None] = ContextVar("agnostic_request_id", default=None)
_client: ContextVar[ClientInfo] = ContextVar("agnostic_client", default=ClientInfo())  # noqa: B039


def current_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> None:
    _ = _request_id.set(value)


def current_client() -> ClientInfo:
    return _client.get()


def set_client(value: ClientInfo) -> None:
    _ = _client.set(value)
