"""Collect the files agents produce as artefacts the control plane can list, view, download and share.

Artefacts are ordinary Agno run media (``Image``, ``Audio``, ``Video``, ``File``) with ``metadata["artifact"]``
describing their origin; AgentOS stores them in its ``media_storage`` and serves them at
``GET /sessions/{session_id}/media/{storage_key}``. This package gets them there from wherever a harness writes:

    from agnostic_bridge.artifacts import DirectorySource, E2BSource, collect_artifacts, ArtifactTools

    tools = E2BTools()
    Agent(
        tools=[tools, ArtifactTools(E2BSource(tools=tools))],
        post_hooks=[collect_artifacts(E2BSource(tools=tools))],
        media_storage=storage,
    )

See ``docs/how-to/collect-artefacts.md`` for Claude Code, Codex, Pi, OpenCode and writing a source of your own.
"""

from agnostic_bridge.artifacts._capture import (
    ArtifactTools,
    HarnessCapture,
    capture_artifacts,
    collect_artifacts,
)
from agnostic_bridge.artifacts._collector import DEFAULT_EXCLUDE, ArtifactCollector
from agnostic_bridge.artifacts._media import ARTIFACT_METADATA_KEY, artifact_kind, build_media, detect_content_type
from agnostic_bridge.artifacts._sources import (
    ArtifactSource,
    ArtifactSourceError,
    CheckpointSource,
    DirectorySource,
    E2BSource,
    SourceEntry,
)

__all__ = [
    "ARTIFACT_METADATA_KEY",
    "DEFAULT_EXCLUDE",
    "ArtifactCollector",
    "ArtifactSource",
    "ArtifactSourceError",
    "ArtifactTools",
    "CheckpointSource",
    "DirectorySource",
    "E2BSource",
    "HarnessCapture",
    "SourceEntry",
    "artifact_kind",
    "build_media",
    "capture_artifacts",
    "collect_artifacts",
    "detect_content_type",
]
