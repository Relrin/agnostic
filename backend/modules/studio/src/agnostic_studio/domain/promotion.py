"""Can a component version move to another instance? Every registry reference and pinned child must exist there."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

type ChildStatus = Literal["present", "promoted_together", "missing"]
type PromotionStatus = Literal["dry_run", "blocked", "applied", "published", "failed"]

TYPE_NOUNS = {
    "tool": "tool",
    "model": "model",
    "knowledge": "knowledge base",
    "schema": "schema",
    "memory_manager": "memory manager",
    "learning": "learning machine",
    "function": "function",
    "workflow": "workflow",
}


@dataclass(frozen=True, slots=True)
class Reference:
    path: str
    type: str
    name: str


@dataclass(frozen=True, slots=True)
class MissingRef:
    type: str
    name: str
    paths: tuple[str, ...]

    @property
    def message(self) -> str:
        return f"{TYPE_NOUNS.get(self.type, self.type)} `{self.name}` isn't registered on the target"


@dataclass(frozen=True, slots=True)
class ChildCheck:
    component_id: str
    kind: str
    version: int | None
    status: ChildStatus


@dataclass(frozen=True, slots=True)
class PromotionReport:
    missing: list[MissingRef] = field(default_factory=list[MissingRef])
    children: list[ChildCheck] = field(default_factory=list[ChildCheck])
    checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.missing and all(child.status != "missing" for child in self.children)

    @property
    def summary(self) -> str:
        if self.ok:
            together = sum(1 for child in self.children if child.status == "promoted_together")
            members = "1 pinned member moves" if together == 1 else f"{together} pinned members move"
            extra = f"; {members} with it" if together else ""
            return f"All {self.checked} registry references exist on the target{extra}."
        parts = [item.message for item in self.missing]
        parts.extend(
            f"member `{child.component_id}` doesn't exist on the target"
            for child in self.children
            if child.status == "missing"
        )
        return "Blocked: " + "; ".join(parts) + "."


def check(
    references: Iterable[Reference],
    target_registry: set[tuple[str, str]],
    children: Iterable[tuple[str, str, int | None]],
    target_components: set[str],
    *,
    include_children: bool,
) -> PromotionReport:
    """``children`` are ``(component_id, kind, pinned version)``; members in the target registry are present."""
    missing: dict[tuple[str, str], list[str]] = {}
    checked = 0
    for reference in references:
        if reference.type in {"agent", "team"}:
            continue
        checked += 1
        if (reference.type, reference.name) not in target_registry:
            missing.setdefault((reference.type, reference.name), []).append(reference.path)
    child_checks: list[ChildCheck] = []
    for component_id, kind, version in children:
        if component_id in target_components or (kind, component_id) in target_registry:
            status: ChildStatus = "present"
        elif include_children:
            status = "promoted_together"
        else:
            status = "missing"
        child_checks.append(ChildCheck(component_id, kind, version, status))
    return PromotionReport(
        missing=[MissingRef(kind, name, tuple(paths)) for (kind, name), paths in missing.items()],
        children=child_checks,
        checked=checked,
    )


def report_dict(report: PromotionReport) -> dict[str, object]:
    return {
        "ok": report.ok,
        "summary": report.summary,
        "checked": report.checked,
        "missing": [{"type": item.type, "name": item.name, "paths": list(item.paths)} for item in report.missing],
        "children": [
            {"component_id": child.component_id, "kind": child.kind, "version": child.version, "status": child.status}
            for child in report.children
        ],
    }


@dataclass(frozen=True, slots=True)
class Promotion:
    id: str
    from_instance: str
    to_instance: str
    component_id: str
    component_kind: str
    from_version: int
    to_version: int | None
    include_children: bool
    status: PromotionStatus
    report: dict[str, object]
    created_by: str
    created_by_name: str
    created_at: datetime
    applied_at: datetime | None = None
