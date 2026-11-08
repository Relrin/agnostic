"""What a coding agent runs in and how: the harness, the sandbox it gets per session, and where its files go.

The same shape is stored on a Studio agent component as ``metadata.agnostic.coding_agent``; that marker is what turns
a stored agent into a coding agent on this runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Harness = Literal["pi", "opencode"]
ProviderKind = Literal["docker", "e2b"]

METADATA_PATH = ("agnostic", "coding_agent")
DEFAULT_IMAGE = "agnostic-coding:0.1.0"


class SandboxSpec(BaseModel):
    """The computer one session of a coding agent gets. Limits apply per sandbox, not per agent."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderKind = "docker"
    image: str = DEFAULT_IMAGE
    """Docker image with the harness CLIs; E2B uses ``template`` instead."""
    template: str | None = None
    """E2B template id or name, built from the same Dockerfile."""
    cpus: float = Field(default=2.0, gt=0, le=64)
    memory_mb: int = Field(default=2048, ge=256, le=65536)
    workspace_mb: int = Field(default=512, ge=64, le=65536)
    pids_limit: int = Field(default=256, ge=32, le=65536)
    network: str = "isolated"
    """``isolated`` (internet and host ports, no other sandboxes) or the name of a Docker network you manage."""
    turn_timeout_s: int = Field(default=900, ge=10, le=86400)
    idle_pause_s: int = Field(default=300, ge=10, le=86400)
    """Seconds without a turn before the sandbox is paused (memory and files are kept)."""
    ttl_s: int = Field(default=3600, ge=60, le=7 * 86400)
    """Seconds without a turn before the sandbox is destroyed; the next turn starts a fresh one."""


class CodingAgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    harness: Harness
    sandbox: SandboxSpec = Field(default_factory=SandboxSpec)
    outputs_root: str = "outputs"
    """Folder in the workspace whose files become artefacts of each run."""
    thinking: str | None = None
    """Reasoning level passed to the harness when it has one (Pi: ``off``, ``low``, ``medium``, ``high``)."""


def spec_from_metadata(metadata: Mapping[str, Any] | None) -> CodingAgentSpec | None:
    """The coding agent settings an agent's metadata carries, or ``None`` when it is not a coding agent.

    Raises :class:`pydantic.ValidationError` when the marker is present but malformed, so a typo surfaces instead of
    the agent quietly running as a plain one.
    """
    node: Any = metadata
    for key in METADATA_PATH:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    if node is None:
        return None
    return CodingAgentSpec.model_validate(node)


def spec_or_none(metadata: Mapping[str, Any] | None) -> CodingAgentSpec | None:
    """:func:`spec_from_metadata` without raising; a malformed marker counts as no marker."""
    try:
        return spec_from_metadata(metadata)
    except ValidationError:
        return None


def spec_to_metadata(spec: CodingAgentSpec, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """``metadata`` with the marker set to ``spec`` (other keys kept)."""
    merged: dict[str, Any] = dict(metadata or {})
    agnostic = dict(merged.get(METADATA_PATH[0]) or {})
    agnostic[METADATA_PATH[1]] = spec.model_dump(mode="json", exclude_none=True)
    merged[METADATA_PATH[0]] = agnostic
    return merged
