"""A deterministic model so tests and demos never call a real LLM.

The same input always produces the same output. The model calls a tool when the latest user message names it
(for example "refund" triggers ``refund_customer`` when that tool is attached); after a tool result it replies
with a one-line summary of it. Everything else gets a canned, persona-specific answer.

As the leader of a ``TeamMode.tasks`` team it works the task list: one task per member, executed in member order,
then ``mark_all_complete``.
"""

import hashlib
import json
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

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

PHRASES = (
    "Here is what I found",
    "Short answer",
    "Summary",
    "Next step",
)


def _digest(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


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

    def _respond(self, messages: list[Message], tools: list[dict[str, Any]] | None) -> ModelResponse:
        user_text = next((m.get_content_string() for m in reversed(messages) if m.role == "user"), "")
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

        phrase = PHRASES[_digest(user_text) % len(PHRASES)]
        echo = " ".join(user_text.split())[:80] or "(no input)"
        return ModelResponse(role="assistant", content=f"[{self.persona}] {phrase}: {echo}")

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
