"""The registry Studio composes from: model presets, schemas, the memory manager, and that configs using them load."""

from pathlib import Path

import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.registry import Registry

from app.models.mock import MockModel
from app.registry import MEMORY_MANAGER_ID, build_registry
from app.schemas import RefundRequest, TriageResult


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    return build_registry(SqliteDb(db_file=str(tmp_path / "registry.db")))


def test_model_presets(registry: Registry) -> None:
    presets = {model.id: model for model in registry.models if isinstance(model, MockModel)}
    assert set(presets) == {"agnostic-mock", "mock-precise", "mock-creative"}
    assert (presets["mock-precise"].temperature, presets["mock-creative"].temperature) == (0.2, 0.9)
    assert registry.get_model("mock-creative", provider="Agnostic") is presets["mock-creative"]


def test_schemas(registry: Registry) -> None:
    assert registry.get_schema("TriageResult") is TriageResult
    assert registry.get_schema("RefundRequest") is RefundRequest
    assert set(TriageResult.model_fields) == {"category", "urgency", "needs_human"}


def test_memory_manager(registry: Registry) -> None:
    manager = registry.get_memory_manager(MEMORY_MANAGER_ID)
    assert manager is not None
    assert isinstance(manager.model, MockModel)
    assert manager.db is registry.dbs[0]


def test_a_config_using_them_loads_strictly(registry: Registry) -> None:
    config = {
        "id": "studio-triage",
        "model": {"id": "mock-precise", "provider": "Agnostic", "name": "MockModel"},
        "output_schema": "TriageResult",
        "memory_manager": {"registry_id": MEMORY_MANAGER_ID},
        "enable_agentic_memory": True,
    }
    agent = Agent.from_dict(config, registry=registry, strict=True)
    assert isinstance(agent.model, MockModel) and agent.model.id == "mock-precise"
    assert agent.output_schema is TriageResult
    assert agent.memory_manager is registry.get_memory_manager(MEMORY_MANAGER_ID)
