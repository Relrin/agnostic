"""HTTP routes of the context module.

Memory duplicates, source and optimization; knowledge bases and filtered content; learning counts and per-user
deletion; file provenance; and the org-wide data-subject request.
"""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from agnostic_context.api.schemas import (
    ContentPageOut,
    DataSubjectIn,
    DataSubjectOut,
    DeleteUserLearningsIn,
    DeletionOut,
    DuplicatesOut,
    FileProvenanceOut,
    KnowledgeBaseOut,
    KnowledgeBasesOut,
    LearningCountsOut,
    MemorySourceOut,
    OptimizeIn,
    OptimizeOut,
)
from agnostic_context.application.files import FindFileProvenance
from agnostic_context.application.knowledge import ListContent, ListKnowledgeBases
from agnostic_context.application.learnings import DataSubjectRequest, DeleteUserLearnings, LearningCounts
from agnostic_context.application.memories import FindDuplicates, FindMemorySource, OptimizeMemories
from agnostic_context.domain.knowledge import ContentFilter, content_kind
from agnostic_kernel.auth import Principal

router = APIRouter(route_class=DishkaRoute)
org_router = APIRouter(route_class=DishkaRoute)

DbId = Annotated[str | None, Query(description="Database id from /config (several memory or learning databases)")]


@router.get(
    "/{instance}/memories/duplicates",
    summary="Likely duplicate memories of one user (trigram similarity; needs memories:read)",
)
async def memory_duplicates(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[FindDuplicates],
    user_id: Annotated[str, Query(min_length=1)],
    db_id: DbId = None,
) -> DuplicatesOut:
    return DuplicatesOut.of(await use_case(principal, instance, user_id, db_id=db_id))


@router.get(
    "/{instance}/memories/{memory_id}/source",
    summary="The run a memory most likely came from: its session and the input the user sent (best effort)",
)
async def memory_source(
    instance: str,
    memory_id: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[FindMemorySource],
    db_id: DbId = None,
) -> MemorySourceOut:
    return MemorySourceOut.of(await use_case(principal, instance, memory_id, db_id=db_id))


@router.post(
    "/{instance}/memories/optimize",
    summary="Preview (apply=false) or apply the summarize optimization of a user's memories (needs memories:write)",
)
async def optimize_memories(
    instance: str, body: OptimizeIn, principal: FromDishka[Principal], use_case: FromDishka[OptimizeMemories]
) -> OptimizeOut:
    result = await use_case(principal, instance, body.user_id, apply=body.apply, model=body.model, db_id=body.db_id)
    return OptimizeOut.of(result)


@router.get(
    "/{instance}/knowledge/bases",
    summary="Knowledge bases with entry counts, vector databases and the agents and teams that read them",
)
async def knowledge_bases(
    instance: str, principal: FromDishka[Principal], use_case: FromDishka[ListKnowledgeBases]
) -> KnowledgeBasesOut:
    return KnowledgeBasesOut(bases=[KnowledgeBaseOut.of(base) for base in await use_case(principal, instance)])


@router.get(
    "/{instance}/knowledge/content",
    summary="Knowledge content filtered by status, type and text, with status and type counts (needs knowledge:read)",
)
async def knowledge_content(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[ListContent],
    knowledge_id: str | None = None,
    status: Annotated[str | None, Query(description="completed, processing, partial or failed")] = None,
    kind: Annotated[
        str | None, Query(alias="type", description='"Markdown", "PDF", "URL"… (the `kind` column)')
    ] = None,
    search: Annotated[str | None, Query(description="Text in the name, description or metadata")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ContentPageOut:
    result = await use_case(
        principal,
        instance,
        knowledge_id,
        ContentFilter(status=status, kind=kind, search=search),
        page=page,
        limit=limit,
    )
    return ContentPageOut.of(result, [content_kind(row.get("type"), row.get("name")) for row in result.rows])


@router.get("/{instance}/learnings/counts", summary="Learning records per type (needs learnings:read)")
async def learning_counts(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[LearningCounts],
    user_id: str | None = None,
    agent_id: str | None = None,
    namespace: str | None = None,
    db_id: DbId = None,
) -> LearningCountsOut:
    counts = await use_case(principal, instance, user_id=user_id, agent_id=agent_id, namespace=namespace, db_id=db_id)
    return LearningCountsOut(counts=counts)


@router.post(
    "/{instance}/learnings/delete-user",
    summary="Delete one user's learnings, or one type of them, after typing the user id (needs learnings:delete)",
)
async def delete_user_learnings(
    instance: str,
    body: DeleteUserLearningsIn,
    principal: FromDishka[Principal],
    use_case: FromDishka[DeleteUserLearnings],
) -> DeletionOut:
    deletion = await use_case(
        principal, instance, body.user_id, body.confirm, learning_type=body.learning_type, db_id=body.db_id
    )
    return DeletionOut.of(deletion)


@router.get(
    "/{instance}/files/provenance",
    summary="Which runs wrote and read a workspace file (exact with agnostic-bridge, otherwise best effort)",
)
async def file_provenance(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[FindFileProvenance],
    path: Annotated[str, Query(min_length=1)],
    namespace: str | None = None,
) -> FileProvenanceOut:
    provenance, reason = await use_case(principal, instance, path, namespace=namespace)
    return FileProvenanceOut.of(path, provenance, reason)


@org_router.post(
    "/context/data-subject-requests",
    summary="Delete one person's learnings on every instance where you hold learnings:delete",
)
async def data_subject_request(
    body: DataSubjectIn, principal: FromDishka[Principal], use_case: FromDishka[DataSubjectRequest]
) -> DataSubjectOut:
    return DataSubjectOut.of(await use_case(principal, body.user_id, body.confirm))
