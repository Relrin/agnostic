"""The SSE wire format of an answer, live from the relay or replayed from the stored answer."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Mapping
from typing import Any

import orjson

from agnostic_assistant.application.ports import Relay
from agnostic_assistant.domain import events
from agnostic_assistant.domain.model import Message

HEARTBEAT = b": keepalive\n\n"


def frame(event_id: str, event_type: str, data: Mapping[str, Any]) -> bytes:
    body = orjson.dumps({"event": event_type, **data}, default=str).decode()
    return f"id: {event_id}\nevent: {event_type}\ndata: {body}\n\n".encode()


def snapshot(message: Message) -> list[bytes]:
    """A settled answer, told as the events a live stream would have sent."""
    frames = [frame(f"{message.id}-0", events.STARTED, {"model": message.model})]
    for index, call in enumerate(message.tool_calls, start=1):
        frames.append(frame(f"{message.id}-t{index}", events.TOOL_STARTED, {"id": call.id, "name": call.name}))
        frames.append(
            frame(
                f"{message.id}-c{index}",
                events.TOOL_COMPLETED,
                {
                    "id": call.id,
                    "name": call.name,
                    "status": call.status,
                    "duration_ms": call.duration_ms,
                    "detail": call.detail,
                },
            )
        )
    sources = [{"kind": s.kind, "label": s.label, "path": s.path} for s in message.sources]
    frames.append(frame(f"{message.id}-s", events.SOURCES, {"sources": sources}))
    if message.status == "completed":
        terminal = {
            "content": message.content,
            "model": message.model,
            "input_tokens": message.input_tokens,
            "output_tokens": message.output_tokens,
        }
        frames.append(frame(f"{message.id}-z", events.COMPLETED, terminal))
    elif message.status == "cancelled":
        frames.append(frame(f"{message.id}-z", events.CANCELLED, {"content": message.content}))
    else:
        frames.append(frame(f"{message.id}-z", events.FAILED, {"reason": message.error or "The answer failed."}))
    return frames


async def answer_events(
    message: Message, relay: Relay, *, last_event_id: str | None, heartbeat: float, max_seconds: float
) -> AsyncIterator[bytes]:
    if message.settled:
        for item in snapshot(message):
            yield item
        return
    deadline = time.monotonic() + max_seconds
    async for event in relay.follow(message.id, last_event_id, heartbeat):
        if event is None:
            yield HEARTBEAT
        else:
            yield frame(event.id, event.type, event.data)
            if event.type in events.TERMINAL:
                return
        if time.monotonic() > deadline:
            return
