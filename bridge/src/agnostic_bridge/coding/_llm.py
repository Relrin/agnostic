"""An OpenAI-compatible chat completions endpoint backed by the coding agent's own Agno model.

The harness in the sandbox speaks the OpenAI chat completions dialect to this endpoint; each request becomes exactly
one call to the agent's :class:`agno.models.base.Model` (``aprocess_response_stream``, which runs no tools). The
harness executes the tool calls the model asks for itself, inside its sandbox. Whatever ``model`` or sampling options
the client sends are ignored: a run gets the model its agent was configured with.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from agno.media import Image
from agno.metrics import MessageMetrics
from agno.models.base import MessageData
from agno.models.message import Message
from agno.utils.log import log_warning
from starlette.responses import JSONResponse, Response, StreamingResponse

from agnostic_bridge.coding._grants import GrantExhausted, RunGrant

MODEL_ALIAS = "agent-model"
"""The model id harnesses are configured with; the real one is the agent's."""

_ROLES = {"system": "system", "developer": "system", "user": "user", "assistant": "assistant", "tool": "tool"}


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        return "".join(str(part) for part in parts)
    return str(content)


def _images(content: Any) -> list[Image]:
    if not isinstance(content, list):
        return []
    images: list[Image] = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "image_url":
            continue
        url = (part.get("image_url") or {}).get("url") if isinstance(part.get("image_url"), dict) else None
        if not isinstance(url, str):
            continue
        if url.startswith("data:") and ";base64," in url:
            header, data = url.split(";base64,", 1)
            try:
                images.append(Image(content=base64.b64decode(data), mime_type=header[5:] or None))
            except ValueError:
                continue
        elif url.startswith(("http://", "https://")):
            images.append(Image(url=url))
    return images


def openai_to_agno(messages: list[dict[str, Any]]) -> list[Message]:
    """OpenAI chat messages as Agno messages: roles mapped, text parts joined, tool calls and results kept."""
    converted: list[Message] = []
    names: dict[str, str] = {}
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        role = _ROLES.get(str(raw.get("role")))
        if role is None:
            continue
        content = raw.get("content")
        if role == "assistant":
            calls = [call for call in raw.get("tool_calls") or [] if isinstance(call, dict)]
            for call in calls:
                function = call.get("function") or {}
                if call.get("id") and function.get("name"):
                    names[str(call["id"])] = str(function["name"])
            converted.append(Message(role="assistant", content=_text(content) or None, tool_calls=calls or None))
        elif role == "tool":
            call_id = str(raw.get("tool_call_id") or "")
            converted.append(
                Message(role="tool", content=_text(content), tool_call_id=call_id, tool_name=names.get(call_id))
            )
        else:
            images = _images(content) if role == "user" else []
            converted.append(Message(role=role, content=_text(content), images=images or None))
    return converted


def openai_tools(tools: Any) -> list[dict[str, Any]] | None:
    """Function tools in the shape Agno models accept (their own tool dicts are OpenAI-shaped)."""
    if not isinstance(tools, list):
        return None
    kept: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type", "function") != "function":
            continue
        function = tool.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            continue
        entry: dict[str, Any] = {"name": function["name"]}
        if isinstance(function.get("description"), str):
            entry["description"] = function["description"]
        entry["parameters"] = function.get("parameters") or {"type": "object", "properties": {}}
        kept.append({"type": "function", "function": entry})
    return kept or None


def _tool_choice(value: Any) -> str | dict[str, Any] | None:
    if value in ("auto", "none", "required"):
        return value
    if isinstance(value, dict) and value.get("type") == "function":
        return value
    return None


def _usage(metrics: MessageMetrics | None) -> dict[str, int]:
    prompt = int(getattr(metrics, "input_tokens", 0) or 0)
    completion = int(getattr(metrics, "output_tokens", 0) or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


def _chunk(completion_id: str, created: int, delta: dict[str, Any], finish: str | None = None) -> str:
    body = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": MODEL_ALIAS,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(body, separators=(',', ':'))}\n\n"


def _wire_calls(calls: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    wire: list[dict[str, Any]] = []
    for index, call in enumerate(calls or []):
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        wire.append(
            {
                "index": index,
                "id": call.get("id") or f"call_{uuid4().hex[:24]}",
                "type": "function",
                "function": {"name": function.get("name") or "", "arguments": arguments},
            }
        )
    return wire


async def _deltas(grant: RunGrant, body: dict[str, Any]) -> AsyncIterator[tuple[str, Any]]:
    """("content" | "reasoning", text) while the model streams, then ("done", assistant message)."""
    model = grant.model
    messages = openai_to_agno(body.get("messages") or [])
    assistant = Message(role="assistant")
    model._ensure_message_metrics_initialized(assistant)
    stream_data = MessageData()
    stream_data.response_metrics = MessageMetrics()
    stream_data.response_metrics.start_timer()
    async for delta in model.aprocess_response_stream(
        messages=messages,
        assistant_message=assistant,
        stream_data=stream_data,
        tools=openai_tools(body.get("tools")),
        tool_choice=_tool_choice(body.get("tool_choice")),
    ):
        if delta.reasoning_content:
            yield "reasoning", delta.reasoning_content
        if delta.content:
            yield "content", delta.content if isinstance(delta.content, str) else str(delta.content)
    grant.add_usage(assistant.metrics)
    yield "done", assistant


def _error_body(message: str, kind: str = "server_error") -> dict[str, Any]:
    return {"error": {"message": message, "type": kind}}


async def chat_completions(grant: RunGrant, body: dict[str, Any]) -> Response:
    """Answer one chat completions request with the grant's model, streamed when the client asks for it."""
    if not isinstance(body.get("messages"), list):
        return JSONResponse(_error_body("messages must be a list", "invalid_request_error"), status_code=400)
    try:
        grant.count_request()
    except GrantExhausted as error:
        return JSONResponse(_error_body(str(error), "rate_limit_error"), status_code=429)

    completion_id = f"chatcmpl-{uuid4().hex[:24]}"
    created = int(time.time())

    if not body.get("stream"):
        content, reasoning = "", ""
        assistant: Message | None = None
        try:
            async for kind, value in _deltas(grant, body):
                if kind == "content":
                    content += value
                elif kind == "reasoning":
                    reasoning += value
                else:
                    assistant = value
        except Exception as error:
            log_warning(f"Coding model proxy: run {grant.run_id} failed: {error}")
            return JSONResponse(_error_body(f"The model call failed: {error}"), status_code=502)
        calls = _wire_calls(assistant.tool_calls if assistant else None)
        message: dict[str, Any] = {"role": "assistant", "content": content or None}
        if reasoning:
            message["reasoning_content"] = reasoning
        if calls:
            message["tool_calls"] = [{key: value for key, value in call.items() if key != "index"} for call in calls]
        return JSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": MODEL_ALIAS,
                "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
                "usage": _usage(assistant.metrics if assistant else None),
            }
        )

    include_usage = bool((body.get("stream_options") or {}).get("include_usage"))

    async def events() -> AsyncIterator[str]:
        yield _chunk(completion_id, created, {"role": "assistant", "content": ""})
        assistant: Message | None = None
        try:
            async for kind, value in _deltas(grant, body):
                if kind == "content":
                    yield _chunk(completion_id, created, {"content": value})
                elif kind == "reasoning":
                    yield _chunk(completion_id, created, {"reasoning_content": value})
                else:
                    assistant = value
        except Exception as error:
            log_warning(f"Coding model proxy: run {grant.run_id} failed: {error}")
            yield f"data: {json.dumps(_error_body(f'The model call failed: {error}'))}\n\n"
            yield "data: [DONE]\n\n"
            return
        calls = _wire_calls(assistant.tool_calls if assistant else None)
        if calls:
            yield _chunk(completion_id, created, {"tool_calls": calls})
        yield _chunk(completion_id, created, {}, "tool_calls" if calls else "stop")
        if include_usage:
            usage = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": MODEL_ALIAS,
                "choices": [],
                "usage": _usage(assistant.metrics if assistant else None),
            }
            yield f"data: {json.dumps(usage, separators=(',', ':'))}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
