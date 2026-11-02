"""Request and response bodies of the context endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from agnostic_context.application.knowledge import ContentPage, KnowledgeBase
from agnostic_context.application.learnings import DataSubjectResult, Deletion
from agnostic_context.application.memories import DuplicateReport, MemorySource, Optimization
from agnostic_context.domain.files import FileEvent, FileProvenance
from agnostic_context.domain.learnings import ID_SCHEMES

# ---------------------------------------------------------------- memories


class DuplicateOut(BaseModel):
    memory_id: str = Field(description="The memory to flag as a likely duplicate")
    duplicate_of: str = Field(description="The memory it repeats (the one to keep)")
    similarity: float = Field(description="Trigram similarity, 0–1")


class DuplicatesOut(BaseModel):
    user_id: str
    method: Literal["trigram"]
    threshold: float
    scanned: int
    total: int | None
    partial: bool = Field(description="The user has more memories than were compared")
    duplicates: list[DuplicateOut]

    @classmethod
    def of(cls, report: DuplicateReport) -> DuplicatesOut:
        return cls(
            user_id=report.user_id,
            method=report.method,
            threshold=report.threshold,
            scanned=report.scanned,
            total=report.total,
            partial=report.partial,
            duplicates=[
                DuplicateOut(memory_id=item.memory_id, duplicate_of=item.duplicate_of, similarity=item.similarity)
                for item in report.duplicates
            ],
        )


class MemorySourceOut(BaseModel):
    memory_id: str
    user_id: str | None
    agent_id: str | None
    team_id: str | None
    session_id: str | None
    run_id: str | None
    input: str | None = Field(description="What the user sent in the matched run")
    run_at: datetime | None
    run_status: str | None
    method: Literal["session_match"] = Field(
        default="session_match",
        description="Matched by user, agent and time: AgentOS doesn't return a memory's source run",
    )
    reason: str | None = Field(description="Why no run was matched")

    @classmethod
    def of(cls, source: MemorySource) -> MemorySourceOut:
        return cls(
            memory_id=source.memory_id,
            user_id=source.user_id,
            agent_id=source.agent_id,
            team_id=source.team_id,
            session_id=source.session_id,
            run_id=source.run_id,
            input=source.input,
            run_at=source.run_at,
            run_status=source.run_status,
            reason=source.reason,
        )


class OptimizeIn(BaseModel):
    user_id: str = Field(min_length=1)
    apply: bool = Field(default=False, description="False previews; True runs the optimization again and saves it")
    model: str | None = Field(default=None, description='"provider:model_id"; default: the instance\'s')
    db_id: str | None = None


class OptimizedMemoryOut(BaseModel):
    memory_id: str
    memory: str
    topics: list[str]


class OptimizeOut(BaseModel):
    user_id: str
    applied: bool
    memories: list[OptimizedMemoryOut]
    memories_before: int
    memories_after: int
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    reduction_percentage: float

    @classmethod
    def of(cls, result: Optimization) -> OptimizeOut:
        return cls(
            user_id=result.user_id,
            applied=result.applied,
            memories=[
                OptimizedMemoryOut(
                    memory_id=str(item.get("memory_id") or ""),
                    memory=str(item.get("memory") or ""),
                    topics=[str(topic) for topic in cast("list[Any]", item.get("topics") or [])],
                )
                for item in result.memories
            ],
            memories_before=result.memories_before,
            memories_after=result.memories_after,
            tokens_before=result.tokens_before,
            tokens_after=result.tokens_after,
            tokens_saved=result.tokens_saved,
            reduction_percentage=result.reduction_percentage,
        )


# ---------------------------------------------------------------- knowledge


class KnowledgeReaderOut(BaseModel):
    id: str
    kind: Literal["agent", "team"]
    name: str


class VectorDbOut(BaseModel):
    id: str
    name: str | None
    search_types: list[str]


class KnowledgeBaseOut(BaseModel):
    id: str = Field(description="The knowledge_id every knowledge route takes")
    name: str
    description: str | None
    db_id: str
    table: str
    entries: int | None = Field(description="Content entries; None when the viewer can't read them")
    vector_dbs: list[VectorDbOut]
    used_by: list[KnowledgeReaderOut] | None = Field(description="None when the viewer can't list agents and teams")

    @classmethod
    def of(cls, base: KnowledgeBase) -> KnowledgeBaseOut:
        return cls(
            id=base.id,
            name=base.name,
            description=base.description,
            db_id=base.db_id,
            table=base.table,
            entries=base.entries,
            vector_dbs=[
                VectorDbOut(id=db.id, name=db.name, search_types=list(db.search_types)) for db in base.vector_dbs
            ],
            used_by=None
            if base.used_by is None
            else [KnowledgeReaderOut(id=item.id, kind=item.kind, name=item.name) for item in base.used_by],
        )


class KnowledgeBasesOut(BaseModel):
    bases: list[KnowledgeBaseOut]


class ContentCountsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    by_kind: dict[str, int]


class ContentPageOut(BaseModel):
    data: list[dict[str, Any]] = Field(description="AgentOS ContentResponseSchema rows, plus `kind`")
    matching: int
    scanned: int
    total: int | None
    partial: bool = Field(description="Only the newest `scanned` rows were filtered and counted")
    counts: ContentCountsOut
    page: int
    limit: int

    @classmethod
    def of(cls, page: ContentPage, kinds: list[str]) -> ContentPageOut:
        return cls(
            data=[{**row, "kind": kind} for row, kind in zip(page.rows, kinds, strict=True)],
            matching=page.matching,
            scanned=page.scanned,
            total=page.total,
            partial=page.partial,
            counts=ContentCountsOut(
                total=page.counts.total, by_status=dict(page.counts.by_status), by_kind=dict(page.counts.by_kind)
            ),
            page=page.page,
            limit=page.limit,
        )


# ---------------------------------------------------------------- learnings


class LearningCountsOut(BaseModel):
    counts: dict[str, int | None] = Field(description="Records per learning type; None where AgentOS didn't answer")
    id_schemes: dict[str, str] = Field(default_factory=lambda: dict(ID_SCHEMES))


class DeleteUserLearningsIn(BaseModel):
    user_id: str = Field(min_length=1)
    learning_type: str | None = Field(default=None, description="One type only; default: every type")
    confirm: str = Field(description="The user id again, typed by the person")
    db_id: str | None = None


class DeletionOut(BaseModel):
    instance_id: str
    instance: str
    user_id: str
    learning_type: str | None
    deleted: int | None

    @classmethod
    def of(cls, deletion: Deletion) -> DeletionOut:
        return cls(
            instance_id=deletion.instance_id,
            instance=deletion.instance,
            user_id=deletion.user_id,
            learning_type=deletion.learning_type,
            deleted=deletion.deleted,
        )


class DataSubjectIn(BaseModel):
    user_id: str = Field(min_length=1, description="The person's user_id on the instances")
    confirm: str


class InstanceOutcomeOut(BaseModel):
    instance_id: str
    instance: str
    status: Literal["deleted", "skipped", "failed"]
    deleted: int | None
    reason: str | None


class DataSubjectOut(BaseModel):
    user_id: str
    outcomes: list[InstanceOutcomeOut]

    @classmethod
    def of(cls, result: DataSubjectResult) -> DataSubjectOut:
        return cls(
            user_id=result.user_id,
            outcomes=[
                InstanceOutcomeOut(
                    instance_id=item.instance_id,
                    instance=item.instance,
                    status=item.status,
                    deleted=item.deleted,
                    reason=item.reason,
                )
                for item in result.outcomes
            ],
        )


# ---------------------------------------------------------------- files


class FileEventOut(BaseModel):
    action: Literal["write", "read", "delete"]
    tool: str
    path: str
    trace_id: str
    run_id: str | None
    session_id: str | None
    component_kind: Literal["agent", "team", "workflow"] | None
    component_id: str | None
    step: str | None
    status: str
    run_status: str
    at: datetime | None

    @classmethod
    def of(cls, event: FileEvent) -> FileEventOut:
        return cls(
            action=event.action,
            tool=event.tool,
            path=event.path,
            trace_id=event.trace_id,
            run_id=event.run_id,
            session_id=event.session_id,
            component_kind=event.component_kind,
            component_id=event.component_id,
            step=event.step,
            status=event.status,
            run_status=event.run_status,
            at=event.at,
        )


class FileReaderOut(BaseModel):
    component_id: str
    step: str | None
    count: int


class FileProvenanceOut(BaseModel):
    path: str
    available: bool
    reason: str | None = Field(description="Why provenance isn't available")
    exact: bool = Field(description="From agnostic-bridge; otherwise a best-effort scan of the newest traces")
    scanned_traces: int
    written: FileEventOut | None
    partial: bool = Field(description="The run that last wrote the file ended in error")
    writes: list[FileEventOut]
    read_by: list[FileReaderOut]

    @classmethod
    def of(cls, path: str, provenance: FileProvenance | None, reason: str | None) -> FileProvenanceOut:
        if provenance is None:
            return cls(
                path=path,
                available=False,
                reason=reason,
                exact=False,
                scanned_traces=0,
                written=None,
                partial=False,
                writes=[],
                read_by=[],
            )
        return cls(
            path=provenance.path,
            available=True,
            reason=None,
            exact=provenance.exact,
            scanned_traces=provenance.scanned_traces,
            written=FileEventOut.of(provenance.written) if provenance.written else None,
            partial=provenance.partial,
            writes=[FileEventOut.of(event) for event in provenance.writes],
            read_by=[
                FileReaderOut(component_id=item.component_id, step=item.step, count=item.count)
                for item in provenance.read_by
            ],
        )
