"""Errors raised by the AgentOS client, mapped from transport failures and status codes."""

from __future__ import annotations


class AgentOSError(Exception):
    """Base class; ``status`` is the HTTP status when the runtime answered."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class InstanceUnreachableError(AgentOSError):
    """Connection refused, DNS failure, TLS failure or timeout."""


class InstanceAuthFailedError(AgentOSError):
    """401: the token or security key was rejected (often a key mismatch)."""


class ForbiddenError(AgentOSError):
    """403: authenticated, but the token lacks a scope."""


class NotFoundError(AgentOSError):
    """404 (AgentOS also answers 404 to callers who may not see a resource)."""


class CapabilityDisabledError(AgentOSError):
    """503: the feature isn't enabled on this runtime (e.g. no durable queue, async db for Studio)."""


class UnexpectedResponseError(AgentOSError):
    """Any other non-success status, or a body that doesn't match the pinned schema."""
