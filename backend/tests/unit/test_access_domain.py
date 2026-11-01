"""Access rules: scope matching, effective scopes, explanations, and built-in role by route (table-driven)."""

from datetime import UTC, datetime, timedelta

import pytest

from agnostic_access.domain.effective import compute_access, explain
from agnostic_access.domain.roles import BUILT_IN_BY_ID, BUILT_IN_ROLES, AccessRole, Binding
from agnostic_access.domain.scopes import ADMIN_SCOPE, compress, satisfies, split
from agnostic_gateway.application.proxy import _holds
from agnostic_gateway.domain.policies import DEFAULT_POLICIES, PolicyTable

NOW = datetime(2026, 11, 1, tzinfo=UTC)
CP = frozenset({"org:read", "org:write", "org:members:read", "org:members:write", "os:read", "os:delete", "audit:read"})
TABLE = PolicyTable(DEFAULT_POLICIES)


def binding(role_id: str | None, instance: str | None = "ins_prod", **kwargs: object) -> Binding:
    defaults: dict[str, object] = {
        "id": f"bnd_{role_id}_{instance}",
        "principal_kind": "user",
        "principal_id": "usr_maya",
        "instance_id": instance,
        "role_id": role_id,
        "scopes": (),
        "expires_at": None,
        "reason": None,
        "created_by": "usr_dana",
        "created_at": NOW,
    }
    defaults.update(kwargs)
    return Binding(**defaults)  # type: ignore[arg-type]


def access_for(org_role: str | None, *bindings: Binding, instance: str | None = "ins_prod", explicit: bool = False):
    return compute_access(
        user_id="usr_maya",
        org_role=org_role,
        instance_id=instance,
        bindings=bindings,
        roles=BUILT_IN_BY_ID,
        require_explicit_bindings=explicit,
        control_plane_scopes=CP,
        now=NOW,
    )


@pytest.mark.parametrize(
    ("held", "required", "expected"),
    [
        ("agents:run", "agents:triage:run", True),
        ("agents:*:run", "agents:triage:run", True),
        ("agents:triage:run", "agents:triage:run", True),
        ("agents:other:run", "agents:triage:run", False),
        ("agents:triage:run", "agents:run", False),
        ("agents:*:run", "agents:run", True),
        ("agents:read", "agents:run", False),
        (ADMIN_SCOPE, "sessions:delete", True),
        ("system:read", "config:read", True),
        ("sessions:read", "sessions:delete", False),
    ],
)
def test_satisfies(held: str, required: str, expected: bool) -> None:
    assert satisfies(held, required) is expected


def test_control_plane_scopes_are_exact() -> None:
    assert not satisfies(ADMIN_SCOPE, "org:members:write", control_plane=True)
    assert satisfies("org:members:write", "org:members:write", control_plane=True)
    assert split("org:members:write") == ("org", "members", "write")


def test_compress() -> None:
    assert compress(["agents:run", "agents:triage:run", "agents:read", "agents:read"]) == ["agents:read", "agents:run"]
    assert compress(["agents:triage:run", "sessions:read"]) == ["agents:triage:run", "sessions:read"]
    assert compress(["sessions:read", ADMIN_SCOPE]) == [ADMIN_SCOPE]


def test_operator_has_the_designed_21_scopes() -> None:
    operator = BUILT_IN_BY_ID["rol_operator"]
    assert len(operator.scopes()) == 21
    assert "approvals:delete" in operator.scopes()
    assert "components:write" not in operator.scopes()


ROLES = ("instance-admin", "operator", "builder", "viewer", "auditor")
ROUTES = [
    # method, path, instance-admin, operator, builder, viewer, auditor
    ("GET", "/agents", 1, 1, 1, 1, 0),
    ("GET", "/config", 1, 1, 1, 1, 1),
    ("POST", "/agents/support-triage/runs", 1, 1, 1, 0, 0),
    ("GET", "/agents/support-triage/runs/run_1", 1, 1, 1, 0, 0),
    ("POST", "/agents/support-triage/runs/run_1/continue", 1, 1, 1, 0, 0),
    ("GET", "/sessions", 1, 1, 1, 1, 1),
    ("DELETE", "/sessions/ses_1", 1, 0, 0, 0, 0),
    ("PATCH", "/sessions/ses_1", 1, 0, 1, 0, 0),
    ("POST", "/approvals/apv_1/resolve", 1, 1, 0, 0, 0),
    ("DELETE", "/approvals/apv_1", 1, 1, 0, 0, 0),
    ("POST", "/components", 1, 0, 1, 0, 0),
    ("POST", "/components/c1/configs/3/set-current", 1, 0, 1, 0, 0),
    ("POST", "/knowledge/content", 1, 0, 1, 0, 0),
    ("POST", "/databases/prod-db/migrate", 1, 0, 0, 0, 0),
    ("GET", "/queue/stats", 1, 0, 0, 0, 0),
    ("GET", "/traces/tr_1", 1, 1, 1, 1, 1),
    ("POST", "/schedules/s1/trigger", 1, 1, 1, 0, 0),
    ("GET", "/filesystem/files", 1, 0, 1, 1, 0),
    ("GET", "/brand-new-endpoint", 1, 0, 0, 0, 0),
]


@pytest.mark.parametrize(("method", "path", "allowed"), [(m, p, tuple(a)) for m, p, *a in ROUTES])
def test_built_in_role_by_route(method: str, path: str, allowed: tuple[int, ...]) -> None:
    policy, params = TABLE.match(method, path)
    required = policy.required(params)
    for role_slug, expected in zip(ROLES, allowed, strict=True):
        role_id = f"rol_{role_slug.replace('-', '_')}"
        runtime = access_for("member", binding(role_id)).runtime_scopes()
        got = all(_holds(runtime, scope, list_filter=policy.list_filter) for scope in required)
        assert got is bool(expected), f"{role_slug} {method} {path} needs {required}"


def test_implicit_full_access_and_explicit_bindings() -> None:
    assert access_for("owner").runtime_scopes() == {ADMIN_SCOPE}
    assert access_for("administrator").role_names() == ["Full access"]
    assert access_for("member").runtime_scopes() == frozenset()
    assert access_for("owner", explicit=True).runtime_scopes() == frozenset()
    assert "org:members:write" in access_for("owner", explicit=True).control_plane_scopes()
    assert "os:delete" not in access_for("administrator").control_plane_scopes()
    assert access_for(None, binding("rol_viewer")).grants == ()  # non-members get nothing


def test_bindings_respect_instance_expiry_and_bindable() -> None:
    other = access_for("member", binding("rol_viewer", "ins_staging"))
    assert other.runtime_scopes() == frozenset()
    everywhere = access_for("member", binding("rol_viewer", None))
    assert "sessions:read" in everywhere.runtime_scopes()
    expired = access_for("member", binding("rol_viewer", expires_at=NOW - timedelta(minutes=1)))
    assert expired.runtime_scopes() == frozenset()
    restricted = AccessRole(
        id="rol_custom",
        slug="custom",
        name="Prod only",
        description="",
        color="",
        kind="custom",
        permissions={"agents": ("read", "run")},
        run_scope={"agents": ("billing-agent",)},
        bindable_instance_ids=("ins_prod",),
    )
    assert restricted.scopes() == {"agents:read", "agents:billing-agent:run"}
    roles = {**BUILT_IN_BY_ID, restricted.id: restricted}
    staging = compute_access(
        user_id="usr_maya",
        org_role="member",
        instance_id="ins_staging",
        bindings=[binding("rol_custom", None)],
        roles=roles,
        require_explicit_bindings=False,
        control_plane_scopes=CP,
        now=NOW,
    )
    assert staging.runtime_scopes() == frozenset()
    direct = access_for("member", binding(None, scopes=("agents:billing-agent:run",)))
    assert direct.role_names() == ["Direct grant"]


def test_explanations() -> None:
    marcus = access_for("member", binding("rol_operator"))
    staging = access_for("member", binding("rol_builder", "ins_staging"), instance="ins_staging")
    denied = explain(
        "components:write",
        marcus,
        who="Marcus",
        instance_label="prod-agentos",
        action_label="Publish support-triage",
        roles=BUILT_IN_ROLES,
        elsewhere={"staging-agentos": staging},
        is_control_plane=CP.__contains__,
    )
    assert not denied.allowed
    assert denied.text == (
        "Publish support-triage needs `components:write` on prod-agentos. Marcus has Operator there, which doesn't "
        "include it. Builder has it on staging-agentos."
    )
    allowed = explain(
        "approvals:write",
        marcus,
        who="Marcus",
        instance_label="prod-agentos",
        action_label=None,
        roles=BUILT_IN_ROLES,
        elsewhere={},
        is_control_plane=CP.__contains__,
    )
    assert allowed.allowed
    assert allowed.text == "Granted by Operator → `approvals:write` on prod-agentos."
    nobody = explain(
        "sessions:read",
        access_for("member"),
        who="Jonas",
        instance_label="prod-agentos",
        action_label="GET /sessions",
        roles=BUILT_IN_ROLES,
        elsewhere={},
        is_control_plane=CP.__contains__,
    )
    assert nobody.text.startswith("GET /sessions needs `sessions:read` on prod-agentos. Jonas has no access there.")
    org = explain(
        "os:delete",
        access_for("administrator", instance=None),
        who="Sam",
        instance_label=None,
        action_label="Delete instance",
        roles=BUILT_IN_ROLES,
        elsewhere={},
        is_control_plane=CP.__contains__,
    )
    assert (
        org.text == "Delete instance needs `os:delete`. Sam is Administrator, which doesn't include it. Owners have it."
    )
