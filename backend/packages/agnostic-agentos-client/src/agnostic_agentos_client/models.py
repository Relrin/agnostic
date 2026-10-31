"""Response models the client returns.

Most come straight from the generated models (``_generated/models.py``, from the pinned AgentOS 3.1.12 OpenAPI).
AgentOS publishes ``/config`` as a free-form object, so :class:`OsConfig` types the sections the control plane
relies on and keeps everything else as extra fields; the contract tests check it against a live runtime.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from agnostic_agentos_client._generated.models import HealthResponse, InfoResponse, McpInfo

__all__ = ["ComponentSummary", "HealthResponse", "InfoResponse", "McpInfo", "OsConfig"]


class ComponentSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None
    description: str | None = None


class OsConfig(BaseModel):
    """``GET /config``: components, databases and the per-feature sections used for capability detection."""

    model_config = ConfigDict(extra="allow")

    os_id: str
    description: str | None = None
    available_models: list[Any] = []
    databases: list[Any] = []
    agents: list[ComponentSummary] = []
    teams: list[ComponentSummary] = []
    workflows: list[ComponentSummary] = []
    interfaces: list[Any] = []
    queue: dict[str, Any] | None = None
    traces: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    knowledge: dict[str, Any] | None = None
    learning: dict[str, Any] | None = None
    session: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    evals: dict[str, Any] | None = None
    filesystem: dict[str, Any] | None = None
