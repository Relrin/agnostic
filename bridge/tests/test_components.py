"""POST /agnostic/v1/components/{validate,normalize}: strict and lenient rebuilds against the registry and db."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os.authz import Authorization
from agno.registry import Registry
from agno.tools import tool
from agno.workflow import Step, Workflow
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agnostic_bridge import SCOPE_MAPPINGS, install
from tests.conftest import OS_ID, make_os

VALIDATE = "/agnostic/v1/components/validate"
NORMALIZE = "/agnostic/v1/components/normalize"


@tool
def lookup_order(order_id: str) -> str:
    """Look up an order."""
    return order_id


class Verdict(BaseModel):
    ok: bool


writer = Agent(id="writer", name="writer")


@pytest.fixture
def db(tmp_path: Path) -> SqliteDb:
    return SqliteDb(db_file=str(tmp_path / "os.db"))


@pytest.fixture
def client(db: SqliteDb) -> TestClient:
    registry = Registry(tools=[lookup_order], schemas=[Verdict], agents=[writer])
    return TestClient(install(make_os(db=db, registry=registry)))


def _validate(client: TestClient, kind: str, config: dict[str, Any]) -> dict[str, Any]:
    response = client.post(VALIDATE, json={"kind": kind, "config": config})
    assert response.status_code == 200, response.text
    return response.json()


def test_scopes() -> None:
    assert SCOPE_MAPPINGS[f"POST {VALIDATE}"] == ["components:read"]
    assert SCOPE_MAPPINGS[f"POST {NORMALIZE}"] == ["components:read"]


def test_a_config_built_from_the_registry_is_valid(client: TestClient) -> None:
    config = {"id": "triage", "name": "triage", "tools": [lookup_order.to_dict()], "output_schema": "Verdict"}
    assert _validate(client, "agent", config) == {"valid": True, "errors": []}


@pytest.mark.parametrize(
    ("kind", "config", "path"),
    [
        ("agent", {"id": "a", "tools": [{"name": "refund_everyone"}]}, "tools"),
        ("agent", {"id": "a", "output_schema": "Missing"}, "output_schema"),
        ("agent", {"id": "a", "model": {"id": "x-1", "provider": "NoSuchProvider"}}, "model"),
        ("team", {"id": "t", "members": [{"type": "agent", "agent_id": "ghost"}]}, "members"),
        ("workflow", {"id": "w", "steps": [{"type": "Step", "name": "s", "agent_id": "ghost"}]}, "steps"),
    ],
)
def test_unresolvable_references_are_reported(client: TestClient, kind: str, config: dict[str, Any], path: str) -> None:
    body = _validate(client, kind, config)
    assert body["valid"] is False
    (error,) = body["errors"]
    assert error["path"] == path
    assert error["message"]


def test_team_and_workflow_members_resolve_from_the_registry(client: TestClient) -> None:
    team = {"id": "t", "name": "t", "members": [{"type": "agent", "agent_id": "writer"}]}
    workflow = Workflow(id="w", name="w", steps=[Step(name="draft", agent=writer)]).to_dict()
    assert _validate(client, "team", team)["valid"] is True
    assert _validate(client, "workflow", workflow)["valid"] is True


def test_normalize_drops_what_does_not_resolve_and_applies_defaults(client: TestClient) -> None:
    config = {"id": "a", "name": "a", "tools": [{"name": "refund_everyone"}], "instructions": ["Be brief."]}
    response = client.post(NORMALIZE, json={"kind": "agent", "config": config})
    assert response.status_code == 200, response.text
    normalized = response.json()["config"]
    assert normalized["id"] == "a"
    assert normalized["instructions"] == ["Be brief."]
    assert "tools" not in normalized
    assert normalized["num_history_runs"] == 3  # agno's default, written back


def test_normalize_leaves_the_request_config_alone(client: TestClient) -> None:
    config = {"id": "a", "output_schema": "Verdict"}
    response = client.post(NORMALIZE, json={"kind": "agent", "config": config})
    assert response.json()["config"]["output_schema"] == "Verdict"


def test_normalize_refuses_what_cannot_be_built(client: TestClient) -> None:
    config = {"id": "a", "model": {"id": "x-1", "provider": "NoSuchProvider"}}
    response = client.post(NORMALIZE, json={"kind": "agent", "config": config})
    assert response.status_code == 422
    body = response.json()
    assert body["valid"] is False
    assert [error["path"] for error in body["errors"]] == ["model"]


def test_unknown_kind_is_a_validation_error(client: TestClient) -> None:
    assert client.post(VALIDATE, json={"kind": "robot", "config": {}}).status_code == 422


@pytest.mark.parametrize("path", [VALIDATE, NORMALIZE])
def test_needs_a_sync_db(path: str) -> None:
    client = TestClient(install(make_os()))
    assert client.post(path, json={"kind": "agent", "config": {"id": "a"}}).status_code == 503


@pytest.mark.parametrize(
    ("scopes", "status"),
    [(["components:read"], 200), (["agent_os:admin"], 200), (["components:write"], 403), ([], 403)],
)
def test_needs_components_read(
    key_pair: tuple[str, str], mint: Callable[..., str], db: SqliteDb, scopes: list[str], status: int
) -> None:
    authorization = Authorization(
        verification_keys=[key_pair[1]], algorithm="RS256", verify_audience=True, audience=OS_ID
    )
    client = TestClient(install(make_os(db=db, authorization=authorization)))
    headers = {"Authorization": f"Bearer {mint(scopes)}"}
    for path in (VALIDATE, NORMALIZE):
        response = client.post(path, json={"kind": "agent", "config": {"id": "a"}}, headers=headers)
        assert response.status_code == status, response.text
