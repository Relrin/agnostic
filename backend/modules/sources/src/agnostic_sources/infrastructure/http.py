"""The HTTP client for git host APIs (one per process; tests route it to fake hosts)."""

from __future__ import annotations

import httpx


class SourcesHttp:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 15.0) -> None:
        self.client = httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "agnostic-sources"},
        )

    async def aclose(self) -> None:
        await self.client.aclose()
