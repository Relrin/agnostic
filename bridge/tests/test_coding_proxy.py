"""The sandbox callback routes: the model proxy, the tool server, and how run tokens get past AgentOS auth."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable

import pytest
from agno.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.os.authz import Authorization
from agno.tools import tool
from fastapi.testclient import TestClient

from agnostic_bridge import install
from agnostic_bridge.coding import CodingConfig
from agnostic_bridge.coding._grants import GrantStore
from agnostic_bridge.coding._llm import openai_to_agno
from agnostic_bridge.coding._mcp import flatten_tools
from agnostic_bridge.coding._runtime import coding_runtime
from tests.coding_support import ScriptedModel, sse_events
from tests.conftest import OS_ID, make_os

LLM = "/agnostic/v1/coding/llm/v1/chat/completions"
MCP = "/agnostic/v1/coding/mcp"


def lookup_order(order_id: str) -> str:
    """Look up an order's status."""
    return f"Order {order_id}: shipped"


@tool(requires_confirmation=True)
def refund(customer_id: str) -> str:
    """Refund a customer."""
    return "refunded"


@pytest.fixture
def secured_app(key_pair: tuple[str, str]) -> TestClient:
    authorization = Authorization(
        verification_keys=[key_pair[1]], algorithm="RS256", verify_audience=True, audience=OS_ID
    )
    app = install(
        make_os(authorization=authorization), coding=CodingConfig(callback_url="http://cb", materialize=False)
    )
    return TestClient(app)


def _grant(model: ScriptedModel, functions: dict | None = None, **limits: object) -> str:
    token, _ = coding_runtime().grants.mint(
        agent_id="a", session_id="s", run_id="r", model=model, functions=functions or {}, ttl=60, **limits
    )
    return token


# ---------------------------------------------------------------------------------------------- grants


def test_grants_keep_hashes_and_expire() -> None:
    store = GrantStore()
    token, grant = store.mint(agent_id="a", session_id="s", run_id="r", model=ScriptedModel(), ttl=60)
    assert token.startswith("agr_")
    assert token not in repr(store.__dict__)
    assert store.verify(token) is grant
    assert store.verify(token + "x") is None
    assert store.verify(None) is None
    grant.expires_at = time.monotonic() - 1
    assert store.verify(token) is None
    store.revoke(token)
    assert len(store) == 0


# ---------------------------------------------------------------------------------------------- model proxy


def test_openai_messages_become_agno_messages() -> None:
    messages = openai_to_agno(
        [
            {"role": "developer", "content": "be brief"},
            {"role": "user", "content": [{"type": "text", "text": "hi "}, {"type": "text", "text": "there"}]},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            {"role": "narrator", "content": "dropped"},
        ]
    )
    assert [m.role for m in messages] == ["system", "user", "assistant", "tool"]
    assert messages[1].content == "hi there"
    assert messages[2].tool_calls[0]["id"] == "c1"
    assert (messages[3].tool_call_id, messages[3].tool_name) == ("c1", "bash")


def test_stream_carries_reasoning_text_tool_calls_and_usage(secured_app: TestClient) -> None:
    model = ScriptedModel(
        deltas=[
            ModelResponse(role="assistant", reasoning_content="thinking"),
            ModelResponse(role="assistant", content="Hel"),
            ModelResponse(role="assistant", content="lo"),
            ModelResponse(
                role="assistant",
                tool_calls=[
                    {"id": "call_1", "type": "function", "function": {"name": "write", "arguments": '{"p":1}'}}
                ],
                response_usage=MessageMetrics(input_tokens=7, output_tokens=3),
            ),
        ]
    )
    token = _grant(model)
    body = {
        "model": "something-else",
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": "go"}],
        "tools": [
            {"type": "function", "function": {"name": "write", "parameters": {"type": "object"}, "strict": True}}
        ],
    }
    response = secured_app.post(LLM, json=body, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    events = sse_events(response.text)
    deltas = [event["choices"][0]["delta"] for event in events[:-2]]
    assert deltas[0] == {"role": "assistant", "content": ""}
    assert {"reasoning_content": "thinking"} in deltas
    assert "".join(delta.get("content", "") for delta in deltas) == "Hello"
    calls = next(delta["tool_calls"] for delta in deltas if "tool_calls" in delta)
    assert calls == [
        {"index": 0, "id": "call_1", "type": "function", "function": {"name": "write", "arguments": '{"p":1}'}}
    ]
    assert events[-3]["choices"][0]["finish_reason"] == "tool_calls"
    assert events[-2]["usage"] == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    assert events[-1] == "[DONE]"
    # The client's model choice and tool flags never reach the agent's model.
    sent = model.calls[0]
    assert sent["tools"] == [{"type": "function", "function": {"name": "write", "parameters": {"type": "object"}}}]
    assert all(getattr(m, "role", None) for m in sent["messages"])


def test_non_streaming_answer(secured_app: TestClient) -> None:
    token = _grant(ScriptedModel(deltas=[ModelResponse(role="assistant", content="done")]))
    response = secured_app.post(
        LLM, json={"messages": [{"role": "user", "content": "x"}]}, headers={"Authorization": f"Bearer {token}"}
    )
    choice = response.json()["choices"][0]
    assert (choice["message"]["content"], choice["finish_reason"]) == ("done", "stop")


def test_request_cap(secured_app: TestClient) -> None:
    token = _grant(ScriptedModel(deltas=[ModelResponse(role="assistant", content="x")]), max_requests=1)
    headers = {"Authorization": f"Bearer {token}"}
    body = {"messages": [{"role": "user", "content": "x"}]}
    assert secured_app.post(LLM, json=body, headers=headers).status_code == 200
    assert secured_app.post(LLM, json=body, headers=headers).status_code == 429


# ---------------------------------------------------------------------------------------------- auth bypass


def test_callbacks_need_a_run_token_not_a_jwt(secured_app: TestClient, mint: Callable[..., str]) -> None:
    jwt = mint(["agent_os:admin"])
    refused = secured_app.post(LLM, json={"messages": []}, headers={"Authorization": f"Bearer {jwt}"})
    assert refused.status_code == 401
    assert "www-authenticate" not in {key.lower() for key in refused.headers}
    assert secured_app.post(MCP, json={}).status_code == 401
    # Every other route is still behind AgentOS auth, and a run token opens none of them.
    token = _grant(ScriptedModel())
    assert secured_app.get("/agnostic/v1/capabilities", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert (
        secured_app.get(
            "/agnostic/v1/capabilities", headers={"Authorization": f"Bearer {mint(['config:read'])}"}
        ).status_code
        == 200
    )


def test_callbacks_are_not_in_the_openapi_document(secured_app: TestClient, mint: Callable[..., str]) -> None:
    spec = secured_app.get("/openapi.json", headers={"Authorization": f"Bearer {mint(['agent_os:admin'])}"})
    paths = spec.json().get("paths", {}) if spec.status_code == 200 else {}
    assert not any(path.startswith("/agnostic/v1/coding/") for path in paths)


# ---------------------------------------------------------------------------------------------- tool server


def test_tools_needing_a_person_are_left_out() -> None:
    functions = asyncio.run(flatten_tools([lookup_order, refund]))
    assert list(functions) == ["lookup_order"]


def test_mcp_lists_and_calls_the_agents_tools(secured_app: TestClient) -> None:
    token = _grant(ScriptedModel(), asyncio.run(flatten_tools([lookup_order])))
    headers = {"Authorization": f"Bearer {token}"}

    def rpc(payload: object) -> object:
        response = secured_app.post(MCP, content=json.dumps(payload), headers=headers)
        return response.status_code, (response.json() if response.content else None)

    status, init = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert status == 200 and init["result"]["protocolVersion"] == "2025-03-26"
    assert rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}) == (202, None)
    _, listed = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    (entry,) = listed["result"]["tools"]
    assert entry["name"] == "lookup_order"
    assert entry["inputSchema"]["properties"]["order_id"]["type"] == "string"
    _, called = rpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "lookup_order", "arguments": {"order_id": "o1"}},
        }
    )
    assert called["result"] == {"content": [{"type": "text", "text": "Order o1: shipped"}], "isError": False}
    _, unknown = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "rm_rf"}})
    assert unknown["result"]["isError"] is True
    status, batch = rpc([{"jsonrpc": "2.0", "id": 5, "method": "ping"}, {"jsonrpc": "2.0", "id": 6, "method": "nope"}])
    assert status == 200 and batch[0]["result"] == {} and batch[1]["error"]["code"] == -32601
    assert secured_app.get(MCP, headers=headers).status_code == 405
