"""The mock model is deterministic and calls tools only when asked to."""

import json

import pytest
from agno.models.message import Message
from agno.models.response import ModelResponse

from app.models.mock import MockModel

REFUND_TOOL = [{"type": "function", "function": {"name": "refund_customer", "parameters": {}}}]


def test_same_input_same_output() -> None:
    model = MockModel(persona="support-triage")
    messages = [Message(role="user", content="where is my order?")]
    first = model.invoke(messages=messages)
    assert first.content == model.invoke(messages=messages).content
    assert str(first.content).startswith("[support-triage] ")


def test_refund_triggers_tool_call_with_parsed_arguments() -> None:
    response = MockModel().invoke(messages=[Message(role="user", content="refund 19.99 to cus_42")], tools=REFUND_TOOL)
    call = response.tool_calls[0]["function"]
    assert call["name"] == "refund_customer"
    assert json.loads(call["arguments"]) == {"customer_id": "cus_42", "amount": 19.99, "reason": "requested in chat"}


def test_no_tool_call_when_tool_is_not_attached() -> None:
    response = MockModel().invoke(messages=[Message(role="user", content="refund please")], tools=[])
    assert not response.tool_calls


def test_tool_result_is_summarised() -> None:
    messages = [Message(role="user", content="refund"), Message(role="tool", content="Refunded 42.00 to cus_demo.")]
    assert MockModel().invoke(messages=messages).content == "Done. Refunded 42.00 to cus_demo."


def test_streaming_reassembles_the_reply() -> None:
    model = MockModel()
    messages = [Message(role="user", content="hello")]
    streamed = "".join(str(chunk.content) for chunk in model.invoke_stream(messages=messages))
    assert streamed == model.invoke(messages=messages).content


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("order 4471, refund 49", 49.0),
        ("please refund 19.99 to cus_42", 19.99),
        ("refund of $12.50 for ord_7", 12.5),
        ("$25 refund for order 4471", 25.0),
        ("refund cus_42 19.99", 19.99),  # ids like cus_42 never count as amounts
        ("refund please", 42.0),
    ],
)
def test_refund_amount_prefers_the_number_after_refund_or_dollar(text: str, amount: float) -> None:
    response = MockModel().invoke(messages=[Message(role="user", content=text)], tools=REFUND_TOOL)
    assert json.loads(response.tool_calls[0]["function"]["arguments"])["amount"] == amount


TASK_TOOLS = [
    {"type": "function", "function": {"name": name}} for name in ("create_task", "execute_task", "mark_all_complete")
]
MEMBERS = (
    '<team_members>\n<member id="kb-researcher" name="kb-researcher">\n</member>\n<member id="summarizer">\n</member>'
)


def _calls(response: ModelResponse) -> list[tuple[str, dict[str, object]]]:
    return [(c["function"]["name"], json.loads(c["function"]["arguments"])) for c in response.tool_calls]


def test_tasks_leader_creates_executes_then_completes() -> None:
    model = MockModel(persona="onboarding-team")
    messages = [Message(role="system", content=MEMBERS), Message(role="user", content="onboard Acme")]

    created = _calls(model.invoke(messages=messages, tools=TASK_TOOLS))
    assert [(name, args["assignee"]) for name, args in created] == [
        ("create_task", "kb-researcher"),
        ("create_task", "summarizer"),
    ]
    messages += [
        Message(role="tool", tool_name="create_task", content="Task created: [t1] kb-researcher: onboard Acme"),
        Message(role="tool", tool_name="create_task", content="Task created: [t2] summarizer: onboard Acme"),
    ]
    assert _calls(model.invoke(messages=messages, tools=TASK_TOOLS)) == [
        ("execute_task", {"task_id": "t1", "member_id": "kb-researcher"})
    ]
    messages.append(Message(role="tool", tool_name="execute_task", content="kb done"))
    assert _calls(model.invoke(messages=messages, tools=TASK_TOOLS)) == [
        ("execute_task", {"task_id": "t2", "member_id": "summarizer"})
    ]
    messages.append(Message(role="tool", tool_name="execute_task", content="brief done"))
    assert _calls(model.invoke(messages=messages, tools=TASK_TOOLS))[0][0] == "mark_all_complete"
    messages.append(Message(role="tool", tool_name="mark_all_complete", content="Goal marked as complete."))
    final = model.invoke(messages=messages, tools=TASK_TOOLS)
    assert not final.tool_calls
    assert final.content == "Done. Goal marked as complete."
