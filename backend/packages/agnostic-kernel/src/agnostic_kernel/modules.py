"""Module SDK: the contract every control-plane module implements, and the loader that composes them.

Modules are separate distributions that register one object in the ``agnostic.modules`` entry-point group, so
customers can add their own modules as wheels. The composition root sorts them by ``depends_on``, fails fast on
cycles and missing dependencies, and leaves out modules disabled by ``AGNOSTIC_MODULES__DISABLED``.
"""

from __future__ import annotations

import graphlib
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

from dishka import AsyncContainer, Provider
from fastapi import APIRouter
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

ENTRY_POINT_GROUP = "agnostic.modules"


@dataclass(frozen=True, slots=True)
class RouterSpec:
    """A router mounted under ``/api/v1{prefix}``."""

    router: APIRouter
    prefix: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScopeDecl:
    """A control-plane scope a module defines, e.g. ``approvals:write``."""

    name: str
    description: str


@dataclass(frozen=True, slots=True)
class JobSpec:
    """A Procrastinate task. ``periodic`` is a cron expression; periodic jobs are de-duplicated across workers.

    The function receives the Procrastinate ``JobContext`` first (use :func:`agnostic_kernel.jobs.job_container`
    to resolve dependencies), then the job's keyword arguments. Periodic jobs also get ``timestamp: int``.
    """

    name: str
    func: Callable[..., Awaitable[Any]]
    queue: str = "default"
    periodic: str | None = None
    retry: int = 0


@dataclass(frozen=True, slots=True)
class EventHandlerSpec:
    """Subscription to a domain event by name (dispatch lands with the outbox in P01)."""

    event: str
    handler: Callable[[Mapping[str, Any]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AuditActionDecl:
    """An audit action and its deterministic summary template, e.g. ``"{actor} created greeting {id}"``."""

    action: str
    summary_template: str


@dataclass(frozen=True, slots=True)
class SearchProvider:
    """Command-palette entity search contributed by a module."""

    entity: str
    search: Callable[[str, int], Awaitable[Sequence[Mapping[str, Any]]]]


@dataclass(frozen=True, slots=True)
class CapabilityProbe:
    """An AgentOS capability a module needs (probed by ``instances`` in P01)."""

    name: str
    description: str


@runtime_checkable
class Module(Protocol):
    name: ClassVar[str]
    version: ClassVar[str]
    depends_on: ClassVar[tuple[str, ...]]

    def settings_model(self) -> type[BaseSettings] | None: ...
    def provide(self) -> Iterable[Provider]: ...
    def routers(self) -> Iterable[RouterSpec]: ...
    def metadata(self) -> MetaData | None: ...
    def migrations(self) -> Path | None: ...
    def scopes(self) -> Iterable[ScopeDecl]: ...
    def jobs(self) -> Iterable[JobSpec]: ...
    def event_handlers(self) -> Iterable[EventHandlerSpec]: ...
    def audit_actions(self) -> Iterable[AuditActionDecl]: ...
    def search_providers(self) -> Iterable[SearchProvider]: ...
    def capabilities(self) -> Iterable[CapabilityProbe]: ...
    async def on_startup(self, container: AsyncContainer) -> None: ...
    async def on_shutdown(self, container: AsyncContainer) -> None: ...


class BaseModule:
    """Convenience base with no-op defaults; override only what the module contributes."""

    name: ClassVar[str]
    version: ClassVar[str] = "0.0.0"
    depends_on: ClassVar[tuple[str, ...]] = ()

    def settings_model(self) -> type[BaseSettings] | None:
        return None

    def provide(self) -> Iterable[Provider]:
        return ()

    def routers(self) -> Iterable[RouterSpec]:
        return ()

    def metadata(self) -> MetaData | None:
        return None

    def migrations(self) -> Path | None:
        return None

    def scopes(self) -> Iterable[ScopeDecl]:
        return ()

    def jobs(self) -> Iterable[JobSpec]:
        return ()

    def event_handlers(self) -> Iterable[EventHandlerSpec]:
        return ()

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return ()

    def search_providers(self) -> Iterable[SearchProvider]:
        return ()

    def capabilities(self) -> Iterable[CapabilityProbe]:
        return ()

    async def on_startup(self, container: AsyncContainer) -> None:  # noqa: ARG002
        return None

    async def on_shutdown(self, container: AsyncContainer) -> None:  # noqa: ARG002
        return None


class ModuleGraphError(RuntimeError):
    """The module set cannot be composed (duplicate name, missing dependency, cycle, disabled dependency)."""


@dataclass(frozen=True, slots=True)
class LoadedModules:
    enabled: tuple[Module, ...]
    """Enabled modules in dependency order (dependencies first)."""
    disabled: tuple[str, ...] = ()
    installed: Mapping[str, Module] = field(default_factory=dict[str, Module])
    """Every discovered module, enabled or not. Migrations cover all installed modules."""

    def names(self) -> list[str]:
        return [module.name for module in self.enabled]


def discover_modules() -> list[Module]:
    """Instantiate every module registered in the ``agnostic.modules`` entry-point group."""
    modules: list[Module] = []
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        loaded: object = entry_point.load()
        instance: object = loaded() if isinstance(loaded, type) else loaded
        if not isinstance(instance, Module):
            msg = f"entry point {entry_point.name!r} does not implement the Module protocol"
            raise ModuleGraphError(msg)
        modules.append(instance)
    return modules


def resolve_modules(modules: Iterable[Module], disabled: Iterable[str] = ()) -> LoadedModules:
    """Order ``modules`` by dependency and drop the disabled ones."""
    installed: dict[str, Module] = {}
    for module in modules:
        if module.name in installed:
            msg = f"module {module.name!r} is installed twice"
            raise ModuleGraphError(msg)
        installed[module.name] = module

    disabled_set = set(disabled)
    unknown = disabled_set - installed.keys()
    if unknown:
        msg = f"cannot disable unknown module(s): {', '.join(sorted(unknown))}"
        raise ModuleGraphError(msg)

    sorter: graphlib.TopologicalSorter[str] = graphlib.TopologicalSorter()
    for name, module in installed.items():
        for dependency in module.depends_on:
            if dependency not in installed:
                msg = f"module {name!r} depends on {dependency!r}, which is not installed"
                raise ModuleGraphError(msg)
            if dependency in disabled_set and name not in disabled_set:
                msg = f"module {name!r} depends on {dependency!r}, which is disabled; disable {name!r} too"
                raise ModuleGraphError(msg)
        sorter.add(name, *module.depends_on)

    try:
        order = list(sorter.static_order())
    except graphlib.CycleError as exc:
        cycle: list[str] = exc.args[1]
        msg = f"module dependency cycle: {' -> '.join(cycle)}"
        raise ModuleGraphError(msg) from exc

    enabled = tuple(installed[name] for name in order if name not in disabled_set)
    return LoadedModules(enabled=enabled, disabled=tuple(sorted(disabled_set)), installed=installed)


def load_modules(disabled: Iterable[str] = ()) -> LoadedModules:
    return resolve_modules(discover_modules(), disabled)
