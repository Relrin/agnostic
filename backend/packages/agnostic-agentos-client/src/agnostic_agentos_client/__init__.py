"""Typed async client for Agno AgentOS 3.1.x."""

from agnostic_agentos_client.auth import Auth, BearerAuth, NoAuth, SecurityKeyAuth, StaticBearerAuth
from agnostic_agentos_client.client import AgentOSClient
from agnostic_agentos_client.errors import (
    AgentOSError,
    CapabilityDisabledError,
    ForbiddenError,
    InstanceAuthFailedError,
    InstanceUnreachableError,
    NotFoundError,
    UnexpectedResponseError,
)
from agnostic_agentos_client.models import HealthResponse, InfoResponse, OsConfig

AGENTOS_VERSION = "3.1.12"
"""The AgentOS/agno version the generated models were taken from."""

__all__ = [
    "AGENTOS_VERSION",
    "AgentOSClient",
    "AgentOSError",
    "Auth",
    "BearerAuth",
    "CapabilityDisabledError",
    "ForbiddenError",
    "HealthResponse",
    "InfoResponse",
    "InstanceAuthFailedError",
    "InstanceUnreachableError",
    "NoAuth",
    "NotFoundError",
    "OsConfig",
    "SecurityKeyAuth",
    "StaticBearerAuth",
    "UnexpectedResponseError",
]
