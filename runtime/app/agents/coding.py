"""Coding agents: Pi and OpenCode, each in a sandbox of its own per session; files under outputs/ become artefacts.

Registered only when their sandbox provider is usable here: the ``docker`` CLI for Docker sandboxes (build the image
with ``just sandbox-image``), or ``E2B_API_KEY`` and the e2b package for E2B. Without a real model configured
(``RUNTIME_CODING_MODEL``) they think with the mock coder, which writes ``outputs/hello.md`` and lists the folder,
so the whole loop works offline.
"""

from __future__ import annotations

import importlib.util
import os
import shutil

from agno.models.base import Model
from agnostic_bridge.artifacts import capture_artifacts
from agnostic_bridge.coding import CodingAgent, CodingAgentSpec, OpenCodeAgent, PiAgent, SandboxSpec

from app.media import media_storage
from app.settings import RuntimeSettings
from app.tools import lookup_order, search_knowledge

INSTRUCTIONS = "Save every file the person should get under outputs/ in the workspace."


def coding_model(setting: str) -> Model:
    if setting in ("", "mock"):
        from app.models.mock import MockModel

        return MockModel(id="mock-coder", persona="coder")
    from agno.models.utils import get_model

    return get_model(setting)


def sandbox_available(settings: RuntimeSettings) -> bool:
    if settings.coding_sandbox == "e2b":
        return bool(os.environ.get("E2B_API_KEY")) and importlib.util.find_spec("e2b") is not None
    return shutil.which("docker") is not None


def build_coding_agents(settings: RuntimeSettings) -> list[CodingAgent]:
    if not settings.coding_enabled or not sandbox_available(settings):
        return []
    sandbox = SandboxSpec(
        provider="e2b" if settings.coding_sandbox == "e2b" else "docker",
        image=settings.coding_image,
        template=settings.coding_template,
        network=settings.coding_network,
    )
    storage = media_storage()
    agents: list[CodingAgent] = []
    for cls, agent_id, name, harness in (
        (PiAgent, "pi-coder", "Pi coder", "pi"),
        (OpenCodeAgent, "opencode-coder", "OpenCode coder", "opencode"),
    ):
        agent = cls(
            id=agent_id,
            name=name,
            description=f"{name}: edits files and runs commands in its own sandbox; outputs/ become artefacts.",
            model=coding_model(settings.coding_model),
            instructions=INSTRUCTIONS,
            tools=[lookup_order, search_knowledge],
            coding=CodingAgentSpec(harness=harness, sandbox=sandbox),  # type: ignore[arg-type]
            store_events=True,
        )
        agents.append(capture_artifacts(agent, media_storage=storage, root="outputs"))
    return agents
