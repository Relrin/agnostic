"""HTTP middleware: request ids (accepted from ``X-Request-Id`` or generated, echoed back, bound to logs)."""

from __future__ import annotations

import re

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agnostic_kernel.context import set_request_id
from agnostic_kernel.ids import new_id

REQUEST_ID_HEADER = "X-Request-Id"
_VALID_INCOMING = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, REQUEST_ID_HEADER.lower().encode())
        request_id = incoming if incoming and _VALID_INCOMING.fullmatch(incoming) else new_id("req")
        set_request_id(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        # The id stays bound after the call: each request runs in its own task context, and the outermost error
        # handler (unhandled exceptions) still needs it for the problem body and header.
        await self.app(scope, receive, send_with_id)


def _header(scope: Scope, name: bytes) -> str | None:
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return None
