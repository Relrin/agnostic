"""What an answer stream says while it is being written, in order."""

from __future__ import annotations

STARTED = "answer.started"
"""``{model}``: the worker picked the question up."""
TOOL_STARTED = "answer.tool_started"
"""``{id, name}``"""
TOOL_COMPLETED = "answer.tool_completed"
"""``{id, name, status, duration_ms, detail}``"""
CONTENT = "answer.content"
"""``{delta}``: the next piece of text."""
SOURCES = "answer.sources"
"""``{sources: [{kind, label, path}]}``: the pages the answer used."""
COMPLETED = "answer.completed"
"""``{content, input_tokens, output_tokens}``"""
FAILED = "answer.failed"
"""``{reason}``"""
CANCELLED = "answer.cancelled"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})


def channel(message_id: str) -> str:
    return f"evt:assistant:{message_id}"
