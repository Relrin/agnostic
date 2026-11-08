"""Sandbox analyst: runs code in an E2B sandbox; what it saves under /home/user/outputs becomes artefacts.

Registered only when ``E2B_API_KEY`` is set and ``e2b_code_interpreter`` is installed. The post-hook collects the
sandbox's outputs folder at the end of the run, before the sandbox times out, so the files outlive it.
"""

from __future__ import annotations

import os

from agno.agent import Agent


def build_sandbox_analyst() -> Agent | None:
    if not os.environ.get("E2B_API_KEY"):
        return None
    try:
        from agno.tools.e2b import E2BTools
    except ImportError:  # e2b_code_interpreter is not installed
        return None
    from agnostic_bridge.artifacts import ArtifactTools, E2BSource, collect_artifacts

    from app.media import media_storage
    from app.models.mock import MockModel

    tools = E2BTools()
    source = E2BSource(tools=tools, root="/home/user/outputs")
    return Agent(
        id="sandbox-analyst",
        name="sandbox-analyst",
        description="Analyses data in an E2B sandbox; files saved to /home/user/outputs become artefacts.",
        model=MockModel(persona="sandbox-analyst"),
        tools=[tools, ArtifactTools(source)],
        instructions="Run Python in the sandbox and save every chart or table you make under /home/user/outputs.",
        post_hooks=[collect_artifacts(source)],
        media_storage=media_storage(),
        markdown=True,
        store_events=True,
    )
