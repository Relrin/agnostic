"""HTTP routes under ``/api/v1/instances/{instance}/studio`` and the org-wide ``/api/v1/studio``."""

from typing import Annotated, Any

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response, status
from fastapi.responses import StreamingResponse

from agnostic_kernel.auth import Principal
from agnostic_spec.v3_1 import json_schema
from agnostic_studio.api.schemas import (
    CodegenIn,
    CodegenOut,
    ComponentDetailOut,
    ComponentRowOut,
    CreateIn,
    DiffOut,
    KindIn,
    KindQuery,
    MetaPatchIn,
    NewDraftIn,
    PromoteIn,
    PromotionApplyIn,
    PromotionOut,
    PublishCheckOut,
    PublishIn,
    PublishOut,
    RegistryEntryDetailOut,
    RegistryEntryOut,
    RegistryOut,
    SaveDraftIn,
    SetCurrentIn,
    SetCurrentOut,
    TemplateOut,
    TestRunIn,
    UsedByOut,
    ValidateIn,
    ValidationOut,
    VersionOut,
)
from agnostic_studio.application.catalog import Catalog, RegistryCatalog
from agnostic_studio.application.codegen import Codegen
from agnostic_studio.application.components import Components, CreateRequest, MetaPatch
from agnostic_studio.application.drafts import Drafts, SaveDraft
from agnostic_studio.application.promotions import PromoteRequest, Promotions
from agnostic_studio.application.publishing import Publisher
from agnostic_studio.application.testing import DraftRuns, TestRun
from agnostic_studio.application.validation import Validator
from agnostic_studio.domain.templates import TEMPLATES

router = APIRouter(route_class=DishkaRoute)
org_router = APIRouter(route_class=DishkaRoute)

COMPONENT = "/{instance}/studio/components/{component_id}"


# ---------------------------------------------------------------- registry


def _registry_out(instance: str, catalog: Catalog, entry_type: str | None, q: str | None) -> RegistryOut:
    needle = (q or "").strip().lower()
    entries = [
        RegistryEntryOut.of(entry, catalog.used_by.get((entry.type, entry.name), []))
        for entry in catalog.entries
        if (entry_type is None or entry.type == entry_type) and (not needle or needle in entry.name.lower())
    ]
    return RegistryOut(
        instance=instance, entries=entries, counts=catalog.counts(), total=len(catalog.entries), bridge=catalog.bridge
    )


@router.get("/{instance}/studio/registry", summary="Everything Studio can compose with, with used-by counts")
async def registry(
    instance: str,
    principal: FromDishka[Principal],
    catalog: FromDishka[RegistryCatalog],
    entry_type: Annotated[str | None, Query(alias="type")] = None,
    q: str | None = None,
) -> RegistryOut:
    found, snapshot = await catalog.catalog(principal, instance)
    return _registry_out(found.slug, snapshot, entry_type, q)


@router.get("/{instance}/studio/registry/{entry_type}/{name}", summary="One registry entry and where it's used")
async def registry_entry(
    instance: str, entry_type: str, name: str, principal: FromDishka[Principal], catalog: FromDishka[RegistryCatalog]
) -> RegistryEntryDetailOut:
    _, entry, used_by = await catalog.entry(principal, instance, entry_type, name)
    return RegistryEntryDetailOut(
        entry=RegistryEntryOut.of(entry, used_by), used_by=[UsedByOut.of(item) for item in used_by]
    )


@router.post("/{instance}/studio/registry/refresh", summary="Re-read the registry and rebuild the used-by index")
async def refresh_registry(
    instance: str, principal: FromDishka[Principal], catalog: FromDishka[RegistryCatalog]
) -> RegistryOut:
    found = await catalog.refresh(principal, instance)
    _, snapshot = await catalog.catalog(principal, found.id)
    return _registry_out(found.slug, snapshot, None, None)


# ---------------------------------------------------------------- components


@router.get("/{instance}/studio/components", summary="Agents, teams or workflows: stored in Studio and defined in code")
async def list_components(
    instance: str, principal: FromDishka[Principal], components: FromDishka[Components], kind: KindQuery = "agent"
) -> list[ComponentRowOut]:
    _, rows = await components.index(principal, instance, kind)
    return [ComponentRowOut.of(row) for row in rows]


@router.post(
    "/{instance}/studio/components",
    status_code=status.HTTP_201_CREATED,
    summary="Create a component with draft v1 (blank, from a template, duplicated or imported)",
)
async def create_component(
    instance: str, body: CreateIn, principal: FromDishka[Principal], components: FromDishka[Components]
) -> ComponentDetailOut:
    detail = await components.create(
        principal,
        instance,
        CreateRequest(
            kind=body.kind,
            name=body.name,
            mode=body.mode,
            component_id=body.component_id,
            description=body.description,
            template_id=body.template_id,
            source_id=body.source_id,
            source_version=body.source_version,
            config=body.config,
            model=body.model,
            notes=body.notes,
        ),
    )
    return ComponentDetailOut.of(detail)


@router.get(COMPONENT, summary="A component with its versions, its open draft and its current version")
async def get_component(
    instance: str, component_id: str, principal: FromDishka[Principal], components: FromDishka[Components]
) -> ComponentDetailOut:
    return ComponentDetailOut.of(await components.detail(principal, instance, component_id))


@router.patch(COMPONENT, summary="Rename, describe, label or assign an owner group")
async def patch_component(
    instance: str,
    component_id: str,
    body: MetaPatchIn,
    principal: FromDishka[Principal],
    components: FromDishka[Components],
) -> ComponentDetailOut:
    patch = MetaPatch(
        name=body.name,
        description=body.description,
        owner_group_id=body.owner_group_id,
        labels=body.labels,
        clear_owner=body.clear_owner,
    )
    return ComponentDetailOut.of(await components.patch(principal, instance, component_id, patch))


@router.delete(COMPONENT, status_code=status.HTTP_204_NO_CONTENT, summary="Archive (409 lists the dependents)")
async def archive_component(
    instance: str, component_id: str, principal: FromDishka[Principal], components: FromDishka[Components]
) -> Response:
    await components.archive(principal, instance, component_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(f"{COMPONENT}/restore", summary="Restore an archived component")
async def restore_component(
    instance: str, component_id: str, principal: FromDishka[Principal], components: FromDishka[Components]
) -> ComponentDetailOut:
    return ComponentDetailOut.of(await components.restore(principal, instance, component_id))


# ---------------------------------------------------------------- versions


@router.get(f"{COMPONENT}/configs/{{version}}", summary="One version with its config")
async def get_version(
    instance: str, component_id: str, version: int, principal: FromDishka[Principal], drafts: FromDishka[Drafts]
) -> VersionOut:
    _, view = await drafts.version(principal, instance, component_id, version)
    return VersionOut.of(view)


@router.post(
    f"{COMPONENT}/configs",
    status_code=status.HTTP_201_CREATED,
    summary="A new draft from a version (default: the current one), member pins included",
)
async def new_draft(
    instance: str, component_id: str, body: NewDraftIn, principal: FromDishka[Principal], drafts: FromDishka[Drafts]
) -> VersionOut:
    return VersionOut.of(await drafts.new_draft(principal, instance, component_id, body.from_version, body.notes))


@router.patch(f"{COMPONENT}/configs/{{version}}", summary="Save a draft (409 when someone else saved it first)")
async def save_draft(
    instance: str,
    component_id: str,
    version: int,
    body: SaveDraftIn,
    principal: FromDishka[Principal],
    drafts: FromDishka[Drafts],
) -> VersionOut:
    request = SaveDraft(config=body.config, revision=body.revision, pins=body.pins, notes=body.notes, label=body.label)
    return VersionOut.of(await drafts.save(principal, instance, component_id, version, request))


@router.delete(f"{COMPONENT}/configs/{{version}}", status_code=status.HTTP_204_NO_CONTENT, summary="Discard a draft")
async def discard_draft(
    instance: str, component_id: str, version: int, principal: FromDishka[Principal], drafts: FromDishka[Drafts]
) -> Response:
    await drafts.discard(principal, instance, component_id, version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(f"{COMPONENT}/diff", summary="Field-level and code diff between two versions")
async def diff_versions(
    instance: str,
    component_id: str,
    principal: FromDishka[Principal],
    drafts: FromDishka[Drafts],
    from_version: Annotated[int, Query(alias="from", ge=1)],
    to_version: Annotated[int, Query(alias="to", ge=1)],
) -> DiffOut:
    return DiffOut.of(await drafts.diff(principal, instance, component_id, from_version, to_version))


@router.get(f"{COMPONENT}/publish-check", summary="Validation and eval gates for publishing a version")
async def publish_check(
    instance: str,
    component_id: str,
    principal: FromDishka[Principal],
    publisher: FromDishka[Publisher],
    version: Annotated[int, Query(ge=1)],
) -> PublishCheckOut:
    return PublishCheckOut.of(await publisher.check(principal, instance, component_id, version))


@router.post(
    f"{COMPONENT}/configs/{{version}}/publish",
    summary="Publish a draft; failed gates need override_reason and evals:gates:override",
)
async def publish(
    instance: str,
    component_id: str,
    version: int,
    body: PublishIn,
    principal: FromDishka[Principal],
    publisher: FromDishka[Publisher],
) -> PublishOut:
    result = await publisher.publish(
        principal, instance, component_id, version, notes=body.notes, override_reason=body.override_reason
    )
    return PublishOut.of(result)


@router.post(f"{COMPONENT}/configs/{{version}}/set-current", summary="Make a published version current (rollback)")
async def set_current(
    instance: str,
    component_id: str,
    version: int,
    body: SetCurrentIn,
    principal: FromDishka[Principal],
    publisher: FromDishka[Publisher],
) -> SetCurrentOut:
    view, outcome = await publisher.set_current(principal, instance, component_id, version, reason=body.reason)
    return SetCurrentOut(version=VersionOut.of(view), outcome=outcome)


# ---------------------------------------------------------------- validation & code


@router.post("/{instance}/studio/validate", summary="Shape, registry references, rules and agno's strict load")
async def validate(
    instance: str, body: ValidateIn, principal: FromDishka[Principal], validator: FromDishka[Validator]
) -> ValidationOut:
    return ValidationOut.of(await validator.validate_ref(principal, instance, body.kind, body.config))


@router.post("/{instance}/studio/codegen", summary="Generated Python with span map, gutter marks, notes and ruff")
async def codegen(
    instance: str, body: CodegenIn, principal: FromDishka[Principal], generator: FromDishka[Codegen]
) -> CodegenOut:
    return CodegenOut.of(await generator.render(principal, instance, body.kind, body.config, body.base_config))


# ---------------------------------------------------------------- promotion


@router.get(f"{COMPONENT}/promotions", summary="Recent promotions of this component to other instances")
async def list_promotions(
    instance: str, component_id: str, principal: FromDishka[Principal], promotions: FromDishka[Promotions]
) -> list[PromotionOut]:
    return [PromotionOut.of(item) for item in await promotions.list(principal, instance, component_id)]


@router.post(
    f"{COMPONENT}/promotions",
    status_code=status.HTTP_201_CREATED,
    summary="Dry run: does every registry reference and pinned member exist on the target?",
)
async def promote(
    instance: str,
    component_id: str,
    body: PromoteIn,
    principal: FromDishka[Principal],
    promotions: FromDishka[Promotions],
) -> PromotionOut:
    request = PromoteRequest(target=body.target, version=body.version, include_children=body.include_children)
    return PromotionOut.of(await promotions.dry_run(principal, instance, component_id, request))


@router.post(
    "/{instance}/studio/promotions/{promotion_id}/apply", summary="Create the drafts on the target (and publish)"
)
async def apply_promotion(
    instance: str,
    promotion_id: str,
    body: PromotionApplyIn,
    principal: FromDishka[Principal],
    promotions: FromDishka[Promotions],
) -> PromotionOut:
    return PromotionOut.of(await promotions.apply(principal, instance, promotion_id, publish=body.publish))


# ---------------------------------------------------------------- test runs


@router.post(
    f"{COMPONENT}/test-runs",
    response_class=StreamingResponse,
    summary="Run a draft version and stream its events (delegated elevation; needs components:write and run)",
)
async def test_run(
    instance: str, component_id: str, body: TestRunIn, principal: FromDishka[Principal], runs: FromDishka[DraftRuns]
) -> StreamingResponse:
    stream = await runs.open(
        principal,
        instance,
        component_id,
        TestRun(message=body.message, version=body.version, session_id=body.session_id),
    )
    return StreamingResponse(
        stream.body,
        status_code=stream.status,
        media_type=stream.content_type or "text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- org-wide


@org_router.get("/studio/schema/{kind}", summary="JSON Schema of a config, with the form's sections and field metadata")
async def schema(kind: KindIn, principal: FromDishka[Principal]) -> dict[str, Any]:  # noqa: ARG001
    return json_schema(kind)


@org_router.get("/studio/templates", summary="Starting points for new agents and teams")
async def templates(principal: FromDishka[Principal], kind: KindIn | None = None) -> list[TemplateOut]:  # noqa: ARG001
    return [TemplateOut.of(item) for item in TEMPLATES if kind is None or item.kind == kind]
