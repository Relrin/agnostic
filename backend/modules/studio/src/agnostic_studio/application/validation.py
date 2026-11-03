"""Validation in layers.

Shape, registry references, Studio's rules, a workflow's CEL expressions, then agno's own strict load (with the
bridge).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast

from agnostic_cel import check as check_cel
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_spec import Diagnostic
from agnostic_spec.v3_1 import Kind as SpecKind
from agnostic_spec.v3_1 import WorkflowConfig, check, iter_nodes, iter_refs, parse, shape_errors
from agnostic_studio.application.access import BRIDGE_VALIDATE, READ_SCOPE, StudioAccess, page_items
from agnostic_studio.application.catalog import Catalog, RegistryCatalog
from agnostic_studio.domain.promotion import TYPE_NOUNS

type LayerStatus = Literal["ok", "failed", "warning", "skipped"]

# Where a node keeps its CEL expression, and the context it is evaluated in.
CEL_FIELDS: dict[str, tuple[str, Literal["condition", "router", "loop"]]] = {
    "Condition": ("evaluator", "condition"),
    "Loop": ("end_condition", "loop"),
    "Router": ("selector", "router"),
}
COMPONENT_REFS = frozenset({"agent", "team", "workflow"})


@dataclass(frozen=True, slots=True)
class Layer:
    id: str
    label: str
    status: LayerStatus
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    layers: list[Layer]

    @property
    def ok(self) -> bool:
        return all(layer.status != "failed" for layer in self.layers)

    @property
    def diagnostics(self) -> list[Diagnostic]:
        return [diagnostic for layer in self.layers for diagnostic in layer.diagnostics]

    @property
    def summary(self) -> str:
        errors = sum(1 for item in self.diagnostics if item.severity == "error")
        warnings = sum(1 for item in self.diagnostics if item.severity == "warning")
        if errors:
            return f"{errors} problem{'s' if errors != 1 else ''} to fix before publishing."
        if warnings:
            return f"Valid, with {warnings} warning{'s' if warnings != 1 else ''}."
        return "Valid."


class Validator:
    def __init__(self, access: StudioAccess, catalog: RegistryCatalog) -> None:
        self._access = access
        self._catalog = catalog

    async def validate_ref(
        self, principal: Principal, ref: str, kind: SpecKind, config: dict[str, Any]
    ) -> ValidationReport:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        return await self.validate(principal, instance, kind, config)

    async def validate(
        self, principal: Principal, instance: Instance, kind: SpecKind, config: dict[str, Any]
    ) -> ValidationReport:
        shape = shape_errors(kind, config)
        if shape:
            skipped = [
                Layer("registry", "Registry references", "skipped", hint="Fix the shape first."),
                Layer("rules", "Studio rules", "skipped", hint="Fix the shape first."),
            ]
            if kind == "workflow":
                skipped.append(Layer("cel", "CEL expressions", "skipped", hint="Fix the shape first."))
            skipped.append(Layer("bridge", "agno strict load", "skipped", hint="Fix the shape first."))
            return ValidationReport([Layer("shape", "Shape", "failed", shape), *skipped])
        parsed = parse(kind, config)
        _, catalog = await self._catalog.catalog(principal, instance.id)
        components = {
            str(item.get("component_id")) for item in await self._access.pages(principal, instance, "/components")
        }
        registry = _registry(parsed, catalog, components, instance)
        rules = check(parsed)
        layers = [
            Layer("shape", "Shape", "ok"),
            Layer("registry", "Registry references", _status(registry), registry),
            Layer("rules", "Studio rules", _status(rules), rules),
        ]
        if isinstance(parsed, WorkflowConfig):
            expressions = cel_diagnostics(parsed)
            layers.append(Layer("cel", "CEL expressions", _status(expressions), expressions))
        layers.append(await self._bridge(principal, instance, kind, parsed.dump()))
        return ValidationReport(layers)

    async def _bridge(self, principal: Principal, instance: Instance, kind: SpecKind, config: dict[str, Any]) -> Layer:
        if BRIDGE_VALIDATE not in await self._access.bridge(instance):
            return Layer(
                "bridge",
                "agno strict load",
                "skipped",
                hint=f"agnostic-bridge isn't installed on {instance.display_name}, so AgentOS checks the config when "
                "it is saved.",
            )
        response = await self._access.call(
            principal, instance, "POST", "/agnostic/v1/components/validate", body={"kind": kind, "config": config}
        )
        if not response.ok:
            return Layer(
                "bridge",
                "agno strict load",
                "warning",
                [
                    Diagnostic(
                        "", "warning", "bridge_unavailable", f"The bridge didn't answer (HTTP {response.status})."
                    )
                ],
            )
        body = cast("dict[str, Any]", response.body) if isinstance(response.body, dict) else {}
        errors = [
            Diagnostic(str(item.get("path") or ""), "error", "agno_strict", str(item.get("message") or ""))
            for item in page_items(body.get("errors") or [])
        ]
        return Layer("bridge", "agno strict load", "failed" if errors or body.get("valid") is False else "ok", errors)


def _registry(parsed: Any, catalog: Catalog, components: set[str], instance: Instance) -> list[Diagnostic]:  # noqa: ANN401
    found: list[Diagnostic] = []
    names = catalog.names()
    for ref in iter_refs(parsed):
        if ref.type in COMPONENT_REFS:
            if ref.name not in components and (ref.type, ref.name) not in names:
                found.append(
                    Diagnostic(
                        ref.path,
                        "error",
                        "member_missing",
                        f"There is no {ref.type} `{ref.name}` on {instance.display_name}.",
                    )
                )
            continue
        noun = TYPE_NOUNS.get(ref.type, ref.type)
        if (ref.type, ref.name) not in names:
            found.append(
                Diagnostic(
                    ref.path,
                    "error",
                    "ref_missing",
                    f"{noun.capitalize()} `{ref.name}` isn't registered on {instance.display_name}.",
                )
            )
            continue
        entry = catalog.of(ref.type, ref.name)
        if entry is not None and not entry.studio_available:
            found.append(
                Diagnostic(
                    ref.path,
                    "error",
                    "ref_not_buildable",
                    f"{noun.capitalize()} `{ref.name}` was discovered on a component defined in code; only tools "
                    "passed to Registry(tools=[...]) can be attached in Studio.",
                )
            )
        elif entry is not None and entry.requires_approval:
            found.append(
                Diagnostic(ref.path, "info", "ref_needs_approval", f"Tool `{ref.name}` is registered · needs approval.")
            )
    return found


def cel_diagnostics(config: WorkflowConfig) -> list[Diagnostic]:
    """Every CEL expression checked in its node's context; a Router's against its choices' names."""
    found: list[Diagnostic] = []
    for info in iter_nodes(config):
        node = info.node
        place = CEL_FIELDS.get(node.node_type)
        if place is None:
            continue
        field_name, context = place
        expression = node.value(field_name)
        if node.value(f"{field_name}_type") != "cel" or not isinstance(expression, str):
            continue
        choices = [child.name or "" for child in node.children("choices")] if context == "router" else None
        result = check_cel(expression, context, choices=choices)
        found.extend(
            Diagnostic(f"{info.path}.{field_name}", finding.severity, f"cel.{finding.code}", finding.message)
            for finding in result.findings
        )
    return found


def _status(diagnostics: list[Diagnostic]) -> LayerStatus:
    if any(item.severity == "error" for item in diagnostics):
        return "failed"
    if any(item.severity == "warning" for item in diagnostics):
        return "warning"
    return "ok"


__all__ = ["CEL_FIELDS", "Layer", "ValidationReport", "Validator", "cel_diagnostics"]
