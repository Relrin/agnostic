"""HTTP routes under ``/api/v1/instances/{instance}``: datasets, evaluations, batches, results and publish gates."""

from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from agnostic_evals.api.schemas import (
    BatchComparisonOut,
    BatchDetailOut,
    BatchIn,
    BatchOut,
    CaseOut,
    CasePatch,
    CasesIn,
    DatasetDetailOut,
    DatasetIn,
    DatasetOut,
    DatasetPatch,
    EvalCapabilitiesOut,
    EvaluationsOut,
    GateIn,
    GateOut,
    ImportIn,
    ImportOut,
)
from agnostic_evals.application.access import EvalAccess
from agnostic_evals.application.batches import Batches, ListEvaluations, StartBatch, StartRequest, bridge_support
from agnostic_evals.application.datasets import Datasets
from agnostic_evals.application.gates import GateRequest, Gates
from agnostic_evals.application.ports import CaseChanges
from agnostic_evals.domain.importing import tool_calls
from agnostic_evals.domain.model import Judge
from agnostic_kernel.auth import Principal

router = APIRouter(route_class=DishkaRoute)

type EvalTypeQuery = Literal["accuracy", "agent_as_judge", "reliability", "performance"]


# ---------------------------------------------------------------- datasets


@router.get("/{instance}/eval-datasets", summary="Eval datasets (org-wide; needs evals:read on this instance)")
async def list_datasets(
    instance: str,
    principal: FromDishka[Principal],
    datasets: FromDishka[Datasets],
    eval_type: EvalTypeQuery | None = None,
) -> list[DatasetOut]:
    return [DatasetOut.of(item) for item in await datasets.list(principal, instance, eval_type)]


@router.post("/{instance}/eval-datasets", status_code=201, summary="Create a dataset, optionally with its cases")
async def create_dataset(
    instance: str, body: DatasetIn, principal: FromDishka[Principal], datasets: FromDishka[Datasets]
) -> DatasetDetailOut:
    created = await datasets.create(
        principal,
        instance,
        name=body.name,
        description=body.description,
        eval_type=body.eval_type,
        tags=body.tags,
        cases=[case.to_draft() for case in body.cases],
    )
    return DatasetDetailOut.detail(created)


@router.get("/{instance}/eval-datasets/{dataset_id}", summary="A dataset with its cases")
async def get_dataset(
    instance: str, dataset_id: str, principal: FromDishka[Principal], datasets: FromDishka[Datasets]
) -> DatasetDetailOut:
    return DatasetDetailOut.detail(await datasets.get(principal, instance, dataset_id))


@router.patch("/{instance}/eval-datasets/{dataset_id}", summary="Rename or describe a dataset")
async def update_dataset(
    instance: str,
    dataset_id: str,
    body: DatasetPatch,
    principal: FromDishka[Principal],
    datasets: FromDishka[Datasets],
) -> DatasetOut:
    updated = await datasets.update(
        principal, instance, dataset_id, name=body.name, description=body.description, tags=body.tags
    )
    return DatasetOut.of(updated)


@router.delete(
    "/{instance}/eval-datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dataset (past evaluations keep their case snapshots)",
)
async def delete_dataset(
    instance: str, dataset_id: str, principal: FromDishka[Principal], datasets: FromDishka[Datasets]
) -> None:
    await datasets.delete(principal, instance, dataset_id)


@router.post("/{instance}/eval-datasets/{dataset_id}/cases", status_code=201, summary="Append cases")
async def add_cases(
    instance: str, dataset_id: str, body: CasesIn, principal: FromDishka[Principal], datasets: FromDishka[Datasets]
) -> list[CaseOut]:
    created = await datasets.add_cases(principal, instance, dataset_id, [case.to_draft() for case in body.cases])
    return [CaseOut.of(case) for case in created]


@router.post("/{instance}/eval-datasets/{dataset_id}/import", summary="Import cases from CSV or JSONL text")
async def import_cases(
    instance: str, dataset_id: str, body: ImportIn, principal: FromDishka[Principal], datasets: FromDishka[Datasets]
) -> ImportOut:
    created = await datasets.import_cases(
        principal, instance, dataset_id, content=body.content, fmt=body.format, replace=body.replace
    )
    return ImportOut(imported=len(created))


@router.patch("/{instance}/eval-datasets/{dataset_id}/cases/{case_id}", summary="Change a case")
async def update_case(
    instance: str,
    dataset_id: str,
    case_id: str,
    body: CasePatch,
    principal: FromDishka[Principal],
    datasets: FromDishka[Datasets],
) -> CaseOut:
    sent = body.model_fields_set
    changes = CaseChanges(
        input=body.input,
        expected_output=body.expected_output or None,
        criteria=body.criteria or None,
        expected_tool_calls=tool_calls(body.expected_tool_calls) if body.expected_tool_calls else None,
        clear=frozenset(
            key
            for key in ("expected_output", "criteria", "expected_tool_calls")
            if key in sent and not getattr(body, key)
        ),
    )
    return CaseOut.of(await datasets.update_case(principal, instance, dataset_id, case_id, changes))


@router.delete(
    "/{instance}/eval-datasets/{dataset_id}/cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a case",
)
async def delete_case(
    instance: str, dataset_id: str, case_id: str, principal: FromDishka[Principal], datasets: FromDishka[Datasets]
) -> None:
    await datasets.delete_case(principal, instance, dataset_id, case_id)


# ---------------------------------------------------------------- evaluations and batches


@router.get(
    "/{instance}/evaluations",
    summary="Evaluations table: dataset batches run here plus AgentOS eval runs created elsewhere",
)
async def list_evaluations(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[ListEvaluations],
    eval_type: EvalTypeQuery | None = None,
    component_id: str | None = None,
    model: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> EvaluationsOut:
    found = await use_case(
        principal, instance, eval_type=eval_type, component_id=component_id, model=model, limit=limit
    )
    return EvaluationsOut.of(found)


@router.get(
    "/{instance}/evals/capabilities",
    summary="Whether drafts and pinned versions can be evaluated here (needs agnostic-bridge)",
)
async def eval_capabilities(
    instance: str, principal: FromDishka[Principal], access: FromDishka[EvalAccess]
) -> EvalCapabilitiesOut:
    return EvalCapabilitiesOut.of(await bridge_support(access, principal, instance))


@router.post(
    "/{instance}/eval-batches",
    status_code=202,
    summary="Evaluate a component version on a dataset: one eval run per case, in the background",
)
async def start_batch(
    instance: str, body: BatchIn, principal: FromDishka[Principal], use_case: FromDishka[StartBatch]
) -> BatchOut:
    batch = await use_case(
        principal,
        instance,
        StartRequest(
            dataset_id=body.dataset_id,
            component_kind=body.component_kind,
            component_id=body.component_id,
            version=body.version,
            judge=Judge(body.judge.model_id, body.judge.provider) if body.judge else None,
            name=body.name,
            params=body.params,
        ),
    )
    return BatchOut.of(batch)


@router.get("/{instance}/eval-batches/{batch_id}", summary="An evaluation with its cases and progress")
async def get_batch(
    instance: str, batch_id: str, principal: FromDishka[Principal], batches: FromDishka[Batches]
) -> BatchDetailOut:
    return BatchDetailOut.of(await batches.get(principal, instance, batch_id))


@router.get(
    "/{instance}/eval-batches/{batch_id}/compare",
    summary="Case-by-case comparison with another evaluation of the same dataset",
)
async def compare_batches(
    instance: str,
    batch_id: str,
    principal: FromDishka[Principal],
    batches: FromDishka[Batches],
    other: Annotated[str, Query(alias="with", description="The other evaluation's id")],
) -> BatchComparisonOut:
    return BatchComparisonOut.of(await batches.compare(principal, instance, batch_id, other))


@router.post("/{instance}/eval-batches/{batch_id}/cancel", summary="Stop an evaluation between cases")
async def cancel_batch(
    instance: str, batch_id: str, principal: FromDishka[Principal], batches: FromDishka[Batches]
) -> BatchOut:
    return BatchOut.of(await batches.cancel(principal, instance, batch_id))


@router.get(
    "/{instance}/eval-results",
    summary="The newest finished evaluation per dataset for one component version",
)
async def eval_results(
    instance: str,
    principal: FromDishka[Principal],
    batches: FromDishka[Batches],
    component_id: str,
    version: Annotated[int | None, Query(ge=1, description="Empty: evaluations of the current version")] = None,
) -> list[BatchOut]:
    return [BatchOut.of(batch) for batch in await batches.results(principal, instance, component_id, version)]


# ---------------------------------------------------------------- publish gates


@router.get("/{instance}/eval-gates", summary="Publish gates with what each would do right now")
async def list_gates(
    instance: str, principal: FromDishka[Principal], gates: FromDishka[Gates], component_id: str | None = None
) -> list[GateOut]:
    return [GateOut.of(view) for view in await gates.list(principal, instance, component_id)]


@router.put(
    "/{instance}/eval-gates",
    summary="Create or change the gate for a component and dataset (needs evals:gates:write)",
)
async def put_gate(instance: str, body: GateIn, principal: FromDishka[Principal], gates: FromDishka[Gates]) -> GateOut:
    view = await gates.put(
        principal,
        instance,
        GateRequest(
            component_kind=body.component_kind,
            component_id=body.component_id,
            dataset_id=body.dataset_id,
            min_average=body.min_average,
            enabled=body.enabled,
        ),
    )
    return GateOut.of(view)


@router.delete(
    "/{instance}/eval-gates/{gate_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a publish gate"
)
async def delete_gate(instance: str, gate_id: str, principal: FromDishka[Principal], gates: FromDishka[Gates]) -> None:
    await gates.delete(principal, instance, gate_id)
