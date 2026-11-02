"""Publish gates: a minimum score on a dataset that Studio checks before publishing a component.

This module only states a gate's current consequence; Studio's Publish enforces it (with an audited override).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from agnostic_evals.domain.model import ComponentKind, EvalType

type GateState = Literal["off", "no_result", "would_block", "passes"]

MIN_AVERAGE_RANGE = (0.0, 10.0)


@dataclass(frozen=True, slots=True)
class Gate:
    id: str
    instance_id: str
    component_kind: ComponentKind
    component_id: str
    dataset_id: str
    eval_type: EvalType
    min_average: float
    enabled: bool
    updated_by: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GateResult:
    """The newest finished batch for the gate's component, dataset and type."""

    batch_id: str
    version_label: str
    value: float | None


@dataclass(frozen=True, slots=True)
class Consequence:
    state: GateState
    text: str


def consequence(gate: Gate, latest: GateResult | None) -> Consequence:
    if not gate.enabled:
        return Consequence("off", "Off: Publish ignores this eval.")
    if latest is None or latest.value is None:
        return Consequence(
            "no_result", f"No result yet: Publish is blocked until a version averages at least {gate.min_average:g}."
        )
    if latest.value < gate.min_average:
        return Consequence(
            "would_block", f"{latest.version_label} ({latest.value:.2f}) would be blocked from publishing."
        )
    return Consequence(
        "passes", f"{latest.version_label} ({latest.value:.2f}) meets the minimum of {gate.min_average:g}."
    )
