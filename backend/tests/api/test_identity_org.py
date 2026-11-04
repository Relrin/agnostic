"""Sign-in, sessions, CSRF, onboarding, invitations and org roles through the HTTP API (SQLite, no Docker)."""

from collections.abc import AsyncIterator

import pytest

from agnostic_kernel.bootstrap import OwnerAccount
from tests.support.stack import OWNER_PASSWORD, Stack, running_stack


@pytest.fixture
async def stack(sqlite_database: str) -> AsyncIterator[Stack]:
    async with running_stack(sqlite_database) as running:
        yield running


async def test_first_run_with_setup_link(stack: Stack) -> None:
    anonymous = stack.client()
    assert (await anonymous.get("/api/v1/onboarding/status")).json() == {
        "org_exists": False,
        "owner_exists": False,
        "org_name": None,
    }
    result = await stack.bootstrap("Localhost Company")
    assert result.setup_url is not None
    assert result.setup_url.startswith("http://agnostic.test/onboarding?token=")
    token = result.setup_url.rsplit("=", 1)[1]

    weak = await anonymous.post(
        "/api/v1/onboarding/complete",
        json={"token": token, "email": "daniel@localhost.company", "display_name": "Daniel", "password": "short"},
    )
    assert weak.status_code == 422
    assert weak.json()["field"] == "password"

    done = await anonymous.post(
        "/api/v1/onboarding/complete",
        json={
            "token": token,
            "org_name": "Localhost Company",
            "email": "Daniel@Localhost.company",
            "display_name": "Daniel Okafor",
            "password": OWNER_PASSWORD,
        },
    )
    assert done.status_code == 200, done.text
    anonymous.headers["X-CSRF-Token"] = done.json()["csrf_token"]
    me = (await anonymous.get("/api/v1/me")).json()
    assert me["email"] == "daniel@localhost.company"
    assert me["org_role"] == "owner"
    org = (await anonymous.get("/api/v1/org")).json()
    assert org["name"] == "Localhost Company"
    assert org["viewer_role"] == "owner"

    reused = await stack.client().post(
        "/api/v1/onboarding/complete",
        json={"token": token, "email": "evan@x.dev", "display_name": "Evan", "password": OWNER_PASSWORD},
    )
    assert reused.status_code == 404
    assert (await stack.client().get("/api/v1/onboarding/status")).json()["owner_exists"] is True


async def test_bootstrap_twice_is_refused(stack: Stack) -> None:
    _ = await stack.owner()
    with pytest.raises(Exception, match="already has an Owner"):
        await stack.bootstrap("Again", OwnerAccount("x@y.dev", "X", OWNER_PASSWORD))


async def test_login_logout_and_csrf(stack: Stack) -> None:
    owner = await stack.owner()
    assert (await stack.client().get("/api/v1/me")).status_code == 401

    no_csrf = stack.client()
    login = await no_csrf.post(
        "/api/v1/auth/login", json={"email": "daniel@localhost.company", "password": OWNER_PASSWORD}
    )
    assert login.status_code == 200
    assert "agnostic_session" in login.cookies
    assert login.json()["user"]["org_role"] == "owner"
    patched = await no_csrf.patch("/api/v1/me", json={"display_name": "Daniel O."})
    assert patched.status_code == 403
    assert patched.json()["code"] == "csrf_failed"

    renamed = await owner.patch("/api/v1/me", json={"display_name": "Daniel O.", "preferences": {"api_hints": True}})
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Daniel O."
    assert renamed.json()["preferences"] == {"api_hints": True}

    sessions = (await owner.get("/api/v1/me/sessions")).json()
    assert len(sessions) == 2
    assert sum(item["current"] for item in sessions) == 1

    assert (await owner.post("/api/v1/auth/logout")).status_code == 204
    assert (await owner.get("/api/v1/me")).status_code == 401


async def test_wrong_password_lockout_and_audit(stack: Stack) -> None:
    owner = await stack.owner()
    attacker = stack.client()
    for _ in range(5):
        wrong = await attacker.post(
            "/api/v1/auth/login", json={"email": "daniel@localhost.company", "password": "nope" * 4}
        )
        assert wrong.status_code == 401
        assert wrong.json()["code"] == "invalid_credentials"
    locked = await attacker.post(
        "/api/v1/auth/login", json={"email": "daniel@localhost.company", "password": OWNER_PASSWORD}
    )
    assert locked.status_code == 429
    assert locked.json()["code"] == "account_locked"
    unknown = await attacker.post(
        "/api/v1/auth/login", json={"email": "nobody@localhost.company", "password": "x" * 12}
    )
    assert unknown.status_code == 401  # same answer as a wrong password

    events = (await owner.get("/api/v1/audit/events", params={"action": "auth.login_failed"})).json()["data"]
    assert len(events) >= 6
    assert events[0]["decision"] == "denied"
    assert "Sign-in failed for" in events[0]["summary"]


async def test_password_reset(stack: Stack) -> None:
    _ = await stack.owner()
    anonymous = stack.client()
    assert (await anonymous.post("/api/v1/auth/password/reset", json={"email": "nobody@x.dev"})).status_code == 202
    assert stack.mailer.sent == []
    assert (
        await anonymous.post("/api/v1/auth/password/reset", json={"email": "daniel@localhost.company"})
    ).status_code == 202
    link = stack.mailer.sent[-1].text.split("reset-password?token=", 1)[1].split()[0]
    confirm = await anonymous.post(
        "/api/v1/auth/password/reset/confirm", json={"token": link, "password": "a brand new passphrase"}
    )
    assert confirm.status_code == 204
    again = await anonymous.post(
        "/api/v1/auth/password/reset/confirm", json={"token": link, "password": "another new passphrase"}
    )
    assert again.status_code == 422
    _ = await stack.sign_in("daniel@localhost.company", "a brand new passphrase")


async def test_invite_accept_and_org_roles(stack: Stack) -> None:
    owner = await stack.owner()
    roles = (await owner.get("/api/v1/access/roles")).json()
    operator = next(role for role in roles if role["slug"] == "operator")
    assert len(operator["scopes"]) == 22  # the 21 AgentOS scopes plus queue:operate
    assert "queue:operate" in operator["scopes"]

    invited = await owner.post(
        "/api/v1/invitations",
        json={"email": "marcus@localhost.company", "org_role": "member", "bindings": [{"role_id": operator["id"]}]},
    )
    assert invited.status_code == 201, invited.text
    accept_url = invited.json()["accept_url"]
    token = accept_url.rsplit("/", 1)[1]
    assert stack.mailer.sent[-1].to == "marcus@localhost.company"
    assert accept_url in stack.mailer.sent[-1].text

    duplicate = await owner.post("/api/v1/invitations", json={"email": "MARCUS@localhost.company"})
    assert duplicate.status_code == 409

    marcus = stack.client()
    preview = (await marcus.get(f"/api/v1/invitations/{token}/preview")).json()
    assert preview == {
        "org_name": "Localhost Company",
        "email": "marcus@localhost.company",
        "org_role": "member",
        "invited_by": "Daniel Okafor",
        "expires_at": preview["expires_at"],
        "has_account": False,
    }
    joined = await marcus.post(
        f"/api/v1/invitations/{token}/accept",
        json={"display_name": "Marcus Chen", "password": "marcus's long password"},
    )
    assert joined.status_code == 200, joined.text
    marcus.headers["X-CSRF-Token"] = joined.json()["csrf_token"]
    me = (await marcus.get("/api/v1/me")).json()
    assert (me["display_name"], me["org_role"]) == ("Marcus Chen", "member")

    # A Member can't invite; the 403 explains why.
    denied = await marcus.post("/api/v1/invitations", json={"email": "jonas@localhost.company"})
    assert denied.status_code == 403
    body = denied.json()
    assert body["code"] == "scope_missing"
    assert body["required_scopes"] == ["org:members:write"]
    assert "Marcus Chen is Member, which doesn't include it" in body["explanation"]

    members = (await owner.get("/api/v1/members")).json()
    assert [m["org_role"] for m in members] == ["owner", "member"]
    maya_id = me["id"]
    promoted = await owner.patch(f"/api/v1/members/{maya_id}", json={"org_role": "administrator"})
    assert promoted.json()["org_role"] == "administrator"
    # The scope cache is invalidated: Marcus can invite right away.
    assert (await marcus.post("/api/v1/invitations", json={"email": "jonas@localhost.company"})).status_code == 201
    # Administrators can't make Owners.
    dana_id = members[0]["user_id"]
    demote = await marcus.patch(f"/api/v1/members/{dana_id}", json={"org_role": "member"})
    assert demote.status_code == 409
    # The last Owner can't be demoted, even by themself.
    last = await owner.patch(f"/api/v1/members/{dana_id}", json={"org_role": "member"})
    assert last.status_code == 409
    assert "at least one Owner" in last.json()["detail"]

    assert (await owner.delete(f"/api/v1/members/{maya_id}")).status_code == 204
    assert (await marcus.get("/api/v1/me")).status_code == 401
    relogin = await stack.client().post(
        "/api/v1/auth/login", json={"email": "marcus@localhost.company", "password": "marcus's long password"}
    )
    assert relogin.status_code == 403
    assert relogin.json()["code"] == "not_a_member"

    actions = [event["action"] for event in (await owner.get("/api/v1/audit/events")).json()["data"]]
    for action in ("invitations.create", "invitations.accept", "members.update", "members.remove", "bindings.create"):
        assert action in actions


async def test_invite_link_without_email(stack: Stack) -> None:
    owner = await stack.owner()
    assert (await owner.get("/api/v1/org")).json()["email_delivery"] is True

    created = await owner.post("/api/v1/invitations", json={"email": "jonas@localhost.company", "delivery": "link"})
    assert created.status_code == 201, created.text
    assert created.json()["email_sent"] is False
    assert stack.mailer.sent == []
    invitation_id = created.json()["invitation"]["id"]
    first = created.json()["accept_url"].rsplit("/", 1)[1]

    renewed = await owner.post(f"/api/v1/invitations/{invitation_id}/link")
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["email_sent"] is False
    assert stack.mailer.sent == []
    second = renewed.json()["accept_url"].rsplit("/", 1)[1]
    anonymous = stack.client()
    assert (await anonymous.get(f"/api/v1/invitations/{first}/preview")).status_code == 404
    assert (await anonymous.get(f"/api/v1/invitations/{second}/preview")).status_code == 200

    resent = await owner.post(f"/api/v1/invitations/{invitation_id}/resend")
    assert resent.json()["email_sent"] is True
    assert stack.mailer.sent[-1].to == "jonas@localhost.company"

    revoked = await owner.delete(f"/api/v1/invitations/{invitation_id}")
    assert revoked.status_code == 204
    assert (await owner.post(f"/api/v1/invitations/{invitation_id}/link")).status_code == 404

    actions = [event["action"] for event in (await owner.get("/api/v1/audit/events")).json()["data"]]
    assert {"invitations.create", "invitations.link", "invitations.resend", "invitations.revoke"} <= set(actions)


async def test_invite_keeps_the_link_when_email_fails(stack: Stack) -> None:
    owner = await stack.owner()
    stack.mailer.failing = True
    created = await owner.post("/api/v1/invitations", json={"email": "jonas@localhost.company"})
    assert created.status_code == 201, created.text
    assert created.json()["email_sent"] is False
    assert created.json()["accept_url"].startswith("http://agnostic.test/invite/")

    stack.mailer.configured = False
    assert (await owner.get("/api/v1/org")).json()["email_delivery"] is False
    unconfigured = await owner.post("/api/v1/invitations", json={"email": "maya@localhost.company"})
    assert unconfigured.json()["email_sent"] is False


async def test_org_settings_and_seats(stack: Stack) -> None:
    owner = await stack.owner()
    updated = await owner.patch(
        "/api/v1/org", json={"name": "Localhost", "seat_limit": 1, "settings": {"require_explicit_bindings": True}}
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert (body["name"], body["seat_limit"], body["settings"]["require_explicit_bindings"]) == ("Localhost", 1, True)
    full = await owner.post("/api/v1/invitations", json={"email": "marcus@localhost.company"})
    assert full.status_code == 409
    assert "seats are taken" in full.json()["detail"]
    event = (await owner.get("/api/v1/audit/events", params={"action": "settings.org.update"})).json()["data"][0]
    assert event["diff"] == {"require_explicit_bindings": {"before": False, "after": True}}
