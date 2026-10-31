"""Typed async client for one AgentOS 3.1.x runtime.

Hand-written transport (httpx, HTTP/2, one pool per instance, retries for idempotent GETs, error mapping) around
generated models. One ``AgentOSClient`` per instance; share it, it's safe for concurrent use.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Self

import httpx
from pydantic import BaseModel, ValidationError

from agnostic_agentos_client.auth import Auth, NoAuth
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

USER_AGENT = "agnostic-agentos-client/0.1"
RETRYABLE_STATUS = frozenset({502, 503, 504})


class AgentOSClient:
    def __init__(
        self,
        base_url: str,
        *,
        auth: Auth | None = None,
        timeout: float = 10.0,
        retries: int = 2,
        backoff: float = 0.2,
        verify: bool | str = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth = auth or NoAuth()
        self._retries = retries
        self._backoff = backoff
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            http2=transport is None,
            verify=verify,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> HealthResponse:
        return await self._get_model("/health", HealthResponse)

    async def info(self) -> InfoResponse:
        return await self._get_model("/info", InfoResponse)

    async def config(self) -> OsConfig:
        return await self._get_model("/config", OsConfig)

    async def _get_model[M: BaseModel](self, path: str, model: type[M]) -> M:
        response = await self._get(path)
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            msg = f"GET {path}: response doesn't match the pinned AgentOS schema: {exc}"
            raise UnexpectedResponseError(msg, status=response.status_code, body=response.text[:2000]) from exc

    async def _get(self, path: str, *, request_id: str | None = None) -> httpx.Response:
        headers = await self._auth.headers()
        if request_id:
            headers["X-Request-Id"] = request_id
        attempt = 0
        while True:
            try:
                response = await self._http.get(path, headers=headers)
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    msg = f"GET {path}: {type(exc).__name__}: {exc}"
                    raise InstanceUnreachableError(msg) from exc
            else:
                if response.status_code not in RETRYABLE_STATUS or attempt >= self._retries:
                    return _raise_for_status(path, response)
            attempt += 1
            await asyncio.sleep(self._backoff * 2 ** (attempt - 1))


def _raise_for_status(path: str, response: httpx.Response) -> httpx.Response:
    status = response.status_code
    if status < 400:  # noqa: PLR2004
        return response
    body = response.text[:2000]
    error: type[AgentOSError] = {
        401: InstanceAuthFailedError,
        403: ForbiddenError,
        404: NotFoundError,
        503: CapabilityDisabledError,
    }.get(status, UnexpectedResponseError)
    raise error(f"GET {path}: HTTP {status}", status=status, body=body)
