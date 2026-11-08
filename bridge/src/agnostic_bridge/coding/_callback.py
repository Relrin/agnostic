"""The routes sandboxes call back on, served ahead of the AgentOS auth layer.

AgentOS checks every request against its JWT (or security key) settings; a sandbox holds neither, only the run token
its turn was given. This middleware sits outside that layer, answers the callback paths itself after checking the
run token, and passes every other request through untouched. The callback paths are not in the OpenAPI document, not
in the scope table and not reachable through the control plane's gateway.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.responses import JSONResponse, Response

from agnostic_bridge.coding._grants import GrantStore, RunGrant
from agnostic_bridge.coding._llm import MODEL_ALIAS, chat_completions
from agnostic_bridge.coding._mcp import handle_mcp

CALLBACK_PREFIX = "/agnostic/v1/coding"
LLM_PREFIX = f"{CALLBACK_PREFIX}/llm/v1"
MCP_PATH = f"{CALLBACK_PREFIX}/mcp"
MAX_BODY_BYTES = 16 * 1024 * 1024

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class BodyTooLarge(Exception):
    pass


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise BodyTooLarge
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _bearer(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name == b"authorization":
            text = value.decode("latin-1")
            if text[:7].lower() == "bearer ":
                return text[7:].strip()
    return None


def _unauthorized() -> Response:
    # No WWW-Authenticate: an MCP client seeing one would start OAuth discovery against the runtime.
    return JSONResponse({"error": {"message": "Invalid or expired run token", "type": "authentication_error"}}, 401)


class CallbackMiddleware:
    """``app.add_middleware(CallbackMiddleware, grants=store)``; outermost, so it runs before AgentOS auth."""

    def __init__(self, app: ASGIApp, grants: GrantStore) -> None:
        self.app = app
        self.grants = grants

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "") if scope.get("type") == "http" else ""
        if path != CALLBACK_PREFIX and not path.startswith(CALLBACK_PREFIX + "/"):
            await self.app(scope, receive, send)
            return
        response = await self._handle(scope, receive, path)
        await response(scope, receive, send)

    async def _handle(self, scope: Scope, receive: Receive, path: str) -> Response:
        grant: RunGrant | None = self.grants.verify(_bearer(scope))
        if grant is None:
            return _unauthorized()
        method = scope.get("method", "GET")
        try:
            body = await _read_body(receive)
        except BodyTooLarge:
            return JSONResponse({"error": {"message": "Request body too large"}}, 413)
        if path == MCP_PATH:
            return await handle_mcp(grant, method, body)
        if path == f"{LLM_PREFIX}/models" and method == "GET":
            return JSONResponse(
                {"object": "list", "data": [{"id": MODEL_ALIAS, "object": "model", "owned_by": "agent"}]}
            )
        if path == f"{LLM_PREFIX}/chat/completions" and method == "POST":
            try:
                payload = json.loads(body or b"{}")
            except ValueError:
                return JSONResponse({"error": {"message": "Invalid JSON", "type": "invalid_request_error"}}, 400)
            if not isinstance(payload, dict):
                return JSONResponse({"error": {"message": "Expected an object", "type": "invalid_request_error"}}, 400)
            return await chat_completions(grant, payload)
        return JSONResponse({"error": {"message": "Not found"}}, 404)
