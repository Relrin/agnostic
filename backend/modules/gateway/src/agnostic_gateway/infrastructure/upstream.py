"""Pooled clients per instance (HTTP/2, keep-alive) for passthrough calls, and route-policy overrides."""

from __future__ import annotations

import hashlib
import ssl
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import cast

import httpx
from sqlalchemy import Boolean, DateTime, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_agentos_client import AgentOSClient
from agnostic_gateway.domain.policies import AuditLevel, RateBucket, RoutePolicy
from agnostic_instances.facade import ConnectionTlsFactory, Instance, connection_tls
from agnostic_kernel.db import JsonDocument, make_metadata


class UpstreamPool:
    def __init__(
        self,
        *,
        read_timeout: float,
        max_connections: int = 200,
        transport: httpx.AsyncBaseTransport | None = None,
        tls: ConnectionTlsFactory | None = None,
    ) -> None:
        self._transport = transport
        self._tls = tls
        self._clients: dict[str, AgentOSClient] = {}
        self._retired: list[AgentOSClient] = []
        """Clients replaced after a TLS or endpoint change; closed on shutdown (streams may still use them)."""
        self._timeout = httpx.Timeout(connect=5.0, read=read_timeout, write=60.0, pool=10.0)
        self._max_connections = max_connections

    def _client(self, instance: Instance) -> AgentOSClient:
        tls = connection_tls(instance)
        fingerprint = hashlib.sha256(f"{instance.endpoint_url}|{tls.fingerprint}".encode()).hexdigest()[:16]
        key = f"{instance.id}:{fingerprint}"
        client = self._clients.get(key)
        if client is None:
            stale = [name for name in self._clients if name.startswith(f"{instance.id}:")]
            for name in stale:
                self._retired.append(self._clients.pop(name))
            verify: bool | ssl.SSLContext = instance.tls_verify
            if self._tls is not None:
                verify = self._tls.verify(tls)
            elif instance.tls_verify and instance.ca_bundle_pem:
                verify = ssl.create_default_context(cadata=instance.ca_bundle_pem)
            client = AgentOSClient(
                instance.endpoint_url,
                timeout=30.0,
                retries=0,
                verify=verify,
                max_connections=self._max_connections,
                transport=self._transport,
            )
            self._clients[key] = client
        return client

    async def send(
        self,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]],
        headers: Mapping[str, str],
        body: AsyncIterator[bytes] | None,
    ) -> httpx.Response:
        return await self._client(instance).open_stream(
            method, path, params=params, headers=headers, content=body, request_timeout=self._timeout
        )

    async def aclose(self) -> None:
        for client in (*self._clients.values(), *self._retired):
            await client.aclose()
        self._clients.clear()
        self._retired.clear()


class GatewayBase(DeclarativeBase):
    metadata = make_metadata()


class RoutePolicyRow(GatewayBase):
    """Overrides of the code-defined route policies (and routes added by operators)."""

    __tablename__ = "gw_route_policies"

    method: Mapped[str] = mapped_column(String(10), primary_key=True)
    path_pattern: Mapped[str] = mapped_column(String(300), primary_key=True)
    required_scopes: Mapped[list[str]] = mapped_column(JsonDocument)
    cache_ttl_s: Mapped[int] = mapped_column(Integer, default=0)
    audit_level: Mapped[str] = mapped_column(String(10), default="decision")
    rate_bucket: Mapped[str] = mapped_column(String(10), default="read")
    list_filter: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SqlRoutePolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def overrides(self) -> list[RoutePolicy]:
        rows = await self._session.scalars(select(RoutePolicyRow))
        return [
            RoutePolicy(
                method=row.method.upper(),
                pattern=row.path_pattern,
                scopes=tuple(row.required_scopes),
                cache_ttl_s=row.cache_ttl_s,
                audit_level=cast("AuditLevel", row.audit_level),
                rate_bucket=cast("RateBucket", row.rate_bucket),
                list_filter=row.list_filter,
                source="override",
            )
            for row in rows
        ]
