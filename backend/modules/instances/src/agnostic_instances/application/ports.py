"""Ports of the instances module."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from agnostic_instances.application.tls import ConnectionTls, connection_tls
from agnostic_instances.domain.instances import (
    Capability,
    Discovery,
    Instance,
    InstanceStatus,
    JwtKey,
    KeyStatus,
)


@dataclass(frozen=True, slots=True)
class Target:
    """How to reach a runtime: endpoint plus TLS (trust and the optional client certificate)."""

    endpoint_url: str
    tls: ConnectionTls = field(default_factory=ConnectionTls)

    @classmethod
    def of(cls, instance: Instance) -> Target:
        return cls(instance.endpoint_url, connection_tls(instance))


class InstanceRepository(Protocol):
    async def add(self, instance: Instance, security_key_sealed: str | None) -> None: ...
    async def get(self, ref: str) -> Instance | None:
        """By id (``ins_…``) or slug."""
        ...

    async def list(self) -> list[Instance]: ...
    async def save(self, instance: Instance, *, expected_version: int | None = None) -> Instance: ...
    async def security_key(self, instance_id: str) -> str | None: ...
    async def set_security_key(self, instance_id: str, sealed: str | None) -> None: ...
    async def delete(self, instance_id: str) -> None: ...
    async def record_health(
        self, instance_id: str, *, status: InstanceStatus, latency_ms: int | None, seen_at: datetime | None
    ) -> None: ...
    async def commit(self) -> None: ...


class KeyRepository(Protocol):
    async def add(self, key: JwtKey, private_sealed: str) -> None: ...
    async def list(self, instance_id: str, statuses: Sequence[KeyStatus] | None = None) -> list[JwtKey]: ...
    async def private(self, instance_id: str, kid: str) -> str | None: ...
    async def set_status(self, instance_id: str, kid: str, status: KeyStatus, at: datetime) -> None: ...


class SnapshotRepository(Protocol):
    async def save(self, instance_id: str, kind: str, payload: Any, fetched_at: datetime) -> None: ...  # noqa: ANN401
    async def latest(self, instance_id: str, kind: str) -> tuple[Any, datetime] | None: ...
    async def save_capabilities(self, instance_id: str, capabilities: Sequence[Capability], at: datetime) -> None: ...
    async def capabilities(self, instance_id: str) -> tuple[list[Capability], datetime | None]: ...


class RuntimeClient(Protocol):
    """Talks to AgentOS runtimes. Errors are the ``agnostic_agentos_client`` ones."""

    async def resolve(self, host: str, port: int) -> list[str]: ...
    async def health(self, target: Target) -> float:
        """Round-trip time of ``GET /health`` in milliseconds."""
        ...

    async def info(self, target: Target) -> Discovery: ...
    async def get_json(
        self, target: Target, path: str, headers: Mapping[str, str], params: Mapping[str, str | int] | None = None
    ) -> Any: ...  # noqa: ANN401
    async def probe(
        self, target: Target, path: str, headers: Mapping[str, str], params: Mapping[str, str | int] | None = None
    ) -> tuple[int, str]: ...
    async def request_json(
        self,
        target: Target,
        method: str,
        path: str,
        headers: Mapping[str, str],
        *,
        params: Mapping[str, str | int] | None = None,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
    ) -> Any: ...  # noqa: ANN401
    async def get_bytes(
        self,
        target: Target,
        path: str,
        headers: Mapping[str, str],
        *,
        params: Mapping[str, str | int] | None = None,
        max_bytes: int,
    ) -> tuple[int, dict[str, str], bytes]:
        """``(status, lower-case headers, body)`` of a GET read as bytes; statuses are not mapped to errors."""
        ...


@dataclass(frozen=True, slots=True)
class GeneratedKey:
    kid: str
    public_pem: str
    private_pem: str


class Signer(Protocol):
    alg: str

    def generate(self) -> GeneratedKey: ...
    def sign(self, private_pem: str, kid: str, claims: Mapping[str, Any]) -> str: ...
    def jwk(self, public_pem: str, kid: str) -> dict[str, str]: ...
    def verify(
        self, token: str, keys: Mapping[str, str], audience: str | None
    ) -> tuple[str | None, dict[str, Any] | None, str | None]:
        """``(kid, claims, error)`` for the "Verify a token" tool."""
        ...
