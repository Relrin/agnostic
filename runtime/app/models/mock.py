"""A deterministic model so tests and demos never call a real LLM.

The same input always produces the same output. The model calls a tool when the latest user message names it
(for example "refund" triggers ``refund_customer`` when that tool is attached); after a tool result it replies
with a one-line summary of it. Everything else gets a canned, persona-specific answer.

As the leader of a ``TeamMode.tasks`` team it works the task list: one task per member, executed in member order,
then ``mark_all_complete``.

With ``persona="coder"`` it plays a coding harness's model: it thinks briefly, writes ``outputs/hello.md`` with the
harness's own ``write`` tool, lists the folder with ``bash`` and then summarises.
"""

import asyncio
import hashlib
import json
import re
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any, ClassVar

from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse

TOOL_TRIGGERS: dict[str, str] = {
    "refund": "refund_customer",
    "order": "lookup_order",
    "search": "search_knowledge",
    "web": "web_search",
    "report": "write_report",
}

TASK_TOOLS = {"create_task", "execute_task", "mark_all_complete"}
# A refund amount right after "refund" (optionally "of"/"for" and "$") or after "$"; then any standalone number.
REFUND_AMOUNT = re.compile(r"(?:\brefund(?:\s+(?:of|for))?\s+\$?|\$\s*)(\d+(?:\.\d{1,2})?)\b", re.IGNORECASE)
NUMBER = re.compile(r"\b(\d+(?:\.\d{1,2})?)\b")
MEMBER = re.compile(r'<member id="([^"]+)"')
TASK_ID = re.compile(r"^Task (?:created|already exists): \[([^\]]+)\]")

REASONING_STEPS = (
    "Reading the request and what came before it.",
    "Checking which tools could help.",
    "Weighing a short answer against a detailed one.",
    "Drafting the answer and checking it against the request.",
)

PHRASES = (
    "Here is what I found",
    "Short answer",
    "Summary",
    "Next step",
)


# Asking for a long or detailed answer gets a multi-paragraph Markdown reply (headings, a list, code), so long
# streamed output can be tried without a real model.
LONG_ANSWER_TRIGGER = re.compile(r"\b(long|detailed) answer\b", re.IGNORECASE)
LONG_ANSWER = """## How the {persona} handles a request

Every request goes through the same three stages. The model reads the conversation so far, decides whether it \
needs a tool, and then writes the answer you are reading now.

1. **Understand** the request and the context it arrives with.
2. **Act** by calling the tools attached to the agent, when the request needs data it does not have.
3. **Answer** in plain language, citing what the tools returned.

### An example

A refund request names an order and an amount. The agent looks the order up, checks the amount against the \
order total and asks for approval before money moves:

```python
order = lookup_order("ord_1001")
if amount <= order.total:
    refund_customer(order.customer_id, amount)
```

> Approvals keep a person in the loop for anything that cannot be undone.

That is all there is to it: read, act when needed, and answer clearly."""

# Rough size of text in tokens, about four characters each, like the tokenizers of the common providers.
CHARS_PER_TOKEN = 4


def _digest(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def _tokens(value: Any) -> int:
    if value is None:
        return 0
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return -(-len(text) // CHARS_PER_TOKEN)


def _usage(messages: list[Message], tools: list[dict[str, Any]] | None, response: ModelResponse) -> MessageMetrics:
    """Token counts a provider would report for this request: everything sent in, and the reply."""
    sent = sum(_tokens(message.get_content_string()) + _tokens(message.tool_calls) for message in messages)
    sent += _tokens(tools)
    written = _tokens(response.content) + _tokens(response.tool_calls) + _tokens(response.reasoning_content)
    return MessageMetrics(input_tokens=sent, output_tokens=written, total_tokens=sent + written)


def _configured_stream_delay() -> float:
    from app.settings import get_settings

    return max(0, get_settings().mock_stream_delay_ms) / 1000


def _tool_names(tools: list[dict[str, Any]] | None) -> set[str]:
    names: set[str] = set()
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        if name := function.get("name"):
            names.add(str(name))
    return names


def _arguments_for(tool: str, text: str) -> dict[str, Any]:
    if tool == "refund_customer":
        amount = REFUND_AMOUNT.search(text) or NUMBER.search(text)
        customer = re.search(r"\b(cus_[A-Za-z0-9]+)\b", text)
        return {
            "customer_id": customer.group(1) if customer else "cus_demo",
            "amount": float(amount.group(1)) if amount else 42.0,
            "reason": "requested in chat",
        }
    if tool == "lookup_order":
        order = re.search(r"\b(ord_[A-Za-z0-9]+)\b", text)
        return {"order_id": order.group(1) if order else "ord_1001"}
    return {"query": text[:120]}


def _tool_call(name: str, arguments: dict[str, Any], seed: str) -> dict[str, Any]:
    return {
        "id": f"call_{_digest(seed + name + json.dumps(arguments, sort_keys=True)):08x}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _tool_schemas(tools: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        if name := function.get("name"):
            schemas[str(name)] = function.get("parameters") or {}
    return schemas


def _pick(schema: dict[str, Any], *candidates: str) -> str:
    properties = schema.get("properties") or {}
    return next((name for name in candidates if name in properties), candidates[0])


def _fill_required(schema: dict[str, Any], arguments: dict[str, Any], note: str) -> dict[str, Any]:
    """Give every other required string field a short value, as a model would."""
    properties = schema.get("properties") or {}
    for name in schema.get("required") or []:
        if name not in arguments and (properties.get(name) or {}).get("type", "string") == "string":
            arguments[name] = note
    return arguments


CODER_REASONING = "The request is about files, so I will write the result under outputs/ and then check it."


def _coder_step(messages: list[Message], tools: list[dict[str, Any]] | None, user_text: str) -> ModelResponse:
    """A coding harness's turn without a real model: write a file, list the folder, then summarise.

    The tool names and argument names come from the tools the harness offers (Pi: ``write(path, content)``,
    OpenCode: ``write(filePath, content)``), so the same persona drives either.
    """
    schemas = _tool_schemas(tools)
    last_user = max((index for index, message in enumerate(messages) if message.role == "user"), default=-1)
    results = [message for message in messages[last_user + 1 :] if message.role == "tool"]
    brief = " ".join(user_text.split())[:120] or "(no request)"
    if not results and "write" in schemas:
        schema = schemas["write"]
        arguments = {
            _pick(schema, "path", "filePath", "file_path"): "outputs/hello.md",
            _pick(schema, "content", "text"): f"# Hello from the sandbox\n\nRequest: {brief}\n",
        }
        call = _tool_call("write", _fill_required(schema, arguments, "Write outputs/hello.md"), user_text)
        return ModelResponse(role="assistant", tool_calls=[call], reasoning_content=CODER_REASONING)
    if len(results) == 1 and "bash" in schemas:
        schema = schemas["bash"]
        arguments = {_pick(schema, "command", "cmd"): "ls -la outputs"}
        call = _tool_call("bash", _fill_required(schema, arguments, "List the outputs folder"), user_text + "ls")
        return ModelResponse(role="assistant", tool_calls=[call])
    return ModelResponse(
        role="assistant",
        content=f"I wrote `outputs/hello.md` with a short note about your request ({brief}) and checked the folder.",
    )


def _next_task_step(messages: list[Message], user_text: str) -> list[dict[str, Any]] | None:
    """The leader's next task-tool calls, or None once the goal is marked complete."""
    members = [m for msg in messages if msg.role == "system" for m in MEMBER.findall(msg.get_content_string())]
    results = [msg for msg in messages if msg.role == "tool"]
    if any(msg.tool_name == "mark_all_complete" for msg in results):
        return None
    created = [msg for msg in results if msg.tool_name == "create_task"]
    if not created:
        brief = " ".join(user_text.split())[:60]
        return [
            _tool_call("create_task", {"title": f"{member}: {brief}", "description": user_text, "assignee": member}, "")
            for member in members
        ]
    task_ids = [match.group(1) for msg in created if (match := TASK_ID.match(msg.get_content_string()))]
    executed = sum(1 for msg in results if msg.tool_name == "execute_task")
    if executed < len(task_ids):
        member = members[executed] if executed < len(members) else members[-1]
        return [_tool_call("execute_task", {"task_id": task_ids[executed], "member_id": member}, user_text)]
    summary = f"Completed {len(task_ids)} task(s) for: {' '.join(user_text.split())[:80]}"
    return [_tool_call("mark_all_complete", {"summary": summary}, user_text)]


@dataclass
class MockModel(Model):
    id: str = "agnostic-mock"
    name: str = "MockModel"
    provider: str = "Agnostic"
    persona: str = "assistant"
    # Sampling setting a real model would take, so presets can differ by it; the mock ignores it.
    temperature: float | None = None
    # How hard to "think": with a level set, each answer starts with a short reasoning trace that names it, so a
    # run's reasoning effort can be tried end to end without a real model.
    reasoning_effort: str | None = None
    # The levels agnostic-bridge offers for this model (``agnostic_bridge.reasoning``).
    reasoning_levels: ClassVar[tuple[str, ...]] = ("off", "low", "medium", "high")
    # Average pause between streamed words, in seconds (RUNTIME_MOCK_STREAM_DELAY_MS); 0 streams at once.
    stream_delay: float = field(default_factory=_configured_stream_delay)

    def _respond(self, messages: list[Message], tools: list[dict[str, Any]] | None) -> ModelResponse:
        user_text = next((m.get_content_string() for m in reversed(messages) if m.role == "user"), "")
        if self.persona == "coder":
            return _coder_step(messages, tools, user_text)
        available = _tool_names(tools)
        if available >= TASK_TOOLS and (calls := _next_task_step(messages, user_text)):
            return ModelResponse(role="assistant", tool_calls=calls)

        last = messages[-1] if messages else None
        if last is not None and last.role == "tool":
            result = last.get_content_string()
            return ModelResponse(role="assistant", content=f"Done. {result}".strip())

        lowered = user_text.lower()
        for trigger, tool in TOOL_TRIGGERS.items():
            if trigger in lowered and tool in available:
                call_id = f"call_{_digest(user_text + tool):08x}"
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": tool, "arguments": json.dumps(_arguments_for(tool, user_text))},
                        }
                    ],
                )

        if LONG_ANSWER_TRIGGER.search(user_text):
            return ModelResponse(role="assistant", content=LONG_ANSWER.format(persona=self.persona))

        phrase = PHRASES[_digest(user_text) % len(PHRASES)]
        echo = " ".join(user_text.split())[:80] or "(no input)"
        return ModelResponse(role="assistant", content=f"[{self.persona}] {phrase}: {echo}")

    def _thinking(self, messages: list[Message]) -> str | None:
        """A reasoning trace as long as the effort asks for; none when it is unset or off, or after a tool result."""
        if not self.reasoning_effort or self.reasoning_effort == "off":
            return None
        if messages and messages[-1].role == "tool":
            return None
        steps = REASONING_STEPS[: {"low": 1, "medium": 2, "high": 4}.get(self.reasoning_effort, 1)]
        return f"Thinking at {self.reasoning_effort} effort. " + " ".join(steps)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        messages = kwargs.get("messages", [])
        tools = kwargs.get("tools")
        response = self._respond(messages, tools)
        thinking = self._thinking(messages)
        if thinking and not response.reasoning_content:
            response.reasoning_content = thinking
        response.response_usage = _usage(messages, tools, response)
        return response

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def _chunks(self, *args: Any, **kwargs: Any) -> Iterator[tuple[ModelResponse, float]]:
        """The reply word by word, each with the pause before it; the last chunk carries the usage."""
        response = self.invoke(*args, **kwargs)
        usage = response.response_usage
        response.response_usage = None
        if response.reasoning_content:
            for index, word in enumerate(response.reasoning_content.split(" ")):
                chunk = ModelResponse(role="assistant", reasoning_content=word if index == 0 else f" {word}")
                yield chunk, self._pause(word, index)
            response.reasoning_content = None
        if response.tool_calls or not isinstance(response.content, str):
            response.response_usage = usage
            yield response, self.stream_delay
            return
        words = response.content.split(" ")
        for index, word in enumerate(words):
            chunk = ModelResponse(role="assistant", content=word if index == 0 else f" {word}")
            if index == len(words) - 1:
                chunk.response_usage = usage
            yield chunk, self._pause(word, index)

    def _pause(self, word: str, index: int) -> float:
        """Uneven gaps between words, the way a provider's stream arrives: mostly quick, now and then a stall."""
        if self.stream_delay <= 0:
            return 0.0
        spread = _digest(f"{word}{index}") % 10
        return self.stream_delay * (6 if spread == 0 else 0.3 + spread / 6)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        for chunk, pause in self._chunks(*args, **kwargs):
            if pause:
                time.sleep(pause)
            yield chunk

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        for chunk, pause in self._chunks(*args, **kwargs):
            if pause:
                await asyncio.sleep(pause)
            yield chunk

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response
