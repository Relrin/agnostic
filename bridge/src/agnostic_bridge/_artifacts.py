"""``/agnostic/v1/artifacts``: the artefacts a session's runs carry, the newest across sessions, and a sync.

AgentOS stores run media and serves one object at a time (``GET /sessions/{id}/media/{storage_key}``), but has no
route that says which media a session holds. These routes read the stored runs and return one row per stored media
object, with what ``agnostic_bridge.artifacts`` recorded about its origin (path, source, hash, revision).

- **Access**: ``sessions:read`` (sync: ``sessions:write``). Under user isolation a caller sees their own sessions only,
  as on ``GET /sessions``.
- **Sync** collects from the sandbox checkpoints of harness adapters set up with ``capture_artifacts`` (a sandboxed
  ``ClaudeAgent``/``CodexAgent``), which store their runs where no post-hook can reach. It is a no-op otherwise.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.db.utils import resolve_session_type
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.utils.media_offload import iter_run_media
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agnostic_bridge.artifacts._capture import harness_capture, sync_sandbox_session
from agnostic_bridge.artifacts._media import ARTIFACT_METADATA_KEY, artifact_kind

if TYPE_CHECKING:
    from agno.os import AgentOS

ARTIFACTS_PATH = "/artifacts"
RECENT_ARTIFACTS_PATH = "/artifacts/recent"
SYNC_ARTIFACTS_PATH = "/artifacts/sync"

Kind = Literal["image", "audio", "video", "file"]
ComponentKind = Literal["agent", "team", "workflow"]


class Artifact(BaseModel):
    id: str = Field(description="Agno media id")
    storage_key: str = Field(description="Key for GET /sessions/{session_id}/media/{storage_key}")
    session_id: str
    run_id: str | None = None
    component_kind: ComponentKind | None = None
    component_id: str | None = None
    kind: Kind
    filename: str
    title: str
    content_type: str
    size: int | None = None
    sha256: str | None = None
    path: str | None = Field(None, description="Where the harness wrote it, relative to the collected root")
    source: str | None = Field(None, description="directory, e2b, sandbox, or the tool that produced it")
    producer: str | None = None
    revision: int = 1
    role: Literal["output", "input"] = Field(description="Produced by the run, or attached by the person")
    created_at: datetime | None = None


class ArtifactList(BaseModel):
    data: list[Artifact]
    scanned_sessions: int


class SyncInput(BaseModel):
    session_id: str = Field(min_length=1)


class SyncResult(BaseModel):
    session_id: str
    runs_synced: int
    artifacts: int


async def _db_call(db: BaseDb | AsyncBaseDb, method: str, *args: Any, **kwargs: Any) -> Any:
    function = getattr(db, method)
    if isinstance(db, AsyncBaseDb):
        return await function(*args, **kwargs)
    return await asyncio.to_thread(function, *args, **kwargs)


def _time(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def _component(session: Any, run: Any) -> tuple[ComponentKind | None, str | None]:
    for kind, attribute in (("workflow", "workflow_id"), ("team", "team_id"), ("agent", "agent_id")):
        value = getattr(run, attribute, None) or getattr(session, attribute, None)
        if value:
            return kind, str(value)  # type: ignore[return-value]
    return None, None


def _input_ids(run: Any) -> set[str]:
    run_input = getattr(run, "input", None)
    return {
        str(getattr(media, "id", ""))
        for attribute in ("images", "videos", "audios", "files")
        for media in getattr(run_input, attribute, None) or []
    }


def session_artifacts(session: Any, *, include_inputs: bool = False) -> list[Artifact]:
    """One row per stored media object in the session's runs, newest run first, deduplicated by storage key."""
    rows: list[Artifact] = []
    seen: set[str] = set()
    for run in reversed(getattr(session, "runs", None) or []):
        kind_of_component, component = _component(session, run)
        inputs = _input_ids(run)
        for media in iter_run_media(run):
            reference = getattr(media, "media_reference", None)
            key = getattr(reference, "storage_key", None)
            if not key or key in seen:
                continue
            role: Literal["output", "input"] = "input" if str(getattr(media, "id", "")) in inputs else "output"
            if role == "input" and not include_inputs:
                continue
            seen.add(key)
            metadata = getattr(media, "metadata", None) or getattr(reference, "metadata", None) or {}
            info = metadata.get(ARTIFACT_METADATA_KEY, {}) if isinstance(metadata, dict) else {}
            content_type = str(
                info.get("content_type") or getattr(reference, "mime_type", None) or getattr(media, "mime_type", None)
                or "application/octet-stream"
            )  # fmt: skip
            filename = str(
                info.get("filename") or getattr(reference, "filename", None) or getattr(media, "filename", None)
                or key.rsplit("/", 1)[-1]
            )  # fmt: skip
            rows.append(
                Artifact(
                    id=str(getattr(media, "id", None) or key),
                    storage_key=key,
                    session_id=str(getattr(session, "session_id", "")),
                    run_id=getattr(run, "run_id", None),
                    component_kind=kind_of_component,
                    component_id=component,
                    kind=artifact_kind(content_type),  # type: ignore[arg-type]
                    filename=filename,
                    title=str(info.get("title") or filename),
                    content_type=content_type,
                    size=info.get("size") or getattr(reference, "size", None),
                    sha256=info.get("sha256") or getattr(reference, "content_hash", None),
                    path=info.get("path"),
                    source=info.get("source"),
                    producer=info.get("producer"),
                    revision=int(info.get("revision") or 1),
                    role=role,
                    created_at=_time(getattr(run, "created_at", None)),
                )
            )
    return rows


def _os_db(agent_os: AgentOS) -> BaseDb | AsyncBaseDb:
    db = agent_os.db
    if not isinstance(db, (BaseDb, AsyncBaseDb)):
        raise HTTPException(status_code=503, detail="This AgentOS has no db, so no stored runs to read")
    return db


async def _load_session(db: BaseDb | AsyncBaseDb, session_id: str, user_id: str | None) -> Any:
    session_type, _ = await resolve_session_type(db, session_id, None, user_id)
    if session_type is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    session = await _db_call(db, "get_session", session_id=session_id, session_type=session_type, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session


def _find_component(agent_os: AgentOS, component_id: str | None) -> Any:
    for agent in agent_os.agents or []:
        if component_id and getattr(agent, "id", None) == component_id:
            return agent
    return None


def add_artifact_routes(router: APIRouter, agent_os: AgentOS) -> None:
    @router.get(
        ARTIFACTS_PATH,
        operation_id="agnostic_bridge_list_artifacts",
        summary="Artefacts of a session",
        description="Stored media of the session's runs, newest run first. Needs sessions:read.",
        response_model=ArtifactList,
    )
    async def list_artifacts(
        request: Request,
        session_id: str = Query(..., min_length=1),
        run_id: str | None = Query(None),
        kind: Kind | None = None,
        include_inputs: bool = Query(False, description="Also list files the person attached"),
    ) -> ArtifactList:
        session = await _load_session(_os_db(agent_os), session_id, get_scoped_user_id(request))
        rows = session_artifacts(session, include_inputs=include_inputs)
        rows = [row for row in rows if (run_id is None or row.run_id == run_id) and (kind is None or row.kind == kind)]
        return ArtifactList(data=rows, scanned_sessions=1)

    @router.get(
        RECENT_ARTIFACTS_PATH,
        operation_id="agnostic_bridge_recent_artifacts",
        summary="Newest artefacts across sessions",
        description="Artefacts of the most recently updated sessions, newest first. Needs sessions:read.",
        response_model=ArtifactList,
    )
    async def recent_artifacts(
        request: Request,
        sessions: int = Query(30, ge=1, le=200, description="Most recently updated sessions to read"),
        limit: int = Query(200, ge=1, le=1000),
        component_id: str | None = Query(None),
        kind: Kind | None = None,
    ) -> ArtifactList:
        db = _os_db(agent_os)
        user_id = get_scoped_user_id(request)
        found: list[Any] = []
        for session_type in (SessionType.AGENT, SessionType.TEAM, SessionType.WORKFLOW):
            result = await _db_call(
                db,
                "get_sessions",
                session_type=session_type,
                user_id=user_id,
                component_id=component_id,
                limit=sessions,
                page=1,
                sort_by="updated_at",
                sort_order="desc",
            )
            found.extend(result[0] if isinstance(result, tuple) else result or [])
        found.sort(key=lambda item: getattr(item, "updated_at", None) or 0, reverse=True)
        found = found[:sessions]
        rows = [row for session in found for row in session_artifacts(session) if kind is None or row.kind == kind]
        floor = datetime.min.replace(tzinfo=timezone.utc)
        rows.sort(key=lambda row: row.created_at or floor, reverse=True)
        return ArtifactList(data=rows[:limit], scanned_sessions=len(found))

    @router.post(
        SYNC_ARTIFACTS_PATH,
        operation_id="agnostic_bridge_sync_artifacts",
        summary="Collect artefacts from sandbox checkpoints",
        description=(
            "For a session of a harness adapter set up with capture_artifacts and a sandbox, read its completed "
            "runs' checkpoints and store what they produced. A no-op for other sessions. Needs sessions:write."
        ),
        response_model=SyncResult,
    )
    async def sync_artifacts(request: Request, body: SyncInput) -> SyncResult:
        db = _os_db(agent_os)
        session = await _load_session(db, body.session_id, get_scoped_user_id(request))
        capture = harness_capture(_find_component(agent_os, getattr(session, "agent_id", None)))
        if capture is None or not capture.sandboxed:
            return SyncResult(session_id=body.session_id, runs_synced=0, artifacts=0)
        changed = await sync_sandbox_session(capture, session)
        for run in changed:
            await _db_call(
                db, "upsert_run", run=run, session_id=session.session_id, user_id=getattr(session, "user_id", None)
            )
        if changed:
            await _db_call(db, "upsert_session", session)
        count = sum(1 for run in changed for media in iter_run_media(run) if getattr(media, "media_reference", None))
        return SyncResult(session_id=body.session_id, runs_synced=len(changed), artifacts=count)
