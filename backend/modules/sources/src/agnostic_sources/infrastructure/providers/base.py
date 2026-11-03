"""What the git host API clients share: JSON calls with errors people can act on."""

from __future__ import annotations

import base64
from typing import Any, cast

import httpx

from agnostic_sources.application.ports import ProviderError

NOT_FOUND = 404
FORBIDDEN = 403
UNAUTHORIZED = 401


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


class Api:
    def __init__(self, client: httpx.AsyncClient, base_url: str, host: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._host = host

    async def headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: object = None,
        allow: frozenset[int] = frozenset(),
    ) -> tuple[int, Any]:
        try:
            response = await self._client.request(
                method, f"{self._base}{path}", params=params, json=json, headers=await self.headers()
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self._host} couldn't be reached: {exc}") from exc
        body: Any = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = response.text[:300]
        if response.is_success or response.status_code in allow:
            return response.status_code, body
        raise ProviderError(
            _message(self._host, response.status_code, body), extra={"upstream_status": response.status_code}
        )

    async def json(self, method: str, path: str, **kwargs: Any) -> Any:  # noqa: ANN401
        _, body = await self.request(method, path, **kwargs)
        return body


def _message(host: str, status: int, body: object) -> str:
    detail = ""
    if isinstance(body, dict):
        data = cast("dict[str, Any]", body)
        detail = str(data.get("message") or data.get("error") or "")
    elif isinstance(body, str):
        detail = body
    if status in {UNAUTHORIZED, FORBIDDEN}:
        prefix = f"{host} refused the connection's credentials"
    elif status == NOT_FOUND:
        prefix = f"{host} doesn't know this repository (or the connection can't see it)"
    else:
        prefix = f"{host} answered HTTP {status}"
    return f"{prefix}: {detail}" if detail else prefix


def items(body: object, key: str | None = None) -> list[dict[str, Any]]:
    if key is not None and isinstance(body, dict):
        body = cast("dict[str, Any]", body).get(key)
    if isinstance(body, list):
        return [cast("dict[str, Any]", item) for item in cast("list[Any]", body) if isinstance(item, dict)]
    return []
