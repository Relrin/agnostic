"""Service accounts: names, expiry, privileged scopes, token rotation and the CLI equivalent."""

from datetime import UTC, datetime, timedelta

import pytest

from agnostic_service_accounts.domain.accounts import (
    GatewayToken,
    InvalidServiceAccountError,
    NativeToken,
    ServiceAccount,
    check_name,
    cli_command,
    curl_sample,
    display_prefix,
    expires_at,
    hash_token,
    is_privileged,
    isolation_note,
    looks_like_gateway_token,
    new_gateway_token,
    sample_agent,
    source_label,
    subject_of,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def account(**changes: object) -> ServiceAccount:
    values: dict[str, object] = {
        "id": "sac_1",
        "name": "zendesk-bridge",
        "description": "Forwards Zendesk tickets to the support agents.",
        "scope_source": "custom",
        "role_id": None,
        "scopes": ("agents:support-triage:run", "sessions:read"),
        "instance_ids": ("ins_prod",),
        "forwards_user_id": True,
        "created_by": "usr_dana",
        "created_by_name": "Dana Okafor",
        "created_at": NOW,
        "expires_at": None,
    }
    values.update(changes)
    return ServiceAccount(**values)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("name", ["zendesk-bridge", "ci-evals", "a", "x" * 63, "bot2"])
def test_valid_names(name: str) -> None:
    assert check_name(f" {name} ") == name


@pytest.mark.parametrize("name", ["", "Zendesk", "-bot", "bot-", "sa:bot", "slack_bot", "x" * 64, "two words"])
def test_invalid_names(name: str) -> None:
    with pytest.raises(InvalidServiceAccountError):
        _ = check_name(name)


def test_principal_and_subject() -> None:
    sa = account()
    assert sa.principal == "sa:zendesk-bridge"
    assert sa.subject == subject_of("zendesk-bridge") == "svc_zendesk-bridge"


def test_expiry_choices() -> None:
    assert expires_at("90d", NOW) == NOW + timedelta(days=90)
    assert expires_at("30d", NOW) == NOW + timedelta(days=30)
    assert expires_at("365d", NOW) == NOW + timedelta(days=365)
    assert expires_at("never", NOW) is None
    with pytest.raises(InvalidServiceAccountError):
        _ = expires_at("7d", NOW)


def test_expiry_warning_and_usability() -> None:
    assert account(expires_at=None).expiry_warning(NOW)  # no expiry: amber
    assert account(expires_at=NOW + timedelta(days=10)).expiry_warning(NOW)
    assert not account(expires_at=NOW + timedelta(days=60)).expiry_warning(NOW)
    expired = account(expires_at=NOW - timedelta(seconds=1))
    assert expired.expired(NOW)
    assert not expired.usable(NOW)
    assert not account().delete(NOW).usable(NOW)


@pytest.mark.parametrize(
    ("scope", "privileged"),
    [
        ("sessions:write", True),
        ("sessions:delete", True),
        ("agent_os:admin", True),
        ("service_accounts:read", True),
        ("service_accounts:manage", True),
        ("agents:support-triage:run", False),
        ("sessions:read", False),
        ("evals:write", True),
    ],
)
def test_privileged_scopes(scope: str, privileged: bool) -> None:
    assert is_privileged(scope) is privileged


def test_gateway_token_format_and_hash() -> None:
    token = new_gateway_token()
    assert looks_like_gateway_token(token)
    assert len(token) == len("agn_pat_") + 32
    assert display_prefix(token) == token[:12]
    assert not looks_like_gateway_token("agno_pat_" + "x" * 32)
    assert hash_token("pepper", token) != hash_token("other", token)
    assert len(hash_token("pepper", token)) == 64


def gateway_token() -> GatewayToken:
    return GatewayToken(
        id="sgt_1", account_id="sac_1", prefix="agn_pat_abcd", token_hash="h", status="active", created_at=NOW
    )


def test_gateway_rotation_keeps_the_old_token_for_a_day() -> None:
    old = gateway_token().rotate_out(NOW)
    assert old.grace_until == NOW + timedelta(hours=24)
    assert old.revoke_reason == "rotated"
    assert old.valid(NOW + timedelta(hours=23))
    assert not old.valid(NOW + timedelta(hours=24))
    assert old.current_status(NOW + timedelta(hours=25)) == "revoked"
    settled = old.settle(NOW + timedelta(hours=25))
    assert (settled.status, settled.revoked_at) == ("revoked", NOW + timedelta(hours=24))
    assert old.settle(NOW) == old


def test_gateway_revoke_and_expire() -> None:
    revoked = gateway_token().revoke(NOW, "revoked")
    assert not revoked.valid(NOW)
    assert revoked.revoke(NOW + timedelta(hours=1), "again") == revoked
    expired = gateway_token().expire(NOW)
    assert (expired.status, expired.revoke_reason) == ("expired", "expired")


def test_native_token_observed_from_the_instance() -> None:
    native = NativeToken(
        id="snt_1",
        account_id="sac_1",
        instance_id="ins_prod",
        agentos_sa_id="sa_1",
        token_prefix="agno_pat_7Hq2",
        status="active",
        scopes=("sessions:read",),
        created_at=NOW,
    )
    used = native.observed(last_used_at=NOW, revoked_at=None, expires_at=None, now=NOW)
    assert (used.status, used.last_used_at) == ("active", NOW)
    revoked = native.observed(last_used_at=None, revoked_at=NOW, expires_at=None, now=NOW)
    assert (revoked.status, revoked.last_used_at) == ("revoked", None)
    expired = native.observed(last_used_at=None, revoked_at=None, expires_at=NOW, now=NOW)
    assert expired.status == "expired"
    assert native.revoke(NOW).revoke(NOW + timedelta(hours=1)).revoked_at == NOW


def test_cli_equivalent() -> None:
    command = cli_command(
        "zendesk-bridge",
        instances=["prod-agentos"],
        role=None,
        scopes=["agents:support-triage:run", "sessions:write"],
        expires_in="90d",
        kinds=["native", "gateway"],
        forwards_user_id=True,
    )
    assert command == (
        "agnostic tokens create zendesk-bridge \\\n"
        "  --instance prod-agentos \\\n"
        "  --scopes agents:support-triage:run,sessions:write \\\n"
        "  --expires-in 90d \\\n"
        "  --kind native \\\n"
        "  --kind gateway \\\n"
        "  --forwards-user-id \\\n"
        "  --yes-privileged"
    )
    with_role = cli_command(
        "slack-bot",
        instances=["prod-agentos"],
        role="viewer",
        scopes=["agents:support-triage:run"],
        expires_in="365d",
        kinds=["native"],
    )
    assert "--role viewer \\\n  --extra-scopes agents:support-triage:run" in with_role
    assert "--yes-privileged" not in with_role


def test_labels_samples_and_isolation_notes() -> None:
    assert source_label("custom", None, 6) == "Custom scopes"
    assert source_label("role", "Viewer", 1) == "Access role: Viewer + 1 scope"
    assert source_label("role", "Viewer", 0) == "Access role: Viewer"
    assert sample_agent(["sessions:read", "agents:support-triage:run"]) == "support-triage"
    assert sample_agent(["sessions:read"]) == "<agent-id>"
    sample = curl_sample("https://prod.example/", variable="AGNO_PAT", agent_id="support-triage")
    assert sample.startswith("curl -X POST https://prod.example/agents/support-triage/runs")
    assert "$AGNO_PAT" in sample
    assert "user isolation applies" in isolation_note(account(), ["sessions:read"])
    ci = isolation_note(account(name="ci-evals", forwards_user_id=False), ["approvals:read"])
    assert "owned by sa:ci-evals" in ci
    assert "svc_ci-evals" in ci
    assert "404 on resolve" in ci
