"""Module loader: discovery, ordering, disabling, failure modes."""

from typing import ClassVar

import pytest

from agnostic_instances.module import InstancesModule
from agnostic_kernel.modules import BaseModule, Module, ModuleGraphError, load_modules, resolve_modules


def make(name: str, *depends_on: str) -> Module:
    class _Module(BaseModule):
        pass

    _Module.name = name
    _Module.depends_on = depends_on
    return _Module()


def test_entry_points_discover_the_installed_modules() -> None:
    loaded = load_modules()
    assert loaded.names() == ["audit", "identity", "instances", "settings", "org", "access", "gateway"]
    assert isinstance(loaded.installed["instances"], InstancesModule)


def test_dependency_order() -> None:
    loaded = resolve_modules([make("gateway", "access", "instances"), make("instances"), make("access", "instances")])
    assert loaded.names() == ["instances", "access", "gateway"]


def test_disable_leaf_module() -> None:
    loaded = resolve_modules([make("a"), make("b", "a")], disabled=["b"])
    assert loaded.names() == ["a"]
    assert loaded.disabled == ("b",)
    assert set(loaded.installed) == {"a", "b"}


@pytest.mark.parametrize(
    ("modules", "disabled", "message"),
    [
        ([make("a"), make("a")], [], "installed twice"),
        ([make("a", "missing")], [], "not installed"),
        ([make("a", "b"), make("b", "a")], [], "cycle"),
        ([make("a"), make("b", "a")], ["a"], "disable 'b' too"),
        ([make("a")], ["ghost"], "unknown module"),
    ],
)
def test_graph_errors(modules: list[Module], disabled: list[str], message: str) -> None:
    with pytest.raises(ModuleGraphError, match=message):
        resolve_modules(modules, disabled)


async def test_base_module_defaults() -> None:
    module = make("plain")
    assert module.settings_model() is None
    assert module.metadata() is None
    assert module.migrations() is None
    for contribution in (
        module.provide(),
        module.routers(),
        module.scopes(),
        module.jobs(),
        module.event_handlers(),
        module.audit_actions(),
        module.search_providers(),
        module.capabilities(),
    ):
        assert list(contribution) == []
    await module.on_startup(None)  # pyright: ignore[reportArgumentType]
    await module.on_shutdown(None)  # pyright: ignore[reportArgumentType]


def test_a_module_contributes_everything_the_contract_needs() -> None:
    instances = InstancesModule()
    assert [s.name for s in instances.scopes()] == ["os:read", "os:write", "os:delete", "os:keys:rotate"]
    jobs: dict[str, str | None] = {j.name: j.periodic for j in instances.jobs()}
    assert jobs["instances.check_health"]
    assert jobs["instances.refresh_snapshots"]
    assert "instances.create" in [a.action for a in instances.audit_actions()]
    assert [spec.root for spec in instances.routers()] == [False, True]  # the JWKS document sits at the root
    migrations = instances.migrations()
    assert migrations is not None
    assert migrations.is_dir()


class _NotAModule:
    name: ClassVar[str] = "nope"


def test_discover_rejects_non_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEntryPoint:
        name = "nope"

        def load(self) -> type:
            return _NotAModule

    def fake_entry_points(group: str) -> list[FakeEntryPoint]:
        assert group == "agnostic.modules"
        return [FakeEntryPoint()]

    monkeypatch.setattr("agnostic_kernel.modules.entry_points", fake_entry_points)
    with pytest.raises(ModuleGraphError, match="does not implement"):
        load_modules()
