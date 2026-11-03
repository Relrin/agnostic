"""app.dump_golden: one file per component, stable output, and fixtures that load strictly from the registry."""

import json
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.team import Team
from agno.workflow import Workflow

from app.agents import AGENTS
from app.dump_golden import dump
from app.registry import build_registry
from app.teams import TEAMS
from app.workflows import WORKFLOWS


def test_writes_every_component_and_the_fixtures(tmp_path: Path) -> None:
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "removed-agent.json").write_text("{}", encoding="utf-8")

    written = dump(tmp_path)

    assert {path.stem for path in (tmp_path / "agents").glob("*.json")} == {
        *(agent.id for agent in AGENTS),
        "golden-full-agent",
    }
    assert {path.stem for path in (tmp_path / "teams").glob("*.json")} == {
        *(team.id for team in TEAMS),
        "golden-tasks-team",
    }
    assert {path.stem for path in (tmp_path / "workflows").glob("*.json")} == {
        *(workflow.id for workflow in WORKFLOWS),
        "golden-full-workflow",
    }
    assert [path.name for path in (tmp_path / "prototype").glob("*.json")] == ["ticket-router.json"]
    assert len(written) == len(AGENTS) + len(TEAMS) + len(WORKFLOWS) + 4


def test_output_is_stable(tmp_path: Path) -> None:
    first = {path.name: path.read_bytes() for path in dump(tmp_path / "a")}
    second = {path.name: path.read_bytes() for path in dump(tmp_path / "b")}
    assert first == second


def test_fixtures_load_strictly(tmp_path: Path) -> None:
    dump(tmp_path)
    db = SqliteDb(db_file=str(tmp_path / "golden.db"))
    registry = build_registry(db)
    # Members rebuilt from their own golden files: the module-level agents pick up run state from other tests.
    for path in sorted((tmp_path / "agents").glob("*.json")):
        member = json.loads(path.read_text(encoding="utf-8"))
        registry.agents.append(Agent.from_dict(member, registry=registry, strict=True))

    agent_config = json.loads((tmp_path / "agents" / "golden-full-agent.json").read_text(encoding="utf-8"))
    rebuilt = Agent.from_dict(agent_config, registry=registry, strict=True).to_dict()
    # A rehydrated tool writes its false approval flags explicitly; everything else round-trips as stored.
    assert {key: value for key, value in rebuilt.items() if key != "tools"} == {
        key: value for key, value in agent_config.items() if key != "tools"
    }
    assert [tool["name"] for tool in rebuilt["tools"]] == [tool["name"] for tool in agent_config["tools"]]

    team_config = json.loads((tmp_path / "teams" / "golden-tasks-team.json").read_text(encoding="utf-8"))
    team = Team.from_dict(team_config, db=db, registry=registry, strict=True)
    assert team.to_dict() == team_config


def test_workflow_fixtures_load_strictly(tmp_path: Path) -> None:
    dump(tmp_path)
    db = SqliteDb(db_file=str(tmp_path / "golden.db"))
    registry = build_registry(db)
    for path in sorted((tmp_path / "agents").glob("*.json")):
        registry.agents.append(Agent.from_dict(json.loads(path.read_text(encoding="utf-8")), registry=registry))
    for path in sorted((tmp_path / "teams").glob("*.json")):
        config = json.loads(path.read_text(encoding="utf-8"))
        registry.teams.append(Team.from_dict(config, db=db, registry=registry))
    daily = json.loads((tmp_path / "workflows" / "daily-brief.json").read_text(encoding="utf-8"))
    registry.workflows.append(Workflow.from_dict(daily, db=db, registry=registry))

    for path in (tmp_path / "workflows" / "golden-full-workflow.json", tmp_path / "prototype" / "ticket-router.json"):
        config = json.loads(path.read_text(encoding="utf-8"))
        rebuilt = Workflow.from_dict(config, db=db, registry=registry, strict=True).to_dict()
        rebuilt.pop("db", None)
        # Steps stored without an id get a fresh one on every load; everything else reads back as stored.
        assert _without_step_ids(rebuilt) == _without_step_ids(config)


def _without_step_ids(value: object) -> object:
    if isinstance(value, list):
        return [_without_step_ids(item) for item in value]
    if isinstance(value, dict):
        return {key: _without_step_ids(item) for key, item in value.items() if key != "step_id"}
    return value
