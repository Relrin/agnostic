"""``Agent.to_dict()`` as typed fields."""

from __future__ import annotations

from typing import ClassVar

from agnostic_spec.fields import meta_field
from agnostic_spec.v3_1.base import Kind, SharedConfig


class AgentConfig(SharedConfig):
    kind: ClassVar[Kind] = "agent"

    add_search_knowledge_instructions: bool | None = meta_field(
        "knowledge", "Explain the search tool in the instructions", widget="switch", default=False, order=8
    )
    read_tool_call_history: bool | None = meta_field(
        "context", "Tool to read past tool calls", widget="switch", default=False, order=10
    )
    structured_outputs: bool | None = meta_field("output", "Provider structured outputs", widget="switch", order=5)

    retries: int | None = meta_field("advanced", "Retries", widget="number", default=0, order=1)
    delay_between_retries: int | None = meta_field(
        "advanced", "Seconds between retries", widget="number", default=1, order=2
    )
    exponential_backoff: bool | None = meta_field(
        "advanced", "Exponential backoff", widget="switch", default=False, order=3
    )
    build_context: bool | None = meta_field(
        "advanced", "Build the system message", widget="switch", default=True, order=11
    )
    build_user_context: bool | None = meta_field(
        "advanced", "Build the user message", widget="switch", default=True, order=12
    )
    user_message_role: str | None = meta_field("advanced", "User message role", default="user", order=13)
    stream: bool | None = meta_field("advanced", "Stream responses", widget="switch", order=50)
    stream_events: bool | None = meta_field("advanced", "Stream intermediate events", widget="switch", order=51)
    store_events: bool | None = meta_field("advanced", "Store run events", widget="switch", default=False, order=52)
    cache_callables: bool | None = meta_field(
        "advanced", "Cache callable factories", widget="switch", default=True, order=60
    )
    debug_mode: bool | None = meta_field("advanced", "Debug mode", widget="switch", default=False, order=70)
    debug_level: int | None = meta_field("advanced", "Debug level", widget="number", default=1, order=71)
    telemetry: bool | None = meta_field("advanced", "Telemetry", widget="switch", default=True, order=72)
