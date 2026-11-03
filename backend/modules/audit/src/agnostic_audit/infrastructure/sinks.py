"""SIEM transports: signed HTTPS webhooks, syslog (RFC 5424 over TCP or TLS) and OTLP/HTTP JSON logs."""

from __future__ import annotations

import asyncio
import contextlib
import ssl
import time
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

import httpx
import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_audit.domain.events import AuditEvent
from agnostic_audit.domain.siem import (
    COUNT_HEADER,
    SIGNATURE_HEADER,
    DeliveryResult,
    Sink,
    as_text,
    format_event,
    otlp_logs_request,
    syslog_message,
    syslog_severity,
    webhook_body,
    webhook_signature,
)
from agnostic_audit.infrastructure.http import AuditHttp
from agnostic_kernel.db import utcnow

DELIVERY_LOCK_KEY = 0x6175646974736E6B
"""``pg_try_advisory_lock`` key held by the worker that is delivering to sinks ("auditsnk")."""
SYSLOG_TIMEOUT = 10.0


def product_version() -> str:
    try:
        return version("agnostic-audit")
    except PackageNotFoundError:
        return "0.0.0"


class SinkTransports:
    def __init__(self, http: AuditHttp) -> None:
        self._http = http
        self._version = product_version()

    async def send(self, sink: Sink, events: Sequence[AuditEvent]) -> DeliveryResult:
        started = time.monotonic()
        try:
            if sink.kind == "https_webhook":
                result = await self._webhook(sink, events)
            elif sink.kind == "syslog":
                result = await self._syslog(sink, events)
            else:
                result = await self._otlp(sink, events)
        except (httpx.HTTPError, OSError, ssl.SSLError, TimeoutError) as exc:
            result = DeliveryResult(ok=False, error=f"{type(exc).__name__}: {exc}"[:500])
        return DeliveryResult(
            ok=result.ok,
            status_code=result.status_code,
            error=result.error,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    @staticmethod
    def _http_result(response: httpx.Response) -> DeliveryResult:
        if 200 <= response.status_code < 300:  # noqa: PLR2004
            return DeliveryResult(ok=True, status_code=response.status_code)
        return DeliveryResult(
            ok=False, status_code=response.status_code, error=f"HTTP {response.status_code}: {response.text[:200]}"
        )

    async def _webhook(self, sink: Sink, events: Sequence[AuditEvent]) -> DeliveryResult:
        body = webhook_body(events, sink.format, product_version=self._version)
        headers: dict[str, str] = {
            **dict(sink.config.get("headers") or {}),
            "content-type": "application/json",
            COUNT_HEADER: str(len(events)),
        }
        secret = sink.config.get("secret")
        if secret:
            headers[SIGNATURE_HEADER] = webhook_signature(str(secret).encode(), int(time.time()), body)
        response = await self._http.client.post(str(sink.config["url"]), content=body, headers=headers)
        return self._http_result(response)

    async def _otlp(self, sink: Sink, events: Sequence[AuditEvent]) -> DeliveryResult:
        request = otlp_logs_request(events, sink.format, product_version=self._version, observed_at=utcnow())
        headers = {**dict(sink.config.get("headers") or {}), "content-type": "application/json"}
        url = f"{str(sink.config['endpoint']).rstrip('/')}/v1/logs"
        response = await self._http.client.post(url, content=orjson.dumps(request), headers=headers)
        return self._http_result(response)

    async def _syslog(self, sink: Sink, events: Sequence[AuditEvent]) -> DeliveryResult:
        config = sink.config
        context: ssl.SSLContext | None = None
        if config.get("tls", True):
            context = ssl.create_default_context(cadata=config.get("ca_pem") or None)
            if not config.get("tls_verify", True):
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
        hostname = str(config.get("hostname") or "agnostic")
        frames = b"".join(
            syslog_message(
                as_text(format_event(event, sink.format, product_version=self._version)),
                timestamp=event.occurred_at,
                hostname=hostname,
                severity=syslog_severity(event),
            )
            for event in events
        )
        async with asyncio.timeout(SYSLOG_TIMEOUT):
            _, writer = await asyncio.open_connection(str(config["host"]), int(config["port"]), ssl=context)
            try:
                writer.write(frames)
                await writer.drain()
            finally:
                writer.close()
                with contextlib.suppress(OSError, ssl.SSLError):
                    await writer.wait_closed()
        return DeliveryResult(ok=True)


class SqlDeliveryLock:
    """One delivery at a time: a session advisory lock on PostgreSQL (across workers), a local lock elsewhere."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._local = asyncio.Lock()

    @asynccontextmanager
    async def hold(self) -> AsyncGenerator[bool]:
        if self._local.locked():
            yield False
            return
        async with self._local:
            if self._engine.dialect.name != "postgresql":
                yield True
                return
            async with self._engine.connect() as connection:
                acquired = bool(
                    await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": DELIVERY_LOCK_KEY})
                )
                await connection.commit()
                try:
                    yield acquired
                finally:
                    if acquired:
                        _ = await connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": DELIVERY_LOCK_KEY}
                        )
                        await connection.commit()
