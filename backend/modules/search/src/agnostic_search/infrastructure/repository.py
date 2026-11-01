"""The search index: full-text + prefix matching on PostgreSQL, LIKE on SQLite."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.db import utcnow
from agnostic_kernel.modules import SearchDocument
from agnostic_search.application.ports import Hit
from agnostic_search.domain.query import like_pattern, prefix_tsquery
from agnostic_search.infrastructure.tables import SearchDocumentRow

_PG_QUERY = text(
    r"""
    SELECT kind, ref, instance_id, title, body, url_path, required_scope,
           (CASE WHEN CAST(:tsq AS text) IS NULL THEN 0 ELSE ts_rank(tsv, to_tsquery('simple', :tsq)) END)
           + (CASE WHEN lower(title) LIKE :prefix ESCAPE '\' THEN 1 ELSE 0 END)
           + (CASE WHEN ref = :exact THEN 2 ELSE 0 END) AS score
      FROM agnostic.search_documents
     WHERE ((CAST(:tsq AS text) IS NOT NULL AND tsv @@ to_tsquery('simple', :tsq))
            OR lower(title) LIKE :like ESCAPE '\'
            OR ref = :exact)
       AND (CAST(:instance AS text) IS NULL OR instance_id IS NULL OR instance_id = :instance OR kind = 'instance')
     ORDER BY score DESC, title
     LIMIT :limit
    """
)


def _doc_id(provider: str, document: SearchDocument) -> str:
    return f"{provider}:{document.kind}:{document.instance_id or '-'}:{document.ref}"[:400]


def _prefix(pattern: str) -> str:
    """``%text%`` → ``text%``."""
    return pattern[1:]


class SqlSearchIndex:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace(self, provider: str, documents: Sequence[SearchDocument]) -> None:
        _ = await self._session.execute(delete(SearchDocumentRow).where(SearchDocumentRow.provider == provider))
        now = utcnow()
        rows: dict[str, dict[str, Any]] = {}
        for document in documents:
            key = _doc_id(provider, document)
            rows[key] = {
                "id": key,
                "provider": provider,
                "kind": document.kind,
                "ref": document.ref[:200],
                "instance_id": document.instance_id,
                "title": document.title[:300],
                "body": document.body,
                "url_path": document.url_path[:500],
                "required_scope": document.required_scope,
                "updated_at": now,
            }
        if rows:
            _ = await self._session.execute(insert(SearchDocumentRow), list(rows.values()))

    async def count(self) -> int:
        return int(await self._session.scalar(select(func.count()).select_from(SearchDocumentRow)) or 0)

    async def query(self, text: str, *, instance_id: str | None, limit: int) -> list[Hit]:
        if self._session.get_bind().dialect.name == "postgresql":
            return await self._postgres(text, instance_id, limit)
        return await self._like(text, instance_id, limit)

    async def _postgres(self, value: str, instance_id: str | None, limit: int) -> list[Hit]:
        pattern = like_pattern(value)
        result = await self._session.execute(
            _PG_QUERY,
            {
                "tsq": prefix_tsquery(value),
                "like": pattern,
                "prefix": _prefix(pattern),
                "exact": value.strip(),
                "instance": instance_id,
                "limit": limit,
            },
        )
        return [
            Hit(
                kind=row.kind,
                ref=row.ref,
                instance_id=row.instance_id,
                title=row.title,
                body=row.body,
                url_path=row.url_path,
                required_scope=row.required_scope,
                score=float(row.score),
            )
            for row in result.all()
        ]

    async def _like(self, value: str, instance_id: str | None, limit: int) -> list[Hit]:
        pattern = like_pattern(value)
        row = SearchDocumentRow
        statement = select(row).where(
            or_(
                func.lower(row.title).like(pattern, escape="\\"),
                func.lower(row.body).like(pattern, escape="\\"),
                func.lower(row.ref).like(pattern, escape="\\"),
            )
        )
        if instance_id is not None:
            statement = statement.where(
                or_(row.instance_id.is_(None), row.instance_id == instance_id, row.kind == "instance")
            )
        found = (await self._session.scalars(statement.limit(limit * 4))).all()
        typed = value.strip().lower()
        hits = [
            Hit(
                kind=item.kind,
                ref=item.ref,
                instance_id=item.instance_id,
                title=item.title,
                body=item.body,
                url_path=item.url_path,
                required_scope=item.required_scope,
                score=(2.0 if item.ref == value.strip() else 0.0)
                + (1.0 if item.title.lower().startswith(typed) else 0.0),
            )
            for item in found
        ]
        hits.sort(key=lambda hit: (-hit.score, hit.title))
        return hits[:limit]
