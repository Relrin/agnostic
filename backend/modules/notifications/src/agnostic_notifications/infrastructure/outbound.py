"""HTTP to Slack and webhook receivers (one pooled client per process)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from agnostic_notifications.application.ports import OutboundResponse


class HttpOutbound:
    def __init__(self, timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=False)

    async def post(
        self,
        url: str,
        *,
        json: Any = None,  # noqa: ANN401
        content: bytes | None = None,
        form: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> OutboundResponse:
        try:
            response = await self._client.post(
                url, json=json, content=content, data=dict(form) if form else None, headers=dict(headers or {})
            )
        except httpx.HTTPError as exc:
            return OutboundResponse(status=599, body=f"{type(exc).__name__}: {exc}")
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text[:2000]
        return OutboundResponse(status=response.status_code, body=body)

    async def aclose(self) -> None:
        await self._client.aclose()
