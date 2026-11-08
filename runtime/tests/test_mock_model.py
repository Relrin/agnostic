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


def test_reports_token_usage_like_a_provider() -> None:
    model = MockModel(stream_delay=0)
    messages = [Message(role="system", content="x" * 400), Message(role="user", content="hello")]
    usage = model.invoke(messages=messages).response_usage
    assert usage is not None
    assert usage.input_tokens > 100
    assert usage.total_tokens == usage.input_tokens + usage.output_tokens
    chunks = list(model.invoke_stream(messages=messages))
    assert [chunk.response_usage is not None for chunk in chunks].count(True) == 1
    assert chunks[-1].response_usage == usage


def test_a_long_answer_is_markdown() -> None:
    content = str(MockModel().invoke(messages=[Message(role="user", content="give me a long answer")]).content)
    assert content.startswith("## ")
    assert "```python" in content


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


PI_TOOLS = [
    {"type": "function", "function": {"name": "write", "parameters": {"properties": {"path": {}, "content": {}}}}},
    {"type": "function", "function": {"name": "bash", "parameters": {"properties": {"command": {}}}}},
]
OPENCODE_TOOLS = [
    {
        "type": "function",
        "function": {"name": "write", "parameters": {"properties": {"filePath": {}, "content": {}}}},
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "parameters": {
                "properties": {"command": {}, "description": {"type": "string"}},
                "required": ["command", "description"],
            },
        },
    },
]


@pytest.mark.parametrize(("tools", "path_key"), [(PI_TOOLS, "path"), (OPENCODE_TOOLS, "filePath")])
def test_coder_writes_lists_then_summarises(tools: list, path_key: str) -> None:
    model = MockModel(persona="coder")
    user = Message(role="user", content="write a hello file")

    first = model.invoke(messages=[user], tools=tools)
    write = first.tool_calls[0]["function"]
    assert write["name"] == "write" and json.loads(write["arguments"])[path_key] == "outputs/hello.md"
    assert first.reasoning_content

    after_write = [user, Message(role="assistant", tool_calls=first.tool_calls), Message(role="tool", content="ok")]
    second = model.invoke(messages=after_write, tools=tools)
    bash = json.loads(second.tool_calls[0]["function"]["arguments"])
    assert bash["command"] == "ls -la outputs"
    if path_key == "filePath":
        assert bash["description"]  # required fields are filled in, as a model would

    done = model.invoke(messages=[*after_write, Message(role="tool", content="hello.md")], tools=tools)
    assert "outputs/hello.md" in str(done.content) and not done.tool_calls


def test_coder_streams_its_reasoning_first() -> None:
    chunks = list(
        MockModel(persona="coder").invoke_stream(messages=[Message(role="user", content="x")], tools=PI_TOOLS)
    )
    assert chunks[0].reasoning_content and chunks[-1].tool_calls


PI_FIX_TOOLS = [
    *PI_TOOLS,
    {"type": "function", "function": {"name": "edit", "parameters": {"properties": {"path": {}, "edits": {}}}}},
]
OPENCODE_FIX_TOOLS = [
    *OPENCODE_TOOLS,
    {
        "type": "function",
        "function": {"name": "edit", "parameters": {"properties": {"filePath": {}, "oldString": {}, "newString": {}}}},
    },
]


def _run_script(model: MockModel, request: str, tools: list) -> list[ModelResponse]:
    """Play a scripted run to its answer, feeding back one tool result per call."""
    messages = [Message(role="user", content=request)]
    replies: list[ModelResponse] = []
    while len(replies) < 10:
        reply = model.invoke(messages=messages, tools=tools)
        replies.append(reply)
        if not reply.tool_calls:
            return replies
        messages.append(Message(role="assistant", tool_calls=reply.tool_calls))
        messages.extend(Message(role="tool", content="ok") for _ in reply.tool_calls)
    raise AssertionError("the script never answered")


@pytest.mark.parametrize("tools", [PI_FIX_TOOLS, OPENCODE_FIX_TOOLS])
def test_coder_fixes_a_bug_test_first(tools: list) -> None:
    from app.models import scenarios

    replies = _run_script(MockModel(persona="coder"), "Please fix this invoice bug", tools)
    names = [[call["function"]["name"] for call in reply.tool_calls or []] for reply in replies]
    assert names == [["write", "write"], ["bash"], ["edit"], ["bash"], []]
    assert replies[0].reasoning_content and replies[2].reasoning_content

    edit = json.loads(replies[2].tool_calls[0]["function"]["arguments"])
    old, new = (
        (edit["edits"][0]["oldText"], edit["edits"][0]["newText"])
        if "edits" in edit
        else (edit["oldString"], edit["newString"])
    )
    assert old in scenarios.INVOICE_BUGGY and new == scenarios.INVOICE_FIXED_LINE
    assert "outputs/" in json.loads(replies[3].tool_calls[0]["function"]["arguments"])["command"]
    assert "applied twice" in str(replies[-1].content)


def test_the_scripted_fix_is_right() -> None:
    from app.models import scenarios

    namespace: dict[str, object] = {}
    exec(scenarios.INVOICE_BUGGY, namespace)
    items = [{"price": 50.0, "qty": 2}]
    assert namespace["invoice_total"](items, discount_pct=10, tax_pct=20) == 98.0  # type: ignore[operator]
    exec(scenarios.INVOICE_BUGGY.replace(scenarios.INVOICE_BUGGY_LINE, scenarios.INVOICE_FIXED_LINE), namespace)
    assert namespace["invoice_total"](items, discount_pct=10, tax_pct=20) == 108.0  # type: ignore[operator]


def test_a_plain_coding_request_still_writes_hello() -> None:
    first = MockModel(persona="coder").invoke(
        messages=[Message(role="user", content="write a note")], tools=PI_FIX_TOOLS
    )
    assert json.loads(first.tool_calls[0]["function"]["arguments"])["path"] == "outputs/hello.md"


def test_web_researcher_searches_then_cites() -> None:
    from app.models import scenarios

    tools = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
    replies = _run_script(MockModel(persona="web-researcher"), "Research pgvector index types", tools)
    queries = [json.loads(call["function"]["arguments"])["query"] for call in replies[0].tool_calls or []]
    assert queries == list(scenarios.RESEARCH_QUERIES)
    assert len(replies) == 2 and scenarios.PGVECTOR_README in str(replies[1].content)


def test_web_search_answers_the_research_queries() -> None:
    from app.models import scenarios
    from app.tools import web_search

    entrypoint = web_search.entrypoint
    assert entrypoint is not None
    for query in scenarios.RESEARCH_QUERIES:
        assert "pgvector README" in entrypoint(query=query)
