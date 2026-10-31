"""The mock model is deterministic and calls tools only when asked to."""

import json

from agno.models.message import Message

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
