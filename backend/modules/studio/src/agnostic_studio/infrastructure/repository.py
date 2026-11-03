"""SQL implementation of the studio store."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.db import aware, aware_or_none, utcnow
from agnostic_studio.domain.model import CanvasLayout, CodeDocument, ComponentMeta, Kind, VersionMeta
from agnostic_studio.domain.promotion import Promotion, PromotionStatus
from agnostic_studio.domain.usage import IndexEntry, UsedBy
from agnostic_studio.infrastructure.tables import (
    CanvasLayoutRow,
    CodeDocumentRow,
    ComponentMetaRow,
    PromotionRow,
    RegistryIndexRow,
    VersionMetaRow,
)


class SqlStudioStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---------------------------------------------------------------- component meta

    async def component_meta(self, instance_id: str, component_id: str) -> ComponentMeta | None:
        row = await self._session.get(ComponentMetaRow, (instance_id, component_id))
        return _component(row) if row is not None else None

    async def component_metas(self, instance_id: str) -> dict[str, ComponentMeta]:
        rows = await self._session.scalars(select(ComponentMetaRow).where(ComponentMetaRow.instance_id == instance_id))
        return {row.component_id: _component(row) for row in rows}

    async def save_component_meta(self, meta: ComponentMeta) -> None:
        row = await self._session.get(ComponentMetaRow, (meta.instance_id, meta.component_id))
        if row is None:
            row = ComponentMetaRow(instance_id=meta.instance_id, component_id=meta.component_id)
            self._session.add(row)
        row.kind = meta.kind
        row.owner_group_id = meta.owner_group_id
        row.labels = list(meta.labels)
        row.last_known_current_version = meta.last_known_current_version
        row.source_binding_id = meta.source_binding_id
        row.code_path = meta.code_path
        row.convention = meta.convention
        row.updated_at = utcnow()

    # ---------------------------------------------------------------- version meta

    async def version_metas(self, instance_id: str, component_id: str) -> dict[int, VersionMeta]:
        rows = await self._session.scalars(
            select(VersionMetaRow).where(
                VersionMetaRow.instance_id == instance_id, VersionMetaRow.component_id == component_id
            )
        )
        return {row.version: _version(row) for row in rows}

    async def version_meta(self, instance_id: str, component_id: str, version: int) -> VersionMeta | None:
        row = await self._session.get(VersionMetaRow, (instance_id, component_id, version))
        return _version(row) if row is not None else None

    async def save_version_meta(self, meta: VersionMeta) -> None:
        row = await self._session.get(VersionMetaRow, (meta.instance_id, meta.component_id, meta.version))
        if row is None:
            row = VersionMetaRow(instance_id=meta.instance_id, component_id=meta.component_id, version=meta.version)
            self._session.add(row)
        for key, value in asdict(meta).items():
            if key not in {"instance_id", "component_id", "version"}:
                setattr(row, key, value)

    # ---------------------------------------------------------------- used-by index

    async def replace_index(self, instance_id: str, snapshot_hash: str, entries: list[IndexEntry]) -> None:
        await self._session.execute(delete(RegistryIndexRow).where(RegistryIndexRow.instance_id == instance_id))
        for entry in entries:
            self._session.add(
                RegistryIndexRow(
                    instance_id=instance_id,
                    entry_type=entry.entry_type,
                    name=entry.name,
                    snapshot_hash=snapshot_hash,
                    used_by=[_used_by_dict(item) for item in entry.used_by],
                    indexed_at=entry.indexed_at,
                )
            )

    async def index(self, instance_id: str) -> list[IndexEntry]:
        rows = await self._session.scalars(select(RegistryIndexRow).where(RegistryIndexRow.instance_id == instance_id))
        return [
            IndexEntry(
                entry_type=row.entry_type,
                name=row.name,
                used_by=[_used_by(item) for item in row.used_by],
                indexed_at=aware(row.indexed_at),
            )
            for row in rows
        ]

    # ---------------------------------------------------------------- promotions

    async def add_promotion(self, promotion: Promotion) -> None:
        self._session.add(PromotionRow(**asdict(promotion)))

    async def save_promotion(self, promotion: Promotion) -> None:
        row = await self._session.get(PromotionRow, promotion.id)
        if row is None:
            await self.add_promotion(promotion)
            return
        for key, value in asdict(promotion).items():
            setattr(row, key, value)

    async def promotion(self, promotion_id: str) -> Promotion | None:
        row = await self._session.get(PromotionRow, promotion_id)
        return _promotion(row) if row is not None else None

    async def promotions(self, instance_id: str, component_id: str, limit: int = 20) -> list[Promotion]:
        rows = await self._session.scalars(
            select(PromotionRow)
            .where(PromotionRow.from_instance == instance_id, PromotionRow.component_id == component_id)
            .order_by(PromotionRow.created_at.desc())
            .limit(limit)
        )
        return [_promotion(row) for row in rows]

    # ---------------------------------------------------------------- canvas layouts & code documents

    async def canvas_layout(self, instance_id: str, component_id: str, version: int) -> CanvasLayout | None:
        row = await self._session.get(CanvasLayoutRow, (instance_id, component_id, version))
        if row is None:
            return None
        return CanvasLayout(
            row.instance_id, row.component_id, row.version, dict(row.layout), row.updated_by, aware(row.updated_at)
        )

    async def save_canvas_layout(self, layout: CanvasLayout) -> None:
        row = await self._session.get(CanvasLayoutRow, (layout.instance_id, layout.component_id, layout.version))
        if row is None:
            row = CanvasLayoutRow(
                instance_id=layout.instance_id, component_id=layout.component_id, version=layout.version
            )
            self._session.add(row)
        row.layout = dict(layout.layout)
        row.updated_by = layout.updated_by
        row.updated_at = layout.updated_at or utcnow()

    async def code_document(self, instance_id: str, component_id: str, version: int) -> CodeDocument | None:
        row = await self._session.get(CodeDocumentRow, (instance_id, component_id, version))
        if row is None:
            return None
        return CodeDocument(
            row.instance_id,
            row.component_id,
            row.version,
            row.code,
            row.config_hash,
            row.updated_by,
            row.updated_by_name,
            aware(row.updated_at),
        )

    async def save_code_document(self, document: CodeDocument) -> None:
        key = (document.instance_id, document.component_id, document.version)
        row = await self._session.get(CodeDocumentRow, key)
        if row is None:
            row = CodeDocumentRow(
                instance_id=document.instance_id, component_id=document.component_id, version=document.version
            )
            self._session.add(row)
        row.code = document.code
        row.config_hash = document.config_hash
        row.updated_by = document.updated_by
        row.updated_by_name = document.updated_by_name
        row.updated_at = document.updated_at or utcnow()

    async def drop_code_document(self, instance_id: str, component_id: str, version: int) -> None:
        _ = await self._session.execute(
            delete(CodeDocumentRow).where(
                CodeDocumentRow.instance_id == instance_id,
                CodeDocumentRow.component_id == component_id,
                CodeDocumentRow.version == version,
            )
        )

    async def commit(self) -> None:
        await self._session.commit()


def _component(row: ComponentMetaRow) -> ComponentMeta:
    return ComponentMeta(
        instance_id=row.instance_id,
        component_id=row.component_id,
        kind=cast("Kind", row.kind),
        owner_group_id=row.owner_group_id,
        labels=tuple(row.labels or ()),
        last_known_current_version=row.last_known_current_version,
        source_binding_id=row.source_binding_id,
        code_path=row.code_path,
        convention=row.convention,
    )


def _version(row: VersionMetaRow) -> VersionMeta:
    return VersionMeta(
        instance_id=row.instance_id,
        component_id=row.component_id,
        version=row.version,
        author_id=row.author_id,
        author_name=row.author_name,
        updated_by=row.updated_by,
        updated_by_name=row.updated_by_name,
        updated_at=aware_or_none(row.updated_at),
        notes=row.notes,
        change_summary=row.change_summary,
        based_on_version=row.based_on_version,
        eval_status=row.eval_status,
        published_by=row.published_by,
        published_by_name=row.published_by_name,
        published_at=aware_or_none(row.published_at),
        promoted_from=row.promoted_from,
    )


def _promotion(row: PromotionRow) -> Promotion:
    return Promotion(
        id=row.id,
        from_instance=row.from_instance,
        to_instance=row.to_instance,
        component_id=row.component_id,
        component_kind=row.component_kind,
        from_version=row.from_version,
        to_version=row.to_version,
        include_children=row.include_children,
        status=cast("PromotionStatus", row.status),
        report=row.report or {},
        created_by=row.created_by,
        created_by_name=row.created_by_name,
        created_at=aware(row.created_at),
        applied_at=aware_or_none(row.applied_at),
    )


def _used_by_dict(item: UsedBy) -> dict[str, Any]:
    return {
        "component_id": item.component_id,
        "component_kind": item.component_kind,
        "component_name": item.component_name,
        "versions": list(item.versions),
    }


def _used_by(raw: dict[str, Any]) -> UsedBy:
    return UsedBy(
        component_id=str(raw.get("component_id") or ""),
        component_kind=str(raw.get("component_kind") or "agent"),
        component_name=str(raw.get("component_name") or ""),
        versions=tuple(str(tag) for tag in raw.get("versions") or ()),
    )
