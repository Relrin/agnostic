"""Typed async client for one AgentOS 3.1.x runtime.

Hand-written transport (httpx, HTTP/2, one pool per instance, retries for idempotent GETs, error mapping) around
generated models. One ``AgentOSClient`` per instance; share it, it's safe for concurrent use.
"""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import AsyncIterable, Mapping
from types import TracebackType
from typing import Any, Self, cast

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
        verify: bool | str | ssl.SSLContext = True,
        transport: httpx.AsyncBaseTransport | None = None,
        max_connections: int = 50,
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
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=10),
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

    async def get_json(self, path: str, *, params: Mapping[str, str | int] | None = None) -> Any:  # noqa: ANN401
        """GET a route the typed methods don't cover; errors are mapped like everywhere else."""
        response = await self._get(path, params=params)
        try:
            return response.json()
        except ValueError as exc:
            msg = f"GET {path}: the response is not JSON"
            raise UnexpectedResponseError(msg, status=response.status_code, body=response.text[:2000]) from exc

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
    ) -> Any:  # noqa: ANN401
        """Send one JSON or form request (no retries unless it is a GET); errors are mapped like everywhere else.

        Returns the decoded JSON body, or ``None`` for an empty body (204).
        """
        if method.upper() == "GET" and json is None and form is None:
            return await self.get_json(path, params=params)
        headers = await self._auth.headers()
        try:
            response = await self._http.request(method, path, params=params, json=json, data=form, headers=headers)
        except httpx.TransportError as exc:
            msg = f"{method} {path}: {type(exc).__name__}: {exc}"
            raise InstanceUnreachableError(msg) from exc
        _ = _raise_for_status(path, response, method=method)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            msg = f"{method} {path}: the response is not JSON"
            raise UnexpectedResponseError(msg, status=response.status_code, body=response.text[:2000]) from exc

    async def probe(self, path: str, *, params: Mapping[str, str | int] | None = None) -> tuple[int, str]:
        """``(status, body excerpt)`` of a GET without retries or error mapping (capability probes).

        Transport failures still raise :class:`InstanceUnreachableError`.
        """
        headers = await self._auth.headers()
        try:
            response = await self._http.get(path, params=params, headers=headers)
        except httpx.TransportError as exc:
            msg = f"GET {path}: {type(exc).__name__}: {exc}"
            raise InstanceUnreachableError(msg) from exc
        return response.status_code, response.text[:2000]

    async def open_stream(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        headers: Mapping[str, str] | None = None,
        content: AsyncIterable[bytes] | bytes | None = None,
        request_timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        """Send a request and return the response unread (``stream=True``); the caller must ``aclose()`` it.

        The gateway uses this for passthrough: bodies stream both ways, nothing is buffered, and statuses are
        returned as they are (no error mapping, no retries: the request may not be idempotent).
        """
        request = self._http.build_request(
            method,
            path,
            params=httpx.QueryParams(cast("Any", params)) if params else None,
            headers=dict(headers or {}),
            content=content,
            timeout=request_timeout if request_timeout is not None else self._http.timeout,
        )
        try:
            return await self._http.send(request, stream=True)
        except httpx.TransportError as exc:
            msg = f"{method} {path}: {type(exc).__name__}: {exc}"
            raise InstanceUnreachableError(msg) from exc

    async def _get_model[M: BaseModel](self, path: str, model: type[M]) -> M:
        response = await self._get(path)
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            msg = f"GET {path}: response doesn't match the pinned AgentOS schema: {exc}"
            raise UnexpectedResponseError(msg, status=response.status_code, body=response.text[:2000]) from exc

    async def _get(
        self, path: str, *, params: Mapping[str, str | int] | None = None, request_id: str | None = None
    ) -> httpx.Response:
        headers = await self._auth.headers()
        if request_id:
            headers["X-Request-Id"] = request_id
        attempt = 0
        while True:
            try:
                response = await self._http.get(path, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    msg = f"GET {path}: {type(exc).__name__}: {exc}"
                    raise InstanceUnreachableError(msg) from exc
            else:
                if response.status_code not in RETRYABLE_STATUS or attempt >= self._retries:
                    return _raise_for_status(path, response)
            attempt += 1
            await asyncio.sleep(self._backoff * 2 ** (attempt - 1))


def _raise_for_status(path: str, response: httpx.Response, *, method: str = "GET") -> httpx.Response:
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
    raise error(f"{method} {path}: HTTP {status}", status=status, body=body)
