"""The coding agent's Agno tools, served to its sandbox as a Model Context Protocol server.

Both harnesses connect to it as a remote (streamable HTTP) MCP server. It is stateless: every request is one JSON-RPC
message or batch answered with ``application/json``, which the transport allows, so no session id or event stream
is kept. Only the agent's own tools are listed, and tools that need a person (confirmation, user input, external
execution, approvals) are left out: nobody is there to answer inside a sandboxed turn.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Iterable
from typing import Any

from agno.tools.function import Function, FunctionCall
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_warning
from starlette.responses import JSONResponse, Response

from agnostic_bridge.coding._grants import RunGrant

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "agnostic-tools", "version": "1"}
MAX_RESULT_CHARS = 200_000
TOOL_TIMEOUT_S = 120.0

_NAME = re.compile(r"[^A-Za-z0-9_-]")


def _needs_a_person(function: Function) -> bool:
    return bool(
        function.requires_confirmation
        or function.requires_user_input
        or function.external_execution
        or getattr(function, "approval_type", None)
    )


def _safe_name(name: str) -> str:
    return _NAME.sub("_", name)[:64] or "tool"


async def _connect(toolkit: Toolkit) -> None:
    connect = getattr(toolkit, "connect", None)
    if connect is None or not toolkit.requires_connect:
        return
    result = connect()
    if inspect.isawaitable(result):
        await result


async def flatten_tools(tools: Iterable[Any] | None) -> dict[str, Function]:
    """The callable functions behind an agent's ``tools``, keyed by the name the sandbox sees."""
    flat: dict[str, Function] = {}

    def add(function: Function) -> None:
        if _needs_a_person(function):
            return
        copy = function.model_copy(deep=True)
        try:
            copy.process_entrypoint()
        except Exception as error:
            log_warning(f"Coding tools: skipping {function.name}: {error}")
            return
        name = _safe_name(copy.name)
        if name not in flat:
            flat[name] = copy

    for tool in tools or []:
        if isinstance(tool, Toolkit):
            try:
                await _connect(tool)
            except Exception as error:
                log_warning(f"Coding tools: cannot connect {tool.name}: {error}")
                continue
            for function in tool.get_async_functions().values():
                add(function)
        elif isinstance(tool, Function):
            add(tool)
        elif callable(tool):
            try:
                add(Function.from_callable(tool))
            except Exception as error:
                log_warning(f"Coding tools: skipping {getattr(tool, '__name__', tool)!r}: {error}")
    return flat


def _tool_entry(name: str, function: Function) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": name,
        "inputSchema": function.parameters or {"type": "object", "properties": {}},
    }
    if function.description:
        entry["description"] = function.description
    return entry


def _result_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        content = getattr(value, "content", None)
        if isinstance(content, str):
            text = content
        else:
            try:
                text = json.dumps(value, default=str)
            except (TypeError, ValueError):
                text = str(value)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "\n[truncated]"


async def call_tool(grant: RunGrant, name: str, arguments: Any) -> dict[str, Any]:
    function = grant.functions.get(name)
    if function is None:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
    call = FunctionCall(
        function=function.model_copy(), arguments=arguments if isinstance(arguments, dict) else {}, call_id=None
    )
    try:
        outcome = await asyncio.wait_for(call.aexecute(), TOOL_TIMEOUT_S)
    except asyncio.TimeoutError:
        return {"content": [{"type": "text", "text": f"{name} timed out"}], "isError": True}
    except Exception as error:
        return {"content": [{"type": "text", "text": f"{name} failed: {error}"}], "isError": True}
    if outcome.status != "success":
        return {"content": [{"type": "text", "text": outcome.error or call.error or "failed"}], "isError": True}
    return {"content": [{"type": "text", "text": _result_text(call.result)}], "isError": False}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def _answer(grant: RunGrant, message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request")
    method = message["method"]
    request_id = message.get("id")
    if "id" not in message:  # a notification: nothing to answer
        return None
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        result: dict[str, Any] = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": "Tools of the Agnostic agent this sandbox runs for.",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [_tool_entry(name, function) for name, function in grant.functions.items()]}
    elif method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            return _error(request_id, -32602, "tools/call needs a tool name")
        result = await call_tool(grant, name, params.get("arguments"))
    else:
        return _error(request_id, -32601, f"Method not found: {method}")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def handle_mcp(grant: RunGrant, method: str, body: bytes) -> Response:
    if method != "POST":
        # No server-initiated stream and no sessions to end.
        return Response(status_code=405, headers={"Allow": "POST"})
    try:
        payload = json.loads(body or b"null")
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    if isinstance(payload, list):
        answers = [answer for answer in [await _answer(grant, item) for item in payload] if answer is not None]
        return JSONResponse(answers) if answers else Response(status_code=202)
    answer = await _answer(grant, payload)
    return JSONResponse(answer) if answer is not None else Response(status_code=202)
