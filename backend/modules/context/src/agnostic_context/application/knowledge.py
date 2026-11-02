"""Knowledge bases with their facts and readers ("Used by"), and content filtered the way AgentOS can't filter it."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from agnostic_context.application.calls import ContextCalls, page_items
from agnostic_context.domain.knowledge import (
    ContentCounts,
    ContentFilter,
    KnowledgeReader,
    count,
    used_by,
)
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal

PAGE = 100


@dataclass(frozen=True, slots=True)
class VectorDb:
    id: str
    name: str | None
    search_types: Sequence[str]


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    id: str
    name: str
    description: str | None
    db_id: str
    table: str
    entries: int | None
    vector_dbs: Sequence[VectorDb]
    used_by: Sequence[KnowledgeReader] | None
    """``None`` when the viewer can't list agents and teams."""


def _readers(payload: object, kind: Literal["agent", "team"]) -> list[KnowledgeReader]:
    items = cast("list[Any]", payload) if isinstance(payload, list) else page_items(payload)[0]
    readers: list[KnowledgeReader] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = cast("dict[str, Any]", raw)
        knowledge = item.get("knowledge")
        if not item.get("id") or not isinstance(knowledge, dict):
            continue
        config = cast("dict[str, Any]", knowledge)
        table = config.get("knowledge_table")
        if not table:
            continue
        readers.append(
            KnowledgeReader(
                id=str(item["id"]),
                kind=kind,
                name=str(item.get("name") or item["id"]),
                db_id=cast("str | None", config.get("db_id")),
                table=str(table),
            )
        )
    return readers


class ListKnowledgeBases:
    """``/config`` knowledge instances, each with its entry count, vector databases and the agents that read it."""

    def __init__(self, calls: ContextCalls) -> None:
        self._calls = calls

    async def __call__(self, principal: Principal, instance_ref: str) -> list[KnowledgeBase]:
        instance = await self._calls.instance(instance_ref)
        config = cast("dict[str, Any]", await self._calls.json(principal, instance, "/config"))
        section = cast("dict[str, Any]", config.get("knowledge") or {})
        bases = [cast("dict[str, Any]", item) for item in cast("list[Any]", section.get("knowledge_instances") or [])]
        if not bases:
            return []
        readers = await self._all_readers(principal, instance)
        return list(await asyncio.gather(*(self._base(principal, instance, base, readers) for base in bases)))

    async def _all_readers(self, principal: Principal, instance: Instance) -> list[KnowledgeReader] | None:
        agents, teams = await asyncio.gather(
            self._calls.call(principal, instance, "GET", "/agents"),
            self._calls.call(principal, instance, "GET", "/teams"),
        )
        if not agents.ok and not teams.ok:
            return None
        return [
            *(_readers(agents.body, "agent") if agents.ok else []),
            *(_readers(teams.body, "team") if teams.ok else []),
        ]

    async def _base(
        self,
        principal: Principal,
        instance: Instance,
        base: dict[str, Any],
        readers: list[KnowledgeReader] | None,
    ) -> KnowledgeBase:
        knowledge_id = str(base.get("id") or "")
        content, settings = await asyncio.gather(
            self._calls.call(
                principal, instance, "GET", "/knowledge/content", params={"knowledge_id": knowledge_id, "limit": 1}
            ),
            self._calls.call(principal, instance, "GET", "/knowledge/config", params={"knowledge_id": knowledge_id}),
        )
        vector_dbs: list[VectorDb] = []
        if settings.ok and isinstance(settings.body, dict):
            for raw in cast("list[Any]", cast("dict[str, Any]", settings.body).get("vector_dbs") or []):
                if isinstance(raw, dict):
                    item = cast("dict[str, Any]", raw)
                    vector_dbs.append(
                        VectorDb(
                            id=str(item.get("id") or ""),
                            name=cast("str | None", item.get("name")),
                            search_types=[str(kind) for kind in cast("list[Any]", item.get("search_types") or [])],
                        )
                    )
        db_id, table = str(base.get("db_id") or ""), str(base.get("table") or "")
        return KnowledgeBase(
            id=knowledge_id,
            name=str(base.get("name") or knowledge_id),
            description=cast("str | None", base.get("description")),
            db_id=db_id,
            table=table,
            entries=page_items(content.body)[1] if content.ok else None,
            vector_dbs=vector_dbs,
            used_by=None if readers is None else used_by(db_id, table, readers),
        )


@dataclass(frozen=True, slots=True)
class ContentPage:
    rows: Sequence[dict[str, Any]]
    matching: int
    """Rows of the scanned set that match the filters."""
    scanned: int
    total: int | None
    """Content rows in the knowledge base, as AgentOS counts them."""
    counts: ContentCounts
    """Over every scanned row, filters ignored (the failed/processing counters)."""
    page: int
    limit: int

    @property
    def partial(self) -> bool:
        return self.total is not None and self.total > self.scanned


class ListContent:
    """Reads the newest content rows (bounded), then filters, counts and pages them."""

    def __init__(self, calls: ContextCalls, max_pages: int) -> None:
        self._calls = calls
        self._max_pages = max_pages

    async def __call__(
        self,
        principal: Principal,
        instance_ref: str,
        knowledge_id: str | None,
        content_filter: ContentFilter,
        *,
        page: int = 1,
        limit: int = 20,
    ) -> ContentPage:
        instance = await self._calls.instance(instance_ref)
        rows: list[dict[str, Any]] = []
        total: int | None = None
        for number in range(1, self._max_pages + 1):
            body = await self._calls.json(
                principal,
                instance,
                "/knowledge/content",
                params={
                    "knowledge_id": knowledge_id,
                    "page": number,
                    "limit": PAGE,
                    "sort_by": "updated_at",
                    "sort_order": "desc",
                },
            )
            items, total = page_items(body)
            rows.extend(items)
            if len(items) < PAGE or (total is not None and len(rows) >= total):
                break
        matching = [row for row in rows if content_filter.matches(row)]
        start = (page - 1) * limit
        return ContentPage(
            rows=matching[start : start + limit],
            matching=len(matching),
            scanned=len(rows),
            total=total,
            counts=count(rows),
            page=page,
            limit=limit,
        )
