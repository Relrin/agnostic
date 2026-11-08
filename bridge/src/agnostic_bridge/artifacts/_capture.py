"""Wire collection into agents: a post-hook for Agno agents and teams, a publish tool, and capture for harnesses.

Three ways in, all producing the same Agno media, which AgentOS stores in its media storage:

- :func:`collect_artifacts` is a run post-hook. At the end of every run it reconciles the source and attaches new
  and changed files to the run output, before the run is stored. Use it with ``E2BTools`` (collect before the
  sandbox is killed) or any agent writing to a directory.
- :class:`ArtifactTools` gives the model a ``publish_artifact`` tool, for agents that should say what they produced.
- :func:`capture_artifacts` covers Agno's harness adapters (``ClaudeAgent``, ``CodexAgent``). Run on the host, the
  harness's ``cwd`` is collected just before the run is stored. With ``sandbox=``, the workspace is read from the
  checkpoint Agno commits after the turn, when the control plane asks (``POST /agnostic/v1/artifacts/sync``).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from typing import Any

from agno.media.storage.base import AsyncMediaStorage, MediaStorage
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_warning
from agno.utils.media_offload import aoffload_run_media, offload_run_media

from agnostic_bridge.artifacts._collector import ArtifactCollector
from agnostic_bridge.artifacts._media import ARTIFACT_METADATA_KEY, attach
from agnostic_bridge.artifacts._sources import (
    ArtifactSource,
    ArtifactSourceError,
    CheckpointSource,
    DirectorySource,
    relative_to_root,
)

CAPTURE_ATTRIBUTE = "_agnostic_artifact_capture"
SYNCED_KEY = "agnostic_artifacts_synced"

SourceSpec = ArtifactSource | Callable[[Any], "ArtifactSource | Awaitable[ArtifactSource | None] | None"]


async def _resolve(spec: SourceSpec, context: Any) -> ArtifactSource | None:
    if isinstance(spec, ArtifactSource):
        return spec
    value = spec(context)
    return await value if inspect.isawaitable(value) else value


def _session_state(run_context: Any = None, session: Any = None) -> MutableMapping[str, Any] | None:
    state = getattr(run_context, "session_state", None)
    if isinstance(state, dict):
        return state
    data = getattr(session, "session_data", None)
    if isinstance(data, dict):
        return data.setdefault("session_state", {})
    return None


def collect_artifacts(source: SourceSpec, **collector: Any) -> Callable[..., Awaitable[None]]:
    """A post-hook that attaches what ``source`` holds to each run: ``Agent(post_hooks=[collect_artifacts(...)])``.

    ``source`` is an :class:`ArtifactSource` or a callable taking the ``RunContext`` and returning one (for a source
    per session). Keyword arguments go to :class:`ArtifactCollector` (``include``, ``exclude``, limits). The agent
    needs ``media_storage=`` so the files are stored outside the session row.
    """

    async def collect_run_artifacts(run_output: Any, run_context: Any = None, session: Any = None) -> None:
        resolved = await _resolve(source, run_context)
        if resolved is None:
            return
        found = await ArtifactCollector(resolved, **collector).collect(_session_state(run_context, session))
        attach(run_output, found)

    return collect_run_artifacts


class ArtifactTools(Toolkit):
    """``publish_artifact(path, title)``: the model hands a file it wrote to the person, as an artefact of the run."""

    def __init__(self, source: SourceSpec, *, max_file_bytes: int = 25 * 1024 * 1024, **kwargs: Any) -> None:
        self._source = source
        self._max_file_bytes = max_file_bytes
        super().__init__(name="artifact_tools", tools=[self.publish_artifact], **kwargs)

    async def publish_artifact(self, path: str, title: str | None = None, run_context: Any = None) -> ToolResult:
        """Publish a file from the workspace so the person can view, download and share it.

        Args:
            path: The file's path in the workspace, as you wrote it.
            title: A short human title for the file (optional).
        """
        source = await _resolve(self._source, run_context)
        if source is None:
            return ToolResult(content="No workspace is attached to this run, so nothing was published.")
        try:
            relative = relative_to_root(path, str(getattr(source, "root", "")))
        except ArtifactSourceError as error:
            return ToolResult(content=f"Not published: {error}")
        collector = ArtifactCollector(source, max_file_bytes=self._max_file_bytes, producer="publish_artifact")
        found = await collector.collect(_session_state(run_context), paths=[relative])
        if not found:
            return ToolResult(content=f"{relative} was already published unchanged, or it does not exist.")
        for media in found:
            if title and isinstance(media.metadata, dict):
                media.metadata[ARTIFACT_METADATA_KEY]["title"] = title
        kinds: dict[str, list[Any]] = {"images": [], "audios": [], "videos": [], "files": []}
        for media in found:
            kinds[{"Image": "images", "Audio": "audios", "Video": "videos"}.get(type(media).__name__, "files")].append(
                media
            )
        return ToolResult(
            content=f"Published {relative}.",
            images=kinds["images"] or None,
            audios=kinds["audios"] or None,
            videos=kinds["videos"] or None,
            files=kinds["files"] or None,
        )


async def _offload(run_output: Any, storage: MediaStorage | AsyncMediaStorage, session_id: str) -> None:
    if isinstance(storage, AsyncMediaStorage):
        await aoffload_run_media(run_output, storage, session_id)
    else:
        await asyncio.to_thread(offload_run_media, run_output, storage, session_id)


class HarnessCapture:
    """What :func:`capture_artifacts` keeps on a harness adapter; the bridge's sync route reads it."""

    def __init__(
        self,
        agent: Any,
        *,
        media_storage: MediaStorage | AsyncMediaStorage,
        root: str,
        include: Sequence[str],
        collector: dict[str, Any],
    ) -> None:
        self.agent = agent
        self.media_storage = media_storage
        self.root = root
        self.include = include
        self.collector = collector

    @property
    def sandboxed(self) -> bool:
        return getattr(self.agent, "sandbox", None) is not None

    def local_source(self) -> ArtifactSource:
        cwd = getattr(self.agent, "cwd", None) or "."
        return DirectorySource(cwd)

    async def source_for(self, session: Any) -> ArtifactSource | None:
        """Where this session's files are: the agent's own source when it has one (a coding agent's live
        sandbox), else its ``cwd`` on this host."""
        own = getattr(self.agent, "artifact_source", None)
        if callable(own):
            return await _resolve(own, session)
        return self.local_source()

    def checkpoint_source(self, run_id: str) -> ArtifactSource:
        return CheckpointSource(lambda: self.agent.aopen_run_checkpoint(run_id), root=self.root)

    async def collect_into(
        self, run_output: Any, source: ArtifactSource, state: MutableMapping[str, Any] | None
    ) -> int:
        include = self.include if not isinstance(source, CheckpointSource) else ("**",)
        collector = ArtifactCollector(source, include=include, producer=type(self.agent).__name__, **self.collector)
        media = await collector.collect(state)
        if not media:
            return 0
        attach(run_output, media)
        return len(media)


def capture_artifacts(
    agent: Any,
    *,
    media_storage: MediaStorage | AsyncMediaStorage,
    root: str = "outputs",
    include: Sequence[str] | None = None,
    **collector: Any,
) -> Any:
    """Collect what a harness adapter (``ClaudeAgent``, ``CodexAgent``, a coding agent) writes under ``root`` of its
    workspace.

    On the host the workspace is the adapter's ``cwd`` and files are collected as each run is stored. With
    ``sandbox=`` they are read from the turn's checkpoint when the control plane syncs the session. Pass the same
    ``media_storage`` to ``AgentOS(media_storage=...)`` so its media route can serve them. Returns ``agent``.
    """
    capture = HarnessCapture(
        agent,
        media_storage=media_storage,
        root=root,
        include=tuple(include) if include is not None else (f"{root.strip('/')}/**",),
        collector=collector,
    )
    setattr(agent, CAPTURE_ATTRIBUTE, capture)
    if capture.sandboxed:
        return agent

    persist = agent._apersist_run_in_session  # the one write every host-side run goes through

    async def persist_with_artifacts(session: Any, run_output: Any, *, strict: bool = False) -> None:
        status = str(getattr(run_output, "status", "") or "").lower()
        if "completed" in status:
            try:
                source = await capture.source_for(session)
                count = (
                    await capture.collect_into(run_output, source, _session_state(None, session))
                    if source is not None
                    else 0
                )
                if count:
                    await _offload(run_output, media_storage, session.session_id)
            except Exception as error:  # an artefact problem must never lose the run itself
                log_warning(f"Artifacts: collection failed for run {getattr(run_output, 'run_id', '?')}: {error}")
        await persist(session, run_output, strict=strict)

    agent._apersist_run_in_session = persist_with_artifacts
    return agent


def harness_capture(component: Any) -> HarnessCapture | None:
    capture = getattr(component, CAPTURE_ATTRIBUTE, None)
    return capture if isinstance(capture, HarnessCapture) else None


async def sync_sandbox_session(capture: HarnessCapture, session: Any) -> list[Any]:
    """Collect from the checkpoints of a sandboxed session's completed runs not synced yet; returns those runs."""
    changed: list[Any] = []
    state = _session_state(None, session)
    for run in getattr(session, "runs", None) or []:
        metadata = run.metadata if isinstance(getattr(run, "metadata", None), dict) else {}
        status = str(getattr(run, "status", "") or "").lower()
        if metadata.get(SYNCED_KEY) or "completed" not in status:
            continue
        if not (metadata.get("sandbox") or {}).get("checkpoint"):
            continue
        try:
            count = await capture.collect_into(run, capture.checkpoint_source(run.run_id), state)
        except Exception as error:
            log_warning(f"Artifacts: cannot read the checkpoint of run {run.run_id}: {error}")
            continue
        if count:
            await _offload(run, capture.media_storage, session.session_id)
        run.metadata = {**metadata, SYNCED_KEY: True}
        changed.append(run)
    return changed
