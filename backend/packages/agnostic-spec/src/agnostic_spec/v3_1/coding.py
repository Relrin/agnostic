"""The coding-agent marker an agent carries at ``metadata.agnostic.coding_agent``.

The bridge reads the same shape to run the agent through a coding harness inside a per-session sandbox, so the
fields here and their defaults must match what it parses.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agnostic_spec.fields import Widget, meta_field

Harness = Literal["pi", "opencode"]
SandboxProvider = Literal["docker", "e2b"]

METADATA_NAMESPACE = "agnostic"
MARKER_KEY = "coding_agent"
MARKER_PATH = f"metadata.{METADATA_NAMESPACE}.{MARKER_KEY}"


def _setting(
    default: Any,  # noqa: ANN401
    label: str,
    *,
    section: str,
    help: str = "",  # noqa: A002
    widget: Widget = "text",
    order: int = 0,
) -> Any:  # noqa: ANN401
    """A :func:`meta_field` with a real default (``...`` for required), so a partial marker parses as the bridge's."""
    meta = meta_field(section, label, help=help, widget=widget, order=order)
    return Field(default=default, description=help or None, json_schema_extra=meta.json_schema_extra)


class SandboxSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: SandboxProvider = _setting(
        "docker", "Sandbox", section="sandbox", help="Where each session's sandbox runs.", widget="select", order=1
    )
    image: str = _setting(
        "agnostic-coding:0.1.0", "Image", section="sandbox", help="The Docker image the sandbox starts from.", order=2
    )
    template: str | None = _setting(
        None, "E2B template", section="sandbox", help="The E2B template; only used with the E2B provider.", order=3
    )
    cpus: Annotated[float, Field(gt=0, le=64)] = _setting(2.0, "CPUs", section="sandbox", widget="number", order=4)
    memory_mb: Annotated[int, Field(ge=256, le=65536)] = _setting(
        2048, "Memory (MB)", section="sandbox", widget="number", order=5
    )
    workspace_mb: Annotated[int, Field(ge=64, le=65536)] = _setting(
        512, "Workspace size (MB)", section="sandbox", widget="number", order=6
    )
    pids_limit: Annotated[int, Field(ge=32, le=65536)] = _setting(
        256, "Process limit", section="sandbox", widget="number", order=7
    )
    network: str = _setting(
        "isolated",
        "Network",
        section="sandbox",
        help="`isolated` (internet and host ports, no other sandboxes) or a Docker network you manage.",
        order=8,
    )
    turn_timeout_s: Annotated[int, Field(ge=10, le=86400)] = _setting(
        900, "Turn timeout (s)", section="sandbox", widget="number", order=9
    )
    idle_pause_s: Annotated[int, Field(ge=10, le=86400)] = _setting(
        300,
        "Pause when idle (s)",
        section="sandbox",
        help="Seconds without a turn before the sandbox pauses; memory and files are kept.",
        widget="number",
        order=10,
    )
    ttl_s: Annotated[int, Field(ge=60, le=7 * 86400)] = _setting(
        3600,
        "Lifetime (s)",
        section="sandbox",
        help="Seconds without a turn before the sandbox is destroyed.",
        widget="number",
        order=11,
    )


class CodingAgentSettings(BaseModel):
    """Run this agent through a coding harness in a sandbox; files it writes under ``outputs_root`` become artefacts."""

    model_config = ConfigDict(extra="forbid")

    harness: Harness = _setting(
        ..., "Harness", section="coding_agent", help="The coding CLI that runs each turn.", widget="select", order=1
    )
    outputs_root: str = _setting(
        "outputs",
        "Outputs folder",
        section="coding_agent",
        help="Files written here, relative to the workspace, become artefacts.",
        order=2,
    )
    thinking: str | None = _setting(
        None,
        "Thinking level",
        section="coding_agent",
        help="Reasoning level passed to the harness (Pi: off, low, medium, high).",
        order=3,
    )
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)


def coding_settings(metadata: object) -> object:
    """The raw marker inside an agent's ``metadata``, or ``None`` when the agent isn't a coding agent."""
    if not isinstance(metadata, dict):
        return None
    namespace: object = metadata.get(METADATA_NAMESPACE)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(namespace, dict):
        return None
    return namespace.get(MARKER_KEY)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


def coding_json_schema() -> dict[str, Any]:
    """The marker's JSON Schema, each field carrying its ``x-agnostic`` meta and enum fields their options."""
    return CodingAgentSettings.model_json_schema(mode="validation")


__all__ = [
    "MARKER_PATH",
    "CodingAgentSettings",
    "Harness",
    "SandboxProvider",
    "SandboxSettings",
    "coding_json_schema",
    "coding_settings",
]
