"""A deterministic agno model for assistant tests: it calls the tools a script names, then writes an answer.

Each tool in the script is called once, in order, if the agent offers it (tools the asking person can't use are
never offered, so the script skips them). The answer is a function of the tool results and the system prompt, so a
test can assert both what the model was told and what it saw.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse

from agnostic_assistant.application.ports import Connection
from agnostic_assistant.infrastructure.models import ModelFactory


@dataclass(frozen=True)
class Seen:
    """What the model was given when it wrote the answer."""

    system: str
    question: str
    results: Mapping[str, str]
    """Tool name → the quoted result it returned."""
    images: int = 0


@dataclass(frozen=True)
class Call:
    tool: str
    arguments: Mapping[str, Any] | Callable[[Seen], Mapping[str, Any]] = field(default_factory=dict[str, Any])


@dataclass
class Script:
    calls: Sequence[Call] = ()
    answer: Callable[[Seen], str] = lambda seen: "ready"
    seen: list[Seen] = field(default_factory=list[Seen])


def _offered(tools: list[dict[str, Any]] | None) -> set[str]:
    names: set[str] = set()
    for tool in tools or []:
        nested: Any = tool.get("function")
        function: dict[str, Any] = nested if isinstance(nested, dict) else tool
        if name := function.get("name"):
            names.add(str(name))
    return names


@dataclass
class ScriptedModel(Model):
    id: str = "scripted"
    name: str | None = "ScriptedModel"
    provider: str | None = "Test"
    script: Script = field(default_factory=Script)

    def _respond(self, messages: list[Message], tools: list[dict[str, Any]] | None) -> ModelResponse:
        system = "\n".join(m.get_content_string() for m in messages if m.role == "system")
        user = next((m for m in reversed(messages) if m.role == "user"), None)
        results = {str(m.tool_name): m.get_content_string() for m in messages if m.role == "tool"}
        seen = Seen(system, user.get_content_string() if user else "", results, len(user.images or []) if user else 0)
        offered = _offered(tools)
        for index, call in enumerate(self.script.calls):
            if call.tool in offered and call.tool not in results:
                arguments = call.arguments(seen) if callable(call.arguments) else call.arguments
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": f"call_{index}",
                            "type": "function",
                            "function": {"name": call.tool, "arguments": json.dumps(dict(arguments))},
                        }
                    ],
                )
        self.script.seen.append(seen)
        return ModelResponse(role="assistant", content=self.script.answer(seen))

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._respond(kwargs.get("messages", []), kwargs.get("tools"))

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        response = self.invoke(*args, **kwargs)
        if response.tool_calls or not isinstance(response.content, str):
            yield response
            return
        for index, word in enumerate(response.content.split(" ")):
            yield ModelResponse(role="assistant", content=word if index == 0 else f" {word}")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        for chunk in self.invoke_stream(*args, **kwargs):
            yield chunk

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


@dataclass
class ScriptedModels(ModelFactory):
    """Hands every agent the current script and remembers what it was asked to build."""

    script: Script = field(default_factory=Script)
    built: list[tuple[str, Connection]] = field(default_factory=list[tuple[str, Connection]])
    real: bool = False
    """Build the configured model instead (the Q&A eval suite runs against a real one)."""

    def build(self, model: str, connection: Connection) -> Model:
        self.built.append((model, connection))
        if self.real:
            return super().build(model, connection)
        return ScriptedModel(script=self.script)
