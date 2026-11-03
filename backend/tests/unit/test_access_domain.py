"""Access rules: scope matching, effective scopes, explanations, and built-in role by route (table-driven)."""

from datetime import UTC, datetime, timedelta

import pytest

from agnostic_access.domain.effective import compute_access, explain
from agnostic_access.domain.requests import AccessRequest, InvalidRequestError, check_duration, check_reason
from agnostic_access.domain.roles import (
    BUILT_IN_BY_ID,
    BUILT_IN_ROLES,
    AccessRole,
    Binding,
    InvalidRoleError,
    RoleDraft,
    check_draft,
    compare_versions,
    scope_diff,
)
from agnostic_access.domain.roles import role_slug as slug_of
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


def test_operator_has_the_designed_21_runtime_scopes_and_queue_operate() -> None:
    operator = BUILT_IN_BY_ID["rol_operator"]
    assert len(operator.scopes() - {"queue:operate"}) == 21
    assert "approvals:delete" in operator.scopes()
    assert "components:write" not in operator.scopes()
    assert "queue:operate" in operator.scopes()
    assert "queue:operate" in BUILT_IN_BY_ID["rol_instance_admin"].scopes()
    assert "queue:operate" not in BUILT_IN_BY_ID["rol_builder"].scopes()


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


def test_group_bindings_count_only_for_groups_the_person_is_in() -> None:
    mine = binding("rol_operator", principal_kind="group", principal_id="grp_support", id="bnd_group")
    other = binding("rol_builder", principal_kind="group", principal_id="grp_research", id="bnd_other")
    access = compute_access(
        user_id="usr_maya",
        org_role="member",
        instance_id="ins_prod",
        bindings=(mine, other),
        roles=BUILT_IN_BY_ID,
        require_explicit_bindings=False,
        control_plane_scopes=CP,
        now=NOW,
        groups={"grp_support": "Support AI"},
    )
    assert access.role_names() == ["Operator"]
    grant = access.find("sessions:read", control_plane=False)[0]
    assert (grant.via_group_id, grant.via_group_name) == ("grp_support", "Support AI")
    text = explain(
        "sessions:read",
        access,
        who="Maya",
        instance_label="prod",
        action_label=None,
        roles=BUILT_IN_ROLES,
        elsewhere={},
        is_control_plane=lambda scope: scope in CP,
    ).text
    assert text == "Granted by Operator via Support AI → `sessions:read` on prod."


def test_service_accounts_hold_only_their_bindings() -> None:
    access = compute_access(
        user_id="sac_zendesk",
        org_role=None,
        instance_id="ins_prod",
        bindings=(binding(None, scopes=("agents:support-triage:run",), principal_kind="service_account"),),
        roles=BUILT_IN_BY_ID,
        require_explicit_bindings=True,
        control_plane_scopes=CP,
        now=NOW,
        principal_kind="service_account",
    )
    assert access.runtime_scopes() == {"agents:support-triage:run"}
    assert not access.implicit_full
    denied = explain(
        "org:members:write",
        access,
        who="sa:zendesk-bridge",
        instance_label=None,
        action_label=None,
        roles=BUILT_IN_ROLES,
        elsewhere={},
        is_control_plane=lambda scope: scope in CP,
    )
    assert "service account" in denied.text


def test_role_drafts_are_checked_against_the_catalog() -> None:
    catalogued = {"agents:read", "agents:run", "knowledge:write", "sessions:read"}.__contains__
    draft = RoleDraft(
        name="  Billing   runner ",
        description=" ",
        color="#7DA6FF",
        permissions={"agents": ("read", "run", "run"), "sessions": ("read",), "empty": ()},
        run_scope={"agents": ("billing-agent", " ")},
    )
    checked = check_draft(draft, catalogued=catalogued)
    assert checked.name == "Billing runner"
    assert checked.permissions == {"agents": ("read", "run"), "sessions": ("read",)}
    assert checked.run_scope == {"agents": ("billing-agent",)}
    assert slug_of(checked.name) == "billing-runner"
    with pytest.raises(InvalidRoleError, match="agents:teleport"):
        check_draft(RoleDraft("X", "", "#000000", {"agents": ("teleport",)}), catalogued=catalogued)
    with pytest.raises(InvalidRoleError, match="can run"):
        check_draft(
            RoleDraft("X", "", "#000000", {"agents": ("read",)}, run_scope={"agents": ("a",)}), catalogued=catalogued
        )
    with pytest.raises(InvalidRoleError, match="bindable"):
        check_draft(
            RoleDraft("X", "", "#000000", {"agents": ("read",)}, bindable_instance_ids=()), catalogued=catalogued
        )


def test_scope_diff_and_version_comparison() -> None:
    operator = BUILT_IN_BY_ID["rol_operator"].scopes()
    edited = (operator | {"knowledge:write"}) - {"approvals:delete"}
    diff = scope_diff(operator, edited)
    assert (diff.added, diff.removed) == (("knowledge:write",), ("approvals:delete",))
    assert diff.lines() == [{"op": "add", "text": "knowledge:write"}, {"op": "remove", "text": "approvals:delete"}]
    assert compare_versions("3.1.12", "3.1.0")
    assert not compare_versions("3.0.9", "3.1.0")
    assert compare_versions(None, "3.1.0")


def test_temporary_access_requests_follow_their_lifecycle() -> None:
    request = AccessRequest(
        id="areq_1",
        requester_id="usr_priya",
        instance_id="ins_prod",
        role_id="rol_builder",
        scopes=(),
        reason="Hotfix",
        duration_hours=4,
        status="pending",
        created_at=NOW,
    )
    with pytest.raises(InvalidRequestError, match="own request"):
        request.approve(by="usr_priya", at=NOW, binding_id="bnd_1", note=None)
    approved = request.approve(by="usr_dana", at=NOW, binding_id="bnd_1", note="ok")
    assert approved.expires_at == NOW + timedelta(hours=4)
    with pytest.raises(InvalidRequestError, match="already approved"):
        approved.deny(by="usr_dana", at=NOW, note=None)
    with pytest.raises(InvalidRequestError, match="Only the person"):
        request.cancel(by="usr_dana", at=NOW)
    with pytest.raises(InvalidRequestError, match="at most 168"):
        check_duration(200, max_hours=168)
    with pytest.raises(InvalidRequestError, match="Say why"):
        check_reason("   ")
