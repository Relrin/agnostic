"""GET /agnostic/v1/introspect/components and /registry/{type}/{name}/source: code locations, declared, approvals."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from agno.agent import Agent
from agno.approval import approval
from agno.memory import MemoryManager
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.os.authz import Authorization
from agno.registry import Registry
from agno.team import Team
from agno.tools import tool
from agno.tools.toolkit import Toolkit
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agnostic_bridge import SCOPE_MAPPINGS, install
from tests.conftest import OS_ID, make_os

COMPONENTS = "/agnostic/v1/introspect/components"
THIS_FILE = str(Path(__file__).resolve())
SOURCE = Path(__file__).read_text(encoding="utf-8").splitlines()


def _line_of(text: str) -> int:
    return next(index for index, line in enumerate(SOURCE, start=1) if line.startswith(text))


def _source(kind: str, name: str) -> str:
    return f"/agnostic/v1/registry/{kind}/{name}/source"


@approval
@tool
def refund_customer(customer_id: str, amount: float) -> str:
    """Refund a customer."""
    return f"refunded {amount} to {customer_id}"


@tool
def lookup_order(order_id: str) -> str:
    """Look up an order."""
    return order_id


def search_help_center(query: str) -> str:
    """Search the help center."""
    return query


def check_stock(sku: str) -> str:
    """Check stock for a SKU."""
    return sku


warehouse = Toolkit(name="warehouse", tools=[check_stock], requires_confirmation_tools=["check_stock"])


class TriageResult(BaseModel):
    category: str


def is_urgent(step_input: object) -> bool:
    return False


@dataclass
class SilentModel(Model):
    """Never called: AgentOS only needs a model so it doesn't default to OpenAI."""

    id: str = "silent"
    provider: str = "Test"

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse(role="assistant", content="")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self.invoke()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


notes = MemoryManager(id="notes-mm", name="notes", model=SilentModel())

triage = Agent(
    id="triage",
    name="triage",
    model=SilentModel(),
    tools=[lookup_order, search_help_center],
    instructions=["Triage."],
)
desk = Team(id="desk", name="desk", model=SilentModel(), members=[triage])


def _registry() -> Registry:
    return Registry(
        tools=[refund_customer, lookup_order, warehouse],
        schemas=[TriageResult],
        functions=[is_urgent],
        memory_managers=[notes],
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(install(make_os(agents=[triage], teams=[desk], registry=_registry())))


def test_scopes() -> None:
    assert SCOPE_MAPPINGS[f"GET {COMPONENTS}"] == ["components:read"]
    assert SCOPE_MAPPINGS["GET /agnostic/v1/registry/{type}/{name}/source"] == ["registry:read"]


def test_lists_code_components_with_their_assignment(client: TestClient) -> None:
    response = client.get(COMPONENTS)
    assert response.status_code == 200, response.text
    by_id = {item["id"]: item for item in response.json()}
    assert set(by_id) == {"triage", "desk", "noop"}

    agent = by_id["triage"]
    assert (agent["kind"], agent["name"], agent["module"]) == ("agent", "triage", __name__)
    assert agent["file"] == THIS_FILE
    assert agent["line"] == _line_of("triage = Agent(")
    assert agent["config"] == triage.to_dict()

    team = by_id["desk"]
    assert (team["kind"], team["line"]) == ("team", _line_of("desk = Team("))
    assert team["config"]["members"] == [{"type": "agent", "agent_id": "triage"}]


def test_a_component_built_in_a_function_has_no_location(client: TestClient) -> None:
    (workflow,) = [item for item in client.get(COMPONENTS).json() if item["kind"] == "workflow"]
    assert workflow["id"] == "noop"
    assert (workflow["module"], workflow["file"], workflow["line"]) == (None, None, None)
    assert workflow["config"]["id"] == "noop"


def test_tool_under_approval(client: TestClient) -> None:
    response = client.get(_source("tool", "refund_customer"))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "type": "tool",
        "name": "refund_customer",
        "module": __name__,
        "file": THIS_FILE,
        "line": _line_of("@approval"),
        "declared": True,
        "requires_confirmation": True,
        "approval_type": "required",
    }


def test_plain_tool(client: TestClient) -> None:
    body = client.get(_source("tool", "lookup_order")).json()
    assert (body["declared"], body["requires_confirmation"], body["approval_type"]) == (True, False, None)
    assert body["line"] == _line_of("def lookup_order(") - 1  # the decorator line


def test_a_tool_only_found_on_a_component_is_not_declared(client: TestClient) -> None:
    body = client.get(_source("tool", "search_help_center")).json()
    assert body["declared"] is False
    assert body["line"] == _line_of("def search_help_center(")


def test_toolkit_and_its_functions(client: TestClient) -> None:
    kit = client.get(_source("tool", "warehouse")).json()
    assert kit["module"] == Toolkit.__module__  # a toolkit is located by its class
    assert (kit["declared"], kit["requires_confirmation"]) == (True, True)

    function = client.get(_source("tool", "check_stock")).json()
    assert (function["module"], function["line"]) == (__name__, _line_of("def check_stock("))
    assert (function["declared"], function["requires_confirmation"]) == (True, True)


@pytest.mark.parametrize(
    ("kind", "name", "module", "line"),
    [
        ("schema", "TriageResult", __name__, "class TriageResult("),
        ("function", "is_urgent", __name__, "def is_urgent("),
        ("agent", "triage", __name__, "triage = Agent("),
        ("team", "desk", __name__, "desk = Team("),
        ("memory_manager", "notes", MemoryManager.__module__, None),
    ],
)
def test_other_entries(client: TestClient, kind: str, name: str, module: str, line: str | None) -> None:
    response = client.get(_source(kind, name))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert (body["type"], body["name"], body["module"]) == (kind, name, module)
    assert (body["declared"], body["requires_confirmation"], body["approval_type"]) == (True, False, None)
    assert body["file"]
    if line is not None:
        assert (body["file"], body["line"]) == (THIS_FILE, _line_of(line))


def test_missing_entry_and_unknown_type(client: TestClient) -> None:
    assert client.get(_source("tool", "nope")).status_code == 404
    assert client.get(_source("schema", "refund_customer")).status_code == 404
    assert client.get(_source("gadget", "x")).status_code == 422


@pytest.mark.parametrize(
    ("path", "allowed", "denied"),
    [
        (COMPONENTS, ["components:read"], ["registry:read"]),
        (_source("tool", "lookup_order"), ["registry:read"], ["components:read"]),
    ],
)
def test_needs_its_scope(
    key_pair: tuple[str, str], mint: Callable[..., str], path: str, allowed: list[str], denied: list[str]
) -> None:
    authorization = Authorization(
        verification_keys=[key_pair[1]], algorithm="RS256", verify_audience=True, audience=OS_ID
    )
    client = TestClient(install(make_os(agents=[triage], registry=_registry(), authorization=authorization)))
    assert client.get(path, headers={"Authorization": f"Bearer {mint(allowed)}"}).status_code == 200
    assert client.get(path, headers={"Authorization": f"Bearer {mint(denied)}"}).status_code == 403
    assert client.get(path, headers={"Authorization": f"Bearer {mint(['agent_os:admin'])}"}).status_code == 200
