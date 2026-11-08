"""Coding agents (Pi, OpenCode) that run in a sandbox of their own per session, on an Agno model.

    from agnostic_bridge.coding import PiAgent, CodingAgentSpec, SandboxSpec

    coder = PiAgent(id="pi-coder", name="Pi coder", model=Claude(id="claude-sonnet-4-6"),
                    coding=CodingAgentSpec(harness="pi", sandbox=SandboxSpec(provider="docker")))
    agent_os = AgentOS(agents=[coder], db=db)
    app = install(agent_os, coding=CodingConfig(callback_url="http://host.docker.internal:7777"))

The harness process runs in the sandbox, never in AgentOS. It reaches the agent's model through a per-run proxy on
this runtime and the agent's tools through a per-run MCP server, both authorised by a token that lives for one turn.
"""

from agnostic_bridge.coding._agent import CodingAgent, CodingHarnessError
from agnostic_bridge.coding._grants import GrantStore, RunGrant
from agnostic_bridge.coding._opencode import OpenCodeAgent
from agnostic_bridge.coding._pi import PiAgent
from agnostic_bridge.coding._providers import (
    DockerProvider,
    E2BProvider,
    HarnessExited,
    ProcessStream,
    SandboxLease,
    SandboxProvider,
)
from agnostic_bridge.coding._runtime import CodingConfig, CodingRuntime, SandboxPool, coding_runtime
from agnostic_bridge.coding._spec import CodingAgentSpec, SandboxSpec, spec_from_metadata, spec_to_metadata

__all__ = [
    "CodingAgent",
    "CodingAgentSpec",
    "CodingConfig",
    "CodingHarnessError",
    "CodingRuntime",
    "DockerProvider",
    "E2BProvider",
    "GrantStore",
    "HarnessExited",
    "OpenCodeAgent",
    "PiAgent",
    "ProcessStream",
    "RunGrant",
    "SandboxLease",
    "SandboxPool",
    "SandboxProvider",
    "SandboxSpec",
    "coding_runtime",
    "spec_from_metadata",
    "spec_to_metadata",
]
