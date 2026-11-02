"""POST /agnostic/v1/evals/run: version resolution, draft gating, scopes and dispatch, with the eval helpers stubbed."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from agno.agent import Agent
from agno.db.base import ComponentType
from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.routers.evals import utils as eval_utils
from agno.os.routers.evals.schemas import EvalSchema
from agno.team import Team
from fastapi.testclient import TestClient

from agnostic_bridge import SCOPE_MAPPINGS, _evals, install
from tests.conftest import OS_ID, make_os

PATH = "/agnostic/v1/evals/run"
OWNER = "owner@example.com"
RUNNERS = {
    EvalType.ACCURACY: "run_accuracy_eval",
    EvalType.AGENT_AS_JUDGE: "run_agent_as_judge_eval",
    EvalType.PERFORMANCE: "run_performance_eval",
    EvalType.RELIABILITY: "run_reliability_eval",
}


@dataclass
class StubModel(Model):
    """Code-defined teams need a model at AgentOS init (else agno imports openai); never invoked here."""

    id: str = "stub"
    name: str = "Stub"
    provider: str = "Stub"

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        raise NotImplementedError

    def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> Any:
        raise NotImplementedError


@pytest.fixture
def db(tmp_path: Path) -> SqliteDb:
    """Agent ``writer`` owned by OWNER: version 1 published (current), version 2 a draft."""
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    db.create_component_with_config(
        component_id="writer",
        component_type=ComponentType.AGENT,
        name="Writer",
        config=Agent(id="writer", name="Writer", instructions="v1").to_dict(),
        stage="published",
        user_id=OWNER,
    )
    db.upsert_config(
        component_id="writer", config=Agent(id="writer", name="Writer", instructions="v2").to_dict(), stage="draft"
    )
    return db


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace AgentOS's eval helpers with recorders that store a run like the real ones do."""
    calls: list[dict[str, Any]] = []

    def recorder(eval_type: EvalType) -> Callable[..., Any]:
        async def run(*, eval_run_input: Any, db: Any, agent: Any = None, team: Any = None, default_model: Any = None):
            calls.append(
                {
                    "type": eval_type,
                    "input": eval_run_input,
                    "agent": agent,
                    "team": team,
                    "default_model": default_model,
                }
            )
            run_id = f"run-{len(calls)}"
            fields = {
                "agent_id": agent.id if agent else None,
                "team_id": team.id if team else None,
                "name": eval_run_input.name,
                "eval_type": eval_type,
                "eval_data": {"eval_status": "PASSED"},
            }
            db.create_eval_run(EvalRunRecord(run_id=run_id, **fields))
            return EvalSchema(id=run_id, **fields)

        return run

    for eval_type, name in RUNNERS.items():
        monkeypatch.setattr(eval_utils, name, recorder(eval_type))
    return calls


def _secured_os(public_pem: str, **kwargs: Any) -> AgentOS:
    authorization = Authorization(
        verification_keys=[public_pem], algorithm="RS256", verify_audience=True, audience=OS_ID
    )
    return make_os(authorization=authorization, **kwargs)


def _body(**overrides: Any) -> dict[str, Any]:
    body = {
        "component_type": "agent",
        "component_id": "writer",
        "eval_type": "accuracy",
        "input": "Write a haiku",
        "expected_output": "A haiku",
    }
    return {**body, **overrides}


def test_listed_in_capabilities_with_evals_write(db: SqliteDb) -> None:
    assert SCOPE_MAPPINGS[f"POST {PATH}"] == ["evals:write"]
    body = TestClient(install(make_os(db=db))).get("/agnostic/v1/capabilities").json()
    assert f"POST {PATH}" in body["endpoints"]


@pytest.mark.parametrize(
    ("version", "instructions"),
    [(None, "v1"), (1, "v1"), (2, "v2")],
)
def test_resolves_the_requested_version(
    db: SqliteDb, runs: list[dict[str, Any]], version: int | None, instructions: str
) -> None:
    client = TestClient(install(make_os(db=db)))

    response = client.post(PATH, json=_body(version=version))

    assert response.status_code == 200, response.text
    assert response.json()["component_version"] == version
    assert response.json()["agent_id"] == "writer"
    assert runs[0]["agent"].instructions == instructions


@pytest.mark.parametrize(("component_id", "version"), [("writer", 99), ("nobody", None), ("nobody", 1)])
def test_unknown_component_or_version_is_404(db: SqliteDb, runs: list[dict[str, Any]], component_id, version) -> None:
    client = TestClient(install(make_os(db=db)))
    response = client.post(PATH, json=_body(component_id=component_id, version=version))
    assert response.status_code == 404
    assert response.json() == {"detail": "Agent not found"}
    assert runs == []


def test_version_skips_code_defined_components(db: SqliteDb, runs: list[dict[str, Any]]) -> None:
    """A pinned version is a stored config; a code-defined agent with that id doesn't answer for it."""
    agent_os = make_os(db=db, agents=[Agent(id="local", model=StubModel())])
    client = TestClient(install(agent_os))
    assert client.post(PATH, json=_body(component_id="local")).status_code == 200
    assert client.post(PATH, json=_body(component_id="local", version=1)).status_code == 404


def test_needs_a_db(runs: list[dict[str, Any]]) -> None:
    client = TestClient(install(make_os(agents=[Agent(id="local", model=StubModel())])))
    response = client.post(PATH, json=_body(component_id="local"))
    assert response.status_code == 503
    assert runs == []


@pytest.mark.parametrize("eval_type", list(RUNNERS))
def test_dispatches_by_eval_type(db: SqliteDb, runs: list[dict[str, Any]], eval_type: EvalType) -> None:
    client = TestClient(install(make_os(db=db)))
    body = _body(
        eval_type=eval_type.value,
        name="case 7",
        num_iterations=3,
        criteria="Is it a haiku?",
        expected_tool_calls=["search"],
        agent_id="ignored",
    )

    response = client.post(PATH, json=body)

    assert response.status_code == 200, response.text
    assert response.json()["eval_type"] == eval_type.value
    assert [call["type"] for call in runs] == [eval_type]
    eval_input = runs[0]["input"]
    assert (eval_input.agent_id, eval_input.team_id) == ("writer", None)
    assert (eval_input.name, eval_input.num_iterations, eval_input.input) == ("case 7", 3, "Write a haiku")
    assert eval_input.criteria == "Is it a haiku?"
    assert eval_input.expected_tool_calls == ["search"]
    assert runs[0]["team"] is None


def test_runs_a_team(db: SqliteDb, runs: list[dict[str, Any]]) -> None:
    team = Team(id="crew", name="Crew", model=StubModel(), members=[Agent(id="member", model=StubModel())])
    client = TestClient(install(make_os(db=db, teams=[team])))

    response = client.post(PATH, json=_body(component_type="team", component_id="crew", eval_type="performance"))

    assert response.status_code == 200, response.text
    assert response.json()["team_id"] == "crew"
    call = runs[0]
    assert call["agent"] is None
    assert call["team"].id == "crew"
    assert call["team"] is not team  # a per-request copy, never the served instance
    assert (call["input"].agent_id, call["input"].team_id) == (None, "crew")


@pytest.mark.parametrize("eval_type", [EvalType.ACCURACY, EvalType.AGENT_AS_JUDGE])
def test_judge_reaches_the_runner_and_the_component_keeps_its_model(
    monkeypatch: pytest.MonkeyPatch, db: SqliteDb, runs: list[dict[str, Any]], eval_type: EvalType
) -> None:
    built: list[str] = []

    def fake_get_model(model: str) -> StubModel:
        built.append(model)
        return StubModel(id="judge-model", provider="Judge")

    monkeypatch.setattr(_evals, "get_model", fake_get_model)
    client = TestClient(install(make_os(db=db, agents=[Agent(id="local", model=StubModel())])))
    body = _body(component_id="local", eval_type=eval_type.value, criteria="Is it a haiku?")

    response = client.post(PATH, json={**body, "model_provider": "Judge", "model_id": "Judge-Model"})

    assert response.status_code == 200, response.text
    assert built == ["Judge:Judge-Model"]
    assert (runs[0]["default_model"].provider, runs[0]["default_model"].id) == ("Judge", "judge-model")
    assert (runs[0]["agent"].model.provider, runs[0]["agent"].model.id) == ("Stub", "stub")


@pytest.mark.parametrize("eval_type", [EvalType.PERFORMANCE, EvalType.RELIABILITY])
def test_judge_is_ignored_without_an_evaluator(db: SqliteDb, runs: list[dict[str, Any]], eval_type: EvalType) -> None:
    client = TestClient(install(make_os(db=db)))
    body = _body(eval_type=eval_type.value, expected_tool_calls=[], model_provider="nope", model_id="x")

    assert client.post(PATH, json=body).status_code == 200
    assert runs[0]["default_model"] is None


def test_no_judge_uses_the_default_evaluator(db: SqliteDb, runs: list[dict[str, Any]]) -> None:
    client = TestClient(install(make_os(db=db)))
    assert client.post(PATH, json=_body()).status_code == 200
    assert runs[0]["default_model"] is None


@pytest.mark.parametrize(
    "judge",
    [{"model_provider": "nope", "model_id": "x"}, {"model_id": "gpt-x"}, {"model_provider": "openai"}],
)
def test_unusable_judge_is_400(db: SqliteDb, runs: list[dict[str, Any]], judge: dict[str, str]) -> None:
    client = TestClient(install(make_os(db=db)))
    assert client.post(PATH, json=_body(**judge)).status_code == 400
    assert runs == []


@pytest.mark.parametrize(
    ("scopes", "status"),
    [
        (["evals:write", "agents:run"], 200),
        (["evals:write", "agents:writer:run"], 200),
        (["agent_os:admin"], 200),
        (["evals:write"], 403),  # may not run the target
        (["agents:run", "evals:read"], 403),  # route scope missing
        ([], 403),
    ],
)
def test_needs_evals_write_and_run_access(
    key_pair: tuple[str, str],
    mint: Callable[..., str],
    db: SqliteDb,
    runs: list[dict[str, Any]],
    scopes: list[str],
    status: int,
) -> None:
    client = TestClient(install(_secured_os(key_pair[1], db=db)))
    response = client.post(PATH, json=_body(), headers={"Authorization": f"Bearer {mint(scopes, sub=OWNER)}"})
    assert response.status_code == status, response.text
    assert len(runs) == (1 if status == 200 else 0)


def test_rejects_anonymous(key_pair: tuple[str, str], db: SqliteDb, runs: list[dict[str, Any]]) -> None:
    client = TestClient(install(_secured_os(key_pair[1], db=db)))
    assert client.post(PATH, json=_body()).status_code == 401


@pytest.mark.parametrize(
    ("sub", "scopes", "version", "status"),
    [
        (OWNER, ["evals:write", "agents:run"], 2, 200),
        ("someone-else", ["evals:write", "agents:run"], 2, 404),  # someone else's draft reads as missing
        ("someone-else", ["evals:write", "agents:run"], 1, 200),  # published versions are never gated
        ("someone-else", ["evals:write", "agents:run"], None, 200),
        ("someone-else", ["agent_os:admin"], 2, 200),
    ],
)
def test_drafts_are_owner_or_admin_only(
    key_pair: tuple[str, str],
    mint: Callable[..., str],
    db: SqliteDb,
    runs: list[dict[str, Any]],
    sub: str,
    scopes: list[str],
    version: int | None,
    status: int,
) -> None:
    client = TestClient(install(_secured_os(key_pair[1], db=db)))
    token = mint(scopes, sub=sub)

    response = client.post(PATH, json=_body(version=version), headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == status, response.text
    if status == 404:
        assert response.json() == {"detail": "Agent not found"}
        assert runs == []
    else:
        assert runs[0]["agent"].instructions == ("v2" if version == 2 else "v1")


def test_open_os_previews_drafts(db: SqliteDb, runs: list[dict[str, Any]]) -> None:
    """Authorization off: every caller is privileged, as on the AgentOS run routes."""
    client = TestClient(install(make_os(db=db)))
    assert client.post(PATH, json=_body(version=2)).status_code == 200


def test_run_is_owned_by_the_caller(
    key_pair: tuple[str, str], mint: Callable[..., str], db: SqliteDb, runs: list[dict[str, Any]]
) -> None:
    client = TestClient(install(_secured_os(key_pair[1], db=db)))
    token = mint(["evals:write", "agents:run"], sub=OWNER)

    response = client.post(PATH, json=_body(version=2), headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == OWNER
    stored = db.get_eval_run(eval_run_id=body["id"], deserialize=False)
    assert isinstance(stored, dict)
    assert stored["user_id"] == OWNER
