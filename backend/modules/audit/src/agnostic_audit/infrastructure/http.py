"""Outbound HTTP of the audit module (archive storage, SIEM webhooks, OTLP); tests swap the transport."""

from __future__ import annotations

import httpx


class AuditHttp:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 30.0) -> None:
        self.client = httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False)

    async def aclose(self) -> None:
        await self.client.aclose()
