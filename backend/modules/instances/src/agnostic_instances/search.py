"""Command-palette documents: instances, and the agents, teams and workflows in their latest ``/config`` snapshot."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from dishka import AsyncContainer

from agnostic_instances.application.ports import InstanceRepository, SnapshotRepository
from agnostic_kernel.modules import SearchDocument

FAMILIES = (("agents", "agent"), ("teams", "team"), ("workflows", "workflow"))


async def instance_documents(container: AsyncContainer) -> Sequence[SearchDocument]:
    instances = await (await container.get(InstanceRepository)).list()
    snapshots = await container.get(SnapshotRepository)
    documents: list[SearchDocument] = []
    for instance in instances:
        documents.append(
            SearchDocument(
                kind="instance",
                ref=instance.id,
                title=instance.display_name,
                body=f"{instance.slug} {instance.env_tag.value} {instance.endpoint_url}",
                url_path=f"/i/{instance.slug}/home",
                instance_id=instance.id,
                required_scope="os:read",
            )
        )
        latest = await snapshots.latest(instance.id, "config")
        config = cast("dict[str, Any]", latest[0]) if latest and isinstance(latest[0], dict) else {}
        for family, kind in FAMILIES:
            for raw in cast("list[Any]", config.get(family) or []):
                if not isinstance(raw, dict):
                    continue
                entry = cast("dict[str, Any]", raw)
                component_id = str(entry.get("id") or "")
                if not component_id:
                    continue
                documents.append(
                    SearchDocument(
                        kind=kind,
                        ref=component_id,
                        title=str(entry.get("name") or component_id),
                        body=f"{component_id} {entry.get('description') or ''} {instance.slug}".strip(),
                        url_path=f"/i/{instance.slug}/chat/{family}/{component_id}",
                        instance_id=instance.id,
                        required_scope=f"{family}:read",
                    )
                )
    return documents
