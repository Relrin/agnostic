"""Read-only tools that modules contribute to the assistant, independent of any agent framework.

A module returns :class:`ToolSpec` objects from ``assistant_tools()``. The ``assistant`` module adapts them to its agent
framework, offers only the tools the asking person may use, and runs them **as that person**: a handler calls the
gateway or the module's own use cases with ``call.principal``, so every scope check still applies.

Handlers never write. They return compact JSON plus the in-app pages the data came from (:class:`Source`), which the
assistant lists under its answer. Fields that carry tool arguments or a person's messages use the keys in
:data:`TOOL_ARG_KEYS` and :data:`USER_MESSAGE_KEYS`, so an org's redaction settings strip them in one place.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from dishka import AsyncContainer
from pydantic import BaseModel

from agnostic_kernel.auth import Principal

REDACTED = "[redacted]"
TOOL_ARG_KEYS = frozenset({"tool_args"})
"""Keys whose values are arguments a runtime passed to a tool (span inputs, tool calls in runs)."""
USER_MESSAGE_KEYS = frozenset({"user_message"})
"""Keys whose values are what a person typed (run inputs, session messages)."""


class NoArguments(BaseModel):
    """Arguments of a tool that takes none."""


@dataclass(frozen=True, slots=True)
class Source:
    """A page the data came from, e.g. ``Source("trace", "Trace 8f3a…", "/i/prod/traces?trace_id=8f3a…")``."""

    kind: str
    label: str
    path: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    principal: Principal
    """The person asking; the handler acts as them."""
    instance_id: str
    """The instance the question is about. Tools never reach other instances."""
    instance_slug: str
    arguments: BaseModel


@dataclass(frozen=True, slots=True)
class ToolResult:
    data: Any
    """JSON-serialisable, kept small: the model reads all of it."""
    sources: Sequence[Source] = field(default_factory=tuple[Source, ...])


type ToolHandler = Callable[[AsyncContainer, ToolCall], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A read-only tool, e.g. ``get_trace``.

    ``scope`` is the scope the person needs for the tool to be offered at all: on the instance (``traces:read``)
    or, with ``org_scope``, on the control plane (``audit:read``). ``None`` means the handler checks on its own.
    ``arguments`` is a pydantic model: its JSON schema is what the model sees and its validation runs before the
    handler.
    """

    name: str
    description: str
    handler: ToolHandler
    arguments: type[BaseModel] = NoArguments
    scope: str | None = None
    org_scope: bool = False


@dataclass(frozen=True, slots=True)
class Redaction:
    """What an org strips from tool results before a model sees them."""

    tool_args: bool = False
    user_messages: bool = False

    def apply(self, value: Any) -> Any:  # noqa: ANN401
        keys: set[str] = set()
        if self.tool_args:
            keys |= TOOL_ARG_KEYS
        if self.user_messages:
            keys |= USER_MESSAGE_KEYS
        return strip_keys(value, frozenset(keys)) if keys else value


def clip(value: object, limit: int = 400) -> str | None:
    """``value`` as text of at most ``limit`` characters, ``None`` stays ``None``."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def strip_keys(value: Any, keys: frozenset[str]) -> Any:  # noqa: ANN401
    """``value`` with every ``keys`` entry (at any depth) replaced by :data:`REDACTED`."""
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, Any]", value)
        return {k: REDACTED if k in keys else strip_keys(v, keys) for k, v in mapping.items()}
    if isinstance(value, list | tuple):
        items = cast("Sequence[Any]", value)
        return [strip_keys(item, keys) for item in items]
    return value
